"""Tests for the tyre choice of tools/tune.py: the "_tyres" state key and its forms, stock_sets, tyre_choices, set_tyres, reset_tyres, the tyre step of apply (own tyre files, compatibletyres, the start tyre in the setup and its limits) and the garage commands.

No game data and no schemas: the cars are synthetic (support.FakeCar replaces tune.load_msg / save_msg with in-memory messages, one shared store for both fake cars; clone_car.build is stubbed for apply, kspkg.cmd_pack is stubbed or, where a test says so, the real one); the game package never exists (self.game), so the tyres are the extracted files; the commands run in-process on those cars, and as a subprocess where nothing decodes a car file.
"""
import contextlib
import copy
import io
import json
import os
import re
import unittest

from support import FakeCar, Sandbox, mini_catalogue, mini_setting, run_main, run_tool, tmp, usage_cases

import clone_car
import kspkg
import tune

USAGE = tune.__doc__.split("\n\n")[1]
REAL_PACK = kspkg.cmd_pack
REAL_RENAME = os.rename
CAR_NOTE = "note: car file: data/x.car renamed to data/CarData.car (the paint shop of a mod car expects that name)"
GS = "content\\cars\\common_phsx\\"
A, B = GS + "tyres\\road\\a.tyre", GS + "tyres\\road\\b.tyre"
S, W = GS + "tyres\\racing_slicks\\s.tyre", GS + "tyres\\racing_wet\\w.tyre"
SC, RS = GS + "tyres\\supercar\\supercar_235_35_19.tyre", GS + "tyres\\road\\road_265_30_19.tyre"
G_F, G_R = GS + "tyres\\gt\\f.tyre", GS + "tyres\\gt\\r.tyre"
A_UP = "CONTENT\\CARS\\COMMON_PHSX\\TYRES\\ROAD\\A.TYRE"
CURVES = {"road": GS + "tyres\\road\\tcurve_road.curve", "slick": GS + "tyres\\slick\\tcurve_slick.curve"}
ROAD, SLICK, WET, SUPER = ("TyreCompound_Road_Generic", "TyreCompound_Racing_Generic_Slick", "TyreCompound_Racing_Generic_Wet",
                           "TyreCompound_Supercar_Generic")
OLD = "TyreCompound_Road_Toyo"
OWN_PATH = "content\\cars\\ax_x\\data\\tyres\\own_%s.tyre"
CONFLICT = "this car has saved tyre values of the old Tyres section and a tyre choice: convert them first"
DAMAGED = "damaged tyre choice in the saved state"
OLD_FORM = "the saved tyre choice was made before the tyre rebuild: choose the tyres again"


def g(path):
    return "game:" + path


def sets(*pairs, **more):
    return dict({"sets": [{"front": f, "rear": r} for f, r in pairs], "split": False}, **more)


def split(fronts, rears, **more):
    return dict({"split": True, "fronts": list(fronts), "rears": list(rears)}, **more)


STOCK = sets((g(A_UP), g(B)), (g(S), g(S)), (g(W), g(W)), (g(SC), g(RS)))


REFUSED = "tyre values are edited in the Tyre Creator: choose or create a tyre there"
CHOICE_FIRST = "this car has a tyre choice already: reset the tyre values or the choice first"
NO_VALUES = "no saved tyre values to convert"
OLD_VALUES = {"tyre_dy_front": 1.4, "tyre_th_front": "slick", "tyre_dy_rear": 1.15}
NOTE_OLD = "note: this car still has saved tyre values of the old Tyres section (%d): convert them with tyres-convert"
STOCK_PAIRS = ((g(A), g(B)), (g(S), g(S)), (g(W), g(W)), (g(SC), g(RS)))


def converted(front, rear):
    """The tyre choice a conversion saves: the pair first, then the stock sets of the car, starting on the pair."""
    return sets((front, rear), *STOCK_PAIRS, start_front=front, start_rear=rear)


def tyre_cat():
    meta = [mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix"),
            mini_setting("variant_name", kind="meta", type="string", default_template="{stock_variant_name}", handler="variant_name")]
    return mini_catalogue(
        *meta,
        mini_setting("tyre_dy_front", group="Tyres", label="Front tyre lateral grip", targets=[("@tyre_front", "modelData.Dy0"), ("@tyre_front", "modelData.Dy1")]),
        mini_setting("tyre_dy_rear", group="Tyres", label="Rear tyre lateral grip", targets=[("@tyre_rear", "modelData.Dy0")]),
        mini_setting("tyre_th_front", group="Tyres", type="enum", choices=["road", "slick"], choice_values=CURVES,
                     targets=[("@tyre_front", "thermalData.thermalPerformanceCurve")]),
        mini_setting("tyre_deep_front", group="Tyres", targets=[("@tyre_front", "modelData.nope.x")]),
        mini_setting("limiter", type="int", targets=[("@engine", "limiter")]))


def tyre_obj(dy, curve="road"):
    return {"name": "stock", "shortName": "ST", "modelData": {"Dy0": dy, "Dy1": dy, "Fz0": 3000}, "thermalData": {"thermalPerformanceCurve": CURVES[curve], "x": 1}}


def alignments(make):
    return {"alignments": [make(i) for i in range(4)], "other": 5}


class World(Sandbox):
    """Two extracted cars. ks_x (the car under test): shared tyres a, b, s, w, road_265_30_19, supercar_235_35_19; the .car names the setup and
    its limits (four alignments each, compound 0 and max 3) and front [A (upper case), S, W] and rear [B, S, W] tyres; the presets p (A+B, S+S,
    W+W with their enum names, extra fields and a wire order, rear tyres as lists, and one compound that names a file in the car folder) and q (S+S, A+B,
    SC+RS, rear tyres as text). The stock sets of ks_x are so a+b, s+s, w+w and sc+rs. ks_y: only the tyres gt f and r."""

    def setUp(self):
        super().setUp()
        self.work = str(self.d / "work")
        self.game = str(self.d / "no_game.kspkg")
        data = {"default": "ks_x", "cars": [{"id": "ks_x", "label": "Car X"}]}
        self.patch(tune, "load_cars", lambda path=None: data)
        self.cat = tyre_cat()
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)
        self.x = FakeCar(self.work, "ks_x").install(self)
        self.y = FakeCar(self.work, "ks_y")
        self.y.store = self.x.store
        self.car = {"stock_setup": self.x.game_path("data/setup.carsetup"), "setupLimits": self.x.game_path("data/limits.carsetuplimits"),
                    "frontTyreCompounds": [A_UP, S, W], "rearTyreCompounds": [B, S, W],
                    "_order": ["frontTyreCompounds"] * 3 + ["rearTyreCompounds"] * 3}
        self.p = {"physic_compounds": [
            {"tyre_compound": ROAD, "front_tyre_data_path": A_UP, "rear_tyre_data_paths": [B], "grip": 1.0},
            {"tyre_compound": SLICK, "front_tyre_data_path": S, "rear_tyre_data_paths": [S], "grip": 2.0},
            {"tyre_compound": WET, "front_tyre_data_path": W, "rear_tyre_data_paths": [W], "grip": 3.0},
            {"tyre_compound": OLD, "front_tyre_data_path": self.x.game_path("data/tyres/odd.tyre"), "rear_tyre_data_paths": [B]}],
            "graphic_compounds": [{"tyre_compound": ROAD, "mark": 1}, {"tyre_compound": SLICK}, {"tyre_compound": WET}, {"tyre_compound": OLD}],
            "_order": ["physic_compounds"] * 4 + ["graphic_compounds"] * 4, "default_index": 0}
        self.q = {"physic_compounds": [{"tyre_compound": SLICK, "front_tyre_data_path": S, "rear_tyre_data_paths": S},
                                       {"tyre_compound": ROAD, "front_tyre_data_path": A, "rear_tyre_data_paths": B},
                                       {"tyre_compound": SUPER, "front_tyre_data_path": SC, "rear_tyre_data_paths": RS}],
                  "graphic_compounds": [{"tyre_compound": SLICK}, {"tyre_compound": ROAD}, {"tyre_compound": SUPER}]}
        self.setup = alignments(lambda i: {"camber": -1.0 - i, "compound": 0.0})
        self.limits = alignments(lambda i: {"compound": {"min": 0.0, "max": 3.0, "is_modifiable": False, "step": 1.0}, "camber": {"max": 9.0}})
        self.x.add("data/x.car", self.car)
        self.x.add("data/setup.carsetup", self.setup)
        self.x.add("data/limits.carsetuplimits", self.limits)
        self.x.add("presets/p.compatibletyres", self.p)
        self.x.add("presets/q.compatibletyres", self.q)
        for rel, dy, curve in (("road/a", 1.2, "road"), ("road/b", 1.1, "road"), ("racing_slicks/s", 1.0, "slick"), ("racing_wet/w", 0.9, "road"),
                               ("road/road_265_30_19", 1.3, "road"), ("supercar/supercar_235_35_19", 1.5, "road")):
            self.x.add_shared("tyres/%s.tyre" % rel, tyre_obj(dy, curve))
        self.y.add_shared("tyres/gt/f.tyre", tyre_obj(2.0))
        self.y.add_shared("tyres/gt/r.tyre", tyre_obj(2.5))
        self.y.add("presets/y.compatibletyres", {"physic_compounds": [{"front_tyre_data_path": G_F, "rear_tyre_data_paths": [G_R]}]})
        self.write(tune.cars_index_path(self.work), [{"id": c, "display_name": "Car " + c[-1].upper(), "brand": "Brand", "year": 1999} for c in ("ks_x", "ks_y")])
        self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_x", "display_name": "Car X", "brand": "Brand", "year": 1999,
                                                              "property_1": "P1", "property_2": "P2", "property_3": "P3", "variant_name": "Base"})

    def tyres(self):
        """The library: gt (source in ks_y only), slicky (source s), soft (source a)."""
        self.gt = tune.create_tyre(self.work, "Gt", G_F, game=self.game)["id"]
        self.slicky = tune.create_tyre(self.work, "Slicky", S, game=self.game)["id"]
        self.soft = tune.create_tyre(self.work, "Soft", A, game=self.game)["id"]
        return self

    def state(self, tune_id=None):
        return tune.load_state(self.work, "ks_x", tune_id)

    def choose(self, choice, tune_id=None, version=None):
        return tune.set_tyres(self.work, "ks_x", choice, tune_id, version, game=self.game)

    def make_tune(self, tune_id="ax01", state=None):
        tune.save_state(self.work, "ks_x", dict(state or {"name_suffix": "_A"}), tune_id)

    def run_main(self, *argv):
        return run_main(tune.main, ["tune.py", *argv, "--work", self.work])


class TestStateKey(World):
    def test_the_key_is_not_an_unknown_state_id_and_the_warning_skips_it(self):
        tune.save_state(self.work, "ks_x", {"limiter": 7000, tune.TYRE_KEY: STOCK, "old": 1})
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat), ["old"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x", self.cat)
        self.assertEqual(err.getvalue(), "warning: ignoring unknown setting 'old' in the saved state\n")
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: STOCK}, tune.DRAFT)
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat, tune.DRAFT), [])

    def test_the_key_is_no_row_and_not_shown(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: STOCK})
        for hidden in (False, True):
            self.assertNotIn(tune.TYRE_KEY, [r["id"] for r in tune.effective_rows(self.work, "ks_x", self.cat, hidden=hidden)])
        code, out, err = self.run_main("show")
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("_tyres", out)

    def test_set_and_unset_of_settings_keep_the_key_and_unset_does_not_touch_it(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: STOCK})
        tune.set_value(self.work, "ks_x", "name_suffix", "_Q", self.cat)
        self.assertEqual(self.state()[tune.TYRE_KEY], STOCK)
        tune.unset_value(self.work, "ks_x", "name_suffix", self.cat)
        self.assertEqual(self.state(), {tune.TYRE_KEY: STOCK})
        for call in (lambda: tune.unset_value(self.work, "ks_x", tune.TYRE_KEY, self.cat), lambda: tune.set_value(self.work, "ks_x", tune.TYRE_KEY, "x", self.cat)):
            with self.assertRaisesRegex(ValueError, "^unknown setting '_tyres'$"):
                call()
        self.assertEqual(self.state(), {tune.TYRE_KEY: STOCK})

    def test_duplicate_tune_copies_the_choice_with_the_rest_of_the_state(self):
        choice = sets((g(S), g(S)), ("own:soft", g(B)), start_front="own:soft", start_rear=g(B))
        tune.save_state(self.work, "ks_x", {"limiter": 8000, tune.TYRE_KEY: choice})
        res = tune.duplicate_tune(self.work, "ks_x", None)
        self.assertEqual(self.state(res["id"])[tune.TYRE_KEY], choice)
        copied = self.state(res["id"])
        copied[tune.TYRE_KEY]["sets"].append({"front": g(W), "rear": g(W)})
        tune.save_state(self.work, "ks_x", copied, res["id"])
        self.assertEqual(self.state()[tune.TYRE_KEY], choice)
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: split([g(W)], [g(B)])}, tune.DRAFT)
        res = tune.duplicate_tune(self.work, "ks_x", tune.DRAFT)
        self.assertEqual(self.state(res["id"])[tune.TYRE_KEY], split([g(W)], [g(B)]))

    def test_new_tune_from_draft_copies_the_key_and_the_draft_keeps_it(self):
        choice = sets((g(S), g(S)))
        tune.save_state(self.work, "ks_x", {"limiter": 9000, tune.TYRE_KEY: choice}, tune.DRAFT)
        res = tune.new_tune_from_draft(self.work, "ks_x")
        self.assertEqual(self.state(res["id"]), {"limiter": 9000, tune.TYRE_KEY: choice, "name_suffix": "MY"})
        self.assertEqual(self.state(tune.DRAFT), {"limiter": 9000, tune.TYRE_KEY: choice})

    def test_the_key_parser(self):
        self.assertEqual(tune.tyre_key("own:soft"), ("own", "soft"))
        self.assertEqual(tune.tyre_key(g(A)), ("game", A))
        for bad in ("own:", "game:", "OWN:soft", "soft", "stock:a|b", "", None, 5, ["own:soft"]):
            with self.subTest(repr(bad)):
                self.assertIsNone(tune.tyre_key(bad))


