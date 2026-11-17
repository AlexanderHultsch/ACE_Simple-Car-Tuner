"""Tests for tools/logfacts.py without the game: finding the modded or stock car of a car name, the tuner facts of the session header (values, garage, turbo kit, sounds, last build) on scratch work and mods folders, the creation time of the game process on a fake Win32 layer, and make_facts.

The real work folder, mods folder and game folder are never touched, and the game's shared memory is never opened. Where the effective rows would need a decoded car they are patched, one test reads a stubbed car (support.FakeCar) through the real tune.effective_rows.
"""
import calendar
import ctypes
import datetime
import json
import os
import re
import sys
import unittest
from unittest import mock

from support import FakeCar, Sandbox, mini_catalogue, mini_setting

import logfacts
import tune

REAL_LOAD_STATE = tune.load_state
ISO_OFFSET = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
START = "2026-11-16T18:30:12+01:00"
SNAPSHOT_TIME = "2026-11-15T10:00:00Z"
KIT = {"donor": "ks_donor", "label": "Donor", "kind": "single turbo", "boost": [0.8]}
GARAGE = {"keys": ["own:fast", "stock:a|b"], "start": "own:fast"}
SOUNDS = {"turbo": "event:/parts/turbos/turbo_rx7"}
CHANGES = {"since": None, "settings": [{"id": "limiter", "from": 7000, "to": 8000}], "extras": [], "total": 1}
BUILD_KEYS = ["snapshot_time", "package_time", "settings", "kit", "garage", "sounds", "changes"]
MODDED_KEYS = ["matched", "modded", "stock_car", "tune_id", "default", "name_suffix", "values", "garage", "turbo_kit", "sounds", "build",
               "game_process_start"]


def suffix():
    return mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix")


def limiter():
    return mini_setting("limiter", type="int", min=3000, max=12000, targets=[("@engine", "limiter")])


def snapshot(**kw):
    data = {"version": 1, "settings": {"limiter": 8000}, "kit": KIT, "garage": GARAGE, "sounds": SOUNDS, "name": "Alpha Stock MY",
            "time": SNAPSHOT_TIME, "changes": CHANGES}
    data.update(kw)
    return data


class FactsCase(Sandbox):
    """Two stock cars in a scratch work folder: ks_alpha (display name Alpha Stock) with the modded cars ax_alpha (default, suffix MY)
    and ax_alp01 (suffix Drift), and ks_bravo (Bravo Stock) without any tune."""

    def setUp(self):
        super().setUp()
        self.work, self.mods = str(self.d / "work"), str(self.d / "mods")
        os.makedirs(self.mods)
        self.patch(tune, "load_cars", lambda path=None: {"default": "ks_alpha", "cars": [{"id": "ks_alpha", "label": "Alpha"},
                                                                                       {"id": "ks_bravo", "label": "Bravo"}]})
        self.catalogue = mini_catalogue(suffix(), limiter())
        self.patch(tune, "load_catalogue", lambda path=None: self.catalogue)
        self.rows = [{"id": "name_suffix", "value": "MY", "default": "MY"}, {"id": "limiter", "value": 8000, "default": tune.to_f32(7000.0)}]
        self.row_calls = []
        self.patch(tune, "effective_rows", self.effective_rows)
        self.stock_info("ks_alpha", "Alpha Stock")
        self.stock_info("ks_bravo", "Bravo Stock")
        os.makedirs(tune.base_dir(self.work, "ks_bravo"))
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY", "limiter": 8000})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "Drift"}, "ax_alp01")

    def effective_rows(self, work, car_id, catalogue=None, hidden=False, tune=None):
        self.row_calls.append((work, car_id, catalogue, hidden, tune))
        REAL_LOAD_STATE(work, car_id, tune)
        return self.rows

    def stock_info(self, car_id, name):
        self.write(tune.stock_info_path(self.work, car_id), {"car_id": car_id, "display_name": name, "brand": "B", "year": 1999})

    def package(self, tune_id, mtime=None):
        path = self.write(os.path.join(self.mods, tune_id + ".kspkg"), b"p", binary=True)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def facts(self, name, start=None):
        got = logfacts.tuner_facts(self.work, self.mods, name, start)
        json.dumps(got, allow_nan=False)
        return got


