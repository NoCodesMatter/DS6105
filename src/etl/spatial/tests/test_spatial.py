"""Tests for distances, the matching and coordinate rules, and the stage build (synthetic fixtures)."""
from __future__ import annotations

import contextlib
import csv
import io
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download
from core import (CROSSWALK, CROSSWALK_HEADER, GEO_HEADER, MAX_DISTANCE_M, NEA_HEADER, REVIEW_HEADER, ROOT,
                  SOURCES, contract, coordinate, geocoded_address_matches, haversine_m, load_sources, number,
                  proximity_class, sha256)
from pipeline import building_points, build, hawker_rows
from verify import distance_atan2, verify

NEA = [
    ("Alpha Food Centre", "1, Alpha Road, S(100001)", "HC", "Government", "10", "10", "0"),
    ("Blk 2 Beta Street", "Blk 2, Beta Street, S(100002)", "MHC", "HDB", "30", "20", "10"),
    ("Gamma Market", "3, Gamma Road, S(100003)", "MK", "Government", "5", "0", "5"),
]
GEO = [
    ("103.8", "1.3", "Alpha Food Centre", "1, Alpha Road, Singapore 100001"),
    ("103.81", "1.31", "Beta Street Blk 2 (Beta Market)", "Blk 2, Beta Street, Singapore\xa0100002"),
    ("103.9", "1.4", "Delta Hawker Centre", ""),
]


def cross(name, address, geo_name="", status="unmatched", approved=None, row=None, hawker_id=None):
    """One crosswalk row in WU's candidate format; matched rows are approved unless told otherwise."""
    ordinal = next((i for i, g in enumerate(GEO, 1) if g[2] == geo_name), "") if row is None else row
    geo_address = next((g[3] for g in GEO if g[2] == geo_name), "")
    approved = bool(geo_name) if approved is None else approved
    return (name, address, hawker_id or contract.hawker_id(name, address), status, ordinal, geo_name,
            geo_address, str(approved))


CROSS = [
    cross(*NEA[0][:2], "Alpha Food Centre", "exact_name_and_postcode"),
    cross(*NEA[1][:2], "Beta Street Blk 2 (Beta Market)", "postcode_only_review"),
    cross(*NEA[2][:2]),
]
HDB_GEO = [  # columns: index, blk_no, street, lat, lng, addr
    ("0", "1", "ALPHA RD", "1.3005", "103.8005", "1 ALPHA ROAD SINGAPORE 100011"),
    ("1", "2", "ALPHA RD", "1.301", "103.801", "2 ALPHA ROAD"),
    ("2", "5", "SHARED ST", "1.35", "103.85", "5 SHARED STREET"),   # same point as 6 OTHER ST and
    ("3", "6", "OTHER ST", "1.35", "103.85", "6 OTHER STREET"),     # both addresses agree: ambiguous
    ("4", "9", "WRONG RD", "1.44", "103.99", "9 WRONG ROAD"),       # rejected in the review file
    ("5", "7", "MOVED ST", "1.36", "103.86", "7 ELSEWHERE ROAD SOME CLUB SINGAPORE 509999"),
    ("6", "8", "OWNER RD", "1.37", "103.87", "8 OWNER ROAD"),       # GUEST RD's addr says this point
    ("7", "8", "GUEST RD", "1.37", "103.87", "8 OWNER ROAD"),       # is OWNER RD's, so OWNER keeps it
]
REVIEW = [("9", "WRONG RD", "reject", "point is in the wrong town")]
BUILDINGS = [("ALPHA", "1", "ALPHA RD"), ("ALPHA", "2", "ALPHA RD"), ("ALPHA", "7", "MISSING RD"),
             ("SHARED", "5", "SHARED ST"), ("WRONG", "9", "WRONG RD"), ("MOVED", "7", "MOVED ST"),
             ("OWNER", "8", "OWNER RD"), ("GUEST", "8", "GUEST RD")]


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