class TestChoiceForms(unittest.TestCase):
    def test_sets_give_the_lists_each_tyre_once_in_order(self):
        c = tune.parse_choice(sets(("game:a", "game:x"), ("game:b", "game:x"), ("game:a", "game:y")))
        self.assertEqual(tune.choice_lists(c), (["game:a", "game:b"], ["game:x", "game:y"]))
        self.assertEqual((c["split"], c["start_front"], c["start_rear"]), (False, "game:a", "game:x"))
        self.assertEqual(c["sets"], [{"front": "game:a", "rear": "game:x"}, {"front": "game:b", "rear": "game:x"}, {"front": "game:a", "rear": "game:y"}])
        self.assertNotIn("fronts", c)

    def test_the_lists_ignore_case_and_slashes_and_the_first_text_wins(self):
        c = tune.parse_choice(sets(("game:A/b", "game:x"), ("game:a\\B", "game:x")))
        self.assertEqual(tune.choice_lists(c), (["game:A/b"], ["game:x"]))

    def test_split_gives_its_own_lists_and_no_sets(self):
        c = tune.parse_choice(split(["own:a", "game:b"], ["game:c"], start_front="game:b"))
        self.assertEqual(c, {"split": True, "fronts": ["own:a", "game:b"], "rears": ["game:c"], "start_front": "game:b", "start_rear": "game:c"})
        self.assertEqual(tune.choice_lists(c), (["own:a", "game:b"], ["game:c"]))

    def test_the_fields_of_the_other_form_are_dropped(self):
        c = tune.parse_choice(dict(sets(("game:a", "game:b")), fronts=["game:q"], rears=["game:r"]))
        self.assertEqual(sorted(c), ["sets", "split", "start_front", "start_rear"])
        c = tune.parse_choice(dict(split(["game:a"], ["game:b"]), sets=[{"front": "game:q", "rear": "game:r"}]))
        self.assertEqual(sorted(c), ["fronts", "rears", "split", "start_front", "start_rear"])

    def test_a_missing_split_means_false_and_the_start_keys_keep_the_text_of_the_list(self):
        c = tune.parse_choice({"sets": [{"front": "game:A", "rear": "own:x"}], "start_front": "game:a"})
        self.assertEqual((c["split"], c["start_front"], c["start_rear"]), (False, "game:A", "own:x"))

    def test_the_start_tyres_must_be_in_their_lists(self):
        for extra in ({"start_front": "game:x"}, {"start_rear": "game:a"}, {"start_front": "own:q"}, {"start_front": None}, {"start_rear": 5}, {"start_front": "game:"}):
            with self.subTest(extra), self.assertRaisesRegex(ValueError, "^start_(front|rear) .* is not one of the (front|rear) tyres$"):
                tune.parse_choice(sets(("game:a", "game:b"), **extra))

    def test_a_start_on_the_other_axle_list_is_refused(self):
        with self.assertRaisesRegex(ValueError, "start_rear 'game:a' is not one of the rear tyres"):
            tune.parse_choice(split(["game:a"], ["game:b"], start_rear="game:a"))

    def test_faults_of_the_shape(self):
        cases = [(5, "must be an object"), ([], "must be an object"), (None, "must be an object"), ({"split": False}, "sets must be a list with at least one"),
                 ({"sets": [], "split": False}, "sets must be a list with at least one"), ({"sets": "x"}, "sets must be a list"),
                 ({"sets": [5]}, "a set is {front, rear}"), ({"sets": [{"front": "game:a"}]}, "a set is {front, rear}"),
                 ({"sets": [{"front": "game:a", "rear": "game:b", "x": 1}]}, "a set is {front, rear}"),
                 ({"sets": [{"front": "a", "rear": "game:b"}]}, "bad tyre key 'a' in a set"), ({"sets": [{"front": "game:a", "rear": 5}]}, "bad tyre key 5"),
                 ({"sets": [{"front": "stock:a|b", "rear": "game:b"}]}, "bad tyre key"), ({"sets": [{"front": "game:", "rear": "game:b"}]}, "bad tyre key"),
                 (dict(sets(("game:a", "game:b")), split="no"), "split must be true or false"), (dict(sets(("game:a", "game:b")), split=1), "split must be"),
                 (dict(sets(("game:a", "game:b")), more=1), "unknown field 'more'"),
                 ({"split": True}, "fronts must be a list of tyre keys with at least one key"), (split([], ["game:b"]), "fronts must be a list"),
                 (split(["game:a"], []), "rears must be a list"), ({"split": True, "fronts": ["game:a"], "rears": "game:b"}, "rears must be a list"),
                 (split(["game:a", "game:a"], ["game:b"]), "fronts lists a tyre twice"), (split(["game:a", "GAME:a"], ["game:b"]), "bad tyre key 'GAME:a'"),
                 (split(["game:A", "game:a"], ["game:b"]), "fronts lists a tyre twice"), (split(["game:a"], ["own:b", "own:b"]), "rears lists a tyre twice"),
                 (split(["a"], ["game:b"]), "bad tyre key 'a' in fronts")]
        for value, text in cases:
            with self.subTest(str(value)[:60]), self.assertRaisesRegex(ValueError, text):
                tune.parse_choice(value)

    def test_the_same_tyre_in_the_front_and_the_rear_list_is_fine(self):
        c = tune.parse_choice(split(["game:a"], ["game:a"]))
        self.assertEqual(tune.choice_lists(c), (["game:a"], ["game:a"]))


class TestSavedTyres(World):
    def test_no_key_is_no_choice(self):
        self.assertIsNone(tune.saved_tyres({}))
        self.assertIsNone(tune.saved_tyres({"limiter": 1}))

    def test_the_new_form_is_read_and_made_complete(self):
        c = tune.saved_tyres({tune.TYRE_KEY: {"sets": [{"front": "game:a", "rear": "game:b"}]}})
        self.assertEqual(c, {"sets": [{"front": "game:a", "rear": "game:b"}], "split": False, "start_front": "game:a", "start_rear": "game:b"})

    def test_a_damaged_entry_is_an_error_with_the_same_message(self):
        for value in (5, "x", None, True, {}, {"sets": []}, {"split": True}, {"sets": [{"front": "game:a"}], "split": False}, [], [5], ["stock:a"],
                      ["stock:a|"], ["stock:|b"], ["game:a"], ["garbage"], {"sets": [{"front": "game:a", "rear": "game:b"}], "start_front": "game:q"},
                      {"split": True, "fronts": ["game:a"], "rears": ["game:b"], "x": 1}):
            with self.subTest(repr(value)), self.assertRaisesRegex(ValueError, "^%s$" % DAMAGED):
                tune.saved_tyres({tune.TYRE_KEY: value})

    def test_an_old_list_of_stock_entries_is_converted_to_sets_starting_on_the_first(self):
        c = tune.saved_tyres({tune.TYRE_KEY: ["stock:%s|%s" % (A, B), "stock:%s|%s" % (S, S)]})
        self.assertEqual(c, sets((g(A), g(B)), (g(S), g(S)), start_front=g(A), start_rear=g(B)))
        self.assertEqual(tune.choice_lists(c), ([g(A), g(S)], [g(B), g(S)]))

    def test_an_old_list_with_an_own_entry_is_an_error_to_choose_again(self):
        for value in (["own:soft"], ["own:soft", "stock:%s|%s" % (A, B)], ["stock:%s|%s" % (A, B), "own:soft"], ["own:soft", "junk"]):
            with self.subTest(value), self.assertRaisesRegex(ValueError, "^%s$" % OLD_FORM):
                tune.saved_tyres({tune.TYRE_KEY: value})

    def test_the_state_is_not_changed_by_reading(self):
        state = {tune.TYRE_KEY: ["stock:%s|%s" % (A, B)]}
        before = copy.deepcopy(state)
        tune.saved_tyres(state)
        self.assertEqual(state, before)


class TestStockSets(World):
    def test_the_physic_compounds_of_the_presets_in_order_each_pair_once(self):
        got = tune.stock_sets(self.work, "ks_x")
        self.assertEqual([(s["front"], s["rear"]) for s in got], [(g(A_UP), g(B)), (g(S), g(S)), (g(W), g(W)), (g(SC), g(RS))])
        self.assertEqual([s["label"] for s in got], ["Road A / Road b", "Racing slick s / Racing slick s", "Racing wet w / Racing wet w",
                                                     "Supercar 235/35 R19 / Road 265/30 R19"])

    def test_the_labels_are_front_label_slash_rear_label(self):
        got = {s["front"]: s["label"] for s in tune.stock_sets(self.work, "ks_x")}
        self.assertEqual(got[g(SC)], "Supercar 235/35 R19 / Road 265/30 R19")
        self.assertEqual(got[g(A_UP)], "Road A / Road b")
        self.assertEqual(got[g(S)], "Racing slick s / Racing slick s")

    def test_the_text_of_the_file_is_kept_with_backslashes(self):
        self.p["physic_compounds"][1]["front_tyre_data_path"] = S.replace("\\", "/")
        self.x.store[self.x.key(os.path.join(self.x.car_root, "presets", "p.compatibletyres"))] = self.p
        self.assertEqual(tune.stock_sets(self.work, "ks_x")[1]["front"], g(S))

    def test_a_pair_with_a_missing_file_or_outside_the_shared_tyres_is_left_out(self):
        os.remove(os.path.join(self.x.shared, "tyres", "racing_wet", "w.tyre"))
        self.assertEqual([s["front"] for s in tune.stock_sets(self.work, "ks_x")], [g(A_UP), g(S), g(SC)])
        self.assertNotIn(self.x.game_path("data/tyres/odd.tyre"), [s["front"][len("game:"):] for s in tune.stock_sets(self.work, "ks_x")])

    def test_a_compound_without_text_paths_is_left_out(self):
        self.p["physic_compounds"].append({"front_tyre_data_path": A})
        self.p["physic_compounds"].append({"front_tyre_data_path": A, "rear_tyre_data_paths": []})
        self.x.store[self.x.key(os.path.join(self.x.car_root, "presets", "p.compatibletyres"))] = self.p
        self.assertEqual(len(tune.stock_sets(self.work, "ks_x")), 4)

    def test_a_car_without_a_base_or_presets_has_none(self):
        self.assertEqual(tune.stock_sets(self.work, "ks_nobase"), [])
        for n in ("p", "q"):
            os.remove(os.path.join(self.x.car_root, "presets", n + ".compatibletyres"))
        self.assertEqual(tune.stock_sets(self.work, "ks_x"), [])

    def test_the_other_car_has_its_own_sets(self):
        self.assertEqual([(s["front"], s["rear"], s["label"]) for s in tune.stock_sets(self.work, "ks_y")], [(g(G_F), g(G_R), "gt f / gt r")])


class TestChoices(World):
    def test_the_default_is_the_stock_choice_of_the_car(self):
        res = tune.tyre_choices(self.work, "ks_x")
        self.assertEqual((res["default"], res["split"], res["car"], res["tune"]), (True, False, "ks_x", None))
        self.assertEqual(res["sets"], STOCK["sets"])
        self.assertEqual((res["fronts"], res["rears"]), ([g(A_UP), g(S), g(W), g(SC)], [g(B), g(S), g(W), g(RS)]))
        self.assertEqual((res["start_front"], res["start_rear"]), (g(A_UP), g(B)))
        self.assertEqual([s["label"] for s in res["stock_sets"]], [res["labels"][s["front"]] + " / " + res["labels"][s["rear"]] for s in res["stock_sets"]])
        self.assertEqual(res["labels"][g(SC)], "Supercar 235/35 R19")
        self.assertEqual(set(res), {"default", "stock_sets", "sets", "split", "fronts", "rears", "start_front", "start_rear", "labels", "car", "tune"})

    def test_a_saved_choice_is_shown_with_the_labels_of_own_tyres(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), (g(S), g(S)), start_front=g(S), start_rear=g(S)))
        res = tune.tyre_choices(self.work, "ks_x")
        self.assertEqual((res["default"], res["split"]), (False, False))
        self.assertEqual((res["fronts"], res["rears"]), (["own:soft", g(S)], [g(B), g(S)]))
        self.assertEqual((res["start_front"], res["start_rear"]), (g(S), g(S)))
        self.assertEqual(res["labels"]["own:soft"], "Soft")
        self.assertEqual(len(res["stock_sets"]), 4)

    def test_a_split_choice_has_no_sets(self):
        self.choose(split([g(S), g(A)], [g(B)], start_front=g(A)))
        res = tune.tyre_choices(self.work, "ks_x")
        self.assertEqual((res["split"], res["sets"], res["fronts"], res["rears"], res["start_front"], res["start_rear"]),
                         (True, [], [g(S), g(A)], [g(B)], g(A), g(B)))

    def test_the_old_form_is_read_as_sets(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: ["stock:%s|%s" % (S, S), "stock:%s|%s" % (W, W)]})
        res = tune.tyre_choices(self.work, "ks_x")
        self.assertEqual((res["default"], res["fronts"], res["start_front"]), (False, [g(S), g(W)], g(S)))

    def test_a_damaged_or_old_choice_with_own_tyres_is_an_error(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: 5})
        with self.assertRaisesRegex(ValueError, "^%s$" % DAMAGED):
            tune.tyre_choices(self.work, "ks_x")
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: ["own:soft"]})
        with self.assertRaisesRegex(ValueError, "^%s$" % OLD_FORM):
            tune.tyre_choices(self.work, "ks_x")

    def test_a_car_without_sets_and_without_a_choice_has_empty_lists(self):
        for n in ("p", "q"):
            os.remove(os.path.join(self.x.car_root, "presets", n + ".compatibletyres"))
        res = tune.tyre_choices(self.work, "ks_x")
        self.assertEqual((res["default"], res["sets"], res["fronts"], res["rears"], res["start_front"], res["start_rear"], res["stock_sets"]),
                         (True, [], [], [], None, None, []))

    def test_the_modded_car_the_draft_and_a_version_read_their_own_state(self):
        self.make_tune()
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        self.choose(sets((g(S), g(S))), "ax01")
        self.choose(sets((g(W), g(W))), tune.DRAFT)
        self.choose(sets((g(B), g(B))), "ax01", vid)
        got = {t: tune.tyre_choices(self.work, "ks_x", t) for t in (None, "ax01", tune.DRAFT)}
        self.assertEqual([got[t]["start_front"] for t in (None, "ax01", tune.DRAFT)], [g(A_UP), g(S), g(W)])
        self.assertEqual((got["ax01"]["tune"], got[tune.DRAFT]["tune"]), ("ax01", tune.DRAFT))
        self.assertEqual(tune.tyre_choices(self.work, "ks_x", "ax01", vid)["start_front"], g(B))
        self.assertEqual(tune.tyre_choices(self.work, "ks_x", "ax01", vid)["tune"], "ax01")