class TestFindCar(FactsCase):
    def find(self, name):
        got = logfacts.find_car(self.work, self.mods, name)
        json.dumps(got)
        return got

    def test_a_modded_car_by_its_id(self):
        self.assertEqual(self.find("ax_alp01"), {"matched": True, "modded": True, "stock_car": "ks_alpha", "tune_id": "ax_alp01", "default": False,
                                                 "name_suffix": "Drift"})
        self.assertEqual(self.find("ax_alpha"), {"matched": True, "modded": True, "stock_car": "ks_alpha", "tune_id": "ax_alpha", "default": True,
                                                 "name_suffix": "MY"})

    def test_a_modded_car_by_its_label(self):
        self.assertEqual(self.find("Alpha Stock Drift"), {"matched": True, "modded": True, "stock_car": "ks_alpha", "tune_id": "ax_alp01",
                                                          "default": False, "name_suffix": "Drift"})
        self.assertEqual(self.find("Alpha Stock MY")["tune_id"], "ax_alpha")

    def test_a_stock_car_by_its_id_and_by_its_display_name(self):
        want = {"matched": True, "modded": False, "stock_car": "ks_bravo"}
        self.assertEqual(self.find("ks_bravo"), want)
        self.assertEqual(self.find("Bravo Stock"), want)
        self.assertEqual(self.find("Alpha Stock"), {"matched": True, "modded": False, "stock_car": "ks_alpha"})
        self.assertEqual(self.find("ks_alpha")["modded"], False)

    def test_case_and_spaces_at_the_ends_are_ignored(self):
        for name in ("AX_ALP01", "  ax_alp01 ", "alpha stock DRIFT", "\tAlpha Stock Drift\n"):
            with self.subTest(name=name):
                self.assertEqual(self.find(name)["tune_id"], "ax_alp01")
        for name in ("KS_BRAVO", " bravo stock  "):
            with self.subTest(name=name):
                self.assertEqual(self.find(name), {"matched": True, "modded": False, "stock_car": "ks_bravo"})

    def test_spaces_inside_the_name_count(self):
        self.assertFalse(self.find("Alpha  Stock Drift")["matched"])

    def test_an_unknown_name_is_not_matched(self):
        for name in ("", "  ", "Gamma", "ax_alp02", "Alpha Stock Drif", "ks_bravo2"):
            with self.subTest(name=name):
                self.assertEqual(self.find(name), {"matched": False, "reason": "car not found in the tuner work folder"})

    def test_the_id_of_a_modded_car_wins_over_the_label_of_another_and_a_modded_car_over_a_stock_car(self):
        rows = [{"id": "a1", "stock": "ks_alpha", "label": "x", "name_suffix": "s", "default": False},
                {"id": "x", "stock": "ks_bravo", "label": "zz", "name_suffix": "t", "default": True}]
        with mock.patch.object(tune, "list_modded", lambda work, mods=None: rows):
            self.assertEqual(self.find("x")["tune_id"], "x")
            self.assertEqual(self.find("zz")["tune_id"], "x")
            self.assertEqual(self.find("Alpha Stock")["modded"], False)
        rows[0]["label"] = "Alpha Stock"
        with mock.patch.object(tune, "list_modded", lambda work, mods=None: rows):
            self.assertEqual(self.find("Alpha Stock"), {"matched": True, "modded": True, "stock_car": "ks_alpha", "tune_id": "a1", "default": False,
                                                        "name_suffix": "s"})

    def test_a_stock_car_without_stock_info_uses_the_cached_index_and_a_damaged_info_too(self):
        os.remove(tune.stock_info_path(self.work, "ks_bravo"))
        self.write(tune.cars_index_path(self.work), [{"id": "ks_bravo", "display_name": "Bravo Game"}, {"id": "ks_other", "display_name": "Other Game"}])
        self.assertEqual(self.find("bravo game"), {"matched": True, "modded": False, "stock_car": "ks_bravo"})
        self.write(tune.stock_info_path(self.work, "ks_bravo"), '{"car_id": "ks_bravo", "disp')
        self.assertEqual(self.find("Bravo Game")["stock_car"], "ks_bravo")
        self.assertFalse(self.find("Bravo Stock")["matched"])

    def test_a_car_of_the_index_without_a_folder_in_the_work_folder_is_not_matched(self):
        self.write(tune.cars_index_path(self.work), [{"id": "ks_other", "display_name": "Other Game"}])
        self.assertFalse(self.find("Other Game")["matched"])
        self.assertFalse(self.find("ks_other")["matched"])

    def test_an_empty_work_folder_matches_nothing(self):
        got = logfacts.find_car(str(self.d / "nowhere"), self.mods, "ax_alpha")
        self.assertEqual(got, {"matched": False, "reason": "car not found in the tuner work folder"})

    def test_the_mods_folder_does_not_matter_for_finding(self):
        self.assertTrue(logfacts.find_car(self.work, str(self.d / "no_mods"), "ax_alp01")["matched"])


