"""Source-step force ownership tests; native fixture is a single 1kg free body."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cooperation_physical_faults import ForceImpulse

try:
    import mujoco
except ImportError:
    mujoco = None


def context(**updates):
    return dict(world_session_id='world-1',episode_id='episode-1',task_id='task-1',
                native_goal_uuid='ab'*16,stage='car_to_delivery',**updates)


def event(identity='pulse-1',**updates):
    return {**context(),'event_id':identity,'body_name':'cargo',
            'force_world_n':[10.,0.,0.],'duration_source_s':.025,**updates}


class Model:
    opt=NS(timestep=.01)
    def body(self,name):return NS(id={'world':0,'cargo':1,'other':2}[name])


def data():
    return NS(time=0.,xfrc_applied=[[0.]*6,[2.,3.,4.,7.,8.,9.],[5.,6.,7.,8.,9.,10.]])


class SourceImpulseTests(unittest.TestCase):
    def setUp(self):
        self.model,self.data=Model(),data()
        self.fault=ForceImpulse(self.model,self.data)

    def step(self,amount=.01):
        self.fault.before_step(context())
        self.data.time+=amount
        return self.fault.after_step()

    def test_actual_source_steps_ignore_wall_time_and_last_fraction_has_exact_impulse(self):
        self.fault.offer(event(),context=context());baseline=copy.deepcopy(self.data.xfrc_applied)
        for wall,expected_force in [(0.,12.),(10000.,12.),(-200.,7.)]:
            with patch('time.monotonic',return_value=wall):
                self.fault.before_step(context())
                self.assertAlmostEqual(self.data.xfrc_applied[1][0],expected_force)
                self.data.time+=.01;self.fault.after_step()
        result=self.fault.status('pulse-1')
        self.assertEqual(result['state'],'completed')
        self.assertAlmostEqual(result['impulse_world_ns'][0],.25)
        self.assertAlmostEqual(result['effective_duration_source_s'],.025)
        self.assertAlmostEqual(result['source_window_s'],.03)
        self.assertAlmostEqual(result['last_step']['last_step_fraction'],.5)
        self.assertTrue(result['last_step']['partial_step_averaging'])
        self.assertEqual(self.data.xfrc_applied,baseline)

    def test_nonprogressing_and_duplicate_calls_never_count_or_add_force_twice(self):
        self.fault.offer(event(),context=context())
        self.fault.before_step(context());prepared=copy.deepcopy(self.data.xfrc_applied)
        self.fault.before_step(context());self.assertEqual(self.data.xfrc_applied,prepared)
        with self.assertRaisesRegex(ValueError,'positive native source progression'):self.fault.after_step()
        self.assertEqual(self.fault.status('pulse-1')['impulse_world_ns'],[0.,0.,0.])
        self.data.time+=.01;self.fault.after_step();result=self.fault.capture_state()
        self.fault.after_step();self.assertEqual(self.fault.capture_state(),result)
        # before_step also reconciles a completed step if after_step was omitted.
        self.fault.before_step(context());self.data.time+=.01;self.fault.before_step(context())
        self.assertAlmostEqual(self.fault.status('pulse-1')['impulse_world_ns'][0],.2)
        self.assertAlmostEqual(self.data.xfrc_applied[1][0],7.)

    def test_duplicates_remain_idempotent_after_completion_and_conflicts_are_local(self):
        first=self.fault.offer(event(),context=context())
        self.assertEqual(self.fault.offer(event(),context=context()),first)
        with self.assertRaisesRegex(ValueError,'already bound'):
            self.fault.offer(event(force_world_n=[99.,0.,0.]),context=context())
        self.assertEqual(self.fault.status('pulse-1'),first)
        for _ in range(3):self.step()
        completed=self.fault.status('pulse-1')
        self.assertEqual(self.fault.offer(event(),context=context()),completed)
        self.step();self.assertEqual(self.fault.status('pulse-1'),completed)

    def test_invalid_force_body_identity_or_duration_does_not_remove_a_valid_event(self):
        self.fault.offer(event(),context=context());before=self.fault.capture_state()
        invalid=[event('bad',force_world_n=[float('nan'),0.,0.]),event('bad',force_world_n=[True,0.,0.]),
                 event('bad',force_world_n=[1.,2.]),event('bad',duration_source_s=0.),
                 event('bad',duration_source_s=float('inf')),event('bad',body_name='missing'),
                 event('bad',body_name='world'),event('bad',world_session_id='another-world'),
                 event('bad',episode_id='other'),event('bad',task_id='other'),
                 event('bad',native_goal_uuid='not-an-accepted-goal'),event('bad',stage='arm_grasp')]
        for bad in invalid:
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.fault.offer(bad,context=context())
            self.assertEqual(self.fault.capture_state(),before)
        self.step();self.assertAlmostEqual(self.fault.status('pulse-1')['impulse_world_ns'][0],.1)

    def test_overlapping_events_and_other_wrenches_keep_independent_ownership(self):
        self.fault.offer(event(),context=context())
        self.fault.offer(event('pulse-2',force_world_n=[0.,20.,0.],duration_source_s=.01),context=context())
        baseline=copy.deepcopy(self.data.xfrc_applied)
        self.fault.before_step(context())
        self.assertEqual(self.data.xfrc_applied[1],[12.,23.,4.,7.,8.,9.])
        # A different owner adds another force while ours is applied.
        self.data.xfrc_applied[1][0]+=4.;self.data.xfrc_applied[1][2]+=5.
        self.data.time+=.01;self.fault.after_step()
        baseline[1][0]+=4.;baseline[1][2]+=5.
        self.assertEqual(self.data.xfrc_applied,baseline)
        self.assertEqual(self.fault.status('pulse-2')['impulse_world_ns'],[0.,.2,0.])
        self.fault.before_step(context());self.fault.dearm('pulse-1')
        self.assertEqual(self.data.xfrc_applied,baseline)

    def test_dearm_one_prepared_event_preserves_another_and_counts_no_unstepped_force(self):
        self.fault.offer(event(),context=context())
        self.fault.offer(event('pulse-2',force_world_n=[0.,20.,0.]),context=context())
        self.fault.before_step(context());self.fault.dearm('pulse-1')
        self.assertEqual(self.data.xfrc_applied[1],[2.,23.,4.,7.,8.,9.])
        self.data.time+=.01;self.fault.after_step()
        self.assertEqual(self.fault.status('pulse-1')['impulse_world_ns'],[0.,0.,0.])
        self.assertEqual(self.fault.status('pulse-1')['state'],'dearmed')
        self.assertEqual(self.fault.status('pulse-2')['impulse_world_ns'],[0.,.2,0.])

    def test_changed_owner_withdraws_prepared_force_without_rebinding_the_event(self):
        self.fault.offer(event(),context=context());self.fault.before_step(context())
        self.fault.before_step({**context(),'native_goal_uuid':'cd'*16})
        self.assertEqual(self.data.xfrc_applied[1],[2.,3.,4.,7.,8.,9.])
        self.assertEqual(self.fault.status('pulse-1')['state'],'dearmed')
        self.assertEqual(self.fault.status('pulse-1')['impulse_world_ns'],[0.,0.,0.])

    def test_dearm_after_a_real_step_accounts_for_the_actual_impulse(self):
        self.fault.offer(event(),context=context());self.fault.before_step(context())
        self.data.time+=.01;self.fault.dearm()
        self.assertAlmostEqual(self.fault.status('pulse-1')['impulse_world_ns'][0],.1)
        self.assertEqual(self.fault.status('pulse-1')['state'],'dearmed')
        self.assertEqual(self.data.xfrc_applied[1],[2.,3.,4.,7.,8.,9.])

    def test_json_active_state_and_native_force_continue_without_double_application(self):
        self.fault.offer(event(),context=context());self.step();self.fault.before_step(context())
        saved=json.loads(json.dumps(self.fault.capture_state()))
        clone_data=copy.deepcopy(self.data);clone=ForceImpulse(self.model,clone_data)
        before=copy.deepcopy(clone_data.xfrc_applied)
        clone.restore_state(saved,context=context(),wrench_included=True)
        self.assertEqual(clone_data.xfrc_applied,before)
        for fault,state in ((self.fault,self.data),(clone,clone_data)):
            state.time+=.01;fault.after_step();fault.before_step(context())
            state.time+=.01;fault.after_step()
        self.assertEqual(clone.capture_state(),self.fault.capture_state())
        self.assertEqual(clone_data.xfrc_applied,self.data.xfrc_applied)
        self.assertAlmostEqual(clone.status('pulse-1')['impulse_world_ns'][0],.25)

    def test_app_only_restore_readds_once_and_changed_context_removes_only_saved_force(self):
        self.fault.offer(event(),context=context());self.fault.before_step(context())
        saved=self.fault.capture_state()
        clone_data=data();clone=ForceImpulse(self.model,clone_data)
        clone.restore_state(saved,context=context(),wrench_included=False)
        self.assertEqual(clone_data.xfrc_applied,self.data.xfrc_applied)
        stale_data=copy.deepcopy(self.data);stale=ForceImpulse(self.model,stale_data)
        stale.restore_state(saved,context={**context(),'episode_id':'new-episode'},wrench_included=True)
        self.assertEqual(stale_data.xfrc_applied[1],[2.,3.,4.,7.,8.,9.])
        self.assertEqual(stale.status('pulse-1')['state'],'dearmed')
        self.assertEqual(stale.status('pulse-1')['impulse_world_ns'],[0.,0.,0.])

    def test_invalid_restored_duration_preserves_existing_state_and_native_wrenches(self):
        self.fault.offer(event('existing'),context=context());self.step()
        before=self.fault.capture_state();baseline=copy.deepcopy(self.data.xfrc_applied)
        for elapsed,window in ((.025,.025),(1.,1.),(.01,.005)):
            with self.subTest(elapsed=elapsed,window=window):
                donor=ForceImpulse(self.model,self.data)
                donor.offer(event('invalid'),context=context())
                saved=donor.capture_state();record=saved['events']['invalid']
                record['effective_duration_source_s']=elapsed;record['source_window_s']=window
                with self.assertRaisesRegex(ValueError,'force duration'):
                    self.fault.restore_state(saved,context=context(),wrench_included=False)
                self.assertEqual(self.fault.capture_state(),before)
                self.assertEqual(self.data.xfrc_applied,baseline)

    def test_restored_pending_fraction_must_match_remaining_duration_before_any_mutation(self):
        self.fault.offer(event(),context=context());self.fault.before_step(context())
        saved=self.fault.capture_state();pending=saved['pending']['contributions']['pulse-1']
        pending.update(fraction=.25,force_world_n=[2.5,0.,0.])
        target_data=data();target=ForceImpulse(self.model,target_data)
        target.offer(event('existing'),context=context())
        before=target.capture_state();baseline=copy.deepcopy(target_data.xfrc_applied)
        with self.assertRaisesRegex(ValueError,'remaining interval'):
            target.restore_state(saved,context=context(),wrench_included=False)
        self.assertEqual(target.capture_state(),before)
        self.assertEqual(target_data.xfrc_applied,baseline)

    def test_nonpositive_remaining_never_injects_negative_force_or_affects_another_event(self):
        self.fault.offer(event('invalid'),context=context())
        self.fault.offer(event('valid',force_world_n=[0.,20.,0.]),context=context())
        self.fault.events['invalid']['effective_duration_source_s']=1.
        self.fault.before_step(context())
        self.assertEqual(self.data.xfrc_applied[1],[2.,23.,4.,7.,8.,9.])
        self.assertEqual(self.fault.status('invalid')['state'],'dearmed')
        self.assertEqual(self.fault.status('invalid')['reason'],'invalid_remaining_source_duration')
        self.data.time+=.01;self.fault.after_step()
        self.assertEqual(self.fault.status('invalid')['impulse_world_ns'],[0.,0.,0.])
        self.assertEqual(self.fault.status('valid')['impulse_world_ns'],[0.,.2,0.])
        self.assertEqual(self.data.xfrc_applied[1],[2.,3.,4.,7.,8.,9.])
        self.fault.events['valid']['effective_duration_source_s']=.025
        self.fault.before_step(context())
        self.assertEqual(self.fault.status('valid')['state'],'completed')
        self.assertEqual(self.data.xfrc_applied[1],[2.,3.,4.,7.,8.,9.])

    def test_late_reconciliation_reports_actual_overrun_instead_of_clipping_the_impulse(self):
        self.fault.offer(event(),context=context());self.fault.before_step(context())
        self.data.time+=.03;self.fault.after_step()
        result=self.fault.status('pulse-1')
        self.assertEqual(result['state'],'overrun')
        self.assertAlmostEqual(result['impulse_world_ns'][0],.3)
        self.assertEqual(self.data.xfrc_applied[1],[2.,3.,4.,7.,8.,9.])

    def test_zero_force_is_a_real_sham_with_source_duration_but_no_impulse(self):
        self.fault.offer(event(force_world_n=[0.,0.,0.]),context=context())
        for _ in range(3):self.step()
        result=self.fault.status('pulse-1')
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['impulse_world_ns'],[0.,0.,0.])
        self.assertAlmostEqual(result['effective_duration_source_s'],.025)


@unittest.skipIf(mujoco is None,'MuJoCo is available only in the existing native planning environment')
class NativeImpulseTests(unittest.TestCase):
    def test_single_free_body_receives_measured_force_impulse_and_preserves_baseline(self):
        model=mujoco.MjModel.from_xml_string('''<mujoco><option timestep=".01" gravity="0 0 0"/>
          <worldbody><body name="cargo"><freejoint/><geom type="box" size=".01 .01 .01" mass="1"/>
          </body></worldbody></mujoco>''')
        state=mujoco.MjData(model);body=model.body('cargo').id
        state.xfrc_applied[body,0]=3.
        fault=ForceImpulse(model,state)
        fault.offer(event(force_world_n=[2.,0.,0.]),context=context())
        for _ in range(3):
            fault.before_step(context());mujoco.mj_step(model,state);fault.after_step()
        self.assertAlmostEqual(fault.status('pulse-1')['impulse_world_ns'][0],.05,places=12)
        self.assertAlmostEqual(state.qvel[0],3.*.03+.05,places=12)
        self.assertAlmostEqual(state.xfrc_applied[body,0],3.,places=12)
        self.assertAlmostEqual(state.time,.03,places=12)
        self.assertEqual(fault.status('pulse-1')['state'],'completed')

    def test_native_integration_snapshot_retains_force_once_and_new_owner_dearms_it(self):
        import numpy as np
        model=mujoco.MjModel.from_xml_string('''<mujoco><option timestep=".01" gravity="0 0 0"/>
          <worldbody><body name="cargo"><freejoint/><geom type="box" size=".01 .01 .01" mass="1"/>
          </body></worldbody></mujoco>''')
        source=mujoco.MjData(model);body=model.body('cargo').id
        source.xfrc_applied[body,0]=3.
        fault=ForceImpulse(model,source);fault.offer(event(force_world_n=[2.,0.,0.]),context=context())
        fault.before_step(context());mujoco.mj_step(model,source);fault.after_step()
        fault.before_step(context())
        saved=json.loads(json.dumps(fault.capture_state()))
        spec=int(mujoco.mjtState.mjSTATE_INTEGRATION)
        native=np.empty(mujoco.mj_stateSize(model,spec));mujoco.mj_getState(model,source,native,spec)
        resumed=mujoco.MjData(model);mujoco.mj_setState(model,resumed,native,spec)
        resumed_fault=ForceImpulse(model,resumed)
        resumed_fault.restore_state(saved,context=context(),wrench_included=True)
        self.assertEqual(resumed.xfrc_applied[body,0],5.)
        mujoco.mj_step(model,resumed);resumed_fault.after_step()
        self.assertAlmostEqual(resumed.qvel[0],.1,places=12)
        self.assertAlmostEqual(resumed_fault.status('pulse-1')['impulse_world_ns'][0],.04,places=12)
        stale=mujoco.MjData(model);mujoco.mj_setState(model,stale,native,spec)
        stale_fault=ForceImpulse(model,stale)
        stale_fault.restore_state(saved,context={**context(),'world_session_id':'new-world'},wrench_included=True)
        self.assertEqual(stale.xfrc_applied[body,0],3.)
        mujoco.mj_step(model,stale)
        self.assertAlmostEqual(stale.qvel[0],.08,places=12)
        self.assertEqual(stale_fault.status('pulse-1')['state'],'dearmed')


if __name__=='__main__':unittest.main()