class TestSetTyres(World):
    def test_a_choice_is_saved_in_the_complete_form_and_answered(self):
        self.tyres()
        res = self.choose(sets(("own:soft", g(B)), (g(S), g(S))))
        self.assertEqual(res, {"default": False, "sets": [{"front": "own:soft", "rear": g(B)}, {"front": g(S), "rear": g(S)}], "split": False,
                               "fronts": ["own:soft", g(S)], "rears": [g(B), g(S)], "start_front": "own:soft", "start_rear": g(B)})
        self.assertEqual(self.state()[tune.TYRE_KEY], sets(("own:soft", g(B)), (g(S), g(S)), start_front="own:soft", start_rear=g(B)))

    def test_a_split_choice_stores_no_sets_and_a_set_choice_no_lists(self):
        self.choose(split([g(S), g(A)], [g(B)], start_front=g(A)))
        self.assertEqual(self.state()[tune.TYRE_KEY], split([g(S), g(A)], [g(B)], start_front=g(A), start_rear=g(B)))
        self.choose(dict(sets((g(S), g(W))), fronts=[g(A)], rears=[g(B)]))
        self.assertEqual(sorted(self.state()[tune.TYRE_KEY]), ["sets", "split", "start_front", "start_rear"])

    def test_the_start_tyres_of_each_axle_are_kept(self):
        res = self.choose(sets((g(S), g(S)), (g(A), g(B)), (g(W), g(W)), start_front=g(W), start_rear=g(B)))
        self.assertEqual((res["start_front"], res["start_rear"]), (g(W), g(B)))

    def test_a_key_is_stored_the_way_the_index_writes_the_path(self):
        res = self.choose(sets(("game:CONTENT/CARS/COMMON_PHSX/TYRES/ROAD/A.TYRE", g(B).replace("\\", "/"))))
        self.assertEqual((res["fronts"], res["rears"]), ([g(A)], [g(B)]))

    def test_the_car_s_own_choice_removes_the_entry(self):
        self.choose(sets((g(S), g(S))))
        res = self.choose(STOCK)
        self.assertEqual((res["default"], res["start_front"]), (True, g(A)))
        self.assertEqual(self.state(), {})
        res = self.choose(sets((g(A), g(B)), (g(S), g(S)), (g(W), g(W)), (g(SC), g(RS))))
        self.assertTrue(res["default"])
        self.assertEqual(self.state(), {})

    def test_the_stock_sets_with_another_start_order_or_form_are_a_choice(self):
        for choice in (dict(STOCK, start_rear=g(S)), dict(STOCK, start_front=g(S)), sets(*[(s["front"], s["rear"]) for s in reversed(STOCK["sets"])]),
                       sets(*[(s["front"], s["rear"]) for s in STOCK["sets"][:3]]), split([g(A_UP), g(S), g(W), g(SC)], [g(B), g(S), g(W), g(RS)])):
            with self.subTest(str(choice)[:80]):
                self.assertFalse(self.choose(choice)["default"])
                self.assertIn(tune.TYRE_KEY, self.state())

    def test_a_car_without_stock_sets_always_saves(self):
        for n in ("p", "q"):
            os.remove(os.path.join(self.x.car_root, "presets", n + ".compatibletyres"))
        self.assertFalse(self.choose(sets((g(A), g(B))))["default"])
        self.assertIn(tune.TYRE_KEY, self.state())

    def test_the_rest_of_the_state_is_kept(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000})
        self.choose(sets((g(S), g(S))))
        self.assertEqual(self.state()["limiter"], 8000)
        self.choose(STOCK)
        self.assertEqual(self.state(), {"limiter": 8000})

    def test_bad_choices_are_refused_and_change_nothing(self):
        self.tyres()
        os.makedirs(os.path.join(self.work, "tyres"), exist_ok=True)
        self.write(os.path.join(self.work, "tyres", "old.json"), {"version": 1, "name": "Old", "source": {"front": A, "rear": B}, "values": {}})
        tune.save_state(self.work, "ks_x", {"limiter": 7000})
        before = self.state()
        cases = [(5, "must be an object"), (["own:soft"], "must be an object"), (sets(), "sets must be a list with at least one"), ({}, "sets must be"),
                 (sets(("game:" + GS + "tyres\\road\\nope.tyre", g(B))), "unknown tyre content.cars.common_phsx.tyres.road.nope.tyre, tyre-index lists the tyres"),
                 (sets(("game:content\\cars\\ks_x\\data\\a.tyre", g(B))), "is not a tyre file below"), (sets(("game:road\\a.tyre", g(B))), "is not a tyre file below"),
                 (sets(("own:nope", g(B))), "^no tyre 'nope' in the library$"), (sets(("own:old", g(B))), "old front/rear form"),
                 (sets((g(A), "own:../x")), "^bad tyre id"), (split([g(A)], [g(B), g(B)]), "rears lists a tyre twice"),
                 (sets((g(A), g(B)), start_front=g(S)), "start_front .* is not one of the front tyres")]
        for choice, text in cases:
            with self.subTest(str(choice)[:80]), self.assertRaisesRegex(ValueError, text.replace(".", ".") if text.startswith("^") else text):
                self.choose(choice)
            self.assertEqual(self.state(), before)

    def test_the_tyres_are_checked_against_the_package_index_when_there_is_a_package(self):
        from test_tyre_library import pack
        pkg = str(self.d / "content.kspkg")
        pack(pkg, ["road\\a.tyre", "road\\b.tyre", "road\\only_in_the_package.tyre"])
        res = tune.set_tyres(self.work, "ks_x", sets((g(A.upper()), g(GS + "tyres\\road\\only_in_the_package.tyre"))), game=pkg)
        self.assertEqual((res["fronts"], res["rears"]), ([g(A)], [g(GS + "tyres\\road\\only_in_the_package.tyre")]))
        with self.assertRaisesRegex(ValueError, "unknown tyre .*road.nope"):
            tune.set_tyres(self.work, "ks_x", sets((g(A), g(GS + "tyres\\road\\nope.tyre"))), game=pkg)
        with self.assertRaisesRegex(ValueError, "unknown tyre"):
            tune.set_tyres(self.work, "ks_x", sets((g(S), g(B))), game=pkg)

    def test_the_modded_car_the_draft_and_the_default_tune_have_their_own_choice(self):
        self.make_tune()
        self.choose(sets((g(S), g(S))), "ax01")
        self.choose(sets((g(W), g(W))), tune.DRAFT)
        self.choose(sets((g(B), g(B))))
        self.assertEqual([self.state(t)[tune.TYRE_KEY]["start_front"] for t in ("ax01", tune.DRAFT, None)], [g(S), g(W), g(B)])
        self.assertEqual(self.state("ax01")["name_suffix"], "_A")

    def test_the_default_tune_is_not_created_by_a_choice_of_the_draft(self):
        self.choose(sets((g(S), g(S))), tune.DRAFT)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))


class TestVersions(World):
    def setUp(self):
        super().setUp()
        self.tyres()
        self.make_tune()
        self.v1 = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        self.v2 = tune.add_version(self.work, "ks_x", "Light", "ax01")

    def vstate(self, version):
        return tune.read_version_state(self.work, "ks_x", version, "ax01")

    def test_each_version_keeps_its_own_choice_and_the_base_keeps_its_own(self):
        self.choose(sets((g(S), g(S))), "ax01")
        self.choose(sets(("own:soft", g(B))), "ax01", self.v1)
        self.choose(split([g(W)], [g(W), g(S)], start_rear=g(S)), "ax01", self.v2)
        self.assertEqual(self.state("ax01")[tune.TYRE_KEY]["start_front"], g(S))
        self.assertEqual(self.vstate(self.v1)[tune.TYRE_KEY]["start_front"], "own:soft")
        self.assertEqual(self.vstate(self.v2)[tune.TYRE_KEY]["start_rear"], g(S))
        self.assertEqual(tune.tyre_choices(self.work, "ks_x", "ax01", self.v2)["rears"], [g(W), g(S)])
        self.assertEqual(self.choose(STOCK, "ax01", self.v1)["default"], True)
        self.assertEqual(self.vstate(self.v1), {})
        self.assertIn(tune.TYRE_KEY, self.vstate(self.v2))

    def test_a_version_choice_is_not_shared_with_the_base_when_the_version_state_is_loaded(self):
        self.choose(sets((g(S), g(S))), "ax01")
        state = tune.load_version_state(self.work, "ks_x", self.v1, "ax01", self.cat)
        self.assertNotIn(tune.TYRE_KEY, state)

    def test_reset_of_a_version_removes_only_its_own_entry(self):
        self.choose(sets((g(S), g(S))), "ax01")
        self.choose(sets((g(W), g(W))), "ax01", self.v1)
        self.assertEqual(tune.reset_tyres(self.work, "ks_x", "ax01", self.v1), {"removed": True})
        self.assertEqual(tune.reset_tyres(self.work, "ks_x", "ax01", self.v1), {"removed": False})
        self.assertIn(tune.TYRE_KEY, self.state("ax01"))

    def test_a_locked_version_is_refused_and_its_state_stays(self):
        self.choose(sets((g(S), g(S))), "ax01", self.v1)
        tune.save_json(tune.version_meta_path(self.work, "ks_x", self.v1, "ax01"), {"name": "Heavy", "locked": True})
        before = self.vstate(self.v1)
        for call in (lambda: self.choose(sets(("own:soft", g(B))), "ax01", self.v1), lambda: tune.reset_tyres(self.work, "ks_x", "ax01", self.v1)):
            with self.assertRaisesRegex(ValueError, r"^version v01 \(Heavy\) is locked; unlock it to change it$"):
                call()
        self.assertEqual(self.vstate(self.v1), before)

    def test_an_unknown_version_and_a_version_of_the_draft_are_errors(self):
        with self.assertRaisesRegex(ValueError, "^ks_x has no version v09 of ax01$"):
            self.choose(STOCK, "ax01", "v09")
        with self.assertRaisesRegex(ValueError, "^the draft has no versions$"):
            self.choose(STOCK, tune.DRAFT, self.v1)

    def test_a_version_of_the_default_tune(self):
        tune.save_state(self.work, "ks_x", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Own")
        self.choose(sets((g(W), g(W))), None, vid)
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid)[tune.TYRE_KEY]["start_front"], g(W))
        self.assertNotIn(tune.TYRE_KEY, self.state())


class TestResetTyres(World):
    def test_reset_removes_the_key_and_keeps_the_rest(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000, tune.TYRE_KEY: STOCK})
        self.assertEqual(tune.reset_tyres(self.work, "ks_x"), {"removed": True})
        self.assertEqual(self.state(), {"limiter": 8000})
        self.assertEqual(tune.reset_tyres(self.work, "ks_x"), {"removed": False})

    def test_reset_writes_nothing_without_a_key_and_follows_the_tune(self):
        self.assertEqual(tune.reset_tyres(self.work, "ks_x", "ax01"), {"removed": False})
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tunes")))
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: STOCK}, tune.DRAFT)
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: STOCK})
        self.assertTrue(tune.reset_tyres(self.work, "ks_x", tune.DRAFT)["removed"])
        self.assertEqual(self.state(), {tune.TYRE_KEY: STOCK})

    def test_a_damaged_entry_is_removed_too(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: 5})
        self.assertTrue(tune.reset_tyres(self.work, "ks_x")["removed"])
        self.assertEqual(self.state(), {})

    def test_the_reset_choice_is_the_default_again(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: STOCK})
        tune.reset_tyres(self.work, "ks_x")
        self.assertTrue(tune.tyre_choices(self.work, "ks_x")["default"])


class TestRemovedFunctions(unittest.TestCase):
    def test_the_old_garage_functions_are_gone(self):
        for name in ("garage_entries", "garage_choices", "set_garage", "reset_garage", "garage_selection", "garage_compounds", "garage_list", "garage_plan",
                     "write_garage", "garage_key", "check_garage_keys", "saved_garage", "car_stock_tyres", "list_source_tyres", "source_tyre", "tyre_source_files"):
            self.assertFalse(hasattr(tune, name), name)


