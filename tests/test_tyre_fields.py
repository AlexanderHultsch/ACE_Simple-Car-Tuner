"""Tests for the Tyre Creator fields beyond the first twelve: the catalogue keys tyre_groups, tyre_settings and tyre_group (validation and the real catalogue), the fields that a tyre file may not store ("absent"), bool and wear curve fields in rows and builds (also as wire bytes of a synthetic schema, with and without an _order list), tyre_ranges with its cache and the values by tyre type (types, by_type, type_ranges).

No game data and no schemas: the tyre files are synthetic (support.FakeCar replaces tune.load_msg with in-memory messages) and the game package is a small package packed by kspkg.cmd_pack or does not exist; the check of the catalogue paths against the real schema is skipped when schemas/acevo.desc is not there.
"""
import copy
import json
import os
import unittest
from unittest import mock

from support import FakeCar, ROOT, desc_field, desc_file, desc_message, desc_set, mini_catalogue, mini_setting, pb_f32, pb_msg, pb_str, pb_vint, tmp

import car_json
import kspkg
import tune
import tyre_sets
from test_tyre_library import GS, ROAD_A, ROAD_B, SLICK_S, World, pack, tyre_cat

REAL = tune.load_catalogue()
SCHEMA = ROOT / "schemas" / "acevo.desc"
GROUP_NAMES = ["Grip", "Slip and falloff", "Steering feel", "Stiffness and damping", "Camber", "Pressure", "Speed sensitivity", "Temperature",
               "Wear and graining", "Rolling resistance", "Wet grooves"]


def field(fid, group="G1", path="modelData.x", **extra):
    """A tyre_settings entry."""
    s = {"id": fid, "group": group, "label": "L " + fid, "kind": "value", "type": "float", "unit": "", "description": "d " + fid,
         "verified": False, "targets": [{"file": "@tyre", "path": path}]}
    s.update(extra)
    return s


def with_tyre_keys(settings=None, tyre_settings=None, groups=None, extra_setting=None):
    """A catalogue with a Tyres group (front setting tyre_a_front in the tyre group G1), tyre_groups and tyre_settings."""
    front = mini_setting("tyre_a_front", group="Tyres", tyre_group="G1", targets=[("@tyre_front", "modelData.Dy0")])
    cat = mini_catalogue(*(settings if settings is not None else [front]))
    cat["tyre_groups"] = groups if groups is not None else [{"name": "G1", "description": "d1"}, {"name": "G2", "description": "d2"}]
    cat["tyre_settings"] = tyre_settings if tyre_settings is not None else [field("tyre_b", "G2")]
    return cat


def load(cat):
    with tmp() as d:
        path = str(d / "c.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cat, f)
        return tune.read_catalogue(path)


class TestTyreCatalogueValidation(unittest.TestCase):
    def test_a_catalogue_with_the_tyre_keys_loads_and_orders_the_fields_by_group(self):
        cat = load(with_tyre_keys(tyre_settings=[field("tyre_c", "G2"), field("tyre_b", "G1")]))
        fields = tune.tyre_fields(cat)
        self.assertEqual([(f["id"], f["group"]) for f in fields], [("tyre_a", "G1"), ("tyre_b", "G1"), ("tyre_c", "G2")])
        self.assertEqual(tune.tyre_group_list(cat), [{"name": "G1", "description": "d1"}, {"name": "G2", "description": "d2"}])

    def test_a_catalogue_without_the_tyre_keys_stays_valid_and_the_group_of_the_derived_fields_is_as_before(self):
        cat = mini_catalogue(mini_setting("tyre_a_front", group="Tyres", targets=[("@tyre_front", "modelData.Dy0")]))
        loaded = load(cat)
        self.assertEqual([(f["id"], f["group"]) for f in tune.tyre_fields(loaded)], [("tyre_a", "Tyres")])
        self.assertEqual(tune.tyre_group_list(loaded), [])

    def test_the_tyre_group_of_a_setting_is_the_group_of_its_field(self):
        self.assertEqual(tune.tyre_fields(load(with_tyre_keys()))[0]["group"], "G1")

    def test_invalid_tyre_keys_are_refused(self):
        def edit(**kw):
            cat = with_tyre_keys()
            cat.update(kw)
            return cat

        no_groups = with_tyre_keys()
        del no_groups["tyre_groups"]
        no_settings = with_tyre_keys()
        del no_settings["tyre_settings"]
        only_group = mini_catalogue(mini_setting("a", group="Tyres", tyre_group="G1", targets=[("@engine", "limiter")]))
        unused = with_tyre_keys(groups=[{"name": "G1", "description": "d1"}, {"name": "G2", "description": "d2"}, {"name": "G3", "description": "d3"}])
        wrong_group = with_tyre_keys(settings=[mini_setting("tyre_a_front", group="Tyres", tyre_group="Nope", targets=[("@tyre_front", "modelData.Dy0")])])
        missing_group = with_tyre_keys(settings=[mini_setting("tyre_a_front", group="Tyres", targets=[("@tyre_front", "modelData.Dy0")])])
        taken = mini_setting("tyre_b", group="Tyres", tyre_group="G1", targets=[("@engine", "limiter")])
        cases = [
            ("a setting's tyre_group without tyre_groups", only_group, "setting 'a' has a tyre_group, but the catalogue has no tyre_groups"),
            ("tyre_groups without tyre_settings", no_settings, "needs tyre_settings, a list, together with tyre_groups"),
            ("tyre_settings without tyre_groups", no_groups, "needs tyre_groups, a list of name and description"),
            ("tyre_settings not a list", edit(tyre_settings={}), "needs tyre_settings, a list"),
            ("damaged tyre group", edit(tyre_groups=[{"name": "G1"}]), "every tyre group needs a name and a description"),
            ("duplicate tyre group", edit(tyre_groups=[{"name": "G1", "description": "d"}, {"name": "G1", "description": "d"}]),
             "duplicate group name 'G1'"),
            ("unknown tyre_group of a setting", wrong_group, "setting 'tyre_a_front' has the tyre_group 'Nope', which is not listed in tyre_groups"),
            ("a derived setting without tyre_group", missing_group, "setting 'tyre_a_front' needs a tyre_group, the catalogue has tyre_groups"),
            ("unused tyre group", unused, "group 'G3' is listed in tyre_groups but no tyre field uses it"),
            ("unknown group of a field", edit(tyre_settings=[field("tyre_b", "Nope")]),
             "tyre setting 'tyre_b' has the group 'Nope', which is not listed in tyre_groups"),
            ("duplicate field id", edit(tyre_settings=[field("tyre_b", "G2"), field("tyre_b", "G1")]), "duplicate tyre setting id 'tyre_b'"),
            ("a field id that is a setting id", with_tyre_keys(settings=[taken, mini_setting("tyre_a_front", group="Tyres", tyre_group="G1",
                                                                                             targets=[("@tyre_front", "modelData.Dy0")])]),
             "duplicate tyre setting id 'tyre_b'"),
            ("a field id that a front setting derives", edit(tyre_settings=[field("tyre_a", "G2")]), "duplicate tyre setting id 'tyre_a'"),
            ("missing key", edit(tyre_settings=[{k: v for k, v in field("tyre_b", "G2").items() if k != "unit"}]), "tyre setting 'tyre_b' misses unit"),
            ("kind and type that do not belong together", edit(tyre_settings=[field("tyre_b", "G2", kind="flag")]), "tyre setting 'tyre_b' needs kind"),
            ("an int type", edit(tyre_settings=[field("tyre_b", "G2", type="int")]), "tyre setting 'tyre_b' needs kind"),
            ("no targets", edit(tyre_settings=[field("tyre_b", "G2", targets=[])]), "needs targets with the file @tyre and a path"),
            ("a target of another file", edit(tyre_settings=[field("tyre_b", "G2", targets=[{"file": "@tyre_front", "path": "a.b"}])]),
             "needs targets with the file @tyre and a path"),
            ("a target without a path", edit(tyre_settings=[field("tyre_b", "G2", targets=[{"file": "@tyre"}])]),
             "needs targets with the file @tyre and a path"),
            ("a bad path", edit(tyre_settings=[field("tyre_b", "G2", path="a..b")]), "tyre setting 'tyre_b': bad field path 'a..b'"),
            ("an enum without choices", edit(tyre_settings=[field("tyre_b", "G2", type="enum")]), "needs choices and choice_values"),
            ("absent 1 on a float", edit(tyre_settings=[field("tyre_b", "G2", absent=1)]), "has an absent that is not 0 for a float or false for a bool"),
            ("absent false on a float", edit(tyre_settings=[field("tyre_b", "G2", absent=False)]), "has an absent that is not 0"),
            ("absent 0 on a bool", edit(tyre_settings=[field("tyre_b", "G2", kind="flag", type="bool", absent=0)]), "has an absent that is not 0"),
            ("absent true on a bool", edit(tyre_settings=[field("tyre_b", "G2", kind="flag", type="bool", absent=True)]), "has an absent that is not 0"),
            ("absent on an enum", edit(tyre_settings=[field("tyre_b", "G2", type="enum", choices=["x"], choice_values={"x": "p"}, absent=0)]),
             "has an absent that is not 0"),
        ]
        for name, cat, message in cases:
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                load(cat)

    def test_absent_is_accepted_for_a_float_zero_and_a_bool_false_and_the_field_gets_create_missing(self):
        cat = load(with_tyre_keys(tyre_settings=[field("tyre_f", "G2", absent=0), field("tyre_g", "G2", absent=0.0),
                                                 field("tyre_h", "G1", kind="flag", type="bool", absent=False), field("tyre_i", "G1")]))
        by_id = {f["id"]: f for f in tune.tyre_fields(cat)}
        self.assertEqual([by_id[i].get("create_missing") for i in ("tyre_f", "tyre_g", "tyre_h", "tyre_i")], [True, True, True, None])
        self.assertNotIn("create_missing", cat["tyre_settings"][0])

    def test_the_error_names_the_catalogue_file(self):
        with tmp() as d:
            path = str(d / "c.json")
            cat = with_tyre_keys()
            del cat["tyre_settings"]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cat, f)
            with self.assertRaises(ValueError) as cm:
                tune.read_catalogue(path)
            self.assertIn(path, str(cm.exception))


