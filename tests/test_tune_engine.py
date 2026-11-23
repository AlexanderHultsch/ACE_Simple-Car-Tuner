"""Tests for the engine of tools/tune.py without the game: path parser, field access, coerce, state files, resolving defaults on a stubbed car, apply orchestration, car list, work folder, CLI.

Everything that decodes car files is stubbed (support.FakeCar replaces tune.load_msg / save_msg with in-memory messages, clone_car.build and kspkg.cmd_pack are stubbed for apply); the committed tuner/*.json are read only where a test says so.
"""
import builtins
import contextlib
import io
import json
import os
import shutil
import sys
import threading
import unittest
from unittest import mock

from support import FakeCar, Sandbox, mini_catalogue, mini_setting, run_main, run_tool, tmp, usage_cases

import car_json
import clone_car
import kspkg
import tune

REAL_LOAD_CATALOGUE = tune.load_catalogue
REAL_RENAME = os.rename
CAR_NOTE = "note: car file: data/x.car renamed to data/CarData.car (the paint shop of a mod car expects that name)"
USAGE = tune.__doc__.split("\n\n")[1]
GAME_SHARED = "content\\cars\\common_phsx\\"
NO_CHANGES = {"since": None, "settings": [], "extras": [], "total": 0}
GAME_MISSING = ("game package not found: %s (is Assetto Corsa EVO installed? if it is in another Steam library, "
                "pass --game <path of content.kspkg>; start_tuner.bat has a GAME line for it)")


def limiter(**kw):
    return mini_setting("limiter", type="int", min=3000, max=12000, targets=[("@engine", "limiter"), ("@car", "engine.limiter", True)], **kw)


def suffix():
    return mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix")


def variant():
    return mini_setting("variant_name", kind="meta", type="string", default_template="{stock_variant_name}", handler="variant_name")


def metas():
    return [suffix(), variant()]


def not_chained(test, exc):
    test.assertTrue(exc.__context__ is None or exc.__suppress_context__, "implicit exception chain: %r" % (exc.__context__,))


def add_variant(fc, name="q_drift", note="Drift", parts=("engine", "setup", "geometry")):
    """A second mechanical preset of the stub car whose forced parts replace the engine (with a turbo of its own), the setup and the suspension geometry."""
    gp = fc.game_path
    tunings = {"engine": {"engine": {"path": gp("data/DRIFT.carengine")}}, "setup": {"setup": {"path": gp("data/drift.carsetup")}},
               "geometry": {"suspensions_geometry": {"geometry_path_front": gp("data/f.suspension"), "geometry_path_rear": gp("data/r.suspension")}},
               "wing": {"wing": {"path": gp("data/w.wing")}}}
    fc.add("presets/%s.mechanicalcarpreset" % name, {"note": note, "description": "Name Preset " + name,
                                                    "car_specs": {"items": [{"key": "KEY_POWER", "value": 600.0}]},
                                                    "forced_compatible_part_paths": [gp("presets/parts/%s_%s.compatiblepart" % (name, p)) for p in parts]})
    for part in parts:
        fc.add("presets/parts/%s_%s.compatiblepart" % (name, part), {"car_part_path": gp("presets/parts/%s_%s.carpart" % (name, part))})
        fc.add("presets/parts/%s_%s.carpart" % (name, part), {"logic_parts": [{"tuning_part_path": gp("data/parts/%s_%s.tuningpart" % (name, part))}]})
        fc.add("data/parts/%s_%s.tuningpart" % (name, part), tunings[part])
    fc.add("data/drift.carengine", {"limiter": 8000.0, "minimum": 800, "turbos_to_load": [gp("data/drift.turbo")]})
    fc.add("data/drift.turbo", {"max_boost": 1.8})
    fc.add("data/drift.carsetup", {"alignments": [{"camber": -3.0, "pressure": 28.0}]})


class Base(Sandbox):
    def setUp(self):
        super().setUp()
        self.work = str(self.d / "work")

    def cars(self, *tested, default=None):
        tested = tested or (("ks_x", "Car X"),)
        data = {"default": default or tested[0][0], "cars": [{"id": i, "label": label} for i, label in tested]}
        self.patch(tune, "load_cars", lambda path=None: data)
        return data

    def run_main(self, *argv):
        return run_main(tune.main, ["tune.py", *argv])


class CarCase(Base):
    """A stubbed extracted car ks_x with engine, setup, curve and preset; self.car / self.engine / self.setup are the live stub objects."""

    def setUp(self):
        super().setUp()
        self.fc = FakeCar(self.work).install(self)
        gp = self.fc.game_path
        self.car = {"engine_path": gp("data/engine.carengine"), "stock_setup": gp("data/setup.carsetup"),
                    "engine": {"limiter": 7000.0, "minimum": 900}, "frontTyreCompounds": [GAME_SHARED + "tyres\\road\\a.tyre"],
                    "rearTyreCompounds": [GAME_SHARED + "tyres\\road\\b.tyre"],
                    "performance_modes": [{"electronics_settings": {"tc1": 3, "esc": 2}}, {"electronics_settings": {"tc1": 2, "tc2": 1}}]}
        self.engine = {"limiter": 7000.0, "minimum": 800, "powerCurve": gp("data/power.curve"), "turbos_to_load": []}
        self.setup = {"alignments": [{"camber": -1.5, "pressure": 30.0}, {"camber": -1.25, "pressure": 30.0}],
                      "electronics": {"tc1": 2}}
        self.fc.add("data/x.car", self.car)
        self.fc.add("data/engine.carengine", self.engine)
        self.fc.add("data/setup.carsetup", self.setup)
        self.fc.add("data/power.curve", {"points": [{"value": 1.0}, {"value": 3.0}, {"x": 5}]})
        self.fc.add("presets/p.mechanicalcarpreset", {"brand": "Brand", "description": "Name Preset Base",
                                                      "car_specs": {"items": [{"key": "KEY_POWER", "value": 380.0}, {"key": 7, "value": 9}]}})
        self.fc.add_shared("tyres/road/a.tyre", {"modelData": {"Dy0": 1.2}, "thermalData": {"thermalPerformanceCurve": GAME_SHARED + "tyres\\road\\tcurve_road.curve"}})
        self.fc.add_shared("tyres/road/b.tyre", {"modelData": {"Dy0": 1.1}})

    def stock_info(self, **kw):
        info = {"car_id": "ks_x", "display_name": "Car X", "brand": "Brand", "year": 1999, "property_1": "P1", "property_2": "P2",
                "property_3": "P3", "variant_name": "Base"}
        info.update(kw)
        return self.write(tune.stock_info_path(self.work, "ks_x"), info)

    def rows(self, *settings, **kw):
        return {r["id"]: r for r in tune.resolve_defaults(self.work, "ks_x", mini_catalogue(*settings), hidden=kw.pop("hidden", True), **kw)}

    def row(self, setting, **kw):
        return self.rows(setting, **kw)[setting["id"]]


# --------------------------------------------------------------------------------------------- path parser and field access
class TestPathParser(unittest.TestCase):
    def test_plain_dotted_path(self):
        self.assertEqual(tune.parse_path("a.b_1.C"), [("key", "a"), ("key", "b_1"), ("key", "C")])

    def test_index_selector_find_selector_and_wildcard(self):
        self.assertEqual(tune.parse_path("gears[1].ratio"), [("key", "gears"), ("idx", 1), ("key", "ratio")])
        self.assertEqual(tune.parse_path("m[*].x"), [("key", "m"), ("all",), ("key", "x")])
        self.assertEqual(tune.parse_path("items[key=KEY_POWER].value"), [("key", "items"), ("find", "key", "KEY_POWER"), ("key", "value")])

    def test_several_selectors_in_a_row(self):
        self.assertEqual(tune.parse_path("a[0][2]"), [("key", "a"), ("idx", 0), ("idx", 2)])

    def test_find_value_may_hold_dots_and_equal_signs(self):
        self.assertEqual(tune.parse_path("a[k=x.y=z].v"), [("key", "a"), ("find", "k", "x.y=z"), ("key", "v")])

    def test_selector_on_the_last_step(self):
        self.assertEqual(tune.parse_path("a[3]"), [("key", "a"), ("idx", 3)])

    def test_bad_paths_are_refused(self):
        for path in ("", "1a", "a..b", "a.", ".a", "a[", "a[x]", "a[]", "a b", "a-b", "a[0]b", "a[0"):
            with self.subTest(path):
                with self.assertRaises(ValueError):
                    tune.parse_path(path)

    def test_bad_selector_message_names_selector_and_path(self):
        with self.assertRaisesRegex(ValueError, r"bad selector \[x\] in field path 'a\[x\]'"):
            tune.parse_path("a[x]")


class TestFieldAccess(unittest.TestCase):
    def obj(self):
        return {"a": {"b": 1.5}, "xs": [{"k": 1, "v": "one"}, {"k": car_json_f32("2.5"), "v": "two"}, {"k": True, "v": "yes"}],
                "n": [[1, 2], [3]], "empty": []}

    def test_get_value_reads_nested_fields_indexes_and_selectors(self):
        o = self.obj()
        self.assertEqual(tune.get_value(o, "a.b"), (1.5, False))
        self.assertEqual(tune.get_value(o, "xs[1].v"), ("two", False))
        self.assertEqual(tune.get_value(o, "n[0][1]"), (2, False))
        self.assertEqual(tune.get_value(o, "xs[k=1].v"), ("one", False))

    def test_find_compares_the_text_of_numbers_floats_and_bools(self):
        o = self.obj()
        self.assertEqual(tune.get_value(o, "xs[k=2.5].v")[0], "two")
        self.assertEqual(tune.get_value(o, "xs[k=true].v")[0], "yes")

    def test_find_takes_the_first_match(self):
        o = {"xs": [{"k": 1, "v": "first"}, {"k": 1, "v": "second"}]}
        self.assertEqual(tune.get_value(o, "xs[k=1].v")[0], "first")

    def test_find_skips_elements_without_the_key_and_non_objects(self):
        o = {"xs": [5, {"other": 1}, {"k": 3, "v": "hit"}]}
        self.assertEqual(tune.get_value(o, "xs[k=3].v")[0], "hit")

    def test_find_without_a_match_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no list element with k=9"):
            tune.get_value(self.obj(), "xs[k=9].v")

    def test_missing_last_field_reads_absent(self):
        self.assertEqual(tune.get_value(self.obj(), "a.zzz"), (None, True))

    def test_missing_object_on_the_way_is_an_error_unless_missing_ok(self):
        with self.assertRaisesRegex(ValueError, "missing field 'q'"):
            tune.get_value(self.obj(), "q.r")
        self.assertEqual(tune.get_value(self.obj(), "q.r", missing_ok=True), (None, True))

    def test_index_out_of_range_and_not_a_list(self):
        with self.assertRaisesRegex(ValueError, "list has no element 5"):
            tune.get_value(self.obj(), "xs[5].v")
        with self.assertRaisesRegex(ValueError, "expected a list before"):
            tune.get_value(self.obj(), "a[0]")

    def test_field_inside_a_non_object_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "is not inside an object"):
            tune.get_value(self.obj(), "a.b.c")

    def test_wildcard_must_be_expanded_first(self):
        with self.assertRaisesRegex(ValueError, r"\[\*\] must be expanded"):
            tune.get_value(self.obj(), "xs[*].v")

    def test_expand_path_gives_one_path_per_element(self):
        self.assertEqual(tune.expand_path(self.obj(), "xs[*].v"), ["xs[0].v", "xs[1].v", "xs[2].v"])
        self.assertEqual(tune.expand_path(self.obj(), "n[*][*]"), ["n[0][0]", "n[0][1]", "n[1][0]"])
        self.assertEqual(tune.expand_path(self.obj(), "a.b"), ["a.b"])

    def test_expand_path_of_empty_or_absent_list_is_empty(self):
        self.assertEqual(tune.expand_path(self.obj(), "empty[*].v"), [])
        self.assertEqual(tune.expand_path(self.obj(), "nolist[*].v"), [])

    def test_expand_path_needs_a_list(self):
        with self.assertRaisesRegex(ValueError, "needs a list at a"):
            tune.expand_path(self.obj(), "a[*].b")

    def test_expand_path_missing_object_on_the_way(self):
        with self.assertRaisesRegex(ValueError, "missing field 'q'"):
            tune.expand_path(self.obj(), "q.xs[*].v")
        self.assertEqual(tune.expand_path(self.obj(), "q.xs[*].v", missing_ok=True), [])

    def test_put_value_replaces_an_existing_field_and_list_element(self):
        o = self.obj()
        tune.put_value(o, "a.b", 9)
        tune.put_value(o, "xs[1].v", "changed")
        tune.put_value(o, "n[0][1]", 20)
        self.assertEqual((o["a"]["b"], o["xs"][1]["v"], o["n"][0]), (9, "changed", [1, 20]))

    def test_put_value_adds_a_missing_last_field_and_keeps_the_key_order_list(self):
        o = {"a": {"_order": ["b"], "b": 1}}
        tune.put_value(o, "a.c", 2)
        self.assertEqual(o["a"]["_order"], ["b", "c"])
        self.assertEqual(o["a"]["c"], 2)

    def test_put_value_creates_missing_objects_on_the_way(self):
        o = {"_order": []}
        tune.put_value(o, "x.y.z", 3)
        self.assertEqual(o["x"]["y"]["z"], 3)
        self.assertEqual(o["_order"], ["x"])

    def test_put_value_does_not_create_list_elements(self):
        with self.assertRaisesRegex(ValueError, "list has no element 4"):
            tune.put_value({"xs": [1]}, "xs[4]", 1)

    def test_locate_returns_container_and_key(self):
        o = self.obj()
        container, key = tune.locate(o, "xs[0].v")
        self.assertIs(container, o["xs"][0])
        self.assertEqual(key, "v")
        container, key = tune.locate(o, "xs[2]")
        self.assertIs(container, o["xs"])
        self.assertEqual(key, 2)

    def test_locate_missing_object_on_the_way(self):
        self.assertEqual(tune.locate({}, "a.b", missing_ok=True), (None, None))
        with self.assertRaisesRegex(ValueError, "missing field 'a'"):
            tune.locate({}, "a.b")

    def test_text_of(self):
        self.assertEqual([tune.text_of(v) for v in (True, False, 3, "s", car_json_f32("1.5"))], ["true", "false", "3", "s", "1.5"])


def car_json_f32(text):
    return tune.to_f32(float(text))


# --------------------------------------------------------------------------------------------- values
class TestCoerce(unittest.TestCase):
    def test_bool_words_numbers_and_case(self):
        s = mini_setting("b", kind="flag", type="bool", value=0, targets=[("@car", "a")])
        for v in (True, "true", "TRUE", " Yes ", "1", 1, "on", "ON"):
            self.assertIs(tune.coerce(s, v), True, v)
        for v in (False, "false", "No", "0", 0, "off", " OFF "):
            self.assertIs(tune.coerce(s, v), False, v)

    def test_bool_refuses_everything_else(self):
        s = mini_setting("b", kind="flag", type="bool", value=0, targets=[("@car", "a")])
        for v in ("maybe", "", 2, 1.0, None, [], "tru"):
            with self.subTest(v):
                with self.assertRaisesRegex(ValueError, "b expects true or false"):
                    tune.coerce(s, v)

    def test_int_from_text_and_number(self):
        s = mini_setting("i", type="int")
        self.assertEqual([tune.coerce(s, v) for v in ("5", "+5", " -7 ", 5, "007")], [5, 5, -7, 5, 7])

    def test_int_with_too_many_digits_is_a_message_not_a_python_error(self):
        if not hasattr(sys, "set_int_max_str_digits"):
            self.skipTest("this Python has no limit on integer text")
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(4300)
        s = mini_setting("i", type="int")
        with self.assertRaises(ValueError) as cm:
            tune.coerce(s, "1" * 5000)
        self.assertEqual(str(cm.exception), "i expects an integer, got '%s'" % ("1" * 40))
        with self.assertRaises(ValueError) as cm:
            tune.coerce(s, "x" * 5000)
        self.assertEqual(str(cm.exception), "i expects an integer, got '%s'" % ("x" * 40))

    def test_int_refuses_floats_and_junk(self):
        s = mini_setting("i", type="int")
        for v in ("5.0", 5.0, "1e3", "0x10", "", "abc", None, True, "5 5"):
            with self.subTest(v):
                with self.assertRaisesRegex(ValueError, "i expects an integer"):
                    tune.coerce(s, v)

    def test_float_from_text_and_number(self):
        s = mini_setting("f")
        self.assertEqual([tune.coerce(s, v) for v in ("1.5", " 2 ", 3, 4.25, "-1e2")], [1.5, 2.0, 3.0, 4.25, -100.0])
        self.assertIs(type(tune.coerce(s, 3)), float)

    def test_float_refuses_junk_and_non_finite(self):
        s = mini_setting("f")
        for v in ("abc", "", None, True, [1], "nan", "inf", "-inf", float("nan"), "1e999"):
            with self.subTest(v):
                with self.assertRaises(ValueError) as cm:
                    tune.coerce(s, v)
                self.assertIn("f expects", str(cm.exception))

    def test_float_refuses_values_the_game_cannot_store_as_float32(self):
        s = mini_setting("f")
        for v in ("1e39", "-1e39", 1e39, "3.5e38"):
            with self.subTest(v):
                with self.assertRaisesRegex(ValueError, "f is out of the float range the game stores"):
                    tune.coerce(s, v)
        for v in ("nan", "inf", "-inf", float("nan"), 10**400):
            with self.subTest(v):
                with self.assertRaisesRegex(ValueError, "f expects"):
                    tune.coerce(s, v)
        self.assertEqual([tune.coerce(s, v) for v in ("3.4e38", "-3.4e38")], [3.4e38, -3.4e38])

    def test_string_needs_text_without_control_characters(self):
        s = mini_setting("t", type="string")
        self.assertEqual(tune.coerce(s, " a b "), " a b ")
        for v in ("", "a\nb", "a\x00", "a\x7fb", 5, None):
            with self.subTest(v):
                with self.assertRaisesRegex(ValueError, "t expects non-empty text"):
                    tune.coerce(s, v)

    def test_enum_must_be_one_of_the_choices(self):
        s = mini_setting("e", type="enum", choices=["a", "b"])
        self.assertEqual(tune.coerce(s, "b"), "b")
        with self.assertRaisesRegex(ValueError, "e must be one of: a, b"):
            tune.coerce(s, "c")

    def test_enum_choice_check_is_case_sensitive(self):
        with self.assertRaises(ValueError):
            tune.coerce(mini_setting("e", type="enum", choices=["a"]), "A")

    def test_name_suffix_is_trimmed_and_one_to_thirty_characters(self):
        s = suffix()
        self.assertEqual(tune.coerce(s, " _X "), "_X")
        self.assertEqual(tune.coerce(s, "\t _X\n"), "_X")
        self.assertEqual(tune.coerce(s, "x" * tune.NAME_SUFFIX_MAX), "x" * 30)
        self.assertEqual(tune.coerce(s, "  " + "x" * 30 + "  "), "x" * 30)
        self.assertEqual(tune.coerce(s, "x"), "x")
        for v in ("", "   ", "x" * 31, " " + "x" * 31, "a\tb", "a\nb", "\x1f", "a\x00", "a\x7fb", 3, None):
            with self.subTest(repr(v)):
                with self.assertRaisesRegex(ValueError, "name_suffix expects 1 to 30 characters"):
                    tune.coerce(s, v)

    def test_name_suffix_keeps_single_inner_spaces_and_collapses_runs_of_them(self):
        s = suffix()
        self.assertEqual(tune.coerce(s, "MY 2"), "MY 2")
        self.assertEqual(tune.coerce(s, "Super   charged"), "Super charged")
        self.assertEqual(tune.coerce(s, " a  b   c "), "a b c")
        self.assertEqual(tune.coerce(s, "x" * 20 + " " * 15 + "y" * 9), "x" * 20 + " " + "y" * 9)

    def test_car_name_is_the_stock_name_a_space_and_the_suffix(self):
        self.assertEqual(tune.car_name("BMW M3 E46 CSL", "MY"), "BMW M3 E46 CSL MY")
        self.assertEqual(tune.car_name("BMW M3 E46 CSL", "Supercharged"), "BMW M3 E46 CSL Supercharged")
        self.assertEqual(tune.car_name("BMW M3 E46 CSL", "MY 2"), "BMW M3 E46 CSL MY 2")
        self.assertEqual(tune.car_name("Car X", "_Drift"), "Car X _Drift")

    def test_to_f32_rounds_to_single_precision_and_keeps_the_short_text(self):
        v = tune.to_f32(1.1)
        self.assertIsInstance(v, car_json.F32)
        self.assertEqual((v.text, tune.plain(v)), ("1.1", 1.1))
        self.assertEqual(tune.to_f32(16777217.0), 16777216.0)

    def test_to_f32_out_of_range(self):
        with self.assertRaisesRegex(ValueError, "float out of range"):
            tune.to_f32(1e300)

    def test_plain_unwraps_f32_only(self):
        self.assertIs(type(tune.plain(tune.to_f32(2.5))), float)
        self.assertEqual([tune.plain(v) for v in (3, "x", True, None)], [3, "x", True, None])

    def test_same_compares_floats_with_a_relative_tolerance(self):
        f, i = mini_setting("f"), mini_setting("i", type="int")
        self.assertTrue(tune.same(f, 1.0, 1.000001))
        self.assertTrue(tune.same(f, 1e6, 1e6 + 1))
        self.assertFalse(tune.same(f, 1.0, 1.001))
        self.assertTrue(tune.same(i, 3, 3))
        self.assertFalse(tune.same(i, 3, 4))
        self.assertFalse(tune.same(f, None, 1.0))
        self.assertTrue(tune.same(f, None, None))

    def test_fmt(self):
        self.assertEqual([tune.fmt(v) for v in (None, True, False, 3, 1.5, "t", 0.1)], ["-", "true", "false", "3", "1.5", "t", "0.1"])

    def test_zero(self):
        self.assertEqual([tune.zero(mini_setting("a", type=t)) for t in ("int", "float", "string")], [0, 0.0, ""])
        self.assertIs(tune.zero(mini_setting("a", kind="flag", type="bool", value=0, targets=[])), False)
        self.assertEqual(tune.zero(mini_setting("a", type="enum", choices=["x", "y"])), "x")
        self.assertEqual(tune.zero(mini_setting("a", type="enum")), "")

    def test_range_warning(self):
        s = mini_setting("lim", type="int", min=10, max=20)
        self.assertIsNone(tune.range_warning(s, 10))
        self.assertIsNone(tune.range_warning(s, 20))
        self.assertEqual(tune.range_warning(s, 9), "lim=9 is outside the suggested range 10..20")
        self.assertEqual(tune.range_warning(s, 21), "lim=21 is outside the suggested range 10..20")

    def test_range_warning_with_one_bound_or_none_and_for_other_types(self):
        self.assertIsNone(tune.range_warning(mini_setting("a"), 1e9))
        self.assertEqual(tune.range_warning(mini_setting("a", min=1.5), 1.0), "a=1.0 is outside the suggested range 1.5..-")
        self.assertIsNone(tune.range_warning(mini_setting("a", min=1.5), 99.0))
        self.assertIsNone(tune.range_warning(mini_setting("t", type="string", min=1), "x"))


class TestLegacySuffix(unittest.TestCase):
    def test_the_old_default_and_its_counted_forms_are_converted(self):
        for old, new in (("_MY", "MY"), ("_MY2", "MY 2"), ("_MY3", "MY 3"), ("_MY12", "MY 12"), ("_MY007", "MY 007")):
            with self.subTest(old):
                self.assertEqual(tune.legacy_suffix(old), new)

    def test_every_other_value_is_left_as_it_is(self):
        for v in ("MY", "MY 2", "MY2", "_Drift", "_MYX", "_MY2x", "_MY 2", "_my", "x_MY", " _MY", "_MY ", "_MY\n", "", None, 5, ["_MY"]):
            with self.subTest(repr(v)):
                self.assertEqual(tune.legacy_suffix(v), v)

    def test_saved_value_converts_the_name_suffix_only(self):
        s, other = suffix(), mini_setting("label", type="string")
        self.assertEqual(tune.saved_value(s, "_MY3"), "MY 3")
        self.assertEqual(tune.saved_value(s, "_Drift"), "_Drift")
        self.assertEqual(tune.saved_value(s, "  _Z  q "), "_Z q")
        self.assertEqual(tune.saved_value(other, "_MY"), "_MY")
        with self.assertRaisesRegex(ValueError, "name_suffix expects 1 to 30 characters"):
            tune.saved_value(s, "")


# --------------------------------------------------------------------------------------------- json files and state
class TestJsonFiles(Base):
    def test_save_json_layout(self):
        path = os.path.join(self.work, "sub", "f.json")
        tune.save_json(path, {"b": 1, "a": ["é", 2.5]})
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b'{\n  "b": 1,\n  "a": [\n    "\xc3\xa9",\n    2.5\n  ]\n}\n')

    def test_save_json_replaces_the_old_content(self):
        path = os.path.join(self.work, "f.json")
        tune.save_json(path, {"a": 1})
        tune.save_json(path, {"b": 2})
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"b": 2})

    def test_save_json_keeps_the_old_file_when_serialising_fails(self):
        path = os.path.join(self.work, "f.json")
        tune.save_json(path, {"a": 1})
        with self.assertRaises(Exception):
            tune.save_json(path, {"a": object()})
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_load_state_missing_file_is_empty(self):
        self.assertEqual(tune.load_state(self.work, "ks_x"), {})

    def test_save_and_load_state_round_trip(self):
        tune.save_state(self.work, "ks_x", {"a": 1, "b": "x", "c": True, "d": 1.5})
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"a": 1, "b": "x", "c": True, "d": 1.5})
        self.assertTrue(os.path.isfile(os.path.join(self.work, "ks_x", "tune_state.json")))

    def test_states_are_per_car(self):
        tune.save_state(self.work, "ks_x", {"a": 1})
        self.assertEqual(tune.load_state(self.work, "ks_y"), {})

    def test_state_must_be_an_object_and_the_error_names_the_file(self):
        path = self.write(tune.state_path(self.work, "ks_x"), "[1]")
        with self.assertRaises(ValueError) as cm:
            tune.load_state(self.work, "ks_x")
        self.assertIn(path, str(cm.exception))
        self.assertIn("expected an object", str(cm.exception))

    LOADERS = {"state": ("ks_x/tune_state.json", lambda w: tune.load_state(w, "ks_x")),
               "stock_info": ("ks_x/stock_info.json", lambda w: tune.load_stock_info(w, "ks_x")),
               "cars": ("cars.json", lambda w: tune.load_cars(os.path.join(w, "cars.json"))),
               "catalogue": ("catalogue.json", lambda w: tune.load_catalogue(os.path.join(w, "catalogue.json")))}

    def broken(self, name, text, encoding="utf-8"):
        rel, load = self.LOADERS[name]
        path = os.path.join(self.work, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding=encoding) as f:
            f.write(text)
        return path, lambda: load(self.work)

    def check_syntax_error_names_the_file(self, name):
        path, load = self.broken(name, '{"a": 1,')
        with self.assertRaises(ValueError) as cm:
            load()
        self.assertIn(os.path.basename(path), str(cm.exception))

    def check_bom_is_tolerated(self, name, good):
        path, load = self.broken(name, json.dumps(good), encoding="utf-8-sig")
        load()

    def test_state_syntax_error_names_the_file(self):
        self.check_syntax_error_names_the_file("state")

    def test_cars_syntax_error_names_the_file(self):
        self.check_syntax_error_names_the_file("cars")

    def test_catalogue_syntax_error_names_the_file(self):
        self.check_syntax_error_names_the_file("catalogue")

    def test_stock_info_syntax_error_names_the_file(self):
        self.check_syntax_error_names_the_file("stock_info")

    def test_state_with_a_bom_loads(self):
        self.check_bom_is_tolerated("state", {"a": 1})

    def test_cars_with_a_bom_loads(self):
        self.check_bom_is_tolerated("cars", {"default": "ks_x", "cars": [{"id": "ks_x", "label": "X"}]})

    def test_catalogue_with_a_bom_loads(self):
        self.check_bom_is_tolerated("catalogue", mini_catalogue(mini_setting("a", targets=[("@car", "a")])))

    def test_stock_info_with_a_bom_loads(self):
        self.check_bom_is_tolerated("stock_info", {"car_id": "ks_x", "display_name": "X", "brand": "B", "year": 2000})


class TestStateFlow(CarCase):
    def cat(self, *settings):
        cat = mini_catalogue(*(settings or (limiter(), suffix())))
        self.patch(tune, "load_catalogue", lambda path=None: cat)
        return cat

    def test_set_stores_the_coerced_value_and_returns_it(self):
        self.cat()
        self.assertEqual(tune.set_value(self.work, "ks_x", "limiter", "8000"), {"id": "limiter", "value": 8000, "warnings": []})
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000})

    def test_set_keeps_other_entries_and_overwrites_the_same_id(self):
        self.cat()
        tune.save_state(self.work, "ks_x", {"name_suffix": "_A", "limiter": 1})
        tune.set_value(self.work, "ks_x", "limiter", "9000")
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"name_suffix": "_A", "limiter": 9000})

    def test_set_outside_the_range_warns_but_stores(self):
        self.cat()
        res = tune.set_value(self.work, "ks_x", "limiter", "20000")
        self.assertEqual(res["warnings"], ["limiter=20000 is outside the suggested range 3000..12000"])
        self.assertEqual(tune.load_state(self.work, "ks_x")["limiter"], 20000)

    def test_set_with_a_bad_value_changes_nothing(self):
        self.cat()
        tune.save_state(self.work, "ks_x", {"limiter": 7500})
        with self.assertRaisesRegex(ValueError, "limiter expects an integer"):
            tune.set_value(self.work, "ks_x", "limiter", "fast")
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 7500})

    def test_set_unknown_setting(self):
        self.cat()
        with self.assertRaisesRegex(ValueError, "unknown setting 'nope'"):
            tune.set_value(self.work, "ks_x", "nope", "1")
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_set_refuses_a_setting_that_is_not_applicable_with_the_reason(self):
        self.cat(mini_setting("deep", targets=[("@engine", "gone.deeper")]))
        with self.assertRaisesRegex(ValueError, "deep is not applicable to ks_x: @engine gone.deeper: missing field 'gone'"):
            tune.set_value(self.work, "ks_x", "deep", "1")
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_set_name_suffix_and_flag(self):
        flag = mini_setting("aids", kind="flag", type="bool", value=0, targets=[("@car", "performance_modes[*].electronics_settings.tc1", True)])
        self.cat(suffix(), flag)
        tune.set_value(self.work, "ks_x", "name_suffix", "_TUNED")
        tune.set_value(self.work, "ks_x", "aids", "yes")
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"name_suffix": "_TUNED", "aids": True})

    def test_unset_removes_and_reports(self):
        self.cat()
        tune.save_state(self.work, "ks_x", {"limiter": 8000, "name_suffix": "_A"})
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter"), {"id": "limiter", "removed": True})
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"name_suffix": "_A"})

    def test_unset_of_a_known_setting_that_is_not_set_leaves_the_file_alone(self):
        self.cat()
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter"), {"id": "limiter", "removed": False})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_unset_unknown_setting_that_is_not_in_the_state(self):
        self.cat()
        with self.assertRaisesRegex(ValueError, "unknown setting 'nope'"):
            tune.unset_value(self.work, "ks_x", "nope")

    def test_unset_removes_a_stale_id_from_the_state(self):
        self.cat()
        tune.save_state(self.work, "ks_x", {"stale_id": 1, "limiter": 8000})
        self.assertEqual(tune.unset_value(self.work, "ks_x", "stale_id"), {"id": "stale_id", "removed": True})
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000})

    def test_set_then_unset_leaves_an_empty_state(self):
        self.cat()
        tune.set_value(self.work, "ks_x", "limiter", "8000")
        tune.unset_value(self.work, "ks_x", "limiter")
        self.assertEqual(tune.load_state(self.work, "ks_x"), {})

    def test_effective_rows_use_state_value_and_mark_changes(self):
        cat = self.cat()
        tune.save_state(self.work, "ks_x", {"limiter": 8000, "name_suffix": "MY"})
        rows = {r["id"]: r for r in tune.effective_rows(self.work, "ks_x", cat)}
        self.assertEqual((rows["limiter"]["value"], rows["limiter"]["default"], rows["limiter"]["changed"]), (8000, 7000, True))
        self.assertEqual((rows["name_suffix"]["value"], rows["name_suffix"]["changed"]), ("MY", False))

    def test_effective_rows_read_a_legacy_name_suffix_converted_and_leave_the_file_alone(self):
        cat = self.cat()
        for saved, shown, changed in (("_MY", "MY", False), ("_MY2", "MY 2", True), ("_Drift", "_Drift", True), ("  My   Car ", "My Car", True)):
            with self.subTest(saved):
                tune.save_state(self.work, "ks_x", {"name_suffix": saved})
                row = {r["id"]: r for r in tune.effective_rows(self.work, "ks_x", cat)}["name_suffix"]
                self.assertEqual((row["value"], row["changed"]), (shown, changed))
                self.assertEqual(tune.load_state(self.work, "ks_x"), {"name_suffix": saved})

    def test_effective_rows_without_state_show_defaults_unchanged(self):
        rows = tune.effective_rows(self.work, "ks_x", self.cat())
        self.assertEqual([(r["value"], r["changed"]) for r in rows], [(7000, False), ("MY", False)])

    def test_effective_rows_a_state_value_equal_to_the_default_is_not_a_change(self):
        cat = self.cat(mini_setting("f", targets=[("@engine", "limiter")]))
        tune.save_state(self.work, "ks_x", {"f": 7000.000001})
        self.assertFalse(tune.effective_rows(self.work, "ks_x", cat)[0]["changed"])

    def test_effective_rows_reject_a_state_value_of_the_wrong_type(self):
        cat = self.cat()
        tune.save_state(self.work, "ks_x", {"limiter": "fast"})
        with self.assertRaisesRegex(ValueError, "limiter expects an integer"):
            tune.effective_rows(self.work, "ks_x", cat)

    def test_effective_rows_hidden_flag_keeps_non_applicable_rows(self):
        cat = self.cat(limiter(), mini_setting("deep", targets=[("@engine", "gone.deeper")]))
        self.assertEqual([r["id"] for r in tune.effective_rows(self.work, "ks_x", cat)], ["limiter"])
        self.assertEqual([r["id"] for r in tune.effective_rows(self.work, "ks_x", cat, hidden=True)], ["limiter", "deep"])

    def test_unknown_state_ids(self):
        cat = self.cat()
        tune.save_state(self.work, "ks_x", {"limiter": 1, "old_a": 2, "old_b": 3})
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", cat), ["old_a", "old_b"])

    def test_unknown_state_ids_are_kept_in_the_file_and_ignored_by_the_rows(self):
        cat = self.cat()
        tune.save_state(self.work, "ks_x", {"old_a": 2})
        self.assertEqual([r["id"] for r in tune.effective_rows(self.work, "ks_x", cat)], ["limiter", "name_suffix"])
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"old_a": 2})

    def test_warn_unknown_state_names_each_id(self):
        self.cat()
        tune.save_state(self.work, "ks_x", {"old_a": 2, "old_b": 3, "limiter": 1})
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x")
        self.assertEqual(err.getvalue().splitlines(), ["warning: ignoring unknown setting 'old_a' in the saved state",
                                                         "warning: ignoring unknown setting 'old_b' in the saved state"])

    def test_warn_unknown_state_is_silent_without_unknown_ids(self):
        self.cat()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x")
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_warn_unknown_state_writes_to_stderr(self):
        self.cat()
        tune.save_state(self.work, "ks_x", {"old_a": 2})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("old_a", err.getvalue())

    def test_show_keeps_warnings_off_stdout(self):
        self.cars()
        self.cat()
        tune.save_state(self.work, "ks_x", {"old_a": 2})
        code, out, err = self.run_main("show", "--work", self.work)
        self.assertNotIn("warning", out)
        self.assertIn("warning", err)