class Apply(World):
    """apply of ks_x with clone_car.build and kspkg.cmd_pack stubbed; the files of the build are the stub contents of FakeCar."""

    def setUp(self):
        super().setUp()
        self.calls, self.packed, self.real_pack = [], [], False
        self.patch(clone_car, "build", self.build)
        self.patch(kspkg, "cmd_pack", self.pack)
        self.patch(tune, "ensure_stock_loc", lambda work, game=None: "present")
        self.patch(os, "rename", self.rename)
        stub = tune.save_msg

        def save_and_touch(path, name, obj):
            stub(path, name, obj)
            with open(kspkg.long_path(path), "wb"):
                pass
        self.patch(tune, "save_msg", save_and_touch)

    def rename(self, src, dst):
        old, new = self.x.key(src), self.x.key(dst)
        moved = [k for k in self.x.store if k == old or k.startswith(old + os.sep)]
        REAL_RENAME(src, dst)
        self.x.store.update({new + k[len(old):]: self.x.store.pop(k) for k in moved})

    def build(self, car_dir, new_id, out_dir, name, year, brand, variant, stock_loc, props, pack=True):
        self.calls.append(("build", new_id))
        print("progress noise of the clone")
        self.x.clone_into(out_dir, new_id)
        return ["note: from build"]

    def pack(self, indir, pkg):
        self.calls.append(("pack", indir))
        self.packed.append(sorted(os.path.relpath(os.path.join(dp, n), indir).replace(os.sep, "/") for dp, _, names in os.walk(indir) for n in names))
        if self.real_pack:
            REAL_PACK(indir, pkg)
        else:
            with open(pkg, "wb") as f:
                f.write(b"PKG-NEW")

    def apply(self, state=None, tune_id=None, **kw):
        if state is not None:
            tune.save_state(self.work, "ks_x", state, tune_id)
        kw.setdefault("install", False)
        return tune.apply(self.work, "ks_x", tune_id, catalogue=self.cat, game=self.game, **kw)

    def built(self, res, rel):
        return self.x.store[self.x.key(os.path.join(res["build_dir"], "content", "cars", res["new_id"], *rel.split("/")))]

    def tree(self, res):
        root = os.path.join(res["build_dir"], "content", "cars", res["new_id"])
        return sorted(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/") for dp, _, names in os.walk(root) for n in names)

    def compounds(self, res, name, field="physic_compounds"):
        return self.built(res, "presets/%s.compatibletyres" % name)[field]

    def names(self, res, name):
        return [c["tyre_compound"] for c in self.compounds(res, name)], [c["tyre_compound"] for c in self.compounds(res, name, "graphic_compounds")]

    def aligned(self, res, key="compound"):
        return [a[key] for a in self.built(res, "data/setup.carsetup")["alignments"]]

    def limited(self, res):
        return [(a["compound"]["max"], a["compound"]["is_modifiable"]) for a in self.built(res, "data/limits.carsetuplimits")["alignments"]]

    def snapshot(self, res):
        root = self.x.key(os.path.join(res["build_dir"], "content", "cars", res["new_id"]))
        return {k[len(root):]: json.dumps(v, sort_keys=True) for k, v in self.x.store.items() if k.startswith(root + os.sep)}


class TestApplyWithoutAChoice(Apply):
    def test_without_the_key_nothing_of_the_tyre_choice_runs_and_the_build_keeps_its_data(self):
        self.patch(tune, "tyre_plan", lambda *a, **k: self.fail("tyre_plan"))
        self.patch(tune, "write_tyre_choice", lambda *a, **k: self.fail("write_tyre_choice"))
        self.patch(tune, "start_tyre_edits", lambda *a, **k: self.fail("start_tyre_edits"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = self.apply({"name_suffix": "_Z"})
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE])
        self.assertEqual([a["id"] for a in res["applied"]], ["name_suffix"])
        self.assertEqual(self.built(res, "data/CarData.car")["frontTyreCompounds"], [A_UP, S, W])
        self.assertEqual(self.compounds(res, "p")[0], self.p["physic_compounds"][0])
        self.assertEqual(self.compounds(res, "p")[3]["front_tyre_data_path"], "content\\cars\\ax_x\\data\\tyres\\odd.tyre")
        self.assertEqual(self.built(res, "presets/q.compatibletyres"), self.q)
        self.assertEqual(self.aligned(res), [0.0] * 4)
        self.assertEqual(self.limited(res), [(3.0, False)] * 4)
        self.assertEqual([t for t in self.tree(res) if "own_" in t], [])

    def test_the_car_s_own_choice_builds_like_a_car_that_never_had_one(self):
        first = self.apply({"name_suffix": "_Z"})
        before, tree = self.snapshot(first), self.tree(first)
        self.choose(sets((g(S), g(S))))
        self.apply()
        self.choose(STOCK)
        second = self.apply()
        self.assertEqual((self.snapshot(second), self.tree(second), second["notes"], second["applied"]), (before, tree, first["notes"], first["applied"]))

    def test_a_tyre_setting_alone_works_as_before(self):
        res = self.apply({"tyre_dy_front": 1.4})
        self.assertIn("tyre front: own file content\\cars\\ax_x\\data\\tyres\\ax_x_front.tyre replaces", res["notes"][-3])
        self.assertEqual(res["notes"][-1], NOTE_OLD % 1)
        self.assertEqual(len(res["notes"]), 4)
        self.assertEqual(self.aligned(res), [0.0] * 4)


class TestApplyOwnTyre(Apply):
    def test_an_own_tyre_alone_gives_one_compound_per_file_with_its_path(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        res = self.apply()
        self.assertEqual(self.compounds(res, "p"), [{"tyre_compound": ROAD, "front_tyre_data_path": OWN_PATH % "soft", "rear_tyre_data_paths": [B]}])
        self.assertEqual(self.compounds(res, "q"), [{"tyre_compound": ROAD, "front_tyre_data_path": OWN_PATH % "soft", "rear_tyre_data_paths": B}])
        self.assertEqual(self.compounds(res, "p", "graphic_compounds"), [{"tyre_compound": ROAD, "mark": 1}])
        self.assertEqual(self.compounds(res, "q", "graphic_compounds"), [{"tyre_compound": ROAD}])
        self.assertEqual(res["applied"], [])

    def test_the_own_file_holds_the_source_data_the_values_the_name_and_the_short_name(self):
        self.tyres()
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.4", self.cat)
        tune.set_tyre_value(self.work, "soft", "tyre_th", "slick", self.cat)
        tune.rename_tyre(self.work, "soft", "Soft Cup", "SC")
        self.choose(sets(("own:soft", g(B))))
        res = self.apply()
        own = self.built(res, "data/tyres/own_soft.tyre")
        self.assertEqual([tune.plain(own["modelData"][k]) for k in ("Dy0", "Dy1", "Fz0")], [1.4, 1.4, 3000])
        self.assertEqual(own["thermalData"], {"thermalPerformanceCurve": CURVES["slick"], "x": 1})
        self.assertEqual((own["name"], own["shortName"]), ("Soft Cup (SC)", "SC"))
        self.assertEqual(sorted(own), ["modelData", "name", "shortName", "thermalData"])
        self.assertEqual(self.x.store[self.x.key(os.path.join(self.x.shared, "tyres", "road", "a.tyre"))], tyre_obj(1.2))

    def test_one_file_per_own_tyre_and_only_for_the_tyres_in_the_choice(self):
        self.tyres()
        self.choose(split(["own:soft", g(S)], ["own:gt", "own:soft"]))
        res = self.apply()
        self.assertEqual([t for t in self.tree(res) if "own_" in t], ["data/tyres/own_gt.tyre", "data/tyres/own_soft.tyre"])
        self.assertEqual(tune.plain(self.built(res, "data/tyres/own_gt.tyre")["modelData"]["Dy0"]), 2.0)
        self.choose(sets((g(S), g(S))))
        self.assertEqual([t for t in self.tree(self.apply()) if "own_" in t], [])

    def test_the_source_of_a_tyre_of_another_car_is_read_from_that_car(self):
        self.tyres()
        self.choose(sets(("own:gt", "own:gt")))
        res = self.apply()
        self.assertEqual(self.compounds(res, "q")[0]["front_tyre_data_path"], OWN_PATH % "gt")
        self.assertEqual(self.compounds(res, "q")[0]["rear_tyre_data_paths"], OWN_PATH % "gt")

    def test_the_type_of_the_source_names_the_compound_of_an_own_tyre(self):
        self.tyres()
        self.choose(sets(("own:slicky", "own:slicky")))
        res = self.apply()
        self.assertEqual(self.names(res, "p"), ([SLICK], [SLICK]))
        self.choose(sets(("own:soft", g(B))))
        self.assertEqual(self.names(self.apply(), "p"), ([ROAD], [ROAD]))
        self.choose(sets(("own:gt", g(B))))
        self.assertEqual(self.names(self.apply(), "p"), (["TyreCompound_Special_Generic"], ["TyreCompound_Special_Generic"]))

    def test_the_new_files_are_in_the_files_the_package_is_packed_from(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), ("own:gt", g(B))))
        res = self.apply()
        self.assertIn("data/tyres/own_soft.tyre", self.tree(res))
        self.assertEqual(self.packed[-1], sorted("content/cars/ax_x/" + t for t in self.tree(res)))

    def test_the_real_package_contains_them(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        self.real_pack = True
        res = self.apply()
        with open(res["package"], "rb") as f:
            entries = [e["path"] for e in kspkg.read_table(f)[1]]
        self.assertIn("content\\cars\\ax_x\\data\\tyres\\own_soft.tyre", entries)
        self.assertNotIn("content\\cars\\ax_x\\data\\tyres\\own_soft_front.tyre", entries)

    def test_a_second_apply_starts_from_the_base_and_leaves_no_file_of_a_tyre_that_is_gone_from_the_choice(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), ("own:gt", g(B))))
        first = self.apply()
        self.assertIn("data/tyres/own_gt.tyre", self.tree(first))
        self.choose(sets(("own:soft", g(B))))
        second = self.apply()
        self.assertEqual([t for t in self.tree(second) if "own_" in t], ["data/tyres/own_soft.tyre"])
        self.assertFalse(os.path.exists(first["build_dir"] + ".partial"))


class TestApplyCompounds(Apply):
    def test_a_stock_pair_keeps_its_compound_with_all_its_fields_and_a_new_pair_gets_a_free_name_of_its_type(self):
        self.choose(split([g(S), g(A)], [g(B)], start_front=g(A)))
        res = self.apply()
        p = self.compounds(res, "p")
        self.assertEqual(p[1], self.p["physic_compounds"][0])
        self.assertEqual(p[0], {"tyre_compound": SLICK, "front_tyre_data_path": S, "rear_tyre_data_paths": [B]})
        self.assertEqual(self.names(res, "p"), ([SLICK, ROAD], [SLICK, ROAD]))
        self.assertEqual(self.compounds(res, "p", "graphic_compounds")[1], {"tyre_compound": ROAD, "mark": 1})

    def test_the_compounds_of_the_file_that_the_choice_does_not_name_are_dropped(self):
        self.choose(sets((g(S), g(S))))
        res = self.apply()
        self.assertEqual(self.compounds(res, "p"), [self.p["physic_compounds"][1]])
        self.assertEqual(self.compounds(res, "q"), [self.q["physic_compounds"][0]])

    def test_the_stock_sets_with_another_start_keep_every_stock_compound_of_the_file(self):
        self.choose(dict(STOCK, start_front=g(S)))
        res = self.apply()
        p = self.compounds(res, "p")
        self.assertEqual(p[:3], self.p["physic_compounds"][:3])
        self.assertEqual(p[3], {"tyre_compound": SUPER, "front_tyre_data_path": SC, "rear_tyre_data_paths": [RS]})
        self.assertEqual(self.names(res, "p"), ([ROAD, SLICK, WET, SUPER], [ROAD, SLICK, WET, SUPER]))
        q = self.compounds(res, "q")
        self.assertEqual([c["front_tyre_data_path"] for c in q], [A, S, W, SC])
        self.assertEqual([q[0], q[1], q[3]], [self.q["physic_compounds"][1], self.q["physic_compounds"][0], self.q["physic_compounds"][2]])
        self.assertEqual(q[2], {"tyre_compound": WET, "front_tyre_data_path": W, "rear_tyre_data_paths": W})

    def test_every_compounds_file_of_the_build_gets_the_choice_and_other_fields_stay(self):
        self.choose(sets((g(S), g(S))))
        res = self.apply()
        self.assertEqual(self.built(res, "presets/p.compatibletyres")["default_index"], 0)
        self.assertEqual(sorted(k for k in self.built(res, "presets/p.compatibletyres") if not k.startswith("_")), ["default_index", "graphic_compounds", "physic_compounds"])

    def test_the_wire_order_follows_the_new_lengths(self):
        self.choose(split([g(S), g(A), g(W)], [g(B)]))
        res = self.apply()
        p = self.built(res, "presets/p.compatibletyres")
        self.assertEqual(p["_order"], ["physic_compounds"] * 3 + ["graphic_compounds"] * 3)
        self.assertEqual(len(p["physic_compounds"]), 3)

    def test_a_file_without_compounds_gets_them_and_a_plain_text_rear_stays_plain(self):
        self.x.add("presets/r.compatibletyres", {"default_index": 0})
        self.choose(sets((g(S), g(S))))
        res = self.apply()
        self.assertEqual(self.compounds(res, "r"), [{"tyre_compound": SLICK, "front_tyre_data_path": S, "rear_tyre_data_paths": [S]}])
        self.assertEqual(self.compounds(res, "r", "graphic_compounds"), [{"tyre_compound": SLICK}])

    def test_the_car_file_and_its_tyre_lists_are_not_changed(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), (g(S), g(S))))
        res = self.apply()
        car = self.built(res, "data/CarData.car")
        self.assertEqual((car["frontTyreCompounds"], car["rearTyreCompounds"], car["_order"]), ([A_UP, S, W], [B, S, W], self.car["_order"]))

    def test_every_front_tyre_of_the_menu_has_a_unique_compound_name_in_each_file(self):
        self.tyres()
        self.choose(split([g(A), g(S), g(W), g(SC), "own:soft", "own:slicky"], [g(B), g(RS)]))
        res = self.apply()
        for name in ("p", "q"):
            names = self.names(res, name)[0]
            self.assertEqual((len(names), len(set(names))), (6, 6))
            self.assertEqual(names, self.names(res, name)[1])


class TestApplyStartTyre(Apply):
    def test_the_start_index_of_each_axle_goes_to_the_setup_and_the_highest_index_to_its_limits(self):
        self.choose(split([g(S), g(A), g(W)], [g(B), g(S)], start_front=g(W), start_rear=g(S)))
        res = self.apply()
        self.assertEqual(self.aligned(res), [2.0, 2.0, 1.0, 1.0])
        self.assertEqual(self.limited(res), [(2.0, True), (2.0, True), (1.0, True), (1.0, True)])

    def test_the_default_start_is_the_first_tyre_of_each_list(self):
        res = (self.choose(sets((g(S), g(S)), (g(A), g(B)))), self.apply())[1]
        self.assertEqual((self.aligned(res), self.limited(res)), ([0.0] * 4, [(1.0, True), (1.0, True), (1.0, True), (1.0, True)]))

    def test_one_tyre_per_axle_limits_the_menu_to_index_zero(self):
        res = (self.choose(sets((g(A), g(B)))), self.apply())[1]
        self.assertEqual(self.limited(res), [(0.0, True)] * 4)

    def test_the_other_fields_of_the_setup_and_its_limits_stay(self):
        res = (self.choose(sets((g(S), g(S)), (g(A), g(B)), start_front=g(A))), self.apply())[1]
        setup, limits = self.built(res, "data/setup.carsetup"), self.built(res, "data/limits.carsetuplimits")
        self.assertEqual([a["camber"] for a in setup["alignments"]], [-1.0, -2.0, -3.0, -4.0])
        self.assertEqual(setup["other"], 5)
        self.assertEqual([(a["compound"]["min"], a["compound"]["step"], a["camber"]) for a in limits["alignments"]], [(0.0, 1.0, {"max": 9.0})] * 4)
        self.assertEqual(limits["other"], 5)

    def test_the_stock_files_are_not_changed(self):
        self.choose(sets((g(S), g(S)), (g(A), g(B)), start_front=g(A)))
        self.apply()
        self.assertEqual(self.x.store[self.x.key(os.path.join(self.x.car_root, "data", "setup.carsetup"))], self.setup)
        self.assertEqual(self.x.store[self.x.key(os.path.join(self.x.car_root, "data", "limits.carsetuplimits"))], self.limits)

    def test_missing_keys_of_the_files_are_added(self):
        self.x.add("data/setup.carsetup", alignments(lambda i: {"camber": -1.0}))
        self.x.add("data/limits.carsetuplimits", alignments(lambda i: {"camber": {"max": 9.0}} if i % 2 else {"compound": {"min": 0.0}}))
        res = (self.choose(sets((g(S), g(S)), (g(A), g(B)), start_front=g(A))), self.apply())[1]
        self.assertEqual(self.aligned(res), [1.0, 1.0, 0.0, 0.0])
        self.assertEqual(self.limited(res), [(1.0, True)] * 4)
        self.assertEqual(self.built(res, "data/limits.carsetuplimits")["alignments"][0]["compound"]["min"], 0.0)

    def test_the_start_tyre_comes_through_the_same_path_as_the_other_setting_edits(self):
        self.cat = mini_catalogue(*self.cat["settings"], mini_setting("camber", targets=[("@setup", "alignments[0].camber"), ("@setup", "alignments[1].camber")]))
        tune.save_state(self.work, "ks_x", {"camber": -3.5})
        res = (self.choose(sets((g(S), g(S)), (g(A), g(B)), start_front=g(A))), self.apply())[1]
        setup = self.built(res, "data/setup.carsetup")
        self.assertEqual([tune.plain(a["camber"]) for a in setup["alignments"]], [-3.5, -3.5, -3.0, -4.0])
        self.assertEqual(self.aligned(res), [1.0, 1.0, 0.0, 0.0])
        applied = {a["id"]: a for a in res["applied"]}
        self.assertEqual(list(applied), ["camber"])
        self.assertEqual(applied["camber"]["files"], ["data/setup.carsetup"])


