"""Adversarial readback checks using tiny valid MCAPs from the real source episode."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from mcap.opcode import Opcode
from mcap.reader import make_reader
from mcap.stream_reader import CRCValidationError
from mcap.writer import Writer

from verify_so101_mcap import sha, verify


FIXTURE = os.environ.get("SO101_RECORDED_FIXTURE")


@unittest.skipUnless(FIXTURE, "Set SO101_RECORDED_FIXTURE to the independently bound real conversion")
class ReadbackSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Path(FIXTURE)
        cls.manifest = json.loads((cls.fixture / "manifest.json").read_text())
        cls.records = []
        with (cls.fixture / "so101.mcap").open("rb") as stream:
            for schema, channel, record in make_reader(stream, validate_crcs=True).iter_messages():
                cls.records.append((schema, channel, record))
                if channel.topic == "/so101/episode":
                    break
        if len(cls.records) != 3:
            raise AssertionError("Expected the original joints/contact/episode prefix")

    def tiny_mcap(self, change=None):
        output = io.BytesIO()
        writer = Writer(output, enable_data_crcs=True)
        writer.start()
        for schema, channel, record in self.records:
            sid = writer.register_schema(schema.name, schema.encoding, schema.data)
            cid = writer.register_channel(channel.topic, channel.message_encoding, sid, channel.metadata)
            data = json.loads(record.data)
            if channel.topic == "/so101/episode" and change is not None:
                change(data)
            writer.add_message(cid, record.log_time, json.dumps(data).encode(), record.publish_time, record.sequence)
        writer.finish()
        return output.getvalue()

    def fixture_directory(self, path, mcap_bytes, manifest=None):
        path = Path(path)
        record = copy.deepcopy(manifest if manifest is not None else self.manifest)
        (path / "so101.mcap").write_bytes(mcap_bytes)
        record["mcap_sha256"] = sha(path / "so101.mcap")
        (path / "manifest.json").write_text(json.dumps(record))
        return path

    def test_every_report_metric_is_checked_even_with_valid_crcs_and_hash(self):
        fields = ("wall_s", "physical_lift_passed", "place_verified", "controller_done",
                  "settled_duration_s", "max_xy_drift_m", "post_detach_peak_force_n")
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory(dir=Path(__file__).parent / "output") as temp:
                def change(message):
                    value = message["metrics"][field]
                    message["metrics"][field] = not value if isinstance(value, bool) else value + 1
                directory = self.fixture_directory(temp, self.tiny_mcap(change))
                with self.assertRaisesRegex(ValueError, "Original report metrics changed"):
                    verify(directory)

    def test_true_message_flag_cannot_replace_the_four_original_bindings(self):
        relations = (("trace_sha256", "report_to_trace"), ("source_adapter_sha256", "report_to_recorder"),
                     ("full_cycle_adapter_sha256", "report_to_cycle_source"), (None, "independent_to_report"))
        for report_field, relation in relations:
            with self.subTest(relation=relation), tempfile.TemporaryDirectory(dir=Path(__file__).parent / "output") as temp:
                directory = Path(temp)
                manifest = copy.deepcopy(self.manifest)
                report = json.loads(Path(manifest["input_paths"]["report"]).read_text())
                independent = json.loads(Path(manifest["input_paths"]["independent"]).read_text())
                if report_field is not None:
                    report[report_field] = "0" * 64
                (directory / "report.json").write_text(json.dumps(report))
                # Keep all other edges internally consistent, isolating the selected broken edge.
                independent["report_sha256"] = "0" * 64 if report_field is None else sha(directory / "report.json")
                (directory / "independent.json").write_text(json.dumps(independent))
                for key, filename in (("report", "report.json"), ("independent", "independent.json")):
                    manifest["input_paths"][key] = str(directory / filename)
                    manifest["input_sha256"][key] = sha(directory / filename)
                self.fixture_directory(directory, self.tiny_mcap(), manifest)
                with self.assertRaisesRegex(ValueError, f"Original source binding mismatch: {relation}"):
                    verify(directory)

    def test_message_source_bound_must_equal_independently_recomputed_truth(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / "output") as temp:
            data = self.tiny_mcap(lambda message: message["provenance"].update(source_bound=False))
            directory = self.fixture_directory(temp, data)
            with self.assertRaisesRegex(ValueError, "source_bound differs from recomputed"):
                verify(directory)

    def test_bad_data_end_crc_is_rejected_when_seeking_reader_still_accepts_chunks(self):
        data = bytearray(self.tiny_mcap())
        offset = 8
        while offset < len(data) - 8:
            opcode, length = struct.unpack_from("<BQ", data, offset)
            if opcode == Opcode.DATA_END:
                crc = struct.unpack_from("<I", data, offset + 9)[0]
                self.assertNotEqual(crc, 0)
                struct.pack_into("<I", data, offset + 9, crc ^ 1)
                break
            offset += 9 + length
        else:
            self.fail("Official Writer did not produce DataEnd")
        # Recompute the outer SHA and prove the old seek-only CRC check accepts this file.
        self.assertEqual(len(list(make_reader(io.BytesIO(data), validate_crcs=True).iter_messages())), 3)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / "output") as temp:
            directory = self.fixture_directory(temp, data)
            with self.assertRaises(CRCValidationError):
                verify(directory)


if __name__ == "__main__":
    unittest.main()
