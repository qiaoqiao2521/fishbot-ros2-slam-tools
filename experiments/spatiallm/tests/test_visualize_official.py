"""The manifest must bind finalized output, including a delayed SDK footer."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


MODULE = Path(__file__).resolve().parents[1]


@pytest.fixture
def viewer(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(MODULE))
    spec = importlib.util.spec_from_file_location('spatiallm_viewer_test', MODULE / 'visualize_official.py')
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'visualize.py').write_text('# pinned test upstream')
    monkeypatch.setattr(wrapper, '_VISUALIZE_HASH', hashlib.sha256((source / 'visualize.py').read_bytes()).hexdigest())
    layout = tmp_path / 'layout.txt'
    layout.write_text('validated layout')
    cloud = tmp_path / 'cloud.ply'
    cloud.write_bytes(b'point cloud')
    output = tmp_path / 'recording.rrd'
    monkeypatch.setattr(wrapper, 'load_layout', lambda *args: {'source': {'kind': 'test_input'}})
    monkeypatch.setattr(wrapper, '_official_layout_class', lambda *args: (object,))
    monkeypatch.setattr(sys, 'argv', ['viewer', '--source-dir', str(source), '--point-cloud', str(cloud),
                                     '--layout', str(layout), '--output', str(output)])
    calls = []

    def run(*args, **kwargs):
        calls.append('write')
        output.write_bytes(b'logged data')

    def close():
        calls.append('close')
        output.write_bytes(output.read_bytes() + bytes(8))

    monkeypatch.setattr(wrapper.runpy, 'run_path', run)
    monkeypatch.setitem(sys.modules, 'rerun', types.SimpleNamespace(disconnect=close))
    return wrapper, output, calls


def test_manifest_hashes_closed_recording(viewer, monkeypatch):
    wrapper, output, calls = viewer
    prior_package = types.ModuleType('prior_spatiallm')
    monkeypatch.setitem(sys.modules, 'spatiallm', prior_package)
    prior_argv = sys.argv
    wrapper.main()
    manifest = json.loads(output.with_suffix('.manifest.json').read_text())
    assert calls == ['write', 'close']
    assert output.read_bytes() == b'logged data' + bytes(8)
    assert manifest['recording_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert manifest['recording_bytes'] == output.stat().st_size
    assert manifest['recording_finalization'] == 'rerun.disconnect completed before hashing'
    assert sys.argv is prior_argv
    assert sys.modules['spatiallm'] is prior_package


@pytest.mark.parametrize('failure', ['upstream', 'close'])
def test_failed_writer_keeps_partial_recording_without_manifest(viewer, monkeypatch, failure):
    wrapper, output, calls = viewer
    prior_argv = sys.argv
    monkeypatch.delitem(sys.modules, 'spatiallm', raising=False)

    def fail():
        raise RuntimeError(failure)

    if failure == 'upstream':
        def failed_run(*args, **kwargs):
            output.write_bytes(b'partial data')
            fail()
        monkeypatch.setattr(wrapper.runpy, 'run_path', failed_run)
    else:
        monkeypatch.setattr(sys.modules['rerun'], 'disconnect', fail)
    with pytest.raises(RuntimeError, match=failure):
        wrapper.main()
    assert output.is_file()
    assert not output.with_suffix('.manifest.json').exists()
    assert sys.argv is prior_argv
    assert 'spatiallm' not in sys.modules
    if failure == 'upstream':
        assert calls == ['close']


def test_existing_manifest_is_preserved(viewer):
    wrapper, output, calls = viewer
    manifest = output.with_suffix('.manifest.json')
    manifest.write_text('old evidence')
    with pytest.raises(SystemExit):
        wrapper.main()
    assert manifest.read_text() == 'old evidence'
    assert not output.exists()
    assert calls == []