# --------------------------------------------------------------------------------------------- resolving defaults
class TestResolveDefaults(CarCase):
    def test_no_base_car_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no base car in .*, run init first"):
            tune.resolve_defaults(os.path.join(self.work, "other"), "ks_x", mini_catalogue(limiter()))

    def test_row_carries_the_catalogue_fields(self):
        s = limiter()
        row = self.row(s)
        for key in ("id", "group", "label", "kind", "type", "unit", "verified", "min", "max", "description"):
            self.assertEqual(row[key], s[key])

    def test_copies_that_agree_give_a_consistent_int_default(self):
        row = self.row(limiter())
        self.assertEqual((row["default"], type(row["default"]), row["consistent"], row["copies_differ"], row["applicable"], row["reason"]),
                         (7000, int, True, False, True, None))
        self.assertEqual([(t["file"], t["resolved"], t.get("optional"), t["rel"]) for t in row["targets"]],
                         [("@engine", True, None, "data/engine.carengine"), ("@car", True, True, "data/x.car")])

    def test_copies_that_differ_are_listed_and_the_first_required_value_is_the_default(self):
        row = self.row(mini_setting("m", type="int", targets=[("@engine", "minimum"), ("@car", "engine.minimum", True)]))
        self.assertEqual((row["default"], row["consistent"], row["copies_differ"], row["applicable"]), (800, False, True, True))
        self.assertEqual(row["copy_values"], [{"target": "@engine minimum", "value": 800}, {"target": "@car engine.minimum", "value": 900}])

    def test_float_copies_within_the_tolerance_agree(self):
        self.car["engine"]["limiter"] = 7000.000001
        row = self.row(mini_setting("f", targets=[("@engine", "limiter"), ("@car", "engine.limiter")]))
        self.assertTrue(row["consistent"])

    def test_f32_values_become_plain_floats(self):
        self.engine["limiter"] = tune.to_f32(1.1)
        row = self.row(mini_setting("f", targets=[("@engine", "limiter")]))
        self.assertEqual((type(row["default"]), row["default"]), (float, 1.1))

    def test_index_selector(self):
        row = self.row(mini_setting("c", targets=[("@setup", "alignments[1].camber")]))
        self.assertEqual(row["default"], -1.25)

    def test_find_selector_by_text_of_the_key(self):
        a = mini_setting("p", targets=[("@mech_preset", "car_specs.items[key=KEY_POWER].value")])
        b = mini_setting("q", targets=[("@mech_preset", "car_specs.items[key=7].value")])
        rows = self.rows(a, b)
        self.assertEqual((rows["p"]["default"], rows["q"]["default"]), (380.0, 9.0))

    def test_list_element_that_is_missing_makes_the_setting_hidden_with_the_reason(self):
        row = self.row(mini_setting("c", targets=[("@setup", "alignments[5].camber")]))
        self.assertEqual((row["applicable"], row["reason"]), (False, "@setup alignments[5].camber: list has no element 5"))

    def test_find_selector_without_a_match_hides_the_setting(self):
        row = self.row(mini_setting("p", targets=[("@mech_preset", "car_specs.items[key=NOPE].value")]))
        self.assertFalse(row["applicable"])
        self.assertIn("no list element with key=NOPE", row["reason"])

    def test_optional_target_that_does_not_resolve_does_not_block(self):
        row = self.row(mini_setting("o", targets=[("@engine", "limiter"), ("@car", "nothere.deeper", True)]))
        self.assertEqual((row["applicable"], row["resolved"], row["default"]), (True, True, 7000.0))
        self.assertEqual([t["resolved"] for t in row["targets"]], [True, False])

    def test_required_target_that_does_not_resolve_hides_the_setting(self):
        row = self.row(mini_setting("deep", targets=[("@engine", "limiter"), ("@car", "nothere.deeper")]))
        self.assertEqual((row["applicable"], row["reason"]), (False, "@car nothere.deeper: missing field 'nothere'"))

    def test_absent_last_field_counts_as_resolved_with_the_zero_default(self):
        row = self.row(mini_setting("z", targets=[("@engine", "nothere")]))
        self.assertEqual((row["applicable"], row["absent"], row["default"], row["targets"][0]["absent"]), (True, True, 0.0, True))

    def test_absent_int_and_enum_defaults(self):
        rows = self.rows(mini_setting("zi", type="int", targets=[("@engine", "nothere")]),
                         mini_setting("ze", type="enum", choices=["x", "y"], targets=[("@engine", "nothere")]))
        self.assertEqual((rows["zi"]["default"], rows["ze"]["default"]), (0, "x"))

    def test_hide_if_absent(self):
        rows = self.rows(mini_setting("h", targets=[("@engine", "nothere")], hide_if_absent=True),
                         mini_setting("k", targets=[("@engine", "limiter")], hide_if_absent=True),
                         mini_setting("mixed", targets=[("@engine", "limiter"), ("@car", "engine.nothere")], hide_if_absent=True),
                         mini_setting("optonly", targets=[("@engine", "nothere"), ("@car", "engine.limiter", True)], hide_if_absent=True))
        self.assertEqual({k: (v["applicable"], v["reason"]) for k, v in rows.items()},
                         {"h": (False, "field absent in the stock data"), "k": (True, None), "mixed": (True, None),
                          "optonly": (False, "field absent in the stock data")})

    def test_create_missing_makes_missing_objects_resolve_as_absent(self):
        plain = mini_setting("plain", targets=[("@car", "suspensions.arbFront.stiffness")])
        creating = mini_setting("creating", targets=[("@car", "suspensions.arbFront.stiffness")], create_missing=True)
        rows = self.rows(plain, creating)
        self.assertEqual((rows["plain"]["applicable"], rows["plain"]["reason"]),
                         (False, "@car suspensions.arbFront.stiffness: missing field 'suspensions'"))
        self.assertEqual((rows["creating"]["applicable"], rows["creating"]["absent"], rows["creating"]["default"]), (True, True, 0.0))

    def test_needs_must_resolve_but_are_not_compared(self):
        ok = mini_setting("ok", targets=[("@engine", "limiter")], needs=[{"file": "@car", "path": "engine.minimum"}])
        bad = mini_setting("bad", targets=[("@engine", "limiter")], needs=[{"file": "@setup", "path": "gone.deeper"}])
        rows = self.rows(ok, bad)
        self.assertEqual((rows["ok"]["applicable"], rows["ok"]["consistent"], rows["ok"]["copies_differ"]), (True, True, False))
        self.assertEqual((rows["bad"]["applicable"], rows["bad"]["reason"]), (False, "@setup gone.deeper: missing field 'gone'"))

    def test_wildcard_target_expands_to_every_list_element(self):
        row = self.row(mini_setting("w", type="int", targets=[("@car", "performance_modes[*].electronics_settings.tc1")]))
        self.assertEqual([t["path"] for t in row["targets"]], ["performance_modes[0].electronics_settings.tc1",
                                                                "performance_modes[1].electronics_settings.tc1"])
        self.assertEqual((row["consistent"], row["copies_differ"], row["default"]), (False, True, 3))

    def test_wildcard_copies_that_agree_are_consistent(self):
        self.car["performance_modes"][1]["electronics_settings"]["tc1"] = 3
        row = self.row(mini_setting("w", type="int", targets=[("@car", "performance_modes[*].electronics_settings.tc1")]))
        self.assertEqual((row["consistent"], row["default"]), (True, 3))

    def test_wildcard_over_an_empty_or_absent_list_hides_a_required_target(self):
        self.car["performance_modes"] = []
        row = self.row(mini_setting("w", targets=[("@car", "performance_modes[*].electronics_settings.tc1")]))
        self.assertEqual((row["applicable"], row["reason"]), (False, "@car performance_modes[*].electronics_settings.tc1: the list has no elements"))
        row = self.row(mini_setting("w", targets=[("@car", "nolist[*].x")]))
        self.assertFalse(row["applicable"])

    def test_wildcard_with_a_field_absent_in_some_elements(self):
        row = self.row(mini_setting("w", type="int", targets=[("@car", "performance_modes[*].electronics_settings.tc2")]))
        self.assertEqual([(t["path"], t["absent"]) for t in row["targets"]],
                         [("performance_modes[0].electronics_settings.tc2", True), ("performance_modes[1].electronics_settings.tc2", False)])
        self.assertEqual(row["default"], 0)

    def test_flag_has_default_false_and_ignores_the_target_values(self):
        flag = mini_setting("aids", kind="flag", type="bool", value=0,
                            targets=[("@car", "performance_modes[*].electronics_settings.tc1", True), ("@setup", "electronics.tc1", True),
                                     ("@setup", "electronics.nothere", True)])
        row = self.row(flag)
        self.assertEqual((row["default"], row["consistent"], row["absent"], row["applicable"]), (False, True, False, True))
        self.assertEqual(len(row["targets"]), 4)

    def test_flag_with_no_resolvable_optional_target_is_still_applicable(self):
        flag = mini_setting("aids", kind="flag", type="bool", value=0, targets=[("@car", "gone.x", True)])
        self.assertTrue(self.row(flag)["applicable"])

    def test_meta_has_no_targets_and_its_default(self):
        self.stock_info()
        rows = self.rows(*metas())
        self.assertEqual((rows["name_suffix"]["default"], rows["name_suffix"]["targets"], rows["name_suffix"]["applicable"]), ("MY", [], True))

    def test_variant_name_default_is_the_stock_variant_text(self):
        self.stock_info(variant_name="GT Base")
        self.assertEqual(self.row(variant())["default"], "GT Base")

    def test_variant_name_is_hidden_when_the_stock_car_has_no_variant(self):
        self.stock_info(variant_name="")
        row = self.row(variant())
        self.assertEqual((row["applicable"], row["reason"], row["default"]), (False, "the stock car has no variant name", "Car X"))

    def test_default_template_placeholders(self):
        self.stock_info(variant_name="Base")
        row = self.row(mini_setting("t", kind="meta", type="string", handler="name_suffix", default_template="{stock_display_name}/{stock_variant_name}"))
        self.assertEqual(row["default"], "Car X/Base")

    def test_stock_name_comes_from_the_mechanical_preset_without_stock_info(self):
        row = self.row(mini_setting("t", kind="meta", type="string", handler="name_suffix", default_template="{stock_display_name}"))
        self.assertEqual(row["default"], "Brand Name")

    def test_incomplete_stock_info_is_used_as_far_as_it_goes(self):
        self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_x", "display_name": "Car X", "brand": "B", "year": 2000})
        setting = mini_setting("t", kind="meta", type="string", handler="name_suffix", default_template="{stock_display_name}")
        self.assertEqual(self.rows(setting, game=os.path.join(self.work, "no_game.kspkg"))["t"]["default"], "Car X")

    def test_curve_scale_reads_the_curve_and_keeps_the_catalogue_default(self):
        curve = mini_setting("ps", kind="curve_scale", default=1.0, curve_from={"file": "@engine", "path": "powerCurve"}, targets=[])
        row = self.row(curve)
        self.assertEqual((row["applicable"], row["default"], row["targets"][0]["curve"]), (True, 1.0, self.fc.game_path("data/power.curve")))
        self.assertEqual(row["targets"][0]["info"], "3 points, peak 3.0")

    def test_curve_scale_without_a_curve_file_is_hidden(self):
        del self.engine["powerCurve"]
        row = self.row(mini_setting("ps", kind="curve_scale", default=1.0, curve_from={"file": "@engine", "path": "powerCurve"}, targets=[]))
        self.assertEqual((row["applicable"], row["reason"]), (False, "@engine powerCurve: powerCurve holds no curve file name"))

    def test_curve_scale_with_an_empty_curve_is_hidden(self):
        self.fc.add("data/power.curve", {"points": [{"x": 1}]})
        row = self.row(mini_setting("ps", kind="curve_scale", default=1.0, curve_from={"file": "@engine", "path": "powerCurve"}, targets=[]))
        self.assertFalse(row["applicable"])
        self.assertIn("has no points with a value", row["reason"])

    def thermal(self, **kw):
        return mini_setting("th", type="enum", choices=["road", "slick"], targets=[("@tyre_front", "thermalData.thermalPerformanceCurve")],
                            choice_values={"road": GAME_SHARED + "tyres\\road\\tcurve_road.curve",
                                           "slick": GAME_SHARED + "tyres\\slick\\tcurve_slick.curve"}, **kw)

    def test_choice_values_default_is_the_choice_whose_text_matches(self):
        self.assertEqual(self.row(self.thermal())["default"], "road")

    def test_choice_values_match_ignoring_case_and_slash_direction(self):
        self.fc.add_shared("tyres/road/a.tyre", {"thermalData": {"thermalPerformanceCurve": "CONTENT/CARS/COMMON_PHSX/TYRES/SLICK/TCURVE_SLICK.CURVE"}})
        self.assertEqual(self.row(self.thermal())["default"], "slick")

    def test_choice_values_text_that_is_no_choice_hides_the_setting(self):
        self.fc.add_shared("tyres/road/a.tyre", {"thermalData": {"thermalPerformanceCurve": GAME_SHARED + "tyres\\other.curve"}})
        row = self.row(self.thermal())
        self.assertFalse(row["applicable"])
        self.assertIn("is not one of the choices of th", row["reason"])

    def test_tyre_role_resolves_to_the_shared_file(self):
        row = self.row(mini_setting("dy", targets=[("@tyre_front", "modelData.Dy0")]))
        self.assertEqual((row["default"], row["targets"][0]["rel"]), (1.2, "../common_phsx/tyres/road/a.tyre"))

    def test_tyre_role_matches_the_game_path_case_insensitively(self):
        self.car["frontTyreCompounds"] = ["CONTENT\\CARS\\COMMON_PHSX\\TYRES\\ROAD\\A.TYRE"]
        self.assertEqual(self.row(mini_setting("dy", targets=[("@tyre_front", "modelData.Dy0")]))["default"], 1.2)

    def test_tyre_file_that_is_not_extracted_hides_the_setting(self):
        os.remove(os.path.join(self.fc.shared, "tyres", "road", "a.tyre"))
        row = self.row(mini_setting("dy", targets=[("@tyre_front", "modelData.Dy0")]), game=os.path.join(self.work, "no_game.kspkg"))
        self.assertFalse(row["applicable"])
        self.assertTrue(row["reason"].startswith("@tyre_front modelData.Dy0: " + tune.TYRE_UNAVAILABLE), row["reason"])

    def test_tyre_failure_shows_the_real_cause(self):
        self.fc.add("presets/bad.compatibletyres", ValueError("bad.compatibletyres: truncated protobuf"))
        os.remove(os.path.join(self.fc.shared, "tyres", "road", "a.tyre"))
        row = self.row(mini_setting("dy", targets=[("@tyre_front", "modelData.Dy0")]), game=os.path.join(self.work, "no_game.kspkg"))
        self.assertFalse(row["applicable"])
        self.assertIn("truncated protobuf", row["reason"])

    def test_role_files_are_decoded_once_per_resolve(self):
        loads = []
        orig = tune.load_msg
        self.patch(tune, "load_msg", lambda p: (loads.append(os.path.basename(p)), orig(p))[1])
        self.rows(limiter(), mini_setting("m", type="int", targets=[("@engine", "minimum"), ("@car", "engine.minimum")]))
        self.assertEqual(sorted(loads), ["engine.carengine", "x.car"])

    def test_mech_preset_is_the_first_in_sorted_order(self):
        self.fc.add("presets/a_first.MECHANICALCARPRESET", {"brand": "First", "description": "x"})
        row = self.row(mini_setting("b", type="string", targets=[("@mech_preset", "brand")]))
        self.assertEqual(row["default"], "First")

    def test_turbo_role_follows_turbos_to_load(self):
        self.engine["turbos_to_load"] = [self.fc.game_path("data/t0.turbo"), self.fc.game_path("data/t1.turbo")]
        self.fc.add("data/t0.turbo", {"max_boost": 0.8})
        self.fc.add("data/t1.turbo", {"max_boost": 1.2})
        rows = self.rows(mini_setting("t0", targets=[("@turbo[0]", "max_boost")]), mini_setting("t1", targets=[("@turbo[1]", "max_boost")]),
                         mini_setting("t2", targets=[("@turbo[2]", "max_boost")]))
        self.assertEqual((rows["t0"]["default"], rows["t1"]["default"]), (0.8, 1.2))
        self.assertEqual(rows["t2"]["reason"], "@turbo[2] max_boost: the engine file lists 2 turbo file(s), no turbos_to_load[2]")

    def test_manifest_path_is_found_whatever_its_case(self):
        self.car["engine_path"] = "CONTENT\\Cars\\KS_X\\DATA\\Engine.CarEngine"
        self.assertEqual(self.row(limiter())["default"], 7000)

    def test_manifest_role_without_a_path_in_the_car_file(self):
        del self.car["engine_path"]
        row = self.row(limiter())
        self.assertEqual((row["applicable"], row["reason"]), (False, "@engine limiter: no engine_path in the car file"))

    def test_manifest_path_to_a_file_that_is_not_there(self):
        self.car["engine_path"] = self.fc.game_path("data/missing.carengine")
        row = self.row(limiter())
        self.assertFalse(row["applicable"])
        self.assertIn("missing.carengine not found in", row["reason"])

    def test_several_car_files_the_one_with_an_engine_path_wins(self):
        self.fc.add("data/other.car", {"general": {}})
        self.assertEqual(self.row(limiter())["default"], 7000)

    def test_several_car_files_with_an_engine_path_are_ambiguous(self):
        self.fc.add("data/other.car", {"engine_path": "x"})
        row = self.row(limiter())
        self.assertFalse(row["applicable"])
        self.assertIn("ambiguous: 2 .car files", row["reason"])

    def test_no_car_file(self):
        os.remove(os.path.join(self.fc.car_root, "data", "x.car"))
        row = self.row(limiter())
        self.assertIn("no .car file in", row["reason"])

    def test_hidden_false_keeps_only_applicable_rows(self):
        rows = tune.resolve_defaults(self.work, "ks_x", mini_catalogue(limiter(), mini_setting("deep", targets=[("@engine", "q.r")])))
        self.assertEqual([r["id"] for r in rows], ["limiter"])

    def test_row_of_undecodable_file_is_hidden_with_the_decoder_message(self):
        self.fc.add("data/engine.carengine", ValueError("engine.carengine: wire type mismatch"))
        row = self.row(limiter())
        self.assertEqual((row["applicable"], row["reason"]), (False, "@engine limiter: engine.carengine: wire type mismatch"))

    def test_car_path_and_curve_path_stay_inside_their_folder(self):
        root = self.fc.car_root
        with self.assertRaises(ValueError):
            tune.car_path(root, "../../etc/passwd")
        with self.assertRaises(ValueError):
            tune.curve_path(self.fc.root, "..\\..\\evil.curve")
        self.assertEqual(tune.car_path(root, "data/x.car"), os.path.realpath(os.path.join(root, "data", "x.car")))
        self.assertTrue(tune.car_path(root, "../common_phsx/tyres/road/a.tyre").endswith(os.path.join("common_phsx", "tyres", "road", "a.tyre")))

    def test_renamed_replaces_the_old_id_case_insensitively(self):
        self.assertEqual(tune.renamed("data/KS_X_engine.car", "ks_x", "ax_x"), "data/ax_x_engine.car")