class TestApplyEqualChoices(Apply):
    def test_two_forms_with_the_same_lists_and_starts_build_identical_files(self):
        self.tyres()
        self.make_tune()
        self.choose(sets(("own:soft", g(B)), (g(S), g(B)), (g(S), g(W))), "ax01")
        a = tune.apply(self.work, "ks_x", "ax01", install=False, catalogue=self.cat, game=self.game)
        shot_a, tree_a = self.snapshot(a), self.tree(a)
        self.choose(split(["own:soft", g(S)], [g(B), g(W)]), "ax01")
        b = tune.apply(self.work, "ks_x", "ax01", install=False, catalogue=self.cat, game=self.game)
        self.assertEqual((self.snapshot(b), self.tree(b)), (shot_a, tree_a))

    def test_two_tunes_with_the_same_choice_build_the_same_tyre_files(self):
        self.tyres()
        self.make_tune("ax01")
        self.make_tune("ax02", {"name_suffix": "_B"})
        for t in ("ax01", "ax02"):
            self.choose(sets(("own:soft", g(B)), (g(S), g(S))), t)
        a = tune.apply(self.work, "ks_x", "ax01", install=False, catalogue=self.cat, game=self.game)
        b = tune.apply(self.work, "ks_x", "ax02", install=False, catalogue=self.cat, game=self.game)
        pick = lambda res, rel: json.dumps(self.built(res, rel), sort_keys=True).replace(res["new_id"], "ID")
        for rel in ("data/tyres/own_soft.tyre", "presets/p.compatibletyres", "presets/q.compatibletyres", "data/setup.carsetup", "data/limits.carsetuplimits"):
            self.assertEqual(pick(a, rel), pick(b, rel), rel)

    def test_a_different_order_gives_different_files(self):
        self.choose(sets((g(S), g(S)), (g(A), g(B))))
        a = self.snapshot(self.apply())
        self.choose(sets((g(A), g(B)), (g(S), g(S))))
        self.assertNotEqual(self.snapshot(self.apply()), a)


class TestApplyVersions(Apply):
    """The plans and the builds of the base and of two versions of one tune that have different choices (the merge of a version into the package is the job of the version build tests)."""

    def setUp(self):
        super().setUp()
        self.tyres()
        self.make_tune()
        self.v1 = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        self.v2 = tune.add_version(self.work, "ks_x", "Light", "ax01")

    def plan(self, version=None):
        return tune.apply_plan(self.work, "ks_x", "ax01", False, None, self.cat, version, self.game)

    def build_of(self, version=None):
        out = os.path.join(self.work, "ks_x", "build", "ax01" + ("_" + version if version else ""))
        part = tune.build_state(self.work, "ks_x", "ax01", out, self.plan(version), self.cat, self.game)[0]
        return {"build_dir": part, "new_id": "ax01"}

    def test_each_state_has_its_own_plan(self):
        self.choose(sets((g(S), g(S))), "ax01")
        self.choose(sets(("own:soft", g(B))), "ax01", self.v1)
        plans = [self.plan(), self.plan(self.v1), self.plan(self.v2)]
        self.assertEqual([p["garage"]["start_front"] if p["garage"] else None for p in plans], [g(S), "own:soft", None])
        self.assertEqual([[f[0] for f in p["garage"]["files"]] if p["garage"] else None for p in plans], [[], ["data/tyres/own_soft.tyre"], None])

    def test_two_versions_with_different_choices_build_different_files_and_the_base_its_own(self):
        self.choose(sets((g(S), g(S)), (g(A), g(B))), "ax01")
        self.choose(sets(("own:soft", g(B))), "ax01", self.v1)
        self.choose(split([g(W), g(S)], [g(W)], start_front=g(S)), "ax01", self.v2)
        base, one, two = self.build_of(), self.build_of(self.v1), self.build_of(self.v2)
        for res, files in ((base, 2), (one, 1), (two, 2)):
            self.assertEqual(len(self.compounds(res, "p")), files)
        self.assertEqual([self.aligned(r)[0] for r in (base, one, two)], [0.0, 0.0, 1.0])
        self.assertEqual([self.limited(r)[0][0] for r in (base, one, two)], [1.0, 0.0, 1.0])
        self.assertEqual([t for t in self.tree(one) if "own_" in t], ["data/tyres/own_soft.tyre"])
        self.assertEqual([t for t in self.tree(base) + self.tree(two) if "own_" in t], [])

    def test_two_versions_with_the_same_choice_build_the_same_files(self):
        for v in (self.v1, self.v2):
            self.choose(sets(("own:soft", g(B)), (g(S), g(S))), "ax01", v)
        one, two = self.build_of(self.v1), self.build_of(self.v2)
        for rel in ("data/tyres/own_soft.tyre", "presets/p.compatibletyres", "presets/q.compatibletyres", "data/setup.carsetup", "data/limits.carsetuplimits"):
            self.assertEqual(json.dumps(self.built(one, rel), sort_keys=True), json.dumps(self.built(two, rel), sort_keys=True), rel)

    def test_a_version_with_a_choice_and_saved_tyre_values_is_a_conflict_of_that_version_only(self):
        self.choose(sets((g(S), g(S))), "ax01", self.v1)
        tune.save_version_state(self.work, "ks_x", dict(tune.read_version_state(self.work, "ks_x", self.v1, "ax01"), tyre_dy_front=1.4), self.v1, "ax01")
        self.assertIsNone(self.plan()["garage"])
        with self.assertRaisesRegex(ValueError, "^%s$" % CONFLICT):
            self.plan(self.v1)

    def test_apply_refuses_before_anything_is_built_when_a_version_cannot_be_built(self):
        tune.save_version_state(self.work, "ks_x", {tune.TYRE_KEY: ["own:soft"]}, self.v2, "ax01")
        with self.assertRaisesRegex(ValueError, "^%s$" % OLD_FORM):
            self.apply(tune_id="ax01")
        self.assertEqual(self.calls, [])