class TestRealCatalogueTyreFields(unittest.TestCase):
    FIELDS = tune.tyre_fields(REAL)

    def test_the_groups_are_the_eleven_in_order_and_every_one_is_used(self):
        self.assertEqual([g["name"] for g in REAL["tyre_groups"]], GROUP_NAMES)
        self.assertEqual(sorted({f["group"] for f in self.FIELDS}), sorted(GROUP_NAMES))
        order = [g["name"] for g in REAL["tyre_groups"]]
        self.assertEqual([order.index(f["group"]) for f in self.FIELDS], sorted(order.index(f["group"]) for f in self.FIELDS))

    def test_every_field_id_is_unique_also_against_the_settings(self):
        ids = [f["id"] for f in self.FIELDS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 12 + len(REAL["tyre_settings"]))
        self.assertFalse({s["id"] for s in REAL["settings"]} & set(ids))
        self.assertTrue(all(i.startswith("tyre_") for i in ids))

    def test_the_twelve_derived_fields_have_a_tyre_group_and_keep_their_other_keys(self):
        derived = [s for s in REAL["settings"] if s.get("group") == "Tyres" and s["id"].endswith("_front")]
        self.assertEqual(len(derived), 12)
        self.assertTrue(all(s["tyre_group"] in GROUP_NAMES for s in derived))
        self.assertEqual({s["tyre_group"] for s in derived}, {"Grip", "Slip and falloff", "Stiffness and damping", "Pressure", "Temperature",
                                                              "Wear and graining"})
        self.assertTrue(all(s["group"] == "Tyres" for s in derived))
        for f in [f for f in self.FIELDS if "front_id" in f and f["type"] == "float"]:
            self.assertIn("min", f)
            self.assertIn("max", f)

    def test_the_new_fields_have_the_shape_the_loader_wants_and_no_range(self):
        for s in REAL["tyre_settings"]:
            with self.subTest(s["id"]):
                self.assertEqual([t["file"] for t in s["targets"]], ["@tyre"])
                self.assertNotIn("min", s)
                self.assertNotIn("max", s)
                self.assertIs(s["verified"], False)
                self.assertEqual(s["kind"], "flag" if s["type"] == "bool" else "value")
                self.assertIn(s["type"], ("float", "bool", "enum"))
                self.assertTrue(s["description"].endswith("Not tested in the game."), s["description"])
                self.assertIn(s["targets"][0]["path"], s["description"])
                self.assertIn(s["unit"], ("", "mu", "deg", "N", "N/m", "psi", "kg", "degC", "m", "mm", "m/s"))
                if "absent" in s:
                    self.assertEqual(s["absent"], False if s["type"] == "bool" else 0)

    def test_the_racing_slick_fields_say_that_only_some_tyres_store_them(self):
        ids = ["tyre_use_slip_falloff", "tyre_falloff_level", "tyre_falloff_slope", "tyre_falloff_shape", "tyre_falloff_x_level",
               "tyre_falloff_x_slope", "tyre_falloff_x_shape", "tyre_use_slip_ratio_limit", "tyre_slip_ratio_limit",
               "tyre_slip_ratio_limit_load_gain", "tyre_new_combined", "tyre_fx_shift_sa", "tyre_fx_scale_sa", "tyre_fy_shift_sr", "tyre_fy_scale_sr"]
        by_id = {s["id"]: s for s in REAL["tyre_settings"]}
        for i in ids:
            with self.subTest(i):
                self.assertIn("racing slicks", by_id[i]["description"])
                self.assertIn("absent", by_id[i])
        self.assertEqual([by_id[i]["type"] for i in ("tyre_use_slip_falloff", "tyre_use_slip_ratio_limit", "tyre_new_combined")], ["bool"] * 3)

    def test_the_wear_curve_is_an_enum_of_the_shared_wear_curves(self):
        wear = next(s for s in REAL["tyre_settings"] if s["id"] == "tyre_wear_curve")
        self.assertEqual(wear["type"], "enum")
        self.assertEqual(set(wear["choice_values"]), set(wear["choices"]))
        self.assertEqual(len(wear["choices"]), len(set(wear["choices"])))
        for choice, text in wear["choice_values"].items():
            self.assertTrue(text.startswith("content\\cars\\common_phsx\\tyres\\") and text.endswith("\\wear_%s.curve" % choice), text)
        self.assertEqual(wear["targets"], [{"file": "@tyre", "path": "modelData.wearCurve"}])

    def test_the_fields_the_brief_leaves_out_are_not_there(self):
        paths = {t["path"] for f in self.FIELDS for t in f["targets"]}
        for left_out in ("tyreData.width", "tyreData.radius", "tyreData.rimRadius", "tyreData.dampingMode", "tyre_compound", "name", "shortName",
                         "pressureData.pressureSpringCurve") + tuple(p for p in paths if p.startswith("init_data")):
            self.assertNotIn(left_out, paths)

    @unittest.skipUnless(SCHEMA.is_file(), "needs schemas/acevo.desc")
    def test_every_path_is_a_field_of_the_tyre_message_with_the_type_of_the_field(self):
        sch = car_json.load_schema(SCHEMA)
        kinds = {"float": (2,), "bool": (8,), "enum": (9,)}
        for f in self.FIELDS:
            for t in f["targets"]:
                with self.subTest(f["id"], path=t["path"]):
                    msg, parts = "TyresCompoundData", t["path"].split(".")
                    for i, part in enumerate(parts):
                        info = car_json.msg_fields(sch, msg)[1].get(part)
                        self.assertIsNotNone(info, "%s has no field %s" % (msg, part))
                        if i < len(parts) - 1:
                            self.assertEqual(info["type"], 11)
                            msg = info["type_name"].lstrip(".")
                    self.assertIn(info["type"], kinds[f["type"]])