class Fixture:
    """A throwaway project root with frozen inputs and a completed HDB stage."""

    def __init__(self, temp, nea=NEA, geo=GEO, crosswalk=CROSS, review=REVIEW):
        self.root = Path(temp)
        raw = self.root / "data/raw/spatial"
        write_csv(raw / "d_68a42f09f350881996d83f9cd73ab02f.csv", NEA_HEADER, nea)
        write_csv(raw / "hawker_geo.csv", GEO_HEADER, geo)
        write_csv(raw / "hdb.csv", ("", "blk_no", "street", "lat", "lng", "addr"), HDB_GEO)
        self.crosswalk, self.review = self.root / "crosswalk.csv", self.root / "review.csv"
        write_csv(self.crosswalk, CROSSWALK_HEADER, crosswalk)
        write_csv(self.review, REVIEW_HEADER, review)
        self.manifest = self.root / "data/manifests/spatial_sources.json"
        self.manifest.parent.mkdir(parents=True)
        labels = {"nea_hawker_centres": "d_68a42f09f350881996d83f9cd73ab02f.csv", "hawker_geo": "hawker_geo.csv",
                  "hdb_geo": "hdb.csv"}
        self.manifest.write_text(json.dumps({"sources": [
            {"label": k, "path": f"data/raw/spatial/{v}", "sha256": sha256(raw / v)} for k, v in labels.items()]}))
        self.hdb_stage = self.root / "hdb_stage"
        rows = sorted((contract.building_id(b, s), t, b, s, "", "") for t, b, s in BUILDINGS)
        write_csv(self.hdb_stage / "hdb_building.csv", contract.CSV_COLUMNS["hdb_building"],
                  sorted(rows, key=lambda r: (r[2], r[3])))
        (self.hdb_stage / "manifest.json").write_text(json.dumps({
            "status": "ready_for_hdb_handoff", "stage": "fixture",
            "tables": {"hdb_building": {"sha256": sha256(self.hdb_stage / "hdb_building.csv")}}}))

    def build(self, name="spatial"):
        out = self.root / name
        with quiet():
            build(self.hdb_stage, out, name, self.manifest, self.crosswalk, self.review, self.root)
        return out

    def verify(self, out):
        with quiet():
            return verify(out, self.hdb_stage)