class TestApplyErrors(Apply):
    def refused(self, text, state=None):
        if state is not None:
            tune.save_state(self.work, "ks_x", state)
        before = self.snapshot_of_work()
        with self.assertRaisesRegex(ValueError, text):
            self.apply()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.snapshot_of_work(), before)
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))

    def snapshot_of_work(self):
        return sorted(os.path.relpath(os.path.join(dp, n), self.work) for dp, _, names in os.walk(self.work) for n in names)

    def test_a_choice_and_saved_tyre_values_are_refused_before_anything_is_written(self):
        for state in ({"tyre_dy_front": 1.4}, {"tyre_dy_rear": 1.0}, {"tyre_th_front": "road"}, {"tyre_deep_front": 1.0}, {"tyre_dy_front": 1.2}):
            with self.subTest(state):
                self.refused("^%s$" % CONFLICT, dict(state, **{tune.TYRE_KEY: sets((g(S), g(S)))}))

    def test_the_conflict_is_reported_even_when_the_tyre_files_of_the_car_are_missing(self):
        shutil_tree = os.path.join(self.x.shared, "tyres")
        for dp, _, names in os.walk(shutil_tree):
            for n in names:
                os.remove(os.path.join(dp, n))
        self.refused("^%s$" % CONFLICT, {"tyre_dy_front": 1.4, tune.TYRE_KEY: sets((g(S), g(S)))})

    def test_other_saved_values_are_no_conflict(self):
        res = self.apply({"name_suffix": "_Z", tune.TYRE_KEY: sets((g(S), g(S)))})
        self.assertEqual([a["id"] for a in res["applied"]], ["name_suffix"])

    def test_a_damaged_or_old_choice_is_refused(self):
        self.refused("^%s$" % DAMAGED, {tune.TYRE_KEY: {"sets": []}})
        self.refused("^%s$" % DAMAGED, {tune.TYRE_KEY: []})
        self.refused("^%s$" % OLD_FORM, {tune.TYRE_KEY: ["own:soft", "stock:%s|%s" % (S, S)]})

    def test_a_tyre_that_is_gone_is_refused(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        os.remove(tune.tyre_path(self.work, "soft"))
        self.refused("^tyres: no tyre 'soft' in the library$")

    def test_an_own_tyre_of_the_old_form_is_refused(self):
        self.write(os.path.join(self.work, "tyres", "old.json"), {"version": 1, "name": "Old", "source": {"front": A, "rear": B}, "values": {}})
        self.refused("^tyres: .*old front/rear form", {tune.TYRE_KEY: sets(("own:old", g(B)))})

    def test_a_source_file_that_cannot_be_read_is_refused(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        os.remove(os.path.join(self.x.shared, "tyres", "road", "a.tyre"))
        self.refused("^tyres: tyre soft: the source %s cannot be read: " % A.replace("\\", "\\\\"))

    def test_a_value_the_source_cannot_take_is_refused(self):
        self.tyres()
        self.write(tune.tyre_path(self.work, "soft"), {"version": 2, "name": "Soft", "short": "SO", "source": A, "values": {"tyre_deep": 1.0}})
        self.refused("^tyres: tyre soft: tyre_deep cannot be written into the source file: ", {tune.TYRE_KEY: sets(("own:soft", g(B)))})
        self.write(tune.tyre_path(self.work, "soft"), {"version": 2, "name": "Soft", "short": "SO", "source": A, "values": {"tyre_dy": "fast"}})
        self.refused("^tyres: tyre soft: tyre_dy expects a number", {tune.TYRE_KEY: sets(("own:soft", g(B)))})

    def test_a_game_tyre_that_is_not_there_is_refused(self):
        self.refused("^tyres: unknown tyre content.cars.common_phsx.tyres.road.gone.tyre, tyre-index lists the tyres$",
                     {tune.TYRE_KEY: sets((g(GS + "tyres\\road\\gone.tyre"), g(B)))})

    def test_a_car_without_setup_files_for_the_start_tyre_is_refused(self):
        self.choose(sets((g(S), g(S))))
        car = dict(self.car)
        del car["stock_setup"]
        self.x.add("data/x.car", car)
        self.refused("^cannot set the start tyre: ")
        self.x.add("data/x.car", self.car)
        os.remove(os.path.join(self.x.car_root, "data", "limits.carsetuplimits"))
        self.refused("^cannot set the start tyre: ")

    def test_files_without_the_alignments_of_four_wheels_are_refused(self):
        self.choose(sets((g(S), g(S))))
        for rel, obj in (("data/setup.carsetup", {"alignments": [{}] * 3}), ("data/setup.carsetup", {"other": 1}), ("data/setup.carsetup", {"alignments": [1, 2, 3, 4]}),
                         ("data/limits.carsetuplimits", {"alignments": []}), ("data/limits.carsetuplimits", {"alignments": [{"compound": 5}] * 4})):
            with self.subTest(rel, obj=obj):
                self.x.add("data/setup.carsetup", self.setup)
                self.x.add("data/limits.carsetuplimits", self.limits)
                self.x.add(rel, obj)
                self.refused("^cannot set the start tyre: ")

    def test_a_file_that_cannot_be_decoded_is_refused_as_a_start_tyre_error(self):
        self.choose(sets((g(S), g(S))))
        self.x.store[self.x.key(os.path.join(self.x.car_root, "data", "setup.carsetup"))] = ValueError("broken setup")
        self.refused("^cannot set the start tyre: broken setup$")

    def test_a_refused_apply_keeps_the_previous_build(self):
        first = self.apply({"name_suffix": "_Z"})
        before = self.snapshot(first)
        tune.save_state(self.work, "ks_x", {"name_suffix": "_Z", tune.TYRE_KEY: sets(("own:ghost", g(B)))})
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.snapshot(first), before)
        self.assertTrue(os.path.isdir(first["build_dir"]))

    def test_the_check_does_not_write_into_a_stale_partial_folder(self):
        stale = os.path.join(self.work, "ks_x", "build", "ax_x.partial", "stale.bin")
        self.write(stale, "x")
        with self.assertRaises(ValueError):
            self.apply({tune.TYRE_KEY: sets(("own:nope", g(B)))})
        self.assertTrue(os.path.isfile(stale))


class TestApplyResult(Apply):
    def test_the_note_names_the_tyres_and_the_start(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), (g(S), g(S)), (g(SC), g(RS)), start_front=g(S), start_rear=g(S)))
        res = self.apply()
        self.assertEqual(res["notes"], ["note: from build", "note: tyres: front Soft, Racing slick s, Supercar 235/35 R19; rear Road b, Racing slick s, Road 265/30 R19; "
                                        "starts on Racing slick s / Racing slick s", CAR_NOTE])

    def test_the_tyre_choice_is_no_applied_setting_and_the_other_settings_still_are(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        res = self.apply(dict(self.state(), name_suffix="_Z"))
        self.assertEqual([a["id"] for a in res["applied"]], ["name_suffix"])

    def test_the_state_is_not_changed_by_apply(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), (g(S), g(S))))
        before = self.state()
        self.apply()
        self.assertEqual(self.state(), before)

    def test_the_choice_is_a_change_of_the_build_and_a_later_build_reports_what_differs(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B)), (g(S), g(S))))
        first = self.apply()
        text = "front Soft, Racing slick s; rear Road b, Racing slick s; starts on Soft / Road b"
        self.assertEqual(first["changes"]["extras"], [{"kind": "garage", "from": None, "to": text, "text": "Tyres: " + text}])
        with open(tune.snapshot_path(self.work, "ks_x", "ax_x"), encoding="utf-8") as f:
            record = json.load(f)["garage"]
        self.assertEqual(record, {"fronts": ["own:soft", g(S)], "rears": [g(B), g(S)], "start_front": "own:soft", "start_rear": g(B),
                                  "labels": {"own:soft": "Soft", g(B): "Road b", g(S): "Racing slick s"}})
        self.assertEqual(self.apply()["changes"]["extras"], [])
        self.choose(sets(("own:soft", g(B)), (g(S), g(S)), start_front=g(S), start_rear=g(S)))
        second = self.apply()
        self.assertEqual([e["text"] for e in second["changes"]["extras"]],
                         ["Tyres: front Soft, Racing slick s; rear Road b, Racing slick s; starts on Racing slick s / Racing slick s"])
        tune.reset_tyres(self.work, "ks_x")
        last = self.apply()
        self.assertEqual(last["changes"]["extras"][0]["to"], None)
        self.assertEqual(last["changes"]["extras"][0]["text"], "Tyres: the car's own tyres again (were front Soft, Racing slick s; rear Road b, Racing slick s; "
                                                               "starts on Racing slick s / Racing slick s)")
        self.assertIsNone(tune.load_snapshot(self.work, "ks_x", "ax_x")["garage"])

    def test_a_renamed_own_tyre_is_a_change_of_the_record(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        self.apply()
        tune.rename_tyre(self.work, "soft", "Softer")
        self.assertEqual(self.apply()["changes"]["extras"][0]["text"], "Tyres: front Softer; rear Road b; starts on Softer / Road b")

    def test_a_record_of_the_old_form_counts_as_no_previous_build(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        first = self.apply()
        path = tune.snapshot_path(self.work, "ks_x", "ax_x")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["garage"] = {"keys": ["own:soft", "stock:a|b"], "start": "own:soft"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertIsNone(tune.load_snapshot(self.work, "ks_x", "ax_x"))
        again = self.apply()
        self.assertEqual((again["changes"]["since"], len(again["changes"]["extras"])), (None, 1))
        self.assertEqual(first["changes"]["extras"], again["changes"]["extras"])

    def test_the_lines_of_the_changes_include_the_tyre_text(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        lines = tune.change_lines(self.apply())
        self.assertIn("  Tyres: front Soft; rear Road b; starts on Soft / Road b", lines)
        self.assertIn("note: tyres: front Soft; rear Road b; starts on Soft / Road b", lines)

    def test_apply_prints_nothing_and_the_command_prints_the_notes(self):
        self.tyres()
        self.choose(sets(("own:soft", g(B))))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.apply()
        self.assertEqual(out.getvalue(), "")
        code, out, err = self.run_main("apply", "--no-install", "--game", self.game)
        self.assertEqual(code, 2)

    def test_a_modded_car_builds_its_own_choice(self):
        self.tyres()
        tune.save_state(self.work, "ks_x", {"name_suffix": "_A"})
        tune.save_state(self.work, "ks_x", {"name_suffix": "_B"}, "ax01")
        self.choose(sets((g(S), g(S))), "ax01")
        res = tune.apply(self.work, "ks_x", "ax01", install=False, catalogue=self.cat, game=self.game)
        self.assertEqual(self.names(res, "p"), ([SLICK], [SLICK]))
        default = tune.apply(self.work, "ks_x", install=False, catalogue=self.cat, game=self.game)
        self.assertEqual(self.names(default, "p"), ([ROAD, SLICK, WET, OLD], [ROAD, SLICK, WET, OLD]))


class TestCommands(World):
    def setUp(self):
        super().setUp()
        self.file = str(self.d / "choice.json")

    def write_choice(self, choice):
        self.write(self.file, choice)
        return self.file

    def test_garage_shows_the_default_with_the_sets_and_the_start_tyres(self):
        code, out, err = self.run_main("garage")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "tyres of ks_x: default (the car's own tyres, the car is not touched)")
        self.assertIn("set: Road A / Road b", lines)
        self.assertIn("set: Supercar 235/35 R19 / Road 265/30 R19", lines)
        front = [[c.strip() for c in line.split(" | ")] for line in lines if "|" in line]
        self.assertEqual(front[0], ["front", "start", "key"])
        self.assertEqual(front[1], ["Road A", "start", g(A_UP)])
        self.assertIn(["rear", "start", "key"], front)
        self.assertIn(["Road b", "start", g(B)], front)

    def test_garage_set_stores_the_choice_from_a_file_and_garage_shows_it(self):
        self.tyres()
        file = self.write_choice(split([g(S), "own:soft"], [g(B)], start_front="own:soft"))
        code, out, err = self.run_main("garage-set", file, "--game", self.game)
        self.assertEqual((code, out, err), (0, "tyres: 2 front, 1 rear, starting on own:soft / %s\n" % g(B), ""))
        self.assertEqual(self.state()[tune.TYRE_KEY], split([g(S), "own:soft"], [g(B)], start_front="own:soft", start_rear=g(B)))
        code, out, err = self.run_main("garage")
        lines = out.splitlines()
        self.assertEqual(lines[0], "tyres of ks_x: saved choice, front and rear apart")
        self.assertNotIn("set: ", out)
        self.assertIn(["Soft", "start", "own:soft"], [[c.strip() for c in line.split(" | ")] for line in lines if "|" in line])

    def test_garage_set_with_sets_prints_them_and_the_default_choice_removes_the_key(self):
        self.run_main("garage-set", self.write_choice(sets((g(S), g(S)))), "--game", self.game)
        self.assertEqual(self.run_main("garage")[1].splitlines()[0], "tyres of ks_x: saved choice, 1 set(s)")
        code, out, err = self.run_main("garage-set", self.write_choice(STOCK), "--game", self.game)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "tyres: 4 front, 4 rear, starting on %s / %s (the car's own tyres, nothing is stored)\n" % (g(A), g(B)))
        self.assertEqual(self.state(), {})

    def test_garage_reset_prints_what_happened(self):
        self.run_main("garage-set", self.write_choice(sets((g(S), g(S)))), "--game", self.game)
        self.assertEqual(self.run_main("garage-reset"), (0, "tyre choice removed from the state\n", ""))
        self.assertEqual(self.run_main("garage-reset"), (0, "tyre choice was not set\n", ""))
        self.assertEqual(self.state(), {})

    def test_the_commands_work_on_the_draft_and_on_a_modded_car(self):
        self.make_tune()
        self.assertEqual(self.run_main("garage-set", self.write_choice(sets((g(S), g(S)))), "--draft", "--game", self.game)[0], 0)
        self.assertEqual(self.run_main("garage-set", self.write_choice(sets((g(W), g(W)))), "--tune", "ax01", "--game", self.game)[0], 0)
        self.assertEqual([self.state(t).get(tune.TYRE_KEY, {}).get("start_front") for t in (None, "ax01", tune.DRAFT)], [None, g(W), g(S)])
        self.assertIn("Racing slick s | start", self.run_main("garage", "--draft")[1])
        self.assertIn("Racing wet w | start", self.run_main("garage", "--tune", "ax01")[1])
        self.assertEqual(self.run_main("garage-reset", "--draft")[1], "tyre choice removed from the state\n")
        self.assertEqual(self.run_main("garage-reset", "--tune", "ax01")[1], "tyre choice removed from the state\n")
        self.assertEqual(self.state("ax01"), {"name_suffix": "_A"})

    def test_a_car_can_be_chosen(self):
        code, out, err = self.run_main("garage", "--car", "ks_x")
        self.assertEqual((code, err), (0, ""))
        code, out, err = self.run_main("garage", "--car", "ks_nope")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: unknown car 'ks_nope'"), err)

    def test_a_car_without_tyres_says_so(self):
        for n in ("p", "q"):
            os.remove(os.path.join(self.x.car_root, "presets", n + ".compatibletyres"))
        code, out, err = self.run_main("garage")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("note: no tyres to show", out)

    def test_a_saved_old_choice_is_shown_as_sets(self):
        tune.save_state(self.work, "ks_x", {tune.TYRE_KEY: ["stock:%s|%s" % (S, S)]})
        out = self.run_main("garage")[1]
        self.assertIn("saved choice, 1 set(s)", out)
        self.assertIn("set: Racing slick s / Racing slick s", out)

    def test_runtime_errors_are_error_lines_with_exit_1(self):
        self.tyres()
        bad = self.write_choice(sets((g(S), "own:nope")))
        for argv, message in ((("garage-set", bad, "--game", self.game), "error: no tyre 'nope' in the library\n"),
                              (("garage-set", str(self.d / "nofile.json"), "--game", self.game), "error: "),
                              (("garage-set", bad, "--tune", "ax99", "--game", self.game), "error: ks_x has no tune ax99"),
                              (("garage", "--tune", "ax99"), "error: ks_x has no tune ax99"), (("garage-reset", "--tune", "ax99"), "error: ks_x has no tune ax99")):
            with self.subTest(argv):
                code, out, err = self.run_main(*argv)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith(message), err)
        self.write(self.file, "not json")
        code, out, err = self.run_main("garage-set", self.file, "--game", self.game)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: ") and self.file in err, err)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_a_choice_with_a_bad_key_or_form_is_an_error_line(self):
        for choice, message in ((sets(("junk", g(S))), "error: bad tyre key 'junk'"), ([1], "error: the tyre choice must be an object"),
                                (sets((g(A), g(B)), start_front=g(S)), "error: start_front"), (split([g(S), g(S)], [g(B)]), "error: fronts lists a tyre twice")):
            with self.subTest(str(choice)[:50]):
                code, out, err = self.run_main("garage-set", self.write_choice(choice), "--game", self.game)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith(message), err)

    def test_the_usage_block_lists_the_garage_commands(self):
        for cmd in ("garage", "garage-set", "garage-reset"):
            line = [l for l in USAGE.splitlines() if l.strip().startswith("python tools/tune.py " + cmd + " ")]
            self.assertEqual(len(line), 1, cmd)
            for option in ("--tune ID | --draft", "[--car ID]", "[--work <dir>]"):
                self.assertIn(option, line[0])
        self.assertIn("garage-set   <file>", USAGE)
        self.assertIn("[--game <content.kspkg>]", [l for l in USAGE.splitlines() if "garage-set" in l][0])

    def test_a_wrong_command_line_prints_the_usage_on_stdout_and_exits_2(self):
        for argv in (("garage", "x"), ("garage-set",), ("garage-set", "--draft"), ("garage-set", "a", "b"), ("garage-reset", "x"),
                     ("garage", "--tune", "ax01", "--draft"), ("garage-set", "x.json", "--tune", "ax01", "--draft"),
                     ("garage-reset", "--tune", "ax01", "--draft"), ("garage", "--bogus", "1"), ("garage", "--game", "x")):
            with self.subTest(argv):
                code, out, err = self.run_main(*argv)
                self.assertEqual((code, out.strip(), err), (2, USAGE.strip(), ""))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tune_state.json")))


class Converting(Apply):
    """ks_x with the old Tyres values saved in its default tune, its draft or in the tune ax01 and its versions."""

    def setUp(self):
        super().setUp()
        self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_x", "display_name": "Car X", "brand": "Brand", "year": 1999,
                                                              "property_1": "P1", "property_2": "P2", "property_3": "P3", "variant_name": "Base"})
        next(s for s in self.cat["settings"] if s["id"] == "tyre_dy_rear")["targets"].append({"file": "@tyre_rear", "path": "modelData.Dy1"})

    def save_old(self, tune_id=None, version=None, **more):
        state = dict(OLD_VALUES, name_suffix="_Z", **more)
        if version is None:
            tune.save_state(self.work, "ks_x", state, tune_id)
        else:
            tune.save_version_state(self.work, "ks_x", state, version, tune_id)

    def two_versions(self):
        self.make_tune("ax01", dict(OLD_VALUES, name_suffix="_A"))
        return [tune.add_version(self.work, "ks_x", n, "ax01") for n in ("Heavy", "Light")]

    def convert(self, name="Mine", tune_id=None, version=None):
        return tune.convert_tyres(self.work, "ks_x", name, tune_id, version, game=self.game)

    def library(self):
        out = {}
        for entry in tune.list_tyres(self.work):
            if "error" not in entry:
                t = tune.load_tyre(self.work, entry["id"])
                out[entry["id"]] = (t["name"], t["short"], t["source"], t["values"])
        return out

    def files_of_work(self):
        out = {}
        for dp, _, names in os.walk(self.work):
            for n in names:
                with open(os.path.join(dp, n), "rb") as f:
                    out[os.path.join(dp, n)] = f.read()
        return out

    def unchanged(self, call, text):
        """call raises ValueError(text) and every file of the work folder is as it was."""
        before = self.files_of_work()
        with self.assertRaisesRegex(ValueError, text):
            call()
        self.assertEqual(self.files_of_work(), before)


