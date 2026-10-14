"""User-flow contracts with server revisions and real MuJoCo validation."""
from pathlib import Path
import copy
import hashlib
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / 'experiments/spatiallm'))
import editor
from validate_scene import validate_scene

SOURCE = Path(os.environ.get('SPATIALLM_SOURCE_DIR', str(Path.home() / '.cache/fishbot-spatiallm/prepared/source/SpatialLM')))
SAMPLE = Path(os.environ.get('SPATIALLM_SAMPLE_LAYOUT', str(Path.home() / '.cache/fishbot-spatiallm/prepared/sample/layout/scene0000_00.txt')))
PCD = Path(os.environ.get('SPATIALLM_SAMPLE_POINT_CLOUD', str(Path.home() / '.cache/fishbot-spatiallm/prepared/sample/pcd/scene0000_00.ply')))


@pytest.fixture
def client(tmp_path):
    app = editor.create_app(editor.EditorConfig(SOURCE, SAMPLE, PCD, tmp_path / 'output', PROJECT, False))
    with TestClient(app, base_url='http://127.0.0.1') as c:
        yield c, tmp_path / 'output'


def sample(c):
    response = c.get('/api/example')
    assert response.status_code == 200
    return response.json()['document']


def ref(doc):
    return {'document_id': doc['document_id'], 'revision': doc['revision']}


def correct_walls(c, doc):
    response = c.post('/api/correct', json={'document': ref(doc), 'edits': [
        {'id': entity['id'], 'params': {'thickness': .12}}
        for entity in doc['entities'] if entity['kind'] == 'wall']})
    assert response.status_code == 200
    return response.json()['document']


def test_zero_thickness_keeps_original_and_has_no_download(client):
    c, output = client
    doc = sample(c)
    assert doc['source']['kind'] == 'official-ground-truth'
    assert len(doc['entities']) == 18 and doc['corrections'] == []
    response = c.post('/api/export', json={'document': ref(doc)})
    assert response.status_code == 400 and 'zero thickness' in response.json()['detail']
    assert not list(output.iterdir())


def test_real_correct_export_download_and_roundtrip(client):
    c, output = client
    original = sample(c)
    doc = correct_walls(c, original)
    assert doc['revision'] == 2 and len(doc['corrections']) == 6
    assert all(e['params']['thickness'] == 0 for e in original['entities'] if e['kind'] == 'wall')
    response = c.post('/api/export', json={'document': ref(doc), 'robot': {'position_x': 3., 'position_y': -2.8}})
    assert response.status_code == 200
    result = response.json()
    assert result['validation']['steps'] == 20
    assert result['validation']['nq'] == 9 and result['validation']['nu'] == 2
    assert result['validation']['finite_physical_state'] is True
    assert all(p['passed'] for p in result['validation']['solid_collision_probes'])
    assert all(p['passed'] for p in result['validation']['door_aperture_probes'])
    assert result['render']['status'] == 'not_requested'
    for item in result['downloads']:
        response = c.get(item['url'])
        assert response.status_code == 200
        if item['name'] != 'manifest.json':
            assert hashlib.sha256(response.content).hexdigest() == result['manifest']['outputs'][item['name']]['sha256']
    text = c.get(next(d['url'] for d in result['downloads'] if d['name'] == 'layout.txt')).text
    parsed = editor.load_layout(text, SOURCE, {'kind': 'roundtrip'})
    assert parsed['entities'] == doc['entities']


def test_stale_revision_is_rejected(client):
    c, _ = client
    old = sample(c)
    correct_walls(c, old)
    assert c.post('/api/export', json={'document': ref(old)}).status_code == 409
    assert c.post('/api/correct', json={'document': ref(old), 'edits': [{'id': 'wall_0', 'params': {'thickness': .2}}]}).status_code == 409