class TestTunerFactsOfAModdedCar(FactsCase):
    def test_the_default_tune_with_everything_set(self):
        state = {"name_suffix": "MY", "limiter": 8000, tune.TYRE_KEY: ["own:fast", "stock:a|b"], tune.TURBO_KEY: {"donor": "ks_donor"},
                 tune.SOUND_KEY: SOUNDS}
        tune.save_state(self.work, "ks_alpha", state)
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        self.package("ax_alpha", 1700000000)
        got = self.facts("Alpha Stock MY", START)
        self.assertEqual(list(got), MODDED_KEYS)
        package_time = got["build"].pop("package_time")
        self.assertEqual(got, {
            "matched": True, "modded": True, "stock_car": "ks_alpha", "tune_id": "ax_alpha", "default": True, "name_suffix": "MY",
            "values": {"name_suffix": {"value": "MY", "default": "MY"}, "limiter": {"value": 8000, "default": 7000.0}},
            "garage": {"keys": ["own:fast", "stock:a|b"]}, "turbo_kit": {"donor": "ks_donor"}, "sounds": SOUNDS,
            "build": {"snapshot_time": SNAPSHOT_TIME, "settings": {"limiter": 8000}, "kit": KIT, "garage": GARAGE, "sounds": SOUNDS,
                      "changes": CHANGES},
            "game_process_start": START})
        self.assertRegex(package_time, ISO_OFFSET)

    def test_the_rows_are_read_for_the_stock_car_the_applicable_settings_and_the_tune_as_the_server_passes_it(self):
        self.facts("ax_alpha")
        self.facts("ax_alp01")
        self.assertEqual(self.row_calls, [(self.work, "ks_alpha", self.catalogue, False, None), (self.work, "ks_alpha", self.catalogue, False, "ax_alp01")])

    def test_float32_values_are_plain_numbers_in_the_text_of_the_file(self):
        self.rows = [{"id": "f", "value": tune.to_f32(0.1), "default": tune.to_f32(0.2)}, {"id": "b", "value": True, "default": False},
                     {"id": "e", "value": "a", "default": "b"}]
        got = self.facts("ax_alpha")
        self.assertEqual(json.dumps(got["values"]), '{"f": {"value": 0.1, "default": 0.2}, "b": {"value": true, "default": false}, '
                                                    '"e": {"value": "a", "default": "b"}}')

    def test_a_tune_without_saved_extras_has_none_and_an_empty_sound_dict(self):
        got = self.facts("ax_alp01")
        self.assertEqual((got["garage"], got["turbo_kit"], got["sounds"]), (None, None, {}))
        self.assertEqual((got["tune_id"], got["default"], got["name_suffix"]), ("ax_alp01", False, "Drift"))

    def test_the_second_tune_reads_its_own_state(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "Drift", tune.TYRE_KEY: ["stock:a|b"], tune.TURBO_KEY: {"donor": "ks_d2"},
                                                tune.SOUND_KEY: {"backfire": "event:/b"}}, "ax_alp01")
        got = self.facts("ax_alp01")
        self.assertEqual((got["garage"], got["turbo_kit"], got["sounds"]), ({"keys": ["stock:a|b"]}, {"donor": "ks_d2"}, {"backfire": "event:/b"}))
        other = self.facts("ax_alpha")
        self.assertEqual((other["garage"], other["turbo_kit"], other["sounds"]), (None, None, {}))

    def test_the_game_start_is_stored_as_given(self):
        self.assertIsNone(self.facts("ax_alpha")["game_process_start"])
        self.assertEqual(self.facts("ax_alpha", START)["game_process_start"], START)

    def test_the_saved_values_are_not_shared_with_the_state(self):
        tune.save_state(self.work, "ks_alpha", {tune.SOUND_KEY: dict(SOUNDS), tune.TYRE_KEY: ["stock:a|b"]})
        got = self.facts("ax_alpha")
        got["sounds"]["turbo"] = "changed"
        got["garage"]["keys"].append("own:x")
        state = tune.load_state(self.work, "ks_alpha")
        self.assertEqual((state[tune.SOUND_KEY], state[tune.TYRE_KEY]), (SOUNDS, ["stock:a|b"]))