class TestConvertTyres(Converting):
    def test_the_base_with_both_axles_makes_two_own_tyres_and_the_choice_and_drops_the_values(self):
        self.save_old(limiter=7500)
        res = self.convert()
        self.assertEqual(res, {"front": {"key": "own:mine_front", "name": "Mine front", "created": True},
                               "rear": {"key": "own:mine_rear", "name": "Mine rear", "created": True}, "sets": 5})
        self.assertEqual(self.state(), {"name_suffix": "_Z", "limiter": 7500, tune.TYRE_KEY: converted("own:mine_front", "own:mine_rear")})
        self.assertEqual(self.library(), {"mine_front": ("Mine front", "MF", A, {"tyre_dy": 1.4, "tyre_th": "slick"}),
                                          "mine_rear": ("Mine rear", "MR", B, {"tyre_dy": 1.15})})

    def test_the_draft_and_the_default_tune_apart(self):
        self.save_old(tune.DRAFT)
        self.save_old(None, limiter=1)
        self.convert(tune_id=tune.DRAFT)
        self.assertEqual(self.state(tune.DRAFT), {"name_suffix": "_Z", tune.TYRE_KEY: converted("own:mine_front", "own:mine_rear")})
        self.assertEqual(self.state(), dict(OLD_VALUES, name_suffix="_Z", limiter=1))

    def test_a_modded_car_other_than_the_default_tune(self):
        self.two_versions()
        self.convert(tune_id="ax01")
        self.assertEqual(self.state("ax01"), {"name_suffix": "_A", tune.TYRE_KEY: converted("own:mine_front", "own:mine_rear")})

    def test_a_version_changes_only_its_own_state(self):
        v1, v2 = self.two_versions()
        self.save_old("ax01", v1)
        self.save_old("ax01", v2, limiter=9000)
        res = self.convert(tune_id="ax01", version=v1)
        self.assertEqual(res["sets"], 5)
        self.assertEqual(tune.read_version_state(self.work, "ks_x", v1, "ax01"), {"name_suffix": "_Z", tune.TYRE_KEY: converted("own:mine_front", "own:mine_rear")})
        self.assertEqual(tune.read_version_state(self.work, "ks_x", v2, "ax01"), dict(OLD_VALUES, name_suffix="_Z", limiter=9000))
        self.assertEqual(self.state("ax01"), dict(OLD_VALUES, name_suffix="_A"))

    def test_a_version_of_the_default_tune(self):
        self.save_old()
        vid = tune.add_version(self.work, "ks_x", "Own")
        tune.save_version_state(self.work, "ks_x", {"tyre_dy_rear": 1.2}, vid)
        res = self.convert(version=vid)
        self.assertEqual((res["front"]["key"], res["rear"]["key"]), (g(A), "own:mine_rear"))
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid), {tune.TYRE_KEY: converted(g(A), "own:mine_rear")})
        self.assertEqual(self.state(), dict(OLD_VALUES, name_suffix="_Z"))

    def test_only_the_front_values_keep_the_original_rear_tyre(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        res = self.convert("Drift")
        self.assertEqual(res, {"front": {"key": "own:drift_front", "name": "Drift front", "created": True},
                               "rear": {"key": g(B), "name": "Road b", "created": False}, "sets": 5})
        self.assertEqual(self.state(), {tune.TYRE_KEY: converted("own:drift_front", g(B))})
        self.assertEqual(self.library(), {"drift_front": ("Drift front", "DF", A, {"tyre_dy": 1.4})})

    def test_only_the_rear_values_keep_the_original_front_tyre_written_as_the_game_has_it(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_rear": 1.15})
        res = self.convert()
        self.assertEqual(res["front"], {"key": g(A), "name": "Road a", "created": False})
        self.assertEqual(self.state(), {tune.TYRE_KEY: converted(g(A), "own:mine_rear")})
        self.assertEqual(list(self.library()), ["mine_rear"])

    def test_the_source_is_the_file_the_car_file_names_first(self):
        self.car["frontTyreCompounds"] = [S, A_UP]
        self.car["rearTyreCompounds"] = [RS]
        self.save_old()
        self.convert()
        self.assertEqual([v[2] for v in self.library().values()], [S, RS])

    def test_an_axle_with_the_same_source_and_values_reuses_the_tyre_made_a_moment_before(self):
        self.car["rearTyreCompounds"] = [A_UP, S, W]
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4, "tyre_dy_rear": 1.4})
        res = self.convert()
        self.assertEqual((res["front"], res["rear"]), ({"key": "own:mine_front", "name": "Mine front", "created": True},
                                                      {"key": "own:mine_front", "name": "Mine front", "created": False}))
        self.assertEqual(list(self.library()), ["mine_front"])
        self.assertEqual(self.state(), {tune.TYRE_KEY: converted("own:mine_front", "own:mine_front")})

    def test_a_later_conversion_reuses_the_tyres_of_an_earlier_one_whatever_their_names(self):
        v1, v2 = self.two_versions()
        self.save_old("ax01", v1)
        self.save_old("ax01", v2)
        first = self.convert("Mine", "ax01", v1)
        second = self.convert("Other", "ax01", v2)
        self.assertEqual(second["front"], {"key": "own:mine_front", "name": "Mine front", "created": False})
        self.assertEqual(second["rear"], {"key": "own:mine_rear", "name": "Mine rear", "created": False})
        self.assertEqual((first["front"]["created"], first["rear"]["created"]), (True, True))
        self.assertEqual(list(self.library()), ["mine_front", "mine_rear"])
        self.assertEqual(tune.read_version_state(self.work, "ks_x", v2, "ax01"), tune.read_version_state(self.work, "ks_x", v1, "ax01"))

    def test_a_library_tyre_made_by_hand_with_the_same_source_and_values_is_used_and_others_are_not(self):
        for name, source, values in (("Near", A, {"tyre_dy": 1.5, "tyre_th": "slick"}), ("Far", S, {"tyre_dy": 1.4, "tyre_th": "slick"}),
                                     ("More", A, {"tyre_dy": 1.4, "tyre_th": "slick", "tyre_deep": 1.0}), ("Hit", A_UP, {"tyre_dy": 1.4, "tyre_th": "slick"})):
            tyre_id = tune.create_tyre(self.work, name, source, game=self.game)["id"]
            for field, value in values.items():
                tune.set_tyre_value(self.work, tyre_id, field, value, self.cat)
        self.write(os.path.join(tune.tyres_dir(self.work), "bad.json"), {"version": 1})
        self.save_old()
        res = self.convert()
        self.assertEqual(res["front"], {"key": "own:hit", "name": "Hit", "created": False})
        self.assertEqual(res["rear"], {"key": "own:mine_rear", "name": "Mine rear", "created": True})
        self.assertEqual(sorted(self.library()), ["far", "hit", "mine_rear", "more", "near"])

    def test_the_same_values_on_another_source_make_a_new_tyre(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        self.convert()
        self.car["frontTyreCompounds"] = [S]
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        res = self.convert()
        self.assertEqual(res["front"], {"key": "own:mine_front_2", "name": "Mine front 2", "created": True})
        self.assertEqual({k: v[2] for k, v in self.library().items()}, {"mine_front": A, "mine_front_2": S})

    def test_a_taken_name_gets_a_number_ignoring_case_and_the_id_follows(self):
        for name in ("MINE FRONT", "mine front 2", "Mine rear"):
            tune.create_tyre(self.work, name, S, game=self.game)
        self.save_old()
        res = self.convert("  Mine ")
        self.assertEqual((res["front"]["name"], res["rear"]["name"]), ("Mine front 3", "Mine rear 2"))
        self.assertEqual((res["front"]["key"], res["rear"]["key"]), ("own:mine_front_3", "own:mine_rear_2"))
        self.assertEqual(self.state()[tune.TYRE_KEY]["start_front"], "own:mine_front_3")

    def test_the_values_are_stored_as_the_fields_coerce_them(self):
        tune.save_state(self.work, "ks_x", {"tyre_th_front": "road", "tyre_dy_front": 2})
        self.convert()
        self.assertEqual(json.dumps(self.library()["mine_front"][3], sort_keys=True), '{"tyre_dy": 2.0, "tyre_th": "road"}')

    def test_every_other_entry_of_the_state_stays(self):
        self.save_old(old_unknown=3)
        self.convert()
        self.assertEqual(self.state()["old_unknown"], 3)


class TestConvertTyresRefusals(Converting):
    def test_a_state_with_a_tyre_choice_is_refused_whatever_else_it_holds(self):
        self.save_old()
        self.choose(sets((g(S), g(S))))
        self.unchanged(self.convert, "^%s$" % CHOICE_FIRST)
        self.unchanged(lambda: self.convert(tune_id=tune.DRAFT), "^%s$" % NO_VALUES)

    def test_a_state_without_saved_tyre_values_has_nothing_to_convert_with_or_without_a_choice(self):
        tune.save_state(self.work, "ks_x", {"name_suffix": "_Z", "limiter": 5})
        self.unchanged(self.convert, "^%s$" % NO_VALUES)
        self.choose(sets((g(S), g(S))))
        self.unchanged(self.convert, "^%s$" % NO_VALUES)
        tune.save_state(self.work, "ks_x", {})
        self.unchanged(self.convert, "^%s$" % NO_VALUES)
        self.assertFalse(os.path.exists(tune.tyres_dir(self.work)))

    def test_a_locked_version_is_refused_by_the_guard_of_the_versions(self):
        v1, _ = self.two_versions()
        self.save_old("ax01", v1)
        tune.save_json(tune.version_meta_path(self.work, "ks_x", v1, "ax01"), {"name": "Heavy", "locked": True})
        self.unchanged(lambda: self.convert(tune_id="ax01", version=v1), r"^version v01 \(Heavy\) is locked; unlock it to change it$")
        self.assertEqual(self.library(), {})

    def test_an_unknown_version_and_a_version_of_the_draft_are_errors(self):
        self.two_versions()
        self.unchanged(lambda: self.convert(tune_id="ax01", version="v09"), "^ks_x has no version v09 of ax01$")
        self.unchanged(lambda: self.convert(tune_id=tune.DRAFT, version="v01"), "^the draft has no versions$")

    def test_a_source_file_that_cannot_be_read_stops_before_any_tyre_is_made(self):
        self.save_old()
        self.x.store[self.x.key(os.path.join(self.x.shared, "tyres", "road", "b.tyre"))] = ValueError("damaged")
        self.unchanged(self.convert, r"^tyre Mine rear: the source content\\cars\\common_phsx\\tyres\\road\\b\.tyre cannot be read: damaged$")
        self.assertEqual(self.library(), {})

    def test_a_source_that_is_no_tyre_of_the_game_is_refused(self):
        self.car["frontTyreCompounds"] = [self.x.game_path("data/tyres/odd.tyre")]
        self.save_old()
        self.unchanged(self.convert, "^" + re.escape("unknown tyre %r, tyre-index lists the tyres" % self.x.game_path("data/tyres/odd.tyre")) + "$")
        self.assertEqual(self.library(), {})

    def test_a_car_without_a_tyre_in_its_car_file_is_refused(self):
        del self.car["frontTyreCompounds"]
        self.save_old()
        self.unchanged(self.convert, "^no frontTyreCompounds in the car file$")

    def test_a_saved_value_that_does_not_fit_its_field_is_refused(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4, "tyre_th_front": "nope"})
        self.unchanged(self.convert, "^tyre_th must be one of: road, slick$")
        self.assertEqual(self.library(), {})

    def test_a_setting_of_the_old_section_without_a_field_in_the_tyre_creator_is_refused(self):
        self.cat["settings"].append(mini_setting("tyre_x_rear", group="Tyres", targets=[("@tyre_rear", "modelData.Dy1")]))
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4, "tyre_x_rear": 1.0})
        self.unchanged(self.convert, "^tyre_x_rear has no field in the Tyre Creator, it cannot be converted$")

    def test_the_name_must_be_a_tyre_name(self):
        self.save_old()
        for name in ("", "   ", None, 5, "x" * 40, "a\nb"):
            with self.subTest(repr(name)):
                self.unchanged(lambda: self.convert(name), "a tyre name needs 1 to 40 characters")
        self.assertEqual(self.library(), {})

    def test_a_state_that_cannot_be_written_removes_the_tyres_made_during_the_call(self):
        self.save_old()
        tune.create_tyre(self.work, "Old one", S, game=self.game)
        self.patch(tune, "save_tune_state", lambda *a, **k: (_ for _ in ()).throw(ValueError("disk full")))
        self.unchanged(self.convert, "^disk full$")
        self.assertEqual(list(self.library()), ["old_one"])

    def test_a_second_tyre_that_cannot_be_made_removes_the_first(self):
        self.save_old()
        real, calls = tune.create_tyre, []

        def create(*a, **k):
            calls.append(a[1])
            if len(calls) == 2:
                raise ValueError("no room")
            return real(*a, **k)
        self.patch(tune, "create_tyre", create)
        self.unchanged(self.convert, "^no room$")
        self.assertEqual((calls, self.library()), (["Mine front", "Mine rear"], {}))

    def test_a_failed_write_leaves_a_tyre_that_was_reused_alone(self):
        tune.create_tyre(self.work, "Hit", A, game=self.game)
        tune.set_tyre_value(self.work, "hit", "tyre_dy", 1.4, self.cat)
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        self.patch(tune, "save_tune_state", lambda *a, **k: (_ for _ in ()).throw(ValueError("disk full")))
        self.unchanged(self.convert, "^disk full$")
        self.assertEqual(list(self.library()), ["hit"])


