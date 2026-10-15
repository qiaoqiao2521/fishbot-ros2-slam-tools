import unittest
from tools.fishbot_edge_voice_node import EdgeHardwareDetector, FillerWordFilter, EdgeVoiceIntentParser


class TestEdgeVoicePerception(unittest.TestCase):
    def test_hardware_detection(self):
        caps = EdgeHardwareDetector.detect_capabilities()
        self.assertIsInstance(caps, dict)
        self.assertIn("has_arm_fp16", caps)
        self.assertIn("has_x86_avx2", caps)

    def test_filler_word_filter(self):
        cleaned, removed = FillerWordFilter.clean("呃那个……小车前进")
        self.assertIn("前进", cleaned)
        self.assertTrue(len(removed) > 0)

        cleaned2, removed2 = FillerWordFilter.clean("um please go forward")
        self.assertEqual(cleaned2, "please go forward")
        self.assertIn("um", [r.lower() for r in removed2])

    def test_intent_parsing(self):
        forward_res = EdgeVoiceIntentParser.parse("那个……往前走")
        self.assertEqual(forward_res["intent"], "FORWARD")
        self.assertGreater(forward_res["linear_x"], 0.0)

        left_res = EdgeVoiceIntentParser.parse("向左转弯")
        self.assertEqual(left_res["intent"], "TURN_LEFT")
        self.assertGreater(left_res["angular_z"], 0.0)

        stop_res = EdgeVoiceIntentParser.parse("快停下")
        self.assertEqual(stop_res["intent"], "STOP")
        self.assertEqual(stop_res["linear_x"], 0.0)
        self.assertEqual(stop_res["angular_z"], 0.0)

        dock_res = EdgeVoiceIntentParser.parse("回家充电")
        self.assertEqual(dock_res["intent"], "DOCK")


if __name__ == "__main__":
    unittest.main()