class Fields(World):
    """World with a catalogue that has tyre groups and fields that the tyre files do not store."""

    def setUp(self):
        super().setUp()
        flag = dict(mini_setting("tyre_flag", kind="flag", type="bool", group="Other", targets=[("@tyre", "modelData.flag")]), absent=False)
        absent = dict(mini_setting("tyre_brake", group="Other", targets=[("@tyre", "modelData.brakeDXMod")]), absent=0)
        deep = dict(mini_setting("tyre_groove", group="Other", targets=[("@tyre", "grooveData.grooveFactor")]), absent=0)
        wear = mini_setting("tyre_wear", type="enum", group="Other", choices=["road", "slick"], targets=[("@tyre", "modelData.wearCurve")],
                            choice_values={"road": GS + "tyres\\road\\wear_road.curve", "slick": GS + "tyres\\slick\\wear_slick.curve"})
        cat = tyre_cat()
        cat["settings"] = [dict(s, tyre_group="Grip") if s.get("group") == "Tyres" and s["id"].endswith("_front") else s for s in cat["settings"]]
        cat.update(tyre_groups=[{"name": "Grip", "description": "dg"}, {"name": "Other", "description": "do"}], tyre_settings=[flag, absent, deep, wear])
        self.cat = cat


class TestAbsentFieldsInRows(Fields):
    def test_the_rows_come_in_group_order_with_the_derived_fields_first(self):
        tid = self.create()
        rows = tune.tyre_rows(self.work, tid, self.cat, self.game)
        self.assertEqual([(r["id"], r["group"]) for r in rows], [("tyre_dy", "Grip"), ("tyre_th", "Grip"), ("tyre_deep", "Grip"), ("tyre_maybe", "Grip"),
                                                                 ("tyre_flag", "Other"), ("tyre_brake", "Other"), ("tyre_groove", "Other"),
                                                                 ("tyre_wear", "Other")])

    def test_a_field_the_file_does_not_store_is_applicable_with_the_default_zero_or_false(self):
        rows = self.rows(self.create())
        for field_id, default in (("tyre_flag", False), ("tyre_brake", 0.0), ("tyre_groove", 0.0)):
            with self.subTest(field_id):
                self.assertEqual((rows[field_id]["applicable"], rows[field_id]["reason"], rows[field_id]["default"], rows[field_id]["value"],
                                  rows[field_id]["changed"]), (True, None, default, default, False))
                self.assertIs(type(rows[field_id]["default"]), type(default))
        self.assertEqual((rows["tyre_flag"]["type"], rows["tyre_flag"]["kind"]), ("bool", "flag"))

    def test_a_field_the_file_stores_shows_its_value(self):
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))]["modelData"].update(brakeDXMod=0.05, flag=True)
        rows = self.rows(self.create())
        self.assertEqual((rows["tyre_brake"]["default"], rows["tyre_flag"]["default"]), (0.05, True))

    def test_a_value_other_than_the_default_is_changed_and_the_default_itself_is_not(self):
        tid = self.create()
        self.assertEqual(tune.set_tyre_value(self.work, tid, "tyre_brake", "0.2", self.cat)["value"], 0.2)
        self.assertEqual(tune.set_tyre_value(self.work, tid, "tyre_flag", "yes", self.cat)["value"], True)
        rows = self.rows(tid)
        self.assertEqual((rows["tyre_brake"]["changed"], rows["tyre_brake"]["value"], rows["tyre_flag"]["changed"], rows["tyre_flag"]["value"]),
                         (True, 0.2, True, True))
        tune.set_tyre_value(self.work, tid, "tyre_brake", "0", self.cat)
        tune.set_tyre_value(self.work, tid, "tyre_flag", "off", self.cat)
        rows = self.rows(tid)
        self.assertEqual((rows["tyre_brake"]["changed"], rows["tyre_flag"]["changed"]), (False, False))

    def test_a_bad_bool_text_is_refused(self):
        tid = self.create()
        with self.assertRaisesRegex(ValueError, "^tyre_flag expects true or false"):
            tune.set_tyre_value(self.work, tid, "tyre_flag", "maybe", self.cat)
        self.assertEqual(tune.load_tyre(self.work, tid)["values"], {})

    def test_the_wear_curve_row_is_an_enum_with_its_choices(self):
        rows = self.rows(self.create())
        self.assertEqual((rows["tyre_wear"]["type"], rows["tyre_wear"]["choices"]), ("enum", ["road", "slick"]))
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))]["modelData"]["wearCurve"] = GS + "tyres\\slick\\wear_slick.curve"
        rows = self.rows(self.create("Other"))
        self.assertEqual((rows["tyre_wear"]["default"], rows["tyre_wear"]["value"]), ("slick", "slick"))
        self.assertNotIn("base_range", rows["tyre_wear"])