def rows(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class DistanceTests(unittest.TestCase):
    def test_zero_symmetry_and_one_degree(self):
        self.assertEqual(haversine_m(1.3, 103.8, 1.3, 103.8), 0.0)
        self.assertEqual(haversine_m(1.3, 103.8, 1.4, 103.9), haversine_m(1.4, 103.9, 1.3, 103.8))
        self.assertAlmostEqual(haversine_m(0, 0, 1, 0), 6371008.8 * math.pi / 180, places=6)
        antipode = haversine_m(0, 0, 0, 180)  # the clamp keeps this finite
        self.assertAlmostEqual(antipode, 6371008.8 * math.pi, places=3)
        self.assertLessEqual(antipode, MAX_DISTANCE_M)

    def test_matches_independent_formula_in_singapore(self):
        rng = random.Random(6103)
        for _ in range(2000):
            a = (rng.uniform(1.2, 1.47), rng.uniform(103.6, 104.05))
            b = (rng.uniform(1.2, 1.47), rng.uniform(103.6, 104.05))
            self.assertLess(abs(haversine_m(*a, *b) - distance_atan2(*a, *b)), 1e-6)

    def test_class_boundaries_follow_the_contract(self):
        for distance, expected in ((0, "near"), (499.999999, "near"), (500, "medium"), (999.999999, "medium"),
                                   (1000, "far"), (MAX_DISTANCE_M, "far"), (-0.1, None), (MAX_DISTANCE_M + 1, None)):
            self.assertEqual(proximity_class(distance), expected, distance)

    def test_coordinate_validation_and_float_text(self):
        for bad in (("nan", "103.8"), ("1.3", "inf"), ("0", "0"), ("1.3", "100.0"), ("2.0", "103.8")):
            with self.assertRaises(ValueError):
                coordinate(*bad)
        lat, lon = coordinate("1.29509740789339", "103.85406834457")
        self.assertEqual((number(lat), number(lon)), ("1.29509740789339", "103.85406834457"))
        self.assertEqual(number(None), "")


class AddressCheckTests(unittest.TestCase):
    def test_real_hdb_csv_addresses(self):
        cases = [  # (block, street, hdb.csv addr, should the point be used?)
            ("51", "KENT RD", "51 KENT ROAD KENT VILLE SINGAPORE 210051", True),
            ("128", "LOR 1 TOA PAYOH", "128 LORONG 1 TOA PAYOH", True),
            ("1", "BEDOK STH AVE 1", "1 BEDOK SOUTH AVENUE 1 SINGAPORE 460001", True),
            ("2", "ST. GEORGE'S RD", "2 SAINT GEORGE'S ROAD SINGAPORE 328023", True),
            ("1", "ST. GEORGE'S RD", "1 SAINT GEORGE'S LANE RESIDENCE @ ST GEORGE SINGAPORE 328047", False),
            ("2", "BEACH RD", "2 ANDOVER ROAD CHANGI BEACH CLUB SINGAPORE 509984", False),
            ("39", "JLN TIGA", "39 JALAN BINTANG TIGA OPERA ESTATE SINGAPORE 457778", False),
            ("21", "HOUGANG AVE 3", "211 HOUGANG STREET 21 OCBC HOUGANG AVE 3 - CHEERS SINGAPORE 530211", False),
            ("215", "CHOA CHU KANG CTRL", "BLK 216 AND 215 CHOA CHU KANG CENTRAL", False),
        ]
        for block, street, addr, expected in cases:
            self.assertEqual(geocoded_address_matches(block, street, addr), expected, (block, street))


class MatchingTests(unittest.TestCase):
    def test_crosswalk_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            hawkers, issues, geo_records = hawker_rows(load_sources(fx.manifest, fx.root), fx.crosswalk)
            self.assertEqual((len(hawkers), geo_records), (3, 3))
            by_name = {h[1]: h for h in hawkers}
            self.assertEqual(by_name["ALPHA FOOD CENTRE"][3:], (0, 1.3, 103.8))
            self.assertEqual(by_name["GAMMA MARKET"][3:], (5, None, None))  # unknown place, known stall count
            self.assertEqual(by_name["BLK 2 BETA STREET"][0],
                             contract.hawker_id("Blk 2 Beta Street", "Blk 2, Beta Street, S(100002)"))
            self.assertEqual(sorted(i[4] for i in issues), ["geo_record_not_in_nea_inventory", "no_hawker_geo_record"])

    def test_crosswalk_failures(self):
        gamma = ("Gamma Market", "3, Gamma Road, S(100001)")  # shares Alpha's postcode
        cases = {
            "without a reviewed crosswalk entry": {"crosswalk": CROSS[:2]},
            "more than one NEA centre": {"nea": NEA[:2] + [gamma + NEA[2][2:]],
                                         "crosswalk": CROSS[:2] + [cross(*gamma, "Alpha Food Centre", "postcode_only_review")]},
            "postcodes disagree": {"geo": [GEO[0], ("103.81", "1.31", GEO[1][2], "Blk 2, Beta Street, Singapore 100099"),
                                           GEO[2]]},
            "Invalid market produce stall count": {"nea": NEA[:2] + [NEA[2][:6] + ("",)]},
            "status and geo_name disagree": {"crosswalk": CROSS[:2] + [cross(*NEA[2][:2], status="postcode_only_review")]},
            "not approved": {"crosswalk": [cross(*NEA[0][:2], "Alpha Food Centre", "exact_name_and_postcode",
                                                 approved=False)] + CROSS[1:]},
            "hawker_id does not follow": {"crosswalk": [cross(*NEA[0][:2], "Alpha Food Centre", "exact_name_and_postcode",
                                                              hawker_id=contract.hawker_id("x", "y"))] + CROSS[1:]},
            "row number does not match": {"crosswalk": [cross(*NEA[0][:2], "Alpha Food Centre", "exact_name_and_postcode",
                                                              row=2)] + CROSS[1:]},
        }
        for message, change in cases.items():
            with self.subTest(message), tempfile.TemporaryDirectory() as temp:
                fx = Fixture(temp, **change)
                with self.assertRaisesRegex(ValueError, message):
                    hawker_rows(load_sources(fx.manifest, fx.root), fx.crosswalk)

    def test_coordinate_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            points, rejected = building_points(load_sources(fx.manifest, fx.root), fx.review)
            self.assertEqual(len(points), 8)
            reasons = {key: reason for key, (reason, _) in rejected.items()}
            self.assertEqual(reasons, {
                ("5", "SHARED ST"): "ambiguous_source_coordinate",
                ("6", "OTHER ST"): "ambiguous_source_coordinate",
                ("9", "WRONG RD"): "rejected_by_coordinate_review",
                ("7", "MOVED ST"): "geocoded_to_other_address",
                ("8", "GUEST RD"): "geocoded_to_other_address",
            })  # 8 OWNER RD keeps the point it shared with GUEST RD

    def test_review_entry_must_not_repeat_a_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp, review=REVIEW + [("7", "MOVED ST", "reject", "already caught by the address check")])
            with self.assertRaisesRegex(ValueError, "redundant"):
                building_points(load_sources(fx.manifest, fx.root), fx.review)

    def test_changed_input_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            with (fx.root / "data/raw/spatial/hawker_geo.csv").open("a", encoding="utf-8") as f:
                f.write("103.95,1.35,Late Edit,\n")
            with self.assertRaises(ValueError):
                load_sources(fx.manifest, fx.root)
            with quiet(), self.assertRaises(ValueError):
                download.acquire(fx.manifest, fx.root)  # never re-freezes a changed local file


