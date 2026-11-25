"""Tests for the tyre library of tools/tune.py (data layer and CLI): ids, names and short names, the file format version 2 in <work>/tyres, the fields of a library tyre, the tyres to choose from (game package or extracted files), values and rows, users and delete.

No game data and no schemas: the cars are synthetic (support.FakeCar replaces tune.load_msg with in-memory messages, one shared store for both fake cars), the game package is a small package packed by kspkg.cmd_pack or does not exist; the CLI is run in-process on those cars, and as a subprocess where nothing decodes a car file.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from support import FakeCar, Sandbox, mini_catalogue, mini_setting, run_main, run_tool, tmp, usage_cases

import kspkg
import tune
import tyre_sets

USAGE = tune.__doc__.split("\n\n")[1]
GS = "content\\cars\\common_phsx\\"
ROAD_A, ROAD_B, SLICK_S = GS + "tyres\\road\\a.tyre", GS + "tyres\\road\\b.tyre", GS + "tyres\\slick\\s.tyre"
CURVES = {"road": GS + "tyres\\road\\tcurve_road.curve", "slick": GS + "tyres\\slick\\tcurve_slick.curve"}
REAL_FIELDS = ["tyre_grip_lateral", "tyre_grip_longitudinal", "tyre_peak_slip_angle", "tyre_load_reference", "tyre_pressure_ref",
               "tyre_flex_lateral", "tyre_flex_longitudinal", "tyre_stiffness_rate", "tyre_heat_partition", "tyre_grain_gain",
               "tyre_grain_slip_angle_gain", "tyre_thermal_curve"]


def tyre_cat():
    return mini_catalogue(
        mini_setting("tyre_dy_front", group="Tyres", label="Front tyre lateral grip", unit="mu", min=0.5, max=2.5, description="grip",
                     targets=[("@tyre_front", "modelData.Dy0"), ("@tyre_front", "modelData.Dy1")]),
        mini_setting("tyre_dy_rear", group="Tyres", label="Rear tyre lateral grip", unit="mu", min=0.5, max=2.5,
                     targets=[("@tyre_rear", "modelData.Dy0")]),
        mini_setting("tyre_th_front", group="Tyres", label="Front tyre thermal curve", type="enum", choices=["road", "slick"], choice_values=CURVES,
                     targets=[("@tyre_front", "thermalData.thermalPerformanceCurve")]),
        mini_setting("tyre_deep_front", group="Tyres", targets=[("@tyre_front", "modelData.nope.x")]),
        mini_setting("tyre_maybe_front", group="Tyres", targets=[("@tyre_front", "modelData.maybe", True)]),
        mini_setting("tyre_front_only", group="Other", targets=[("@tyre_front", "modelData.Dy0")]),
        mini_setting("limiter", type="int", targets=[("@engine", "limiter")]))


def tyre_obj(dy, curve="road"):
    return {"name": "stock", "shortName": "ST", "modelData": {"Dy0": dy, "Dy1": dy}, "thermalData": {"thermalPerformanceCurve": CURVES[curve]}}


def pack(dst, names):
    """A package with the shared tyre files names (below content\\cars\\common_phsx\\tyres) as files with placeholder bytes."""
    src = tempfile.mkdtemp()
    try:
        for rel in names:
            path = os.path.join(src, "content", "cars", "common_phsx", "tyres", *rel.split("\\"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"tyre " + rel.encode())
        with contextlib.redirect_stdout(io.StringIO()):
            kspkg.cmd_pack(src, dst)
    finally:
        shutil.rmtree(src)


class Base(Sandbox):
    def setUp(self):
        super().setUp()
        self.work = str(self.d / "work")
        self.game = str(self.d / "no_game.kspkg")

    def read(self, tyre_id):
        with open(tune.tyre_path(self.work, tyre_id), "rb") as f:
            return f.read()

    def write_tyre(self, tyre_id, data):
        path = os.path.join(self.work, "tyres", tyre_id + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def run_main(self, *argv):
        return run_main(tune.main, ["tune.py", *argv])


class World(Base):
    """Two extracted cars sharing one message store. ks_a: road a/b, slick s (the file of ks_b does not have it), supercar sc_235_35_19 and
    the two files road/dup and slick/dup. ks_b: road a/b again with other values. The game package does not exist (self.game)."""

    def setUp(self):
        super().setUp()
        self.a = FakeCar(self.work, "ks_a").install(self)
        self.b = FakeCar(self.work, "ks_b")
        self.b.store = self.a.store
        self.a.add_shared("tyres/road/a.tyre", tyre_obj(1.2))
        self.a.add_shared("tyres/road/b.tyre", {"modelData": {"Dy0": 1.1}})
        self.a.add_shared("tyres/slick/s.tyre", tyre_obj(1.0, "slick"))
        self.a.add_shared("tyres/supercar/supercar_235_35_19.tyre", tyre_obj(1.5))
        self.a.add_shared("tyres/road/dup.tyre", tyre_obj(1.0))
        self.a.add_shared("tyres/slick/dup.tyre", tyre_obj(1.0))
        self.b.add_shared("tyres/road/a.tyre", tyre_obj(1.25))
        self.cat = tyre_cat()

    def create(self, name="Slick", source=ROAD_A, **kw):
        return tune.create_tyre(self.work, name, source, game=self.game, **kw)["id"]

    def rows(self, tyre_id):
        return {r["id"]: r for r in tune.tyre_rows(self.work, tyre_id, self.cat, self.game)}


class TestIds(Base):
    BAD = ("..", "../x", "a/b", "a\\b", "A", "", "x" * 25, "a b", "a.json", "a\n", "é", None, 5, ["a"])

    def test_the_pattern_is_one_to_24_of_a_z_0_9_and_underscore(self):
        for good in ("a", "x_1", "0", "_", "a" * 24):
            tune.check_tyre_id(good)
        for bad in self.BAD:
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "^bad tyre id "):
                tune.check_tyre_id(bad)

    def test_every_function_that_takes_an_id_checks_it_before_a_path_is_built(self):
        self.write_tyre("x", {"version": 2, "name": "X", "short": "X", "source": ROAD_A, "values": {}})
        calls = (lambda i: tune.load_tyre(self.work, i), lambda i: tune.rename_tyre(self.work, i, "N"),
                 lambda i: tune.set_tyre_source(self.work, i, "a", self.game), lambda i: tune.set_tyre_value(self.work, i, "tyre_dy", "1", tyre_cat()),
                 lambda i: tune.unset_tyre_value(self.work, i, "tyre_dy", tyre_cat()), lambda i: tune.reset_tyre(self.work, i),
                 lambda i: tune.tyre_rows(self.work, i, tyre_cat(), self.game), lambda i: tune.tyre_users(self.work, i),
                 lambda i: tune.delete_tyre(self.work, i))
        self.patch(tune, "tyres_dir", lambda work: self.fail("a path was built for a bad id"))
        for bad in self.BAD:
            for call in calls:
                with self.subTest(bad), self.assertRaisesRegex(ValueError, "^bad tyre id "):
                    call(bad)

    def test_a_traversal_id_does_not_reach_a_file_outside_the_library(self):
        self.write_tyre("x", {"version": 2, "name": "X", "short": "X", "source": ROAD_A, "values": {}})
        outside = os.path.join(self.work, "x.json")
        os.replace(os.path.join(self.work, "tyres", "x.json"), outside)
        with self.assertRaisesRegex(ValueError, "^bad tyre id "):
            tune.load_tyre(self.work, "../x")
        with self.assertRaisesRegex(ValueError, "^bad tyre id "):
            tune.delete_tyre(self.work, "../x")
        self.assertTrue(os.path.isfile(outside))

    def test_free_tyre_id_makes_a_slug(self):
        for name, expected in (("Slick Soft", "slick_soft"), ("  Road / Hard!! ", "road_hard"), ("A--B__C", "a_b_c"), ("Tyre 2024", "tyre_2024"),
                               ("", "tyre"), ("  ", "tyre"), ("---", "tyre"), ("Ä Ö", "tyre"), ("Ä x", "x")):
            with self.subTest(name):
                self.assertEqual(tune.free_tyre_id(self.work, name), expected)

    def test_free_tyre_id_cuts_to_24_characters(self):
        self.assertEqual(tune.free_tyre_id(self.work, "a" * 30), "a" * 24)
        self.assertEqual(len(tune.free_tyre_id(self.work, "ab cd " * 10)), 24)
        tune.check_tyre_id(tune.free_tyre_id(self.work, "x" * 100))

    def test_a_taken_id_gets_a_number_and_the_base_is_cut_to_stay_within_24_characters(self):
        for taken in ("slick", "slick2", "a" * 24, "a" * 23 + "2"):
            self.write_tyre(taken, "{}")
        self.assertEqual(tune.free_tyre_id(self.work, "Slick"), "slick3")
        self.assertEqual(tune.free_tyre_id(self.work, "a" * 30), "a" * 23 + "3")
        for n in range(3, 10):
            self.write_tyre("a" * 23 + str(n), "{}")
        self.assertEqual(tune.free_tyre_id(self.work, "a" * 30), "a" * 22 + "10")

    def test_a_damaged_file_with_the_id_counts_as_taken(self):
        self.write_tyre("tyre", "not json")
        self.assertEqual(tune.free_tyre_id(self.work, ""), "tyre2")


class TestNames(World):
    def test_name_rules(self):
        for bad in ("", "   ", "a\x01b", "a\tb", "a\nb", "a\x7fb", "x" * 41, None, 5):
            with self.subTest(repr(bad)), self.assertRaisesRegex(ValueError, "a tyre name"):
                tune.create_tyre(self.work, bad, ROAD_A, game=self.game)
        self.assertFalse(os.path.exists(os.path.join(self.work, "tyres")))

    def test_the_name_is_stripped_and_40_characters_are_fine(self):
        self.assertEqual(tune.create_tyre(self.work, "  Soft  ", ROAD_A, game=self.game)["name"], "Soft")
        self.assertEqual(tune.create_tyre(self.work, "y" * 40, ROAD_A, game=self.game)["name"], "y" * 40)

    def test_the_name_must_be_unique_ignoring_case(self):
        self.create("Slick")
        for dup in ("Slick", "SLICK", " slick "):
            with self.subTest(dup), self.assertRaisesRegex(ValueError, "^a tyre named 'Slick' exists already"):
                tune.create_tyre(self.work, dup, ROAD_A, game=self.game)
        self.assertEqual([t["id"] for t in tune.list_tyres(self.work)], ["slick"])

    def test_rename_changes_the_name_and_keeps_id_short_source_and_values(self):
        tid = self.create("Slick")
        tune.set_tyre_value(self.work, tid, "tyre_dy", "1.4", self.cat)
        self.assertEqual(tune.rename_tyre(self.work, tid, "Soft"), {"id": "slick", "name": "Soft", "short": "SL"})
        t = tune.load_tyre(self.work, "slick")
        self.assertEqual((t["name"], t["short"], t["source"], t["values"]), ("Soft", "SL", ROAD_A, {"tyre_dy": 1.4}))

    def test_rename_can_change_the_short_name(self):
        tid = self.create("Slick")
        self.assertEqual(tune.rename_tyre(self.work, tid, "Slick", "Q9")["short"], "Q9")
        self.assertEqual(tune.load_tyre(self.work, tid)["short"], "Q9")
        before = self.read(tid)
        with self.assertRaisesRegex(ValueError, "a tyre short name needs 1 to 3 characters"):
            tune.rename_tyre(self.work, tid, "Other", "q")
        self.assertEqual(self.read(tid), before)

    def test_rename_to_the_same_name_or_another_case_of_it_is_fine(self):
        tid = self.create("Slick")
        self.assertEqual(tune.rename_tyre(self.work, tid, "Slick")["name"], "Slick")
        self.assertEqual(tune.rename_tyre(self.work, tid, "SLICK")["name"], "SLICK")

    def test_rename_to_the_name_of_another_tyre_is_refused_and_changes_nothing(self):
        tid = self.create("Slick")
        self.create("Soft")
        before = self.read(tid)
        with self.assertRaisesRegex(ValueError, "^a tyre named 'Soft' exists already"):
            tune.rename_tyre(self.work, tid, "soft")
        with self.assertRaisesRegex(ValueError, "a tyre name needs"):
            tune.rename_tyre(self.work, tid, "")
        self.assertEqual(self.read(tid), before)

    def test_rename_of_a_missing_tyre(self):
        with self.assertRaisesRegex(ValueError, "^no tyre 'nope' in the library$"):
            tune.rename_tyre(self.work, "nope", "x")

    def test_the_name_can_be_reused_after_a_delete(self):
        tid = self.create("Slick")
        tune.delete_tyre(self.work, tid)
        self.assertEqual(self.create("Slick"), "slick")


class TestShortNames(World):
    def test_the_default_is_made_from_the_last_two_words(self):
        for name, expected in (("Soft", "SO"), ("Slick Soft", "SS"), ("My Slick Soft", "SS"), ("a", "A"), ("  hard   road  ", "HR"), ("Q", "Q"),
                               ("Road 205", "R2"), ("(x) y", "Y"), ("--", "X"), ("Ärger Test", "T"), ("ab", "AB"), ("12345", "12")):
            with self.subTest(name):
                self.assertEqual(tune.default_short(name), expected)

    def test_a_short_name_is_one_to_three_characters_of_a_z_and_0_9(self):
        for good in ("A", "AB", "A1", "123", "Z9X"):
            self.assertEqual(tune.check_tyre_short(good), good)
        for bad in ("", "ab", "A B", "ABCD", "A-", "ä", "A\n", None, 5, ["A"]):
            with self.subTest(repr(bad)), self.assertRaisesRegex(ValueError, "^a tyre short name needs 1 to 3 characters A-Z and 0-9 \\(upper case, no spaces\\)"):
                tune.check_tyre_short(bad)

    def test_create_takes_the_short_name_or_makes_one(self):
        self.assertEqual(tune.create_tyre(self.work, "Slick Soft", ROAD_A, game=self.game)["short"], "SS")
        self.assertEqual(tune.create_tyre(self.work, "Other", ROAD_A, "Z1", game=self.game)["short"], "Z1")
        self.assertEqual(tune.load_tyre(self.work, "other")["short"], "Z1")

    def test_a_bad_short_name_writes_nothing(self):
        for bad in ("", "abc", "ABCD", " A"):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "a tyre short name"):
                tune.create_tyre(self.work, "Soft", ROAD_A, bad, self.game)
        self.assertFalse(os.path.exists(os.path.join(self.work, "tyres")))


class TestFields(World):
    def test_one_field_per_front_setting_of_the_group_tyres(self):
        fields = tune.tyre_fields(self.cat)
        self.assertEqual([f["id"] for f in fields], ["tyre_dy", "tyre_th", "tyre_deep", "tyre_maybe"])
        self.assertEqual([f["front_id"] for f in fields], ["tyre_dy_front", "tyre_th_front", "tyre_deep_front", "tyre_maybe_front"])

    def test_the_label_loses_the_word_front_and_keeps_the_rest_of_the_definition(self):
        dy, th = tune.tyre_fields(self.cat)[:2]
        self.assertEqual((dy["label"], th["label"]), ("Tyre lateral grip", "Tyre thermal curve"))
        self.assertEqual((dy["type"], dy["unit"], dy["min"], dy["max"], dy["description"]), ("float", "mu", 0.5, 2.5, "grip"))
        self.assertEqual(th["choices"], ["road", "slick"])
        self.assertEqual(th["choice_values"], CURVES)

    def test_the_targets_are_the_paths_after_tyre_front(self):
        dy, _, _, maybe = tune.tyre_fields(self.cat)
        self.assertEqual([(t["file"], t["path"]) for t in dy["targets"]], [("@tyre", "modelData.Dy0"), ("@tyre", "modelData.Dy1")])
        self.assertTrue(maybe["targets"][0]["optional"])

    def test_the_label_word_is_matched_as_a_whole_word_in_any_case(self):
        cat = mini_catalogue(mini_setting("a_front", group="Tyres", label="FRONT grip"), mini_setting("b_front", group="Tyres", label="Frontal front lift"),
                             mini_setting("c_front", group="Tyres", label="Grip"))
        self.assertEqual([f["label"] for f in tune.tyre_fields(cat)], ["Grip", "Frontal lift", "Grip"])

    def test_the_catalogue_of_the_tuner_gives_the_twelve_derived_fields_and_the_tyre_settings(self):
        cat = tune.load_catalogue()
        fields = tune.tyre_fields()
        derived = [f for f in fields if "front_id" in f]
        self.assertEqual(sorted(f["id"] for f in derived), sorted(REAL_FIELDS))
        self.assertEqual(len(fields), 12 + len(cat["tyre_settings"]))
        self.assertTrue(all(f["id"] + "_front" == f["front_id"] for f in derived))
        self.assertTrue(all("front" not in f["label"].lower().split() for f in fields))
        self.assertEqual(fields[0]["label"], "Tyre lateral grip")
        self.assertEqual(next(f for f in fields if f["id"] == "tyre_thermal_curve")["type"], "enum")

    def test_a_field_id_that_is_no_field_is_refused(self):
        for bad, text in (("tyre_dy_front", "^tyre_dy_front is not a tyre setting$"), ("tyre_dy_rear", "^tyre_dy_rear is not a tyre setting$"),
                          ("limiter", "^limiter is not a tyre setting$"), ("nope", "^unknown setting 'nope'$")):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, text):
                tune.tyre_field(self.cat, bad)


class TestChoosableTyres(World):
    def test_without_the_package_only_the_extracted_files_count(self):
        index = tune.available_tyres(self.work, self.game)
        self.assertEqual([t["file"] for t in index], ["a", "b", "dup", "supercar_235_35_19", "dup", "s"])
        self.assertEqual(index[0]["path"], ROAD_A)
        self.assertEqual(index[3]["label"], "Supercar 235/35 R19")

    def test_the_extracted_tyres_of_the_tyre_files_folder_count_too(self):
        os.makedirs(os.path.join(self.work, "tyre_files", "content", "cars", "common_phsx", "tyres", "eco"))
        with open(os.path.join(self.work, "tyre_files", "content", "cars", "common_phsx", "tyres", "eco", "eco_175_50_13.tyre"), "wb"):
            pass
        self.assertIn("eco_175_50_13", [t["file"] for t in tune.available_tyres(self.work, self.game)])

    def test_no_extracted_car_and_no_package_gives_none(self):
        self.assertEqual(tune.available_tyres(str(self.d / "empty"), self.game), [])

    def test_with_the_package_the_index_of_its_table_counts(self):
        pkg = str(self.d / "content.kspkg")
        pack(pkg, ["road\\road_235_35_19.tyre", "supercar\\supercar_265_30_19.tyre"])
        self.assertEqual([t["file"] for t in tune.available_tyres(self.work, pkg)], ["road_235_35_19", "supercar_265_30_19"])
        self.assertEqual(tune.available_tyres(self.work, pkg), tyre_sets.read_index(pkg))

    def test_a_game_path_finds_its_entry_with_any_slashes_case_and_extension(self):
        for text in (ROAD_A, ROAD_A[:-len(".tyre")], ROAD_A.replace("\\", "/"), ROAD_A.upper(), "  " + ROAD_A + " "):
            with self.subTest(text):
                self.assertEqual(tune.find_tyre(self.work, text, self.game)["path"], ROAD_A)

    def test_a_file_name_finds_its_entry(self):
        self.assertEqual(tune.find_tyre(self.work, "supercar_235_35_19", self.game)["label"], "Supercar 235/35 R19")
        self.assertEqual(tune.find_tyre(self.work, "SUPERCAR_235_35_19.TYRE", self.game)["file"], "supercar_235_35_19")

    def test_an_unknown_tyre_a_foreign_path_or_text_that_is_not_text_is_refused(self):
        for text in ("nope", GS + "tyres\\road\\nope.tyre", "content\\cars\\ks_a\\data\\a.tyre", "road\\a.tyre"):
            with self.subTest(text), self.assertRaisesRegex(ValueError, "^unknown tyre .*, tyre-index lists the tyres$"):
                tune.find_tyre(self.work, text, self.game)
        for bad in (None, 5, "", "  ", ["a"]):
            with self.subTest(repr(bad)), self.assertRaisesRegex(ValueError, "^a tyre source must be a game path or a file name"):
                tune.find_tyre(self.work, bad, self.game)

    def test_a_file_name_that_two_tyres_have_is_refused_and_the_game_path_works(self):
        with self.assertRaisesRegex(ValueError, "^'dup' names 2 tyres \\(.*road\\\\dup.tyre.*slick\\\\dup.tyre\\), give the game path$"):
            tune.find_tyre(self.work, "dup", self.game)
        self.assertEqual(tune.find_tyre(self.work, GS + "tyres\\slick\\dup", self.game)["type"], "slick")

    def test_a_tyre_that_is_only_in_the_package_can_be_a_source(self):
        pkg = str(self.d / "content.kspkg")
        pack(pkg, ["road\\road_205_55_16.tyre"])
        res = tune.create_tyre(self.work, "Far", "road_205_55_16", game=pkg)
        self.assertEqual(res["source"], GS + "tyres\\road\\road_205_55_16.tyre")
        with self.assertRaisesRegex(ValueError, "unknown tyre"):
            tune.create_tyre(self.work, "Near", ROAD_A, game=pkg)


class TestLibraryFiles(World):
    def test_create_writes_the_documented_file(self):
        res = tune.create_tyre(self.work, "Slick Soft", "a", game=self.game)
        self.assertEqual(res, {"id": "slick_soft", "name": "Slick Soft", "short": "SS", "source": ROAD_A})
        raw = self.read("slick_soft")
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(json.loads(raw), {"version": 2, "name": "Slick Soft", "short": "SS", "source": ROAD_A, "values": {}})
        self.assertEqual(list(json.loads(raw)), ["version", "name", "short", "source", "values"])
        self.assertEqual(tune.load_tyre(self.work, "slick_soft"), json.loads(raw))

    def test_create_with_an_unknown_source_writes_nothing(self):
        for source in ("nope", "dup", ROAD_A + "|" + ROAD_B, GS + "tyres\\road\\missing.tyre"):
            with self.subTest(source), self.assertRaises(ValueError):
                tune.create_tyre(self.work, "Slick", source, game=self.game)
        self.assertFalse(os.path.exists(os.path.join(self.work, "tyres")))

    def test_only_changed_values_are_stored(self):
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_dy", "1.4", self.cat)
        self.assertEqual(json.loads(self.read(tid))["values"], {"tyre_dy": 1.4})

    def test_a_second_tyre_whose_name_makes_the_same_id_gets_a_numbered_id(self):
        self.assertEqual(self.create("Slick Soft"), "slick_soft")
        self.assertEqual(self.create("Slick-Soft!"), "slick_soft2")

    def test_list_sorts_by_name_ignoring_case_then_id_and_puts_damaged_files_last(self):
        self.create("beta")
        self.create("Alpha")
        self.create("Gamma")
        self.write_tyre("zzz", "{")
        self.write_tyre("old", {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        self.write_tyre("short_bad", {"version": 2, "name": "X", "short": "x", "source": ROAD_A, "values": {}})
        listed = tune.list_tyres(self.work)
        self.assertEqual([t["id"] for t in listed], ["alpha", "beta", "gamma", "old", "short_bad", "zzz"])
        self.assertEqual(listed[0], {"id": "alpha", "name": "Alpha", "short": "AL", "source": ROAD_A, "changed": 0})
        self.assertTrue(all(set(t) == {"id", "error"} for t in listed[3:]))

    def test_a_tyre_of_version_1_is_an_error_that_says_to_create_it_again(self):
        self.write_tyre("old", {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        with self.assertRaisesRegex(ValueError, "the tyre was saved in the old front/rear form and must be created again$"):
            tune.load_tyre(self.work, "old")
        self.assertIn("old front/rear form", tune.list_tyres(self.work)[0]["error"])
        for call in (lambda: tune.rename_tyre(self.work, "old", "X"), lambda: tune.set_tyre_value(self.work, "old", "tyre_dy", "1", self.cat),
                     lambda: tune.tyre_rows(self.work, "old", self.cat, self.game)):
            with self.assertRaisesRegex(ValueError, "old front/rear form"):
                call()

    def test_a_damaged_file_is_an_error_naming_the_fault(self):
        good = {"version": 2, "name": "X", "short": "X", "source": ROAD_A, "values": {}}
        cases = [("not json", "x.json"), ("[]", "expected an object"), (dict(good, version=3), "version 3 is not supported"),
                 (dict(good, version="2"), "version '2' is not supported"), (dict(good, version=True), "is not supported"),
                 (dict(good, name=""), "name must be text"), (dict(good, name=5), "name must be text"),
                 (dict(good, short="abc"), "short must be 1 to 3 characters"), (dict(good, short=None), "short must be"),
                 (dict(good, source=""), "source needs a tyre game path"), (dict(good, source={"front": ROAD_A, "rear": ROAD_B}), "source needs"),
                 (dict(good, values=[]), "values must be an object")]
        cases += [({k: v for k, v in good.items() if k != missing}, "") for missing in good]
        for data, text in cases:
            with self.subTest(str(data)[:70]):
                self.write_tyre("x", data)
                with self.assertRaises(ValueError) as caught:
                    tune.load_tyre(self.work, "x")
                self.assertIn(text, str(caught.exception))
                self.assertEqual(list(tune.list_tyres(self.work)[0]), ["id", "error"])

    def test_a_missing_tyre(self):
        with self.assertRaisesRegex(ValueError, "^no tyre 'nope' in the library$"):
            tune.load_tyre(self.work, "nope")

    def test_set_source_keeps_the_values_name_and_short(self):
        tid = self.create("Slick", ROAD_A, short="QQ")
        tune.set_tyre_value(self.work, tid, "tyre_dy", "1.4", self.cat)
        self.assertEqual(tune.set_tyre_source(self.work, tid, "s", self.game), {"id": tid, "source": SLICK_S})
        self.assertEqual(json.loads(self.read(tid)), {"version": 2, "name": "Slick", "short": "QQ", "source": SLICK_S, "values": {"tyre_dy": 1.4}})

    def test_set_source_with_an_unknown_source_changes_nothing(self):
        tid = self.create()
        before = self.read(tid)
        for source in ("nope", "dup", ROAD_A + "|" + ROAD_B):
            with self.subTest(source), self.assertRaises(ValueError):
                tune.set_tyre_source(self.work, tid, source, self.game)
        with self.assertRaisesRegex(ValueError, "^no tyre 'nope' in the library$"):
            tune.set_tyre_source(self.work, "nope", "a", self.game)
        self.assertEqual(self.read(tid), before)

    def test_the_library_is_shared_by_every_car_and_needs_no_car(self):
        self.create()
        self.assertEqual([t["id"] for t in tune.list_tyres(str(self.d / "work"))], ["slick"])
        self.assertEqual(tune.list_tyres(str(self.d / "none")), [])


class TestValues(World):
    def set(self, tid, field, value):
        return tune.set_tyre_value(self.work, tid, field, value, self.cat)

    def test_set_stores_the_coerced_value_with_the_generic_id(self):
        tid = self.create()
        self.assertEqual(self.set(tid, "tyre_dy", "1.4"), {"id": "tyre_dy", "value": 1.4, "warnings": []})
        self.assertEqual(self.set(tid, "tyre_dy", 2), {"id": "tyre_dy", "value": 2.0, "warnings": []})
        self.assertEqual(tune.load_tyre(self.work, tid)["values"], {"tyre_dy": 2.0})
        self.assertEqual(self.set(tid, "tyre_th", "slick")["value"], "slick")

    def test_a_value_outside_the_range_of_the_front_setting_is_stored_with_a_warning(self):
        tid = self.create()
        res = self.set(tid, "tyre_dy", "9")
        self.assertEqual((res["value"], res["warnings"]), (9.0, ["tyre_dy=9.0 is outside the suggested range 0.5..2.5"]))
        self.assertEqual(tune.load_tyre(self.work, tid)["values"], {"tyre_dy": 9.0})

    def test_a_bad_value_is_refused_and_changes_nothing(self):
        tid = self.create()
        before = self.read(tid)
        for field, value, text in (("tyre_dy", "fast", "^tyre_dy expects a number, got 'fast'$"), ("tyre_dy", "nan", "finite"),
                                   ("tyre_dy", True, "expects a number"), ("tyre_th", "grass", "^tyre_th must be one of: road, slick$"),
                                   ("tyre_th", 5, "non-empty text")):
            with self.subTest(field, value=value), self.assertRaisesRegex(ValueError, text):
                self.set(tid, field, value)
        self.assertEqual(self.read(tid), before)

    def test_a_setting_that_is_no_field_is_refused(self):
        tid = self.create()
        before = self.read(tid)
        for field, text in (("tyre_dy_front", "is not a tyre setting"), ("tyre_dy_rear", "is not a tyre setting"), ("limiter", "is not a tyre setting"),
                            ("nope", "unknown setting 'nope'"), ("tyre_front_only", "is not a tyre setting")):
            with self.subTest(field), self.assertRaisesRegex(ValueError, text):
                self.set(tid, field, "1")
        self.assertEqual(self.read(tid), before)

    def test_unset_removes_one_value_and_is_a_noop_for_a_field_that_was_not_set(self):
        tid = self.create()
        self.set(tid, "tyre_dy", "1.4")
        self.set(tid, "tyre_th", "slick")
        self.assertEqual(tune.unset_tyre_value(self.work, tid, "tyre_dy", self.cat), {"id": "tyre_dy", "removed": True})
        self.assertEqual(tune.load_tyre(self.work, tid)["values"], {"tyre_th": "slick"})
        before = self.read(tid)
        self.assertEqual(tune.unset_tyre_value(self.work, tid, "tyre_dy", self.cat), {"id": "tyre_dy", "removed": False})
        self.assertEqual(self.read(tid), before)
        with self.assertRaisesRegex(ValueError, "^unknown setting 'nope'$"):
            tune.unset_tyre_value(self.work, tid, "nope", self.cat)
        with self.assertRaisesRegex(ValueError, "tyre_dy_front is not a tyre setting"):
            tune.unset_tyre_value(self.work, tid, "tyre_dy_front", self.cat)

    def test_reset_drops_every_value_and_counts_them(self):
        tid = self.create()
        self.set(tid, "tyre_dy", "1.4")
        self.set(tid, "tyre_th", "slick")
        self.assertEqual(tune.reset_tyre(self.work, tid), {"id": tid, "cleared": 2})
        self.assertEqual(tune.load_tyre(self.work, tid)["values"], {})
        before = self.read(tid)
        self.assertEqual(tune.reset_tyre(self.work, tid), {"id": tid, "cleared": 0})
        self.assertEqual(self.read(tid), before)

    def test_the_values_of_one_tyre_do_not_touch_another(self):
        one, two = self.create("One"), self.create("Two", SLICK_S)
        self.set(one, "tyre_dy", "1.4")
        self.assertEqual(tune.load_tyre(self.work, two)["values"], {})
        self.assertEqual(self.rows(two)["tyre_dy"]["value"], 1.0)


class TestRows(World):
    def test_one_row_per_field_in_the_order_of_the_fields(self):
        tid = self.create()
        rows = tune.tyre_rows(self.work, tid, self.cat, self.game)
        self.assertEqual([r["id"] for r in rows], ["tyre_dy", "tyre_th", "tyre_deep", "tyre_maybe"])
        dy = rows[0]
        self.assertEqual((dy["label"], dy["group"], dy["unit"], dy["type"], dy["min"], dy["max"]), ("Tyre lateral grip", "Tyres", "mu", "float", 0.5, 2.5))
        self.assertNotIn("axle", dy)
        self.assertEqual(rows[1]["choices"], ["road", "slick"])

    def test_the_default_is_read_from_the_source_file(self):
        rows = self.rows(self.create("A", ROAD_A))
        self.assertEqual((rows["tyre_dy"]["default"], rows["tyre_dy"]["value"], rows["tyre_dy"]["changed"]), (1.2, 1.2, False))
        self.assertEqual((rows["tyre_th"]["default"], rows["tyre_th"]["applicable"]), ("road", True))
        rows = self.rows(self.create("S", SLICK_S))
        self.assertEqual((rows["tyre_dy"]["default"], rows["tyre_th"]["default"]), (1.0, "slick"))

    def test_the_source_file_is_the_one_of_the_first_extracted_car(self):
        self.assertEqual(self.rows(self.create("A", ROAD_A))["tyre_dy"]["default"], 1.2)

    def test_a_value_set_is_the_value_and_changed_unless_it_equals_the_default(self):
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_dy", "1.4", self.cat)
        row = self.rows(tid)["tyre_dy"]
        self.assertEqual((row["default"], row["value"], row["changed"]), (1.2, 1.4, True))
        tune.set_tyre_value(self.work, tid, "tyre_dy", "1.2", self.cat)
        self.assertFalse(self.rows(tid)["tyre_dy"]["changed"])

    def test_a_field_the_source_cannot_give_is_listed_with_the_reason_and_no_default(self):
        rows = self.rows(self.create())
        self.assertEqual((rows["tyre_deep"]["applicable"], rows["tyre_deep"]["default"], rows["tyre_deep"]["value"]), (False, None, None))
        self.assertIn("modelData.nope.x: missing field 'nope'", rows["tyre_deep"]["reason"])
        self.assertTrue(rows["tyre_dy"]["applicable"] and rows["tyre_dy"]["reason"] is None)

    def test_a_last_field_the_file_lacks_reads_as_zero_like_the_settings_of_a_car(self):
        row = self.rows(self.create())["tyre_maybe"]
        self.assertEqual((row["applicable"], row["default"], row["reason"]), (True, 0.0, None))

    def test_a_stored_value_that_does_not_fit_is_an_error_naming_the_tyre(self):
        tid = self.create()
        self.write_tyre(tid, {"version": 2, "name": "Slick", "short": "SL", "source": ROAD_A, "values": {"tyre_dy": "fast"}})
        with self.assertRaisesRegex(ValueError, "^tyre slick: tyre_dy expects a number, got 'fast'$"):
            tune.tyre_rows(self.work, tid, self.cat, self.game)

    def test_a_source_that_is_gone_is_an_error_naming_the_tyre_and_the_source(self):
        tid = self.create("S", SLICK_S)
        os.remove(os.path.join(self.a.shared, "tyres", "slick", "s.tyre"))
        with self.assertRaisesRegex(ValueError, "^tyre s: the source %s cannot be read: " % SLICK_S.replace("\\", "\\\\")):
            tune.tyre_rows(self.work, tid, self.cat, self.game)

    def test_a_source_file_that_cannot_be_decoded_is_an_error_naming_the_tyre(self):
        tid = self.create()
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))] = ValueError("broken file")
        with self.assertRaisesRegex(ValueError, "^tyre slick: the source .* cannot be read: broken file$"):
            tune.tyre_rows(self.work, tid, self.cat, self.game)

    def test_the_rows_of_an_empty_catalogue_are_empty(self):
        self.assertEqual(tune.tyre_rows(self.work, self.create(), mini_catalogue(mini_setting("limiter", type="int", targets=[("@engine", "limiter")])), self.game), [])


class TestUsers(World):
    def use(self, tyre_id, tune_id=None, version=None, car="ks_a", value=None):
        value = value or {"sets": [{"front": "own:" + tyre_id, "rear": "game:" + ROAD_B}], "split": False}
        if version is None:
            tune.save_state(self.work, car, {tune.TYRE_KEY: value}, tune_id)
        else:
            tune.save_version_state(self.work, car, {tune.TYRE_KEY: value}, version, tune_id)

    def test_no_state_uses_a_new_tyre(self):
        self.create()
        self.assertEqual(tune.tyre_users(self.work, "slick"), [])

    def test_the_default_tune_other_tunes_and_the_draft_are_found_in_order(self):
        self.create()
        self.use("slick", "ax01")
        self.use("slick", tune.DRAFT)
        self.use("slick", None)
        self.use("slick", "ax02", car="ks_b")
        tune.save_state(self.work, "ks_a", {"limiter": 7000}, "ax03")
        self.assertEqual(tune.tyre_users(self.work, "slick"), [
            {"car": "ks_a", "tune": "ax_a"}, {"car": "ks_a", "tune": "ax01"}, {"car": "ks_a", "tune": tune.DRAFT},
            {"car": "ks_b", "tune": "ax02"}])

    def test_a_version_state_counts_and_names_the_version(self):
        self.create()
        tune.save_state(self.work, "ks_a", {}, "ax01")
        vid = tune.add_version(self.work, "ks_a", "Heavy", "ax01")
        self.use("slick", "ax01", vid)
        self.assertEqual(tune.tyre_users(self.work, "slick"), [{"car": "ks_a", "tune": "ax01", "version": vid}])

    def test_only_the_tyre_in_the_choice_counts_in_every_form_of_the_choice(self):
        self.create()
        self.create("Other")
        self.use("other", "ax01")
        self.assertEqual(tune.tyre_users(self.work, "slick"), [])
        self.use("x", "ax01", value={"split": True, "fronts": ["game:" + ROAD_A], "rears": ["own:slick"]})
        self.assertEqual(tune.tyre_users(self.work, "slick"), [{"car": "ks_a", "tune": "ax01"}])
        self.use("x", "ax01", value={"sets": [{"front": "game:" + ROAD_A, "rear": "game:" + ROAD_B}], "split": False, "start_front": "own:slick"})
        self.assertEqual(tune.tyre_users(self.work, "slick"), [{"car": "ks_a", "tune": "ax01"}])
        self.use("x", "ax01", value=["own:slick", "stock:a|b"])
        self.assertEqual(tune.tyre_users(self.work, "slick"), [{"car": "ks_a", "tune": "ax01"}])
        self.use("x", "ax01", value=["own:slick2"])
        self.assertEqual(tune.tyre_users(self.work, "slick"), [])

    def test_an_unreadable_state_is_ignored(self):
        self.create()
        self.write(tune.state_path(self.work, "ks_a", "ax01"), "{")
        self.write(tune.state_path(self.work, "ks_a", "ax02"), "[]")
        self.write(tune.state_path(self.work, "ks_a", None), '{"_tyres": 5}')
        self.assertEqual(tune.tyre_users(self.work, "slick"), [])


class TestDelete(World):
    def test_a_tyre_that_nothing_uses_is_deleted(self):
        tid = self.create()
        self.assertEqual(tune.delete_tyre(self.work, tid), {"id": "slick", "deleted": True})
        self.assertFalse(tune.tyre_exists(self.work, tid))
        self.assertEqual(tune.list_tyres(self.work), [])

    def test_delete_is_refused_while_a_state_a_version_or_the_draft_uses_the_tyre(self):
        tid = self.create()
        tune.save_state(self.work, "ks_a", {}, "ax01")
        vid = tune.add_version(self.work, "ks_a", "Heavy", "ax01")
        choice = {"sets": [{"front": "own:slick", "rear": "game:" + ROAD_B}], "split": False}
        tune.save_state(self.work, "ks_a", {tune.TYRE_KEY: choice}, "ax01")
        with self.assertRaisesRegex(ValueError, "^tyre slick is used by ks_a / ax01$"):
            tune.delete_tyre(self.work, tid)
        tune.save_version_state(self.work, "ks_a", {tune.TYRE_KEY: choice}, vid, "ax01")
        tune.save_state(self.work, "ks_a", {tune.TYRE_KEY: choice}, tune.DRAFT)
        with self.assertRaisesRegex(ValueError, "^tyre slick is used by ks_a / ax01, ks_a / ax01 / v01, ks_a \\(draft\\)$"):
            tune.delete_tyre(self.work, tid)
        self.assertTrue(tune.tyre_exists(self.work, tid))
        tune.save_state(self.work, "ks_a", {}, "ax01")
        tune.save_version_state(self.work, "ks_a", {}, vid, "ax01")
        with self.assertRaisesRegex(ValueError, "^tyre slick is used by ks_a \\(draft\\)$"):
            tune.delete_tyre(self.work, tid)
        tune.save_state(self.work, "ks_a", {}, tune.DRAFT)
        tune.delete_tyre(self.work, tid)
        self.assertFalse(tune.tyre_exists(self.work, tid))

    def test_a_missing_tyre_is_an_error_even_when_a_state_names_it(self):
        tune.save_state(self.work, "ks_a", {tune.TYRE_KEY: ["own:ghost"]}, "ax01")
        with self.assertRaisesRegex(ValueError, "^no tyre 'ghost' in the library$"):
            tune.delete_tyre(self.work, "ghost")

    def test_a_damaged_tyre_file_can_be_deleted(self):
        self.write_tyre("old", {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        tune.delete_tyre(self.work, "old")
        self.assertEqual(tune.list_tyres(self.work), [])


class TestCommands(World):
    def setUp(self):
        super().setUp()
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)

    def main(self, *argv, game=None):
        game = argv[0] in ("tyre-index", "tyre-new", "tyre-show") if game is None else game
        return self.run_main(*argv, "--work", self.work, *(["--game", self.game] if game else []))

    def test_tyres_on_an_empty_work_folder(self):
        self.assertEqual(self.run_main("tyres", "--work", str(self.d / "empty")), (0, "no tyres in the library\n", ""))
        self.assertFalse(os.path.exists(str(self.d / "empty")))

    def test_tyre_index_lists_label_file_and_type_of_the_available_tyres(self):
        code, out, err = self.main("tyre-index")
        self.assertEqual((code, err), (0, ""))
        lines = [[c.strip() for c in line.split(" | ")] for line in out.splitlines()]
        self.assertEqual(lines[0], ["label", "file", "type"])
        self.assertEqual(lines[2], ["Road a", "a", "road"])
        self.assertIn(["Supercar 235/35 R19", "supercar_235_35_19", "supercar"], lines)
        self.assertEqual(len(lines), 2 + 6)

    def test_tyre_index_with_a_type_keeps_that_type_by_folder_name_or_label_in_any_case(self):
        for text in ("slick", "SLICK", "Slick"):
            with self.subTest(text):
                out = self.main("tyre-index", "--type", text)[1]
                self.assertEqual(sorted(line.split(" | ")[1].strip() for line in out.splitlines()[2:]), ["dup", "s"])
        out = self.main("tyre-index", "--type", "Supercar")[1]
        self.assertEqual([line.split(" | ")[1].strip() for line in out.splitlines()[2:]], ["supercar_235_35_19"])
        code, out, err = self.main("tyre-index", "--type", "road")
        self.assertEqual([line.split(" | ")[1].strip() for line in out.splitlines()[2:]], ["a", "b", "dup"])

    def test_tyre_index_without_tyres_is_a_note(self):
        code, out, err = self.run_main("tyre-index", "--work", str(self.d / "empty"), "--game", self.game)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("note: no tyres to list"))
        code, out, err = self.main("tyre-index", "--type", "nope")
        self.assertTrue(out.startswith("note: no tyres to list"))

    def test_tyre_index_reads_the_package_when_there_is_one(self):
        pkg = str(self.d / "content.kspkg")
        pack(pkg, ["road\\road_235_35_19.tyre"])
        code, out, err = self.run_main("tyre-index", "--work", self.work, "--game", pkg)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("road_235_35_19", out)
        self.assertNotIn("supercar", out)

    def test_new_set_show_unset_delete(self):
        code, out, err = self.main("tyre-new", "--name", "Slick Soft", "--source", "a")
        self.assertEqual((code, out, err), (0, "created tyre slick_soft: Slick Soft (SS, source %s)\n" % ROAD_A, ""))
        self.assertEqual(self.main("tyre-set", "slick_soft", "tyre_dy", "1.4", game=False), (0, "tyre_dy = 1.4\n", ""))
        code, out, err = self.main("tyre-show", "slick_soft")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "tyre slick_soft: Slick Soft (SS), source %s" % ROAD_A)
        rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")] for line in lines[3:]}
        self.assertEqual([c.strip() for c in lines[1].split("|")], ["", "id", "value", "default", "unit", "note"])
        self.assertEqual(rows["tyre_dy"][:5], ["*", "tyre_dy", "1.4", "1.2", "mu"])
        self.assertEqual(rows["tyre_deep"][1:5], ["tyre_deep", "-", "-", ""])
        self.assertIn("modelData.nope.x: missing field 'nope'", rows["tyre_deep"][5])
        self.assertEqual(self.main("tyre-unset", "slick_soft", "tyre_dy", game=False), (0, "tyre_dy removed from the tyre\n", ""))
        self.assertEqual(self.main("tyre-unset", "slick_soft", "tyre_dy", game=False), (0, "tyre_dy was not set\n", ""))
        self.assertEqual(self.main("tyre-delete", "slick_soft", game=False), (0, "deleted tyre slick_soft\n", ""))
        self.assertEqual(self.main("tyres", game=False), (0, "no tyres in the library\n", ""))

    def test_new_with_a_short_name(self):
        code, out, err = self.main("tyre-new", "--name", "Soft", "--source", ROAD_A, "--short", "Q7")
        self.assertEqual((code, out), (0, "created tyre soft: Soft (Q7, source %s)\n" % ROAD_A))
        self.assertEqual(tune.load_tyre(self.work, "soft")["short"], "Q7")

    def test_tyres_lists_one_line_per_tyre_and_the_damaged_ones(self):
        self.main("tyre-new", "--name", "Slick", "--source", "a")
        self.main("tyre-set", "slick", "tyre_dy", "1.2", game=False)
        self.write_tyre("broken", "{")
        self.write_tyre("old", {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        code, out, err = self.main("tyres", game=False)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual([c.strip() for c in lines[0].split("|")], ["id", "name", "short", "source", "changed"])
        self.assertEqual([c.strip() for c in lines[2].split("|")], ["slick", "Slick", "SL", ROAD_A, "1"])
        self.assertTrue(lines[3].startswith("broken"))
        self.assertIn("old front/rear form", lines[4])
        self.assertEqual(len(lines), 5)

    def test_set_prints_the_range_warning_on_stderr(self):
        self.main("tyre-new", "--name", "Slick", "--source", "a")
        self.assertEqual(self.main("tyre-set", "slick", "tyre_dy", "9", game=False),
                         (0, "tyre_dy = 9.0\n", "warning: tyre_dy=9.0 is outside the suggested range 0.5..2.5\n"))

    def test_runtime_errors_are_error_lines_with_exit_1(self):
        self.main("tyre-new", "--name", "Slick", "--source", "a")
        for argv, message in ((("tyre-new", "--name", "Slick", "--source", "a"), "error: a tyre named 'Slick' exists already (slick)\n"),
                              (("tyre-new", "--name", "X", "--source", "nope"), "error: unknown tyre 'nope', tyre-index lists the tyres\n"),
                              (("tyre-new", "--name", "X", "--source", "dup"), "error: 'dup' names 2 tyres"),
                              (("tyre-new", "--name", "X", "--source", "a", "--short", "abc"), "error: a tyre short name needs"),
                              (("tyre-set", "slick", "limiter", "1"), "error: limiter is not a tyre setting\n"),
                              (("tyre-set", "slick", "tyre_dy_front", "1"), "error: tyre_dy_front is not a tyre setting\n"),
                              (("tyre-set", "slick", "tyre_dy", "fast"), "error: tyre_dy expects a number, got 'fast'\n"),
                              (("tyre-set", "nope", "tyre_dy", "1"), "error: no tyre 'nope' in the library\n"),
                              (("tyre-show", "../x"), "error: bad tyre id '../x'"), (("tyre-delete", "nope"), "error: no tyre 'nope' in the library\n"),
                              (("tyre-unset", "slick", "nope"), "error: unknown setting 'nope'\n")):
            with self.subTest(argv):
                code, out, err = self.main(*argv)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith(message), err)

    def test_delete_is_refused_while_a_modded_car_uses_the_tyre(self):
        self.main("tyre-new", "--name", "Slick", "--source", "a")
        tune.save_state(self.work, "ks_a", {tune.TYRE_KEY: {"sets": [{"front": "own:slick", "rear": "game:" + ROAD_B}], "split": False}}, "ax01")
        self.assertEqual(self.main("tyre-delete", "slick", game=False), (1, "", "error: tyre slick is used by ks_a / ax01\n"))
        self.assertTrue(os.path.isfile(tune.tyre_path(self.work, "slick")))

    def test_show_of_a_tyre_whose_source_is_gone_is_an_error_line(self):
        self.main("tyre-new", "--name", "Slick", "--source", "s")
        os.remove(os.path.join(self.a.shared, "tyres", "slick", "s.tyre"))
        code, out, err = self.main("tyre-show", "slick")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: tyre slick: the source %s cannot be read" % SLICK_S), err)

    def test_the_work_folder_is_expanded(self):
        code, out, err = self.run_main("tyres", "--work", "%ACE_TEST_NO_SUCH_VAR%/w")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: cannot expand the work directory"), err)

    def test_the_game_option_is_expanded_like_the_other_paths(self):
        with mock.patch.dict(os.environ, {"ACE_TEST_GAME": self.game}):
            code, out, err = self.run_main("tyre-index", "--work", self.work, "--game", "%ACE_TEST_GAME%")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("supercar_235_35_19", out)


class TestCliUsage(unittest.TestCase):
    def test_the_usage_block_lists_every_tyre_command(self):
        for cmd in ("tyres", "tyre-index", "tyre-new", "tyre-show", "tyre-set", "tyre-unset", "tyre-delete"):
            self.assertIn("python tools/tune.py " + cmd + " ", USAGE)
        self.assertNotIn("tyre-sources", USAGE)
        self.assertNotIn("--car", "\n".join(line for line in USAGE.splitlines() if "tyre" in line and "tyres-convert" not in line))
        self.assertIn("python tools/tune.py tyres-convert --name <text>", USAGE)


usage_cases(TestCliUsage, USAGE, (("no_arguments", []), ("tyres_with_a_positional", ["tyres", "x"]), ("tyre_index_with_a_positional", ["tyre-index", "x"]),
                                  ("tyre_index_with_the_old_name", ["tyre-sources"]), ("tyre_index_type_without_value", ["tyre-index", "--type"]),
                                  ("tyre_new_without_options", ["tyre-new"]), ("tyre_new_without_source", ["tyre-new", "--name", "x"]),
                                  ("tyre_new_without_name", ["tyre-new", "--source", "k"]),
                                  ("tyre_new_with_a_positional", ["tyre-new", "--name", "x", "--source", "k", "y"]),
                                  ("tyre_new_option_without_value", ["tyre-new", "--name"]), ("tyre_new_short_without_value", ["tyre-new", "--name", "x", "--source", "k", "--short"]),
                                  ("tyre_show_without_id", ["tyre-show"]), ("tyre_show_with_two_ids", ["tyre-show", "a", "b"]),
                                  ("tyre_set_with_two_operands", ["tyre-set", "a", "b"]), ("tyre_set_with_four_operands", ["tyre-set", "a", "b", "c", "d"]),
                                  ("tyre_set_without_operands", ["tyre-set"]),
                                  ("tyre_unset_with_one_operand", ["tyre-unset", "a"]), ("tyre_unset_with_three_operands", ["tyre-unset", "a", "b", "c"]),
                                  ("tyre_delete_without_id", ["tyre-delete"]), ("tyre_delete_with_two_ids", ["tyre-delete", "a", "b"]),
                                  ("tyres_with_a_car", ["tyres", "--car", "ks_x"]), ("tyre_show_with_a_tune", ["tyre-show", "a", "--tune", "ax01"]),
                                  ("tyre_set_with_an_unknown_option", ["tyre-set", "a", "b", "c", "--bogus", "1"])), tune, check_empty=True)


class TestCliSubprocess(unittest.TestCase):
    def test_tyres_on_an_empty_work_folder_writes_nothing(self):
        with tmp() as d:
            r = run_tool("tune.py", "tyres", "--work", d / "w", cwd=d)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "no tyres in the library\n", ""))
            self.assertEqual(os.listdir(d), [])

    def test_tyre_index_on_an_empty_work_folder_without_a_package(self):
        with tmp() as d:
            r = run_tool("tune.py", "tyre-index", "--work", d / "w", "--game", d / "no.kspkg", cwd=d)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertTrue(r.stdout.startswith("note: no tyres to list"))

    def test_runtime_errors_are_error_lines_on_stderr_with_exit_1(self):
        with tmp() as d:
            for argv, message in ((("tyre-new", "--name", "x", "--source", "nokey"), "error: unknown tyre 'nokey'"),
                                  (("tyre-show", "nope"), "error: no tyre 'nope' in the library\n"),
                                  (("tyre-set", "nope", "tyre_grip_lateral", "1"), "error: no tyre 'nope' in the library\n"),
                                  (("tyre-unset", "../x", "a"), "error: bad tyre id '../x'"), (("tyre-delete", "A"), "error: bad tyre id 'A'")):
                with self.subTest(argv):
                    game = ["--game", str(d / "no.kspkg")] if argv[0] in ("tyre-new", "tyre-show") else []
                    code, out, err = run_main(tune.main, ["tune.py", *argv, "--work", str(d / "w"), *game], cwd=d)
                    self.assertEqual((code, out), (1, ""))
                    self.assertTrue(err.startswith(message), err)
            self.assertEqual(os.listdir(d), [])

    def test_a_tyre_file_in_the_work_folder_is_listed_and_shown_as_an_error_when_damaged(self):
        with tmp() as d:
            os.makedirs(d / "w" / "tyres")
            (d / "w" / "tyres" / "x.json").write_text("{", encoding="utf-8")
            r = run_tool("tune.py", "tyres", "--work", d / "w", cwd=d)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertIn("error: ", r.stdout)
            r = run_tool("tune.py", "tyre-delete", "x", "--work", d / "w", cwd=d)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "deleted tyre x\n", ""))


if __name__ == "__main__":
    unittest.main()