# --------------------------------------------------------------------------------------------- variants
class TestVariants(CarCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(tune._resolved.clear)
        self.engine["turbos_to_load"] = [self.fc.game_path("data/t0.turbo")]
        self.fc.add("data/t0.turbo", {"max_boost": 0.8})
        add_variant(self.fc)
        self.cat = mini_catalogue(limiter(), mini_setting("camber", targets=[("@setup", "alignments[0].camber")]),
                                  mini_setting("boost", targets=[("@turbo[0]", "max_boost")]),
                                  mini_setting("power", targets=[("@mech_preset", "car_specs.items[key=KEY_POWER].value")]),
                                  mini_setting("tyre", targets=[("@tyre_front", "modelData.Dy0")]))

    def variants(self):
        return {v["id"]: v for v in tune.list_variants(self.work, "ks_x")}

    def defaults(self, **kw):
        return {r["id"]: r["default"] for r in tune.resolve_defaults(self.work, "ks_x", self.cat, hidden=True, **kw)}

    def test_the_variant_lists_its_role_files_and_the_members_not_shown(self):
        self.assertEqual(tune.list_variants(self.work, "ks_x"),
                         [{"id": "q_drift", "label": "Drift", "preset": "presets/q_drift.mechanicalcarpreset",
                           "roles": {"@engine": "data/drift.carengine", "@setup": "data/drift.carsetup"},
                           "not_shown": ["suspensions_geometry"], "error": None}])

    def test_the_id_is_lower_case_and_the_label_the_description_without_a_note(self):
        add_variant(self.fc, "q_Mixed", note="")
        found = self.variants()["q_mixed"]
        self.assertEqual((found["label"], found["preset"]), ("Name Preset q_Mixed", "presets/q_Mixed.mechanicalcarpreset"))

    def test_a_car_with_only_the_base_preset_has_no_variants(self):
        os.remove(os.path.join(self.fc.car_root, "presets", "q_drift.mechanicalcarpreset"))
        self.assertEqual(tune.list_variants(self.work, "ks_x"), [])

    def test_visual_only_presets_are_not_variants(self):
        self.fc.add("presets/r_visual.mechanicalcarpreset", {"note": "Visual", "forced_compatible_part_paths": []})
        add_variant(self.fc, "s_wing", "Wing", parts=("wing",))
        self.assertEqual(list(self.variants()), ["q_drift"])

    def test_variants_come_in_sorted_order_without_the_base_preset(self):
        add_variant(self.fc, "q_a", "A", parts=("setup",))
        self.assertEqual(list(self.variants()), ["q_a", "q_drift"])

    def test_a_missing_file_on_the_way_is_the_error_of_that_preset_only(self):
        add_variant(self.fc, "r_broken", "Broken", parts=("engine",))
        os.remove(os.path.join(self.fc.car_root, "presets", "parts", "r_broken_engine.carpart"))
        found = self.variants()
        self.assertIsNone(found["q_drift"]["error"])
        self.assertEqual((found["r_broken"]["label"], found["r_broken"]["roles"]), ("Broken", {}))
        self.assertIn("r_broken_engine.carpart not found in", found["r_broken"]["error"])

    def test_an_undecodable_tuning_part_and_a_missing_replacement_file_are_errors(self):
        add_variant(self.fc, "r_bad", "Bad", parts=("setup",))
        self.fc.add("data/parts/r_bad_setup.tuningpart", ValueError("r_bad_setup.tuningpart: wire type mismatch"))
        add_variant(self.fc, "s_gone", "Gone", parts=("engine",))
        os.remove(os.path.join(self.fc.car_root, "data", "drift.carengine"))
        found = self.variants()
        self.assertEqual(found["r_bad"]["error"], "r_bad_setup.tuningpart: wire type mismatch")
        self.assertIn("DRIFT.carengine not found in", found["s_gone"]["error"])

    def test_two_parts_naming_different_files_for_one_role_are_an_error(self):
        add_variant(self.fc, "r_two", "Two", parts=("engine", "setup"))
        self.fc.add("data/parts/r_two_setup.tuningpart", {"engine": {"path": self.fc.game_path("data/t0.turbo")}})
        self.assertRegex(self.variants()["r_two"]["error"], r"two tuning parts override @engine with different files")

    def test_the_variant_resolves_its_own_engine_turbo_setup_and_preset(self):
        stock = self.defaults()
        self.assertEqual((stock["limiter"], stock["boost"], stock["camber"], stock["power"]), (7000, 0.8, -1.5, 380.0))
        var = self.defaults(variant="q_drift")
        self.assertEqual((var["limiter"], var["boost"], var["camber"], var["power"]), (8000, 1.8, -3.0, 600.0))
        self.assertEqual(var["tyre"], stock["tyre"])
        self.assertEqual(self.defaults(), stock)

    def test_variant_and_stock_rows_do_not_share_the_cache(self):
        self.assertEqual(self.defaults(variant="q_drift")["limiter"], 8000)
        self.assertEqual(self.defaults()["limiter"], 7000)
        self.assertEqual(self.defaults(variant="q_drift")["limiter"], 8000)

    def test_a_variant_cannot_be_combined_with_a_tune(self):
        with self.assertRaisesRegex(ValueError, "variant"):
            tune.resolve_defaults(self.work, "ks_x", self.cat, tune="ax_x", variant="q_drift")

    def test_an_unknown_variant_and_a_variant_with_an_error_are_errors_naming_it(self):
        with self.assertRaisesRegex(ValueError, "ks_x has no variant nope"):
            self.defaults(variant="nope")
        add_variant(self.fc, "r_broken", "Broken", parts=("engine",))
        os.remove(os.path.join(self.fc.car_root, "presets", "parts", "r_broken_engine.carpart"))
        with self.assertRaisesRegex(ValueError, "variant r_broken of ks_x cannot be read: .*r_broken_engine.carpart not found"):
            self.defaults(variant="r_broken")


# --------------------------------------------------------------------------------------------- resolve cache, effective_row
class TestResolveCache(CarCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(tune._resolved.clear)
        self.stock_info()
        self.cat = mini_catalogue(*metas(), limiter())
        self.reads = []
        real = tune.load_msg
        self.patch(tune, "load_msg", lambda path: (self.reads.append(path), real(path))[1])

    def resolve(self, cat=None, **kw):
        return tune.resolve_defaults(self.work, "ks_x", cat or self.cat, **kw)

    def reads_after(self, call):
        call()
        return len(self.reads)

    def test_a_second_resolve_of_an_unchanged_car_reads_no_file(self):
        first = self.resolve()
        reads = len(self.reads)
        self.assertGreater(reads, 0)
        self.assertEqual(self.resolve(), first)
        self.assertEqual(self.resolve(hidden=True)[:len(first)], first)
        self.assertEqual(len(self.reads), reads)

    def test_a_changed_stamp_of_a_car_file_resolves_again(self):
        self.resolve()
        reads = len(self.reads)
        path = os.path.join(self.fc.car_root, "data", "x.car")
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1000000))
        self.resolve()
        self.assertGreater(len(self.reads), reads)

    def test_a_changed_stock_info_resolves_again(self):
        self.resolve()
        reads = len(self.reads)
        path = tune.stock_info_path(self.work, "ks_x")
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1000000))
        self.resolve()
        self.assertGreater(len(self.reads), reads)

    def test_init_forgets_the_cached_rows(self):
        self.write(tune.stock_loc_path(self.work), "loc")
        self.resolve()
        reads = self.reads_after(lambda: tune.init(self.work, "ks_x", os.path.join(self.work, "none.kspkg")))
        self.resolve()
        self.assertGreater(len(self.reads), reads)

    def test_ensure_tyre_files_forgets_the_cached_rows_when_it_extracts(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(kspkg, "cmd_extract", lambda pkg, outdir, prefix=None: self.fc.add_shared("tyres/road/a.tyre"))
        self.resolve()
        os.remove(os.path.join(self.fc.shared, "tyres", "road", "a.tyre"))
        reads = self.reads_after(lambda: self.assertEqual(tune.ensure_tyre_files(self.work, "ks_x", game), "extracted 1 file(s)"))
        self.resolve()
        self.assertGreater(len(self.reads), reads)

    def test_ensure_tyre_files_without_the_package_says_how_to_pass_it(self):
        game = os.path.join(self.work, "none.kspkg")
        self.resolve()
        os.remove(os.path.join(self.fc.shared, "tyres", "road", "a.tyre"))
        with self.assertRaises(ValueError) as cm:
            tune.ensure_tyre_files(self.work, "ks_x", game)
        self.assertEqual(str(cm.exception), GAME_MISSING % game)

    def test_ensure_tyre_files_keeps_the_cached_rows_when_nothing_is_extracted(self):
        game = os.path.join(self.work, "none.kspkg")
        self.resolve()
        reads = self.reads_after(lambda: self.assertEqual(tune.ensure_tyre_files(self.work, "ks_x", game), "present"))
        self.resolve()
        self.assertEqual(len(self.reads), reads)

    def test_the_caller_gets_its_own_copy_of_the_rows(self):
        expected = json.dumps(self.resolve(hidden=True), sort_keys=True)
        for _ in range(2):
            rows = self.resolve(hidden=True)
            rows[0]["default"] = "changed"
            rows[0]["targets"].append({})
            rows[-1]["targets"].clear()
            rows.pop(1)
        self.assertEqual(json.dumps(self.resolve(hidden=True), sort_keys=True), expected)

    def test_a_different_catalogue_is_resolved_on_its_own(self):
        self.resolve()
        self.assertEqual([r["id"] for r in self.resolve(mini_catalogue(*metas()))], ["name_suffix", "variant_name"])
        self.assertEqual([r["id"] for r in self.resolve(mini_catalogue(limiter()))], ["limiter"])

    def test_the_cache_key_holds_no_catalogue_text(self):
        self.resolve()
        self.assertTrue(tune._resolved)
        text = json.dumps(self.cat, sort_keys=True)
        for key in tune._resolved:
            self.assertFalse(any(isinstance(part, str) and text in part for part in key), key)

    def test_rows_are_not_cached_when_the_stock_info_is_missing(self):
        os.remove(tune.stock_info_path(self.work, "ks_x"))
        self.resolve()
        reads = len(self.reads)
        self.resolve()
        self.assertGreater(len(self.reads), reads)

    def test_effective_row_resolves_only_its_setting(self):
        cat = mini_catalogue(*metas(), limiter(), mini_setting("tc", type="int", targets=[("@setup", "electronics.tc1")]))
        tune.save_state(self.work, "ks_x", {"limiter": 8000})
        row = tune.effective_row(self.work, "ks_x", "limiter", cat)
        self.assertNotIn("setup.carsetup", [os.path.basename(p) for p in self.reads])
        self.assertEqual((row["id"], row["value"], row["default"], row["changed"]), ("limiter", 8000, 7000, True))
        every = {r["id"]: r for r in tune.effective_rows(self.work, "ks_x", cat, hidden=True)}
        self.assertEqual(row, every["limiter"])

    def test_effective_row_of_an_unknown_setting(self):
        with self.assertRaisesRegex(ValueError, "unknown setting 'nope'"):
            tune.effective_row(self.work, "ks_x", "nope", self.cat)


# --------------------------------------------------------------------------------------------- stock info, car list
class TestStockInfo(Base):
    def info(self, **kw):
        info = {"car_id": "ks_x", "display_name": "Car X", "brand": "B", "year": 2000}
        info.update(kw)
        return info

    def test_valid_and_complete(self):
        self.assertTrue(tune.valid_stock_info(self.info(), "ks_x"))
        self.assertFalse(tune.complete_stock_info(self.info()))
        full = self.info(property_1="a", property_2="b", property_3="c", variant_name="")
        self.assertTrue(tune.complete_stock_info(full))
        self.assertFalse(tune.complete_stock_info(None))

    def test_invalid_variants(self):
        for bad in (self.info(car_id="ks_y"), self.info(display_name=""), self.info(brand=3), self.info(year="2000"),
                    self.info(year=True), {"car_id": "ks_x"}, [1], None):
            with self.subTest(bad):
                self.assertFalse(tune.valid_stock_info(bad, "ks_x"))

    def test_load_missing_is_none_and_invalid_names_the_file(self):
        self.assertIsNone(tune.load_stock_info(self.work, "ks_x"))
        path = self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_other"})
        with self.assertRaises(ValueError) as cm:
            tune.load_stock_info(self.work, "ks_x")
        self.assertIn(path, str(cm.exception))

    def test_stock_info_or_none_with_nothing_and_no_game(self):
        self.assertIsNone(tune.stock_info_or_none(self.work, "ks_x", os.path.join(self.work, "no_game.kspkg")))

    def test_stock_info_or_none_returns_incomplete_info_when_the_game_cannot_complete_it(self):
        self.write(tune.stock_info_path(self.work, "ks_x"), self.info())
        got = tune.stock_info_or_none(self.work, "ks_x", os.path.join(self.work, "no_game.kspkg"))
        self.assertEqual(got, self.info())

    def stub_game(self, rows, loc=b""):
        sch = {"enums": {"CarContentData.Property%d" % i: ({}, {0: "Prop%d_Zero" % i}) for i in (1, 2, 3)}}
        self.patch(car_json, "load_schema", lambda path=None: sch)
        self.patch(tune, "read_game_file", lambda work, game, rel: b"table")
        self.patch(car_json, "decode_msg", lambda s, name, data: {"preset": {"lines": [{"car_content": r} for r in rows]}})
        if loc:
            self.write(tune.stock_loc_path(self.work), loc, binary=True)

    def test_write_stock_info_from_the_cars_table(self):
        self.stub_game([{"name": "ks_x", "display_name": "Car X", "brand": "B", "year": 1999, "property_2": "Property2_Modern"},
                        {"name": "ks_y", "display_name": "Other", "brand": "O", "year": 1}],
                       b"ks_x_preset_base=GT Base\r\nks_x_other=Z\r\nks_y_preset_base=No\r\n")
        self.assertEqual(tune.write_stock_info(self.work, "ks_x", "game"), "written")
        with open(tune.stock_info_path(self.work, "ks_x"), encoding="utf-8") as f:
            info = json.load(f)
        self.assertEqual(info, {"car_id": "ks_x", "display_name": "Car X", "brand": "B", "year": 1999, "property_1": "Prop1_Zero",
                                "property_2": "Property2_Modern", "property_3": "Prop3_Zero", "variant_name": "GT Base"})
        self.assertEqual(tune.write_stock_info(self.work, "ks_x", "game"), "present")

    def test_write_stock_info_needs_exactly_one_row(self):
        self.stub_game([], b"x=y\r\n")
        with self.assertRaisesRegex(ValueError, "has 0 rows for ks_x, expected 1"):
            tune.write_stock_info(self.work, "ks_x", "game")
        self.stub_game([{"name": "ks_x", "display_name": "A", "brand": "B", "year": 1}] * 2, b"x=y\r\n")
        with self.assertRaisesRegex(ValueError, "has 2 rows"):
            tune.write_stock_info(self.work, "ks_x", "game")

    def test_write_stock_info_row_without_a_year(self):
        self.stub_game([{"name": "ks_x", "display_name": "A", "brand": "B"}], b"x=y\r\n")
        with self.assertRaisesRegex(ValueError, "lacks display_name, brand or year"):
            tune.write_stock_info(self.work, "ks_x", "game")

    def test_ensure_stock_loc_copies_once(self):
        calls = []
        self.patch(tune, "read_game_file", lambda work, game, rel: calls.append(rel) or b"loc bytes")
        self.assertEqual(tune.ensure_stock_loc(self.work, "game"), "written")
        self.assertEqual(tune.ensure_stock_loc(self.work, "game"), "present")
        self.assertEqual(calls, [tune.STOCK_LOC])
        with open(tune.stock_loc_path(self.work), "rb") as f:
            self.assertEqual(f.read(), b"loc bytes")

    def test_read_game_file_requires_the_package(self):
        with self.assertRaisesRegex(ValueError, "game package not found"):
            tune.read_game_file(self.work, os.path.join(self.work, "nope.kspkg"), "a\\b")

    def test_read_game_file_without_the_package_says_how_to_pass_it(self):
        game = os.path.join(self.work, "nope.kspkg")
        with self.assertRaises(ValueError) as cm:
            tune.read_game_file(self.work, game, "a\\b")
        self.assertEqual(str(cm.exception), GAME_MISSING % game)

    def test_read_game_file_extracts_through_a_temp_folder_and_cleans_up(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)

        def extract(pkg, outdir, prefix=None):
            self.write(os.path.join(outdir, "system", "cars.table"), b"DATA", binary=True)
            print("noise from kspkg")
        self.patch(kspkg, "cmd_extract", extract)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            data = tune.read_game_file(self.work, game, "system\\cars.table")
        self.assertEqual((data, out.getvalue()), (b"DATA", ""))
        self.assertFalse(os.path.exists(os.path.join(self.work, "stock_tmp")))

    def test_read_game_file_file_not_in_the_package(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(kspkg, "cmd_extract", lambda pkg, outdir, prefix=None: None)
        with self.assertRaisesRegex(ValueError, "system.cars.table not found in"):
            tune.read_game_file(self.work, game, "system\\cars.table")
        self.assertFalse(os.path.exists(os.path.join(self.work, "stock_tmp")))


class TestPickCarAndIndex(Base):
    CARS = {"default": "ks_a", "cars": [{"id": "ks_a", "label": "A"}, {"id": "ks_b", "label": "B"}]}

    def test_pick_car_default_and_known(self):
        self.assertEqual(tune.pick_car(self.CARS), "ks_a")
        self.assertEqual(tune.pick_car(self.CARS, "ks_b"), "ks_b")

    def test_pick_car_without_index_lists_the_tested_cars(self):
        tune._index_error.clear()
        with self.assertRaisesRegex(ValueError, r"unknown car 'ks_z', the car list of the game is not available, the tested cars \(tuner/cars.json\) are: ks_a, ks_b"):
            tune.pick_car(self.CARS, "ks_z")

    def test_pick_car_with_index_accepts_any_game_car(self):
        index = [{"id": "ks_a", "display_name": "A"}, {"id": "ks_q", "display_name": "Q"}]
        self.assertEqual(tune.pick_car(self.CARS, "ks_q", index), "ks_q")

    def test_pick_car_with_index_suggests_close_matches_or_counts(self):
        index = [{"id": "ks_alfa_romeo", "display_name": "A"}, {"id": "ks_toyota_gr86", "display_name": "T"}]
        with self.assertRaisesRegex(ValueError, "unknown car 'ks_alfa_romeu', close matches: ks_alfa_romeo"):
            tune.pick_car(self.CARS, "ks_alfa_romeu", index)
        with self.assertRaisesRegex(ValueError, "the game has 2 cars, tune.py cars lists them"):
            tune.pick_car(self.CARS, "zzzz", index)

    def test_new_id_for(self):
        self.assertEqual(tune.new_id_for("ks_bmw_m3_e46_csl"), "ax_bmw_m3_e46_csl")
        self.assertEqual(tune.new_id_for("mx_thing"), "ax_thing")
        for car in ("ks_a", "ab_cd_ef"):
            self.assertEqual(len(tune.new_id_for(car)), len(car))

    def test_index_from_a_valid_cache(self):
        index = [{"id": "ks_a", "display_name": "A", "brand": "x", "year": 1}]
        self.write(tune.cars_index_path(self.work), index)
        self.assertEqual(tune.load_cars_index(self.work, os.path.join(self.work, "none.kspkg")), index)

    def test_index_cache_that_is_damaged_or_empty_falls_back_to_none_without_a_game(self):
        for text in ("[]", "{", '[{"id": 1}]', '{"id": "ks_a"}', '[{"id": "ks_a"}]'):
            with self.subTest(text):
                self.write(tune.cars_index_path(self.work), text)
                self.assertIsNone(tune.load_cars_index(self.work, os.path.join(self.work, "none.kspkg")))

    def test_index_without_cache_and_without_game_is_none(self):
        self.assertIsNone(tune.load_cars_index(self.work, os.path.join(self.work, "none.kspkg")))

    def test_index_without_game_says_how_to_pass_the_package(self):
        game = os.path.join(self.work, "none.kspkg")
        self.assertIsNone(tune.load_cars_index(self.work, game))
        self.assertEqual(tune._index_error, [GAME_MISSING % game])
        with self.assertRaises(ValueError) as cm:
            tune.pick_car(self.CARS, "ks_z")
        self.assertIn("(reason: %s)" % (GAME_MISSING % game), str(cm.exception))

    def test_index_from_a_damaged_package_says_to_pass_the_game(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(tune, "read_game_file", lambda work, game, rel: (_ for _ in ()).throw(ValueError("g.kspkg is not a .kspkg package")))
        self.assertIsNone(tune.load_cars_index(self.work, game))
        self.assertEqual(tune._index_error, ["g.kspkg is not a .kspkg package; if this is the wrong file, pass --game <path of content.kspkg>"])

    def test_index_from_a_table_without_cars_says_to_pass_the_game(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.stub_table([{"other": 1}])
        self.assertIsNone(tune.load_cars_index(self.work, game))
        self.assertEqual(tune._index_error, ["system\\cars.table lists no cars, pass --game <path of content.kspkg> of Assetto Corsa EVO"])

    def stub_table(self, lines):
        self.patch(tune, "read_game_file", lambda work, game, rel: b"table")
        self.patch(car_json, "load_schema", lambda path=None: {})
        self.patch(car_json, "decode_msg", lambda s, name, data: {"preset": {"lines": lines}})

    def test_index_from_the_game_is_sorted_cached_and_cleaned(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.stub_table([{"car_content": {"name": "ks_b", "display_name": "beta", "brand": "BB", "year": 2001}},
                         {"car_content": {"name": "ks_a", "display_name": "Zeta", "brand": "AA", "year": 2002}},
                         {"car_content": {"name": "ks_c"}},
                         {"car_content": {"name": ""}},
                         {"car_content": {"display_name": "no name"}},
                         {"other": 1},
                         {"car_content": {"name": "ks_b", "display_name": "beta again"}}])
        index = tune.load_cars_index(self.work, game)
        self.assertEqual([c["id"] for c in index], ["ks_b", "ks_c", "ks_a"])
        self.assertEqual(index[1], {"id": "ks_c", "display_name": "ks_c", "brand": "", "year": None})
        self.assertEqual(index[0]["display_name"], "beta again")
        with open(tune.cars_index_path(self.work), encoding="utf-8") as f:
            self.assertEqual(json.load(f), index)

    def test_index_with_an_unreadable_table_is_none_and_nothing_is_cached(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(tune, "read_game_file", lambda work, game, rel: (_ for _ in ()).throw(ValueError("package damaged")))
        self.assertIsNone(tune.load_cars_index(self.work, game))
        self.assertFalse(os.path.exists(tune.cars_index_path(self.work)))

    def test_unknown_car_message_carries_the_real_reason(self):
        self.cars(("ks_a", "A"))
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(tune, "read_game_file", lambda work, game, rel: (_ for _ in ()).throw(ValueError("missing schema file acevo.desc")))
        with self.assertRaises(ValueError) as cm:
            tune.start({"work": self.work, "car": "ks_other", "game": game})
        self.assertIn("missing schema file acevo.desc", str(cm.exception))


class TestListCars(Base):
    def setUp(self):
        super().setUp()
        self.cars(("ks_a", "Alpha"), ("ks_b", "Beta"))
        self.mods = str(self.d / "mods")
        self.game = os.path.join(self.work, "none.kspkg")

    def extract(self, car_id, size=10, name="f.bin"):
        self.write(os.path.join(tune.car_root_of(tune.base_dir(self.work, car_id), car_id), name), b"x" * size, binary=True)

    def test_an_unexpandable_default_mods_folder_says_what_to_pass(self):
        bad = "%ACE_TEST_NO_SUCH_VAR%" + os.sep + "m"
        with mock.patch.object(clone_car, "DEFAULT_MODS", bad), self.assertRaises(ValueError) as cm:
            tune.list_cars(self.work, game=self.game)
        self.assertEqual(str(cm.exception), "cannot expand the mods directory %r: the default is %s and this program expects Windows; "
                         "pass --mods <folder> on other systems" % (bad, bad))

    def test_without_index_only_tested_cars_sorted_by_display_name(self):
        rows = tune.list_cars(self.work, self.mods, game=self.game)
        self.assertEqual([(r["id"], r["display_name"], r["tested"], r["default"], r["extracted"], r["installed"], r["bytes"], r["new_id"])
                          for r in rows],
                         [("ks_a", "Alpha", True, True, False, False, None, "ax_a"), ("ks_b", "Beta", True, False, False, False, None, "ax_b")])

    def test_cache_adds_untested_cars_and_names(self):
        self.write(tune.cars_index_path(self.work), [{"id": "ks_c", "display_name": "Charlie"}, {"id": "ks_b", "display_name": "Beta Game"},
                                                     {"id": "ks_d", "display_name": "alpha two"}])
        rows = tune.list_cars(self.work, self.mods, game=self.game)
        self.assertEqual([(r["id"], r["display_name"], r["label"], r["tested"]) for r in rows],
                         [("ks_a", "Alpha", "Alpha", True), ("ks_d", "alpha two", "alpha two", False), ("ks_b", "Beta Game", "Beta", True),
                          ("ks_c", "Charlie", "Charlie", False)])

    def test_tested_only_ignores_the_cache(self):
        self.write(tune.cars_index_path(self.work), [{"id": "ks_c", "display_name": "Charlie"}])
        self.assertEqual([r["id"] for r in tune.list_cars(self.work, self.mods, tested_only=True, game=self.game)], ["ks_a", "ks_b"])

    def test_extracted_size_and_stock_name(self):
        self.extract("ks_a", 10)
        self.extract("ks_a", 5, "sub/g.bin")
        self.write(tune.stock_info_path(self.work, "ks_a"), {"car_id": "ks_a", "display_name": "Zulu Stock", "brand": "B", "year": 1})
        rows = {r["id"]: r for r in tune.list_cars(self.work, self.mods, game=self.game)}
        self.assertEqual((rows["ks_a"]["extracted"], rows["ks_a"]["bytes"], rows["ks_a"]["display_name"], rows["ks_a"]["label"]),
                         (True, 15, "Zulu Stock", "Alpha"))
        self.assertEqual((rows["ks_b"]["extracted"], rows["ks_b"]["bytes"]), (False, None))

    def test_empty_car_folder_does_not_count_as_extracted(self):
        os.makedirs(tune.car_root_of(tune.base_dir(self.work, "ks_a"), "ks_a"))
        self.assertFalse([r for r in tune.list_cars(self.work, self.mods, game=self.game) if r["id"] == "ks_a"][0]["extracted"])

    def test_installed_means_the_new_id_package_is_in_the_mods_folder(self):
        self.write(os.path.join(self.mods, "ax_b.kspkg"), b"p", binary=True)
        self.write(os.path.join(self.mods, "ax_a.txt"), b"p", binary=True)
        rows = {r["id"]: r["installed"] for r in tune.list_cars(self.work, self.mods, game=self.game)}
        self.assertEqual(rows, {"ks_a": False, "ks_b": True})

    def test_list_survives_a_damaged_stock_info(self):
        self.extract("ks_a")
        self.extract("ks_b")
        self.write(tune.stock_info_path(self.work, "ks_b"), '{"car_id": "ks_b", "disp')
        rows = tune.list_cars(self.work, self.mods, game=self.game)
        self.assertEqual([r["id"] for r in rows], ["ks_a", "ks_b"])

    def test_without_sizes_no_tree_is_walked(self):
        self.extract("ks_a", 10)
        walked = []
        real = tune.count_tree
        self.patch(tune, "count_tree", lambda path: walked.append(path) or real(path))
        rows = {r["id"]: r for r in tune.list_cars(self.work, self.mods, game=self.game, sizes=False)}
        self.assertEqual((walked, rows["ks_a"]["extracted"], rows["ks_a"]["bytes"]), ([], True, None))
        rows = {r["id"]: r for r in tune.list_cars(self.work, self.mods, game=self.game)}
        self.assertEqual((len(walked), rows["ks_a"]["bytes"]), (1, 10))

    def test_an_unexpandable_mods_folder_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "cannot expand"):
            tune.list_cars(self.work, "%ACE_TEST_NO_SUCH_VAR%" + os.sep + "m", game=self.game)

    def test_note_untested(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tune.note_untested("ks_a")
            tune.note_untested("ks_zzz")
        self.assertEqual(out.getvalue(), "note: ks_zzz is not in the tested list; results are unverified\n")


# --------------------------------------------------------------------------------------------- modded cars (tunes)
class TuneCase(Base):
    """Two synthetic stock cars ks_alpha / ks_bravo (default tunes ax_alpha / ax_bravo) in a scratch work folder and mods folder."""

    def setUp(self):
        super().setUp()
        self.cars(("ks_alpha", "Alpha"), ("ks_bravo", "Bravo"))
        self.patch(tune, "load_catalogue", lambda path=None: mini_catalogue(suffix()))
        self.mods = str(self.d / "mods")
        os.makedirs(self.mods)

    def extract(self, car_id):
        self.write(os.path.join(tune.car_root_of(tune.base_dir(self.work, car_id), car_id), "f.bin"), b"x", binary=True)

    def build(self, car_id, tune_id):
        self.write(os.path.join(tune.build_dir(self.work, car_id), tune_id, tune_id + ".kspkg"), b"p", binary=True)

    def install(self, tune_id):
        self.write(os.path.join(self.mods, tune_id + ".kspkg"), b"p", binary=True)

    def files(self):
        return sorted(os.path.relpath(os.path.join(dp, n), self.work) for dp, _, names in os.walk(self.work) for n in names)

    def dirs(self):
        return sorted(os.path.relpath(os.path.join(dp, n), self.work) for dp, names, _ in os.walk(self.work) for n in names)


class TestTuneStatePaths(TuneCase):
    def test_check_tune_id_checks_the_id_only_and_never_looks_at_the_disk(self):
        with mock.patch.object(os.path, "exists", side_effect=AssertionError("looked at the disk")):
            tune.check_tune_id(self.work, "ks_alpha", "ax_alpha")
            for bad in ("AX_ALPHA", "ax_alph", "ks_alpha", "", None, 5):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    tune.check_tune_id(self.work, "ks_alpha", bad)

    def test_clone_defaults_are_the_ones_of_clone_car(self):
        self.assertEqual((tune.CLONE_YEAR, tune.CLONE_BRAND), (clone_car.DEFAULT_YEAR, clone_car.DEFAULT_BRAND))

    def test_old_calls_keep_the_legacy_path(self):
        self.assertEqual(tune.state_path(self.work, "ks_alpha"), os.path.join(self.work, "ks_alpha", "tune_state.json"))
        tune.save_state(self.work, "ks_alpha", {"limiter": 1})
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"limiter": 1})
        self.assertEqual(self.files(), [os.path.join("ks_alpha", "tune_state.json")])

    def test_default_id_and_none_are_the_legacy_path_and_write_no_meta(self):
        self.assertEqual(tune.state_path(self.work, "ks_alpha", "ax_alpha"), tune.state_path(self.work, "ks_alpha"))
        tune.save_state(self.work, "ks_alpha", {"a": 1}, "ax_alpha")
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"a": 1})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alpha"), {"a": 1})
        self.assertEqual(self.files(), [os.path.join("ks_alpha", "tune_state.json")])

    def test_draft_path_and_no_meta(self):
        self.assertEqual(tune.DRAFT, "draft")
        self.assertEqual(tune.state_path(self.work, "ks_alpha", tune.DRAFT), os.path.join(self.work, "ks_alpha", "draft_state.json"))
        tune.save_state(self.work, "ks_alpha", {"d": 1}, tune.DRAFT)
        self.assertEqual(tune.load_state(self.work, "ks_alpha", tune.DRAFT), {"d": 1})
        self.assertEqual(self.files(), [os.path.join("ks_alpha", "draft_state.json")])
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {})

    def test_other_ids_live_in_tunes_with_a_meta_file(self):
        self.assertEqual(tune.TUNES, "tunes")
        self.assertEqual(tune.state_path(self.work, "ks_alpha", "ax_alp01"), os.path.join(self.work, "ks_alpha", "tunes", "ax_alp01", "tune_state.json"))
        tune.save_state(self.work, "ks_alpha", {"x": 2}, "ax_alp01")
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {"x": 2})
        self.assertEqual(self.files(), [os.path.join("ks_alpha", "tunes", "ax_alp01", "meta.json"), os.path.join("ks_alpha", "tunes", "ax_alp01", "tune_state.json")])
        with open(os.path.join(self.work, "ks_alpha", "tunes", "ax_alp01", "meta.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"stock": "ks_alpha"})

    def test_an_existing_meta_file_is_kept(self):
        meta = self.write(os.path.join(self.work, "ks_alpha", "tunes", "ax_alp01", "meta.json"), {"stock": "ks_alpha", "keep": True})
        tune.save_state(self.work, "ks_alpha", {}, "ax_alp01")
        with open(meta, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"stock": "ks_alpha", "keep": True})

    def test_a_missing_tune_state_is_empty(self):
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {})

    def test_tune_dir(self):
        car = os.path.join(self.work, "ks_alpha")
        self.assertEqual([tune.tune_dir(self.work, "ks_alpha", t) for t in (None, "ax_alpha", tune.DRAFT)], [car] * 3)
        self.assertEqual(tune.tune_dir(self.work, "ks_alpha", "ax_alp02"), os.path.join(car, "tunes", "ax_alp02"))

    def test_invalid_ids_are_refused_everywhere_and_write_nothing(self):
        for bad in ("ax_alp1", "ax_alpha1", "AX_ALP01", "ax_alp0!", "..", "../ax_al", "ax/alp01", "ax\\alp01", "ks_alpha", "", 5):
            with self.subTest(bad=bad):
                for call in (lambda: tune.state_path(self.work, "ks_alpha", bad), lambda: tune.load_state(self.work, "ks_alpha", bad),
                             lambda: tune.save_state(self.work, "ks_alpha", {}, bad)):
                    with self.assertRaises(ValueError):
                        call()
        self.assertFalse(os.path.exists(self.work))

    def test_the_stock_id_is_refused_with_the_clone_message(self):
        with self.assertRaisesRegex(ValueError, "new id equals the old id 'ks_alpha'"):
            tune.state_path(self.work, "ks_alpha", "ks_alpha")


