"""Reject malformed records and verify orientation conversion at singular cases."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from so101_to_mcap import convert, digest, object_quaternion, validate_trace, verify_video_source
from verify_so101_mcap import rotation_from_xyzw


def small_trace():
    return {"time_s": np.array([.02, .04, .06]), "stage": np.array(["ready"] * 3),
            "state": np.zeros((3, 6)), "action": np.zeros((3, 6)),
            "object_xyz_m": np.zeros((3, 3)), "object_rotation": np.repeat(np.eye(3)[None], 3, axis=0),
            "tip_forces_n": np.zeros((3, 2)), "floor_contact": np.zeros(3, dtype=bool),
            "arm_valid": np.ones(3, dtype=bool), "obstacle_contact": np.zeros(3, dtype=bool)}


class ConversionBoundaries(unittest.TestCase):
    def test_duplicate_physical_time_rejected(self):
        data = small_trace()
        data["time_s"][1] = data["time_s"][0]
        with self.assertRaisesRegex(ValueError, "strictly increase"):
            validate_trace(data)

    def test_nan_command_rejected(self):
        data = small_trace()
        data["action"][1, 4] = np.nan
        with self.assertRaisesRegex(ValueError, "Nonfinite action"):
            validate_trace(data)

    def test_wrong_joint_count_rejected(self):
        data = small_trace()
        data["state"] = np.zeros((3, 5))
        with self.assertRaisesRegex(ValueError, "state shape"):
            validate_trace(data)

    def test_reflection_is_not_a_pose(self):
        data = small_trace()
        data["object_rotation"][0, 0, 0] = -1
        with self.assertRaisesRegex(ValueError, "proper rotations"):
            validate_trace(data)

    def test_subnanosecond_collisions_rejected(self):
        data = small_trace()
        data["time_s"] = np.array([.02, .02000000001, .04])
        with self.assertRaisesRegex(ValueError, "nanosecond conversion"):
            validate_trace(data)

    def test_rotation_half_turns_and_arbitrary_axes(self):
        for axis in (np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, 1]), np.array([1., 2, 3])):
            axis /= np.linalg.norm(axis)
            for angle in (0, .31, np.pi, np.pi-1e-10):
                x, y, z = axis * np.sin(angle / 2)
                source = {"x": x, "y": y, "z": z, "w": np.cos(angle / 2)}
                matrix = rotation_from_xyzw(source)
                result = rotation_from_xyzw(object_quaternion(matrix))
                np.testing.assert_allclose(result, matrix, atol=2e-15)

    def test_recorded_source_hash_cannot_be_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "recorder.py"
            source.write_text("print('not the reviewed recorder')\n")
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                verify_video_source(source, "0" * 64)
            with self.assertRaisesRegex(ValueError, "fresh source review"):
                verify_video_source(source, digest(source))

    def test_output_cannot_overwrite_original_episode(self):
        with self.assertRaisesRegex(ValueError, "Output must"):
            convert(Path("/not-read"), Path("/not-read"), Path("/tmp/not-allowed"))


if __name__ == "__main__":
    unittest.main()