class TestAbsentFieldsInBuilds(Fields):
    def build(self, tid):
        return tune.own_tyre_file(self.work, tid, self.game, self.cat)[2]

    def test_an_absent_float_is_added_with_the_value_float32(self):
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_brake", "0.2", self.cat)
        obj = self.build(tid)
        self.assertEqual(tune.plain(obj["modelData"]["brakeDXMod"]), 0.2)
        self.assertIsInstance(obj["modelData"]["brakeDXMod"], car_json.F32)

    def test_an_absent_bool_is_added_as_a_bool(self):
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_flag", "true", self.cat)
        self.assertIs(self.build(tid)["modelData"]["flag"], True)

    def test_a_missing_sub_message_is_created_with_the_field(self):
        tid = self.create()
        self.assertNotIn("grooveData", self.build(tid))
        tune.set_tyre_value(self.work, tid, "tyre_groove", "0.4", self.cat)
        self.assertEqual(tune.plain(self.build(tid)["grooveData"]["grooveFactor"]), 0.4)

    def test_setting_the_default_of_an_absent_field_adds_nothing_and_does_not_break_the_build(self):
        tid = self.create()
        for field_id, text in (("tyre_brake", "0"), ("tyre_flag", "false"), ("tyre_groove", "0.0")):
            tune.set_tyre_value(self.work, tid, field_id, text, self.cat)
        obj = self.build(tid)
        self.assertNotIn("brakeDXMod", obj["modelData"])
        self.assertNotIn("flag", obj["modelData"])
        self.assertNotIn("grooveData", obj)

    def test_a_stored_field_is_set_to_zero_like_any_other_value(self):
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))]["modelData"]["brakeDXMod"] = 0.05
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_brake", "0", self.cat)
        self.assertEqual(tune.plain(self.build(tid)["modelData"]["brakeDXMod"]), 0.0)

    def test_the_wear_curve_choice_writes_the_text_of_the_curve(self):
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_wear", "slick", self.cat)
        self.assertEqual(self.build(tid)["modelData"]["wearCurve"], GS + "tyres\\slick\\wear_slick.curve")

    def test_an_unknown_wear_curve_is_refused(self):
        with self.assertRaisesRegex(ValueError, "^tyre_wear must be one of: road, slick$"):
            tune.set_tyre_value(self.work, self.create(), "tyre_wear", "nope", self.cat)

    def test_the_twelve_derived_fields_still_build_as_before(self):
        tid = self.create()
        tune.set_tyre_value(self.work, tid, "tyre_dy", "1.4", self.cat)
        obj = self.build(tid)
        self.assertEqual((tune.plain(obj["modelData"]["Dy0"]), tune.plain(obj["modelData"]["Dy1"])), (1.4, 1.4))
        self.assertEqual(obj["name"], "Slick (SL)")


def wire_tyre(order_first_high=False):
    """A TyresCompoundData with modelData (Dy0 #1, use_slip_falloff #2, brakeDXMod #3) and camberData (camberGain #1, dcamber1_x #2): the
    model fields in descending wire order and the bool set when order_first_high (the decoder then records an _order list)."""
    dy = pb_f32(1, 1.25)
    model = pb_msg(4, pb_vint(2, 1), dy) if order_first_high else pb_msg(4, dy)
    return pb_str(1, "stock") + model + pb_msg(6, pb_f32(1, 0.5))


def schema_bytes():
    model = desc_message("TyresModelData", [desc_field("Dy0", 1, 2), desc_field("use_slip_falloff", 2, 8), desc_field("brakeDXMod", 3, 2)])
    camber = desc_message("TyresCamberData", [desc_field("camberGain", 1, 2), desc_field("dcamber1_x", 2, 2)])
    groove = desc_message("TyresGrooveData", [desc_field("grooveFactor", 1, 2)])
    root = desc_message("TyresCompoundData", [desc_field("name", 1, 9), desc_field("shortName", 2, 9),
                                              desc_field("modelData", 4, 11, 1, ".TyresModelData"),
                                              desc_field("camberData", 6, 11, 1, ".TyresCamberData"),
                                              desc_field("grooveData", 7, 11, 1, ".TyresGrooveData")])
    return desc_set(desc_file("tyre.proto", messages=[model, camber, groove, root]))


