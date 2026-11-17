import asyncio
import importlib.util
from pathlib import Path
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

SOURCE=Path(__file__).resolve().parents[1]/'workbench-tools/drone-disarmed-observation.py'
spec=importlib.util.spec_from_file_location('disarmed_probe',SOURCE)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class Startup:
    async def connect(self): self.startup_called=True
    async def stream(self,name,generator):
        self.streamed=[value async for value in generator]
    def check_startup_processes(self): self.process_checks+=1
    def set_phase(self,*args): self.phase=args[0]
    async def setpoint(self,position,**kwargs):
        self.sent.append((position,kwargs))
        self.reference={'position':position,**kwargs}
        if len(self.sent)==self.lose_after:self.telemetry['armed']=True


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    def instance(self):
        instance=probe.collector_type(Startup)()
        instance.report={};instance.telemetry={'armed':False,'landed':'ON_GROUND'}
        instance.sent=[];instance.lose_after=-1;instance.process_checks=0
        instance.pose={'position':[5.,0.,.2]};instance.observer=types.SimpleNamespace(simulation_s=10.)
        async def native(module,*args):
            return {'exit_code':0,'raw':'TOPIC: '+args[0] if module=='listener' and args[0]=='offboard_control_mode' else '', 'command':[module,*args]}
        instance.native=AsyncMock(side_effect=native)
        return instance

    async def test_only_finite_setpoints_and_log_commands_no_motion_mode(self):
        instance=self.instance()
        with patch.object(probe.asyncio,'sleep',new=AsyncMock()):
            await instance.connect()
        self.assertEqual(len(instance.sent),18)
        self.assertEqual([call.args[0] for call in instance.native.await_args_list].count('logger'),3)
        self.assertTrue(instance.report['disarmed_observation']['collection_completed'])
        rows=instance.report['disarmed_observation']['snapshots']
        self.assertEqual(sum(row['topic_observed'] for row in rows),3)
        self.assertTrue(all(not row['topic_observed'] for row in rows if row['topic']=='position_control_handoff'))
        self.assertEqual(instance.report['disarmed_observation']['candidate_adoption'],'not_proven')
        self.assertFalse(instance.report['disarmed_observation']['offboard_started'])

    async def test_lost_disarmed_state_stops_sending_and_stops_logger(self):
        instance=self.instance();instance.lose_after=3
        with patch.object(probe.asyncio,'sleep',new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError,'Disarmed observation lost'):
                await instance.connect()
        self.assertEqual(len(instance.sent),3)
        self.assertEqual(instance.native.await_args_list[-1].args,('logger','off'))
        self.assertFalse(instance.report['disarmed_observation']['collection_completed'])

    def test_armed_unknown_does_not_pass_but_change_only_callback_age_is_not_heartbeat(self):
        instance=self.instance()
        for armed in [None,True]:
            instance.telemetry['armed']=armed
            with self.assertRaises(RuntimeError):instance.require_disarmed()
        instance.telemetry['armed']=False;instance.armed_received_s=time.monotonic()-60
        instance.require_disarmed()
        self.assertGreater(instance.report['armed_stream_emission_ages_s'][-1],59)

    async def test_no_motion_recovery(self):
        instance=self.instance()
        with self.assertRaisesRegex(RuntimeError,'No motion recovery'):
            await instance.recover('fault')
        for method in (instance.land,instance.return_home):
            with self.assertRaises(RuntimeError):await method()
        self.assertEqual(instance.sent,[])

    async def test_explicit_disarmed_mode_request_is_stopped_without_arm_api(self):
        instance=self.instance();instance.request_offboard=True
        offboard=types.SimpleNamespace(start=AsyncMock(),stop=AsyncMock())
        instance.drone=types.SimpleNamespace(offboard=offboard) # deliberately no arm/action API
        with patch.object(probe.asyncio,'sleep',new=AsyncMock()):await instance.connect()
        offboard.start.assert_awaited_once();offboard.stop.assert_awaited_once()
        self.assertTrue(instance.report['disarmed_observation']['offboard_stop_returned'])
        self.assertEqual(len(instance.sent),18)

    async def test_lost_armed_stream_does_not_issue_mode_stop_on_cached_false(self):
        instance=self.instance();instance.request_offboard=True
        offboard=types.SimpleNamespace(start=AsyncMock(),stop=AsyncMock())
        instance.drone=types.SimpleNamespace(offboard=offboard)
        original=instance.setpoint
        async def ending(*args,**kwargs):
            await original(*args,**kwargs)
            if len(instance.sent)==8:instance.armed_stream_ended=True
        instance.setpoint=ending
        with patch.object(probe.asyncio,'sleep',new=AsyncMock()):
            with self.assertRaises(RuntimeError):await instance.connect()
        offboard.start.assert_awaited_once();offboard.stop.assert_not_awaited()
        self.assertEqual(instance.native.await_args_list[-1].args,('logger','off'))

    async def test_pending_rpc_times_out_and_stops_logger(self):
        instance=self.instance()
        async def pending(*args,**kwargs):await asyncio.Future()
        instance.setpoint=pending
        with patch.object(probe,'SETPOINT_TIMEOUT_S',.01):
            with self.assertRaises(asyncio.TimeoutError):await instance.connect()
        self.assertEqual(instance.native.await_args_list[-1].args,('logger','off'))
        self.assertFalse(instance.report['disarmed_observation']['collection_completed'])

    async def test_terminated_armed_stream_cannot_reuse_cached_false(self):
        instance=self.instance()
        async def values():yield False
        await instance.stream('armed',values())
        with self.assertRaises(RuntimeError):instance.require_disarmed()

    async def test_cancelled_parent_cleanup_still_reaps_sdk_and_records_runtime_error(self):
        parent_finally=asyncio.Event()
        async def parent():
            try:await asyncio.sleep(.001)
            finally:
                parent_finally.set()
                await asyncio.Future()
        task=asyncio.create_task(parent())
        await parent_finally.wait()
        with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(task,.001)
        flight=types.SimpleNamespace(tasks=[],drone=types.SimpleNamespace(_server_process=types.SimpleNamespace(poll=lambda:None)),close_mavsdk=AsyncMock())
        runtime=types.SimpleNamespace(close=lambda:(_ for _ in ()).throw(OSError('close failed')))
        errors=await probe.close_owned(flight,runtime)
        flight.close_mavsdk.assert_awaited_once()
        self.assertEqual(len(errors),1)
        self.assertIn('close failed',errors[0])

    async def test_timestamp_wrapper_keeps_original_stream_values(self):
        instance=self.instance()
        async def values():
            yield False
            yield True
        await instance.stream('armed',values())
        self.assertEqual(instance.streamed,[False,True])
        self.assertIsNotNone(instance.armed_received_s)
        instance.telemetry['armed']=False
        with self.assertRaises(RuntimeError):instance.require_disarmed()


if __name__=='__main__':unittest.main()
