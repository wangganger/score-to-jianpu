import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from validate_score import beats, midi, validate

FIXTURE = Path(__file__).resolve().parents[1] / "assets" / "example-score.json"


class ScoreChecks(unittest.TestCase):
    def setUp(self):
        self.score = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.first = self.score["voices"][0]["measures"][0]

    def fails(self, prefix):
        result = validate(self.score)
        self.assertFalse(result["ok"])
        self.assertTrue(any(e.startswith(prefix + ":") for e in result["errors"]), result)

    def test_valid_two_independent_voices(self):
        self.assertTrue(validate(self.score)["ok"])

    def test_missing_rest(self):
        self.score["voices"][1]["measures"][0]["events"].pop()
        self.fails("MEASURE_DURATION")

    def test_chord_assigned_to_one_player(self):
        self.first["events"][1]["pitches"] = ["D5", "F5", "A5"]
        self.fails("MONOPHONIC_CHORD")

    def test_pitched_rest(self):
        self.score["voices"][1]["measures"][0]["events"][1]["pitches"] = ["C4"]
        self.fails("PITCHED_REST")

    def test_wrong_octave_mapping(self):
        self.first["events"][0]["jianpu"][0]["octave"] = 0
        self.fails("JIANPU_PITCH")

    def test_accidental_mapping(self):
        self.first["events"][0].update(pitches=["C#5"], jianpu=[{"degree": 1, "octave": 1, "alter": 1}])
        self.assertTrue(validate(self.score)["ok"])

    def test_wrong_tie_pitch(self):
        self.score["voices"][0]["measures"][1]["events"][0]["pitches"] = ["F5"]
        self.fails("TIE_PITCH")

    def test_cross_voice_tie(self):
        self.score["connections"][0]["end"] = "b1"
        self.fails("CONNECTION_VOICE_OR_ORDER")

    def test_tie_skipping_intervening_event(self):
        self.score["connections"] = [{"kind": "tie", "start": "a2", "end": "a6"}]
        self.fails("TIE_NOT_ADJACENT")

    def test_same_pitch_slur_not_reclassified(self):
        self.score["connections"][0]["kind"] = "slur"
        self.assertTrue(validate(self.score)["ok"])

    def test_unresolved_is_not_silent_success(self):
        self.first["events"][1].update(kind="unresolved", pitches=[], source_pitches=["D5", "F5", "A5"])
        result = validate(self.score)
        self.assertFalse(result["ok"])
        self.assertTrue(result["warnings"])
        self.assertFalse(result["errors"])

    def test_editorial_rest_requires_approval(self):
        self.score["voices"][1]["measures"][0]["events"][1]["editorial"] = {"approved": False, "reason": "Example only"}
        self.fails("UNAPPROVED_EDIT")

    def test_approved_edit(self):
        self.score["voices"][1]["measures"][0]["events"][1]["editorial"] = {"approved": True, "reason": "Explicit test authorization"}
        self.assertTrue(validate(self.score)["ok"])

    def test_different_measure_order(self):
        self.score["voices"][1]["measures"].reverse()
        self.fails("VOICE_ALIGNMENT")

    def test_duplicate_event(self):
        self.first["events"][1]["id"] = "a1"
        self.fails("DUPLICATE_EVENT")

    def test_unexplained_short_bar(self):
        self.first["events"] = self.first["events"][:1]
        self.first["expected_beats"] = "1/2"
        self.fails("UNEXPLAINED_METER_EXCEPTION")

    def test_source_incomplete_remains_warning(self):
        for voice in self.score["voices"]:
            measure = voice["measures"][0]
            measure.update(expected_beats="1/2", exception={"kind": "source_incomplete", "reason": "Source missing remainder"})
            measure["events"] = [dict(measure["events"][0], duration="1/2")]
        self.score["connections"] = []
        result = validate(self.score)
        self.assertFalse(result["errors"])
        self.assertEqual(len(result["warnings"]), 2)

    def triplet(self):
        self.first["events"] = [
            {"id": f"t{i}", "kind": "note", "pitches": ["C5"], "duration": "1/3", "tuplet": "three"}
            for i in range(3)
        ] + [{"id": "after", "kind": "rest", "duration": "1"}]
        self.first["tuplets"] = [{"id": "three", "count": 3, "total_beats": "1"}]
        self.score["connections"] = []

    def test_exact_triplet(self):
        self.triplet()
        self.assertTrue(validate(self.score)["ok"])

    def test_triplet_wrong_total(self):
        self.triplet()
        self.first["tuplets"][0]["total_beats"] = "2"
        self.fails("TUPLET_DURATION")

    def test_triplet_not_contiguous(self):
        self.triplet()
        self.first["events"].insert(1, self.first["events"].pop())
        self.fails("TUPLET_CONTIGUITY")

    def test_float_duration_rejected(self):
        self.first["events"][0]["duration"] = 0.5
        self.fails("SCHEMA")

    def test_invalid_pitch_and_empty_input(self):
        self.assertEqual(midi("B#3"), midi("C4"))
        self.assertEqual(midi("Cbb4"), midi("Bb3"))
        with self.assertRaises(ValueError):
            midi("H4")
        with self.assertRaises(ValueError):
            beats("0")
        for value in ({}, [], None, {"meter": [2, 4], "voices": []}):
            self.assertTrue(validate(value)["errors"])

    def test_cli_exit_codes(self):
        validator = Path(__file__).with_name("validate_score.py")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "score.json"
            for mode in (0, 1, 2):
                data = copy.deepcopy(self.score)
                event = data["voices"][0]["measures"][0]["events"][1]
                if mode == 1:
                    event["duration"] = "3"
                if mode == 2:
                    event.update(kind="unresolved", pitches=[])
                target.write_text(json.dumps(data), encoding="utf-8")
                result = subprocess.run([sys.executable, str(validator), str(target)], capture_output=True, text=True)
                self.assertEqual(result.returncode, mode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
