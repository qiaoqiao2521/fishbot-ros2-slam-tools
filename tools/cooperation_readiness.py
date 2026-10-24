"""Native lifecycle readiness and opt-in static AMCL branch initialization.

Readiness.update_lifecycle owns query cadence, pending requests and timeouts.
The R2 adapter requests no-motion updates; neither adapter dispatches motion.
"""
import importlib.util
import copy
import logging
import math
from numbers import Real
from pathlib import Path
import threading
import time


REQUIRED_NODES=('docking_server','bt_navigator')
SOURCE=Path(__file__).resolve().parents[1]/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/wait_ready.py'


def _load_runtime():
    spec=importlib.util.spec_from_file_location('cooperation_existing_readiness',SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.Readiness.update_lifecycle,module.GetState


def snapshot_active(snapshot,now=None):
    now=time.monotonic() if now is None else now
    if not isinstance(snapshot,dict) or snapshot.get('ready') is not True:
        return False
    observed=snapshot.get('observed_monotonic')
    if isinstance(observed,bool) or not isinstance(observed,(int,float)) or not math.isfinite(observed) or not 0<=now-observed<=.5:
        return False
    lifecycle=snapshot.get('lifecycle',{})
    for name in REQUIRED_NODES:
        state=lifecycle.get(name) if isinstance(lifecycle,dict) else None
        if not isinstance(state,list) or len(state)!=2 or type(state[0]) is not int or state[0]!=3:
            return False
        stamp=state[1]
        if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not 0<=now-stamp<=3.:
            return False
    return True


class NativeReadiness:
    def __init__(self,node,required_nodes=REQUIRED_NODES):
        if tuple(required_nodes)!=REQUIRED_NODES:
            raise ValueError('Native docking readiness requires docking_server and bt_navigator')
        self.required_nodes=tuple(required_nodes)
        self._update,self._state_type=_load_runtime()
        self.lifecycle_clients={name:node.create_client(self._state_type,'/'+name+'/get_state') for name in self.required_nodes}
        self.pending,self.lifecycle,self.last_query={},{},{}

    def update(self):
        self._update(self)

    def snapshot(self):
        value={'ready':True,'observed_monotonic':time.monotonic(),
               'lifecycle':{name:list(state) for name,state in self.lifecycle.copy().items()},
               'required_nodes':list(self.required_nodes),'source':'wait_ready.Readiness.update_lifecycle'}
        value['ready']=snapshot_active(value,value['observed_monotonic'])
        return value

    def active(self):
        return self.snapshot()['ready']


class StaticLocalizationWarmup:
    """R2-only no-motion requests with separate fresh AMCL pose evidence.

    No true pose, initial-pose publication, motion command or action is accepted.
    A service response sets an update flag; it is not a pose-consumption ACK.
    """
    def __init__(self, client, request, updates=3):
        self.client, self.request, self.required = client, request, updates
        self.lock = threading.RLock()
        self.records = []
        self.pending = self.candidate = None
        self.source = None
        self.held = False
        self.reason = 'waiting_for_held_native_world'
        self.started_wall = self.finished_wall = None

    def update(self, source, *, held, native_active):
        with self.lock:
            self.source, self.held = source, held
            if len(self.records) >= self.required:
                return
            if not held or not native_active:
                self.candidate = None
                self.reason = 'waiting_for_held_native_world'
                return
            now = time.monotonic()
            if self.pending is not None:
                item = self.pending
                if item['future'].done() and item.get('response_wall') is None:
                    try:
                        item['future'].result()
                        item['response_wall'] = time.time()
                    except Exception as error:
                        self.reason = 'nomotion_service_error: '+str(error)
                        self.pending = self.candidate = None
                        return
                if item.get('response_wall') is not None and self.candidate is not None:
                    self.records.append({k:v for k,v in item.items() if k not in ('future','monotonic')}
                                        | self.candidate)
                    self.pending = self.candidate = None
                    self.reason = 'ready' if len(self.records) >= self.required else 'warming'
                    if self.reason == 'ready':
                        self.finished_wall = time.time()
                elif now-item['monotonic'] > 3.:
                    self.reason = 'nomotion_response_or_fresh_pose_timeout'
                    item['future'].cancel()
                    self.pending = self.candidate = None
                return
            if not self.client.service_is_ready():
                self.reason = 'waiting_for_nomotion_service'
                return
            self.started_wall = self.started_wall or time.time()
            try:
                self.pending = {'future':self.client.call_async(self.request()),
                                'requested_source_s':source,'requested_wall':time.time(),
                                'monotonic':now}
            except Exception as error:
                self.reason = 'nomotion_service_error: '+str(error)
            self.reason = 'waiting_for_service_and_new_amcl_pose'

    def observe(self, *, stamp, pose, covariance, frame_id, source_now):
        with self.lock:
            if self.pending is None or not self.held:
                return
            try:
                values = [stamp, source_now, *(pose[k] for k in ('x','y','yaw'))]
                if (frame_id != 'map'
                        or any(isinstance(v,bool) or not isinstance(v,Real) or not math.isfinite(v) for v in values)):
                    raise ValueError('invalid AMCL frame or pose')
                if stamp <= self.pending['requested_source_s'] or not -1.2 <= source_now-stamp <= .8:
                    raise ValueError('AMCL source stamp is not a fresh post-request frame')
                # Covariance is diagnostic here, never a convergence or dispatch threshold.
                valid_covariance = (isinstance(covariance,(list,tuple)) and len(covariance)==36
                    and all(not isinstance(v,bool) and isinstance(v,Real) and math.isfinite(v)
                            for v in covariance))
                warning = None
                if not valid_covariance:
                    warning = 'AMCL covariance unavailable; original fresh pose retained'
                elif any(covariance[i]<0 for i in (0,7,35)):
                    warning = 'AMCL negative covariance diagonal recorded without clamping'
                if warning:
                    logging.warning(warning)
                self.candidate = {'pose_source_s':float(stamp),'pose_received_wall':time.time(),
                                  'pose':{k:float(pose[k]) for k in ('x','y','yaw')},
                                  'covariance':[float(v) for v in covariance] if valid_covariance else None,
                                  'covariance_warning':warning}
            except (KeyError, TypeError, ValueError) as error:
                self.reason = str(error)

    def snapshot(self):
        with self.lock:
            return {'enabled':True,'ready':len(self.records)>=self.required,
                    'reason':self.reason,'required_updates':self.required,
                    'completed_updates':len(self.records),'started_wall':self.started_wall,
                    'finished_wall':self.finished_wall,'records':copy.deepcopy(self.records),
                    'service_response_is_pose_consumption_ack':False,
                    'truth_used_for_localization':False,'convergence_claimed':False}
