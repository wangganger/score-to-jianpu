"""Read-only checks for resolved, voice-separated transcription data.

This does not recognize a score image, infer instrumentation, or engrave a PDF.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import re


def beats(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:/[1-9]\d*)?", value):
        raise ValueError("duration must be an exact positive rational string")
    result = Fraction(value)
    if result <= 0:
        raise ValueError("duration must be positive")
    return result


def midi(value):
    if not isinstance(value, str):
        raise ValueError("pitch must be a string")
    match = re.fullmatch(r"([A-G])(bb|##|b|#)?(-?\d+)", value)
    if not match:
        raise ValueError(f"invalid resolved pitch: {value!r}")
    letter, accidental, octave = match.groups()
    shift = {None: 0, "#": 1, "##": 2, "b": -1, "bb": -2}[accidental]
    return 12 * (int(octave) + 1) + {"C": 0, "D": 2, "E": 4, "F": 5,
                                          "G": 7, "A": 9, "B": 11}[letter] + shift


def identifier(obj):
    value = obj.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("id must be a nonempty string")
    return value


def array(obj, key, required=False):
    value = obj.get(key, [])
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{key} must be {'a nonempty' if required else 'an'} array")
    return value


def validate(document):
    errors, warnings = [], []
    events, voice_ids = {}, set()
    baseline = None
    event_count = 0
    try:
        meter = document["meter"]
        if (not isinstance(meter, list) or len(meter) != 2 or
                any(type(n) is not int or n <= 0 for n in meter) or
                meter[1] & (meter[1] - 1)):
            raise ValueError("meter must have a positive numerator and power-of-two denominator")
        regular = Fraction(meter[0] * 4, meter[1])
        voices = array(document, "voices", required=True)
        for voice in voices:
            vid = identifier(voice)
            if vid in voice_ids:
                errors.append(f"DUPLICATE_VOICE: {vid}")
            voice_ids.add(vid)
            tonic = midi(voice["tonic"])
            if voice.get("pitch_basis") not in ("written", "concert"):
                errors.append(f"PITCH_BASIS: {vid} must specify written or concert")
            mono = voice.get("monophonic", True)
            if type(mono) is not bool:
                raise ValueError("monophonic must be boolean")
            scale = voice.get("scale", [0, 2, 4, 5, 7, 9, 11])
            if not isinstance(scale, list) or len(scale) != 7 or any(type(n) is not int for n in scale):
                raise ValueError("scale must contain seven integer semitone offsets")
            measure_ids, shape = set(), []
            clock, sequence = Fraction(0), 0
            for measure in array(voice, "measures", required=True):
                mid = identifier(measure)
                where = f"{vid}/{mid}"
                if mid in measure_ids:
                    errors.append(f"DUPLICATE_MEASURE: {where}")
                measure_ids.add(mid)
                expected = regular
                if "expected_beats" in measure:
                    expected = beats(measure["expected_beats"])
                    exception = measure.get("exception", {})
                    if (exception.get("kind") not in ("pickup", "meter_change", "source_incomplete", "other")
                            or not isinstance(exception.get("reason"), str) or not exception["reason"].strip()):
                        errors.append(f"UNEXPLAINED_METER_EXCEPTION: {where}")
                    elif exception["kind"] == "source_incomplete":
                        warnings.append(f"SOURCE_INCOMPLETE: {where}: {exception['reason']}")
                shape.append((mid, expected))
                offset = Fraction(0)
                members = {}
                for local_index, event in enumerate(array(measure, "events", required=True)):
                    eid = identifier(event)
                    loc = f"{where}/{eid}"
                    if eid in events:
                        errors.append(f"DUPLICATE_EVENT: {eid}")
                    duration = beats(event["duration"])
                    kind = event.get("kind")
                    if kind not in ("note", "rest", "unresolved"):
                        errors.append(f"EVENT_KIND: {loc}")
                    names = array(event, "pitches")
                    pitches = [midi(p) for p in names]
                    if kind == "note" and not pitches:
                        errors.append(f"MISSING_PITCH: {loc}")
                    if kind == "rest" and pitches:
                        errors.append(f"PITCHED_REST: {loc}")
                    if mono and len(pitches) > 1:
                        errors.append(f"MONOPHONIC_CHORD: {loc}: {names}")
                    if kind == "unresolved":
                        warnings.append(f"UNRESOLVED: {loc}")
                        if pitches:
                            errors.append(f"UNRESOLVED_HAS_ASSIGNED_PITCH: {loc}")
                    if "editorial" in event:
                        ed = event["editorial"]
                        if (ed.get("approved") is not True or
                                not isinstance(ed.get("reason"), str) or not ed["reason"].strip()):
                            errors.append(f"UNAPPROVED_EDIT: {loc}")
                    if "jianpu" in event:
                        numbered = array(event, "jianpu")
                        if kind != "note" or len(numbered) != len(pitches):
                            errors.append(f"JIANPU_COUNT: {loc}")
                        else:
                            for p, number in zip(pitches, numbered):
                                degree = number.get("degree")
                                octave = number.get("octave", 0)
                                alter = number.get("alter", 0)
                                if (type(degree) is not int or not 1 <= degree <= 7 or
                                        type(octave) is not int or type(alter) is not int):
                                    errors.append(f"JIANPU_FORMAT: {loc}")
                                elif tonic + scale[degree - 1] + 12 * octave + alter != p:
                                    errors.append(f"JIANPU_PITCH: {loc}")
                    group = event.get("tuplet")
                    if group is not None:
                        if not isinstance(group, str) or not group:
                            raise ValueError("tuplet ID must be a nonempty string")
                        members.setdefault(group, []).append((local_index, duration))
                    events[eid] = {"voice": vid, "sequence": sequence, "kind": kind,
                                   "pitches": pitches, "time": clock + offset, "duration": duration}
                    offset += duration
                    sequence += 1
                    event_count += 1
                if offset != expected:
                    errors.append(f"MEASURE_DURATION: {where}: {offset} != {expected}")
                definitions = {}
                for group in array(measure, "tuplets"):
                    gid = identifier(group)
                    if gid in definitions:
                        errors.append(f"DUPLICATE_TUPLET: {where}/{gid}")
                    definitions[gid] = group
                for gid in sorted(set(definitions) | set(members)):
                    group = definitions.get(gid)
                    values = members.get(gid, [])
                    if group is None or not values:
                        errors.append(f"TUPLET_DEFINITION: {where}/{gid}")
                        continue
                    count = group.get("count")
                    if type(count) is not int or count < 2 or len(values) != count:
                        errors.append(f"TUPLET_COUNT: {where}/{gid}")
                    if sum((d for _, d in values), Fraction(0)) != beats(group["total_beats"]):
                        errors.append(f"TUPLET_DURATION: {where}/{gid}")
                    indices = [i for i, _ in values]
                    if indices != list(range(indices[0], indices[-1] + 1)):
                        errors.append(f"TUPLET_CONTIGUITY: {where}/{gid}")
                clock += expected
            if baseline is None:
                baseline = shape
            elif shape != baseline:
                errors.append(f"VOICE_ALIGNMENT: {vid}: measure IDs/order/lengths differ")
        for relation in array(document, "connections"):
            a, b = events.get(relation.get("start")), events.get(relation.get("end"))
            loc = f"{relation.get('start')} -> {relation.get('end')}"
            kind = relation.get("kind")
            if kind not in ("tie", "slur"):
                errors.append(f"CONNECTION_KIND: {loc}")
            if a is None or b is None:
                errors.append(f"CONNECTION_ENDPOINT: {loc}")
                continue
            if a["voice"] != b["voice"] or a["sequence"] >= b["sequence"]:
                errors.append(f"CONNECTION_VOICE_OR_ORDER: {loc}")
            if a["kind"] != "note" or b["kind"] != "note":
                errors.append(f"CONNECTION_NON_NOTE: {loc}")
            if kind == "tie":
                if sorted(a["pitches"]) != sorted(b["pitches"]):
                    errors.append(f"TIE_PITCH: {loc}")
                if (b["sequence"] != a["sequence"] + 1 or
                        b["time"] != a["time"] + a["duration"]):
                    errors.append(f"TIE_NOT_ADJACENT: {loc}")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append(f"SCHEMA: {exc}")
    return {"ok": not errors and not warnings, "errors": errors, "warnings": warnings,
            "voices": len(voice_ids), "events": event_count,
            "scope": "Data consistency only; source reading, voice allocation and PDF layout require review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path)
    args = parser.parse_args()
    try:
        report = validate(json.loads(args.score.read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report = {"ok": False, "errors": [f"INPUT: {exc}"], "warnings": []}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 2 if report["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
