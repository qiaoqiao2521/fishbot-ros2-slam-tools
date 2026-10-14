"""Negative entry-point and receipt checks; no Isaac runtime is exercised here."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fishbot_arena", TOOLS / "fishbot_arena.py")
arena = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arena)


class ArenaBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.output = Path(self.temp.name) / "native-output"
        self.source.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Arena unit fixture")
        self.git("config", "user.email", "arena-fixture@example.invalid")
        for name in ("pyproject.toml", "uv.lock"):
            (self.source / name).write_text("# unit fixture, not upstream\n")
        self.git("add", "pyproject.toml", "uv.lock")
        self.git("commit", "-qm", "fixture")
        self.lock = {"commit": self.git("rev-parse", "HEAD"), "submodules": {},
                     "source_sha256": {name: hashlib.sha256((self.source / name).read_bytes()).hexdigest()
                                       for name in ("pyproject.toml", "uv.lock")},
                     "python": "3.12", "isaac_sim": "6.1.0.0", "minimum_vram_mib": 16384,
                     "requirements_url": "https://example.invalid/requirements"}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.source, capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_real_git_fixture_matches_only_its_own_identity(self):
        self.assertTrue(arena.source_status(self.source, self.lock)["verified"])
        other = dict(self.lock, commit="0" * 40)
        self.assertFalse(arena.source_status(self.source, other)["verified"])

    def test_changed_source_and_missing_submodule_are_unverified(self):
        (self.source / "pyproject.toml").write_text("changed\n")
        self.assertFalse(arena.source_status(self.source, self.lock)["verified"])
        locked_child = dict(self.lock, submodules={"submodules/IsaacLab": "1" * 40})
        state = arena.source_status(self.source, locked_child)
        self.assertIsNone(state["submodules"]["submodules/IsaacLab"]["head"])
        self.assertFalse(state["verified"])

    def test_parent_repository_does_not_count_as_submodule(self):
        (self.source / "submodules/IsaacLab").mkdir(parents=True)
        locked_child = dict(self.lock, submodules={"submodules/IsaacLab": self.lock["commit"]})
        state = arena.source_status(self.source, locked_child)
        self.assertIsNone(state["submodules"]["submodules/IsaacLab"]["head"])
        self.assertFalse(state["verified"])

    def test_four_gb_and_unknown_gpu_cannot_pass_hardware_precheck(self):
        for raw in (None, "0, NVIDIA RTX 3050, 4096, 595.58.03, GPU-unit-fixture", "unparseable"):
            with self.subTest(raw=raw), patch.object(arena, "query", return_value=raw):
                self.assertFalse(arena.hardware_status(self.source, self.lock)["precheck_passed"])

    def test_official_cloud_t4_reports_nominal_memory_without_desktop_false_rejection(self):
        for name in ('T4', 'Tesla T4', 'NVIDIA T4'):
            raw = f'0, {name}, 15360, 580.82.07, GPU-unit-fixture'
            with self.subTest(name=name), patch.object(arena, 'query', return_value=raw):
                result = arena.hardware_status(self.source, self.lock)
                self.assertTrue(result['precheck_passed'])
                self.assertEqual(result['selected_minimum_vram_mib'], 15360)
                self.assertIn('requires official checker', result['official_compatibility'])
        for name in ('NVIDIA A100-SXM4-80GB', 'NVIDIA H100 PCIe'):
            with patch.object(arena, 'query', return_value=f'0, {name}, 81920, 580.82.07, GPU-unit-fixture'):
                self.assertFalse(arena.hardware_status(self.source, self.lock)['precheck_passed'])

    def test_uv_version_info_and_standard_version_both_readback_without_import(self):
        venv = self.source/'.venv'
        (venv/'bin').mkdir(parents=True)
        (venv/'bin/python').write_text('metadata fixture only')
        site = venv/'lib/python3.12/site-packages';site.mkdir(parents=True)
        packages = {'isaaclab-arena':'0.3.0', 'isaaclab':'17.0.2', 'isaacsim':'6.1.0.0', 'torch':'2.11.0+cu128'}
        (self.source/'uv.lock').write_text(''.join(f'[[package]]\nname = "{name}"\nversion = "{version}"\n' for name, version in packages.items()))
        for name, version in packages.items():
            folder = site/(name+'.dist-info');folder.mkdir()
            (folder/'METADATA').write_text(f'Name: {name}\nVersion: {version}\n')
        for field in ('version_info', 'version'):
            (venv/'pyvenv.cfg').write_text(f'{field} = 3.12.3\n')
            self.assertTrue(arena.dependency_status(self.source, self.lock)['installed'])
        (venv/'pyvenv.cfg').write_text('version = 3.13.0\nversion_info = 3.12.3\n')
        self.assertFalse(arena.dependency_status(self.source, self.lock)['installed'])

    def test_inherited_eula_never_authorizes_execution(self):
        with patch.dict(os.environ, {"ACCEPT_EULA": "Y", "OMNI_KIT_ACCEPT_EULA": "YES"}), \
                patch.object(arena, "run_checked") as execute:
            for action in ("install", "smoke", "evaluate"):
                with self.subTest(action=action), self.assertRaisesRegex(RuntimeError, "explicit --accept-eula"):
                    arena.execute(action, self.source, self.lock)
            execute.assert_not_called()
            self.assertNotIn("ACCEPT_EULA", arena.runtime_environment(False))

    def test_license_acceptance_does_not_change_existing_privacy_preference(self):
        with patch.dict(os.environ, {"PRIVACY_CONSENT": "NO"}):
            self.assertEqual(arena.runtime_environment(False)["PRIVACY_CONSENT"], "NO")
            self.assertEqual(arena.runtime_environment(True)["PRIVACY_CONSENT"], "NO")

    def test_standalone_child_does_not_inherit_notebook_shutdown_mode(self):
        markers = {"JPY_PARENT_PID": "42", "ISAAC_JUPYTER_KERNEL": "0",
                   "ISAAC_JUPYTER_PYTHON_PACKAGE": "1",
                   "ISAACLAB_ARENA_FORCE_EXIT_ON_COMPLETE": "1"}
        with patch.dict(os.environ, {**markers, "PRIVACY_CONSENT": "NO"}):
            with patch.object(arena.subprocess, "run") as execute:
                arena.run_checked(["python", "official_runner.py"], self.source)
            child_env = execute.call_args.kwargs["env"]
            for key, value in markers.items():
                self.assertNotIn(key, child_env)
                self.assertEqual(os.environ[key], value)
            self.assertEqual(child_env["PRIVACY_CONSENT"], "NO")

    def test_changed_source_rejects_before_native_execution(self):
        (self.source / "unexpected.py").write_text("# preserved untracked source\n")
        with patch.object(arena, "run_checked") as execute, self.assertRaisesRegex(RuntimeError, "source identity"):
            arena.execute("smoke", self.source, self.lock, accept_eula=True)
        execute.assert_not_called()

    def test_four_gb_does_not_install_or_create_evaluation_output(self):
        hardware = {"precheck_passed": False, "errors": ["4096 MiB is below minimum"]}
        output = Path(self.temp.name) / "new-evaluation"
        with patch.object(arena, "hardware_status", return_value=hardware), \
                patch.object(arena, "run_checked") as execute:
            for action in ("install", "smoke", "evaluate"):
                with self.subTest(action=action), self.assertRaisesRegex(RuntimeError, "hardware precheck"):
                    arena.execute(action, self.source, self.lock, accept_eula=True, output=output)
            execute.assert_not_called()
            self.assertFalse(output.exists())

    def test_existing_output_is_preserved_without_dispatch(self):
        output = Path(self.temp.name) / "old-evaluation"
        output.mkdir()
        (output / "evidence.json").write_text('{"old": true}\n')
        with patch.object(arena, "runtime_gate", return_value={}), \
                patch.object(arena, "run_checked") as execute, \
                self.assertRaisesRegex(RuntimeError, "output already exists"):
            arena.execute("evaluate", self.source, self.lock, accept_eula=True, output=output)
        execute.assert_not_called()
        self.assertEqual((output / "evidence.json").read_text(), '{"old": true}\n')

    def test_prepare_preserves_mismatched_checkout(self):
        with patch.object(arena, "run_checked") as execute, self.assertRaisesRegex(RuntimeError, "different HEAD"):
            arena.prepare(self.source, dict(self.lock, commit="0" * 40))
        execute.assert_not_called()
        self.assertEqual(self.git("rev-parse", "HEAD"), self.lock["commit"])

    def test_prepare_preserves_changed_checkout(self):
        (self.source / "notes.txt").write_text("local work\n")
        with patch.object(arena, "run_checked") as execute, self.assertRaisesRegex(RuntimeError, "changed"):
            arena.prepare(self.source, self.lock)
        execute.assert_not_called()
        self.assertEqual((self.source / "notes.txt").read_text(), "local work\n")

    def test_plan_uses_exact_native_runners(self):
        commands = arena.native_commands(self.source, Path(self.temp.name) / "output", 1)
        smoke = commands["smoke"]
        self.assertEqual(smoke[1], "isaaclab_arena/evaluation/policy_runner.py")
        self.assertEqual(smoke[smoke.index("--num_steps") + 1], "20")
        self.assertEqual(smoke[smoke.index("--num_envs") + 1], "1")
        self.assertEqual(smoke[-1], "cube_goal_pose")
        evaluate = commands["evaluate"]
        self.assertEqual(evaluate[1], "isaaclab_arena/evaluation/experiment_runner.py")
        self.assertEqual(evaluate[evaluate.index("--experiment_config") + 1], str(arena.CONFIG))
        self.assertIn("--experiment_output_directory", evaluate)
        self.assertEqual(commands["install"], ["uv", "sync", "--locked"])

    def test_installer_exit_without_locked_dependency_readback_is_incomplete(self):
        before = {"dependencies": {"uv": "/unit/uv", "git_lfs": "unit-lfs"}}
        after = {"source": {"verified": True}, "dependencies": {"installed": False}}
        with patch.object(arena, "runtime_gate", return_value=before), \
                patch.object(arena, "run_checked"), \
                patch.object(arena, "doctor", return_value=after), \
                self.assertRaisesRegex(RuntimeError, "did not verify"):
            arena.execute("install", self.source, self.lock, accept_eula=True)

    def result(self):
        objects = {"baseline": ("rubiks_cube_hot3d_robolab", "bowl_ycb_robolab"),
                   "swap_objects": ("mustard_bottle_hot3d_robolab", "wooden_bowl_hot3d_robolab")}
        return {"runs": {name: {
            "environment": {"name": "pick_and_place_maple_table", "definition": "pick_and_place_maple_table"},
            "policy_variant": "zero_action", "status": "completed", "rebuilds": [
                {"index": 0, "episodes": [{"job_name": name, "env_id": 0, "episode_in_env": 0,
                    "seed": 42, "success": False, "episode_length": 23,
                    "language_instruction": f"Pick up the {pair[0]}, and place it into the {pair[1]}",
                    "timestamp": datetime.now().isoformat()}]}]}
            for name, pair in objects.items()}}

    def write_result(self, result):
        import shutil
        if self.output.exists():
            shutil.rmtree(self.output)
        self.output.mkdir()
        state = arena.source_status(self.source, self.lock)
        combined, counts = [], {}
        for name, run in result.get("runs", {}).items():
            directory = self.output/name
            directory.mkdir()
            for rebuild in run.get("rebuilds", []):
                path = directory/f"episode_results_rebuild{rebuild['index']}.jsonl"
                path.write_text(''.join(json.dumps(ep)+'\n' for ep in rebuild['episodes']))
            length = sum(ep['episode_length'] for rebuild in run.get('rebuilds', []) for ep in rebuild['episodes'])
            timing = [{'type': 'timing', 'name': key, 'app_name': 'experiment_runner', 'count': length,
                       'mean_ms': .1, 'total_ms': length*.1, 'min_ms': .1, 'max_ms': .1,
                       'p10_ms': .1, 'p50_ms': .1, 'p90_ms': .1}
                      for key in ('step', 'step/env_step', 'step/policy_inference')]
            (directory/'arena_experiment_timings.json').write_text(json.dumps(timing))
            combined.extend(dict(record, run_name=name) for record in timing)
            for record in timing:
                counts[record['name']] = counts.get(record['name'], 0)+record['count']
        (self.output/'arena_experiment_timings.json').write_text(json.dumps({
            'runs': combined, 'totals': [{'name': name, 'count': count, 'mean_ms': .1,
                                       'total_ms': count*.1, 'min_ms': .1, 'max_ms': .1}
                                      for name, count in counts.items()]}))
        (self.output / "arena_experiment_result.json").write_text(json.dumps(result))
        receipt = {'command': arena.native_commands(self.source, self.output)['evaluate'],
                   'started_utc': (datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),
                   'finished_utc': datetime.now(timezone.utc).isoformat(), 'returncode': 0,
                   'source_before': state, 'source_after': state, 'source_unchanged': True,
                   'config_sha256': hashlib.sha256(arena.CONFIG.read_bytes()).hexdigest(), 'config_unchanged': True}
        (self.output/'fishbot-runner-receipt.json').write_text(json.dumps(receipt))

    def refresh_receipt(self):
        path = self.output/'fishbot-runner-receipt.json'
        receipt = json.loads(path.read_text())
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(receipt))

    def test_receipt_missing_file_run_or_episode_is_not_completion(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            arena.result_readback(self.output)
        missing_run = self.result()
        del missing_run["runs"]["swap_objects"]
        no_episode = self.result()
        no_episode["runs"]["baseline"]["rebuilds"][0]["episodes"] = []
        failed = self.result()
        failed["runs"]["baseline"]["status"] = "failed"
        for result in (missing_run, no_episode, failed):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                self.write_result(result)
                arena.result_readback(self.output)

    def test_native_success_false_and_null_are_preserved(self):
        result = self.result()
        result["runs"]["swap_objects"]["rebuilds"][0]["episodes"][0]["success"] = None
        self.write_result(result)
        receipt = arena.result_readback(self.output)
        self.assertTrue(receipt["pipeline_completed"])
        self.assertEqual(receipt["policy_success"], {"baseline": [False], "swap_objects": [None]})
        invalid = copy.deepcopy(result)
        invalid["runs"]["baseline"]["rebuilds"][0]["episodes"][0]["success"] = 1
        self.write_result(invalid)
        with self.assertRaises(RuntimeError):
            arena.result_readback(self.output)

    def test_result_only_or_missing_native_jsonl_cannot_complete_pipeline(self):
        self.write_result(self.result())
        (self.output/'baseline/episode_results_rebuild0.jsonl').unlink()
        with self.assertRaisesRegex(RuntimeError, 'single rebuild JSONL'):
            arena.result_readback(self.output)
        self.write_result(self.result())
        (self.output/'fishbot-runner-receipt.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'runner evidence'):
            arena.result_readback(self.output)

    def test_run_metadata_episode_identity_and_budget_mismatch_reject(self):
        for field, value in (('job_name', 'swap_objects'), ('env_id', 1), ('env_id', False),
                             ('episode_in_env', 1), ('seed', 43), ('seed', True),
                             ('episode_length', 0), ('episode_length', 24),
                             ('language_instruction', 'wrong objects'), ('timestamp', 'invalid')):
            result = self.result()
            result['runs']['baseline']['rebuilds'][0]['episodes'][0][field] = value
            self.write_result(result)
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                arena.result_readback(self.output)
        for field, value in (('environment', {'name': 'another_task', 'definition': 'another_task'}),
                             ('policy_variant', 'learned_policy')):
            result = self.result()
            result['runs']['baseline'][field] = value
            self.write_result(result)
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'environment/policy'):
                arena.result_readback(self.output)

    def test_extra_episode_rebuild_wrong_index_or_rank_file_reject(self):
        result = self.result()
        result['runs']['baseline']['rebuilds'][0]['episodes'] *= 2
        self.write_result(result)
        with self.assertRaisesRegex(RuntimeError, 'one episode'):
            arena.result_readback(self.output)
        result = self.result()
        result['runs']['baseline']['rebuilds'][0]['index'] = 9
        self.write_result(result)
        with self.assertRaisesRegex(RuntimeError, 'rebuild 0'):
            arena.result_readback(self.output)
        self.write_result(self.result())
        (self.output/'baseline/episode_results_rebuild0_rank0.jsonl').write_text('{}\n')
        self.refresh_receipt()
        with self.assertRaisesRegex(RuntimeError, 'single rebuild JSONL'):
            arena.result_readback(self.output)

    def test_aggregate_and_jsonl_must_match_with_strict_json_types(self):
        self.write_result(self.result())
        path = self.output/'baseline/episode_results_rebuild0.jsonl'
        native = json.loads(path.read_text())
        native['success'] = 0  # Python considers False == 0, but the native JSON differs.
        path.write_text(json.dumps(native)+'\n')
        self.refresh_receipt()
        with self.assertRaisesRegex(RuntimeError, 'aggregate/JSONL mismatch'):
            arena.result_readback(self.output)

    def test_duplicate_json_keys_or_nonfinite_constants_reject(self):
        self.write_result(self.result())
        path = self.output/'arena_experiment_result.json'
        path.write_text(path.read_text().replace('"runs":', '"runs": {}, "runs":', 1))
        self.refresh_receipt()
        with self.assertRaisesRegex(RuntimeError, 'duplicate JSON'):
            arena.result_readback(self.output)
        self.write_result(self.result())
        path.write_text(path.read_text().replace('"seed": 42', '"seed": NaN', 1))
        self.refresh_receipt()
        with self.assertRaisesRegex(RuntimeError, 'nonfinite JSON'):
            arena.result_readback(self.output)

    def test_missing_or_mismatched_native_step_timings_reject(self):
        self.write_result(self.result())
        path = self.output/'baseline/arena_experiment_timings.json'
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'artifact is missing'):
            arena.result_readback(self.output)
        self.write_result(self.result())
        timings = json.loads(path.read_text())
        timings[1]['count'] = 22
        path.write_text(json.dumps(timings))
        self.refresh_receipt()
        with self.assertRaisesRegex(RuntimeError, 'timing/episode mismatch'):
            arena.result_readback(self.output)
        self.write_result(self.result())
        combined = self.output/'arena_experiment_timings.json'
        data = json.loads(combined.read_text())
        data['totals'][0]['count'] -= 1
        combined.write_text(json.dumps(data))
        self.refresh_receipt()
        with self.assertRaisesRegex(RuntimeError, 'combined timing'):
            arena.result_readback(self.output)

    def test_native_early_termination_is_valid_without_inventing_reason(self):
        result = self.result()
        result['runs']['baseline']['rebuilds'][0]['episodes'][0]['episode_length'] = 1
        self.write_result(result)
        receipt = arena.result_readback(self.output)
        self.assertTrue(receipt['pipeline_completed'])
        self.assertFalse(receipt['policy_success']['baseline'][0])
        self.assertIsNone(receipt['episodes']['baseline'][0]['termination_reason'])

    def test_stale_timestamp_or_redirected_native_file_rejects(self):
        result = self.result()
        result['runs']['baseline']['rebuilds'][0]['episodes'][0]['timestamp'] = '2000-01-01T00:00:00'
        self.write_result(result)
        with self.assertRaisesRegex(RuntimeError, 'episode timestamp'):
            arena.result_readback(self.output)
        self.write_result(self.result())
        path = self.output/'baseline/episode_results_rebuild0.jsonl'
        outside = Path(self.temp.name)/'outside.jsonl'
        outside.write_text(path.read_text())
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'redirects outside'):
            arena.result_readback(self.output)

    def evaluate_state(self):
        return {'source': arena.source_status(self.source, self.lock),
                'hardware': {'selected_gpu': {'uuid': 'GPU-offline-test-only'}}}

    def test_evaluate_persists_final_false_null_and_native_evidence(self):
        def native_run(*_args, **_kwargs):
            result = self.result()
            result['runs']['swap_objects']['rebuilds'][0]['episodes'][0]['success'] = None
            self.write_result(result)
        with patch.object(arena, 'runtime_gate', return_value=self.evaluate_state()), \
                patch.object(arena, 'run_checked', side_effect=native_run):
            result = arena.execute('evaluate', self.source, self.lock, accept_eula=True, output=self.output)
        saved = json.loads((self.output/'fishbot-runner-receipt.json').read_text())
        self.assertTrue(saved['pipeline_completed'])
        self.assertEqual(saved['policy_success'], {'baseline': [False], 'swap_objects': [None]})
        self.assertEqual(saved, result)

    def test_exit_zero_with_incomplete_results_persists_failed_validation(self):
        with patch.object(arena, 'runtime_gate', return_value=self.evaluate_state()), \
                patch.object(arena, 'run_checked'), self.assertRaises(RuntimeError):
            arena.execute('evaluate', self.source, self.lock, accept_eula=True, output=self.output)
        saved = json.loads((self.output/'fishbot-runner-receipt.json').read_text())
        self.assertEqual(saved['returncode'], 0)
        self.assertFalse(saved['pipeline_completed'])
        self.assertIsNone(saved['policy_success'])
        self.assertTrue(saved['validation_error'])

    def test_native_abnormal_exit_keeps_pipeline_incomplete(self):
        with patch.object(arena, 'runtime_gate', return_value=self.evaluate_state()), \
                patch.object(arena, 'run_checked', side_effect=subprocess.CalledProcessError(-11, ['native'])), \
                self.assertRaises(subprocess.CalledProcessError):
            arena.execute('evaluate', self.source, self.lock, accept_eula=True, output=self.output)
        saved = json.loads((self.output/'fishbot-runner-receipt.json').read_text())
        self.assertEqual(saved['returncode'], -11)
        self.assertFalse(saved['pipeline_completed'])
        self.assertIsNone(saved['policy_success'])

    def test_source_or_config_changed_during_evaluate_is_not_completed(self):
        config = Path(self.temp.name)/'evaluation.yaml'
        config.write_bytes(arena.CONFIG.read_bytes())
        def native_run(*_args, **_kwargs):
            self.write_result(self.result())
            config.write_text(config.read_text()+'# changed during native execution\n')
        with patch.object(arena, 'CONFIG', config), \
                patch.object(arena, 'runtime_gate', return_value=self.evaluate_state()), \
                patch.object(arena, 'run_checked', side_effect=native_run), \
                self.assertRaisesRegex(RuntimeError, 'configuration changed'):
            arena.execute('evaluate', self.source, self.lock, accept_eula=True, output=self.output)
        saved = json.loads((self.output/'fishbot-runner-receipt.json').read_text())
        self.assertFalse(saved['pipeline_completed'])
        self.assertFalse(saved['config_unchanged'])

    def test_false_exit_or_unverified_freeze_receipt_is_not_pipeline_completion(self):
        for key, value in (('returncode', -11), ('returncode', False), ('source_unchanged', False),
                           ('config_unchanged', False), ('config_sha256', '0'*64)):
            self.write_result(self.result())
            path = self.output/'fishbot-runner-receipt.json'
            receipt = json.loads(path.read_text())
            receipt[key] = value
            path.write_text(json.dumps(receipt))
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                arena.result_readback(self.output)

    def test_changed_preset_rejects_before_native_dispatch_or_output_creation(self):
        config = Path(self.temp.name)/'changed-preset.yaml'
        config.write_text(arena.CONFIG.read_text().replace('num_envs: 1', 'num_envs: 2'))
        with patch.object(arena, 'CONFIG', config), \
                patch.object(arena, 'runtime_gate', return_value=self.evaluate_state()), \
                patch.object(arena, 'run_checked') as native, \
                self.assertRaisesRegex(RuntimeError, 'frozen two-Run preset'):
            arena.execute('evaluate', self.source, self.lock, accept_eula=True, output=self.output)
        native.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