class TestConvertedBuild(Converting):
    def files(self, res, *stems):
        return [self.built(res, "data/tyres/" + stem + ".tyre") for stem in stems]

    def test_the_build_after_the_conversion_has_the_files_of_the_old_build_except_their_names(self):
        before = self.apply(dict(OLD_VALUES, name_suffix="_Z"))
        old = self.files(before, "ax_x_front", "ax_x_rear")
        self.convert()
        after = self.apply()
        new = self.files(after, "own_mine_front", "own_mine_rear")
        for was, now in zip(old, new):
            self.assertEqual({k: v for k, v in now.items() if k not in ("name", "shortName")}, {k: v for k, v in was.items() if k not in ("name", "shortName")})
        self.assertEqual([(t["name"], t["shortName"]) for t in new], [("Mine front (MF)", "MF"), ("Mine rear (MR)", "MR")])
        self.assertEqual([tune.plain(t["modelData"]["Dy0"]) for t in new], [1.4, 1.15])
        self.assertEqual(new[0]["thermalData"]["thermalPerformanceCurve"], CURVES["slick"])
        self.assertEqual([t for t in self.tree(after) if "tyres/" in t], ["data/tyres/own_mine_front.tyre", "data/tyres/own_mine_rear.tyre"])

    def test_the_choice_gives_the_pair_first_the_stock_sets_after_it_and_starts_on_the_pair(self):
        self.save_old()
        self.convert()
        res = self.apply()
        compounds = self.compounds(res, "p")
        self.assertEqual([(c["front_tyre_data_path"], c["rear_tyre_data_paths"]) for c in compounds][0], (OWN_PATH % "mine_front", [OWN_PATH % "mine_rear"]))
        self.assertEqual(self.aligned(res), [0.0] * 4)
        self.assertEqual(self.built(res, "data/CarData.car")["frontTyreCompounds"], [A_UP, S, W])
        self.assertEqual(res["changes"]["extras"][0]["kind"], "garage")

    def test_the_converted_values_are_gone_from_the_state_and_the_note_with_them(self):
        tune.save_state(self.work, "ks_x", dict(OLD_VALUES, name_suffix="_Z"))
        self.assertEqual(self.apply()["notes"][-1], NOTE_OLD % 3)
        self.convert()
        notes = self.apply()["notes"]
        self.assertEqual([n for n in notes if "old Tyres section" in n], [])
        self.assertEqual(notes[:2], ["note: from build", "note: tyres: front Mine front, Road a, Racing slick s, Racing wet w, Supercar 235/35 R19; rear Mine rear, Road b, Racing slick s, Racing wet w, Road 265/30 R19; starts on Mine front / Mine rear"])

    def test_the_converted_choice_is_not_the_default_one(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        self.convert()
        self.assertFalse(tune.tyre_choices(self.work, "ks_x")["default"])


class TestOldValuesNoteOfApply(Converting):
    def test_a_state_with_old_values_and_no_choice_adds_the_note_once_and_builds_as_before(self):
        res = self.apply(dict(OLD_VALUES, name_suffix="_Z"))
        self.assertEqual(res["notes"][-1], NOTE_OLD % 3)
        self.assertEqual([n for n in res["notes"] if "old Tyres section" in n], [res["notes"][-1]])
        self.assertIn("tyre front: own file content\\cars\\ax_x\\data\\tyres\\ax_x_front.tyre replaces", res["notes"][-4])
        self.assertEqual(len(res["notes"]), 5)
        self.assertEqual(sorted(a["id"] for a in res["applied"]), ["name_suffix", "tyre_dy_front", "tyre_dy_rear", "tyre_th_front"])

    def test_the_count_is_the_number_of_saved_values(self):
        for state, count in (({"tyre_dy_front": 1.4}, 1), ({"tyre_dy_front": 1.4, "tyre_dy_rear": 1.15}, 2)):
            with self.subTest(count):
                self.assertEqual(self.apply(state)["notes"][-1], NOTE_OLD % count)

    def test_no_note_without_old_values(self):
        self.assertEqual(self.apply({"name_suffix": "_Z"})["notes"], ["note: from build", CAR_NOTE])
        self.choose(sets((g(S), g(S))))
        self.assertEqual([n for n in self.apply()["notes"] if "old Tyres" in n], [])

    def test_a_tune_other_than_the_default_gets_the_note_too(self):
        self.make_tune("ax01", {"tyre_dy_rear": 1.15})
        self.assertEqual(self.apply(tune_id="ax01")["notes"][-1], NOTE_OLD % 1)

    def test_the_note_of_a_version_names_the_version_and_a_state_with_a_choice_or_without_values_has_none(self):
        self.assertEqual(tune.old_tyre_notes({"tyre_dy_front": 1.4, "limiter": 1}, self.cat, "version v02 (Light): "),
                         ["note: version v02 (Light): this car still has saved tyre values of the old Tyres section (1): convert them with tyres-convert"])
        self.assertEqual(tune.old_tyre_notes({"tyre_dy_front": 1.4, tune.TYRE_KEY: STOCK}, self.cat), [])
        self.assertEqual(tune.old_tyre_notes({"limiter": 1}, self.cat), [])


class TestOldValuesAreNotSetAnyMore(World):
    TYRE_IDS = ("tyre_dy_front", "tyre_dy_rear", "tyre_th_front", "tyre_deep_front")

    def test_set_refuses_every_tyre_setting_of_the_car_and_writes_nothing(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        for setting_id in self.TYRE_IDS:
            for kw in ({}, {"tune": "ax01"}, {"tune": tune.DRAFT}, {"tune": "ax01", "version": vid}):
                with self.subTest(setting_id, **kw), self.assertRaisesRegex(ValueError, "^%s$" % REFUSED):
                    tune.set_value(self.work, "ks_x", setting_id, "1.2", self.cat, **kw)
        self.assertEqual(self.state("ax01"), {"name_suffix": "_A"})
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid, "ax01"), {})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", tune.DRAFT)))

    def test_a_saved_value_cannot_be_changed_either_and_stays_applied(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        with self.assertRaisesRegex(ValueError, "^%s$" % REFUSED):
            tune.set_value(self.work, "ks_x", "tyre_dy_front", "1.5", self.cat)
        self.assertEqual(self.state(), {"tyre_dy_front": 1.4})
        self.assertEqual([r["value"] for r in tune.effective_rows(self.work, "ks_x", self.cat, hidden=True) if r["id"] == "tyre_dy_front"], [1.4])

    def test_the_other_settings_still_take_values(self):
        self.assertEqual(tune.set_value(self.work, "ks_x", "name_suffix", "_Q", self.cat)["value"], "_Q")

    def test_a_value_that_does_not_fit_gets_the_same_refusal_and_an_unknown_id_its_own(self):
        with self.assertRaisesRegex(ValueError, "^%s$" % REFUSED):
            tune.set_value(self.work, "ks_x", "tyre_th_front", "nope", self.cat)
        with self.assertRaisesRegex(ValueError, "^unknown setting 'tyre_dy'$"):
            tune.set_value(self.work, "ks_x", "tyre_dy", "1", self.cat)

    def test_unset_removes_a_saved_old_value_and_is_not_refused_for_an_unsaved_one(self):
        self.make_tune("ax01", dict(OLD_VALUES, name_suffix="_A"))
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        tune.save_version_state(self.work, "ks_x", {"tyre_dy_rear": 1.2}, vid, "ax01")
        self.assertEqual(tune.unset_value(self.work, "ks_x", "tyre_dy_front", self.cat, tune="ax01"), {"id": "tyre_dy_front", "removed": True})
        self.assertEqual(tune.unset_value(self.work, "ks_x", "tyre_dy_front", self.cat, tune="ax01"), {"id": "tyre_dy_front", "removed": False})
        self.assertEqual(tune.unset_value(self.work, "ks_x", "tyre_dy_rear", self.cat, tune="ax01", version=vid), {"id": "tyre_dy_rear", "removed": True})
        self.assertEqual(self.state("ax01"), {"name_suffix": "_A", "tyre_th_front": "slick", "tyre_dy_rear": 1.15})
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid, "ax01"), {})

    def test_show_lists_the_old_rows_as_before_with_their_saved_value(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        code, out, err = self.run_main("show")
        self.assertEqual((code, err), (0, ""))
        row = [line for line in out.splitlines() if "tyre_dy_front" in line][0]
        self.assertEqual([c.strip() for c in row.split("|")][:3], ["*", "tyre_dy_front", "1.4"])
        self.assertIn("tyre_dy_rear", out)

    def test_the_command_line_refuses_set_and_allows_unset(self):
        code, out, err = self.run_main("set", "tyre_dy_front", "1.2")
        self.assertEqual((code, out, err), (1, "", "error: %s\n" % REFUSED))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4, "limiter": 7000})
        self.assertEqual(self.run_main("unset", "tyre_dy_front"), (0, "tyre_dy_front removed from the state\n", ""))
        self.assertEqual(self.run_main("unset", "tyre_dy_front"), (0, "tyre_dy_front was not set\n", ""))
        self.assertEqual(self.state(), {"limiter": 7000})


class TestTyresConvertCommand(Converting):
    def run_convert(self, *argv):
        return self.run_main("tyres-convert", *argv, "--game", self.game)

    def test_it_prints_what_was_made_the_sets_and_the_start_tyres(self):
        self.save_old()
        self.assertEqual(self.run_convert("--name", "Mine"), (0, "front: created tyre own:mine_front (Mine front)\n"
                                                              "rear: created tyre own:mine_rear (Mine rear)\n"
                                                              "tyres: 5 set(s), starting on Mine front / Mine rear\n", ""))
        self.assertEqual(self.state(), {"name_suffix": "_Z", tune.TYRE_KEY: converted("own:mine_front", "own:mine_rear")})

    def test_it_says_when_a_tyre_is_used_again_and_when_an_axle_stays_on_the_original_tyre(self):
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4})
        tune.save_state(self.work, "ks_x", {"tyre_dy_front": 1.4}, tune.DRAFT)
        self.run_convert("--name", "Mine")
        self.assertEqual(self.run_convert("--name", "Other", "--draft"),
                         (0, "front: used tyre own:mine_front (Mine front)\nrear: no saved values, stays on %s (Road b)\n"
                             "tyres: 5 set(s), starting on Mine front / Road b\n" % g(B), ""))

    def test_the_options_choose_the_tune_the_version_and_the_car(self):
        v1, _ = self.two_versions()
        self.save_old("ax01", v1)
        code, out, err = self.run_convert("--name", "Mine", "--tune", "ax01", "--version", v1, "--car", "ks_x")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("front: created tyre own:mine_front (Mine front)", out)
        self.assertEqual(tune.read_version_state(self.work, "ks_x", v1, "ax01"), {"name_suffix": "_Z", tune.TYRE_KEY: converted("own:mine_front", "own:mine_rear")})
        self.assertEqual(self.state("ax01"), dict(OLD_VALUES, name_suffix="_A"))

    def test_refusals_are_error_lines_on_stderr_with_exit_1_and_change_nothing(self):
        self.assertEqual(self.run_convert("--name", "Mine"), (1, "", "error: %s\n" % NO_VALUES))
        self.save_old()
        self.choose(sets((g(S), g(S))))
        before = self.files_of_work()
        self.assertEqual(self.run_convert("--name", "Mine"), (1, "", "error: %s\n" % CHOICE_FIRST))
        self.assertEqual(self.run_convert("--name", "Mine", "--version", "v01", "--draft"), (1, "", "error: the draft has no versions\n"))
        self.assertEqual(self.run_convert("--name", "Mine", "--tune", "ax09"), (1, "", "error: ks_x has no tune ax09\n"))
        self.assertEqual(self.files_of_work(), before)
        self.assertFalse(os.path.exists(tune.tyres_dir(self.work)))

    def test_a_wrong_command_line_prints_the_usage_on_stdout_and_exits_2(self):
        for argv in (("tyres-convert",), ("tyres-convert", "--draft"), ("tyres-convert", "x", "--name", "Mine"), ("tyres-convert", "--name"),
                     ("tyres-convert", "--name", "Mine", "--tune", "ax01", "--draft"), ("tyres-convert", "--name", "Mine", "--bogus", "1"),
                     ("tyres-convert", "--name", "Mine", "--new-id", "ax02")):
            with self.subTest(argv):
                code, out, err = self.run_main(*argv)
                self.assertEqual((code, out.strip(), err), (2, USAGE.strip(), ""))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tune_state.json")))

    def test_the_usage_block_lists_the_command_after_tyre_delete(self):
        lines = USAGE.splitlines()
        at = [i for i, l in enumerate(lines) if l.strip().startswith("python tools/tune.py tyre-delete ")][0]
        self.assertEqual(lines[at + 1], "  python tools/tune.py tyres-convert --name <text> [--tune ID | --draft] [--version ID] [--car ID] "
                                        "[--game <content.kspkg>] [--work <dir>]")


class TestTheGenericFieldTexts(World):
    """The 12 fields of the Tyre Creator say "the tyre" and "its axle" where the front settings say "the front tyre" and "the front axle"."""

    GONE = ("Stored in the car's own copy", "which the build makes only when", "It changes the compound the car starts on")
    PIECES = {
        "tyre_grip_lateral": ("friction coefficient of the tyre (TyresCompoundData.modelData.Dy0,", "a higher value gives its axle more sideways grip;"),
        "tyre_grip_longitudinal": ("friction coefficient of the tyre (modelData.Dx0,", "a higher value gives its axle more grip when accelerating"),
        "tyre_peak_slip_angle": ("Slip angle at which the tyre reaches its friction limit", "a larger angle lets its axle keep gripping"),
        "tyre_load_reference": ("Reference vertical load of the tyre model (modelData.Fz0,", "the load at which the tyre works best."),
        "tyre_pressure_ref": ("Inflation pressure stored in the tyre file (TyresCompoundData.pressure,", "(tyre_pressure_front / tyre_pressure_rear)"),
        "tyre_flex_lateral": ("Lateral flex stiffness of the tyre (tyreData.lateralFlexK;", "so the tyre gives less. The effect on driving is not tested in the game."),
        "tyre_flex_longitudinal": ("Longitudinal flex stiffness of the tyre (tyreData.longitudinalFlexK;", "so the tyre gives less under power"),
        "tyre_stiffness_rate": ("Vertical stiffness of the tyre (tyreData.rate;", "also changes the ride of its axle."),
        "tyre_heat_partition": ("Heat partition coefficient of the tyre (thermalData.heat_partition_coeff;", "heats the tyre faster when it slides."),
        "tyre_grain_gain": ("(rubber balling on the surface) of the tyre. Written to both", "makes the tyre grain up more when it slides."),
        "tyre_grain_slip_angle_gain": ("Graining caused by slip angle on the tyre (thermalData.grainSlipAngleGain,", "sliding sideways grain the tyre more."),
        "tyre_thermal_curve": ("Thermal performance curve family of the tyre (thermalData.thermalPerformanceCurve):", None)}

    def test_the_12_fields_of_the_real_catalogue_have_the_new_words_and_nothing_else_changes(self):
        cat = tune.read_catalogue(tune.CATALOGUE)
        fields = {f["id"]: f for f in tune.tyre_fields(cat) if "front_id" in f}
        self.assertEqual(sorted(fields), sorted(self.PIECES))
        by_id = {s["id"]: s["description"] for s in cat["settings"]}
        for field_id, pieces in self.PIECES.items():
            text = fields[field_id]["description"]
            with self.subTest(field_id):
                for piece in pieces:
                    if piece:
                        self.assertIn(piece, text)
                for gone in self.GONE:
                    self.assertNotIn(gone, text)
                self.assertIn("The effect on driving is not tested in the game.", text)
                self.assertNotIn("the front tyre", text)
                self.assertNotIn("the front axle", text)
                old = by_id[field_id + "_front"]
                self.assertEqual(text, old.replace("the front tyre", "the tyre").replace("the front axle", "its axle"))

    def test_the_catalogue_keeps_its_texts_and_a_description_without_the_words_is_untouched(self):
        cat = tune.read_catalogue(tune.CATALOGUE)
        self.assertIn("the front tyre", next(s for s in cat["settings"] if s["id"] == "tyre_grip_lateral_front")["description"])
        self.assertEqual([f["description"] for f in tune.tyre_fields(self.cat)], ["d tyre_dy_front", "d tyre_th_front", "d tyre_deep_front"])


class TestCliSubprocess(unittest.TestCase):
    def test_runtime_errors_are_error_lines_on_stderr_with_exit_1(self):
        with tmp() as d:
            for argv, message in ((("garage", "--car", "ks_no_such_car"), "error: unknown car 'ks_no_such_car'"),
                                  (("garage-set", "x.json", "--car", "ks_no_such_car"), "error: unknown car 'ks_no_such_car'"),
                                  (("garage-reset", "--car", "ks_no_such_car"), "error: unknown car 'ks_no_such_car'")):
                with self.subTest(argv):
                    code, out, err = run_main(tune.main, ["tune.py", *argv, "--work", str(d / "w")], cwd=d)
                    self.assertEqual((code, out), (1, ""))
                    self.assertTrue(err.startswith(message), err)
            self.assertEqual(os.listdir(d), [])

    def test_garage_and_garage_reset_on_an_empty_work_folder_write_nothing(self):
        with tmp() as d:
            r = run_tool("tune.py", "garage", "--work", d / "w", cwd=d)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertIn("default (the car's own tyres, the car is not touched)", r.stdout)
            self.assertIn("note: no tyres to show", r.stdout)
            r = run_tool("tune.py", "garage-reset", "--work", d / "w", cwd=d)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "tyre choice was not set\n", ""))
            self.assertEqual(os.listdir(d), [])


usage_cases(TestCliSubprocess, USAGE, (("garage_with_a_positional", ["garage", "x"]), ("garage_set_without_a_file", ["garage-set"]),
                                       ("garage_set_with_only_options", ["garage-set", "--draft"]), ("garage_reset_with_a_positional", ["garage-reset", "x"]),
                                       ("garage_tune_with_draft", ["garage", "--tune", "ax01", "--draft"]),
                                       ("garage_set_tune_with_draft", ["garage-set", "x.json", "--tune", "ax01", "--draft"]),
                                       ("garage_reset_tune_with_draft", ["garage-reset", "--tune", "ax01", "--draft"]),
                                       ("garage_with_an_unknown_option", ["garage", "--bogus", "1"]), ("garage_option_without_value", ["garage", "--car"]),
                                       ("garage_with_new_id", ["garage", "--new-id", "ax02"])), tune, check_empty=True)


if __name__ == "__main__":
    unittest.main()
