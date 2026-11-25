"""Tests for the values per car category: tune.car_category (the rules), tune.car_ranges (what every car of the game package stores, by category, with the drift presets, skipped cars, the temporary folder, the cache and the one computation at a time), tune.car_range_data and the route GET /api/car_ranges of tools/tuner_server.py.

No game data and no schemas: the game package is a small package packed by kspkg.cmd_pack with placeholder files, system\\cars.table is replaced by the rows of a stub for tune.cars_table_lines, and tune.load_msg is replaced by a reader of in-memory messages keyed by the path below content\\cars (so the cars are resolved from the temporary folder like real ones).
"""
import contextlib
import copy
import io
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from support import Sandbox, mini_catalogue, mini_setting

import car_json
import kspkg
import tune
import tuner_server as ts
from test_tuner_server import TuneCase

REAL_CAR_RANGES = tune.car_ranges
REAL_COMPUTE = tune.compute_car_ranges
REAL_RESOLVE = tune.resolve_defaults
EMPTY = {"categories": [], "by_category": {}, "skipped": []}


def gp(car, rel):
    return "content\\cars\\%s\\%s" % (car, rel.replace("/", "\\"))


# (id, display name, property_1, property_2, property_3, tags, mass, limiter, diff, abs, variants [(id, note, limiter, with parts)])
CARS = [
    ("ks_fm", "Alpha FM", None, None, None, ["rwd", "front_engine"], 1400.5, 7000, "LSD", True, []),
    ("ks_fm2", "Alpha Two", None, None, None, ["rwd", "front_engine"], 1200.0, 8000, "Spool", False, []),
    ("ks_fc", "Beta FC", None, "Property2_Vintage", None, ["rwd", "front_engine"], 1100.0, 6500, None, False, []),
    ("ks_mr", "Gamma MR", None, None, None, ["rwd"], 1300.0, None, None, None, []),
    ("ks_mr2", "Gamma Two", None, None, None, ["rwd"], 1350.0, 9000, None, True, []),
    ("ks_noeng", "Odd", None, None, None, ["rwd"], 1250.0, "no engine file", None, None, []),
    ("ks_awd", "Delta AWD", None, None, None, ["awd", "rwd", "front_engine"], 1600.0, 7500, "Torsen", None, []),
    ("ks_fwd", "Echo FWD", None, None, None, ["front_engine"], 1000.0, 6800, None, None, []),
    ("ks_ev", "Foxtrot EV", None, None, "Property3_EV", ["awd"], 1900.0, 15000, None, None, []),
    ("ks_gt4", "Golf GT4", "Property1_Track", None, None, ["gt4"], 1500.0, 7300, None, None, []),
    ("ks_gt3", "Hotel GT3", "Property1_Race", None, None, ["gt3", "gt2"], 1300.0, 7400, None, None, []),
    ("ks_gt2", "India GT2", "Property1_Race", None, None, ["gt4", "gt2"], 1250.0, 7600, None, None, []),
    ("ks_cup", "Juliet Cup", "Property1_Race", None, None, [], 1100.0, 7700, None, None, []),
    ("ks_form", "Kilo Formula", "Property1_Race", None, None, ["formula", "gt3"], 700.0, None, None, None, []),
    ("ks_dr", "Drift Car", None, None, None, ["rwd", "front_engine"], 1500.0, 7200, None, True,
     [("q_drift", "Drift", 9000, True), ("q_race", "Race", 7777, True), ("q_broken", "Drift broken", 5000, False)]),
    ("ks_dr2", "Drift Two", None, None, None, [], 1111.0, 6000, None, None, [("q_big", "BIG DRIFT pack", 8800, True)]),
    ("ks_none", "No Files", None, None, None, [], 1000.0, 6000, None, None, []),
]
ORDER = ["rwd_front_modern", "rwd_front_classic", "rwd_mid_rear", "awd", "fwd", "electric", "gt4", "gt3", "gt2", "race_other", "formula", "drift"]
LABELS = ["Front RWD modern", "Front RWD classic", "Mid/rear RWD", "AWD road", "FWD road", "Electric", "GT4", "GT3", "GT2", "Cup/other race",
          "Formula", "Drift"]
MEMBERS = {"rwd_front_modern": ["Alpha FM", "Alpha Two", "Drift Car"], "rwd_front_classic": ["Beta FC"], "rwd_mid_rear": ["Gamma MR", "Gamma Two", "Odd"],
           "awd": ["Delta AWD"], "fwd": ["Drift Two", "Echo FWD"], "electric": ["Foxtrot EV"], "gt4": ["Golf GT4"], "gt3": ["Hotel GT3"],
           "gt2": ["India GT2"], "race_other": ["Juliet Cup"], "formula": ["Kilo Formula"],
           "drift": ["Drift Car (Drift)", "Drift Two (BIG DRIFT pack)"]}


def table_row(car):
    cid, name, p1, p2, p3, tags = car[:6]
    row = {"name": cid, "display_name": name, "brand": "B", "year": 2000, "sub_categories": [{"categories": ["CarCategoryEnum_" + t for t in tags[:2]]},
                                                                                           {"categories": ["CarCategoryEnum_" + t for t in tags[2:]]}]}
    row.update({k: v for k, v in (("property_1", p1), ("property_2", p2), ("property_3", p3)) if v})
    return row