class TestListTunes(TuneCase):
    def test_nothing_without_a_state_or_build(self):
        self.extract("ks_alpha")
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha"), [])
        self.assertEqual(tune.list_tunes(self.work, "ks_missing"), [])

    def test_default_is_listed_for_its_state_file(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"})
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha"),
                         [{"id": "ax_alpha", "stock": "ks_alpha", "default": True, "name_suffix": "_A", "has_state": True}])

    def test_default_is_listed_for_its_build_folder_without_a_state(self):
        self.build("ks_alpha", "ax_alpha")
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha"),
                         [{"id": "ax_alpha", "stock": "ks_alpha", "default": True, "name_suffix": "MY", "has_state": False}])

    def test_an_empty_build_folder_of_another_tune_does_not_list_it(self):
        self.build("ks_alpha", "ax_alp01")
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha"), [])

    def test_other_tunes_need_a_state_file_and_the_default_comes_first(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_Z"}, "ax_alp02")
        tune.save_state(self.work, "ks_alpha", {}, "ax_alp01")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_D"})
        os.makedirs(os.path.join(self.work, "ks_alpha", "tunes", "ax_alp03"))
        self.write(os.path.join(self.work, "ks_alpha", "tunes", "ax_alp04", "meta.json"), {"stock": "ks_alpha"})
        rows = tune.list_tunes(self.work, "ks_alpha")
        self.assertEqual([(r["id"], r["default"], r["name_suffix"], r["has_state"]) for r in rows],
                         [("ax_alpha", True, "_D", True), ("ax_alp01", False, "MY", True), ("ax_alp02", False, "_Z", True)])
        self.assertEqual({r["stock"] for r in rows}, {"ks_alpha"})

    def test_stray_and_reserved_folders_are_ignored(self):
        for name in ("notes", "AX_ALP01", "ax_alp1", "draft", "ax_alpha"):
            self.write(os.path.join(self.work, "ks_alpha", "tunes", name, "tune_state.json"), {"name_suffix": "_S"})
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha"), [])

    def test_the_tunes_of_another_car_are_not_listed(self):
        tune.save_state(self.work, "ks_bravo", {}, "ax_bra01")
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha"), [])

    def test_suffix_comes_from_the_catalogue_default_when_the_state_has_none(self):
        self.patch(tune, "load_catalogue", lambda path=None: mini_catalogue(dict(suffix(), default="_DEF")))
        tune.save_state(self.work, "ks_alpha", {"limiter": 5}, "ax_alp01")
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha")[0]["name_suffix"], "_DEF")

    def test_a_catalogue_without_the_suffix_setting_is_an_error(self):
        self.patch(tune, "load_catalogue", lambda path=None: mini_catalogue(limiter()))
        with self.assertRaisesRegex(ValueError, "no name_suffix setting"):
            tune.list_tunes(self.work, "ks_alpha")

    def test_a_damaged_state_is_an_error_naming_the_file(self):
        self.write(tune.state_path(self.work, "ks_alpha"), '{"name_su')
        with self.assertRaisesRegex(ValueError, "tune_state.json"):
            tune.list_tunes(self.work, "ks_alpha")


class TestKnownTuneIds(TuneCase):
    def test_default_ids_of_tested_cars_even_without_a_work_folder(self):
        self.assertEqual(tune.known_tune_ids(self.work), {"ax_alpha", "ax_bravo"})

    def test_cars_index_and_extracted_folders_add_default_ids(self):
        self.write(tune.cars_index_path(self.work), [{"id": "ks_charlie", "display_name": "Charlie"}])
        self.extract("ks_delta")
        self.write(os.path.join(self.work, "backups", "x.kspkg"), b"p", binary=True)
        self.assertEqual(tune.known_tune_ids(self.work), {"ax_alpha", "ax_bravo", "ax_charlie", "ax_delta"})

    def test_tunes_folders_of_every_car(self):
        tune.save_state(self.work, "ks_alpha", {}, "ax_alp01")
        tune.save_state(self.work, "ks_bravo", {}, "ax_bra07")
        os.makedirs(os.path.join(self.work, "ks_bravo", "tunes", "ax_bra08"))
        self.write(os.path.join(self.work, "ks_bravo", "tunes", "stray.txt"), "x")
        self.assertEqual(tune.known_tune_ids(self.work), {"ax_alpha", "ax_bravo", "ax_alp01", "ax_bra07", "ax_bra08"})

    def test_mods_folder_packages_only_when_given(self):
        self.install("ax_alp05")
        self.write(os.path.join(self.mods, "ax_alp06.txt"), b"x", binary=True)
        self.write(os.path.join(self.mods, "AX_ALP07.KSPKG"), b"x", binary=True)
        self.assertNotIn("ax_alp05", tune.known_tune_ids(self.work))
        self.assertEqual(tune.known_tune_ids(self.work, self.mods), {"ax_alpha", "ax_bravo", "ax_alp05", "ax_alp07"})

    def test_a_missing_mods_folder_adds_nothing(self):
        self.assertEqual(tune.known_tune_ids(self.work, str(self.d / "nowhere")), {"ax_alpha", "ax_bravo"})

    def test_the_game_package_is_never_read(self):
        real = tune.read_game_file
        calls = []
        self.patch(tune, "read_game_file", lambda *a, **k: calls.append(a) or real(*a, **k))
        tune.known_tune_ids(self.work)
        self.assertEqual(calls, [])


class TestFreeTuneId(TuneCase):
    def test_first_id_replaces_the_last_two_characters_and_keeps_the_length(self):
        got = tune.free_tune_id(self.work, "ks_alpha")
        self.assertEqual((got, len(got)), ("ax_alp01", len("ks_alpha")))
        self.assertEqual(tune.free_tune_id(self.work, "ks_bmw_m3_e46_csl"), "ax_bmw_m3_e46_c01")

    def test_nothing_is_written(self):
        tune.free_tune_id(self.work, "ks_alpha", self.mods)
        self.assertFalse(os.path.exists(self.work))

    def test_the_counter_skips_tunes_mods_packages_and_other_default_ids(self):
        tune.save_state(self.work, "ks_alpha", {}, "ax_alp01")
        self.install("ax_alp02")
        self.cars(("ks_alpha", "Alpha"), ("ks_alp03", "Other"))
        # the default id of another stock car sits in the sequence: ks_alp03 -> ax_alp03
        self.assertEqual(tune.free_tune_id(self.work, "ks_alpha", self.mods), "ax_alp04")

    def test_without_the_mods_folder_its_packages_do_not_count(self):
        self.install("ax_alp01")
        self.assertEqual(tune.free_tune_id(self.work, "ks_alpha"), "ax_alp01")
        self.assertEqual(tune.free_tune_id(self.work, "ks_alpha", self.mods), "ax_alp02")

    def test_a_tune_of_another_stock_car_blocks_the_id_too(self):
        tune.save_state(self.work, "ks_bravo", {}, "ax_alp01")
        self.assertEqual(tune.free_tune_id(self.work, "ks_alpha"), "ax_alp02")

    def test_ids_up_to_99_then_exhausted(self):
        for n in range(1, 100):
            self.install("ax_alp%02d" % n)
        os.remove(os.path.join(self.mods, "ax_alp99.kspkg"))
        self.assertEqual(tune.free_tune_id(self.work, "ks_alpha", self.mods), "ax_alp99")
        self.install("ax_alp99")
        with self.assertRaisesRegex(ValueError, "no free tuned car id left for ks_alpha"):
            tune.free_tune_id(self.work, "ks_alpha", self.mods)

    def test_a_stock_id_too_short_for_the_pattern_has_no_valid_id(self):
        self.cars(("k", "K"))
        with self.assertRaisesRegex(ValueError, "no free tuned car id left"):
            tune.free_tune_id(self.work, "k")


class TestTuneSuffix(TuneCase):
    def setUp(self):
        super().setUp()
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_B"}, "ax_alp01")
        tune.save_state(self.work, "ks_bravo", {"name_suffix": "_C"})

    def test_taken_is_per_stock_car(self):
        self.assertIsNotNone(tune.suffix_owner(self.work, "ks_alpha", "_A"))
        self.assertIsNotNone(tune.suffix_owner(self.work, "ks_alpha", "_B"))
        self.assertIsNone(tune.suffix_owner(self.work, "ks_alpha", "_C"))
        self.assertIsNone(tune.suffix_owner(self.work, "ks_alpha", "_a"))
        self.assertIsNone(tune.suffix_owner(self.work, "ks_alpha", "_A "))

    def test_free_suffix_reads_the_state_of_each_tune_once(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY"}, "ax_alp02")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY 2"}, "ax_alp03")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY 3"}, "ax_alp04")
        reads = []
        real = tune.load_state
        self.patch(tune, "load_state", lambda work, car, tune_id=None: (reads.append(tune_id), real(work, car, tune_id))[1])
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY"), "MY 4")
        self.assertEqual(sorted(reads), ["ax_alp01", "ax_alp02", "ax_alp03", "ax_alp04", "ax_alpha"])

    def test_exclude_ignores_that_tune(self):
        self.assertIsNone(tune.suffix_owner(self.work, "ks_alpha", "_A", exclude="ax_alpha"))
        self.assertIsNotNone(tune.suffix_owner(self.work, "ks_alpha", "_A", exclude="ax_alp01"))

    def test_the_default_suffix_counts_when_the_state_has_none(self):
        tune.save_state(self.work, "ks_alpha", {}, "ax_alp02")
        self.assertIsNotNone(tune.suffix_owner(self.work, "ks_alpha", "MY"))

    def test_free_suffix_returns_a_free_one_unchanged(self):
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_NEW"), "_NEW")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_C"), "_C")

    def test_free_suffix_counts_up_from_2(self):
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_A"), "_A 2")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A 2"}, "ax_alp02")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_A"), "_A 3")

    def test_free_suffix_treats_a_number_without_a_space_as_part_of_the_text(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY2"}, "ax_alp02")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY2"), "MY2 2")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY2 2"}, "ax_alp03")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY2"), "MY2 3")

    def test_free_suffix_counts_a_trailing_number_up_instead_of_appending(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY"}, "ax_alp02")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY"), "MY 2")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY 2"}, "ax_alp03")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY"), "MY 3")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY 2"), "MY 3")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "MY 3"}, "ax_alp04")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY 2"), "MY 4")

    def test_free_suffix_with_a_wanted_number_goes_to_the_next_one(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_T 1"}, "ax_alp02")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_T 1"), "_T 2")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_T 2"}, "ax_alp03")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_T 1"), "_T 3")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_T 3"), "_T 3")

    def test_free_suffix_keeps_the_width_of_a_number_with_leading_zeros(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_T 01"}, "ax_alp02")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_T 09"}, "ax_alp03")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_T 01"), "_T 02")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_T 09"), "_T 10")

    def test_free_suffix_cuts_the_stem_and_never_the_number(self):
        wanted = "x" * 28 + " 9"
        tune.save_state(self.work, "ks_alpha", {"name_suffix": wanted}, "ax_alp02")
        got = tune.free_suffix(self.work, "ks_alpha", wanted)
        self.assertEqual((got, len(got)), ("x" * 27 + " 10", 30))
        tune.save_state(self.work, "ks_alpha", {"name_suffix": got}, "ax_alp03")
        got = tune.free_suffix(self.work, "ks_alpha", wanted)
        self.assertEqual((got, len(got)), ("x" * 27 + " 11", 30))
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "x " + "9" * 28}, "ax_alp04")
        with self.assertRaisesRegex(ValueError, "no free name suffix left"):
            tune.free_suffix(self.work, "ks_alpha", "x " + "9" * 28)

    def test_free_suffix_never_leaves_a_space_at_the_end_of_the_cut_stem(self):
        wanted = "x" * 27 + " " + "y" * 2
        tune.save_state(self.work, "ks_alpha", {"name_suffix": wanted}, "ax_alp02")
        got = tune.free_suffix(self.work, "ks_alpha", wanted)
        self.assertEqual((got, len(got)), ("x" * 27 + " 2", 29))

    def test_free_suffix_with_exclude_keeps_its_own(self):
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "_B", exclude="ax_alp01"), "_B")

    def test_free_suffix_stays_within_the_length_limit(self):
        long = "x" * tune.NAME_SUFFIX_MAX
        tune.save_state(self.work, "ks_alpha", {"name_suffix": long}, "ax_alp02")
        got = tune.free_suffix(self.work, "ks_alpha", long)
        self.assertEqual((got, len(got)), ("x" * 28 + " 2", 30))

    def test_free_suffix_validates_the_wanted_suffix(self):
        for bad in ("", "x" * 31, "a\nb", 5, None):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "name_suffix expects 1 to 30 characters"):
                tune.free_suffix(self.work, "ks_alpha", bad)

    def test_a_legacy_suffix_on_disk_reads_converted_and_is_not_rewritten(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY"}, "ax_alp02")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY3"}, "ax_alp03")
        self.assertEqual([t["name_suffix"] for t in tune.list_tunes(self.work, "ks_alpha")], ["_A", "_B", "MY", "MY 3"])
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp02"), {"name_suffix": "_MY"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp03"), {"name_suffix": "_MY3"})
        self.assertEqual(tune.suffix_owner(self.work, "ks_alpha", "MY"), "ax_alp02")
        self.assertEqual(tune.suffix_owner(self.work, "ks_alpha", "MY 3"), "ax_alp03")
        self.assertIsNone(tune.suffix_owner(self.work, "ks_alpha", "_MY"))
        self.assertIsNone(tune.suffix_owner(self.work, "ks_alpha", "_MY3"))
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY"), "MY 2")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "MY 3"), "MY 4")

    def test_another_saved_suffix_with_an_underscore_stays_as_it_is(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_Drift"}, "ax_alp02")
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha")[-1]["name_suffix"], "_Drift")
        self.assertEqual(tune.state_suffix({"name_suffix": "_Drift"}, suffix()), "_Drift")
        self.assertEqual(tune.state_suffix({"name_suffix": "_MY2"}, suffix()), "MY 2")
        self.assertEqual(tune.state_suffix({}, suffix()), "MY")

    def test_the_wanted_suffix_is_trimmed_and_its_inner_space_runs_collapsed_before_it_is_compared(self):
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", " _A"), "_A 2")
        self.assertEqual(tune.free_suffix(self.work, "ks_alpha", "  _NEW   x "), "_NEW x")


class TestDuplicateTune(TuneCase):
    def snapshot(self):
        out = {}
        for dp, _, names in os.walk(self.work):
            for n in names:
                with open(os.path.join(dp, n), "rb") as f:
                    out[os.path.relpath(os.path.join(dp, n), self.work)] = f.read()
        return out, self.dirs()

    def test_from_the_default_tune(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A", "limiter": 8000, "nested": {"a": [1]}})
        res = tune.duplicate_tune(self.work, "ks_alpha", None)
        self.assertEqual(res, {"id": "ax_alp01", "stock": "ks_alpha", "name_suffix": "_A 2"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {"name_suffix": "_A 2", "limiter": 8000, "nested": {"a": [1]}})
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"name_suffix": "_A", "limiter": 8000, "nested": {"a": [1]}})
        with open(os.path.join(self.work, "ks_alpha", "tunes", "ax_alp01", "meta.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"stock": "ks_alpha"})

    def test_from_a_legacy_source_the_suffix_counts_up_from_the_converted_one(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY", "limiter": 8000})
        res = tune.duplicate_tune(self.work, "ks_alpha", None)
        self.assertEqual(res, {"id": "ax_alp01", "stock": "ks_alpha", "name_suffix": "MY 2"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {"name_suffix": "MY 2", "limiter": 8000})
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"name_suffix": "_MY", "limiter": 8000})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY2"}, "ax_alp05")
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", "ax_alp05")["name_suffix"], "MY 3")

    def test_an_explicit_suffix_is_saved_trimmed_and_compared_trimmed(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"})
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", None, suffix="  Super   charged ")["name_suffix"], "Super charged")
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {"name_suffix": "Super charged"})
        with self.assertRaisesRegex(ValueError, "name suffix already used by ax_alpha"):
            tune.duplicate_tune(self.work, "ks_alpha", None, suffix=" _A ")

    def test_the_default_id_as_src_is_the_default_tune(self):
        tune.save_state(self.work, "ks_alpha", {"limiter": 1})
        tune.duplicate_tune(self.work, "ks_alpha", "ax_alpha")
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01")["limiter"], 1)

    def test_the_copy_is_deep(self):
        tune.save_state(self.work, "ks_alpha", {"nested": {"a": [1]}})
        tune.duplicate_tune(self.work, "ks_alpha", None)
        state = tune.load_state(self.work, "ks_alpha", "ax_alp01")
        state["nested"]["a"].append(2)
        tune.save_state(self.work, "ks_alpha", state, "ax_alp01")
        self.assertEqual(tune.load_state(self.work, "ks_alpha")["nested"], {"a": [1]})

    def test_from_a_modded_tune_and_a_chain_of_copies(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A", "x": 1})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_DRIFT", "x": 2}, "ax_alp01")
        first = tune.duplicate_tune(self.work, "ks_alpha", "ax_alp01")
        second = tune.duplicate_tune(self.work, "ks_alpha", "ax_alp01")
        self.assertEqual((first["id"], first["name_suffix"], second["id"], second["name_suffix"]), ("ax_alp02", "_DRIFT 2", "ax_alp03", "_DRIFT 3"))
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp03"), {"name_suffix": "_DRIFT 3", "x": 2})

    def test_from_the_draft(self):
        tune.save_state(self.work, "ks_alpha", {"limiter": 9000}, tune.DRAFT)
        res = tune.duplicate_tune(self.work, "ks_alpha", tune.DRAFT)
        self.assertEqual(res, {"id": "ax_alp01", "stock": "ks_alpha", "name_suffix": "MY"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {"limiter": 9000, "name_suffix": "MY"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", tune.DRAFT), {"limiter": 9000})

    def test_an_absent_draft_or_default_state_copies_an_empty_state(self):
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", tune.DRAFT)["id"], "ax_alp01")
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", None)["name_suffix"], "MY 2")
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp02"), {"name_suffix": "MY 2"})

    def test_the_first_modded_car_can_take_the_default_id(self):
        tune.save_state(self.work, "ks_alpha", {"limiter": 9000}, tune.DRAFT)
        res = tune.duplicate_tune(self.work, "ks_alpha", tune.DRAFT, new_id="ax_alpha")
        self.assertEqual(res["id"], "ax_alpha")
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"limiter": 9000, "name_suffix": "MY"})
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_alpha", "tunes")))
        self.assertEqual([t["id"] for t in tune.list_tunes(self.work, "ks_alpha")], ["ax_alpha"])

    def test_the_default_id_is_refused_when_the_default_tune_exists(self):
        for make in (lambda: tune.save_state(self.work, "ks_alpha", {}), lambda: self.build("ks_alpha", "ax_alpha")):
            make()
            with self.assertRaisesRegex(ValueError, "ax_alpha is already a tune of ks_alpha"):
                tune.duplicate_tune(self.work, "ks_alpha", tune.DRAFT, new_id="ax_alpha")
            shutil.rmtree(os.path.join(self.work, "ks_alpha"))

    def test_an_explicit_id(self):
        res = tune.duplicate_tune(self.work, "ks_alpha", None, new_id="ax_alp42", suffix="_X")
        self.assertEqual(res, {"id": "ax_alp42", "stock": "ks_alpha", "name_suffix": "_X"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp42"), {"name_suffix": "_X"})

    def test_the_auto_id_skips_the_mods_folder_when_given(self):
        self.install("ax_alp01")
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", None, mods_dir=self.mods)["id"], "ax_alp02")

    def test_explicit_ids_that_are_used_are_refused(self):
        tune.save_state(self.work, "ks_alpha", {}, "ax_alp01")
        self.install("ax_alp02")
        for bad in ("ax_alp01", "ax_bravo"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "already used or reserved"):
                tune.duplicate_tune(self.work, "ks_alpha", None, new_id=bad, mods_dir=self.mods)
        with self.assertRaisesRegex(ValueError, "already used or reserved"):
            tune.duplicate_tune(self.work, "ks_alpha", None, new_id="ax_alp02", mods_dir=self.mods)
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", None, new_id="ax_alp02")["id"], "ax_alp02")

    def test_invalid_explicit_ids_are_refused(self):
        for bad in ("ax_alp1", "ax_alpha1", "AX_ALP01", "ax/alp01", "ax\\alp01", "..", "../ax_alp", "ks_alpha", "", 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tune.duplicate_tune(self.work, "ks_alpha", None, new_id=bad)
        self.assertFalse(os.path.exists(self.work))

    def test_the_draft_name_is_reserved_for_a_five_character_stock_id(self):
        self.cars(("ks_ab", "Ab"))
        with self.assertRaisesRegex(ValueError, "already used or reserved"):
            tune.duplicate_tune(self.work, "ks_ab", None, new_id="draft")
        self.assertEqual(tune.duplicate_tune(self.work, "ks_ab", None)["id"], "ax_01")

    def test_suffix_defaults_to_a_unique_one_and_an_explicit_one_is_checked(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"})
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", None, suffix="_NEW")["name_suffix"], "_NEW")
        with self.assertRaisesRegex(ValueError, "name suffix already used by ax_alpha"):
            tune.duplicate_tune(self.work, "ks_alpha", None, suffix="_A")
        with self.assertRaisesRegex(ValueError, "name suffix already used by ax_alp01"):
            tune.duplicate_tune(self.work, "ks_alpha", None, suffix="_NEW")

    def test_a_suffix_of_another_stock_car_is_no_collision(self):
        tune.save_state(self.work, "ks_bravo", {"name_suffix": "_A"})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_Q"})
        self.assertEqual(tune.duplicate_tune(self.work, "ks_alpha", None, suffix="_A")["name_suffix"], "_A")

    def test_an_invalid_explicit_suffix_is_refused(self):
        for bad in ("", "x" * 31, "a\tb", 3):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "name_suffix expects"):
                tune.duplicate_tune(self.work, "ks_alpha", None, suffix=bad)
        self.assertFalse(os.path.exists(self.work))

    def test_an_unknown_source_tune_is_refused(self):
        with self.assertRaisesRegex(ValueError, "ks_alpha has no tune ax_alp09"):
            tune.duplicate_tune(self.work, "ks_alpha", "ax_alp09")
        with self.assertRaises(ValueError):
            tune.duplicate_tune(self.work, "ks_alpha", "../x")
        self.assertFalse(os.path.exists(self.work))

    def test_nothing_is_left_behind_when_validation_fails(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A", "x": 1})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_B"}, "ax_alp01")
        before = self.snapshot()
        for kw in ({"new_id": "ax_alp01"}, {"new_id": "bad"}, {"suffix": "_A"}, {"suffix": ""}, {"src": "ax_alp09"}, {"new_id": "ax_alpha"}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                tune.duplicate_tune(self.work, "ks_alpha", kw.pop("src", None), **kw)
            self.assertEqual(self.snapshot(), before)

    def test_a_failing_save_leaves_no_temp_file(self):
        tune.save_state(self.work, "ks_alpha", {"x": 1})
        before = self.snapshot()
        self.patch(os, "replace", mock.Mock(side_effect=OSError("disk full")))
        with self.assertRaises(OSError):
            tune.duplicate_tune(self.work, "ks_alpha", None)
        self.assertEqual(sorted(self.snapshot()[0]), sorted(before[0]))

    def test_exhausted_ids_fail_before_anything_is_written(self):
        for n in range(1, 100):
            self.install("ax_alp%02d" % n)
        with self.assertRaisesRegex(ValueError, "no free tuned car id left"):
            tune.duplicate_tune(self.work, "ks_alpha", None, mods_dir=self.mods)
        self.assertFalse(os.path.exists(self.work))

    def test_the_state_files_are_written_with_lf_only(self):
        tune.duplicate_tune(self.work, "ks_alpha", None)
        with open(tune.state_path(self.work, "ks_alpha", "ax_alp01"), "rb") as f:
            self.assertNotIn(b"\r", f.read())


class TestNewTuneFromDraft(TuneCase):
    def test_the_first_modded_car_takes_the_default_id(self):
        tune.save_state(self.work, "ks_alpha", {"limiter": 9000}, tune.DRAFT)
        res = tune.new_tune_from_draft(self.work, "ks_alpha")
        self.assertEqual(res, {"id": "ax_alpha", "stock": "ks_alpha", "name_suffix": "MY"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"limiter": 9000, "name_suffix": "MY"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", tune.DRAFT), {"limiter": 9000})
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_alpha", "tunes")))
        self.assertEqual([(t["id"], t["default"]) for t in tune.list_tunes(self.work, "ks_alpha")], [("ax_alpha", True)])

    def test_from_a_legacy_default_suffix_the_draft_gets_the_next_counted_one(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY"})
        tune.save_state(self.work, "ks_alpha", {"limiter": 9000, "name_suffix": "_MY"}, tune.DRAFT)
        res = tune.new_tune_from_draft(self.work, "ks_alpha")
        self.assertEqual(res, {"id": "ax_alp01", "stock": "ks_alpha", "name_suffix": "MY 2"})
        self.assertEqual(tune.new_tune_from_draft(self.work, "ks_alpha")["name_suffix"], "MY 3")

    def test_the_second_one_takes_a_free_id_and_a_counted_suffix(self):
        tune.save_state(self.work, "ks_alpha", {"limiter": 9000}, tune.DRAFT)
        tune.new_tune_from_draft(self.work, "ks_alpha")
        res = tune.new_tune_from_draft(self.work, "ks_alpha")
        self.assertEqual(res, {"id": "ax_alp01", "stock": "ks_alpha", "name_suffix": "MY 2"})
        self.assertEqual(tune.load_state(self.work, "ks_alpha", "ax_alp01"), {"limiter": 9000, "name_suffix": "MY 2"})
        self.assertEqual(tune.new_tune_from_draft(self.work, "ks_alpha")["name_suffix"], "MY 3")

    def test_a_build_of_the_default_id_without_a_state_counts_as_the_default_tune(self):
        self.build("ks_alpha", "ax_alpha")
        self.assertEqual(tune.new_tune_from_draft(self.work, "ks_alpha")["id"], "ax_alp01")

    def test_an_installed_package_of_the_free_ids_is_skipped_when_the_mods_folder_is_given(self):
        tune.new_tune_from_draft(self.work, "ks_alpha", mods_dir=self.mods)
        self.install("ax_alp01")
        self.assertEqual(tune.new_tune_from_draft(self.work, "ks_alpha", mods_dir=self.mods)["id"], "ax_alp02")

    def test_explicit_suffix_and_id_are_passed_on(self):
        res = tune.new_tune_from_draft(self.work, "ks_alpha", suffix="_X", new_id="ax_alp42")
        self.assertEqual(res, {"id": "ax_alp42", "stock": "ks_alpha", "name_suffix": "_X"})
        self.assertEqual(tune.list_tunes(self.work, "ks_alpha")[0]["id"], "ax_alp42")
        self.assertEqual(tune.new_tune_from_draft(self.work, "ks_alpha")["id"], "ax_alpha")

    def test_errors_leave_nothing_behind(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"})
        before = sorted(self.files())
        for kw in ({"suffix": "_A"}, {"suffix": ""}, {"new_id": "ax_alpha"}, {"new_id": "bad"}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                tune.new_tune_from_draft(self.work, "ks_alpha", **kw)
            self.assertEqual(sorted(self.files()), before)

    def test_the_draft_stays_unsaved_state_of_the_base_car(self):
        tune.new_tune_from_draft(self.work, "ks_alpha")
        self.assertEqual(tune.list_modded(self.work, self.mods)[0]["id"], "ax_alpha")
        self.assertEqual(tune.load_state(self.work, "ks_alpha", tune.DRAFT), {})


class TestListModded(TuneCase):
    def info(self, car_id, name):
        self.write(tune.stock_info_path(self.work, car_id), {"car_id": car_id, "display_name": name, "brand": "B", "year": 1})

    def test_nothing_without_tunes(self):
        self.extract("ks_alpha")
        self.write(os.path.join(self.work, "backups", "ax_x.kspkg"), b"p", binary=True)
        self.assertEqual(tune.list_modded(self.work, self.mods), [])
        self.assertEqual(tune.list_modded(str(self.d / "nowhere"), self.mods), [])

    def test_two_stock_cars_sorted_by_label(self):
        self.info("ks_alpha", "Zeta Stock")
        self.info("ks_bravo", "Bravo Stock")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_Z"})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"}, "ax_alp01")
        tune.save_state(self.work, "ks_bravo", {}, "ax_bra01")
        self.build("ks_alpha", "ax_alpha")
        self.build("ks_alpha", "ax_alp01")
        self.install("ax_alp01")
        self.install("ax_bra01")
        self.extract("ks_alpha")
        rows = tune.list_modded(self.work, self.mods)
        self.assertEqual([(r["label"], r["id"], r["stock"], r["name_suffix"], r["default"], r["installed"], r["built"]) for r in rows],
                         [("Bravo Stock MY", "ax_bra01", "ks_bravo", "MY", False, True, False),
                          ("Zeta Stock _A", "ax_alp01", "ks_alpha", "_A", False, True, True),
                          ("Zeta Stock _Z", "ax_alpha", "ks_alpha", "_Z", True, False, True)])
        self.assertEqual(set(rows[0]), {"id", "stock", "label", "name_suffix", "default", "installed", "built"})

    def test_a_legacy_suffix_gives_a_label_with_a_space_and_the_converted_suffix(self):
        self.info("ks_alpha", "Zeta Stock")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY"})
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_MY2"}, "ax_alp01")
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_Drift"}, "ax_alp02")
        rows = tune.list_modded(self.work, self.mods)
        self.assertEqual([(r["id"], r["label"], r["name_suffix"]) for r in rows],
                         [("ax_alp02", "Zeta Stock _Drift", "_Drift"), ("ax_alpha", "Zeta Stock MY", "MY"), ("ax_alp01", "Zeta Stock MY 2", "MY 2")])
        self.assertEqual(tune.load_state(self.work, "ks_alpha"), {"name_suffix": "_MY"})

    def test_a_build_only_default_tune_is_listed_and_built_needs_the_package(self):
        self.build("ks_bravo", "ax_bravo")
        os.makedirs(os.path.join(tune.build_dir(self.work, "ks_alpha"), "ax_alpha"))
        tune.save_state(self.work, "ks_alpha", {})
        rows = {r["id"]: r for r in tune.list_modded(self.work, self.mods)}
        self.assertEqual({k: (v["built"], v["installed"]) for k, v in rows.items()}, {"ax_alpha": (False, False), "ax_bravo": (True, False)})

    def test_label_falls_back_to_the_index_then_the_tested_label_then_the_id(self):
        self.write(tune.cars_index_path(self.work), [{"id": "ks_bravo", "display_name": "Bravo Game"}, {"id": "ks_other", "display_name": "Other Game"}])
        for car_id in ("ks_alpha", "ks_bravo", "ks_other", "ks_zzz"):
            tune.save_state(self.work, car_id, {})
        self.assertEqual({r["stock"]: r["label"] for r in tune.list_modded(self.work, self.mods)},
                         {"ks_alpha": "Alpha MY", "ks_bravo": "Bravo Game MY", "ks_other": "Other Game MY", "ks_zzz": "ks_zzz MY"})

    def test_an_unreadable_stock_info_does_not_break_the_list(self):
        self.info("ks_alpha", "Alpha Stock")
        self.write(tune.stock_info_path(self.work, "ks_bravo"), '{"car_id": "ks_bravo", "disp')
        self.write(tune.stock_info_path(self.work, "ks_other"), {"car_id": "ks_wrong", "display_name": "X", "brand": "B", "year": 1})
        for car_id in ("ks_alpha", "ks_bravo", "ks_other"):
            tune.save_state(self.work, car_id, {})
        self.assertEqual({r["stock"]: r["label"] for r in tune.list_modded(self.work, self.mods)},
                         {"ks_alpha": "Alpha Stock MY", "ks_bravo": "Bravo MY", "ks_other": "ks_other MY"})

    def test_installed_is_the_exact_package_name(self):
        tune.save_state(self.work, "ks_alpha", {})
        self.write(os.path.join(self.mods, "ax_alpha.txt"), b"x", binary=True)
        self.assertFalse(tune.list_modded(self.work, self.mods)[0]["installed"])

    def test_an_unexpandable_mods_folder_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "cannot expand"):
            tune.list_modded(self.work, "%ACE_TEST_NO_SUCH_VAR%" + os.sep + "m")

    def test_the_draft_is_not_a_modded_car(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_D"}, tune.DRAFT)
        self.assertEqual(tune.list_modded(self.work, self.mods), [])

    def test_a_duplicate_shows_up(self):
        tune.save_state(self.work, "ks_alpha", {"name_suffix": "_A"})
        tune.duplicate_tune(self.work, "ks_alpha", None)
        self.assertEqual([(r["id"], r["name_suffix"]) for r in tune.list_modded(self.work, self.mods)],
                         [("ax_alpha", "_A"), ("ax_alp01", "_A 2")])


class TestPerTuneState(CarCase):
    """set / unset / rows / unknown ids on the default tune (tune=None), the draft and a modded car ax01 of the stub car ks_x."""

    def setUp(self):
        super().setUp()
        self.cars(("ks_x", "Car X"))
        self.cat = mini_catalogue(suffix(), limiter())
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)
        tune.save_state(self.work, "ks_x", {"limiter": 8000, "name_suffix": "_D"})
        tune.save_state(self.work, "ks_x", {"limiter": 6000, "name_suffix": "_DR"}, tune.DRAFT)
        tune.save_state(self.work, "ks_x", {"limiter": 9000, "name_suffix": "_M"}, "ax01")

    def states(self):
        return [tune.load_state(self.work, "ks_x", t) for t in (None, tune.DRAFT, "ax01")]

    def test_set_changes_only_the_chosen_tune(self):
        res = tune.set_value(self.work, "ks_x", "limiter", "9500", tune="ax01")
        self.assertEqual(res, {"id": "limiter", "value": 9500, "warnings": []})
        self.assertEqual([s["limiter"] for s in self.states()], [8000, 6000, 9500])
        tune.set_value(self.work, "ks_x", "limiter", "4000", tune=tune.DRAFT)
        self.assertEqual([s["limiter"] for s in self.states()], [8000, 4000, 9500])
        tune.set_value(self.work, "ks_x", "limiter", "7500", tune="ax_x")
        self.assertEqual([s["limiter"] for s in self.states()], [7500, 4000, 9500])
        tune.set_value(self.work, "ks_x", "limiter", "7000")
        self.assertEqual([s["limiter"] for s in self.states()], [7000, 4000, 9500])

    def test_set_with_a_range_warning_and_errors_write_nothing(self):
        self.assertEqual(tune.set_value(self.work, "ks_x", "limiter", "20000", tune="ax01")["warnings"],
                         ["limiter=20000 is outside the suggested range 3000..12000"])
        before = self.states()
        for text, setting in (("fast", "limiter"), ("1", "nope")):
            with self.subTest(setting), self.assertRaises(ValueError):
                tune.set_value(self.work, "ks_x", setting, text, tune="ax01")
        self.assertEqual(self.states(), before)

    def test_unset_removes_from_the_chosen_tune_only(self):
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter", tune="ax01"), {"id": "limiter", "removed": True})
        self.assertEqual(self.states(), [{"limiter": 8000, "name_suffix": "_D"}, {"limiter": 6000, "name_suffix": "_DR"}, {"name_suffix": "_M"}])
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter", tune="ax01"), {"id": "limiter", "removed": False})
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter", tune=tune.DRAFT)["removed"], True)
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000, "name_suffix": "_D"})
        with self.assertRaisesRegex(ValueError, "unknown setting 'nope'"):
            tune.unset_value(self.work, "ks_x", "nope", tune="ax01")

    def test_rows_show_the_values_of_the_chosen_tune(self):
        values = {t: {r["id"]: (r["value"], r["changed"]) for r in tune.effective_rows(self.work, "ks_x", self.cat, tune=t)} for t in (None, tune.DRAFT, "ax01")}
        self.assertEqual([values[t]["limiter"] for t in (None, tune.DRAFT, "ax01")], [(8000, True), (6000, True), (9000, True)])
        self.assertEqual([values[t]["name_suffix"] for t in (None, tune.DRAFT, "ax01")], [("_D", True), ("_DR", True), ("_M", True)])
        row = tune.effective_row(self.work, "ks_x", "limiter", self.cat, tune="ax01")
        self.assertEqual((row["value"], row["default"], row["changed"]), (9000, 7000, True))
        self.assertEqual(tune.effective_row(self.work, "ks_x", "limiter", self.cat)["value"], 8000)
        self.assertEqual(tune.effective_rows(self.work, "ks_x", self.cat, True, "ax01")[0]["value"], "_M")

    def test_a_tune_without_a_state_shows_the_defaults(self):
        rows = {r["id"]: (r["value"], r["changed"]) for r in tune.effective_rows(self.work, "ks_x", self.cat, tune="ax02")}
        self.assertEqual(rows, {"name_suffix": ("MY", False), "limiter": (7000, False)})

    def test_unknown_state_ids_and_their_warning_follow_the_tune(self):
        tune.save_state(self.work, "ks_x", {"old_m": 1}, "ax01")
        tune.save_state(self.work, "ks_x", {"old_d": 1})
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat, "ax01"), ["old_m"])
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat), ["old_d"])
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat, tune.DRAFT), [])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x", self.cat, "ax01")
        self.assertEqual(err.getvalue(), "warning: ignoring unknown setting 'old_m' in the saved state\n")

    def test_the_tune_is_an_optional_trailing_keyword_after_the_old_arguments(self):
        for fn, args in ((tune.set_value, ("ks_x", "limiter", "7000", self.cat)), (tune.unset_value, ("ks_x", "limiter", self.cat)),
                         (tune.unknown_state_ids, ("ks_x", self.cat)), (tune.warn_unknown_state, ("ks_x", self.cat)),
                         (tune.effective_row, ("ks_x", "limiter", self.cat))):
            with self.subTest(fn.__name__), contextlib.redirect_stderr(io.StringIO()):
                fn(self.work, *args, tune=None)
                fn(self.work, *args)
        self.assertEqual(len(tune.effective_rows(self.work, "ks_x", self.cat, False, None)), 2)

    def test_invalid_tune_ids_are_refused_by_every_function_and_write_nothing(self):
        before = self.states()
        calls = (lambda t: tune.set_value(self.work, "ks_x", "limiter", "7000", self.cat, t), lambda t: tune.unset_value(self.work, "ks_x", "limiter", self.cat, t),
                 lambda t: tune.unknown_state_ids(self.work, "ks_x", self.cat, t), lambda t: tune.warn_unknown_state(self.work, "ks_x", self.cat, t),
                 lambda t: tune.effective_rows(self.work, "ks_x", self.cat, tune=t), lambda t: tune.effective_row(self.work, "ks_x", "limiter", self.cat, t))
        for bad in ("ax1", "AX01", "ax0!", "..", "ax/1", "ks_x", "", 5):
            for call in calls:
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    call(bad)
        self.assertEqual(self.states(), before)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "ks_x", "tunes"))), ["ax01"])

    def test_the_default_tune_files_stay_where_they_were(self):
        tune.set_value(self.work, "ks_x", "limiter", "7100", tune="ax_x")
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(self.work, "ks_x")) if f.endswith(".json")), ["draft_state.json", "tune_state.json"])