class DownloadTests(unittest.TestCase):
    def test_fetch_retries_resets_but_not_client_errors(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        calls = []

        def flaky(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise ConnectionResetError(54, "Connection reset by peer")
            return Response(b'{"ok": true}')

        out = io.StringIO()
        with mock.patch.object(download.urllib.request, "urlopen", flaky), \
                mock.patch.object(download.time, "sleep"), contextlib.redirect_stdout(out):
            self.assertEqual(download.fetch("https://example.test/file.csv?X-Amz-Signature=secret"), {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertNotIn("secret", out.getvalue())

        def missing(request, timeout):
            calls.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        calls.clear()
        with mock.patch.object(download.urllib.request, "urlopen", missing), \
                mock.patch.object(download.time, "sleep"), self.assertRaises(urllib.error.HTTPError):
            download.fetch("https://example.test/missing.csv")
        self.assertEqual(len(calls), 1)


class StageTests(unittest.TestCase):
    def test_build_keeps_ids_and_writes_a_complete_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            out = fx.build()
            source = rows(fx.hdb_stage / "hdb_building.csv")
            built = rows(out / "hdb_building.csv")
            self.assertEqual([r["building_id"] for r in built], [r["building_id"] for r in source])
            located = {r["block"] + " " + r["street_name"] for r in built if r["latitude"]}
            self.assertEqual(located, {"1 ALPHA RD", "2 ALPHA RD", "8 OWNER RD"})
            issues = {(r["key"], r["issue"]) for r in rows(out / "diagnostics.csv")}
            self.assertLessEqual({("7 MISSING RD", "no_hdb_geo_record"), ("5 SHARED ST", "ambiguous_source_coordinate"),
                                  ("9 WRONG RD", "rejected_by_coordinate_review"),
                                  ("8 GUEST RD", "geocoded_to_other_address")}, issues)
            pairs = rows(out / "building_hawker.csv")
            self.assertEqual(len(pairs), 3 * 2)
            self.assertEqual([(p["building_id"], p["hawker_id"]) for p in pairs],
                             sorted((p["building_id"], p["hawker_id"]) for p in pairs))
            self.assertEqual(fx.verify(out)["building_hawker_pairs"], 6)

    def test_deterministic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            first, second = fx.build("one"), fx.build("two")
            for name in ("hdb_building.csv", "hawker_centre.csv", "building_hawker.csv", "diagnostics.csv"):
                self.assertEqual(sha256(first / name), sha256(second / name), name)
            with self.assertRaises(ValueError):
                fx.build("one")

    def test_verify_recomputes_distances(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            out = fx.build()
            path = out / "building_hawker.csv"
            lines = path.read_text(encoding="utf-8").splitlines()
            bid, hid, distance = lines[1].split(",")
            lines[1] = f"{bid},{hid},{number(float(distance) + 0.5)}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):  # caught by the hash check
                fx.verify(out)
            manifest = json.loads((out / "manifest.json").read_text())
            manifest["tables"]["building_hawker"].update(sha256=sha256(path), bytes=path.stat().st_size)
            (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Distance differs"):  # and by recomputation
                fx.verify(out)

    def test_rejects_unfinished_hdb_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            fx = Fixture(temp)
            (fx.hdb_stage / "manifest.json").write_text(json.dumps({"status": "failed"}))
            with self.assertRaises(ValueError):
                fx.build()


@unittest.skipUnless(all((ROOT / "data/raw/spatial" / name).exists() for name in (
    "d_68a42f09f350881996d83f9cd73ab02f.csv", "hawker_geo.csv", "hdb.csv")), "frozen spatial inputs not present")
class FrozenInputTests(unittest.TestCase):
    def test_approved_crosswalk_covers_the_nea_inventory(self):
        hawkers, _, geo_records = hawker_rows(load_sources(SOURCES), CROSSWALK)
        self.assertEqual((len(hawkers), geo_records), (107, 129))
        self.assertEqual(sum(h[4] is not None for h in hawkers), 104)
        self.assertEqual(sum(h[3] > 0 and h[4] is not None for h in hawkers), 81)


if __name__ == "__main__":
    unittest.main()