def car_objects():
    """{path below content\\cars (lower case, /): the message the stub load_msg returns}; the placeholder files of the package have the same names."""
    out = {}
    for cid, name, p1, p2, p3, tags, mass, limiter, diff, abs_on, variants in CARS:
        if cid == "ks_none":
            continue
        car = {"engine_path": gp(cid, "data/nope.carengine" if limiter == "no engine file" else "data/engine.carengine"),
               "drivetrain_path": gp(cid, "data/d.drivetrain"), "stock_setup": gp(cid, "data/s.carsetup"), "mass": mass}
        if abs_on is not None:
            car["abs"] = abs_on
        engine = {"turbos_to_load": []}
        if isinstance(limiter, int):
            engine["limiter"] = limiter
        out[cid + "/data/x.car"] = car
        out[cid + "/data/engine.carengine"] = engine
        out[cid + "/data/d.drivetrain"] = {"differential_data": {"type": diff} if diff else {}}
        out[cid + "/data/s.carsetup"] = {"electronics": {"tc1": 2}}
        out[cid + "/presets/p.mechanicalcarpreset"] = {"brand": "Brand", "description": "Name Preset Base"}
        for vid, note, vlimiter, with_parts in variants:
            out["%s/presets/%s.mechanicalcarpreset" % (cid, vid)] = {
                "note": note, "description": "Name Preset " + vid,
                "forced_compatible_part_paths": [gp(cid, "presets/parts/%s_engine.compatiblepart" % vid)]}
            if with_parts:
                out["%s/presets/parts/%s_engine.compatiblepart" % (cid, vid)] = {"car_part_path": gp(cid, "presets/parts/%s_engine.carpart" % vid)}
                out["%s/presets/parts/%s_engine.carpart" % (cid, vid)] = {"logic_parts": [{"tuning_part_path": gp(cid, "data/parts/%s_engine.tuningpart" % vid)}]}
                out["%s/data/parts/%s_engine.tuningpart" % (cid, vid)] = {"engine": {"path": gp(cid, "data/%s.carengine" % vid)}}
                out["%s/data/%s.carengine" % (cid, vid)] = {"limiter": vlimiter, "turbos_to_load": []}
    return out


OBJECTS = car_objects()
EXTRA_FILES = ["ks_fm/ks_fm.actor", "ks_fm/ui/icon.png", "ks_fm/data/readme.txt", "ks_dr/sub/dr.actor", "ks_other/data/x.car", "ks_other/ks_other.actor",
               "common_phsx/tyres/road/a.tyre"]


def fake_load_msg(path):
    name = car_json.message_for(path)
    parts = os.path.normpath(kspkg.plain_path(os.fspath(path))).replace("\\", "/").lower().split("/")
    i = max(k for k in range(len(parts) - 1) if parts[k] == "content" and parts[k + 1] == "cars")
    obj = OBJECTS.get("/".join(parts[i + 2:]))
    if obj is None:
        raise ValueError("%s: no stub content" % path)
    return copy.deepcopy(obj), name