# --------------------------------------------------------------------------------------------- versions
class TestVersions(CarCase):
    """Versions of the default tune (ax_x) and of the modded car ax01 of the stub car ks_x."""

    def setUp(self):
        super().setUp()
        self.cars(("ks_x", "Car X"))
        self.stock_info()
        self.patch(tune, "load_cars_index", lambda work, game=None: None)
        self.cat = mini_catalogue(*metas(), limiter(), mini_setting("m", type="int", targets=[("@engine", "minimum")]))
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)
        tune.save_state(self.work, "ks_x", {"limiter": 8000, "name_suffix": "Base"})
        tune.save_state(self.work, "ks_x", {"limiter": 9000, "name_suffix": "Mine", "m": 700}, "ax01")

    def main(self, *argv):
        return self.run_main(*argv, "--work", self.work)

    def vpath(self, *parts, tune_id=None):
        base = os.path.join(self.work, "ks_x") if tune_id is None else os.path.join(self.work, "ks_x", "tunes", tune_id)
        return os.path.join(base, "versions", *parts)

    def values(self, version, tune_id=None, hidden=False):
        return {r["id"]: (r["value"], r["changed"]) for r in tune.effective_rows(self.work, "ks_x", self.cat, hidden, tune_id, version)}

    def test_a_tune_without_versions_lists_none_and_writes_nothing(self):
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [])
        self.assertEqual(tune.list_versions(self.work, "ks_x", "ax01"), [])
        self.assertFalse(os.path.exists(self.vpath()))

    def test_added_versions_get_the_next_free_ids_and_are_listed_by_id(self):
        self.assertEqual(tune.add_version(self.work, "ks_x", "Drift"), "v01")
        self.assertEqual(tune.add_version(self.work, "ks_x", "Grip"), "v02")
        self.assertEqual(tune.add_version(self.work, "ks_x", "Other car", "ax01"), "v01")
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [{"id": "v01", "name": "Drift", "locked": False, "built": None}, {"id": "v02", "name": "Grip", "locked": False, "built": None}])
        self.assertEqual(tune.list_versions(self.work, "ks_x", "ax_x"), tune.list_versions(self.work, "ks_x"))
        self.assertEqual(tune.list_versions(self.work, "ks_x", "ax01"), [{"id": "v01", "name": "Other car", "locked": False, "built": None}])
        self.assertEqual(tune.read_json(self.vpath("v01", "meta.json")), {"name": "Drift"})

    def test_a_gap_in_the_ids_is_filled_first_and_the_last_id_is_v99(self):
        for name in ("A", "B", "C"):
            tune.add_version(self.work, "ks_x", name)
        shutil.rmtree(self.vpath("v02"))
        self.assertEqual(tune.add_version(self.work, "ks_x", "D"), "v02")
        for n in range(4, 100):
            os.makedirs(self.vpath("v%02d" % n))
        with self.assertRaisesRegex(ValueError, "no free version id left for ax_x"):
            tune.add_version(self.work, "ks_x", "E")

    def test_a_version_copies_the_base_state_without_the_meta_settings(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000, "name_suffix": "Base", "_turbo": {"donor": "ks_y"}, "_tyres": ["own:t"]})
        tune.add_version(self.work, "ks_x", "Drift")
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01"), {"limiter": 8000, "_turbo": {"donor": "ks_y"}, "_tyres": ["own:t"]})
        self.assertEqual(tune.load_state(self.work, "ks_x")["name_suffix"], "Base")

    def test_a_version_can_copy_another_version_instead_of_the_base(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v01")
        self.assertEqual(tune.add_version(self.work, "ks_x", "Copy", source="v01"), "v02")
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v02"), {"limiter": 6500})
        with self.assertRaisesRegex(ValueError, "ks_x has no version v07 of ax_x"):
            tune.add_version(self.work, "ks_x", "Nope", source="v07")
        self.assertEqual([v["id"] for v in tune.list_versions(self.work, "ks_x")], ["v01", "v02"])

    def test_names_are_trimmed_and_must_be_1_to_40_characters_without_control_characters(self):
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [])
        tune.add_version(self.work, "ks_x", "  Drift  ")
        tune.add_version(self.work, "ks_x", "x" * 40)
        self.assertEqual([v["name"] for v in tune.list_versions(self.work, "ks_x")], ["Drift", "x" * 40])
        for bad in ("", "   ", "x" * 41, "a\tb", "a\x7fb", "a\x00b", "\x1f", None, 5):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "a version name must be 1 to 40 characters"):
                tune.add_version(self.work, "ks_x", bad)
        self.assertEqual(len(tune.list_versions(self.work, "ks_x")), 2)

    def test_names_are_unique_per_tune_ignoring_case(self):
        tune.add_version(self.work, "ks_x", "Drift")
        for again in ("Drift", "DRIFT", " drift "):
            with self.subTest(again), self.assertRaisesRegex(ValueError, "version name .* is already used by v01"):
                tune.add_version(self.work, "ks_x", again)
        self.assertEqual(tune.add_version(self.work, "ks_x", "Drift", "ax01"), "v01")
        self.assertEqual(len(tune.list_versions(self.work, "ks_x")), 1)

    def test_rename_changes_only_the_name_with_the_same_rules(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.add_version(self.work, "ks_x", "Grip")
        state = tune.read_version_state(self.work, "ks_x", "v02")
        self.assertEqual(tune.rename_version(self.work, "ks_x", "v02", "  Wet grip "), "Wet grip")
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [{"id": "v01", "name": "Drift", "locked": False, "built": None}, {"id": "v02", "name": "Wet grip", "locked": False, "built": None}])
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v02"), state)
        self.assertEqual(tune.rename_version(self.work, "ks_x", "v01", "DRIFT"), "DRIFT")
        with self.assertRaisesRegex(ValueError, "already used by v01"):
            tune.rename_version(self.work, "ks_x", "v02", "drift")
        for bad in ("", "x" * 41, "a\nb"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "a version name must be"):
                tune.rename_version(self.work, "ks_x", "v02", bad)
        with self.assertRaisesRegex(ValueError, "ks_x has no version v05 of ax_x"):
            tune.rename_version(self.work, "ks_x", "v05", "Name")
        self.assertEqual([v["name"] for v in tune.list_versions(self.work, "ks_x")], ["DRIFT", "Wet grip"])

    def test_the_draft_and_unknown_tunes_have_no_versions(self):
        for call in (lambda: tune.list_versions(self.work, "ks_x", tune.DRAFT), lambda: tune.add_version(self.work, "ks_x", "A", tune.DRAFT),
                     lambda: tune.rename_version(self.work, "ks_x", "v01", "A", tune.DRAFT), lambda: tune.load_version_state(self.work, "ks_x", "v01", tune.DRAFT),
                     lambda: tune.effective_rows(self.work, "ks_x", self.cat, tune=tune.DRAFT, version="v01"),
                     lambda: tune.set_value(self.work, "ks_x", "limiter", "7000", tune=tune.DRAFT, version="v01")):
            with self.assertRaisesRegex(ValueError, "the draft has no versions"):
                call()
        with self.assertRaisesRegex(ValueError, "ks_x has no tune ax02"):
            tune.add_version(self.work, "ks_x", "A", "ax02")
        for bad in ("ax1", "ks_x", 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tune.list_versions(self.work, "ks_x", bad)
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "draft_state.json")))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tunes", "ax02")))

    def test_version_ids_must_be_v01_to_v99(self):
        for bad in ("v00", "v1", "v100", "V01", "x01", "../v01", "", 1, None):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "version id must be v01 .. v99"):
                tune.read_version_state(self.work, "ks_x", bad)
        os.makedirs(self.vpath("v00"))
        tune.save_json(self.vpath("v00", "tune_state.json"), {})
        tune.add_version(self.work, "ks_x", "A")
        self.assertEqual([v["id"] for v in tune.list_versions(self.work, "ks_x")], ["v01"])

    def test_an_unknown_version_is_an_error_and_loads_nothing(self):
        for call in (lambda: tune.load_version_state(self.work, "ks_x", "v01"), lambda: tune.effective_rows(self.work, "ks_x", self.cat, version="v01"),
                     lambda: tune.set_value(self.work, "ks_x", "limiter", "7000", version="v01"),
                     lambda: tune.unset_value(self.work, "ks_x", "limiter", version="v01"),
                     lambda: tune.unknown_state_ids(self.work, "ks_x", self.cat, version="v01")):
            with self.assertRaisesRegex(ValueError, "ks_x has no version v01 of ax_x"):
                call()
        self.assertFalse(os.path.exists(self.vpath()))

    def test_the_values_of_a_version_come_from_its_state_and_the_meta_settings_from_the_base(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.save_version_state(self.work, "ks_x", {"limiter": 6500, "name_suffix": "Ignored", "variant_name": "Ignored"}, "v01")
        self.assertEqual(tune.load_version_state(self.work, "ks_x", "v01"), {"limiter": 6500, "name_suffix": "Base"})
        version = self.values("v01")
        self.assertEqual((version["limiter"], version["name_suffix"]), ((6500, True), ("Base", True)))
        self.assertEqual(self.values(None)["limiter"], (8000, True))
        row = tune.effective_row(self.work, "ks_x", "limiter", self.cat, version="v01")
        self.assertEqual((row["value"], row["default"], row["changed"]), (6500, 7000, True))
        self.assertEqual(tune.effective_row(self.work, "ks_x", "limiter", self.cat)["value"], 8000)

    def test_a_version_has_its_own_complete_state_so_unset_settings_show_the_default(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000, "m": 700})
        tune.add_version(self.work, "ks_x", "Drift")
        tune.unset_value(self.work, "ks_x", "m", version="v01")
        self.assertEqual(self.values("v01")["m"], (800, False))
        self.assertEqual(self.values(None)["m"], (700, True))

    def test_the_base_meta_setting_changes_show_in_every_version(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.set_value(self.work, "ks_x", "name_suffix", "Renamed")
        self.assertEqual(self.values("v01")["name_suffix"], ("Renamed", True))
        tune.add_version(self.work, "ks_x", "Own", "ax01")
        self.assertEqual(self.values("v01", "ax01")["name_suffix"], ("Mine", True))
        self.assertEqual(self.values("v01", "ax01")["limiter"], (9000, True))

    def test_the_defaults_of_a_version_are_those_of_the_tune(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.assertEqual([r["default"] for r in tune.resolve_defaults(self.work, "ks_x", self.cat, hidden=True, tune="ax_x", version="v01")],
                         [r["default"] for r in tune.resolve_defaults(self.work, "ks_x", self.cat, hidden=True, tune="ax_x")])
        self.assertEqual([r["default"] for r in tune.resolve_defaults(self.work, "ks_x", self.cat, hidden=True, version="v01")],
                         [r["default"] for r in tune.resolve_defaults(self.work, "ks_x", self.cat, hidden=True)])
        with self.assertRaisesRegex(ValueError, "a version cannot be combined with a variant"):
            tune.resolve_defaults(self.work, "ks_x", self.cat, version="v01", variant="q_drift")

    def test_changed_settings_and_unknown_ids_follow_the_version(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v01")
        rows, changed = tune.changed_settings(self.work, "ks_x", "ax_x", self.cat, version="v01")
        self.assertEqual([(s["id"], r["value"]) for s, r in changed], [("name_suffix", "Base"), ("limiter", 6500)])
        self.assertEqual([(s["id"], r["value"]) for s, r in tune.changed_settings(self.work, "ks_x", "ax_x", self.cat)[1]], [("name_suffix", "Base"), ("limiter", 8000)])
        tune.save_version_state(self.work, "ks_x", {"old": 1, "_turbo": {"donor": "ks_y"}}, "v01")
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat, version="v01"), ["old"])
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat), [])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x", self.cat, version="v01")
        self.assertEqual(err.getvalue(), "warning: ignoring unknown setting 'old' in the saved state\n")

    def test_set_and_unset_with_a_version_write_only_that_versions_state(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.add_version(self.work, "ks_x", "Grip")
        tune.add_version(self.work, "ks_x", "Other", "ax01")
        before = (tune.load_state(self.work, "ks_x"), tune.load_state(self.work, "ks_x", "ax01"), tune.read_version_state(self.work, "ks_x", "v02"),
                  tune.read_version_state(self.work, "ks_x", "v01", "ax01"))
        res = tune.set_value(self.work, "ks_x", "limiter", "6500", version="v01")
        self.assertEqual(res, {"id": "limiter", "value": 6500, "warnings": []})
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01")["limiter"], 6500)
        self.assertEqual((tune.load_state(self.work, "ks_x"), tune.load_state(self.work, "ks_x", "ax01"), tune.read_version_state(self.work, "ks_x", "v02"),
                          tune.read_version_state(self.work, "ks_x", "v01", "ax01")), before)
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter", version="v01"), {"id": "limiter", "removed": True})
        self.assertEqual(tune.unset_value(self.work, "ks_x", "limiter", version="v01"), {"id": "limiter", "removed": False})
        self.assertNotIn("limiter", tune.read_version_state(self.work, "ks_x", "v01"))
        tune.set_value(self.work, "ks_x", "limiter", "6100", tune="ax01", version="v01")
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01", "ax01")["limiter"], 6100)
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax01")["limiter"], 9000)
        self.assertEqual(tune.load_state(self.work, "ks_x")["limiter"], 8000)

    def test_a_version_set_with_a_range_warning_or_a_bad_value_changes_nothing_more(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.assertEqual(tune.set_value(self.work, "ks_x", "limiter", "20000", version="v01")["warnings"],
                         ["limiter=20000 is outside the suggested range 3000..12000"])
        before = tune.read_version_state(self.work, "ks_x", "v01")
        for setting, text in (("limiter", "fast"), ("nope", "1")):
            with self.subTest(setting), self.assertRaises(ValueError):
                tune.set_value(self.work, "ks_x", setting, text, version="v01")
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01"), before)

    def test_meta_settings_are_refused_for_a_version_in_set_and_unset(self):
        tune.add_version(self.work, "ks_x", "Drift")
        before = (tune.read_version_state(self.work, "ks_x", "v01"), tune.load_state(self.work, "ks_x"))
        for fn, args in ((tune.set_value, ("name_suffix", "Other")), (tune.set_value, ("variant_name", "V")), (tune.unset_value, ("name_suffix",)),
                         (tune.unset_value, ("variant_name",))):
            with self.subTest(fn.__name__, args=args), self.assertRaisesRegex(ValueError, "^%s is shared by all versions, set it on the base$" % args[0]):
                fn(self.work, "ks_x", *args, version="v01")
        self.assertEqual((tune.read_version_state(self.work, "ks_x", "v01"), tune.load_state(self.work, "ks_x")), before)
        tune.set_value(self.work, "ks_x", "name_suffix", "Other")
        self.assertEqual(tune.load_state(self.work, "ks_x")["name_suffix"], "Other")

    def test_root_for_takes_the_turbo_kit_of_the_versions_own_state(self):
        calls = []
        self.patch(tune, "kit_root", lambda work, car_id, donor: calls.append(donor) or "KIT_" + donor)
        tune.save_state(self.work, "ks_x", {"_turbo": {"donor": "ks_a"}})
        tune.add_version(self.work, "ks_x", "Drift")
        self.assertEqual(tune.root_for(self.work, "ks_x", None), "KIT_ks_a")
        self.assertEqual(tune.root_for(self.work, "ks_x", None, "v01"), "KIT_ks_a")
        tune.save_version_state(self.work, "ks_x", {"_turbo": {"donor": "ks_b"}}, "v01")
        self.assertEqual(tune.root_for(self.work, "ks_x", "ax_x", "v01"), "KIT_ks_b")
        tune.save_version_state(self.work, "ks_x", {"limiter": 7000}, "v01")
        self.assertEqual(tune.root_for(self.work, "ks_x", "ax_x", "v01"), tune.base_dir(self.work, "ks_x"))
        self.assertEqual(tune.root_for(self.work, "ks_x", "ax_x"), "KIT_ks_a")
        tune.save_version_state(self.work, "ks_x", {"_turbo": "broken"}, "v01")
        with self.assertRaisesRegex(ValueError, "damaged turbo kit"):
            tune.root_for(self.work, "ks_x", None, "v01")
        self.assertEqual(calls, ["ks_a", "ks_a", "ks_b", "ks_a"])

    def test_resolve_defaults_reads_the_kit_root_of_the_version(self):
        donors = []
        self.patch(tune, "kit_root", lambda work, car_id, donor: donors.append(donor) or tune.base_dir(work, car_id))
        tune.save_state(self.work, "ks_x", {"_turbo": {"donor": "ks_a"}})
        tune.add_version(self.work, "ks_x", "Drift")
        tune.save_version_state(self.work, "ks_x", {"_turbo": {"donor": "ks_b"}}, "v01")
        tune.resolve_defaults(self.work, "ks_x", self.cat, tune="ax_x", version="v01")
        tune.resolve_defaults(self.work, "ks_x", self.cat, tune="ax_x")
        tune.resolve_defaults(self.work, "ks_x", self.cat, version="v01")
        self.assertEqual(donors, ["ks_b", "ks_a", "ks_b"])

    def test_the_version_is_an_optional_trailing_keyword_after_the_old_arguments(self):
        for fn, args in ((tune.set_value, ("ks_x", "limiter", "7000", self.cat)), (tune.unset_value, ("ks_x", "limiter", self.cat)),
                         (tune.unknown_state_ids, ("ks_x", self.cat)), (tune.warn_unknown_state, ("ks_x", self.cat)),
                         (tune.effective_row, ("ks_x", "limiter", self.cat)), (tune.root_for, ("ks_x",))):
            with self.subTest(fn.__name__), contextlib.redirect_stderr(io.StringIO()):
                fn(self.work, *args, version=None)
                fn(self.work, *args)

    def test_versions_do_not_make_a_tune_or_a_car_folder_appear(self):
        tune.add_version(self.work, "ks_x", "Drift", "ax01")
        tune.add_version(self.work, "ks_x", "Drift")
        self.assertEqual([t["id"] for t in tune.list_tunes(self.work, "ks_x")], ["ax_x", "ax01"])
        self.assertEqual(tune.car_folders(self.work), ["ks_x"])
        self.assertNotIn("versions", tune.known_tune_ids(self.work))

    # ---------------------------------------------------------------------------- command line
    def test_versions_prints_the_base_and_every_version(self):
        self.assertEqual(self.main("versions"), (0, "base\n", ""))
        tune.add_version(self.work, "ks_x", "Drift")
        tune.add_version(self.work, "ks_x", "Wet grip")
        tune.add_version(self.work, "ks_x", "Own", "ax01")
        self.assertEqual(self.main("versions"), (0, "base\nv01: Drift\nv02: Wet grip\n", ""))
        self.assertEqual(self.main("versions", "--tune", "ax01"), (0, "base\nv01: Own\n", ""))
        self.assertEqual(self.main("versions", "--tune", "ax_x", "--car", "ks_x"), (0, "base\nv01: Drift\nv02: Wet grip\n", ""))

    def test_version_add_and_rename_print_the_id_and_the_name(self):
        self.assertEqual(self.main("version-add", " Drift "), (0, "car: ks_x, new version: v01\n", ""))
        self.assertEqual(self.main("version-add", "Copy", "--from", "v01", "--tune", "ax01")[::2], (1, "error: ks_x has no version v01 of ax01\n"))
        self.assertEqual(self.main("version-add", "Copy", "--from", "v01"), (0, "car: ks_x, new version: v02\n", ""))
        self.assertEqual(self.main("version-rename", "v02", "Wet grip"), (0, "v02: Wet grip\n", ""))
        self.assertEqual(self.main("versions"), (0, "base\nv01: Drift\nv02: Wet grip\n", ""))
        self.assertEqual(self.main("version-add", "ax", "--tune", "ax01"), (0, "car: ks_x, new version: v01\n", ""))

    def test_version_commands_report_runtime_errors_on_stderr_with_exit_1(self):
        tune.add_version(self.work, "ks_x", "Drift")
        for argv, text in ((("version-add", "drift"), "error: version name drift is already used by v01\n"),
                           (("version-add", "x" * 41), "error: a version name must be 1 to 40 characters without control characters\n"),
                           (("version-rename", "v09", "A"), "error: ks_x has no version v09 of ax_x\n"),
                           (("version-rename", "v1", "A"), "error: version id must be v01 .. v99, got 'v1'\n"),
                           (("versions", "--tune", "ax99"), "error: ks_x has no tune ax99\n"),
                           (("version-add", "A", "--tune", "ax99"), "error: ks_x has no tune ax99\n")):
            with self.subTest(argv):
                self.assertEqual(self.main(*argv)[::2], (1, text))

    # ---------------------------------------------------------------------------- locking
    def keep(self, version, tune_id=None, **over):
        """A kept build for the version made from its state as it is now (build/files/data/a.bin and build/build.json); over replaces keys of build.json."""
        folder = self.vpath(version, "build", tune_id=tune_id)
        self.write(os.path.join(folder, "files", "data", "a.bin"), b"A", binary=True)
        record = {"tune": tune_id or "ax_x", "preset": "content\\cars\\ax_x\\presets\\p_v01.mechanicalcarpreset", "sound_part": None, "files": ["data/a.bin"],
                  "time": "2026-11-23T10:00:00Z", "state": tune.read_version_state(self.work, "ks_x", version, tune_id)}
        record.update(over)
        self.write(os.path.join(folder, "build.json"), record)
        return record

    def lock(self, name="Drift", tune_id=None):
        v = tune.add_version(self.work, "ks_x", name, tune_id)
        self.keep(v, tune_id)
        tune.lock_version(self.work, "ks_x", v, tune_id)
        return v

    def tree(self, folder):
        found = {}
        for dp, _, names in os.walk(folder):
            for n in names:
                with open(os.path.join(dp, n), "rb") as f:
                    found[os.path.relpath(os.path.join(dp, n), folder)] = f.read()
        return found

    def test_list_versions_tells_locked_and_the_time_of_the_kept_build(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.add_version(self.work, "ks_x", "Grip")
        tune.add_version(self.work, "ks_x", "Wet")
        self.keep("v02")
        self.keep("v03")
        tune.lock_version(self.work, "ks_x", "v03")
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [{"id": "v01", "name": "Drift", "locked": False, "built": None},
                                                                 {"id": "v02", "name": "Grip", "locked": False, "built": "2026-11-23T10:00:00Z"},
                                                                 {"id": "v03", "name": "Wet", "locked": True, "built": "2026-11-23T10:00:00Z"}])

    def test_locked_is_true_only_for_exactly_true_in_a_meta_json_object(self):
        for n in range(1, 7):
            tune.add_version(self.work, "ks_x", "V%d" % n)
        for v, meta in (("v01", {"name": "A", "locked": True}), ("v02", {"name": "B", "locked": 1}), ("v03", {"name": "C", "locked": "true"}),
                        ("v04", {"name": "D", "locked": False}), ("v05", "{not json"), ("v06", [True])):
            self.write(self.vpath(v, "meta.json"), meta)
        self.assertEqual([(v["name"], v["locked"]) for v in tune.list_versions(self.work, "ks_x")],
                         [("A", True), ("B", False), ("C", False), ("D", False), ("v05", False), ("v06", False)])

    def test_built_is_the_time_of_a_valid_kept_build_of_this_tune_only(self):
        tune.add_version(self.work, "ks_x", "Drift")
        record = self.keep("v01")
        self.assertEqual(tune.kept_build(self.work, "ks_x", "v01"), record)
        self.assertEqual(tune.kept_build(self.work, "ks_x", "v01", "ax_x"), record)
        tune.add_version(self.work, "ks_x", "Other", "ax01")
        self.keep("v01", "ax01", tune="ax_x")
        self.assertIsNone(tune.kept_build(self.work, "ks_x", "v01", "ax01"))
        self.assertEqual(tune.list_versions(self.work, "ks_x", "ax01")[0]["built"], None)

    def test_a_kept_build_that_is_damaged_is_none(self):
        tune.add_version(self.work, "ks_x", "Drift")
        build = self.vpath("v01", "build", "build.json")
        good = self.keep("v01")
        bad = [("files", []), ("files", "data/a.bin"), ("files", [5]), ("files", ["data/missing.bin"]), ("files", ["../x"]), ("files", ["data//a.bin"]),
               ("files", ["/data/a.bin"]), ("preset", ""), ("preset", None), ("sound_part", ""), ("sound_part", 5), ("time", None), ("time", 5),
               ("state", []), ("state", None), ("tune", "ax01"), ("tune", None)]
        for key, value in bad:
            with self.subTest(key=key, value=value):
                self.write(build, dict(good, **{key: value}))
                self.assertIsNone(tune.kept_build(self.work, "ks_x", "v01"))
                self.assertEqual(tune.list_versions(self.work, "ks_x")[0]["built"], None)
        for key in ("files", "preset", "sound_part", "time", "state", "tune"):
            with self.subTest(missing=key):
                self.write(build, {k: v for k, v in good.items() if k != key})
                self.assertIsNone(tune.kept_build(self.work, "ks_x", "v01"))
        for text in ("{not json", "[]", "null", ""):
            with self.subTest(text=text):
                self.write(build, text)
                self.assertIsNone(tune.kept_build(self.work, "ks_x", "v01"))
        self.write(build, dict(good, sound_part="content\\cars\\ax_x\\presets\\parts\\physics\\ax_x_v01_sound.compatiblepart"))
        self.assertIsNotNone(tune.kept_build(self.work, "ks_x", "v01"))
        os.remove(build)
        self.assertIsNone(tune.kept_build(self.work, "ks_x", "v01"))

    def test_lock_needs_a_kept_build(self):
        tune.add_version(self.work, "ks_x", "Drift")
        with self.assertRaisesRegex(ValueError, r"^version v01 \(Drift\) has no kept build: Apply first, then lock it$"):
            tune.lock_version(self.work, "ks_x", "v01")
        self.keep("v01", files=[])
        with self.assertRaisesRegex(ValueError, "has no kept build"):
            tune.lock_version(self.work, "ks_x", "v01")
        self.assertEqual(tune.read_json(self.vpath("v01", "meta.json")), {"name": "Drift"})

    def test_lock_needs_a_kept_build_of_the_state_the_version_has_now(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.keep("v01")
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v01")
        with self.assertRaisesRegex(ValueError, r"^version v01 \(Drift\) has changes that are not built yet: Apply first, then lock it$"):
            tune.lock_version(self.work, "ks_x", "v01")
        self.assertEqual(tune.read_json(self.vpath("v01", "meta.json")), {"name": "Drift"})
        self.keep("v01")
        self.assertEqual(tune.lock_version(self.work, "ks_x", "v01"), "Drift")

    def test_lock_and_unlock_keep_the_name_and_every_other_key_of_the_meta(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.keep("v01")
        self.write(self.vpath("v01", "meta.json"), {"name": "Drift", "extra": [1]})
        tune.lock_version(self.work, "ks_x", "v01")
        self.assertEqual(tune.read_json(self.vpath("v01", "meta.json")), {"name": "Drift", "extra": [1], "locked": True})
        self.assertEqual(tune.list_versions(self.work, "ks_x")[0]["name"], "Drift")
        self.assertEqual(tune.unlock_version(self.work, "ks_x", "v01"), "Drift")
        self.assertEqual(tune.read_json(self.vpath("v01", "meta.json")), {"name": "Drift", "extra": [1]})
        self.assertFalse(tune.list_versions(self.work, "ks_x")[0]["locked"])

    def test_locking_a_locked_version_and_unlocking_an_unlocked_one_are_fine(self):
        v = self.lock()
        self.assertEqual(tune.lock_version(self.work, "ks_x", v), "Drift")
        self.assertTrue(tune.list_versions(self.work, "ks_x")[0]["locked"])
        tune.unlock_version(self.work, "ks_x", v)
        self.assertEqual(tune.unlock_version(self.work, "ks_x", v), "Drift")
        self.assertEqual(tune.read_json(self.vpath(v, "meta.json")), {"name": "Drift"})

    def test_lock_and_unlock_touch_neither_the_kept_build_nor_the_snapshot(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.keep("v01")
        self.write(self.vpath("v01", "snapshot.json"), {"version": 1})
        before = self.tree(self.vpath("v01"))
        before.pop("meta.json")
        tune.lock_version(self.work, "ks_x", "v01")
        locked = self.tree(self.vpath("v01"))
        self.assertEqual(locked.pop("meta.json"), json.dumps({"name": "Drift", "locked": True}, indent=2).encode() + b"\n")
        self.assertEqual(locked, before)
        tune.unlock_version(self.work, "ks_x", "v01")
        self.assertEqual({k: v for k, v in self.tree(self.vpath("v01")).items() if k != "meta.json"}, before)

    def test_lock_and_unlock_of_an_unknown_version_and_of_the_draft_are_errors(self):
        for call in (tune.lock_version, tune.unlock_version):
            with self.subTest(call.__name__):
                with self.assertRaisesRegex(ValueError, "ks_x has no version v05 of ax_x"):
                    call(self.work, "ks_x", "v05")
                with self.assertRaisesRegex(ValueError, "version id must be v01 .. v99"):
                    call(self.work, "ks_x", "v1")
                with self.assertRaisesRegex(ValueError, "the draft has no versions"):
                    call(self.work, "ks_x", "v01", tune.DRAFT)
        self.assertFalse(os.path.exists(self.vpath()))

    def test_lock_works_per_tune(self):
        v = self.lock("Own", "ax01")
        self.assertEqual(tune.list_versions(self.work, "ks_x", "ax01")[0]["locked"], True)
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [])
        self.assertEqual(tune.read_json(self.vpath(v, "meta.json", tune_id="ax01")), {"name": "Own", "locked": True})

    MESSAGE = r"^version v01 \(Drift\) is locked; unlock it to change it$"

    def test_a_locked_version_refuses_every_change_of_its_state_and_keeps_it(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v01")
        self.keep("v01")
        tune.lock_version(self.work, "ks_x", "v01")
        before = self.tree(self.vpath("v01"))
        for call in (lambda: tune.set_value(self.work, "ks_x", "limiter", "7500", version="v01"),
                     lambda: tune.set_value(self.work, "ks_x", "m", "700", version="v01"),
                     lambda: tune.unset_value(self.work, "ks_x", "limiter", version="v01"),
                     lambda: tune.save_version_state(self.work, "ks_x", {}, "v01"),
                     lambda: tune.save_tune_state(self.work, "ks_x", {}, version="v01"),
                     lambda: tune.rename_version(self.work, "ks_x", "v01", "Other")):
            with self.assertRaisesRegex(ValueError, self.MESSAGE):
                call()
        self.assertEqual(self.tree(self.vpath("v01")), before)
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01"), {"limiter": 6500})

    def test_the_message_names_the_version_by_its_id_when_the_name_is_unknown(self):
        v = self.lock()
        self.write(self.vpath(v, "meta.json"), {"locked": True})
        with self.assertRaisesRegex(ValueError, r"^version v01 \(v01\) is locked; unlock it to change it$"):
            tune.set_value(self.work, "ks_x", "limiter", "7500", version=v)

    def test_an_unlocked_version_and_the_base_stay_editable_and_unlocking_allows_changes_again(self):
        v = self.lock()
        tune.add_version(self.work, "ks_x", "Grip")
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v02")
        tune.set_value(self.work, "ks_x", "limiter", "6600")
        tune.unlock_version(self.work, "ks_x", v)
        tune.set_value(self.work, "ks_x", "limiter", "6700", version=v)
        self.assertEqual(tune.rename_version(self.work, "ks_x", v, "Renamed"), "Renamed")
        self.assertEqual(tune.read_version_state(self.work, "ks_x", v)["limiter"], 6700)

    def test_a_rename_keeps_the_other_keys_of_the_meta(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.write(self.vpath("v01", "meta.json"), {"name": "Drift", "extra": 1, "locked": False})
        tune.rename_version(self.work, "ks_x", "v01", "Grip")
        self.assertEqual(tune.read_json(self.vpath("v01", "meta.json")), {"name": "Grip", "extra": 1, "locked": False})

    def test_a_new_version_from_a_locked_one_is_a_new_unlocked_copy(self):
        v = self.lock()
        before = self.tree(self.vpath(v))
        self.assertEqual(tune.add_version(self.work, "ks_x", "Copy", source=v), "v02")
        self.assertEqual(tune.read_json(self.vpath("v02", "meta.json")), {"name": "Copy"})
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v02"), tune.read_version_state(self.work, "ks_x", v))
        self.assertEqual(self.tree(self.vpath("v02")).keys(), {"meta.json", "tune_state.json"})
        self.assertEqual([(x["id"], x["locked"], x["built"]) for x in tune.list_versions(self.work, "ks_x")], [("v01", True, "2026-11-23T10:00:00Z"), ("v02", False, None)])
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v02")
        self.assertEqual(self.tree(self.vpath(v)), before)

    # ---------------------------------------------------------------------------- locking: command line
    def test_versions_prints_a_locked_version_with_the_word_locked(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.lock("Grip")
        self.assertEqual(self.main("versions"), (0, "base\nv01: Drift\nv02: Grip (locked)\n", ""))

    def test_version_lock_and_unlock_print_the_id_and_the_name(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.keep("v01")
        self.assertEqual(self.main("version-lock", "v01"), (0, "locked v01 (Drift)\n", ""))
        self.assertEqual(self.main("version-lock", "v01", "--car", "ks_x", "--tune", "ax_x"), (0, "locked v01 (Drift)\n", ""))
        self.assertEqual(self.main("versions"), (0, "base\nv01: Drift (locked)\n", ""))
        self.assertEqual(self.main("version-unlock", "v01"), (0, "unlocked v01 (Drift)\n", ""))
        self.assertEqual(self.main("version-unlock", "v01", "--tune", "ax_x"), (0, "unlocked v01 (Drift)\n", ""))
        self.assertEqual(self.main("versions"), (0, "base\nv01: Drift\n", ""))
        tune.add_version(self.work, "ks_x", "Own", "ax01")
        self.keep("v01", "ax01")
        self.assertEqual(self.main("version-lock", "v01", "--tune", "ax01"), (0, "locked v01 (Own)\n", ""))
        self.assertEqual(self.main("versions"), (0, "base\nv01: Drift\n", ""))
        self.assertEqual(self.main("versions", "--tune", "ax01"), (0, "base\nv01: Own (locked)\n", ""))

    def test_version_lock_and_unlock_report_runtime_errors_on_stderr_with_exit_1(self):
        tune.add_version(self.work, "ks_x", "Drift")
        for argv, text in ((("version-lock", "v01"), "error: version v01 (Drift) has no kept build: Apply first, then lock it\n"),
                           (("version-lock", "v09"), "error: ks_x has no version v09 of ax_x\n"),
                           (("version-unlock", "v09"), "error: ks_x has no version v09 of ax_x\n"),
                           (("version-lock", "v1"), "error: version id must be v01 .. v99, got 'v1'\n"),
                           (("version-lock", "v01", "--tune", "ax99"), "error: ks_x has no tune ax99\n"),
                           (("version-unlock", "v01", "--tune", "ax99"), "error: ks_x has no tune ax99\n")):
            with self.subTest(argv):
                self.assertEqual(self.main(*argv)[::2], (1, text))
        self.keep("v01")
        tune.set_value(self.work, "ks_x", "limiter", "6500", version="v01")
        self.assertEqual(self.main("version-lock", "v01")[::2], (1, "error: version v01 (Drift) has changes that are not built yet: Apply first, then lock it\n"))
        self.keep("v01")
        self.main("version-lock", "v01")
        for argv in (("set", "limiter", "7000", "--version", "v01"), ("unset", "limiter", "--version", "v01"), ("version-rename", "v01", "Other")):
            with self.subTest(argv):
                self.assertEqual(self.main(*argv)[::2], (1, "error: version v01 (Drift) is locked; unlock it to change it\n"))

    def test_show_with_a_version_prints_its_values_and_the_base_meta_settings(self):
        tune.add_version(self.work, "ks_x", "Drift")
        tune.save_version_state(self.work, "ks_x", {"limiter": 6500, "name_suffix": "Ignored"}, "v01")
        code, out, err = self.main("show", "--version", "v01")
        rows = {l.split(" | ")[1].strip(): [c.strip(" |") for c in l.split(" | ")] for l in out.splitlines()[2:]}
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(rows["limiter"][2:4], ["6500", "7000"])
        self.assertEqual(rows["name_suffix"][2], "Base")
        self.assertEqual(rows["limiter"][0], "*")
        self.assertEqual([l.split(" | ")[2].strip() for l in self.main("show")[1].splitlines()[2:] if " limiter " in l], ["8000"])
        self.assertEqual(self.main("show", "--version", "v02")[::2], (1, "error: ks_x has no version v02 of ax_x\n"))

    def test_set_and_unset_with_a_version_write_the_version_only(self):
        tune.add_version(self.work, "ks_x", "Drift")
        self.assertEqual(self.main("set", "limiter", "6500", "--version", "v01"), (0, "limiter = 6500\n", ""))
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01"), {"limiter": 6500})
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000, "name_suffix": "Base"})
        self.assertEqual(self.main("unset", "limiter", "--version", "v01"), (0, "limiter removed from the state\n", ""))
        self.assertEqual(self.main("unset", "limiter", "--version", "v01"), (0, "limiter was not set\n", ""))
        self.assertEqual(tune.read_version_state(self.work, "ks_x", "v01"), {})

    def test_set_and_unset_of_a_meta_setting_with_a_version_are_runtime_errors(self):
        tune.add_version(self.work, "ks_x", "Drift")
        text = "error: name_suffix is shared by all versions, set it on the base\n"
        self.assertEqual(self.main("set", "name_suffix", "X", "--version", "v01")[::2], (1, text))
        self.assertEqual(self.main("unset", "name_suffix", "--version", "v01")[::2], (1, text))
        self.assertEqual(self.main("set", "name_suffix", "X")[::2], (0, ""))

    def test_defaults_with_a_version_prints_the_defaults_of_the_tune(self):
        tune.add_version(self.work, "ks_x", "Drift")
        code, out, err = self.main("defaults", "--version", "v01")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, self.main("defaults")[1])
        self.assertEqual(self.main("defaults", "--version", "v05")[::2], (1, "error: ks_x has no version v05 of ax_x\n"))
        self.assertEqual(self.main("defaults", "--version", "v01", "--tune", "ax01")[::2], (1, "error: ks_x has no version v01 of ax01\n"))


# --------------------------------------------------------------------------------------------- work folder
class TestWorkFolder(Base):
    def test_work_dir_expands_environment_variables(self):
        var = "%ACE_TEST_WORK%" if os.name == "nt" else "$ACE_TEST_WORK"
        with mock.patch.dict(os.environ, {"ACE_TEST_WORK": str(self.d)}):
            self.assertEqual(tune.work_dir(var + os.sep + "w"), os.path.join(str(self.d), "w"))

    def test_work_dir_refuses_an_unexpanded_variable(self):
        with self.assertRaisesRegex(ValueError, "cannot expand the work directory"):
            tune.work_dir("%ACE_TEST_NO_SUCH_VAR%" + os.sep + "w")

    def test_work_dir_error_says_what_to_pass(self):
        bad = "%ACE_TEST_NO_SUCH_VAR%" + os.sep + "w"
        with self.assertRaises(ValueError) as cm:
            tune.work_dir(bad)
        self.assertEqual(str(cm.exception), "cannot expand the work directory %r: the default is %%USERPROFILE%%\\ace_modded_cars_work and this program "
                         "expects Windows; pass --work <folder> on other systems" % bad)
        default = "%ACE_TEST_NO_SUCH_VAR%" + os.sep + "d"
        with mock.patch.object(tune, "DEFAULT_WORK", default), self.assertRaises(ValueError) as cm:
            tune.work_dir()
        self.assertIn("cannot expand the work directory %r: the default is %s and" % (default, default), str(cm.exception))

    def test_work_dir_makes_the_path_absolute(self):
        self.assertTrue(os.path.isabs(tune.work_dir("relative_work")))

    def test_inside_accepts_children_and_refuses_others(self):
        root = str(self.d)
        self.assertEqual(tune.resolve_inside(root, os.path.join(root, "a", "b")), os.path.realpath(os.path.join(root, "a", "b")))
        with self.assertRaisesRegex(ValueError, "is not inside"):
            tune.resolve_inside(root, os.path.join(root, "..", "elsewhere"))

    def test_remove_tree_removes_a_subfolder(self):
        self.write(os.path.join(self.work, "a", "f.txt"), "x")
        tune.remove_tree(self.work, os.path.join(self.work, "a"))
        self.assertFalse(os.path.exists(os.path.join(self.work, "a")))

    def test_remove_tree_refuses_the_work_folder_and_outside_paths(self):
        self.write(os.path.join(self.work, "f.txt"), "x")
        with self.assertRaisesRegex(ValueError, "refusing to remove the work directory"):
            tune.remove_tree(self.work, self.work)
        with self.assertRaises(ValueError):
            tune.remove_tree(self.work, str(self.d))
        self.assertTrue(os.path.exists(os.path.join(self.work, "f.txt")))

    def old_layout(self, names=tune.OLD_LAYOUT):
        for name in names:
            if name in ("base", "build"):
                self.write(os.path.join(self.work, name, "f.txt"), name)
            else:
                self.write(os.path.join(self.work, name), "{}")

    def test_migrate_moves_the_old_single_car_layout(self):
        self.old_layout()
        self.write(os.path.join(self.work, "backups", "b.kspkg"), "b")
        moved = tune.migrate_old_layout(self.work, "ks_a")
        self.assertEqual(moved, list(tune.OLD_LAYOUT))
        for name in tune.OLD_LAYOUT:
            self.assertFalse(os.path.exists(os.path.join(self.work, name)), name)
            self.assertTrue(os.path.exists(os.path.join(self.work, "ks_a", name)), name)
        self.assertTrue(os.path.exists(os.path.join(self.work, "backups", "b.kspkg")))
        self.assertTrue(os.path.exists(os.path.join(self.work, "ks_a", "base", "f.txt")))

    def test_migrate_moves_only_what_exists(self):
        self.old_layout(("base", "tune_state.json"))
        self.assertEqual(tune.migrate_old_layout(self.work, "ks_a"), ["base", "tune_state.json"])

    def test_migrate_does_nothing_twice_or_without_a_base(self):
        self.old_layout()
        tune.migrate_old_layout(self.work, "ks_a")
        self.assertEqual(tune.migrate_old_layout(self.work, "ks_a"), [])
        other = os.path.join(self.work, "second")
        self.write(os.path.join(other, "tune_state.json"), "{}")
        self.assertEqual(tune.migrate_old_layout(other, "ks_a"), [])
        self.assertTrue(os.path.exists(os.path.join(other, "tune_state.json")))

    def test_migrate_leaves_a_layout_alone_when_the_car_folder_exists(self):
        self.old_layout()
        os.makedirs(os.path.join(self.work, "ks_a"))
        self.assertEqual(tune.migrate_old_layout(self.work, "ks_a"), [])
        self.assertTrue(os.path.exists(os.path.join(self.work, "base", "f.txt")))

    def test_start_migrates_and_says_so(self):
        self.cars(("ks_a", "A"))
        self.old_layout(("base", "defaults.json"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            work, car_id = tune.start({"work": self.work, "game": os.path.join(self.work, "none.kspkg")})
        self.assertEqual((work, car_id), (os.path.abspath(self.work), "ks_a"))
        self.assertEqual(out.getvalue(), "moved the old single-car layout of %s into %s: base, defaults.json\n"
                         % (os.path.abspath(self.work), os.path.join(os.path.abspath(self.work), "ks_a")))

    def test_start_rejects_an_unknown_car_before_moving_anything(self):
        self.cars(("ks_a", "A"))
        self.old_layout()
        with self.assertRaisesRegex(ValueError, "unknown car 'ks_zzz'"):
            tune.start({"work": self.work, "car": "ks_zzz", "game": os.path.join(self.work, "none.kspkg")})
        self.assertTrue(os.path.exists(os.path.join(self.work, "base")))

    def test_start_refuses_an_unexpanded_work_folder(self):
        self.cars()
        with self.assertRaisesRegex(ValueError, "cannot expand the work directory"):
            tune.start({"work": "%ACE_TEST_NO_SUCH_VAR%" + os.sep + "w"})

    def test_init_reports_a_present_base_without_the_game(self):
        fc = FakeCar(self.work).install(self)
        fc.add("data/x.car", {"engine_path": "x"})
        self.write(tune.stock_loc_path(self.work), "loc")
        self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_x", "display_name": "X", "brand": "B", "year": 1, "property_1": "a",
                                                          "property_2": "b", "property_3": "c", "variant_name": ""})
        res = tune.init(self.work, "ks_x", os.path.join(self.work, "none.kspkg"))
        self.assertEqual((res["present"], res["files"], res["stock_loc"], res["stock_info"], res["tyre_files"]),
                         (True, 1, "present", "present", "present"))
        self.assertEqual(res["dir"], fc.car_root)

    def test_init_without_base_and_without_game(self):
        with self.assertRaisesRegex(ValueError, "game package not found"):
            tune.init(self.work, "ks_x", os.path.join(self.work, "none.kspkg"))

    def test_init_without_the_package_says_how_to_pass_it(self):
        game = os.path.join(self.work, "none.kspkg")
        with self.assertRaises(ValueError) as cm:
            tune.init(self.work, "ks_x", game)
        self.assertEqual(str(cm.exception), GAME_MISSING % game)

    def test_init_extracts_through_a_partial_folder(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        seen = []

        def extract(pkg, outdir, prefix=None):
            seen.append((outdir, prefix))
            self.write(os.path.join(outdir, "content", "cars", "ks_x", "data", "x.car"), b"car", binary=True)
        self.patch(kspkg, "cmd_extract", extract)
        self.patch(tune, "ensure_stock_loc", lambda work, game: "written")
        self.patch(tune, "write_stock_info", lambda work, car_id, game: "written")
        self.patch(tune, "ensure_tyre_files", lambda work, car_id, game: "present")
        res = tune.init(self.work, "ks_x", game)
        self.assertEqual((res["present"], res["files"], res["bytes"]), (False, 1, 3))
        self.assertEqual(seen, [(tune.base_dir(self.work, "ks_x") + ".partial", "content\\cars\\ks_x")])
        self.assertTrue(os.path.isfile(os.path.join(tune.base_dir(self.work, "ks_x"), "content", "cars", "ks_x", "data", "x.car")))
        self.assertFalse(os.path.exists(tune.base_dir(self.work, "ks_x") + ".partial"))

    def test_init_with_a_package_that_lacks_the_car_leaves_no_partial_folder(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(kspkg, "cmd_extract", lambda pkg, outdir, prefix=None: os.makedirs(outdir))
        with self.assertRaisesRegex(ValueError, "ks_x not found in"):
            tune.init(self.work, "ks_x", game)
        self.assertFalse(os.path.exists(tune.base_dir(self.work, "ks_x") + ".partial"))
        self.assertFalse(os.path.exists(tune.base_dir(self.work, "ks_x")))


# --------------------------------------------------------------------------------------------- rename_files
class TestRenameFiles(CarCase):
    """rename_files on the stubbed car: the decoded messages come from the stub store, the bytes of the files are placeholders (put_bytes writes text into one)."""

    def setUp(self):
        super().setUp()
        self.fc.add("data/old.car", {"engine_path": self.fc.game_path("data/engine.carengine")})
        self.fc.add("data/other.car", {"x": 1})

    def put_bytes(self, rel, data):
        return self.write(os.path.join(self.fc.car_root, *rel.split("/")), data, binary=True)

    def decoded(self, rel):
        return self.fc.store[self.fc.key(os.path.join(self.fc.car_root, *rel.split("/")))]

    def test_the_file_moves_and_the_references_in_decodable_files_are_rewritten(self):
        gp = self.fc.game_path
        self.fc.add("presets/a.carfinalstate", {"car_data": gp("data/old.car"), "keep": gp("data/other.car"), "n": 3})
        self.fc.add("presets/b.carfinalstate", {"car_data": gp("data/other.car")})
        res = tune.rename_files(self.fc.car_root, {"data/old.car": "data/CarData.car"})
        self.assertEqual(res, {"renamed": [("data/old.car", "data/CarData.car")], "rewritten": {"presets/a.carfinalstate": 1}})
        self.assertFalse(os.path.exists(os.path.join(self.fc.car_root, "data", "old.car")))
        self.assertTrue(os.path.isfile(os.path.join(self.fc.car_root, "data", "CarData.car")))
        self.assertEqual(self.decoded("presets/a.carfinalstate"), {"car_data": gp("data/CarData.car"), "keep": gp("data/other.car"), "n": 3})
        self.assertEqual(self.decoded("presets/b.carfinalstate"), {"car_data": gp("data/other.car")})
        self.assertEqual(self.fc.saved, [self.fc.key(os.path.join(self.fc.car_root, "presets", "a.carfinalstate"))])

    def test_a_renamed_file_that_refers_to_itself_is_reported_under_its_new_name(self):
        self.fc.add("data/old.car", {"self": self.fc.game_path("data/old.car"), "engine_path": "e"})
        res = tune.rename_files(self.fc.car_root, {"data/old.car": "data/CarData.car"})
        self.assertEqual(res["rewritten"], {"data/CarData.car": 1})

    def test_case_differences_in_the_mapping_and_in_the_texts_are_matched_and_the_slashes_of_a_text_are_kept(self):
        self.fc.add("presets/a.carfinalstate", {"a": "CONTENT\\CARS\\KS_X\\DATA\\OLD.CAR",
                                                "b": ["content/cars/ks_x/data/old.car", "content/cars/ks_x/data/old.carx"]})
        res = tune.rename_files(self.fc.car_root, {"DATA/Old.CAR": "data/CarData.car"})
        self.assertEqual(res["renamed"], [("data/old.car", "data/CarData.car")])
        self.assertEqual(self.decoded("presets/a.carfinalstate"),
                         {"a": "content\\cars\\ks_x\\data\\CarData.car", "b": ["content/cars/ks_x/data/CarData.car", "content/cars/ks_x/data/old.carx"]})

    def test_a_case_only_rename_is_allowed_and_a_taken_name_is_not(self):
        res = tune.rename_files(self.fc.car_root, {"data/old.car": "data/OLD.CAR"})
        self.assertEqual(res["renamed"], [("data/old.car", "data/OLD.CAR")])
        self.assertIn("OLD.CAR", os.listdir(os.path.join(self.fc.car_root, "data")))
        with self.assertRaisesRegex(ValueError, "cannot rename data/OLD.CAR to data/Other.car: the name is taken"):
            tune.rename_files(self.fc.car_root, {"data/OLD.CAR": "data/Other.car"})

    def test_a_file_that_holds_the_old_path_but_cannot_be_decoded_is_an_error_and_nothing_changes(self):
        self.fc.add("presets/a.carfinalstate", {"car_data": self.fc.game_path("data/old.car")})
        bad = self.put_bytes("presets/bad.carfinalstate", b"\x0a\x2bcontent\\cars\\ks_x\\data\\OLD.car\x10\x01")
        self.fc.store[self.fc.key(bad)] = ValueError("bad.carfinalstate: truncated")
        with self.assertRaisesRegex(ValueError, r"^presets/bad.carfinalstate refers to content.cars.ks_x.data.OLD.car, which is renamed, but cannot be decoded "
                                                r"\(bad.carfinalstate: truncated\); its bytes are not patched$"):
            tune.rename_files(self.fc.car_root, {"data/old.car": "data/CarData.car"})
        self.assertTrue(os.path.isfile(os.path.join(self.fc.car_root, "data", "old.car")))
        self.assertEqual((self.fc.saved, self.decoded("presets/a.carfinalstate")["car_data"]), ([], self.fc.game_path("data/old.car")))

    def test_a_file_of_a_type_without_a_message_that_holds_the_old_path_is_an_error(self):
        self.put_bytes("data/notes.txt", b"see content/cars/ks_x/data/old.car")
        with self.assertRaisesRegex(ValueError, "^data/notes.txt refers to content/cars/ks_x/data/old.car, which is renamed, but cannot be decoded"):
            tune.rename_files(self.fc.car_root, {"data/old.car": "data/CarData.car"})

    def test_an_undecodable_file_without_the_old_path_is_left_alone(self):
        bad = self.put_bytes("presets/bad.carfinalstate", b"\x0a\x05hello")
        self.fc.store[self.fc.key(bad)] = ValueError("truncated")
        self.put_bytes("data/notes.txt", b"content/cars/ks_x/data/other.car")
        res = tune.rename_files(self.fc.car_root, {"data/old.car": "data/CarData.car"})
        self.assertEqual((res["rewritten"], self.fc.saved), ({}, []))

    def test_a_decodable_file_that_holds_the_path_outside_a_text_field_is_an_error(self):
        self.fc.add("presets/a.carfinalstate", {"n": 5})
        self.put_bytes("presets/a.carfinalstate", b"\x0a\x1bcontent\\cars\\ks_x\\data\\old.car")
        with self.assertRaisesRegex(ValueError, "^presets/a.carfinalstate refers to .*old.car, which is renamed, but not in a text field of it; its bytes are not patched$"):
            tune.rename_files(self.fc.car_root, {"data/old.car": "data/CarData.car"})
        self.assertEqual(self.fc.saved, [])

    def test_bad_mappings_are_refused_before_anything_changes(self):
        for mapping, message in (({"data/missing.car": "data/CarData.car"}, "missing.car not found in"),
                                 ({"data": "data2"}, "data is not a file"),
                                 ({"data/old.car": "../x.car"}, "is not inside"),
                                 ({"data/old.car": "data/Other.car"}, "the name is taken"),
                                 ({"data/old.car": "data/a.car", "DATA/OLD.CAR": "data/b.car"}, "a file is listed twice"),
                                 ({"data/old.car": "data/a.car", "data/other.car": "DATA/A.CAR"}, "a file is listed twice"),
                                 ({"data/old.car": "data/other.car", "data/other.car": "data/b.car"}, "the name is taken")):
            with self.subTest(mapping):
                with self.assertRaisesRegex(ValueError, message):
                    tune.rename_files(self.fc.car_root, mapping)
        self.assertEqual(sorted(os.listdir(os.path.join(self.fc.car_root, "data"))),
                         ["engine.carengine", "old.car", "other.car", "power.curve", "setup.carsetup", "x.car"])

    def test_several_files_and_a_new_folder(self):
        gp = self.fc.game_path
        self.fc.add("presets/a.carfinalstate", {"p": gp("data/old.car"), "q": gp("data/other.car")})
        res = tune.rename_files(self.fc.car_root, {"data/old.car": "data/new/A.car", "data/other.car": "data/B.car"})
        self.assertEqual(res, {"renamed": [("data/old.car", "data/new/A.car"), ("data/other.car", "data/B.car")], "rewritten": {"presets/a.carfinalstate": 2}})
        self.assertEqual(self.decoded("presets/a.carfinalstate"), {"p": gp("data/new/A.car"), "q": gp("data/B.car")})
        self.assertTrue(os.path.isfile(os.path.join(self.fc.car_root, "data", "new", "A.car")))


# --------------------------------------------------------------------------------------------- apply
class TestApply(CarCase):
    def setUp(self):
        super().setUp()
        self.cars(("ks_x", "Car X"))
        self.stock_info()
        self.calls = []
        self.patch(clone_car, "build", self.build)
        self.patch(kspkg, "cmd_pack", self.pack)
        self.patch(tune, "ensure_stock_loc", lambda work, game=None: "present")
        self.game = os.path.join(self.work, "no_game.kspkg")
        self.notes = ["note: from build"]
        self.build_error = None
        self.pack_error = None
        self.patch(os, "rename", self.rename)

    def rename(self, src, dst):
        """os.rename that also moves the stub contents of the files below src, like the files themselves."""
        old, new = self.fc.key(src), self.fc.key(dst)
        moved = [k for k in self.fc.store if k == old or k.startswith(old + os.sep)]
        REAL_RENAME(src, dst)
        self.fc.store.update({new + k[len(old):]: self.fc.store.pop(k) for k in moved})

    def build(self, car_dir, new_id, out_dir, name, year, brand, variant, stock_loc, props, pack=True):
        self.calls.append(("build", car_dir, new_id, out_dir, name, year, brand, variant, stock_loc, props, pack))
        if self.build_error:
            self.write(os.path.join(out_dir, "content", "cars", new_id, "partial.bin"), b"half", binary=True)
            raise self.build_error
        print("progress noise of the clone")
        self.fc.clone_into(out_dir, new_id)
        return list(self.notes)

    def pack(self, indir, pkg):
        self.calls.append(("pack", indir, pkg))
        if self.pack_error:
            raise self.pack_error
        with open(pkg, "wb") as f:
            f.write(b"PKG-NEW")

    def settings(self, *more):
        return mini_catalogue(*metas(), *more)

    def apply(self, cat, state=None, **kw):
        if state is not None:
            tune.save_state(self.work, "ks_x", state)
        kw.setdefault("install", False)
        return tune.apply(self.work, "ks_x", catalogue=cat, game=self.game, **kw)

    def built(self, res, rel):
        return self.fc.store[self.fc.key(os.path.join(res["build_dir"], "content", "cars", res["new_id"], *rel.split("/")))]

    def test_without_changes_nothing_is_applied_and_the_build_gets_the_stock_data(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = self.apply(self.settings(limiter()))
        self.assertEqual(out.getvalue(), "")
        self.assertEqual((res["new_id"], res["applied"], res["notes"], res["installed"], res["backup"], res["size"]),
                         ("ax_x", [], ["note: from build", CAR_NOTE], None, None, 7))
        build = self.calls[0]
        self.assertEqual(build[1:], (self.fc.car_root, "ax_x", os.path.join(self.work, "ks_x", "build", "ax_x.partial"), "Car X MY", 1999, "Brand", "Base",
                                     None, {"property_1": "P1", "property_2": "P2", "property_3": "P3"}, False))
        part = res["build_dir"] + ".partial"
        self.assertEqual(self.calls[1], ("pack", part, os.path.join(part, "ax_x.kspkg")))
        self.assertEqual(res["package"], os.path.join(res["build_dir"], "ax_x.kspkg"))

    def test_build_and_pack_output_stays_out_of_stdout(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.apply(self.settings())
        self.assertEqual(out.getvalue(), "")

    def test_custom_new_id(self):
        res = self.apply(self.settings(), new_id="ax_y")
        self.assertEqual((res["new_id"], self.calls[0][2]), ("ax_y", "ax_y"))

    def test_name_suffix_and_variant_reach_the_build(self):
        self.apply(self.settings(), {"name_suffix": "_TUNED", "variant_name": "My Variant"})
        self.assertEqual((self.calls[0][4], self.calls[0][7]), ("Car X _TUNED", "My Variant"))

    def test_meta_changes_are_listed_with_the_file_they_land_in(self):
        res = self.apply(self.settings(), {"name_suffix": "_TUNED", "variant_name": "My Variant"})
        self.assertEqual([(a["id"], a["old"], a["new"], a["files"]) for a in res["applied"]],
                         [("name_suffix", "MY", "_TUNED", ["ax_x.moddedcarcontent"]),
                          ("variant_name", "Base", "My Variant", ["uiresources/localization/en.cars.loc"])])

    def test_the_car_file_of_the_build_is_data_cardata_car_and_every_reference_follows(self):
        gp = self.fc.game_path
        self.fc.add("presets/p1.carfinalstate", {"car_data": gp("data/x.car")})
        self.fc.add("presets/p2.carfinalstate", {"car_data": gp("data/x.car").upper(), "other": gp("data/engine.carengine")})
        res = self.apply(self.settings(limiter()), {"limiter": 8000})
        data = os.path.join(res["build_dir"], "content", "cars", "ax_x", "data")
        self.assertEqual(sorted(n for n in os.listdir(data) if n.lower().endswith(".car")), ["CarData.car"])
        self.assertEqual(self.built(res, "data/CarData.car")["engine"]["limiter"], 8000)
        for name in ("p1", "p2"):
            self.assertEqual(self.built(res, "presets/%s.carfinalstate" % name)["car_data"], "content\\cars\\ax_x\\data\\CarData.car")
        self.assertEqual(self.built(res, "presets/p2.carfinalstate")["other"], "content\\cars\\ax_x\\data\\engine.carengine")
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE])
        self.assertEqual([a["files"] for a in res["applied"] if a["id"] == "limiter"], [["data/engine.carengine", "data/CarData.car"]])
        self.assertEqual(self.fc.store[self.fc.key(os.path.join(self.fc.car_root, "presets", "p1.carfinalstate"))]["car_data"], gp("data/x.car"))
        self.assertTrue(os.path.isfile(os.path.join(self.fc.car_root, "data", "x.car")))

    def test_a_car_file_that_is_named_cardata_already_is_not_touched(self):
        os.remove(os.path.join(self.fc.car_root, "data", "x.car"))
        self.fc.add("data/CARDATA.car", self.car)
        self.fc.add("presets/p1.carfinalstate", {"car_data": self.fc.game_path("data/CARDATA.car")})
        self.patch(tune, "rename_files", lambda *a, **k: self.fail("rename_files"))
        res = self.apply(self.settings(limiter()), {"limiter": 8000})
        self.assertEqual(res["notes"], ["note: from build"])
        self.assertEqual(self.built(res, "data/CARDATA.car")["engine"]["limiter"], 8000)
        self.assertEqual(self.built(res, "presets/p1.carfinalstate")["car_data"], "content\\cars\\ax_x\\data\\CARDATA.car")
        self.assertEqual([a["files"] for a in res["applied"] if a["id"] == "limiter"], [["data/engine.carengine", "data/CARDATA.car"]])

    def test_a_changed_value_is_written_into_every_resolved_copy_of_the_build_only(self):
        before = {k: json.dumps(v, sort_keys=True) for k, v in self.fc.store.items()}
        res = self.apply(self.settings(limiter()), {"limiter": 8000})
        self.assertEqual(self.built(res, "data/engine.carengine")["limiter"], 8000)
        self.assertEqual(self.built(res, "data/CarData.car")["engine"]["limiter"], 8000)
        self.assertEqual({k: json.dumps(v, sort_keys=True) for k, v in self.fc.store.items() if k in before}, before)
        self.assertTrue(all(p.startswith(self.fc.key(res["build_dir"])) for p in self.fc.saved))
        item = [a for a in res["applied"] if a["id"] == "limiter"][0]
        self.assertEqual((item["old"], item["new"], item["files"]), (7000, 8000, ["data/engine.carengine", "data/CarData.car"]))

    def test_unchanged_settings_are_not_written(self):
        res = self.apply(self.settings(limiter(), mini_setting("m", targets=[("@engine", "minimum")])), {"m": 900.0})
        self.assertEqual([a["id"] for a in res["applied"]], ["m"])
        self.assertEqual(len(self.fc.saved), 1)

    def test_state_equal_to_the_default_is_not_a_change(self):
        res = self.apply(self.settings(limiter()), {"limiter": 7000, "name_suffix": "MY"})
        self.assertEqual((res["applied"], self.fc.saved), ([], []))

    def test_a_legacy_suffix_in_the_state_builds_the_converted_name(self):
        res = self.apply(self.settings(), {"name_suffix": "_MY"})
        self.assertEqual((self.calls[0][4], res["name_suffix"], res["applied"]), ("Car X MY", "MY", []))
        res = self.apply(self.settings(), {"name_suffix": "_MY2"})
        self.assertEqual(([c[4] for c in self.calls if c[0] == "build"][1], res["name_suffix"]), ("Car X MY 2", "MY 2"))
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"name_suffix": "_MY2"})

    def test_the_build_name_is_the_stock_name_a_space_and_the_trimmed_suffix(self):
        self.apply(self.settings(), {"name_suffix": "  Super   charged "})
        self.assertEqual(self.calls[0][4], "Car X Super charged")

    def test_floats_are_written_as_f32_with_the_short_text(self):
        res = self.apply(self.settings(mini_setting("f", targets=[("@engine", "minimum")])), {"f": 1.1})
        v = self.built(res, "data/engine.carengine")["minimum"]
        self.assertIsInstance(v, car_json.F32)
        self.assertEqual(v.text, "1.1")

    def test_an_optional_copy_that_does_not_resolve_is_skipped(self):
        s = mini_setting("o", targets=[("@engine", "minimum"), ("@car", "nothere.deeper", True)])
        res = self.apply(self.settings(s), {"o": 5.0})
        self.assertEqual([a["files"] for a in res["applied"]], [["data/engine.carengine"]])

    def test_a_missing_last_field_is_created(self):
        res = self.apply(self.settings(mini_setting("z", targets=[("@engine", "nothere")])), {"z": 2.0})
        self.assertEqual(self.built(res, "data/engine.carengine")["nothere"], 2.0)

    def test_create_missing_creates_the_objects_on_the_way(self):
        s = mini_setting("arb", targets=[("@car", "suspensions.arbFront.stiffness")], create_missing=True)
        res = self.apply(self.settings(s), {"arb": 1000.0})
        self.assertEqual(self.built(res, "data/CarData.car")["suspensions"], {"arbFront": {"stiffness": 1000.0}})

    def test_curve_scale_multiplies_every_point_value(self):
        s = mini_setting("ps", kind="curve_scale", default=1.0, curve_from={"file": "@engine", "path": "powerCurve"}, targets=[])
        res = self.apply(self.settings(s), {"ps": 1.5})
        self.assertEqual(self.built(res, "data/power.curve")["points"], [{"value": 1.5}, {"value": 4.5}, {"x": 5}])
        self.assertEqual([a["files"] for a in res["applied"] if a["id"] == "ps"], [["data/power.curve"]])
        self.assertEqual(self.fc.store[self.fc.key(os.path.join(self.fc.car_root, "data", "power.curve"))]["points"][0], {"value": 1.0})

    def flag(self, **kw):
        return mini_setting("aids", kind="flag", type="bool", value=0, targets=[
            ("@car", "performance_modes[*].electronics_settings.tc1", True), ("@car", "performance_modes[*].electronics_settings.tc2", True),
            ("@setup", "electronics.tc1", True)], **kw)

    def test_flag_writes_its_value_into_all_resolved_copies_and_skips_absent_zero_fields(self):
        res = self.apply(self.settings(self.flag()), {"aids": True})
        modes = self.built(res, "data/CarData.car")["performance_modes"]
        self.assertEqual([m["electronics_settings"] for m in modes], [{"tc1": 0, "esc": 2}, {"tc1": 0, "tc2": 0}])
        self.assertEqual(self.built(res, "data/setup.carsetup")["electronics"]["tc1"], 0)
        item = [a for a in res["applied"] if a["id"] == "aids"][0]
        self.assertEqual((item["old"], item["new"], sorted(item["files"])), (False, True, ["data/CarData.car", "data/setup.carsetup"]))

    def test_the_static_camber_settings_write_both_wheels_of_their_axle(self):
        real = [s for s in REAL_LOAD_CATALOGUE()["settings"] if s["id"] in ("static_camber_front", "static_camber_rear")]
        self.assertEqual([s["id"] for s in real], ["static_camber_front", "static_camber_rear"])
        self.setup["alignments"] = [{"camber": -1.0, "static_camber": -1.5 - i / 10} for i in range(4)]
        res = self.apply(self.settings(*real), {"static_camber_front": -3.5, "static_camber_rear": -2.0})
        alignments = self.built(res, "data/setup.carsetup")["alignments"]
        self.assertEqual([a["static_camber"] for a in alignments], [-3.5, -3.5, -2.0, -2.0])
        self.assertEqual([a["camber"] for a in alignments], [-1.0] * 4)
        items = {a["id"]: a for a in res["applied"]}
        self.assertEqual((items["static_camber_front"]["old"], items["static_camber_front"]["new"]), (-1.5, -3.5))
        self.assertEqual((items["static_camber_rear"]["old"], items["static_camber_rear"]["new"]), (-1.7, -2.0))

    def test_the_wastegate_settings_write_the_engine_and_the_turbo_file_of_their_own_turbo_only(self):
        real = [s for s in REAL_LOAD_CATALOGUE()["settings"] if s["id"] in ("turbo_wastegate_1", "turbo_wastegate_2")]
        self.assertEqual([s["id"] for s in real], ["turbo_wastegate_1", "turbo_wastegate_2"])
        self.engine["turbos"] = [{"max_boost": 1.0, "wastegate": 0.785}, {"max_boost": 1.0, "wastegate": 0.785}]
        self.engine["turbos_to_load"] = [self.fc.game_path("data/t0.turbo"), self.fc.game_path("data/t1.turbo")]
        self.fc.add("data/t0.turbo", {"max_boost": 1.0, "wastegate": 0.785})
        self.fc.add("data/t1.turbo", {"max_boost": 1.0, "wastegate": 0.785})
        res = self.apply(self.settings(*real), {"turbo_wastegate_2": 1.25})
        turbos = self.built(res, "data/engine.carengine")["turbos"]
        self.assertEqual([t["wastegate"] for t in turbos], [0.785, 1.25])
        self.assertEqual(self.built(res, "data/t0.turbo")["wastegate"], 0.785)
        self.assertEqual(self.built(res, "data/t1.turbo")["wastegate"], 1.25)
        self.assertEqual([t["max_boost"] for t in turbos], [1.0, 1.0])
        items = {a["id"]: a for a in res["applied"]}
        self.assertEqual(list(items), ["turbo_wastegate_2"])
        self.assertEqual((items["turbo_wastegate_2"]["old"], items["turbo_wastegate_2"]["new"]), (0.785, 1.25))

    def test_the_force_feedback_multiplier_writes_the_controls_of_the_car_and_nothing_else(self):
        real = [s for s in REAL_LOAD_CATALOGUE()["settings"] if s["id"] == "ff_mult"]
        self.assertEqual([s["id"] for s in real], ["ff_mult"])
        self.car["controls"] = {"ffMult": 1.75, "linearSteerRodRatio": 0.0017}
        res = self.apply(self.settings(*real), {"ff_mult": 2.25})
        built = self.built(res, "data/CarData.car")
        self.assertEqual(built["controls"], {"ffMult": 2.25, "linearSteerRodRatio": 0.0017})
        self.assertEqual(built["engine"], {"limiter": 7000.0, "minimum": 900})
        items = {a["id"]: a for a in res["applied"]}
        self.assertEqual(list(items), ["ff_mult"])
        self.assertEqual((items["ff_mult"]["old"], items["ff_mult"]["new"], items["ff_mult"]["files"]), (1.75, 2.25, ["data/CarData.car"]))

    def test_flag_that_is_off_writes_nothing(self):
        res = self.apply(self.settings(self.flag()), {"aids": False})
        self.assertEqual((res["applied"], self.fc.saved), ([], []))

    def test_flag_wins_over_a_value_on_the_same_field(self):
        value = mini_setting("tc", type="int", targets=[("@setup", "electronics.tc1")])
        res = self.apply(self.settings(self.flag(), value), {"aids": True, "tc": 7})
        self.assertEqual(self.built(res, "data/setup.carsetup")["electronics"]["tc1"], 0)

    def test_a_flag_with_a_non_zero_value_creates_absent_fields(self):
        flag = mini_setting("on", kind="flag", type="bool", value=5, targets=[("@setup", "electronics.nothere", True)])
        res = self.apply(self.settings(flag), {"on": True})
        self.assertEqual(self.built(res, "data/setup.carsetup")["electronics"]["nothere"], 5)

    def test_unknown_state_ids_do_not_stop_apply(self):
        res = self.apply(self.settings(limiter()), {"old_id": 1, "limiter": 8000})
        self.assertEqual([a["id"] for a in res["applied"]], ["limiter"])
        self.assertEqual(tune.load_state(self.work, "ks_x")["old_id"], 1)

    def test_changed_setting_that_is_not_applicable_is_refused_before_building(self):
        with self.assertRaisesRegex(ValueError, r"cannot apply the changed setting\(s\), not applicable to ks_x: deep \(@engine q.r: missing field 'q'\)"):
            self.apply(self.settings(mini_setting("deep", targets=[("@engine", "q.r")])), {"deep": 1.0})
        self.assertEqual(self.calls, [])

    def test_unchanged_setting_that_is_not_applicable_does_not_matter(self):
        self.apply(self.settings(mini_setting("deep", targets=[("@engine", "q.r")])))
        self.assertEqual(len(self.calls), 2)

    def test_no_base_car(self):
        with self.assertRaisesRegex(ValueError, "no base car in .*, run init first"):
            tune.apply(os.path.join(self.work, "elsewhere"), "ks_x", catalogue=self.settings(), install=False, game=self.game)

    def test_new_id_must_have_the_length_of_the_old_one(self):
        with self.assertRaisesRegex(ValueError, "must have exactly 4"):
            self.apply(self.settings(), new_id="ax_xy")
        self.assertEqual(self.calls, [])

    def test_new_id_must_differ_and_use_plain_characters(self):
        for bad, message in (("ks_x", "equals the old id"), ("AX_X", "may only contain")):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, message):
                    self.apply(self.settings(), new_id=bad)

    def test_other_car_than_the_default_needs_its_stock_info(self):
        self.cars(("ks_a", "Other"), ("ks_x", "Car X"))
        os.remove(tune.stock_info_path(self.work, "ks_x"))
        with self.assertRaisesRegex(ValueError, "stock info missing, run init with the game installed"):
            self.apply(self.settings())

    def test_default_car_without_stock_info_falls_back_to_the_preset_name_and_clone_defaults(self):
        os.remove(tune.stock_info_path(self.work, "ks_x"))
        self.apply(self.settings())
        build = self.calls[0]
        self.assertEqual((build[4], build[5], build[6], build[7], build[9]),
                         ("Brand Name MY", tune.CLONE_YEAR, tune.CLONE_BRAND, "Brand Name", {"property_1": None, "property_2": None, "property_3": None}))

    def test_stock_localization_is_passed_on_when_present(self):
        self.write(tune.stock_loc_path(self.work), b"ks_x_preset_base=Base\r\n", binary=True)
        self.apply(self.settings())
        self.assertEqual(self.calls[0][8], tune.stock_loc_path(self.work))

    def test_a_failing_self_check_becomes_an_error_with_the_log(self):
        def failing(*a, **k):
            print("self-check (a) old id in names: 1 FOUND")
            raise ValueError("self-check failed (see the lines above)")
        self.patch(clone_car, "build", failing)
        with self.assertRaisesRegex(ValueError, "clone self-check failed:\nself-check \\(a\\) old id in names: 1 FOUND"):
            self.apply(self.settings())

    def test_a_leftover_build_of_the_same_id_is_replaced(self):
        old = self.write(os.path.join(self.work, "ks_x", "build", "ax_x", "leftover.txt"), "old")
        res = self.apply(self.settings())
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isfile(res["package"]))

    def test_a_stale_partial_build_is_removed_at_the_start(self):
        stale = self.write(os.path.join(self.work, "ks_x", "build", "ax_x.partial", "stale.txt"), "old")
        self.apply(self.settings())
        self.assertFalse(os.path.exists(stale))
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x"])

    def test_a_failed_build_leaves_only_the_partial_folder_and_the_next_run_removes_it(self):
        builds = os.path.join(self.work, "ks_x", "build")
        self.apply(self.settings())
        self.build_error = ValueError("disk full")
        with self.assertRaises(ValueError):
            self.apply(self.settings())
        self.assertEqual(sorted(os.listdir(builds)), ["ax_x", "ax_x.partial"])
        self.build_error = None
        self.apply(self.settings())
        self.assertEqual(os.listdir(builds), ["ax_x"])

    def test_other_builds_are_left_alone(self):
        other = self.write(os.path.join(self.work, "ks_x", "build", "ax_other", "keep.txt"), "keep")
        self.apply(self.settings())
        self.assertTrue(os.path.exists(other))

    def test_install_copies_the_package_and_reports_no_backup_the_first_time(self):
        mods = str(self.d / "mods")
        res = self.apply(self.settings(), install=True, mods_dir=mods)
        self.assertEqual((res["installed"], res["backup"]), (os.path.join(os.path.abspath(mods), "ax_x.kspkg"), None))
        with open(res["installed"], "rb") as f:
            self.assertEqual(f.read(), b"PKG-NEW")

    def test_install_backs_up_the_previous_package(self):
        mods = str(self.d / "mods")
        self.write(os.path.join(mods, "ax_x.kspkg"), b"OLD PACKAGE", binary=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = self.apply(self.settings(), install=True, mods_dir=mods)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(os.path.dirname(res["backup"]), os.path.join(self.work, "backups"))
        self.assertRegex(os.path.basename(res["backup"]), r"^ax_x_\d{8}_\d{6}\.kspkg$")
        with open(res["backup"], "rb") as f:
            self.assertEqual(f.read(), b"OLD PACKAGE")
        with open(res["installed"], "rb") as f:
            self.assertEqual(f.read(), b"PKG-NEW")

    def test_the_backup_is_the_path_install_returns(self):
        mods, seen = str(self.d / "mods"), []

        def install(pkg, mods_dir, backups):
            seen.append((pkg, mods_dir, backups))
            return "elsewhere" + os.sep + "backup.kspkg"
        self.patch(clone_car, "install", install)
        res = self.apply(self.settings(), install=True, mods_dir=mods)
        self.assertEqual(res["backup"], "elsewhere" + os.sep + "backup.kspkg")
        self.assertEqual(seen, [(res["package"], os.path.abspath(mods), os.path.join(self.work, "backups"))])
        self.assertEqual(res["installed"], os.path.join(os.path.abspath(mods), "ax_x.kspkg"))

    def test_an_unexpandable_mods_folder_is_an_error_before_anything_is_built(self):
        with self.assertRaisesRegex(ValueError, "cannot expand"):
            self.apply(self.settings(), install=True, mods_dir="%ACE_TEST_NO_SUCH_VAR%" + os.sep + "m")
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))

    def test_without_install_the_mods_folder_is_not_touched(self):
        mods = self.d / "mods"
        self.apply(self.settings(), install=False, mods_dir=str(mods))
        self.assertFalse(mods.exists())

    def test_the_result_names_the_tune_and_its_suffix(self):
        res = self.apply(self.settings(), {"name_suffix": "_TUNED"})
        self.assertEqual((res["tune"], res["new_id"], res["name_suffix"]), ("ax_x", "ax_x", "_TUNED"))
        self.assertEqual(self.apply(self.settings())["name_suffix"], "_TUNED")

    def modded(self, state, tune_id="ax01"):
        tune.save_state(self.work, "ks_x", state, tune_id)

    def test_a_modded_car_builds_under_its_id_with_its_suffix_and_its_state_only(self):
        self.modded({"limiter": 8000, "name_suffix": "_DRIFT"})
        tune.save_state(self.work, "ks_x", {"limiter": 9500, "name_suffix": "MY"})
        res = self.apply(self.settings(limiter()), new_id="ax01")
        self.assertEqual((res["tune"], res["new_id"], res["name_suffix"]), ("ax01", "ax01", "_DRIFT"))
        self.assertEqual((res["build_dir"], res["package"]), (os.path.join(self.work, "ks_x", "build", "ax01"),
                                                             os.path.join(self.work, "ks_x", "build", "ax01", "ax01.kspkg")))
        self.assertEqual((self.calls[0][2], self.calls[0][4]), ("ax01", "Car X _DRIFT"))
        self.assertEqual(self.built(res, "data/engine.carengine")["limiter"], 8000)
        self.assertEqual(self.built(res, "data/CarData.car")["engine"]["limiter"], 8000)
        self.assertEqual([(a["id"], a["new"]) for a in res["applied"]], [("name_suffix", "_DRIFT"), ("limiter", 8000)])
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax01"])

    def test_building_a_modded_car_leaves_the_default_tune_and_the_draft_alone(self):
        self.modded({"limiter": 8000, "name_suffix": "_DRIFT"})
        tune.save_state(self.work, "ks_x", {"limiter": 9500}, tune.DRAFT)
        before = {n: tune.load_state(self.work, "ks_x", t) for n, t in (("default", None), ("draft", tune.DRAFT), ("ax01", "ax01"))}
        self.apply(self.settings(limiter()), new_id="ax01")
        self.assertEqual({n: tune.load_state(self.work, "ks_x", t) for n, t in (("default", None), ("draft", tune.DRAFT), ("ax01", "ax01"))}, before)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_each_tune_builds_its_own_values(self):
        self.modded({"limiter": 8000, "name_suffix": "_A"})
        self.modded({"limiter": 9000, "name_suffix": "_B"}, "ax02")
        first, second = (self.apply(self.settings(limiter()), new_id=t) for t in ("ax01", "ax02"))
        self.assertEqual([self.built(r, "data/engine.carengine")["limiter"] for r in (first, second)], [8000, 9000])
        self.assertEqual([c[4] for c in self.calls if c[0] == "build"], ["Car X _A", "Car X _B"])

    def test_a_modded_car_is_installed_under_its_id(self):
        self.modded({"name_suffix": "_DRIFT"})
        mods = str(self.d / "mods")
        res = self.apply(self.settings(), new_id="ax01", install=True, mods_dir=mods)
        self.assertEqual(res["installed"], os.path.join(os.path.abspath(mods), "ax01.kspkg"))

    def test_a_name_suffix_used_by_another_tune_is_refused_before_building(self):
        self.modded({"name_suffix": "_SAME"})
        tune.save_state(self.work, "ks_x", {"name_suffix": "_SAME"})
        with self.assertRaisesRegex(ValueError, "^name suffix _SAME is already used by ax_x$"):
            self.apply(self.settings(), new_id="ax01")
        with self.assertRaisesRegex(ValueError, "^name suffix _SAME is already used by ax01$"):
            self.apply(self.settings())
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))

    def test_the_suffix_of_another_stock_car_or_of_the_tune_itself_is_no_collision(self):
        self.cars(("ks_x", "Car X"), ("ks_y", "Car Y"))
        tune.save_state(self.work, "ks_y", {"name_suffix": "_SAME"})
        self.modded({"name_suffix": "_SAME"})
        self.assertEqual(self.apply(self.settings(), new_id="ax01")["name_suffix"], "_SAME")

    def test_the_default_suffix_of_a_tune_without_one_collides_too(self):
        self.modded({"limiter": 8000})
        tune.save_state(self.work, "ks_x", {})
        with self.assertRaisesRegex(ValueError, "name suffix MY is already used by ax_x"):
            self.apply(self.settings(limiter()), new_id="ax01")

    def test_an_id_that_is_not_a_modded_car_is_refused_when_the_stock_car_has_modded_cars(self):
        tune.save_state(self.work, "ks_x", {})
        with self.assertRaisesRegex(ValueError, "^ax02 is not a modded car of ks_x, create it with duplicate first$"):
            self.apply(self.settings(), new_id="ax02")
        self.modded({"name_suffix": "_A"})
        with self.assertRaisesRegex(ValueError, "ax02 is not a modded car of ks_x"):
            self.apply(self.settings(), new_id="ax02")
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tunes", "ax02")))

    def test_the_default_id_is_always_a_tune_and_a_stock_car_without_modded_cars_accepts_any_valid_id(self):
        self.assertEqual(self.apply(self.settings(), new_id="ax_x")["tune"], "ax_x")
        shutil.rmtree(os.path.join(self.work, "ks_x", "build"))
        self.assertEqual(self.apply(self.settings(), new_id="ax_y")["tune"], "ax_y")

    def test_the_tune_id_is_validated_before_any_state_is_read(self):
        self.modded({})
        for bad, message in (("ax_xy", "must have exactly 4"), ("AX01", "may only contain"), ("ks_x", "equals the old id")):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, message):
                self.apply(self.settings(), new_id=bad)

    def tyre_world(self):
        self.fc.add_shared("tyres/slick/s.tyre", {"modelData": {"Dy0": 1.0}})
        self.fc.add("presets/c.compatibletyres", {"physic_compounds": [
            {"front_tyre_data_path": "content/cars/common_phsx/tyres/road/A.tyre", "rear_tyre_data_paths": GAME_SHARED + "tyres\\road\\b.tyre"},
            {"front_tyre_data_path": GAME_SHARED + "tyres\\slick\\s.tyre", "rear_tyre_data_paths": GAME_SHARED + "tyres\\slick\\s.tyre"}]})
        return mini_setting("dy", targets=[("@tyre_front", "modelData.Dy0")])

    def test_a_changed_tyre_value_goes_into_the_cars_own_tyre_file_and_the_references_follow(self):
        s = self.tyre_world()
        self.car["frontTyreCompounds"] = ["CONTENT\\CARS\\COMMON_PHSX\\TYRES\\ROAD\\A.TYRE", GAME_SHARED + "tyres\\slick\\s.tyre"]
        res = self.apply(self.settings(s), {"dy": 1.4})
        own = "data/tyres/ax_x_front.tyre"
        self.assertEqual(tune.plain(self.built(res, own)["modelData"]["Dy0"]), 1.4)
        self.assertEqual(self.built(res, "data/CarData.car")["frontTyreCompounds"],
                         ["content\\cars\\ax_x\\data\\tyres\\ax_x_front.tyre", GAME_SHARED + "tyres\\slick\\s.tyre"])
        compounds = self.built(res, "presets/c.compatibletyres")["physic_compounds"]
        self.assertEqual(compounds[0]["front_tyre_data_path"], "content\\cars\\ax_x\\data\\tyres\\ax_x_front.tyre")
        self.assertEqual(compounds[0]["rear_tyre_data_paths"], GAME_SHARED + "tyres\\road\\b.tyre")
        self.assertEqual(compounds[1]["front_tyre_data_path"], GAME_SHARED + "tyres\\slick\\s.tyre")
        item = [a for a in res["applied"] if a["id"] == "dy"][0]
        self.assertEqual(item["files"], [own])
        self.assertIn("tyre front: own file content\\cars\\ax_x\\data\\tyres\\ax_x_front.tyre replaces", res["notes"][-2])
        self.assertIn("in 1 .car entry(ies) and 1 compatibletyres entry(ies)", res["notes"][-2])

    def test_a_tyre_file_inside_the_car_folder_is_refused_before_building(self):
        self.fc.add("data/tyres/own.tyre", {"modelData": {"Dy0": 1.0}})
        self.car["frontTyreCompounds"] = [self.fc.game_path("data/tyres/own.tyre")]
        s = mini_setting("dy", targets=[("@tyre_front", "modelData.Dy0")])
        with self.assertRaisesRegex(ValueError, "^@tyre_front: the tyre file is inside the car folder, not supported yet$"):
            self.apply(self.settings(s), {"dy": 1.4})
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))

    def test_the_shared_tyre_file_and_the_other_axle_stay_untouched(self):
        s = self.tyre_world()
        res = self.apply(self.settings(s), {"dy": 1.4})
        self.assertEqual(self.fc.store[self.fc.key(os.path.join(self.fc.shared, "tyres", "road", "a.tyre"))]["modelData"]["Dy0"], 1.2)
        self.assertNotIn(self.fc.key(os.path.join(res["build_dir"], "content", "cars", "ax_x", "data", "tyres", "ax_x_rear.tyre")), self.fc.store)
        self.assertEqual(self.built(res, "data/CarData.car")["rearTyreCompounds"], [GAME_SHARED + "tyres\\road\\b.tyre"])

    def test_both_axles_get_their_own_file_when_both_change(self):
        s = [self.tyre_world(), mini_setting("dyr", targets=[("@tyre_rear", "modelData.Dy0")])]
        res = self.apply(self.settings(*s), {"dy": 1.4, "dyr": 1.3})
        self.assertEqual(tune.plain(self.built(res, "data/tyres/ax_x_front.tyre")["modelData"]["Dy0"]), 1.4)
        self.assertEqual(tune.plain(self.built(res, "data/tyres/ax_x_rear.tyre")["modelData"]["Dy0"]), 1.3)
        self.assertEqual(self.built(res, "data/CarData.car")["rearTyreCompounds"], ["content\\cars\\ax_x\\data\\tyres\\ax_x_rear.tyre"])

    def test_a_choice_setting_writes_the_text_of_the_choice(self):
        s = mini_setting("th", type="enum", choices=["road", "slick"], targets=[("@tyre_front", "thermalData.thermalPerformanceCurve")],
                         choice_values={"road": GAME_SHARED + "tyres\\road\\tcurve_road.curve", "slick": GAME_SHARED + "tyres\\slick\\tcurve_slick.curve"})
        res = self.apply(self.settings(s), {"th": "slick"})
        self.assertEqual(self.built(res, "data/tyres/ax_x_front.tyre")["thermalData"]["thermalPerformanceCurve"],
                         GAME_SHARED + "tyres\\slick\\tcurve_slick.curve")
        item = [a for a in res["applied"] if a["id"] == "th"][0]
        self.assertEqual((item["old"], item["new"]), ("road", "slick"))

    def test_failed_build_keeps_the_previous_build(self):
        res = self.apply(self.settings())
        self.build_error = ValueError("disk full while copying")
        with self.assertRaisesRegex(ValueError, "disk full"):
            self.apply(self.settings(), new_id=res["new_id"])
        self.assertTrue(os.path.isfile(res["package"]), "the previous package is gone")
        with open(res["package"], "rb") as f:
            self.assertEqual(f.read(), b"PKG-NEW")

    def test_failed_pack_keeps_the_previous_build(self):
        res = self.apply(self.settings())
        self.pack_error = OSError(28, "No space left on device")
        with self.assertRaises(OSError):
            self.apply(self.settings())
        self.assertTrue(os.path.isfile(res["package"]), "the previous package is gone")
        with open(res["package"], "rb") as f:
            self.assertEqual(f.read(), b"PKG-NEW")

    def test_failed_build_does_not_touch_the_installed_package(self):
        mods = str(self.d / "mods")
        installed = self.write(os.path.join(mods, "ax_x.kspkg"), b"INSTALLED", binary=True)
        self.build_error = ValueError("disk full")
        with self.assertRaises(ValueError):
            self.apply(self.settings(), install=True, mods_dir=mods)
        with open(installed, "rb") as f:
            self.assertEqual(f.read(), b"INSTALLED")

    def test_self_check_failure_error_is_not_chained(self):
        def failing(*a, **k):
            raise ValueError("self-check failed (see the lines above)")
        self.patch(clone_car, "build", failing)
        with self.assertRaises(ValueError) as cm:
            self.apply(self.settings())
        not_chained(self, cm.exception)

    def snapshot_file(self, tune_id="ax_x"):
        return os.path.join(self.work, "ks_x", "snapshots", tune_id + ".json")

    def test_the_first_build_lists_everything_compared_to_the_stock_car_and_writes_the_snapshot(self):
        res = self.apply(self.settings(limiter(), mini_setting("f", targets=[("@engine", "minimum")])), {"limiter": 8000, "f": 1.5})
        self.assertEqual(res["changes"], {"since": None, "total": 2, "extras": [],
                                          "settings": [{"id": "limiter", "from": 7000, "to": 8000}, {"id": "f", "from": 800, "to": 1.5}]})
        self.assertEqual([a["id"] for a in res["applied"]], ["limiter", "f"])
        with open(self.snapshot_file(), encoding="utf-8") as f:
            record = json.load(f)
        self.assertRegex(record.pop("time"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(record, {"version": 1, "settings": {"limiter": 8000, "f": 1.5}, "kit": None, "garage": None, "sounds": {}, "name": "Car X MY",
                                  "changes": res["changes"]})
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.snapshot_file()))), ["ax_x.json"])

    def test_the_changes_are_json_text_without_nan_and_the_applied_list_stays_the_full_list(self):
        s = self.settings(limiter(), mini_setting("f", targets=[("@engine", "minimum")]))
        self.apply(s, {"limiter": 8000, "f": 1.5})
        res = self.apply(s, {"limiter": 8000, "f": 1.6})
        json.dumps(res["changes"], allow_nan=False)
        self.assertEqual(res["changes"], {"since": "last build", "total": 2, "extras": [], "settings": [{"id": "f", "from": 1.5, "to": 1.6}]})
        self.assertEqual([(a["id"], a["old"], a["new"]) for a in res["applied"]], [("limiter", 7000, 8000), ("f", 800, 1.6)])

    def test_a_second_build_with_one_changed_value_has_exactly_that_change(self):
        s = self.settings(limiter())
        self.apply(s, {"limiter": 8000})
        res = self.apply(s, {"limiter": 9000})
        self.assertEqual(res["changes"], {"since": "last build", "total": 1, "extras": [], "settings": [{"id": "limiter", "from": 8000, "to": 9000}]})

    def test_a_second_build_without_a_change_has_nothing_and_a_new_setting_starts_from_the_stock_value(self):
        s = self.settings(limiter(), mini_setting("f", targets=[("@engine", "minimum")]))
        self.apply(s, {"limiter": 8000})
        self.assertEqual(self.apply(s)["changes"], {"since": "last build", "total": 1, "extras": [], "settings": []})
        res = self.apply(s, {"limiter": 8000, "f": 1.5})
        self.assertEqual(res["changes"]["settings"], [{"id": "f", "from": 800, "to": 1.5}])

    def test_a_setting_set_back_to_the_default_goes_to_the_stock_value(self):
        s = self.settings(limiter())
        self.apply(s, {"limiter": 8000})
        res = self.apply(s, {})
        self.assertEqual(res["changes"], {"since": "last build", "total": 0, "extras": [], "settings": [{"id": "limiter", "from": 8000, "to": 7000}]})
        self.assertEqual(res["applied"], [])

    def test_float_noise_between_two_builds_is_no_change(self):
        s = self.settings(mini_setting("f", targets=[("@engine", "minimum")]))
        self.apply(s, {"f": 1.1})
        self.assertEqual(self.apply(s, {"f": 1.1 + 1e-9})["changes"]["settings"], [])

    def test_the_snapshot_is_written_after_the_pack_and_not_before(self):
        seen = []
        real_pack = self.pack

        def pack(indir, pkg):
            seen.append(os.path.exists(self.snapshot_file()))
            real_pack(indir, pkg)
        self.patch(kspkg, "cmd_pack", pack)
        self.apply(self.settings())
        self.assertEqual((seen, os.path.isfile(self.snapshot_file())), ([False], True))
        self.apply(self.settings())
        self.assertEqual(seen, [False, True])

    def test_a_failed_build_or_pack_leaves_no_snapshot_and_keeps_the_previous_one(self):
        s = self.settings(limiter())
        for error_name, error in (("build_error", ValueError("disk full")), ("pack_error", OSError(28, "No space left on device"))):
            with self.subTest(error_name):
                shutil.rmtree(os.path.join(self.work, "ks_x", "snapshots"), ignore_errors=True)
                setattr(self, error_name, error)
                with self.assertRaises((ValueError, OSError)):
                    self.apply(s, {"limiter": 8000})
                self.assertFalse(os.path.exists(os.path.dirname(self.snapshot_file())))
                setattr(self, error_name, None)
                self.apply(s, {"limiter": 8000})
                with open(self.snapshot_file(), encoding="utf-8") as f:
                    before = f.read()
                setattr(self, error_name, error)
                with self.assertRaises((ValueError, OSError)):
                    self.apply(s, {"limiter": 9000})
                with open(self.snapshot_file(), encoding="utf-8") as f:
                    self.assertEqual(f.read(), before)
                setattr(self, error_name, None)
                self.assertEqual(self.apply(s)["changes"]["settings"], [{"id": "limiter", "from": 8000, "to": 9000}])

    def test_a_failure_before_the_build_leaves_the_snapshot_alone(self):
        s = self.settings(limiter())
        self.apply(s, {"limiter": 8000})
        with open(self.snapshot_file(), encoding="utf-8") as f:
            before = f.read()
        with self.assertRaisesRegex(ValueError, "not applicable"):
            self.apply(self.settings(limiter(), mini_setting("deep", targets=[("@engine", "q.r")])), {"limiter": 9000, "deep": 1.0})
        with open(self.snapshot_file(), encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_a_missing_damaged_or_foreign_snapshot_makes_a_first_build_and_is_replaced(self):
        s = self.settings(limiter())
        self.apply(s, {"limiter": 8000})
        good = os.path.getsize(self.snapshot_file())
        for text in ("", "{", "[]", '{"version": 2, "settings": {}}', '{"version": 1, "settings": []}'):
            with self.subTest(text):
                self.write(self.snapshot_file(), text)
                res = self.apply(s)
                self.assertEqual((res["changes"]["since"], res["changes"]["settings"]), (None, [{"id": "limiter", "from": 7000, "to": 8000}]))
                self.assertEqual(os.path.getsize(self.snapshot_file()), good)
        os.remove(self.snapshot_file())
        self.assertIsNone(self.apply(s)["changes"]["since"])

    def test_the_build_does_not_depend_on_the_snapshot(self):
        s = self.settings(limiter(), mini_setting("f", targets=[("@engine", "minimum")]))
        state = {"limiter": 8000, "f": 1.5, "name_suffix": "_Z"}

        def built():
            self.calls.clear()
            res = self.apply(s, state)
            root = self.fc.key(res["build_dir"])
            with open(res["package"], "rb") as f:
                package = f.read()
            return (res["notes"], res["applied"], res["size"], res["name_suffix"], list(self.calls), package,
                    {k[len(root):]: json.dumps(v, sort_keys=True) for k, v in self.fc.store.items() if k.startswith(root + os.sep)},
                    sorted(os.path.relpath(os.path.join(dp, n), res["build_dir"]) for dp, _, names in os.walk(res["build_dir"]) for n in names))
        first = built()
        self.assertTrue(os.path.isfile(self.snapshot_file()))
        with_snapshot = built()
        os.remove(self.snapshot_file())
        without = built()
        self.write(self.snapshot_file(), "damaged")
        damaged = built()
        self.assertEqual((with_snapshot, without, damaged), (first, first, first))

    def test_every_modded_car_has_its_own_snapshot_and_a_new_id_is_a_first_build(self):
        s = self.settings(limiter())
        self.modded({"limiter": 8000, "name_suffix": "_A"})
        tune.save_state(self.work, "ks_x", {"limiter": 7500, "name_suffix": "MY"})
        default = self.apply(s)
        self.assertEqual(self.apply(s)["changes"]["since"], "last build")
        second = self.apply(s, new_id="ax01")
        self.assertEqual((second["changes"]["since"], second["changes"]["settings"]), (None, [{"id": "name_suffix", "from": "MY", "to": "_A"},
                                                                                           {"id": "limiter", "from": 7000, "to": 8000}]))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.snapshot_file()))), ["ax01.json", "ax_x.json"])
        self.modded({"limiter": 8500, "name_suffix": "_A"})
        self.assertEqual(self.apply(s, new_id="ax01")["changes"]["settings"], [{"id": "limiter", "from": 8000, "to": 8500}])
        self.assertEqual(self.apply(s)["changes"]["settings"], [])
        self.assertEqual(default["changes"]["total"], 1)

    def test_duplicate_does_not_copy_the_snapshot(self):
        s = self.settings(limiter())
        self.patch(tune, "load_catalogue", lambda path=None: s)
        self.apply(s, {"limiter": 8000})
        dup = tune.duplicate_tune(self.work, "ks_x", None, "ax01")
        self.assertFalse(os.path.exists(self.snapshot_file("ax01")))
        res = self.apply(s, new_id=dup["id"])
        self.assertEqual((res["changes"]["since"], res["changes"]["total"]), (None, 2))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.snapshot_file()))), ["ax01.json", "ax_x.json"])

    def test_no_install_builds_write_the_snapshot_too_and_so_do_installing_builds(self):
        s = self.settings(limiter())
        res = self.apply(s, {"limiter": 8000}, install=False)
        self.assertEqual((res["installed"], res["changes"]["since"], os.path.isfile(self.snapshot_file())), (None, None, True))
        mods = str(self.d / "mods")
        res = self.apply(s, {"limiter": 9000}, install=True, mods_dir=mods)
        self.assertTrue(res["installed"])
        self.assertEqual(res["changes"], {"since": "last build", "total": 1, "extras": [], "settings": [{"id": "limiter", "from": 8000, "to": 9000}]})

    def test_the_name_of_the_build_is_in_the_snapshot(self):
        self.apply(self.settings(), {"name_suffix": "_Z"})
        with open(self.snapshot_file(), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["name"], "Car X _Z")

    def test_the_snapshot_holds_the_changes_of_its_build_as_json(self):
        s = self.settings(limiter())
        for state in ({"limiter": 8000}, {"limiter": 9000}, {}):
            res = self.apply(s, state)
            with open(self.snapshot_file(), encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["changes"], res["changes"])
            self.assertEqual(json.loads(json.dumps(saved["changes"], allow_nan=False)), res["changes"])
            self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["changes"], res["changes"])
        self.assertEqual(res["changes"]["settings"], [{"id": "limiter", "from": 9000, "to": 7000}])

    def test_a_snapshot_without_changes_is_a_valid_previous_build(self):
        s = self.settings(limiter())
        self.apply(s, {"limiter": 8000})
        with open(self.snapshot_file(), encoding="utf-8") as f:
            older = json.load(f)
        del older["changes"]
        self.write(self.snapshot_file(), older)
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x"), older)
        res = self.apply(s, {"limiter": 9000})
        self.assertEqual(res["changes"], {"since": "last build", "total": 1, "extras": [], "settings": [{"id": "limiter", "from": 8000, "to": 9000}]})
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["changes"], res["changes"])

    def test_the_changes_stored_in_the_previous_snapshot_do_not_touch_the_delta(self):
        s = self.settings(limiter())
        first = self.apply(s, {"limiter": 8000})
        with open(self.snapshot_file(), encoding="utf-8") as f:
            stored = json.load(f)
        want = {"since": "last build", "total": 1, "extras": [], "settings": [{"id": "limiter", "from": 8000, "to": 9000}]}
        for junk in (None, "text", [], {"since": "x", "settings": 5, "total": "many"}, first["changes"]):
            with self.subTest(junk=junk):
                self.write(self.snapshot_file(), dict(stored, changes=junk))
                self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["changes"], junk)
                self.assertEqual(self.apply(s, {"limiter": 9000})["changes"], want)