def test_client_cannot_forge_source_or_replace_entities(client):
    c, _ = client
    loaded = c.post('/api/import', json={'layout_text': 'wall_0=Wall(0,0,0,4,0,0,3,.2)', 'source_kind': 'user-provided'}).json()['document']
    forged = copy.deepcopy(loaded)
    forged['source']['kind'] = 'official-ground-truth'
    forged['entities'][0]['params']['height'] = 3000
    response = c.post('/api/export', json={'document': forged})
    assert response.status_code == 200
    assert response.json()['manifest']['source']['kind'] == 'user-provided'
    stored = json.loads(c.get(next(x['url'] for x in response.json()['downloads'] if x['name'] == 'layout.json')).content)
    assert stored['entities'][0]['params']['height'] == 3


def test_failed_native_validation_never_registers_files(client, monkeypatch):
    c, output = client
    doc = correct_walls(c, sample(c))
    def fail(*args, **kwargs):
        raise RuntimeError('injected native failure')
    monkeypatch.setattr(editor, 'validate_scene', fail)
    assert c.post('/api/export', json={'document': ref(doc)}).status_code == 503
    folders = list(output.iterdir())
    assert len(folders) == 1
    assert c.get(f'/api/exports/{folders[0].name}/scene.xml').status_code == 404


def test_changed_download_is_not_presented_as_verified(client):
    c, output = client
    result = c.post('/api/export', json={'document': ref(correct_walls(c, sample(c)))}).json()
    item = next(x for x in result['downloads'] if x['name'] == 'scene.xml')
    path = output / result['export_id'] / 'scene.xml'
    assert c.get(item['url']).status_code == 200
    path.write_text('changed')
    assert c.get(item['url']).status_code == 409


def test_cross_origin_host_and_path_boundaries(client):
    c, _ = client
    assert c.post('/api/import', json={'layout_text': 'wall_0=Wall(0,0,0,1,0,0,2,.1)'}, headers={'Origin': 'https://unrelated.example'}).status_code == 403
    assert c.get('/api/health', headers={'Host': 'unrelated.example'}).status_code == 400
    assert c.get('/api/exports/00000000-0000-0000-0000-000000000000/scene.xml').status_code == 404
    assert c.get('/api/exports/00000000-0000-0000-0000-000000000000/%2e%2e%2fscene.xml').status_code in (404, 422)


def test_invalid_unicode_and_unbounded_coordinates_are_visible_errors(client):
    c, _ = client
    assert c.post('/api/import', content=b'{"layout_text":"\\ud800"}', headers={'Content-Type': 'application/json'}).status_code in (400, 422)
    result = c.post('/api/import', json={'layout_text': 'wall_0=Wall(0,0,0,1e20,0,0,3,.2)'})
    assert result.status_code == 400


@pytest.mark.parametrize('change', ['remove_manifest', 'remove_layout', 'drop_doors', 'change_scene', 'remove_hash'])
def test_validation_rejects_missing_or_changed_evidence(client, change):
    c, output = client
    result = c.post('/api/export', json={'document': ref(correct_walls(c, sample(c)))}).json()
    folder = output / result['export_id']
    if change.startswith('remove_') and change != 'remove_hash':
        (folder / ('manifest.json' if change == 'remove_manifest' else 'layout.json')).unlink()
    elif change == 'drop_doors':
        path = folder / 'layout.json'
        doc = json.loads(path.read_text())
        doc['entities'] = [e for e in doc['entities'] if e['kind'] != 'door']
        path.write_text(json.dumps(doc))
    elif change == 'change_scene':
        with (folder / 'scene.xml').open('a') as stream:
            stream.write('\n<!-- changed after export -->\n')
    else:
        path = folder / 'manifest.json'
        manifest = json.loads(path.read_text())
        del manifest['outputs']['layout.json']['sha256']
        path.write_text(json.dumps(manifest))
    verification = folder / 'revalidation'
    with pytest.raises(ValueError, match='requires|SHA256'):
        validate_scene(folder / 'scene.xml', verification, steps=1, render=False)
    assert not verification.exists()
