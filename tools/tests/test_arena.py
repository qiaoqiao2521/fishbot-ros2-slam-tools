"""Negative entry-point and receipt checks; no Isaac runtime is exercised here."""
import copy
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
        return {"runs": {name: {"status": "completed", "rebuilds": [
            {"index": 0, "episodes": [{"success": False, "episode_length": 75}]}]}
            for name in ("baseline", "swap_objects")}}

    def write_result(self, result):
        (self.source / "arena_experiment_result.json").write_text(json.dumps(result))

    def test_receipt_missing_file_run_or_episode_is_not_completion(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            arena.result_readback(self.source)
        missing_run = self.result()
        del missing_run["runs"]["swap_objects"]
        no_episode = self.result()
        no_episode["runs"]["baseline"]["rebuilds"][0]["episodes"] = []
        failed = self.result()
        failed["runs"]["baseline"]["status"] = "failed"
        for result in (missing_run, no_episode, failed):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                self.write_result(result)
                arena.result_readback(self.source)

    def test_native_success_false_and_null_are_preserved(self):
        result = self.result()
        result["runs"]["swap_objects"]["rebuilds"][0]["episodes"][0]["success"] = None
        self.write_result(result)
        receipt = arena.result_readback(self.source)
        self.assertTrue(receipt["pipeline_completed"])
        self.assertEqual(receipt["policy_success"], {"baseline": [False], "swap_objects": [None]})
        invalid = copy.deepcopy(result)
        invalid["runs"]["baseline"]["rebuilds"][0]["episodes"][0]["success"] = 1
        self.write_result(invalid)
        with self.assertRaises(RuntimeError):
            arena.result_readback(self.source)


if __name__ == "__main__":
    unittest.main()