RECORD_CAT = mini_catalogue(suffix(), mini_setting("limiter", type="int", targets=[("@engine", "limiter")]),
                            mini_setting("f", targets=[("@engine", "minimum")]), mini_setting("g", targets=[("@engine", "maximum")]),
                            mini_setting("mode", type="enum", choices=["a", "b"], targets=[("@engine", "mode")]),
                            mini_setting("aids", kind="flag", type="bool", value=0, targets=[("@car", "aids")]))
RECORD_ROWS = [{"id": "name_suffix", "default": "MY"}, {"id": "limiter", "default": 7000}, {"id": "f", "default": 0.5}, {"id": "g", "default": 2.0},
               {"id": "mode", "default": "a"}, {"id": "aids", "default": False}]
KIT_A = {"donor": "ks_a", "label": "Single A", "kind": "single turbo", "boost": [0.8]}
KIT_B = {"donor": "ks_b", "label": "Twin B", "kind": "twin turbo", "boost": [1.0, 1.2]}
GARAGE_AB = {"keys": ["own:fast", "stock:a|b"], "start": "own:fast"}
GARAGE_B = {"keys": ["stock:a|b"], "start": "stock:a|b"}
T_EVENT, T_RX7_EVENT, B_EVENT = "event:/parts/turbos/turbo_none", "event:/parts/turbos/turbo_rx7", "event:/parts/backfires/backfire_classic#8"