def pack_world(dst, with_table=True):
    src = tempfile.mkdtemp()
    try:
        files = {"content/cars/" + rel: b"x " + rel.encode() for rel in list(OBJECTS) + EXTRA_FILES}
        if with_table:
            files["system/cars.table"] = b"table"
        for rel, data in files.items():
            path = os.path.join(src, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        with contextlib.redirect_stdout(io.StringIO()):
            kspkg.cmd_pack(src, dst)
    finally:
        shutil.rmtree(src)


PACKAGES = {}


def setUpModule():
    PACKAGES["dir"] = tempfile.mkdtemp()
    PACKAGES["full"] = os.path.join(PACKAGES["dir"], "full.kspkg")
    pack_world(PACKAGES["full"])


def tearDownModule():
    shutil.rmtree(PACKAGES["dir"], ignore_errors=True)


def settings():
    return [mini_setting("limiter", type="int", targets=[("@engine", "limiter")]),
            mini_setting("mass", targets=[("@car", "mass")]),
            mini_setting("abs_on", type="bool", targets=[("@car", "abs")]),
            mini_setting("aids_off", kind="flag", type="bool", value=0, targets=[("@setup", "electronics.tc1")]),
            mini_setting("diff_type", type="enum", choices=["Spool", "LSD", "Torsen"], targets=[("@drivetrain", "differential_data.type")]),
            mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix"),
            mini_setting("tyre_dy_front", group="Tyres", targets=[("@tyre_front", "modelData.Dy0")])]


def snapshot(folder):
    """{relative path: bytes} of every file below folder."""
    out = {}
    for dp, _, names in os.walk(folder):
        for n in names:
            with open(os.path.join(dp, n), "rb") as f:
                out[os.path.relpath(os.path.join(dp, n), folder)] = f.read()
    return out


class World(Sandbox):
    """A work folder with one installed car (ks_inst), the package of the module, the stub table of the cars and the stub reader of the car files."""

    def setUp(self):
        super().setUp()
        self.work, self.game = str(self.d / "work"), PACKAGES["full"]
        self.cat = mini_catalogue(*settings())
        self.lines = [{"car_content": table_row(c)} for c in CARS]
        self.write(os.path.join(self.work, "ks_inst", "base", "content", "cars", "ks_inst", "data", "x.car"), b"installed", binary=True)
        tune._car_ranges_loaded.clear()
        self.addCleanup(tune._car_ranges_loaded.clear)
        self.patch(tune, "load_msg", fake_load_msg)
        self.patch(tune, "cars_table_lines", lambda data: self.lines)
        self.computed = []
        self.patch(tune, "compute_car_ranges", lambda *a: self.computed.append(1) or REAL_COMPUTE(*a))
        self.tmp = os.path.join(self.work, tune.CAR_RANGES_TMP)
        self.cache = os.path.join(self.work, tune.CAR_RANGES_FILE)

    def ranges(self, cat=None, game=None, work=None):
        return tune.car_ranges(work or self.work, cat or self.cat, game or self.game)

    def spy(self):
        """Records what is on disk at every resolve of a car: the car folders and installed cars of the work folder, the files extracted of the car and the folders in the temporary folder."""
        seen = {"folders": [], "installed": [], "files": {}, "tmp": [], "calls": []}

        def resolve(work, car_id, *args, **kw):
            seen["folders"].append(tune.car_folders(self.work))
            seen["installed"].append(tune.installed_cars(self.work))
            seen["calls"].append((car_id, kw.get("variant")))
            seen["tmp"].append(sorted(os.listdir(self.tmp)))
            if car_id not in seen["files"]:
                folder = os.path.join(self.tmp, car_id)
                seen["files"][car_id] = sorted(os.path.relpath(os.path.join(dp, n), folder).replace(os.sep, "/")
                                               for dp, _, names in os.walk(folder) for n in names)
            return REAL_RESOLVE(work, car_id, *args, **kw)

        self.patch(tune, "resolve_defaults", resolve)
        return seen

    def entry(self, result, setting, category):
        return result["by_category"].get(setting, {}).get(category)


class TestFiniteNumber(unittest.TestCase):
    def test_finite_number(self):
        self.assertTrue(all(tune.finite_number(v) for v in (0, -3, 2.5, 1e300)))
        self.assertFalse(any(tune.finite_number(v) for v in (None, True, False, "1", [1], math.nan, math.inf, -math.inf)))


class TestCategoryRules(unittest.TestCase):
    def content(self, tags=(), p1=None, p2=None, p3=None, split=True):
        row = {"name": "ks_a", "sub_categories": ([{"categories": ["CarCategoryEnum_" + t]} for t in tags] if split else
                                                  [{"categories": ["CarCategoryEnum_" + t for t in tags]}])}
        row.update({k: v for k, v in (("property_1", p1), ("property_2", p2), ("property_3", p3)) if v})
        return row

    def test_every_rule_and_their_order(self):
        cases = [
            ("a car that is not a road car: formula first", dict(tags=["gt3", "formula", "gt2", "gt4"], p1="Property1_Race"), "formula"),
            ("gt3 before gt2 and gt4", dict(tags=["gt4", "gt2", "gt3"], p1="Property1_Race"), "gt3"),
            ("gt2 before gt4", dict(tags=["gt4", "gt2"], p1="Property1_Track"), "gt2"),
            ("gt4", dict(tags=["gt4", "rwd"], p1="Property1_Track"), "gt4"),
            ("race without a class tag", dict(tags=["rwd", "front_engine"], p1="Property1_Race"), "race_other"),
            ("race with an EV is still race", dict(tags=[], p1="Property1_Race", p3="Property3_EV"), "race_other"),
            ("an EV before awd", dict(tags=["awd", "rwd"], p3="Property3_EV"), "electric"),
            ("awd before rwd", dict(tags=["rwd", "awd", "front_engine"]), "awd"),
            ("no rwd tag is fwd", dict(tags=["front_engine"]), "fwd"),
            ("no tag at all is fwd", dict(tags=[]), "fwd"),
            ("front engine, modern", dict(tags=["rwd", "front_engine"], p2="Property2_Modern"), "rwd_front_modern"),
            ("front engine, property_2 left off is Modern", dict(tags=["rwd", "front_engine"]), "rwd_front_modern"),
            ("front engine, vintage", dict(tags=["rwd", "front_engine"], p2="Property2_Vintage"), "rwd_front_classic"),
            ("front engine, young timer", dict(tags=["rwd", "front_engine"], p2="Property2_YoungTimer"), "rwd_front_classic"),
            ("rwd without front engine", dict(tags=["rwd", "mid_engine"], p2="Property2_Vintage"), "rwd_mid_rear"),
            ("property_3 ICE is not electric", dict(tags=["rwd"], p3="Property3_ICE"), "rwd_mid_rear"),
        ]
        for name, kw, expected in cases:
            for split in (True, False):
                with self.subTest(name, split=split):
                    self.assertEqual(tune.car_category(self.content(split=split, **kw)), expected)

    def test_the_tags_are_the_categories_of_every_sub_category_without_the_prefix(self):
        row = {"sub_categories": [{"categories": ["CarCategoryEnum_rwd"]}, {}, {"categories": []}, {"categories": ["front_engine"]}]}
        self.assertEqual(tune.car_category(row), "rwd_front_modern")
        self.assertEqual(tune.car_category({}), "fwd")

    def test_the_order_and_the_labels(self):
        self.assertEqual([c[0] for c in tune.CAR_CATEGORIES], ORDER)
        self.assertEqual([c[1] for c in tune.CAR_CATEGORIES], LABELS)


class TestCarRanges(World):
    def test_the_categories_in_display_order_with_labels_totals_and_sorted_display_names(self):
        r = self.ranges()
        self.assertEqual([(c["id"], c["label"], c["total"]) for c in r["categories"]], [(i, l, len(MEMBERS[i])) for i, l in zip(ORDER, LABELS)])
        self.assertEqual({c["id"]: c["cars"] for c in r["categories"]}, MEMBERS)
        self.assertEqual(set(r), {"categories", "by_category", "skipped"})
        self.assertTrue(all(set(c) == {"id", "label", "total", "cars"} for c in r["categories"]))

    def test_only_categories_with_members_are_listed(self):
        self.lines = [l for l in self.lines if l["car_content"]["name"] in ("ks_gt3", "ks_fm")]
        self.assertEqual([c["id"] for c in self.ranges()["categories"]], ["rwd_front_modern", "gt3"])

    def test_a_car_that_cannot_be_read_is_skipped_and_not_counted(self):
        r = self.ranges()
        self.assertEqual([s["car"] for s in r["skipped"]], ["ks_none"])
        self.assertIn("no base car", r["skipped"][0]["reason"])
        self.assertNotIn(tune.CAR_RANGES_TMP, r["skipped"][0]["reason"])
        self.assertNotIn(self.work, r["skipped"][0]["reason"])
        self.assertNotIn("No Files", [n for c in r["categories"] for n in c["cars"]])
        self.assertEqual(next(c for c in r["categories"] if c["id"] == "fwd")["total"], 2)

    def test_a_numeric_entry_is_low_high_and_the_number_of_cars_that_store_the_setting(self):
        r = self.ranges()
        self.assertEqual(self.entry(r, "mass", "rwd_front_modern"), {"low": 1200.0, "high": 1500.0, "count": 3})
        self.assertEqual(self.entry(r, "mass", "awd"), {"low": 1600.0, "high": 1600.0, "count": 1})
        self.assertEqual(self.entry(r, "limiter", "rwd_front_modern"), {"low": 7000, "high": 8000, "count": 3})
        self.assertIsInstance(self.entry(r, "limiter", "rwd_front_modern")["low"], int)
        self.assertEqual(self.entry(r, "mass", "drift"), {"low": 1111.0, "high": 1500.0, "count": 2})

    def test_cars_that_do_not_store_or_have_the_setting_do_not_count(self):
        r = self.ranges()
        mid = next(c for c in r["categories"] if c["id"] == "rwd_mid_rear")
        self.assertEqual(mid["total"], 3)
        self.assertEqual(self.entry(r, "limiter", "rwd_mid_rear"), {"low": 9000, "high": 9000, "count": 1})
        self.assertEqual(self.entry(r, "mass", "rwd_mid_rear")["count"], 3)

    def test_a_category_in_which_no_car_has_the_setting_has_no_entry(self):
        r = self.ranges()
        self.assertNotIn("formula", r["by_category"]["limiter"])
        self.assertNotIn("awd", r["by_category"]["abs_on"])
        self.assertIn("gt3", r["by_category"]["limiter"])
        self.assertEqual(r["by_category"]["diff_type"].keys(), {"rwd_front_modern", "awd"})

    def test_a_bool_setting_lists_the_values_and_the_number_of_cars(self):
        r = self.ranges()
        self.assertEqual(self.entry(r, "abs_on", "rwd_front_modern"), {"values": [False, True], "count": 3})
        self.assertEqual(self.entry(r, "abs_on", "rwd_mid_rear"), {"values": [True], "count": 1})
        self.assertEqual(self.entry(r, "abs_on", "rwd_front_classic"), {"values": [False], "count": 1})

    def test_a_flag_setting_is_left_out(self):
        r = self.ranges()
        self.assertNotIn("aids_off", r["by_category"])

    def test_an_enum_setting_lists_the_choices_in_the_order_of_the_catalogue(self):
        r = self.ranges()
        self.assertEqual(self.entry(r, "diff_type", "rwd_front_modern"), {"values": ["Spool", "LSD"], "count": 2})
        self.assertEqual(self.entry(r, "diff_type", "awd"), {"values": ["Torsen"], "count": 1})

    def test_text_settings_and_the_hidden_tyre_settings_are_left_out(self):
        r = self.ranges()
        self.assertEqual(sorted(r["by_category"]), ["abs_on", "diff_type", "limiter", "mass"])

    def test_the_drift_presets_of_every_car_whose_label_contains_drift_with_the_values_of_the_variant(self):
        r = self.ranges()
        drift = next(c for c in r["categories"] if c["id"] == "drift")
        self.assertEqual(drift, {"id": "drift", "label": "Drift", "total": 2, "cars": ["Drift Car (Drift)", "Drift Two (BIG DRIFT pack)"]})
        self.assertEqual(self.entry(r, "limiter", "drift"), {"low": 8800, "high": 9000, "count": 2})
        self.assertEqual(self.entry(r, "abs_on", "drift"), {"values": [True], "count": 1})
        self.assertEqual(r["skipped"][0]["car"], "ks_none")
        self.assertEqual(len(r["skipped"]), 1)

    def test_the_cars_with_a_drift_preset_keep_their_own_category_and_their_own_values(self):
        r = self.ranges()
        self.assertIn("Drift Car", MEMBERS["rwd_front_modern"])
        self.assertEqual(self.entry(r, "limiter", "rwd_front_modern"), {"low": 7000, "high": 8000, "count": 3})
        self.assertEqual(self.entry(r, "limiter", "fwd"), {"low": 6000, "high": 6800, "count": 2})

    def test_a_drift_preset_that_cannot_be_resolved_is_skipped_by_name(self):
        def resolve(work, car_id, *args, **kw):
            if kw.get("variant") == "q_big":
                raise ValueError("variant broken")
            return REAL_RESOLVE(work, car_id, *args, **kw)
        self.patch(tune, "resolve_defaults", resolve)
        r = self.ranges()
        self.assertEqual([c["cars"] for c in r["categories"] if c["id"] == "drift"], [["Drift Car (Drift)"]])
        self.assertEqual(sorted((s["car"], s["reason"][:14]) for s in r["skipped"]), [("Drift Two (BIG DRIFT pack)", "variant broken"), ("ks_none", "no base car in")])

    def test_only_the_data_and_presets_folders_and_the_actor_files_of_the_cars_of_the_table_are_extracted(self):
        seen = self.spy()
        self.ranges()
        self.assertEqual(seen["files"]["ks_fm"], ["base/content/cars/ks_fm/data/d.drivetrain", "base/content/cars/ks_fm/data/engine.carengine",
                                                   "base/content/cars/ks_fm/data/readme.txt", "base/content/cars/ks_fm/data/s.carsetup",
                                                   "base/content/cars/ks_fm/data/x.car", "base/content/cars/ks_fm/ks_fm.actor",
                                                   "base/content/cars/ks_fm/presets/p.mechanicalcarpreset"])
        self.assertIn("base/content/cars/ks_dr/sub/dr.actor", seen["files"]["ks_dr"])
        self.assertEqual(sorted(seen["tmp"][0]), sorted(c[0] for c in CARS if c[0] != "ks_none"))

    def test_the_values_are_the_defaults_of_resolve_defaults(self):
        work = str(self.d / "extracted")
        with contextlib.redirect_stdout(io.StringIO()):
            kspkg.cmd_extract(self.game, os.path.join(work, "ks_awd", "base"), "content\\cars\\ks_awd")
        rows = {r["id"]: r for r in tune.resolve_defaults(work, "ks_awd", self.cat, "", hidden=True)}
        r = self.ranges()
        for sid in ("mass", "limiter"):
            self.assertEqual(self.entry(r, sid, "awd"), {"low": rows[sid]["default"], "high": rows[sid]["default"], "count": 1})
        self.assertEqual(self.entry(r, "diff_type", "awd"), {"values": [rows["diff_type"]["default"]], "count": 1})

    def test_the_answer_is_a_copy(self):
        first = self.ranges()
        first["categories"].clear()
        first["by_category"]["mass"]["awd"]["low"] = -1
        second = self.ranges()
        self.assertEqual(len(second["categories"]), 12)
        self.assertEqual(second["by_category"]["mass"]["awd"]["low"], 1600.0)


class TestTemporaryFolder(World):
    def test_the_folder_is_no_car_folder_and_is_removed_afterwards(self):
        self.assertIsNone(re.fullmatch(r"[a-z0-9_]+", tune.CAR_RANGES_TMP))
        before = snapshot(self.work)
        self.ranges()
        self.assertFalse(os.path.lexists(self.tmp))
        self.assertEqual(os.listdir(self.work).count(tune.CAR_RANGES_TMP), 0)
        self.assertEqual(set(snapshot(self.work)) - set(before), {tune.CAR_RANGES_FILE})
        self.assertEqual({k: v for k, v in snapshot(self.work).items() if k != tune.CAR_RANGES_FILE}, before)

    def test_no_car_becomes_installed_or_a_car_folder_at_any_moment(self):
        seen = self.spy()
        self.assertEqual((tune.installed_cars(self.work), tune.car_folders(self.work)), (["ks_inst"], ["ks_inst"]))
        self.ranges()
        self.assertEqual(len(seen["calls"]), 19)
        self.assertEqual(seen["installed"], [["ks_inst"]] * len(seen["calls"]))
        self.assertEqual(seen["folders"], [["ks_inst"]] * len(seen["calls"]))
        self.assertEqual((tune.installed_cars(self.work), tune.car_folders(self.work)), (["ks_inst"], ["ks_inst"]))

    def test_the_folder_is_removed_when_a_resolve_fails_unexpectedly(self):
        calls = []

        def resolve(work, car_id, *args, **kw):
            calls.append(car_id)
            if len(calls) == 3:
                raise RuntimeError("boom")
            return REAL_RESOLVE(work, car_id, *args, **kw)
        self.patch(tune, "resolve_defaults", resolve)
        before = snapshot(self.work)
        with self.assertRaisesRegex(RuntimeError, "boom"):
            self.ranges()
        self.assertFalse(os.path.lexists(self.tmp))
        self.assertEqual(snapshot(self.work), before)

    def test_the_folder_is_removed_when_the_extraction_fails_and_the_answer_is_empty(self):
        real, calls = kspkg.copy_entry, []

        def copy_entry(*args):
            calls.append(1)
            if len(calls) == 6:
                raise OSError("disk full")
            return real(*args)
        self.patch(kspkg, "copy_entry", copy_entry)
        before = snapshot(self.work)
        self.assertEqual(self.ranges(), EMPTY)
        self.assertGreaterEqual(len(calls), 6)
        self.assertFalse(os.path.lexists(self.tmp))
        self.assertEqual(snapshot(self.work), before)

    def test_a_folder_left_by_a_crash_is_replaced(self):
        self.write(os.path.join(self.tmp, "ks_old", "base", "content", "cars", "ks_old", "data", "x.car"), b"old", binary=True)
        seen = self.spy()
        self.ranges()
        self.assertNotIn("ks_old", seen["tmp"][0])
        self.assertFalse(os.path.lexists(self.tmp))

    def test_nothing_is_computed_into_a_missing_work_folder(self):
        work = str(self.d / "nowhere")
        self.assertEqual(self.ranges(work=work), EMPTY)
        self.assertFalse(os.path.exists(work))


class TestNoPackage(World):
    def test_without_a_package_nothing_is_read_or_written(self):
        seen = self.spy()
        before = snapshot(self.work)
        with mock.patch.object(kspkg, "read_table", side_effect=AssertionError("read the package")):
            self.assertEqual(self.ranges(game=str(self.d / "none.kspkg")), EMPTY)
            self.assertEqual(self.ranges(game=str(self.d)), EMPTY)
        self.assertEqual((seen["calls"], self.computed, snapshot(self.work)), ([], [], before))
        self.assertFalse(os.path.lexists(self.tmp))

    def test_a_package_without_cars_table_gives_the_empty_answer_and_no_cache(self):
        game = str(self.d / "no_table.kspkg")
        pack_world(game, with_table=False)
        before = snapshot(self.work)
        self.assertEqual(self.ranges(game=game), EMPTY)
        self.assertEqual(snapshot(self.work), before)
        self.assertFalse(os.path.lexists(self.tmp))

    def test_a_cars_table_that_cannot_be_decoded_gives_the_empty_answer_and_no_cache(self):
        def broken(data):
            raise ValueError("missing schema file")
        self.patch(tune, "cars_table_lines", broken)
        before = snapshot(self.work)
        self.assertEqual(self.ranges(), EMPTY)
        self.assertEqual(snapshot(self.work), before)

    def test_a_cars_table_without_cars_gives_the_empty_answer(self):
        self.lines = [{"car_content": {"display_name": "no name"}}, {}]
        before = snapshot(self.work)
        self.assertEqual(self.ranges(), EMPTY)
        self.assertEqual(snapshot(self.work), before)

    def test_a_failure_is_tried_again_the_next_time(self):
        self.patch(tune, "cars_table_lines", mock.Mock(side_effect=ValueError("broken")))
        self.assertEqual(self.ranges(), EMPTY)
        self.patch(tune, "cars_table_lines", lambda data: self.lines)
        self.assertEqual(len(self.ranges()["categories"]), 12)

    def test_car_range_data_never_raises(self):
        with mock.patch.object(tune, "car_ranges", side_effect=ValueError("broken")):
            self.assertEqual(tune.car_range_data(self.work, self.cat, self.game), EMPTY)
        with mock.patch.object(tune, "car_ranges", side_effect=OSError("broken")):
            self.assertEqual(tune.car_range_data(self.work, self.cat, self.game), EMPTY)
        self.assertEqual([c["id"] for c in tune.car_range_data(self.work, self.cat, self.game)["categories"]], ORDER)


class TestCache(World):
    def stored(self):
        with open(self.cache, encoding="utf-8") as f:
            return json.load(f)

    def test_the_result_is_written_with_the_version_the_package_stamp_and_the_catalogue_key(self):
        r = self.ranges()
        data = self.stored()
        st = os.stat(self.game)
        self.assertEqual(data["version"], tune.CAR_RANGES_VERSION)
        self.assertEqual(data["stamp"], [st.st_size, st.st_mtime_ns])
        self.assertEqual({k: data[k] for k in ("categories", "by_category", "skipped")}, r)
        self.assertEqual(set(data), {"version", "stamp", "settings", "category_list", "categories", "by_category", "skipped"})
        self.assertEqual([f for f in os.listdir(self.work) if f.endswith(".tmp")], [])

    def test_a_second_call_is_answered_from_memory_and_a_new_process_from_the_file(self):
        first = self.ranges()
        self.assertEqual(self.ranges(), first)
        self.assertEqual(len(self.computed), 1)
        tune._car_ranges_loaded.clear()
        self.assertEqual(self.ranges(), first)
        self.assertEqual(len(self.computed), 1)

    def test_a_changed_package_is_read_again(self):
        self.ranges()
        st = os.stat(self.game)
        game = str(self.d / "copy.kspkg")
        shutil.copyfile(self.game, game)
        self.ranges(game=game)
        self.assertEqual(len(self.computed), 2)
        os.utime(game, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        self.ranges(game=game)
        self.assertEqual(len(self.computed), 3)
        self.assertEqual(self.stored()["stamp"], [os.path.getsize(game), os.stat(game).st_mtime_ns])
        self.ranges(game=game)
        self.assertEqual(len(self.computed), 3)

    def test_a_changed_catalogue_is_read_again_where_it_changes_what_is_computed(self):
        self.ranges()
        self.ranges()
        self.assertEqual(len(self.computed), 1)
        changed = [mini_setting("limiter", type="int", targets=[("@engine", "limiter"), ("@car", "engine.limiter", True)])] + settings()[1:]
        self.ranges(cat=mini_catalogue(*changed))
        self.assertEqual(len(self.computed), 2)
        self.ranges(cat=mini_catalogue(*settings(), mini_setting("extra", targets=[("@car", "mass")])))
        self.assertEqual(len(self.computed), 3)
        self.ranges(cat=mini_catalogue(*[s for s in settings() if s["id"] != "mass"]))
        self.assertEqual(len(self.computed), 4)
        enum = [dict(s, choices=["LSD", "Spool", "Torsen"]) if s["id"] == "diff_type" else s for s in settings()]
        self.ranges(cat=mini_catalogue(*enum))
        self.assertEqual(len(self.computed), 5)

    def test_a_change_that_does_not_decide_the_values_is_no_reason_to_read_again(self):
        self.ranges()
        other = [dict(s, label="other", description="other", unit="kg", min=1, max=2, verified=True) for s in settings()]
        other[-1] = dict(other[-1], targets=[{"file": "@tyre_rear", "path": "x.y"}])
        other[-2] = dict(other[-2], default="Z")
        self.ranges(cat=mini_catalogue(*other))
        self.assertEqual(len(self.computed), 1)

    def test_a_damaged_file_is_read_again_and_replaced(self):
        self.ranges()
        for text in ('{"version": 1', "[]", "null", "", "\ufeff"):
            tune._car_ranges_loaded.clear()
            with open(self.cache, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertEqual(len(self.ranges()["categories"]), 12)
            self.assertEqual(self.stored()["version"], tune.CAR_RANGES_VERSION)
        self.assertEqual(len(self.computed), 6)

    def test_a_file_with_the_wrong_shape_is_read_again(self):
        self.ranges()
        good = self.stored()

        def bad_total(d):
            d["categories"][0]["total"] += 1

        def bad_id(d):
            d["categories"][0]["id"] = "nope"

        def bad_order(d):
            d["categories"].reverse()

        def bad_entry(d):
            d["by_category"]["mass"]["awd"]["low"] = "x"

        def bad_values(d):
            d["by_category"]["abs_on"]["awd"] = {"values": [], "count": 0}

        def bad_category(d):
            d["by_category"]["mass"]["nope"] = {"low": 1, "high": 2, "count": 1}

        def bad_skipped(d):
            d["skipped"] = [{"car": 1}]

        def old_version(d):
            d["version"] = tune.CAR_RANGES_VERSION - 1

        def old_catalogue(d):
            d["settings"] = "0" * 40

        def old_labels(d):
            d["category_list"][0][1] = "Old"

        def other_package(d):
            d["stamp"] = [1, 2]
        for edit in (bad_total, bad_id, bad_order, bad_entry, bad_values, bad_category, bad_skipped, old_version, old_catalogue, old_labels, other_package):
            with self.subTest(edit.__name__):
                data = copy.deepcopy(good)
                edit(data)
                tune._car_ranges_loaded.clear()
                self.write(self.cache, data)
                before = len(self.computed)
                self.assertEqual(self.ranges(), {k: good[k] for k in ("categories", "by_category", "skipped")})
                self.assertEqual(len(self.computed), before + 1)

    def test_a_deleted_file_is_computed_again_even_with_the_memory_copy(self):
        self.ranges()
        os.remove(self.cache)
        self.ranges()
        self.assertEqual(len(self.computed), 2)
        self.assertTrue(os.path.isfile(self.cache))

    def test_a_write_error_is_no_error_and_the_memory_copy_still_serves(self):
        with mock.patch.object(tune, "save_json", side_effect=OSError("read-only")):
            first = self.ranges()
            self.assertEqual(self.ranges(), first)
        self.assertEqual(len(first["categories"]), 12)
        self.assertEqual(len(self.computed), 1)
        self.assertFalse(os.path.exists(self.cache))

    def test_skipped_cars_are_kept_in_the_cache(self):
        self.ranges()
        tune._car_ranges_loaded.clear()
        self.assertEqual([s["car"] for s in self.ranges()["skipped"]], ["ks_none"])
        self.assertEqual(len(self.computed), 1)

    def test_the_cache_of_another_work_folder_is_not_used(self):
        self.ranges()
        other = str(self.d / "other")
        os.makedirs(other)
        self.ranges(work=other)
        self.assertEqual(len(self.computed), 2)
        self.assertTrue(os.path.isfile(os.path.join(other, tune.CAR_RANGES_FILE)))


class TestOneComputationAtATime(World):
    def test_concurrent_calls_compute_once_and_get_their_own_copy(self):
        def slow(*args):
            self.computed.append(1)
            time.sleep(0.3)
            return REAL_COMPUTE(*args)
        self.patch(tune, "compute_car_ranges", slow)
        results, errors, barrier = [], [], threading.Barrier(5)

        def run():
            try:
                barrier.wait(5)
                results.append(self.ranges())
            except BaseException as e:
                errors.append(e)
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 5)
        self.assertEqual(len(self.computed), 1)
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len({id(r["categories"]) for r in results}), 5)

    def test_a_call_that_waits_gets_the_result_of_the_first_and_a_failure_is_tried_again_by_the_next(self):
        gate, entered, calls = threading.Event(), threading.Event(), []

        def compute(*args):
            calls.append(1)
            entered.set()
            gate.wait(10)
            return None if len(calls) == 1 else REAL_COMPUTE(*args)
        self.patch(tune, "compute_car_ranges", compute)
        results = []
        first = threading.Thread(target=lambda: results.append(self.ranges()))
        first.start()
        entered.wait(5)
        second = threading.Thread(target=lambda: results.append(self.ranges()))
        second.start()
        time.sleep(0.1)
        gate.set()
        first.join(30)
        second.join(30)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sorted(len(r["categories"]) for r in results), [0, 12])


