"""Receipt attribution negative controls; no ROS runtime is imported or started."""
import copy
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'workbench-tools/drone-ros-ack-probe.py'
spec=importlib.util.spec_from_file_location('ros_ack_probe_fixture',path)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class ReceiptAttribution(unittest.TestCase):
    def fixture(self):
        events=[dict(kind=k,source_timestamp=100+i,publication_sequence_number=1,
            message={'id':i}) for i,k in enumerate(('ack','bspline','position'))]
        receipts=[dict(e,publisher_gid='gid-'+e['kind']) for e in copy.deepcopy(events)]
        graph={k:[{'endpoint_gid':'gid-'+k}] for k in ('ack','bspline','position')}
        return events,receipts,graph

    def test_complete_receipts_join_by_source_sequence_and_payload(self):
        self.assertTrue(all(probe.audit_receipts(*self.fixture()).values()))

    def test_graph_alone_or_wrong_gid_is_not_per_message_origin(self):
        events,receipts,graph=self.fixture()
        self.assertFalse(all(probe.audit_receipts(events,[],graph).values()))
        receipts[0]['publisher_gid']='other'
        self.assertFalse(probe.audit_receipts(events,receipts,graph)['ack_cpp_gid_matches_graph'])
        graph['position'].append({'endpoint_gid':'other'})
        self.assertFalse(probe.audit_receipts(events,receipts,graph)['position_cpp_gid_matches_graph'])

    def test_missing_timestamp_sequence_or_different_body_cannot_join(self):
        for key,value in [('source_timestamp',None),('publication_sequence_number',None),('message',{'id':99})]:
            with self.subTest(key=key):
                events,receipts,graph=self.fixture();receipts[1][key]=value
                self.assertFalse(probe.audit_receipts(events,receipts,graph)['bspline_python_receipts_join_cpp'])
        events,receipts,graph=self.fixture()
        events[0]['source_timestamp']=receipts[0]['source_timestamp']=None
        self.assertFalse(probe.audit_receipts(events,receipts,graph)['ack_python_receipts_join_cpp'])


    def test_reaped_process_is_not_a_clean_native_exit(self):
        events=[dict(kind='process_start',role='trajectory',pid=7),
            dict(kind='process_exit',role='trajectory',pid=7,exit_code=-11,proc_absent=True)]
        self.assertFalse(probe.native_shutdown_clean(events))
        events[-1]['exit_code']=0
        self.assertTrue(probe.native_shutdown_clean(events))
        events[-1]['proc_absent']=False
        self.assertFalse(probe.native_shutdown_clean(events))
        self.assertFalse(probe.native_shutdown_clean(events[:1]))


if __name__=='__main__':unittest.main()