class TestBuildFacts(FactsCase):
    def build(self, name="ax_alpha"):
        return self.facts(name)["build"]

    def test_a_never_built_car_has_every_build_field_none(self):
        self.assertEqual(self.build(), dict.fromkeys(BUILD_KEYS))
        self.assertEqual(list(self.build()), BUILD_KEYS)

    def test_an_installed_package_without_a_snapshot_still_has_its_package_time(self):
        self.package("ax_alpha", 1700000000)
        got = self.build()
        self.assertEqual(list(got), BUILD_KEYS)
        self.assertEqual(datetime.datetime.fromisoformat(got["package_time"]).timestamp(), 1700000000)
        self.assertRegex(got["package_time"], ISO_OFFSET)
        self.assertEqual({k: v for k, v in got.items() if k != "package_time"}, dict.fromkeys(BUILD_KEYS[:1] + BUILD_KEYS[2:]))
        json.dumps(got)

    def test_a_damaged_snapshot_with_an_installed_package_keeps_the_package_time_only(self):
        self.write(tune.snapshot_path(self.work, "ks_alpha", "ax_alpha"), "{")
        self.package("ax_alpha", 1700000000)
        got = self.build()
        self.assertEqual(datetime.datetime.fromisoformat(got["package_time"]).timestamp(), 1700000000)
        self.assertEqual([k for k, v in got.items() if v is not None], ["package_time"])

    def test_the_fields_of_the_snapshot_and_the_package_time(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        self.package("ax_alpha", 1700000000)
        got = self.build()
        self.assertEqual(list(got), BUILD_KEYS)
        self.assertEqual((got["snapshot_time"], got["settings"], got["kit"], got["garage"], got["sounds"], got["changes"]),
                         (SNAPSHOT_TIME, {"limiter": 8000}, KIT, GARAGE, SOUNDS, CHANGES))
        self.assertRegex(got["package_time"], ISO_OFFSET)
        self.assertEqual(datetime.datetime.fromisoformat(got["package_time"]).timestamp(), 1700000000)
        self.assertEqual(datetime.datetime.fromisoformat(got["package_time"]).utcoffset(),
                         datetime.datetime.fromtimestamp(1700000000).astimezone().utcoffset())

    def test_the_package_time_follows_the_file_time_of_the_right_package(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        tune.save_snapshot(self.work, "ks_alpha", "ax_alp01", snapshot())
        self.package("ax_alpha", 1700000000)
        self.package("ax_alp01", 1700003600)
        self.assertEqual(datetime.datetime.fromisoformat(self.build("ax_alpha")["package_time"]).timestamp(), 1700000000)
        self.assertEqual(datetime.datetime.fromisoformat(self.build("ax_alp01")["package_time"]).timestamp(), 1700003600)

    def test_a_package_that_is_not_in_the_mods_folder_gives_none_for_its_time_only(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        got = self.build()
        self.assertIsNone(got["package_time"])
        self.assertEqual((got["snapshot_time"], got["changes"]), (SNAPSHOT_TIME, CHANGES))
        self.mods = str(self.d / "no_mods")
        self.assertIsNone(self.build()["package_time"])

    def test_a_snapshot_without_changes_gives_none_for_the_changes_and_keeps_the_rest(self):
        data = snapshot()
        del data["changes"]
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", data)
        got = self.build()
        self.assertIsNone(got["changes"])
        self.assertEqual((got["snapshot_time"], got["settings"], got["kit"], got["garage"], got["sounds"]),
                         (SNAPSHOT_TIME, {"limiter": 8000}, KIT, GARAGE, SOUNDS))

    def test_a_snapshot_of_a_build_without_kit_garage_and_sounds(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot(settings={}, kit=None, garage=None, sounds={}))
        got = self.build()
        self.assertEqual((got["settings"], got["kit"], got["garage"], got["sounds"]), ({}, None, None, {}))

    def test_a_damaged_snapshot_file_counts_as_never_built_like_load_snapshot(self):
        for text in ("{", "[]", '{"version": 2}'):
            with self.subTest(text=text):
                self.write(tune.snapshot_path(self.work, "ks_alpha", "ax_alpha"), text)
                self.assertEqual(self.build(), dict.fromkeys(BUILD_KEYS))

    def test_a_failing_build_part_is_an_error_and_the_rest_is_kept(self):
        tune.save_state(self.work, "ks_alpha", {tune.TYRE_KEY: ["stock:a|b"]})
        with mock.patch.object(tune, "load_snapshot", side_effect=OSError("disk gone")):
            got = self.facts("ax_alpha", START)
        self.assertEqual(got["build"], {"error": "disk gone"})
        self.assertEqual((got["garage"], got["values"]["limiter"]["value"], got["game_process_start"]), ({"keys": ["stock:a|b"]}, 8000, START))
        self.assertEqual(list(got), MODDED_KEYS)


class TestHomeFolderInErrors(FactsCase):
    def setUp(self):
        super().setUp()
        self.home = str(self.d)
        patch = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        patch.start()
        self.addCleanup(patch.stop)

    def assert_no_home(self, facts):
        text = json.dumps(facts)
        self.assertNotIn(self.home, text)
        self.assertNotIn(json.dumps(self.home)[1:-1], text)

    def test_the_text_has_the_home_folder_shortened(self):
        self.assertEqual(logfacts.error_text(ValueError("%s%sx.json: bad" % (self.home, os.sep))), "~%sx.json: bad" % os.sep)
        self.assertEqual(logfacts.error_text(ValueError("nothing personal")), "nothing personal")
        self.assertEqual(logfacts.error_text(OSError(2, "gone")), "[Errno 2] gone")

    def test_a_home_folder_that_cannot_be_found_leaves_the_text_alone(self):
        for home in ("~", "/", ""):
            with self.subTest(home=home), mock.patch.object(os.path, "expanduser", return_value=home):
                self.assertEqual(logfacts.error_text(ValueError("a/b/c")), "a/b/c")

    def test_a_damaged_state_file_has_no_home_folder_in_any_part(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        found = logfacts.find_car(self.work, self.mods, "ax_alpha")
        with mock.patch.object(logfacts, "find_car", return_value=found):
            self.write(tune.state_path(self.work, "ks_alpha"), '{"name_suffix": "M')
            got = self.facts("ax_alpha", START)
        self.assertIn("~", got["values"]["error"])
        for key in ("values", "garage", "turbo_kit", "sounds"):
            self.assertEqual(list(got[key]), ["error"], key)
        self.assert_no_home(got)

    def test_a_damaged_file_read_by_part_has_no_home_folder(self):
        path = self.write(os.path.join(self.work, "x.json"), "{")
        got = logfacts.part(tune.read_json, path)
        self.assertEqual(list(got), ["error"])
        self.assertTrue(got["error"].startswith("~"), got)
        self.assert_no_home(got)

    def test_the_list_of_modded_cars_failing_has_no_home_folder_in_the_error(self):
        self.write(tune.state_path(self.work, "ks_alpha", "ax_alp01"), "{")
        got = self.facts("ax_alpha", START)
        self.assertIn("tune_state.json", got["error"])
        self.assert_no_home(got)

    def test_any_other_failure_of_the_search_has_no_home_folder_in_the_error(self):
        with mock.patch.object(tune, "list_modded", side_effect=RuntimeError("cannot read %s" % os.path.join(self.home, "work"))):
            got = self.facts("ax_alpha", START)
        self.assertEqual(got["error"], "cannot read %s" % os.path.join("~", "work"))
        self.assert_no_home(got)


class TestDamagedParts(FactsCase):
    def found(self, name="ax_alpha"):
        """The result of find_car for name, to be used while the state file is damaged (list_modded reads every state file itself)."""
        return mock.patch.object(logfacts, "find_car", return_value=logfacts.find_car(self.work, self.mods, name))

    def test_a_damaged_state_file_gives_an_error_for_the_state_parts_and_the_values(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        with self.found():
            self.write(tune.state_path(self.work, "ks_alpha"), '{"name_suffix": "M')
            got = self.facts("ax_alpha", START)
        for key in ("values", "garage", "turbo_kit", "sounds"):
            self.assertEqual(list(got[key]), ["error"], key)
            self.assertIsInstance(got[key]["error"], str)
        self.assertEqual(got["build"]["snapshot_time"], SNAPSHOT_TIME)
        self.assertEqual((got["matched"], got["tune_id"], got["game_process_start"]), (True, "ax_alpha", START))
        self.assertEqual(list(got), MODDED_KEYS)

    def test_a_state_that_is_not_an_object_is_the_same(self):
        with self.found():
            self.write(tune.state_path(self.work, "ks_alpha"), "[1]")
            got = self.facts("ax_alpha")
        self.assertEqual([list(got[k]) for k in ("values", "garage", "turbo_kit", "sounds")], [["error"]] * 4)

    def test_a_damaged_state_of_an_unrelated_tune_still_gives_the_stock_match(self):
        self.write(tune.state_path(self.work, "ks_alpha", "ax_alp01"), "{")
        for name, want in (("Bravo Stock", "ks_bravo"), ("ks_bravo", "ks_bravo"), ("Alpha Stock", "ks_alpha"), ("KS_ALPHA", "ks_alpha")):
            self.assertEqual(self.facts(name, START), {"matched": True, "modded": False, "stock_car": want, "game_process_start": START})

    def test_a_car_that_exists_only_as_a_modded_car_with_a_damaged_state_is_unmatched_with_the_error(self):
        self.write(tune.state_path(self.work, "ks_alpha", "ax_alp01"), "{")
        for name in ("ax_alpha", "ax_alp01", "Alpha Stock Drift"):
            got = self.facts(name, START)
            self.assertEqual(list(got), ["matched", "reason", "error", "game_process_start"])
            self.assertEqual((got["matched"], got["reason"], got["game_process_start"]), (False, "car not found in the tuner work folder", START))
            self.assertIn("tune_state.json", got["error"])
            json.dumps(logfacts.find_car(self.work, self.mods, name))

    def test_an_unmatched_name_without_a_failure_has_no_error_key(self):
        self.assertEqual(logfacts.find_car(self.work, self.mods, "Gamma"), {"matched": False, "reason": "car not found in the tuner work folder"})

    def test_an_oserror_of_the_list_is_handled_like_a_valueerror(self):
        with mock.patch.object(tune, "list_modded", side_effect=PermissionError("denied")):
            self.assertEqual(logfacts.find_car(self.work, self.mods, "ax_alpha"),
                             {"matched": False, "reason": "car not found in the tuner work folder", "error": "denied"})
            self.assertEqual(logfacts.find_car(self.work, self.mods, "Bravo Stock")["stock_car"], "ks_bravo")

    def test_each_damaged_entry_is_an_error_under_its_own_key_only(self):
        for key, bad, others in ((tune.TYRE_KEY, "stock:a|b", ("turbo_kit", "sounds")), (tune.TURBO_KEY, 5, ("garage", "sounds")),
                                 (tune.SOUND_KEY, [], ("garage", "turbo_kit"))):
            with self.subTest(key=key):
                tune.save_state(self.work, "ks_alpha", {key: bad, "name_suffix": "MY"})
                got = self.facts("ax_alpha")
                part = {tune.TYRE_KEY: "garage", tune.TURBO_KEY: "turbo_kit", tune.SOUND_KEY: "sounds"}[key]
                self.assertEqual(list(got[part]), ["error"])
                self.assertEqual([got[o] for o in others], [{} if o == "sounds" else None for o in others])
                self.assertEqual(got["values"]["limiter"]["value"], 8000)

    def test_failing_rows_are_an_error_for_the_values_only(self):
        tune.save_state(self.work, "ks_alpha", {tune.TURBO_KEY: {"donor": "ks_donor"}})
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        with mock.patch.object(tune, "effective_rows", side_effect=ValueError("no base car in x, run init first")):
            got = self.facts("ax_alpha")
        self.assertEqual(got["values"], {"error": "no base car in x, run init first"})
        self.assertEqual((got["turbo_kit"], got["build"]["snapshot_time"]), ({"donor": "ks_donor"}, SNAPSHOT_TIME))

    def test_a_catalogue_that_cannot_be_read_is_an_error_for_the_values_only(self):
        with self.found():
            self.patch(tune, "load_catalogue", mock.Mock(side_effect=ValueError("catalogue broken")))
            got = self.facts("ax_alpha")
        self.assertEqual(got["values"], {"error": "catalogue broken"})
        self.assertEqual(got["sounds"], {})

    def test_a_catalogue_that_cannot_be_read_skips_the_modded_cars_but_not_the_stock_cars(self):
        self.patch(tune, "load_catalogue", mock.Mock(side_effect=ValueError("catalogue broken")))
        self.assertEqual(self.facts("ax_alpha", START), {"matched": False, "reason": "car not found in the tuner work folder",
                                                         "error": "catalogue broken", "game_process_start": START})
        self.assertEqual(self.facts("Bravo Stock", START), {"matched": True, "modded": False, "stock_car": "ks_bravo", "game_process_start": START})

    def test_a_failing_list_gives_an_unmatched_entry_with_the_reason_the_error_and_the_game_start(self):
        with mock.patch.object(tune, "list_modded", side_effect=ValueError("cannot expand the path 'x'")):
            got = self.facts("ax_alpha", START)
        self.assertEqual(got, {"matched": False, "reason": "car not found in the tuner work folder", "error": "cannot expand the path 'x'",
                               "game_process_start": START})

    def test_any_other_failure_of_the_search_is_still_an_error_entry(self):
        with mock.patch.object(tune, "list_modded", side_effect=RuntimeError("boom")):
            self.assertEqual(self.facts("ax_alpha", START), {"matched": False, "error": "boom", "game_process_start": START})

    def test_a_package_time_that_cannot_be_read_is_an_error_in_the_build_part_only(self):
        tune.save_snapshot(self.work, "ks_alpha", "ax_alpha", snapshot())
        with mock.patch.object(tune, "stat_or_none", side_effect=PermissionError("denied")):
            got = self.facts("ax_alpha")
        self.assertEqual(got["build"], {"error": "denied"})
        self.assertEqual(got["values"]["limiter"]["value"], 8000)


class TestOtherCars(FactsCase):
    def test_a_stock_car_has_the_found_keys_and_the_game_start_only(self):
        self.assertEqual(self.facts("Bravo Stock", START), {"matched": True, "modded": False, "stock_car": "ks_bravo", "game_process_start": START})
        self.assertEqual(self.facts("ks_alpha"), {"matched": True, "modded": False, "stock_car": "ks_alpha", "game_process_start": None})
        self.assertEqual(self.row_calls, [])

    def test_an_unmatched_car_has_the_reason_and_the_game_start_only(self):
        self.assertEqual(self.facts("Unknown Car", START),
                         {"matched": False, "reason": "car not found in the tuner work folder", "game_process_start": START})
        self.assertEqual(self.facts("")["matched"], False)
        self.assertEqual(self.row_calls, [])

    def test_every_result_is_json_text(self):
        for name in ("ax_alpha", "ax_alp01", "ks_bravo", "nothing"):
            for start in (None, START):
                with self.subTest(name=name, start=start):
                    text = json.dumps(self.facts(name, start), allow_nan=False)
                    self.assertEqual(json.loads(text), self.facts(name, start))

    def test_nothing_raises_for_a_missing_work_folder_or_mods_folder(self):
        got = logfacts.tuner_facts(str(self.d / "nowhere"), str(self.d / "no_mods"), "ax_alpha", START)
        self.assertEqual(got, {"matched": False, "reason": "car not found in the tuner work folder", "game_process_start": START})

    def test_a_car_name_that_is_not_text_is_an_error_entry(self):
        got = logfacts.tuner_facts(self.work, self.mods, None, START)
        self.assertEqual((got["matched"], got["game_process_start"], list(got["error"]) != []), (False, START, True))
        json.dumps(got)


class TestRealRows(Sandbox):
    """tune.effective_rows itself, on a stubbed car."""

    def setUp(self):
        super().setUp()
        self.work, self.mods = str(self.d / "work"), str(self.d / "mods")
        for name, value in (("load_cars", lambda path=None: {"default": "ks_alpha", "cars": [{"id": "ks_alpha", "label": "Alpha"}]}),
                            ("load_catalogue", lambda path=None: mini_catalogue(suffix(), limiter()))):
            p = mock.patch.object(tune, name, value)
            p.start()
            self.addCleanup(p.stop)
        fc = FakeCar(self.work, "ks_alpha").install(self)
        fc.add("data/x.car", {"engine_path": fc.game_path("data/engine.carengine")})
        fc.add("data/engine.carengine", {"limiter": 7000.0})
        tune.save_json(tune.stock_info_path(self.work, "ks_alpha"), {"car_id": "ks_alpha", "display_name": "Alpha Stock", "brand": "B", "year": 1999})

    def test_the_values_and_defaults_of_the_default_tune_and_of_another_tune(self):
        tune.save_state(self.work, "ks_alpha", {"limiter": 8000})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "Drift", "limiter": 9000}, "ax_alp01")
        default = logfacts.tuner_facts(self.work, self.mods, "Alpha Stock MY")
        other = logfacts.tuner_facts(self.work, self.mods, "ax_alp01")
        self.assertEqual(default["values"], {"name_suffix": {"value": "MY", "default": "MY"}, "limiter": {"value": 8000, "default": 7000.0}})
        self.assertEqual(other["values"], {"name_suffix": {"value": "Drift", "default": "MY"}, "limiter": {"value": 9000, "default": 7000.0}})
        json.dumps([default, other], allow_nan=False)


class FakeKernel:
    """A scripted kernel32: the processes (pid, exe name) a snapshot walks through, the creation time of every process and the handles."""

    INVALID = ctypes.c_void_p(-1).value

    def __init__(self, processes, created_ticks=0, snapshot=1000, open_ok=True, times_ok=True):
        self.processes, self.created_ticks, self.snapshot = processes, created_ticks, snapshot
        self.open_ok, self.times_ok = open_ok, times_ok
        self.position = 0
        self.closed, self.opened = [], []
        self.CreateToolhelp32Snapshot = mock.Mock(side_effect=lambda flags, pid: self.snapshot)
        self.Process32FirstW = mock.Mock(side_effect=self.first)
        self.Process32NextW = mock.Mock(side_effect=self.next)
        self.OpenProcess = mock.Mock(side_effect=self.open)
        self.GetProcessTimes = mock.Mock(side_effect=self.times)
        self.CloseHandle = mock.Mock(side_effect=lambda handle: self.closed.append(handle))

    def fill(self, ref):
        entry = ref._obj
        pid, name = self.processes[self.position]
        entry.th32ProcessID, entry.szExeFile = pid, name

    def first(self, snap, ref):
        self.position = 0
        if not self.processes:
            return 0
        self.fill(ref)
        return 1

    def next(self, snap, ref):
        self.position += 1
        if self.position >= len(self.processes):
            return 0
        self.fill(ref)
        return 1

    def open(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        return 77 if self.open_ok else 0

    def times(self, handle, created, ended, kernel, user):
        if not self.times_ok:
            return 0
        created._obj.dwLowDateTime = self.created_ticks & 0xFFFFFFFF
        created._obj.dwHighDateTime = self.created_ticks >> 32
        return 1


def ticks_of(year, month, day, hour, minute, second):
    """The FILETIME of a UTC moment: 100 ns since 1601-01-01."""
    return (calendar.timegm((year, month, day, hour, minute, second)) + 11644473600) * 10000000


class TestGameProcessStart(unittest.TestCase):
    def fake(self, **kw):
        kernel = FakeKernel(kw.pop("processes", [(4, "System"), (812, "explorer.exe"), (5120, "AssettoCorsaEVO.exe"), (6000, "other.exe")]), **kw)
        for patcher in (mock.patch.object(logfacts, "_kernel32", kernel, create=True), mock.patch.object(logfacts.sys, "platform", "win32")):
            patcher.start()
            self.addCleanup(patcher.stop)
        return kernel

    def test_the_creation_time_of_the_found_process_as_iso_text_with_the_local_offset(self):
        kernel = self.fake(created_ticks=ticks_of(2026, 11, 16, 17, 30, 12))
        got = logfacts.game_process_start()
        want = datetime.datetime.fromtimestamp(calendar.timegm((2026, 11, 16, 17, 30, 12))).astimezone().isoformat(timespec="seconds")
        self.assertEqual(got, want)
        self.assertRegex(got, ISO_OFFSET)
        self.assertEqual(kernel.opened, [(0x1000, 0, 5120)])

    def test_the_exe_name_is_compared_ignoring_case_and_the_names_are_a_parameter(self):
        kernel = self.fake(processes=[(1, "assettocorsaevo.EXE")], created_ticks=ticks_of(2026, 1, 2, 3, 4, 5))
        self.assertRegex(logfacts.game_process_start(), ISO_OFFSET)
        self.assertEqual(kernel.opened[-1][2], 1)
        kernel = self.fake(processes=[(1, "a.exe"), (2, "Game2.EXE")], created_ticks=ticks_of(2026, 1, 2, 3, 4, 5))
        self.assertRegex(logfacts.game_process_start(("game1.exe", "game2.exe")), ISO_OFFSET)
        self.assertEqual(kernel.opened[-1][2], 2)

    def test_the_first_process_of_that_name_is_taken(self):
        kernel = self.fake(processes=[(10, "AssettoCorsaEVO.exe"), (20, "AssettoCorsaEVO.exe")], created_ticks=ticks_of(2026, 1, 2, 3, 4, 5))
        logfacts.game_process_start()
        self.assertEqual(kernel.opened, [(0x1000, 0, 10)])

    def test_no_such_process_is_none_and_nothing_is_opened(self):
        kernel = self.fake(processes=[(4, "System"), (812, "explorer.exe")])
        self.assertIsNone(logfacts.game_process_start())
        self.assertIsNone(logfacts.game_process_start(("no_such_game_xyz.exe",)))
        self.assertEqual(kernel.opened, [])

    def test_an_empty_process_list_is_none(self):
        self.fake(processes=[])
        self.assertIsNone(logfacts.game_process_start())

    def test_the_handles_are_closed_on_every_path(self):
        kernel = self.fake(created_ticks=ticks_of(2026, 1, 2, 3, 4, 5))
        logfacts.game_process_start()
        self.assertEqual(kernel.closed, [1000, 77])
        kernel = self.fake(processes=[(4, "System")])
        logfacts.game_process_start()
        self.assertEqual(kernel.closed, [1000])
        kernel = self.fake(times_ok=False)
        self.assertIsNone(logfacts.game_process_start())
        self.assertEqual(kernel.closed, [1000, 77])

    def test_an_invalid_snapshot_handle_is_none_and_not_closed(self):
        for handle in (FakeKernel.INVALID, None):
            with self.subTest(handle=handle):
                kernel = self.fake(snapshot=handle)
                self.assertIsNone(logfacts.game_process_start())
                self.assertEqual((kernel.closed, kernel.opened, kernel.Process32FirstW.called), ([], [], False))

    def test_a_process_that_cannot_be_opened_is_none(self):
        kernel = self.fake(open_ok=False)
        self.assertIsNone(logfacts.game_process_start())
        self.assertEqual(kernel.closed, [1000])

    def test_a_failure_of_the_win32_layer_is_none(self):
        kernel = self.fake()
        kernel.CreateToolhelp32Snapshot.side_effect = OSError("kernel32 gone")
        self.assertIsNone(logfacts.game_process_start())
        kernel = self.fake()
        kernel.Process32FirstW.side_effect = RuntimeError("boom")
        self.assertIsNone(logfacts.game_process_start())

    def test_a_failure_of_the_lookups_is_none(self):
        self.fake()
        with mock.patch.object(logfacts, "process_id", side_effect=OSError("denied")):
            self.assertIsNone(logfacts.game_process_start())
        with mock.patch.object(logfacts, "process_id", return_value=5), mock.patch.object(logfacts, "process_created", side_effect=ValueError("bad time")):
            self.assertIsNone(logfacts.game_process_start())

    def test_elsewhere_than_windows_it_is_none_and_the_win32_layer_is_not_used(self):
        with mock.patch.object(logfacts.sys, "platform", "linux"), mock.patch.object(logfacts, "_kernel32", create=True) as kernel:
            self.assertIsNone(logfacts.game_process_start())
        self.assertEqual(kernel.mock_calls, [])

    def test_the_default_name_is_the_game_exe_of_the_tuner(self):
        self.assertEqual(logfacts.game_process_start.__defaults__, ((tune.GAME_EXE,),))
        self.assertEqual(tune.GAME_EXE, "AssettoCorsaEVO.exe")

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8 and ctypes.sizeof(ctypes.c_wchar) == 2, "the 64-bit Windows layout (wchar_t is 4 bytes elsewhere)")
    def test_the_process_entry_has_the_size_of_the_win32_structure(self):
        self.assertEqual(ctypes.sizeof(logfacts.ProcessEntry), 568)
        self.assertEqual(logfacts.ProcessEntry.szExeFile.offset, 44)
        self.assertEqual(logfacts.ProcessEntry.th32DefaultHeapID.offset, 16)

    @unittest.skipUnless(sys.platform == "win32", "the real Win32 layer")
    def test_on_windows_an_impossible_name_is_none_and_the_game_name_is_none_or_a_time(self):
        self.assertIsNone(logfacts.game_process_start(("no_such_game_xyz.exe",)))
        got = logfacts.game_process_start()
        self.assertTrue(got is None or ISO_OFFSET.match(got), got)


class TestMakeFacts(FactsCase):
    def test_it_calls_the_start_function_and_passes_the_car(self):
        starts = []

        def start():
            starts.append(1)
            return START

        facts = logfacts.make_facts(self.work, self.mods, start)
        got = facts("Bravo Stock")
        self.assertEqual(got, {"matched": True, "modded": False, "stock_car": "ks_bravo", "game_process_start": START})
        self.assertEqual(starts, [1])
        facts("ax_alpha")
        self.assertEqual(starts, [1, 1])

    def test_it_hands_the_folders_the_car_and_the_start_to_tuner_facts(self):
        with mock.patch.object(logfacts, "tuner_facts", return_value={"matched": False}) as call:
            facts = logfacts.make_facts("W", "M", lambda: START)
            self.assertEqual(facts("Some Car"), {"matched": False})
        call.assert_called_once_with("W", "M", "Some Car", START)

    def test_the_default_start_is_the_game_process_start(self):
        self.assertIs(logfacts.make_facts.__defaults__[0], logfacts.game_process_start)

    def test_the_result_has_the_shape_of_a_logger_facts_function(self):
        facts = logfacts.make_facts(self.work, self.mods, lambda: None)
        self.assertEqual(list(facts("ax_alpha")), MODDED_KEYS)


if __name__ == "__main__":
    unittest.main()