class RouteCase(TuneCase):
    """TuneCase with the game of the server set to a package that does not exist; tests that need a package set it."""

    def setUp(self):
        super().setUp()
        self.patch_dict(ts.CONFIG, {"game": str(self.d / "none.kspkg")})
        tune._car_ranges_loaded.clear()
        self.addCleanup(tune._car_ranges_loaded.clear)

    def use_package(self):
        self.patch_dict(ts.CONFIG, {"game": PACKAGES["full"]})
        self.patch(tune, "cars_table_lines", lambda data: [{"car_content": table_row(c)} for c in CARS])
        current = tune.load_msg
        self.patch(tune, "load_msg", lambda path: fake_load_msg(path) if tune.CAR_RANGES_TMP in os.fspath(path) else current(path))
        self.cat = mini_catalogue(*settings())


class TestCarRangesRoute(RouteCase):
    def test_without_a_package_both_lists_are_empty_and_nothing_is_written(self):
        before = snapshot(self.work)
        r = self.get("/api/car_ranges")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control")), (200, "application/json; charset=utf-8", "no-store"))
        self.assertEqual(r.json, {"categories": [], "by_category": {}})
        self.assertEqual(snapshot(self.work), before)

    def test_it_answers_the_categories_and_the_values_of_the_package_without_the_skipped_cars(self):
        self.use_package()
        r = self.get("/api/car_ranges")
        self.assertEqual(r.status, 200)
        self.assertEqual(set(r.json), {"categories", "by_category"})
        self.assertEqual({c["id"]: c["cars"] for c in r.json["categories"]}, MEMBERS)
        self.assertEqual([c["id"] for c in r.json["categories"]], ORDER)
        self.assertEqual(r.json["by_category"]["limiter"]["rwd_front_modern"], {"low": 7000, "high": 8000, "count": 3})
        self.assertEqual(r.json["by_category"]["limiter"]["drift"], {"low": 8800, "high": 9000, "count": 2})
        self.assertEqual(r.json["by_category"]["diff_type"]["awd"], {"values": ["Torsen"], "count": 1})
        self.assertNotIn("formula", r.json["by_category"]["limiter"])
        self.assertTrue(os.path.isfile(os.path.join(self.work, tune.CAR_RANGES_FILE)))
        self.assertFalse(os.path.lexists(os.path.join(self.work, tune.CAR_RANGES_TMP)))
        self.assertEqual(tune.installed_cars(self.work), ["ks_x"])

    def test_it_is_cached_and_the_settings_rows_do_not_start_it(self):
        self.use_package()
        calls = []
        self.patch(tune, "compute_car_ranges", lambda *a: calls.append(1) or REAL_COMPUTE(*a))
        rows = self.get("/api/settings").json
        self.assertEqual(calls, [])
        first = self.get("/api/car_ranges").json
        self.assertEqual(self.get("/api/car_ranges").json, first)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all("category_ranges" not in r for r in rows))
        self.assertIsInstance(rows, list)

    def test_it_needs_no_base_car_and_is_the_same_for_every_car_tune_and_version(self):
        self.use_package()
        self.assertEqual(self.get("/api/settings?car=ks_y").status, 409)
        expected = self.get("/api/car_ranges").json
        self.make_tune("ax01", {"limiter": 9000})
        version = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        for query in ("?car=ks_y", "?tune=draft", "?tune=ax01", "?car=ks_x&tune=ax01&version=" + version):
            with self.subTest(query):
                r = self.get("/api/car_ranges" + query)
                self.assertEqual((r.status, r.json), (200, expected))

    def test_the_dispatcher_still_checks_the_car(self):
        self.assertEqual(self.get("/api/car_ranges?car=nope").status, 400)

    def test_the_computation_does_not_hold_the_state_lock_and_other_requests_go_on(self):
        entered, gate, locked = threading.Event(), threading.Event(), []

        def slow(work, catalogue=None, game=None):
            locked.append(ts.STATE_LOCK.locked())
            entered.set()
            gate.wait(10)
            return {"categories": [], "by_category": {}, "skipped": []}
        self.patch(tune, "car_ranges", slow)
        self.addCleanup(gate.set)
        result = []
        t = threading.Thread(target=lambda: result.append(self.get("/api/car_ranges")))
        t.start()
        self.assertTrue(entered.wait(5))
        self.assertEqual(self.get("/api/state").status, 200)
        self.assertEqual(self.get("/api/settings").status, 200)
        self.assertEqual(self.post("/api/set", {"id": "limiter", "value": "8000"}).status, 200)
        gate.set()
        t.join(10)
        self.assertEqual((result[0].status, locked), (200, [False]))

    def test_an_error_of_the_computation_gives_the_empty_answer(self):
        self.patch(tune, "car_ranges", mock.Mock(side_effect=ValueError("broken")))
        self.assertEqual(self.get("/api/car_ranges").json, {"categories": [], "by_category": {}})

    def test_the_settings_and_the_answers_of_set_and_unset_are_as_before(self):
        self.use_package()
        rows = self.get("/api/settings").json
        self.assertIsInstance(rows, list)
        self.assertTrue(all("category_ranges" not in r for r in rows))
        self.assertNotIn("category_ranges", self.post("/api/set", {"id": "limiter", "value": "8000"}).json["row"])
        self.assertNotIn("category_ranges", self.post("/api/unset", {"id": "limiter"}).json["row"])
        self.assertFalse(os.path.exists(os.path.join(self.work, tune.CAR_RANGES_FILE)))


if __name__ == "__main__":
    unittest.main()