def record(settings=None, kit=None, garage=None, sounds=None):
    return {"version": 1, "settings": dict(settings or {}), "kit": kit, "garage": garage, "sounds": dict(sounds or {}), "name": "Car X MY",
            "time": "2026-11-15T10:00:00Z"}


def changes(previous, current):
    return tune.build_changes(previous, current, RECORD_CAT, RECORD_ROWS)


class TestBuildChanges(unittest.TestCase):
    def test_a_first_build_lists_every_changed_setting_from_the_stock_value_in_catalogue_order(self):
        res = changes(None, record({"f": 1.5, "name_suffix": "_Z", "limiter": 8000, "aids": True}))
        self.assertEqual(res, {"since": None, "total": 4, "extras": [], "settings": [
            {"id": "name_suffix", "from": "MY", "to": "_Z"}, {"id": "limiter", "from": 7000, "to": 8000}, {"id": "f", "from": 0.5, "to": 1.5},
            {"id": "aids", "from": False, "to": True}]})

    def test_a_first_build_describes_the_kit_the_garage_and_the_sounds_as_additions(self):
        res = changes(None, record(kit=KIT_A, garage=GARAGE_AB, sounds={"turbo": T_RX7_EVENT, "backfire": B_EVENT}))
        self.assertEqual(res["since"], None)
        self.assertEqual(res["extras"], [
            {"kind": "turbo_kit", "from": None, "to": "Single A (single turbo, 0.8 bar)", "text": "Turbo kit: none -> Single A (single turbo, 0.8 bar)"},
            {"kind": "garage", "from": None, "to": "own:fast, stock:a|b", "text": "Garage tyres: own:fast, stock:a|b; starts on own:fast"},
            {"kind": "sound", "slot": "turbo", "from": None, "to": T_RX7_EVENT, "text": "Sound turbo: own sound -> turbo_rx7"},
            {"kind": "sound", "slot": "backfire", "from": None, "to": B_EVENT, "text": "Sound backfire: own sound -> backfire_classic#8"}])

    def test_a_first_build_without_anything_has_no_settings_and_no_extras(self):
        self.assertEqual(changes(None, record()), {"since": None, "settings": [], "extras": [], "total": 0})

    def test_an_unchanged_build_has_no_changes_but_the_total(self):
        same = record({"limiter": 8000, "f": 1.5}, KIT_A, GARAGE_AB, {"turbo": T_RX7_EVENT})
        self.assertEqual(changes(same, copy_of(same)), {"since": "last build", "settings": [], "extras": [], "total": 2})

    def test_a_changed_value_goes_from_the_previous_value(self):
        res = changes(record({"limiter": 8000, "f": 1.5}), record({"limiter": 9000, "f": 1.5}))
        self.assertEqual(res["settings"], [{"id": "limiter", "from": 8000, "to": 9000}])

    def test_a_new_setting_goes_from_the_stock_value(self):
        res = changes(record({"limiter": 8000}), record({"limiter": 8000, "f": 1.5, "mode": "b"}))
        self.assertEqual(res["settings"], [{"id": "f", "from": 0.5, "to": 1.5}, {"id": "mode", "from": "a", "to": "b"}])
        self.assertEqual(res["total"], 3)

    def test_a_setting_set_back_to_the_default_goes_to_the_stock_value(self):
        res = changes(record({"limiter": 8000, "aids": True, "f": 1.5}), record({"f": 1.5}))
        self.assertEqual(res, {"since": "last build", "total": 1, "extras": [], "settings": [
            {"id": "limiter", "from": 8000, "to": 7000}, {"id": "aids", "from": True, "to": False}]})

    def test_float_noise_is_ignored_but_a_real_difference_is_not(self):
        res = changes(record({"f": 1.1, "g": 3.0}), record({"f": 1.1 + 1e-9, "g": 3.0001}))
        self.assertEqual(res["settings"], [{"id": "g", "from": 3.0, "to": 3.0001}])

    def test_an_int_is_not_compared_with_a_tolerance(self):
        self.assertEqual(len(changes(record({"limiter": 8000}), record({"limiter": 8001}))["settings"]), 1)

    def test_a_previous_value_of_the_wrong_kind_is_a_change_and_does_not_break(self):
        res = changes(record({"f": "text", "g": True}), record({"f": 1.5, "g": 2.0}))
        self.assertEqual(res["settings"], [{"id": "f", "from": "text", "to": 1.5}, {"id": "g", "from": True, "to": 2.0}])

    def test_a_setting_that_the_catalogue_does_not_know_any_more_is_left_out(self):
        res = changes(record({"gone": 5, "limiter": 8000}), record({"limiter": 8000}))
        self.assertEqual((res["settings"], res["total"]), ([], 1))

    def test_the_stock_value_is_the_plain_number_of_a_float32_default(self):
        f32 = tune.to_f32(0.1)
        rows = [dict(r, default=f32) if r["id"] == "f" else r for r in RECORD_ROWS]
        res = tune.build_changes(None, record({"f": 0.25}), RECORD_CAT, rows)
        self.assertEqual(res["settings"], [{"id": "f", "from": 0.1, "to": 0.25}])
        self.assertIs(type(res["settings"][0]["from"]), float)

    def test_a_kit_added_changed_and_removed(self):
        added = changes(record(), record(kit=KIT_A))
        self.assertEqual(added["extras"], [{"kind": "turbo_kit", "from": None, "to": "Single A (single turbo, 0.8 bar)",
                                            "text": "Turbo kit: none -> Single A (single turbo, 0.8 bar)"}])
        swapped = changes(record(kit=KIT_A), record(kit=KIT_B))
        self.assertEqual(swapped["extras"], [{"kind": "turbo_kit", "from": "Single A (single turbo, 0.8 bar)", "to": "Twin B (twin turbo, 1.0/1.2 bar)",
                                              "text": "Turbo kit: Single A (single turbo, 0.8 bar) -> Twin B (twin turbo, 1.0/1.2 bar)"}])
        removed = changes(record(kit=KIT_B), record())
        self.assertEqual(removed["extras"], [{"kind": "turbo_kit", "from": "Twin B (twin turbo, 1.0/1.2 bar)", "to": None,
                                              "text": "Turbo kit: Twin B (twin turbo, 1.0/1.2 bar) -> none"}])

    def test_the_same_donor_with_other_details_is_no_change_and_a_kit_without_boost_has_no_bar(self):
        self.assertEqual(changes(record(kit=KIT_A), record(kit=dict(KIT_A, label="Renamed", boost=[0.9])))["extras"], [])
        res = changes(record(), record(kit=dict(KIT_A, boost=[])))
        self.assertEqual(res["extras"][0]["text"], "Turbo kit: none -> Single A (single turbo)")

    def test_garage_tyres_added_and_removed(self):
        res = changes(record(garage=GARAGE_B), record(garage=GARAGE_AB))
        self.assertEqual(res["extras"], [{"kind": "garage", "from": "stock:a|b", "to": "own:fast, stock:a|b",
                                          "text": "Garage tyres: +own:fast; starts on own:fast"}])
        res = changes(record(garage=GARAGE_AB), record(garage=GARAGE_B))
        self.assertEqual(res["extras"][0]["text"], "Garage tyres: -own:fast; starts on stock:a|b")
        both = changes(record(garage={"keys": ["own:a", "stock:x"], "start": "own:a"}), record(garage={"keys": ["own:b", "stock:x"], "start": "own:b"}))
        self.assertEqual(both["extras"][0]["text"], "Garage tyres: +own:b, -own:a; starts on own:b")

    def test_garage_start_changes_alone_and_the_order_alone(self):
        res = changes(record(garage={"keys": ["own:a", "own:b"], "start": "own:a"}), record(garage={"keys": ["own:b", "own:a"], "start": "own:b"}))
        self.assertEqual(res["extras"][0]["text"], "Garage tyres: other order; starts on own:b")
        res = changes(record(garage={"keys": ["own:a", "own:b"], "start": "own:a"}), record(garage={"keys": ["own:a", "own:b"], "start": "own:b"}))
        self.assertEqual(res["extras"][0]["text"], "Garage tyres: other order; starts on own:b")

    def test_a_garage_selection_that_is_gone_or_new(self):
        res = changes(record(garage=GARAGE_AB), record())
        self.assertEqual(res["extras"], [{"kind": "garage", "from": "own:fast, stock:a|b", "to": None,
                                          "text": "Garage tyres: stock compounds again (were own:fast, stock:a|b)"}])
        res = changes(record(), record(garage=GARAGE_B))
        self.assertEqual(res["extras"][0]["text"], "Garage tyres: stock:a|b; starts on stock:a|b")

    def test_a_sound_slot_changed_added_and_removed(self):
        res = changes(record(sounds={"turbo": T_EVENT, "backfire": B_EVENT}), record(sounds={"turbo": T_RX7_EVENT}))
        self.assertEqual(res["extras"], [
            {"kind": "sound", "slot": "turbo", "from": T_EVENT, "to": T_RX7_EVENT, "text": "Sound turbo: turbo_none -> turbo_rx7"},
            {"kind": "sound", "slot": "backfire", "from": B_EVENT, "to": None, "text": "Sound backfire: backfire_classic#8 -> own sound"}])
        res = changes(record(sounds={"turbo": T_RX7_EVENT}), record(sounds={"turbo": T_RX7_EVENT, "backfire": B_EVENT}))
        self.assertEqual(res["extras"], [{"kind": "sound", "slot": "backfire", "from": None, "to": B_EVENT, "text": "Sound backfire: own sound -> backfire_classic#8"}])

    def test_an_unchanged_sound_slot_is_no_extra(self):
        same = record(sounds={"turbo": T_RX7_EVENT, "backfire": B_EVENT})
        self.assertEqual(changes(same, copy_of(same))["extras"], [])

    def test_the_extras_come_in_the_order_kit_garage_turbo_backfire(self):
        res = changes(record(), record(kit=KIT_A, garage=GARAGE_B, sounds={"backfire": B_EVENT, "turbo": T_RX7_EVENT}))
        self.assertEqual([(e["kind"], e.get("slot")) for e in res["extras"]], [("turbo_kit", None), ("garage", None), ("sound", "turbo"), ("sound", "backfire")])

    def test_nothing_is_read_or_changed(self):
        previous, current = record({"limiter": 8000}, KIT_A), record({"limiter": 9000})
        before = copy_of(previous), copy_of(current)
        res = changes(previous, current)
        json.dumps(res, allow_nan=False)
        self.assertEqual((previous, current), before)


def copy_of(data):
    return json.loads(json.dumps(data))


class TestChangeLines(unittest.TestCase):
    def res(self, since, settings=(), extras=(), total=0, notes=("note: a", "note: b")):
        return {"changes": {"since": since, "settings": list(settings), "extras": list(extras), "total": total}, "notes": list(notes)}

    def test_a_first_build_names_the_total_and_lists_everything_then_the_notes(self):
        res = self.res(None, [{"id": "limiter", "from": 7000, "to": 8000}, {"id": "f", "from": 0.5, "to": 1.5}, {"id": "aids", "from": False, "to": True},
                              {"id": "v", "from": None, "to": "x"}],
                       [{"kind": "turbo_kit", "from": None, "to": "A", "text": "Turbo kit: none -> A"}], total=4)
        self.assertEqual(tune.change_lines(res), [
            "first build of this car: 4 changed settings compared to the stock car", "  limiter: 7000 -> 8000", "  f: 0.5 -> 1.5", "  aids: false -> true",
            "  v: - -> x", "  Turbo kit: none -> A", "note: a", "note: b"])

    def test_a_later_build_counts_settings_and_extras_and_names_the_total(self):
        res = self.res("last build", [{"id": "limiter", "from": 8000, "to": 9000}],
                       [{"kind": "sound", "slot": "turbo", "from": None, "to": "e", "text": "Sound turbo: own sound -> turbo_rx7"}], total=7)
        self.assertEqual(tune.change_lines(res), [
            "2 change(s) since the last build (7 changed settings compared to the stock car in total)", "  limiter: 8000 -> 9000",
            "  Sound turbo: own sound -> turbo_rx7", "note: a", "note: b"])

    def test_an_empty_delta_says_so(self):
        self.assertEqual(tune.change_lines(self.res("last build", total=3, notes=())),
                         ["no change since the last build (3 changed settings compared to the stock car in total)"])

    def test_the_applied_list_and_its_files_are_not_printed_and_the_result_is_not_changed(self):
        res = dict(self.res("last build", total=1), applied=[{"id": "limiter", "old": 7000, "new": 8000, "files": ["data/x.car"]}])
        before = copy_of(res)
        lines = tune.change_lines(res)
        self.assertFalse([line for line in lines if "limiter" in line or "applied" in line or "data/x.car" in line])
        lines.append("more")
        self.assertEqual(res, before)


class TestSnapshotFile(Base):
    def test_the_snapshot_of_a_modded_car_lives_below_its_stock_car(self):
        self.assertEqual(tune.snapshot_path(self.work, "ks_x", "ax01"), os.path.join(self.work, "ks_x", "snapshots", "ax01.json"))

    def test_save_and_load_round_trip_and_leave_no_temporary_file(self):
        data = record({"limiter": 8000, "f": 1.5, "name_suffix": "_Z", "aids": True}, KIT_B, GARAGE_AB, {"turbo": T_RX7_EVENT})
        tune.save_snapshot(self.work, "ks_x", "ax01", data)
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax01"), data)
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "snapshots")), ["ax01.json"])
        tune.save_snapshot(self.work, "ks_x", "ax01", record())
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax01"), record())

    def test_a_missing_file_or_folder_is_no_previous_build(self):
        self.assertIsNone(tune.load_snapshot(self.work, "ks_x", "ax01"))
        tune.save_snapshot(self.work, "ks_x", "ax01", record())
        self.assertIsNone(tune.load_snapshot(self.work, "ks_x", "ax02"))

    def test_a_damaged_or_foreign_file_is_ignored(self):
        path = tune.snapshot_path(self.work, "ks_x", "ax01")
        good = record({"f": 1.5}, KIT_A, GARAGE_AB, {"turbo": T_RX7_EVENT})
        bad = [b"", b"{", b"\xff\xfe\x00", b"null", b"[]", b'"text"', b'{"version": 1, "settings": {"f": NaN}, "kit": null, "garage": null, "sounds": {}, "name": "n", "time": "t"}']
        bad += [json.dumps(dict(good, **change)).encode() for change in (
            {"version": 2}, {"version": "1"}, {"version": True}, {"settings": []}, {"settings": {"f": None}}, {"settings": {"f": [1]}}, {"settings": {"f": {"a": 1}}},
            {"kit": []}, {"kit": dict(KIT_A, donor=5)}, {"kit": dict(KIT_A, boost="1")}, {"kit": dict(KIT_A, boost=[None])}, {"kit": {"donor": "x"}},
            {"garage": []}, {"garage": {"keys": "a", "start": "a"}}, {"garage": {"keys": [1], "start": "a"}}, {"garage": {"keys": ["a"]}},
            {"sounds": []}, {"sounds": {"turbo": 5}}, {"name": 5}, {"time": None})]
        bad += [json.dumps({k: v for k, v in good.items() if k != missing}).encode() for missing in good]
        for text in bad:
            with self.subTest(text[:60]):
                self.write(path, text, binary=True)
                self.assertIsNone(tune.load_snapshot(self.work, "ks_x", "ax01"))
        self.write(path, json.dumps(good), binary=False)
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax01"), good)

    def test_the_changes_key_is_optional_and_its_content_is_not_checked(self):
        changes_of_a_build = {"since": None, "settings": [{"id": "f", "from": 0.5, "to": 1.5}], "extras": [], "total": 1}
        for extra in ({}, {"changes": changes_of_a_build}, {"changes": None}, {"changes": "text"}, {"changes": [1, 2]}):
            with self.subTest(extra=extra):
                data = dict(record({"f": 1.5}), **extra)
                self.assertTrue(tune.valid_snapshot(data))
                tune.save_snapshot(self.work, "ks_x", "ax01", data)
                self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax01"), data)

    def test_a_snapshot_with_a_utf8_bom_is_read(self):
        self.write(tune.snapshot_path(self.work, "ks_x", "ax01"), b"\xef\xbb\xbf" + json.dumps(record({"f": 1.5})).encode(), binary=True)
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax01"), record({"f": 1.5}))


