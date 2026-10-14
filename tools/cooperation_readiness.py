"""Share existing read-only lifecycle queries between the bridge and runner.

Readiness.update_lifecycle owns query cadence, pending requests and timeouts.
This adapter adds no thread, timer, transition call or action dispatch.
"""
import importlib.util
import math
from pathlib import Path
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
