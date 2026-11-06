"""Exact, query-local mesh sharing only; no simulator, scoring or file locks."""
import unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np
from cooperation_arm_entities import _FrozenMeshAssets


def model_fixture():
    vertices=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]])
    changed=vertices.copy();changed[1,0]+=1e-12
    return SimpleNamespace(mesh_vertadr=np.arange(4)*3,mesh_vertnum=np.full(4,3),
        mesh_faceadr=np.arange(4),mesh_facenum=np.ones(4,dtype=int),
        mesh_vert=np.vstack([vertices,vertices,vertices,changed]),
        mesh_face=np.array([[0,1,2],[0,1,2],[0,2,1],[0,1,2]]))


class FrozenMeshAssetsTests(unittest.TestCase):
    def test_reuses_same_id_and_identical_arrays_but_never_near_geometry_or_changed_faces(self):
        assets=ET.Element('asset');cache=_FrozenMeshAssets(assets,model_fixture(),np)
        first=cache.asset(0,10)
        self.assertEqual(cache.asset(0,11),first)
        self.assertEqual(cache.asset(1,12),first)
        self.assertNotEqual(cache.asset(2,13),first)
        self.assertNotEqual(cache.asset(3,14),first)
        self.assertEqual(len(assets.findall('mesh')),3)
        self.assertEqual(cache.same_id_reuses,1)
        self.assertEqual(cache.same_value_reuses,1)
        self.assertEqual(assets.findall('mesh')[1].get('face'),'0 2 1')

    def test_independent_query_builds_do_not_share_assets_or_mutable_cache(self):
        model=model_fixture();a,b=ET.Element('asset'),ET.Element('asset')
        cache_a,cache_b=_FrozenMeshAssets(a,model,np),_FrozenMeshAssets(b,model,np)
        self.assertNotEqual(cache_a.asset(0,10),cache_b.asset(0,20))
        self.assertEqual(len(a),1);self.assertEqual(len(b),1)
        self.assertEqual(cache_b.same_id_reuses,0)


if __name__=='__main__':unittest.main()