class TestAbsentFieldsOnTheWire(unittest.TestCase):
    """The tyre file as a decoded message of a synthetic schema: a field that was not stored is added, also into a message that has an _order
    list, and the result encodes and decodes back to the same object."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tmp()
        base = cls._tmp.__enter__()
        (base / "acevo.desc").write_bytes(schema_bytes())
        cls.sch = car_json.load_schema(base / "acevo.desc")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.__exit__(None, None, None)

    def setUp(self):
        self.td = tmp()
        self.d = self.td.__enter__()
        self.addCleanup(self.td.__exit__, None, None, None)
        self.work = str(self.d / "work")
        self.game = str(self.d / "none.kspkg")
        fc = FakeCar(self.work, "ks_a")
        fc.add_shared("tyres/road/a.tyre")
        self.wire = b""
        self.patch_load()
        tune.create_tyre(self.work, "Soft", ROAD_A, game=self.game)
        flag = dict(mini_setting("tyre_flag", kind="flag", type="bool", group="Other", targets=[("@tyre", "modelData.use_slip_falloff")]), absent=False)
        brake = dict(mini_setting("tyre_brake", group="Other", targets=[("@tyre", "modelData.brakeDXMod")]), absent=0)
        camber = dict(mini_setting("tyre_camber", group="Other", targets=[("@tyre", "camberData.dcamber1_x")]), absent=0)
        groove = dict(mini_setting("tyre_groove", group="Other", targets=[("@tyre", "grooveData.grooveFactor")]), absent=0)
        self.cat = dict(mini_catalogue(), tyre_groups=[{"name": "Other", "description": "do"}], tyre_settings=[flag, brake, camber, groove])

    def patch_load(self):
        def load_msg(path):
            return car_json.decode_msg(self.sch, "TyresCompoundData", self.wire), "TyresCompoundData"
        p = mock.patch.object(tune, "load_msg", load_msg)
        p.start()
        self.addCleanup(p.stop)

    def built(self, wire, values):
        self.wire = wire
        for field_id, text in values.items():
            tune.set_tyre_value(self.work, "soft", field_id, text, self.cat)
        obj = tune.own_tyre_file(self.work, "soft", self.game, self.cat)[2]
        data = car_json.encode_msg(self.sch, "TyresCompoundData", obj)
        return obj, car_json.decode_msg(self.sch, "TyresCompoundData", data), data

    def test_the_source_without_an_order_list_gets_the_fields_and_encodes_back(self):
        obj, back, _ = self.built(wire_tyre(), {"tyre_brake": "0.2", "tyre_flag": "true", "tyre_camber": "-5", "tyre_groove": "0.3"})
        self.assertNotIn("_order", obj["modelData"])
        self.assertEqual((tune.plain(back["modelData"]["brakeDXMod"]), back["modelData"]["use_slip_falloff"], tune.plain(back["camberData"]["dcamber1_x"]),
                          tune.plain(back["grooveData"]["grooveFactor"])), (0.2, True, -5.0, 0.3))
        self.assertEqual(back["modelData"]["Dy0"], 1.25)
        self.assertEqual(back["name"], "Soft (SO)")

    def test_a_message_with_an_order_list_keeps_it_covering_the_new_field(self):
        wire = wire_tyre(True)
        self.wire = wire
        source = car_json.decode_msg(self.sch, "TyresCompoundData", wire)
        self.assertEqual(source["modelData"]["_order"], ["use_slip_falloff", "Dy0"])
        obj, back, _ = self.built(wire, {"tyre_brake": "0.2"})
        self.assertEqual(obj["modelData"]["_order"], ["use_slip_falloff", "Dy0", "brakeDXMod"])
        self.assertEqual((tune.plain(back["modelData"]["brakeDXMod"]), back["modelData"]["use_slip_falloff"], back["modelData"]["Dy0"]), (0.2, True, 1.25))

    def test_a_stored_bool_can_be_switched_off_and_stays_stored(self):
        obj, back, _ = self.built(wire_tyre(True), {"tyre_flag": "false"})
        self.assertIs(back["modelData"].get("use_slip_falloff", False), False)

    def test_the_default_of_an_absent_field_leaves_the_file_bytes_as_the_plain_build(self):
        _, _, plain = self.built(wire_tyre(), {})
        _, _, same = self.built(wire_tyre(), {"tyre_brake": "0", "tyre_camber": "0", "tyre_groove": "0"})
        self.assertEqual(plain, same)

    def test_a_message_that_is_missing_altogether_is_created(self):
        _, back, _ = self.built(wire_tyre(), {"tyre_groove": "0.3"})
        self.assertIn("grooveData", back)


class TestTyreRanges(Fields):
    def setUp(self):
        super().setUp()
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))]["modelData"]["brakeDXMod"] = 0.05
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "slick", "s.tyre"))]["modelData"]["brakeDXMod"] = -0.05
        self.cache_path = os.path.join(self.work, "tyre_ranges.json")

    def ranges(self, cat=None, game=None):
        return tune.tyre_ranges(self.work, cat or self.cat, game or self.game)

    def test_low_high_and_count_are_over_the_tyres_that_store_the_field(self):
        res = self.ranges()
        self.assertEqual(res["total"], 6)
        self.assertEqual(res["by_type"]["tyre_dy"], {"road": {"low": 1.0, "high": 1.2, "count": 3}, "supercar": {"low": 1.5, "high": 1.5, "count": 1},
                                                     "slick": {"low": 1.0, "high": 1.0, "count": 2}})
        self.assertEqual(res["by_type"]["tyre_brake"], {"road": {"low": 0.05, "high": 0.05, "count": 1}, "slick": {"low": -0.05, "high": -0.05, "count": 1}})

    def test_a_field_nobody_stores_has_no_entry(self):
        res = self.ranges()
        for field_id in ("tyre_groove", "tyre_deep", "tyre_maybe"):
            self.assertNotIn(field_id, res["by_type"])

    def test_the_values_are_the_defaults_of_the_rows(self):
        tid = self.create()
        rows = self.rows(tid)
        self.assertEqual(rows["tyre_dy"]["default"], 1.2)
        self.assertEqual(rows["tyre_dy"]["type_ranges"]["road"], {"low": 1.0, "high": 1.2, "count": 3})
        self.assertEqual(rows["tyre_brake"]["type_ranges"]["slick"], {"low": -0.05, "high": -0.05, "count": 1})

    def test_a_field_with_several_targets_uses_the_first(self):
        cat = copy.deepcopy(self.cat)
        cat["settings"][0]["targets"] = [{"file": "@tyre_front", "path": "modelData.Dy1"}, {"file": "@tyre_front", "path": "modelData.Dy0"}]
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))]["modelData"]["Dy1"] = 3.0
        res = self.ranges(cat)
        self.assertEqual(res["by_type"]["tyre_dy"]["road"], {"low": 1.0, "high": 3.0, "count": 2})

    def test_a_tyre_that_cannot_be_read_is_skipped_and_not_counted(self):
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "b.tyre"))] = ValueError("damaged")
        res = self.ranges()
        self.assertEqual(res["total"], 5)
        self.assertEqual(res["by_type"]["tyre_dy"]["road"], {"low": 1.0, "high": 1.2, "count": 2})

    def test_the_result_is_cached_in_the_work_folder_and_a_second_call_reads_no_tyre(self):
        self.ranges()
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual((data["version"], data["total"]), (tune.TYRE_RANGES_VERSION, 6))
        self.assertEqual(data["by_type"]["tyre_dy"]["road"], {"low": 1.0, "high": 1.2, "count": 3})
        with mock.patch.object(tune, "read_tyre_ranges", side_effect=AssertionError("read again")), mock.patch.object(tune, "load_msg", side_effect=AssertionError("read")):
            self.assertEqual(self.ranges()["total"], 6)
            tune._tyre_ranges_loaded.clear()
            self.assertEqual(self.ranges()["total"], 6)

    def test_the_memory_cache_serves_without_the_file_being_read(self):
        self.ranges()
        with mock.patch.object(tune, "read_json", side_effect=AssertionError("file read")):
            self.assertEqual(self.ranges()["total"], 6)

    def test_the_result_is_a_copy_the_caller_may_change(self):
        self.ranges()["by_type"].clear()
        self.assertIn("tyre_dy", self.ranges()["by_type"])

    def test_a_change_of_the_field_list_reads_again(self):
        self.ranges()
        more = copy.deepcopy(self.cat)
        more["tyre_settings"].append(dict(mini_setting("tyre_more", group="Other", targets=[("@tyre", "modelData.Dy1")]), absent=0))
        with mock.patch.object(tune, "read_tyre_ranges", wraps=tune.read_tyre_ranges) as spy:
            res = self.ranges(more)
            self.assertEqual(spy.call_count, 1)
            self.assertIn("tyre_more", res["by_type"])
            self.ranges(more)
            self.assertEqual(spy.call_count, 1)
            self.ranges()
            self.assertEqual(spy.call_count, 2)

    def test_a_change_of_a_field_path_reads_again(self):
        self.ranges()
        other = copy.deepcopy(self.cat)
        other["tyre_settings"][1]["targets"][0]["path"] = "modelData.Dy1"
        with mock.patch.object(tune, "read_tyre_ranges", wraps=tune.read_tyre_ranges) as spy:
            self.ranges(other)
            self.assertEqual(spy.call_count, 1)

    def test_a_new_tyre_file_without_a_package_reads_again(self):
        self.ranges()
        self.a.add_shared("tyres/road/new.tyre", {"modelData": {"Dy0": 2.0}})
        res = self.ranges()
        self.assertEqual((res["total"], res["by_type"]["tyre_dy"]["road"]["high"]), (7, 2.0))

    def test_a_changed_package_reads_again_and_an_unchanged_one_does_not(self):
        pkg = str(self.d / "content.kspkg")
        pack(pkg, ["road\\a.tyre", "road\\b.tyre"])
        with mock.patch.object(tune, "read_tyre_ranges", wraps=tune.read_tyre_ranges) as spy:
            self.ranges(game=pkg)
            self.ranges(game=pkg)
            self.assertEqual(spy.call_count, 1)
            pack(pkg, ["road\\a.tyre", "road\\b.tyre", "road\\c.tyre"])
            self.ranges(game=pkg)
            self.assertEqual(spy.call_count, 2)
            os.utime(pkg, ns=(1, 1))
            self.ranges(game=pkg)
            self.assertEqual(spy.call_count, 3)

    def test_a_damaged_cache_file_is_ignored_and_written_again(self):
        self.ranges()
        for text in ("{", "[]", json.dumps({"version": 1}), json.dumps({"version": tune.TYRE_RANGES_VERSION, "stamp": [], "fields": [], "total": 1, "types": []})):
            with self.subTest(text):
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    f.write(text)
                tune._tyre_ranges_loaded.clear()
                res = self.ranges()
                self.assertEqual(res["total"], 6)
                with open(self.cache_path, encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["total"], 6)

    def test_a_cache_with_a_nonsense_range_is_ignored(self):
        self.ranges()
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        data["by_type"]["tyre_dy"]["road"] = {"low": 5, "high": 1, "count": 1}
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tune._tyre_ranges_loaded.clear()
        self.assertEqual(self.ranges()["by_type"]["tyre_dy"]["road"]["high"], 1.2)

    def test_a_cache_that_cannot_be_written_is_no_error(self):
        with mock.patch.object(tune, "save_json", side_effect=OSError("disk full")):
            self.assertEqual(self.ranges()["total"], 6)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_nothing_is_written_outside_the_work_folder(self):
        def files():
            return sorted(os.path.join(dp, n) for dp, _, names in os.walk(str(self.d)) for n in names if not dp.startswith(self.work))

        before = files()
        self.ranges()
        self.ranges()
        self.assertEqual(files(), before)
        self.assertTrue(os.path.isfile(self.cache_path))

    def test_the_rows_have_no_type_ranges_when_they_cannot_be_computed_and_no_error(self):
        tid = self.create()
        with mock.patch.object(tune, "tyre_ranges", side_effect=ValueError("no table")):
            rows = self.rows(tid)
        self.assertEqual([r["type_ranges"] for r in rows.values()], [{}] * 8)

    def test_a_work_folder_without_tyres_gives_an_empty_result(self):
        self.assertEqual(tune.tyre_ranges(str(self.d / "empty"), self.cat, self.game), {"total": 0, "types": [], "by_type": {}})


class TestTyreRangesByType(Fields):
    """World: road a, b, dup (3), supercar (1), slick s, dup (2); the type "slick" is no known folder, so it comes last."""

    def setUp(self):
        super().setUp()
        self.cache_path = os.path.join(self.work, "tyre_ranges.json")
        for name, extra in (("road/a", {"brakeDXMod": 0.05, "flag": True, "wearCurve": GS + "tyres\\road\\wear_road.curve"}),
                            ("road/b", {"wearCurve": GS + "tyres\\slick\\wear_slick.curve"}),
                            ("road/dup", {"wearCurve": GS + "tyres\\road\\wear_zzz.curve"}),
                            ("supercar/supercar_235_35_19", {"wearCurve": GS + "tyres\\supercar\\wear_supercar.curve"}),
                            ("slick/s", {"brakeDXMod": -0.05, "flag": False, "wearCurve": GS + "tyres\\slick\\wear_slick.curve"})):
            self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", *name.split("/")) + ".tyre")]["modelData"].update(extra)

    def ranges(self, cat=None, game=None):
        return tune.tyre_ranges(self.work, cat or self.cat, game or self.game)

    def by_type(self, field_id):
        return self.ranges()["by_type"].get(field_id)

    def test_the_types_are_those_of_the_tyres_read_in_the_order_of_the_menu_unknown_ones_last(self):
        self.assertEqual(self.ranges()["types"], [{"type": "road", "label": "Road", "total": 3}, {"type": "supercar", "label": "Supercar", "total": 1},
                                                  {"type": "slick", "label": "slick", "total": 2}])
        self.assertEqual(tune.tyre_type_list(self.work, self.cat, self.game), self.ranges()["types"])

    def test_the_known_types_follow_tyre_sets_type_order_whatever_the_order_of_the_tyres(self):
        for kind in ("f1_2025", "hypercar", "vintage", "eco"):
            self.a.add_shared("tyres/%s/x.tyre" % kind, {"modelData": {"Dy0": 1.0}})
        self.assertEqual([t["type"] for t in self.ranges()["types"]], ["road", "eco", "supercar", "hypercar", "vintage", "f1_2025", "slick"])

    def test_a_tyre_that_cannot_be_read_is_not_counted_in_its_type(self):
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "b.tyre"))] = ValueError("damaged")
        res = self.ranges()
        self.assertEqual((res["total"], res["types"][0]), (5, {"type": "road", "label": "Road", "total": 2}))
        self.assertEqual(sum(t["total"] for t in res["types"]), res["total"])

    def test_a_float_field_has_low_high_and_count_per_type(self):
        self.assertEqual(self.by_type("tyre_dy"), {"road": {"low": 1.0, "high": 1.2, "count": 3}, "supercar": {"low": 1.5, "high": 1.5, "count": 1},
                                                    "slick": {"low": 1.0, "high": 1.0, "count": 2}})

    def test_a_type_in_which_no_tyre_stores_a_float_field_has_no_entry(self):
        self.assertEqual(self.by_type("tyre_brake"), {"road": {"low": 0.05, "high": 0.05, "count": 1}, "slick": {"low": -0.05, "high": -0.05, "count": 1}})
        self.assertNotIn("tyre_groove", self.ranges()["by_type"])

    def test_there_is_no_range_over_all_tyres_any_more_only_the_total_the_types_and_the_values_by_type(self):
        res = self.ranges()
        self.assertEqual(sorted(res), ["by_type", "total", "types"])
        self.assertEqual(res["total"], 6)
        for row in self.rows(self.create()).values():
            self.assertNotIn("base_range", row)

    def test_a_bool_with_absent_counts_a_tyre_that_does_not_store_it_as_false_but_not_in_count(self):
        self.assertEqual(self.by_type("tyre_flag"), {"road": {"values": [False, True], "count": 1}, "supercar": {"values": [False], "count": 0},
                                                      "slick": {"values": [False], "count": 1}})

    def test_the_values_of_a_bool_are_false_before_true(self):
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "supercar", "supercar_235_35_19.tyre"))]["modelData"]["flag"] = True
        self.assertEqual(self.by_type("tyre_flag")["supercar"], {"values": [True], "count": 1})

    def test_a_bool_without_absent_is_only_there_for_the_types_that_store_it(self):
        cat = copy.deepcopy(self.cat)
        del cat["tyre_settings"][0]["absent"]
        self.assertEqual(self.ranges(cat)["by_type"]["tyre_flag"], {"road": {"values": [True], "count": 1}, "slick": {"values": [False], "count": 1}})

    def test_an_enum_gives_the_choice_names_in_the_order_of_the_choices_and_the_file_stem_for_a_path_that_is_no_choice(self):
        self.assertEqual(self.by_type("tyre_wear"), {"road": {"values": ["road", "slick", "wear_zzz"], "count": 3},
                                                      "supercar": {"values": ["wear_supercar"], "count": 1}, "slick": {"values": ["slick"], "count": 1}})

    def test_a_tyre_that_does_not_store_an_enum_is_not_counted(self):
        self.assertEqual(self.by_type("tyre_th"), {"road": {"values": ["road"], "count": 2}, "supercar": {"values": ["road"], "count": 1},
                                                    "slick": {"values": ["road", "slick"], "count": 2}})

    def test_the_values_are_as_the_editor_shows_them(self):
        rows = self.rows(self.create())
        self.assertEqual(rows["tyre_th"]["default"], "road")
        self.assertIn(rows["tyre_th"]["default"], self.by_type("tyre_th")["road"]["values"])

    def test_the_rows_carry_type_ranges(self):
        rows = self.rows(self.create())
        self.assertEqual(rows["tyre_dy"]["type_ranges"], self.by_type("tyre_dy"))
        self.assertEqual(rows["tyre_flag"]["type_ranges"]["road"], {"values": [False, True], "count": 1})
        self.assertEqual(rows["tyre_groove"]["type_ranges"], {})

    def test_a_row_is_a_copy_the_caller_may_change(self):
        tid = self.create()
        self.rows(tid)["tyre_flag"]["type_ranges"]["road"]["values"].append("x")
        self.assertEqual(self.rows(tid)["tyre_flag"]["type_ranges"]["road"]["values"], [False, True])
        self.assertEqual(self.by_type("tyre_flag")["road"]["values"], [False, True])

    def test_the_rows_have_empty_type_ranges_and_there_are_no_types_when_the_ranges_cannot_be_computed(self):
        tid = self.create()
        with mock.patch.object(tune, "tyre_ranges", side_effect=ValueError("no table")):
            rows = self.rows(tid)
            self.assertEqual(tune.tyre_type_list(self.work, self.cat, self.game), [])
        self.assertEqual([r["type_ranges"] for r in rows.values()], [{}] * 8)

    def test_the_cache_has_the_new_version_the_types_and_the_values_by_type(self):
        self.assertEqual(tune.TYRE_RANGES_VERSION, 3)
        res = self.ranges()
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual((data["version"], data["types"], data["by_type"]), (3, res["types"], res["by_type"]))
        tune._tyre_ranges_loaded.clear()
        with mock.patch.object(tune, "read_tyre_ranges", side_effect=AssertionError("read again")):
            self.assertEqual(self.ranges(), res)

    def test_a_cache_of_the_old_version_is_read_again(self):
        self.ranges()
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        data.update(version=2, ranges={"tyre_dy": {"low": 1.0, "high": 1.5, "count": 6}})
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tune._tyre_ranges_loaded.clear()
        res = self.ranges()
        self.assertEqual(res["types"][0]["total"], 3)
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual((data["version"], "ranges" in data), (3, False))

    def test_a_change_of_a_bool_or_enum_field_reads_again(self):
        self.ranges()
        flag_path, wear_path, wear_choice = copy.deepcopy(self.cat), copy.deepcopy(self.cat), copy.deepcopy(self.cat)
        flag_path["tyre_settings"][0]["targets"][0]["path"] = "modelData.flag2"
        wear_path["tyre_settings"][3]["targets"][0]["path"] = "modelData.wearCurve2"
        wear_choice["tyre_settings"][3]["choice_values"]["road"] = GS + "tyres\\road\\wear_other.curve"
        for name, cat in (("bool path", flag_path), ("enum path", wear_path), ("enum choice", wear_choice)):
            with self.subTest(name), mock.patch.object(tune, "read_tyre_ranges", wraps=tune.read_tyre_ranges) as spy:
                self.ranges(cat)
                self.assertEqual(spy.call_count, 1)
                self.ranges(cat)
                self.assertEqual(spy.call_count, 1)

    def test_a_removed_bool_field_reads_again_and_has_no_values(self):
        self.ranges()
        less = copy.deepcopy(self.cat)
        del less["tyre_settings"][0]
        self.assertNotIn("tyre_flag", self.ranges(less)["by_type"])

    def test_a_changed_label_reads_again(self):
        self.ranges()
        with mock.patch.object(tune, "read_tyre_ranges", wraps=tune.read_tyre_ranges) as spy, \
                mock.patch.dict(tyre_sets.TYPE_LABELS, {"road": "Roadster"}):
            self.assertEqual(self.ranges()["types"][0]["label"], "Roadster")
            self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.ranges()["types"][0]["label"], "Road")

    def test_a_damaged_by_type_in_the_cache_is_ignored_and_written_again(self):
        good = self.ranges()
        bad = {"not an object": lambda d: d.update(by_type=[]),
               "field that is no field": lambda d: d["by_type"].update(nope=copy.deepcopy(d["by_type"]["tyre_dy"])),
               "type that is not listed": lambda d: d["by_type"]["tyre_dy"].update(plane={"low": 1, "high": 2, "count": 1}),
               "per type not an object": lambda d: d["by_type"].update(tyre_dy=[]),
               "low above high": lambda d: d["by_type"]["tyre_dy"]["road"].update(low=5),
               "count 0 of a float": lambda d: d["by_type"]["tyre_dy"]["road"].update(count=0),
               "count not a number": lambda d: d["by_type"]["tyre_flag"]["road"].update(count="1"),
               "negative count": lambda d: d["by_type"]["tyre_flag"]["road"].update(count=-1),
               "no values": lambda d: d["by_type"]["tyre_flag"]["road"].update(values=[]),
               "values mixed": lambda d: d["by_type"]["tyre_flag"]["road"].update(values=[True, "x"]),
               "values not a list": lambda d: d["by_type"]["tyre_flag"]["road"].update(values="road"),
               "entry not an object": lambda d: d["by_type"]["tyre_flag"].update(road=3),
               "types not a list": lambda d: d.update(types={}),
               "type without a label": lambda d: d["types"][0].pop("label"),
               "type total 0": lambda d: d["types"][0].update(total=0),
               "totals that do not add up": lambda d: d["types"][0].update(total=1)}
        for name, damage in bad.items():
            with self.subTest(name):
                with open(self.cache_path, encoding="utf-8") as f:
                    data = json.load(f)
                damage(data)
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                tune._tyre_ranges_loaded.clear()
                with mock.patch.object(tune, "read_tyre_ranges", wraps=tune.read_tyre_ranges) as spy:
                    self.assertEqual(self.ranges(), good)
                    self.assertEqual(spy.call_count, 1)
                with open(self.cache_path, encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["by_type"], good["by_type"])


class TestFindFiles(World):
    def test_a_file_in_an_extracted_car_wins_and_one_walk_finds_all(self):
        with mock.patch.object(tyre_sets, "_local_tyres", wraps=tyre_sets._local_tyres) as spy:
            found = tyre_sets.find_files(self.work, [ROAD_A, ROAD_B, SLICK_S], self.game)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(sorted(found), sorted(tyre_sets.norm(p) for p in (ROAD_A, ROAD_B, SLICK_S)))
        self.assertEqual(found[tyre_sets.norm(ROAD_A)], tyre_sets.find_file(self.work, ROAD_A, self.game))

    def test_the_package_is_read_once_and_the_files_are_extracted_into_tyre_files(self):
        pkg = str(self.d / "content.kspkg")
        names = ["road\\x%d.tyre" % i for i in range(5)]
        pack(pkg, names)
        paths = [GS + "tyres\\" + n for n in names]
        with mock.patch.object(kspkg, "read_table", wraps=kspkg.read_table) as spy:
            found = tyre_sets.find_files(str(self.d / "w2"), paths, pkg)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len(found), 5)
        for n, p in zip(names, paths):
            with open(found[tyre_sets.norm(p)], "rb") as f:
                self.assertEqual(f.read(), b"tyre " + n.encode())
            self.assertTrue(found[tyre_sets.norm(p)].startswith(str(self.d / "w2" / "tyre_files")))

    def test_a_path_that_is_nowhere_or_unsafe_is_left_out(self):
        pkg = str(self.d / "content.kspkg")
        pack(pkg, ["road\\x.tyre"])
        found = tyre_sets.find_files(str(self.d / "w2"), [GS + "tyres\\road\\x.tyre", GS + "tyres\\road\\nope.tyre", "..\\x.tyre"], pkg)
        self.assertEqual(list(found), [tyre_sets.norm(GS + "tyres\\road\\x.tyre")])

    def test_without_a_package_only_the_local_files_are_found(self):
        found = tyre_sets.find_files(self.work, [ROAD_A, GS + "tyres\\road\\nope.tyre"], self.game)
        self.assertEqual(list(found), [tyre_sets.norm(ROAD_A)])


class TestTyreShowColumn(Fields):
    def test_the_table_has_no_game_min_max_column(self):
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "road", "a.tyre"))]["modelData"]["brakeDXMod"] = 0.05
        self.a.store[self.a.key(os.path.join(self.a.shared, "tyres", "slick", "s.tyre"))]["modelData"]["brakeDXMod"] = -0.05
        self.create("Soft")
        code, out, err = self.run_main("tyre-show", "soft", "--work", self.work, "--game", self.game)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual([c.strip() for c in lines[1].split("|")][:6], ["", "id", "value", "default", "unit", "note"])
        rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")] for line in lines[3:]}
        self.assertEqual(rows["tyre_flag"][3], "false")
        self.assertNotIn("game min - max", out)


if __name__ == "__main__":
    unittest.main()