class TestMakeSnapshot(Base):
    def plan(self, kit=None, garage=None, sounds=()):
        return {"kit": kit, "garage": garage, "sounds": list(sounds)}

    def test_the_record_of_a_plain_build(self):
        applied = [{"id": "limiter", "old": 7000, "new": 8000, "files": ["a"]}, {"id": "f", "old": tune.to_f32(0.1), "new": 0.25, "files": []}]
        data = tune.make_snapshot(self.work, self.plan(), applied, "Car X MY")
        self.assertRegex(data.pop("time"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(data, {"version": 1, "settings": {"limiter": 8000, "f": 0.25}, "kit": None, "garage": None, "sounds": {}, "name": "Car X MY"})

    def test_the_new_values_are_plain_numbers(self):
        applied = [{"id": "f", "old": 0.0, "new": tune.to_f32(0.1), "files": []}]
        data = tune.make_snapshot(self.work, self.plan(), applied, "n")
        self.assertEqual(json.dumps(data["settings"]), '{"f": 0.1}')

    def test_the_kit_garage_and_sounds(self):
        donors = [{"car": "ks_b", "label": "Twin B", "count": 2, "kind": "twin turbo", "boost": [1.0, 1.2]}]
        kit = {"donor": "ks_b", "kind": "twin turbo", "files": [], "fields": [], "inline_fields": [], "stamp": []}
        garage = {"entries": [{"key": "own:fast", "label": "Fast"}, {"key": "stock:a|b", "label": "A"}]}
        sounds = [{"slot": "turbo", "option": {"key": T_RX7_EVENT}, "template": {}}, {"slot": "backfire", "option": {"key": B_EVENT}, "template": {}}]
        with mock.patch.object(tune, "turbo_donor", lambda work, car_id, names: donors[0] if car_id == "ks_b" else None):
            data = tune.make_snapshot(self.work, self.plan(kit, garage, sounds), [], "n")
        self.assertEqual((data["kit"], data["garage"], data["sounds"]), (
            {"donor": "ks_b", "label": "Twin B", "kind": "twin turbo", "boost": [1.0, 1.2]}, GARAGE_AB,
            {"turbo": T_RX7_EVENT, "backfire": B_EVENT}))
        json.dumps(data, allow_nan=False)

    def test_a_donor_that_is_not_listed_any_more_keeps_its_id_as_the_label(self):
        kit = {"donor": "ks_gone", "kind": "single turbo"}
        with mock.patch.object(tune, "turbo_donor", lambda work, car_id, names: None):
            data = tune.make_snapshot(self.work, self.plan(kit), [], "n")
        self.assertEqual(data["kit"], {"donor": "ks_gone", "label": "ks_gone", "kind": "single turbo", "boost": []})
        self.assertTrue(tune.valid_snapshot(data))

    def test_a_record_it_makes_is_valid(self):
        self.assertTrue(tune.valid_snapshot(tune.make_snapshot(self.work, self.plan(), [{"id": "x", "old": 1, "new": True, "files": []}], "n")))


# --------------------------------------------------------------------------------------------- error chains
class TestErrorChains(Base):
    def test_to_f32_error_is_not_chained(self):
        with self.assertRaises(ValueError) as cm:
            tune.to_f32(1e300)
        not_chained(self, cm.exception)

    def test_coerce_float_error_is_not_chained(self):
        with self.assertRaises(ValueError) as cm:
            tune.coerce(mini_setting("f"), "abc")
        not_chained(self, cm.exception)

    def test_load_msg_read_error_is_not_chained(self):
        with self.assertRaises(ValueError) as cm:
            tune.load_msg(os.path.join(self.work, "missing.car"))
        not_chained(self, cm.exception)

    def test_save_msg_encode_error_is_not_chained(self):
        self.patch(car_json, "load_schema", lambda path=None: {})

        def encode(sch, name, obj):
            raise ValueError("cannot encode")
        self.patch(car_json, "encode_msg", encode)
        with self.assertRaises(ValueError) as cm:
            tune.save_msg(os.path.join(self.work, "x.car"), "CarData", {})
        not_chained(self, cm.exception)

    def test_find_ci_listing_error_is_not_chained(self):
        with self.assertRaises(ValueError) as cm:
            tune.find_ci(os.path.join(self.work, "no_such_folder"), "a/b")
        not_chained(self, cm.exception)

    def test_tyre_found_error_is_not_chained(self):
        os.makedirs(self.work)
        with self.assertRaises(ValueError) as cm:
            tune.tyre_found(self.work, "content\\cars\\common_phsx\\a.tyre")
        not_chained(self, cm.exception)

    def test_the_messages_themselves(self):
        with self.assertRaisesRegex(ValueError, "missing.car: "):
            tune.load_msg(os.path.join(self.work, "missing.car"))
        with self.assertRaisesRegex(ValueError, "a not found in|no_such_folder"):
            tune.find_ci(os.path.join(self.work, "no_such_folder"), "a/b")
        os.makedirs(self.work)
        with self.assertRaisesRegex(ValueError, tune.TYRE_UNAVAILABLE):
            tune.tyre_found(self.work, "content\\x.tyre")


class TestStdoutCapture(Base):
    def test_overlapping_captures_restore_stdout(self):
        real = sys.stdout
        self.addCleanup(setattr, sys, "stdout", real)
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        a_in, b_in, a_out = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def extract(pkg, outdir, prefix=None):
            self.write(os.path.join(outdir, "f.txt"), b"d", binary=True)
            if threading.current_thread().name == "A":
                a_in.set()
                b_in.wait(1.5)
            else:
                a_in.wait(1.5)
                b_in.set()
                a_out.wait(1.5)
        self.patch(kspkg, "cmd_extract", extract)

        def run(name, work):
            try:
                tune.read_game_file(work, game, "f.txt")
            except Exception as e:
                errors.append(e)
            if name == "A":
                a_out.set()
        threads = [threading.Thread(target=run, args=(n, os.path.join(self.work, n)), name=n) for n in "AB"]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        stdout_after = sys.stdout
        sys.stdout = real
        self.assertEqual(errors, [])
        self.assertIs(stdout_after, real)

    def test_single_capture_restores_stdout(self):
        real = sys.stdout
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        self.patch(kspkg, "cmd_extract", lambda pkg, outdir, prefix=None: self.write(os.path.join(outdir, "f.txt"), b"d", binary=True))
        self.assertEqual(tune.read_game_file(self.work, game, "f.txt"), b"d")
        self.assertIs(sys.stdout, real)


# --------------------------------------------------------------------------------------------- CLI
class TestParseAndTable(unittest.TestCase):
    def test_parse_args_positionals_options_and_switches(self):
        pos, opts = tune.parse_args(["a", "--car", "x", "b", "--hidden", "--work", "w"], ("car", "work"), ("hidden",))
        self.assertEqual((pos, opts), (["a", "b"], {"car": "x", "hidden": True, "work": "w"}))

    def test_parse_args_unknown_option_and_missing_value(self):
        with self.assertRaisesRegex(ValueError, "bad option --bogus"):
            tune.parse_args(["--bogus", "1"], ("car",))
        with self.assertRaisesRegex(ValueError, "--car"):
            tune.parse_args(["--car"], ("car",))
        with self.assertRaisesRegex(ValueError, "bad option --hidden"):
            tune.parse_args(["--hidden"], ("car",))

    def test_table_pads_columns_and_strips_trailing_blanks(self):
        self.assertEqual(tune.table(["a", "bb"], [["x", "yyy"], ["zz", 1]]), "a  | bb\n---+----\nx  | yyy\nzz | 1")

    def test_consistency_text(self):
        self.assertEqual(tune.consistency_text({"targets": [], "consistent": True}), "yes")
        self.assertEqual(tune.consistency_text({"targets": [{"resolved": True, "value": 1}], "consistent": True}), "yes")
        row = {"targets": [{"resolved": True, "value": 1}, {"resolved": False, "value": 5}, {"resolved": True, "value": 2.5}], "consistent": False}
        self.assertEqual(tune.consistency_text(row), "NO (1 / 2.5)")


class TestCommands(CarCase):
    def setUp(self):
        super().setUp()
        self.cars(("ks_x", "Car X"))
        self.stock_info()
        self.cat = mini_catalogue(*metas(), limiter(), mini_setting("m", type="int", targets=[("@engine", "minimum"), ("@car", "engine.minimum", True)]),
                                  mini_setting("deep", targets=[("@engine", "q.r")]))
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)

    def main(self, *argv):
        return self.run_main(*argv, "--work", self.work)

    def test_defaults_prints_the_table_and_the_hidden_count(self):
        code, out, err = self.main("defaults")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0].split(" | ")[0].strip(), "id")
        self.assertIn("limiter", out)
        self.assertNotIn("deep", out.split("hidden")[0])
        self.assertIn("1 hidden for this car (not applicable)", out)

    def test_defaults_hidden_lists_each_hidden_setting_with_its_reason(self):
        code, out, err = self.main("defaults", "--hidden")
        self.assertIn("  deep: @engine q.r: missing field 'q'\n", out)

    def test_variants_prints_the_roles_the_members_not_shown_and_the_errors(self):
        self.patch(tune, "load_cars_index", lambda work, game=None: None)
        add_variant(self.fc)
        add_variant(self.fc, "r_broken", "Broken", parts=("engine",))
        os.remove(os.path.join(self.fc.car_root, "presets", "parts", "r_broken_engine.carpart"))
        code, out, err = self.main("variants")
        lines = out.splitlines()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[:6], ["q_drift: Drift", "  preset: presets/q_drift.mechanicalcarpreset", "  @engine = data/drift.carengine",
                                     "  @setup = data/drift.carsetup", "  not shown: suspensions_geometry", "r_broken: Broken"])
        self.assertTrue(lines[7].startswith("  error: ") and "r_broken_engine.carpart not found" in lines[7])

    def test_variants_of_a_car_without_any_says_so(self):
        self.patch(tune, "load_cars_index", lambda work, game=None: None)
        self.assertEqual(self.main("variants"), (0, "ks_x has no variants\n", ""))

    def test_defaults_with_a_variant_prints_its_values(self):
        self.patch(tune, "load_cars_index", lambda work, game=None: None)
        add_variant(self.fc)
        code, out, err = self.main("defaults", "--variant", "q_drift")
        self.assertEqual((code, err), (0, ""))
        row = [c.strip() for c in next(l for l in out.splitlines() if l.startswith("limiter")).split(" | ")]
        self.assertEqual(row[2], "8000")
        self.assertEqual(self.main("defaults", "--variant", "nope")[::2], (1, "error: ks_x has no variant nope\n"))

    def test_defaults_lists_settings_whose_copies_differ(self):
        code, out, err = self.main("defaults")
        self.assertIn("copies differ in the stock data (1 setting(s), the default shown is the first required target):\n  m\n"
                      "    @engine minimum = 800\n    @car engine.minimum = 900\n", out)
        self.assertIn("NO (800 / 900)", out)

    def test_set_prints_value_and_warning_and_writes_the_state(self):
        code, out, err = self.main("set", "limiter", "20000")
        self.assertEqual((code, out, err), (0, "limiter = 20000\n", "warning: limiter=20000 is outside the suggested range 3000..12000\n"))
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 20000})

    def test_set_name_suffix(self):
        self.assertEqual(self.main("set", "name_suffix", "_Z")[1], "name_suffix = _Z\n")

    def test_set_errors_are_error_lines_with_exit_1(self):
        code, out, err = self.main("set", "limiter", "fast")
        self.assertEqual((code, out, err), (1, "", "error: limiter expects an integer, got 'fast'\n"))
        code, out, err = self.main("set", "nope", "1")
        self.assertEqual((code, out, err), (1, "", "error: unknown setting 'nope'\n"))
        code, out, err = self.main("set", "deep", "1")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: deep is not applicable to ks_x: @engine q.r"))

    def test_unset_prints_what_happened(self):
        self.main("set", "limiter", "8000")
        self.assertEqual(self.main("unset", "limiter")[1], "limiter removed from the state\n")
        self.assertEqual(self.main("unset", "limiter")[1], "limiter was not set\n")

    def test_show_marks_changed_rows_and_hides_non_applicable_ones(self):
        self.main("set", "limiter", "8000")
        code, out, err = self.main("show")
        self.assertEqual((code, err), (0, ""))
        rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")] for line in out.splitlines()[2:]}
        self.assertEqual(rows["limiter"], ["*", "limiter", "8000", "7000", ""])
        self.assertEqual(rows["name_suffix"][0:4], ["", "name_suffix", "MY", "MY"])
        self.assertNotIn("deep", rows)
        self.assertEqual(out.splitlines()[0].split("|")[1].strip(), "id")

    def test_show_warns_about_unknown_ids_and_keeps_them(self):
        tune.save_state(self.work, "ks_x", {"old": 1})
        code, out, err = self.main("show")
        self.assertEqual(code, 0)
        self.assertIn("warning: ignoring unknown setting 'old' in the saved state", out + err)
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"old": 1})

    def test_unknown_car_is_an_error_line(self):
        code, out, err = self.run_main("show", "--car", "ks_nope", "--work", self.work)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: unknown car 'ks_nope'"))

    def test_cars_table_and_note(self):
        mods = self.d / "mods"
        self.write(str(mods / "ax_x.kspkg"), b"p", binary=True)
        code, out, err = self.run_main("cars", "--work", self.work, "--mods", str(mods), "--game", os.path.join(self.work, "none.kspkg"))
        lines = out.splitlines()
        self.assertEqual([c.strip() for c in lines[0].split("|")], ["id", "display name", "extracted", "tested", "new id", "installed", "size"])
        self.assertEqual([c.strip() for c in lines[2].split("|")][:6], ["ks_x", "Car X", "yes", "yes", "ax_x", "yes"])
        self.assertRegex(lines[2], r"\d+\.\d MB$")
        self.assertEqual(lines[-1], "note: no car index, only the tested cars are listed: " + GAME_MISSING % os.path.join(self.work, "none.kspkg"))

    def test_cars_note_names_the_schema_step_when_the_schemas_are_missing(self):
        game = self.write(os.path.join(self.work, "g.kspkg"), b"x", binary=True)
        real = car_json.load_schema
        self.patch(tune, "read_game_file", lambda work, game, rel: b"table")
        self.patch(car_json, "load_schema", lambda path=None: real(os.path.join(self.work, "none.desc")))
        code, out, err = self.run_main("cars", "--work", self.work, "--mods", str(self.d / "mods"), "--game", game)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[-1], "note: no car index, only the tested cars are listed: missing schema file %s: run once  python tools/extract_protos.py "
                         "<path of AssettoCorsaEVOEditor.exe in the Assetto Corsa EVO SDK folder> schemas  (see docs/USER_GUIDE.md)" % os.path.join(self.work, "none.desc"))

    def test_apply_is_refused_while_the_game_runs(self):
        self.patch(tune, "game_running", lambda: True)
        built = []
        self.patch(clone_car, "build", lambda *a, **k: built.append(a))
        code, out, err = self.main("apply")
        self.assertEqual((code, out, err, built), (1, "", "error: the game is running, close it first\n", []))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))

    def test_apply_no_install_is_not_refused_while_the_game_runs(self):
        self.patch(tune, "game_running", lambda: True)
        applied = []
        self.patch(tune, "apply", lambda *a: applied.append(a) or {"new_id": "ax_x", "applied": [], "notes": [], "package": "p.kspkg", "size": 1,
                                                                        "changes": NO_CHANGES, "installed": None, "backup": None})
        code, out, err = self.main("apply", "--no-install")
        self.assertEqual((code, err, [a[3] for a in applied]), (0, "", [False]))
        self.assertIn("package: p.kspkg (1 bytes)", out)

    def test_apply_prints_the_changes_since_the_last_build_and_not_every_applied_setting(self):
        res = {"new_id": "ax_x", "package": "p.kspkg", "size": 1, "installed": "m.kspkg", "backup": None, "notes": ["note: from build"],
               "applied": [{"id": "limiter", "old": 7000, "new": 9000, "files": ["data/engine.carengine"]}, {"id": "m", "old": 900, "new": 1000, "files": ["f"]}],
               "changes": {"since": "last build", "total": 2, "settings": [{"id": "limiter", "from": 8000, "to": 9000}],
                           "extras": [{"kind": "turbo_kit", "from": None, "to": "A (single turbo, 1.0 bar)", "text": "Turbo kit: none -> A (single turbo, 1.0 bar)"}]}}
        self.patch(tune, "apply", lambda *a: res)
        code, out, err = self.main("apply")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "car: ks_x, new id: ax_x", "2 change(s) since the last build (2 changed settings compared to the stock car in total)",
            "  limiter: 8000 -> 9000", "  Turbo kit: none -> A (single turbo, 1.0 bar)", "note: from build", "package: p.kspkg (1 bytes)",
            "installed: m.kspkg", "backup: no previous install"])

    def test_apply_prints_the_first_build_and_the_empty_delta(self):
        res = {"new_id": "ax_x", "package": "p.kspkg", "size": 1, "installed": None, "backup": None, "notes": [], "applied": [],
               "changes": {"since": None, "total": 3, "settings": [{"id": "limiter", "from": 7000, "to": 9000}], "extras": []}}
        self.patch(tune, "apply", lambda *a: res)
        code, out, err = self.main("apply", "--no-install")
        self.assertEqual(out.splitlines()[1:3], ["first build of this car: 3 changed settings compared to the stock car", "  limiter: 7000 -> 9000"])
        res["changes"] = {"since": "last build", "total": 3, "settings": [], "extras": []}
        code, out, err = self.main("apply", "--no-install")
        self.assertEqual(out.splitlines()[1], "no change since the last build (3 changed settings compared to the stock car in total)")

    def test_apply_end_to_end_prints_the_first_build_then_only_the_delta(self):
        self.patch(clone_car, "build", lambda car_dir, new_id, out_dir, *a, **k: (self.fc.clone_into(out_dir, new_id), [])[1])
        self.patch(kspkg, "cmd_pack", lambda indir, pkg: open(pkg, "wb").close())
        self.patch(tune, "ensure_stock_loc", lambda work, game=None: "present")
        tune.save_state(self.work, "ks_x", {"limiter": 8000})
        code, out, err = self.main("apply", "--no-install")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[:3], ["car: ks_x, new id: ax_x", "first build of this car: 1 changed settings compared to the stock car",
                                                "  limiter: 7000 -> 8000"])
        tune.save_state(self.work, "ks_x", {"limiter": 8500})
        code, out, err = self.main("apply", "--no-install")
        self.assertEqual(out.splitlines()[1:3], ["1 change(s) since the last build (1 changed settings compared to the stock car in total)",
                                                 "  limiter: 8000 -> 8500"])
        self.assertNotIn("applied", out)
        self.assertNotIn("[data/", out)

    def test_init_is_not_refused_while_the_game_runs(self):
        self.patch(tune, "game_running", lambda: True)
        self.patch(tune, "init", lambda work, car_id, game=None: {"present": True, "dir": "d", "files": 1, "dirs": 0, "bytes": 2, "stock_loc": "present",
                                                                  "stock_info": "present", "tyre_files": "present"})
        code, out, err = self.main("init")
        self.assertEqual((code, err, out.splitlines()[0]), (0, "", "base already present"))

    def test_cars_tested_has_no_note(self):
        code, out, err = self.run_main("cars", "--tested", "--work", self.work, "--game", os.path.join(self.work, "none.kspkg"))
        self.assertNotIn("note:", out)

    def modded_car(self, *argv):
        code, out, err = self.main("duplicate", *argv)
        self.assertEqual((code, err), (0, ""), out)
        return out

    def test_duplicate_prints_the_new_id_and_suffix_and_writes_the_state(self):
        self.main("set", "limiter", "8000")
        code, out, err = self.main("duplicate")
        self.assertEqual((code, out, err), (0, "car: ks_x, new id: ax01\nname suffix: MY 2\n", ""))
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax01"), {"limiter": 8000, "name_suffix": "MY 2"})
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000})

    def test_duplicate_takes_a_source_tune_the_draft_an_id_and_a_suffix(self):
        self.main("set", "limiter", "8000")
        self.main("set", "name_suffix", "_A")
        self.assertEqual(self.modded_car("--suffix", "_B"), "car: ks_x, new id: ax01\nname suffix: _B\n")
        self.assertEqual(self.modded_car("--tune", "ax01", "--new-id", "ax05"), "car: ks_x, new id: ax05\nname suffix: _B 2\n")
        tune.save_state(self.work, "ks_x", {"limiter": 6000}, tune.DRAFT)
        self.assertEqual(self.modded_car("--draft"), "car: ks_x, new id: ax02\nname suffix: MY\n")
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax02"), {"limiter": 6000, "name_suffix": "MY"})
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax05")["limiter"], 8000)

    def test_duplicate_mods_folder_packages_take_ids(self):
        mods = self.d / "mods"
        self.write(str(mods / "ax01.kspkg"), b"p", binary=True)
        self.assertIn("new id: ax01\n", self.main("duplicate")[1])
        self.assertIn("new id: ax02\n", self.main("duplicate", "--mods", str(mods))[1])

    def test_duplicate_errors_are_error_lines_and_write_nothing(self):
        self.main("set", "name_suffix", "_A")
        before = sorted(os.listdir(os.path.join(self.work, "ks_x")))
        for argv, message in ((("--tune", "ax09"), "error: ks_x has no tune ax09\n"), (("--tune", "draft"), "error: ks_x has no tune draft\n"),
                              (("--suffix", "_A"), "error: name suffix already used by ax_x\n"), (("--new-id", "ax_x"), "error: ax_x is already a tune of ks_x\n"),
                              (("--suffix", ""), "error: name_suffix expects 1 to 30 characters without control characters\n")):
            with self.subTest(argv):
                self.assertEqual(self.main("duplicate", *argv), (1, "", message))
        code, out, err = self.main("duplicate", "--new-id", "AX01")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: new id 'AX01' may only contain"), err)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "ks_x"))), before)

    def test_cars_modded_lists_the_modded_cars(self):
        mods = self.d / "mods"
        self.main("set", "name_suffix", "_A")
        self.modded_car("--suffix", "_B")
        self.write(str(mods / "ax01.kspkg"), b"p", binary=True)
        self.write(os.path.join(tune.build_dir(self.work, "ks_x"), "ax_x", "ax_x.kspkg"), b"p", binary=True)
        code, out, err = self.run_main("cars", "--modded", "--work", self.work, "--mods", str(mods), "--game", os.path.join(self.work, "none.kspkg"))
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual([c.strip() for c in lines[0].split("|")], ["id", "stock", "label", "suffix", "installed", "built"])
        self.assertEqual([[c.strip() for c in line.split("|")] for line in lines[2:]],
                         [["ax_x", "ks_x", "Car X _A", "_A", "no", "yes"], ["ax01", "ks_x", "Car X _B", "_B", "yes", "no"]])

    def test_cars_modded_without_modded_cars_prints_only_the_header(self):
        code, out, err = self.run_main("cars", "--modded", "--work", self.work, "--mods", str(self.d / "mods"), "--game", os.path.join(self.work, "none.kspkg"))
        self.assertEqual((code, err, len(out.splitlines())), (0, "", 2))
        self.assertNotIn("note:", out)

    def test_set_unset_and_show_with_a_tune_leave_the_default_tune_alone(self):
        self.main("set", "limiter", "8000")
        self.modded_car()
        self.assertEqual(self.main("set", "limiter", "9000", "--tune", "ax01")[1], "limiter = 9000\n")
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000})
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax01"), {"limiter": 9000, "name_suffix": "MY 2"})
        shown = {tune_id: {line.split("|")[1].strip(): [c.strip() for c in line.split("|")] for line in self.main("show", *extra)[1].splitlines()[2:]}
                 for tune_id, extra in (("default", ()), ("ax01", ("--tune", "ax01")), ("ax_x", ("--tune", "ax_x")))}
        self.assertEqual(shown["default"]["limiter"], ["*", "limiter", "8000", "7000", ""])
        self.assertEqual(shown["ax01"]["limiter"], ["*", "limiter", "9000", "7000", ""])
        self.assertEqual(shown["ax01"]["name_suffix"][2], "MY 2")
        self.assertEqual(shown["ax_x"], shown["default"])
        self.assertEqual(self.main("unset", "limiter", "--tune", "ax01")[1], "limiter removed from the state\n")
        self.assertEqual(tune.load_state(self.work, "ks_x"), {"limiter": 8000})
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax01"), {"name_suffix": "MY 2"})

    def test_show_with_a_tune_warns_about_its_unknown_ids_only(self):
        self.modded_car()
        tune.save_state(self.work, "ks_x", {"old_m": 1}, "ax01")
        tune.save_state(self.work, "ks_x", {"old_d": 1})
        err = self.main("show", "--tune", "ax01")[2]
        self.assertIn("'old_m'", err)
        self.assertNotIn("old_d", err)

    def test_an_unknown_or_invalid_tune_is_an_error_line_for_every_command(self):
        self.main("set", "limiter", "8000")
        before = sorted(os.listdir(os.path.join(self.work, "ks_x")))
        for argv in (("show",), ("defaults",), ("set", "limiter", "1"), ("unset", "limiter"), ("apply", "--no-install")):
            for bad, message in (("ax09", "error: ks_x has no tune ax09\n"), ("draft", "error: ks_x has no tune draft\n")):
                with self.subTest(argv=argv, bad=bad):
                    self.assertEqual(self.main(*argv, "--tune", bad), (1, "", message))
            with self.subTest(argv=argv, bad="bad"):
                code, out, err = self.main(*argv, "--tune", "bad")
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("error: new id 'bad' has 3 characters"), err)
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "ks_x"))), before)

    def test_defaults_with_a_tune_prints_the_same_table(self):
        self.modded_car()
        self.assertEqual(self.main("defaults", "--tune", "ax01"), self.main("defaults"))

    def stub_apply(self):
        applied = []
        self.patch(tune, "apply", lambda *a: applied.append(a) or {"new_id": a[2] or "ax_x", "applied": [], "notes": [], "package": "p.kspkg", "size": 1,
                                                                    "changes": NO_CHANGES, "installed": None, "backup": None})
        return applied

    def test_apply_with_a_tune_builds_that_tune(self):
        self.modded_car()
        applied = self.stub_apply()
        code, out, err = self.main("apply", "--tune", "ax01", "--no-install")
        self.assertEqual((code, err, [a[2] for a in applied]), (0, "", ["ax01"]))
        self.assertIn("car: ks_x, new id: ax01\n", out)
        self.main("apply", "--tune", "ax_x", "--no-install")
        self.main("apply", "--no-install")
        self.main("apply", "--new-id", "ax07", "--no-install")
        self.assertEqual([a[2] for a in applied], ["ax01", "ax_x", None, "ax07"])

    def test_apply_with_a_tune_and_a_new_id_is_an_error_before_anything_happens(self):
        self.modded_car()
        applied = self.stub_apply()
        self.patch(tune, "game_running", lambda: self.fail("the game check comes after the option check"))
        code, out, err = self.main("apply", "--tune", "ax01", "--new-id", "ax02")
        self.assertEqual((code, out, err, applied), (1, "", "error: --tune and --new-id cannot be combined\n", []))

    def test_apply_warns_about_the_unknown_ids_of_the_tune_it_builds(self):
        self.modded_car()
        tune.save_state(self.work, "ks_x", {"old_m": 1}, "ax01")
        self.stub_apply()
        code, out, err = self.main("apply", "--tune", "ax01", "--no-install")
        self.assertEqual(err, "warning: ignoring unknown setting 'old_m' in the saved state\n")

    def test_show_opens_the_catalogue_once(self):
        self.patch(tune, "load_catalogue", REAL_LOAD_CATALOGUE)
        self.patch(tune, "resolve_defaults", lambda work, car, cat=None, game=None, hidden=False, **_: [
            {"id": s["id"], "applicable": True, "reason": None, "default": tune.zero(s), "unit": s["unit"], "group": s["group"],
             "targets": [], "absent": False, "consistent": True, "copies_differ": False} for s in (cat or tune.load_catalogue())["settings"]])
        opened = []
        real_open = builtins.open
        tune._catalogue_loaded.clear()

        def spy(file, *a, **k):
            if str(file).endswith("catalogue.json"):
                opened.append(str(file))
            return real_open(file, *a, **k)
        with mock.patch.object(builtins, "open", spy):
            code, out, err = self.run_main("show", "--work", self.work)
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)


class TestGameRunning(unittest.TestCase):
    def running(self, **kw):
        with mock.patch.object(tune.subprocess, "run", **kw) as run:
            return tune.game_running(), run

    def done(self, code, out):
        return mock.Mock(return_value=tune.subprocess.CompletedProcess([], code, stdout=out, stderr=b""))

    def test_the_image_name_is_looked_up_with_tasklist(self):
        found, run = self.running(new=self.done(0, b'"AssettoCorsaEVO.exe","1234","Console","1","9,999 K"\r\n'))
        self.assertTrue(found)
        self.assertEqual(run.call_args[0][0], ["tasklist", "/FI", "IMAGENAME eq AssettoCorsaEVO.exe", "/NH", "/FO", "CSV"])

    def test_no_matching_task_is_not_running(self):
        self.assertFalse(self.running(new=self.done(0, b"INFO: No tasks are running which match the specified criteria.\r\n"))[0])

    def test_a_failing_tasklist_is_not_running(self):
        self.assertFalse(self.running(new=self.done(1, b'"AssettoCorsaEVO.exe"'))[0])

    def test_a_missing_tasklist_is_not_running(self):
        self.assertFalse(self.running(side_effect=FileNotFoundError("tasklist"))[0])


class TestUsageText(unittest.TestCase):
    def usage_lines(self):
        return [line.strip() for line in USAGE.splitlines()[1:]]

    def test_usage_block_is_the_first_paragraph_after_the_title(self):
        self.assertTrue(USAGE.startswith("usage:\n  python tools/tune.py cars"))
        self.assertEqual(len(tune.__doc__.split("\n\n")[0].splitlines()), 1)

    def test_every_usage_line_is_a_command_main_dispatches(self):
        commands = [line.split()[2] for line in self.usage_lines()]
        self.assertEqual(commands, ["cars", "init", "defaults", "variants", "versions", "version-add", "version-rename", "version-lock", "version-unlock", "set", "unset", "show", "apply", "duplicate", "tyres", "tyre-sources",
                                    "tyre-new", "tyre-show", "tyre-set", "tyre-unset", "tyre-delete", "garage", "garage-set", "garage-reset", "turbo-donors",
                                    "turbo-add", "turbo-remove", "turbo-kit", "sounds", "sound-set", "sound-reset", "ranges"])
        self.assertEqual(list(tune.COMMANDS), commands)
        for cmd in commands:
            self.assertEqual(tune.COMMANDS[cmd].__name__, "cmd_" + cmd.replace("-", "_"))

    def test_every_documented_option_and_positional_is_accepted_by_the_parser(self):
        class Reached(Exception):
            pass

        def reached(opts):
            raise Reached

        with mock.patch.object(tune, "start", reached), mock.patch.object(tune, "work_arg", reached), mock.patch.object(tune, "game_running", lambda: False):
            for line in self.usage_lines():
                words = line.split()
                cmd = words[2]
                required = line.replace("[", " [").split("[")[0].split()[3:]
                positional = [w for i, w in enumerate(required) if not w.startswith("--") and not (i and required[i - 1].startswith("--"))]
                options = [w for w in required if w.startswith("--")]
                values = ["value%d" % i for i in range(len(positional))] + [x for o in options for x in (o, "x")]
                groups = [g for g in line.replace("]", "[").split("[")[1::2]]
                alternatives = [alt.split() for g in groups for alt in g.split(" | ")]
                for opt in alternatives or [[]]:
                    argv = [cmd] + values + [w if w.startswith("--") else "x" for w in opt]
                    with self.subTest(" ".join(argv)):
                        with mock.patch.object(sys, "argv", ["tune.py"] + argv):
                            with self.assertRaises(Reached):
                                tune.main()


class TestCliUsage(unittest.TestCase):
    pass


usage_cases(TestCliUsage, USAGE, (("no_arguments", []), ("unknown_command", ["frobnicate"]), ("cars_with_a_positional", ["cars", "x"]),
                                  ("init_with_a_positional", ["init", "x"]), ("defaults_with_a_positional", ["defaults", "x"]),
                                  ("set_with_one_operand", ["set", "limiter"]), ("set_with_three_operands", ["set", "a", "b", "c"]),
                                  ("unset_without_operand", ["unset"]), ("unset_with_two_operands", ["unset", "a", "b"]),
                                  ("show_with_a_positional", ["show", "x"]), ("apply_with_a_positional", ["apply", "x"]),
                                  ("unknown_option", ["show", "--bogus", "1"]),
                                  ("option_without_value", ["show", "--car"]), ("tune_without_value", ["show", "--tune"]),
                                  ("cars_modded_with_tested", ["cars", "--modded", "--tested"]), ("duplicate_with_a_positional", ["duplicate", "x"]),
                                  ("duplicate_tune_with_draft", ["duplicate", "--tune", "ax01", "--draft"]), ("duplicate_with_all", ["duplicate", "--all"]),
                                  ("defaults_with_variant_and_tune", ["defaults", "--variant", "q_drift", "--tune", "ax01"]),
                                  ("variants_with_a_positional", ["variants", "x"]), ("variants_with_a_tune", ["variants", "--tune", "ax01"]),
                                  ("defaults_with_variant_and_version", ["defaults", "--variant", "q_drift", "--version", "v01"]),
                                  ("versions_with_a_positional", ["versions", "x"]), ("versions_with_a_version", ["versions", "--version", "v01"]),
                                  ("versions_with_draft", ["versions", "--draft"]), ("version_add_without_a_name", ["version-add"]),
                                  ("version_add_with_two_names", ["version-add", "a", "b"]), ("version_add_with_draft", ["version-add", "a", "--draft"]),
                                  ("version_add_from_without_value", ["version-add", "a", "--from"]),
                                  ("version_rename_with_one_operand", ["version-rename", "v01"]),
                                  ("version_rename_with_three_operands", ["version-rename", "v01", "a", "b"]),
                                  ("version_rename_with_draft", ["version-rename", "v01", "a", "--draft"]),
                                  ("version_lock_without_an_id", ["version-lock"]), ("version_lock_with_two_ids", ["version-lock", "v01", "v02"]),
                                  ("version_lock_with_draft", ["version-lock", "v01", "--draft"]), ("version_lock_with_a_version", ["version-lock", "v01", "--version", "v01"]),
                                  ("version_unlock_without_an_id", ["version-unlock"]), ("version_unlock_with_two_ids", ["version-unlock", "v01", "v02"]),
                                  ("version_unlock_with_draft", ["version-unlock", "v01", "--draft"]),
                                  ("show_with_version_and_draft", ["show", "--version", "v01", "--draft"]),
                                  ("set_with_version_and_draft", ["set", "limiter", "1", "--version", "v01", "--draft"]),
                                  ("unset_with_version_and_draft", ["unset", "limiter", "--version", "v01", "--draft"]),
                                  ("show_with_version_without_value", ["show", "--version"]), ("apply_with_a_version", ["apply", "--version", "v01"]),
                                  ("init_with_a_tune", ["init", "--tune", "ax01"]),
                                  ("cars_with_a_tune", ["cars", "--tune", "ax01"]), ("show_with_draft", ["show", "--draft"]),
                                  ("apply_with_new_id_without_value", ["apply", "--tune", "ax01", "--new-id"])), tune, real=("no_arguments",))


class TestCliRuntimeErrors(unittest.TestCase):
    def test_unknown_car_is_an_error_line_on_stderr_with_exit_1(self):
        with tmp() as d:
            r = run_tool("tune.py", "show", "--car", "ks_no_such_car", "--work", d / "w", cwd=d)
            self.assertEqual((r.returncode, r.stdout), (1, ""))
            self.assertTrue(r.stderr.startswith("error: unknown car 'ks_no_such_car'"), r.stderr)
            self.assertEqual(os.listdir(d), [])

    def test_unknown_setting_is_an_error_line_on_stderr_with_exit_1(self):
        with tmp() as d:
            code, out, err = run_main(tune.main, ["tune.py", "unset", "no_such_setting", "--work", str(d / "w")], cwd=d)
            self.assertEqual((code, out, err), (1, "", "error: unknown setting 'no_such_setting'\n"))

    def test_unextracted_car_is_an_error_line_on_stderr_with_exit_1(self):
        with tmp() as d:
            code, out, err = run_main(tune.main, ["tune.py", "defaults", "--work", str(d / "w")], cwd=d)
            self.assertEqual((code, out), (1, ""))
            self.assertRegex(err, r"^error: no base car in .*, run init first\n$")

    def test_tune_with_new_id_is_an_error_line_on_stderr_with_exit_1(self):
        with tmp() as d:
            code, out, err = run_main(tune.main, ["tune.py", "apply", "--tune", "ax01", "--new-id", "ax02", "--no-install", "--work", str(d / "w")], cwd=d)
            self.assertEqual((code, out, err), (1, "", "error: --tune and --new-id cannot be combined\n"))
            self.assertEqual(os.listdir(d), [])

    def test_unknown_tune_is_an_error_line_on_stderr_with_exit_1(self):
        with tmp() as d:
            code, out, err = run_main(tune.main, ["tune.py", "show", "--tune", "ax_zz99", "--work", str(d / "w")], cwd=d)
            self.assertEqual((code, out), (1, ""))
            self.assertRegex(err, r"^error: .*ax_zz99")

    def test_unexpanded_work_folder_is_an_error_line(self):
        with tmp() as d:
            code, out, err = run_main(tune.main, ["tune.py", "show", "--work", "%ACE_TEST_NO_SUCH_VAR%/w"], cwd=d)
            self.assertEqual((code, out), (1, ""))
            self.assertTrue(err.startswith("error: cannot expand the work directory"), err)
            self.assertEqual(os.listdir(d), [])


if __name__ == "__main__":
    unittest.main()
