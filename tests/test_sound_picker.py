"""Tests for the sound picker part of tools/tune.py: the "_sounds" state key, actor_path, sound_options, sound_own, sound_choices, set_sound, reset_sounds, the build with a saved choice and the commands sounds, sound-set and sound-reset (the pure functions are tested in tests/test_sounds.py).

No game data and no schemas: the cars are synthetic (support.FakeCar replaces tune.load_msg / save_msg with in-memory messages, one shared store for all fake cars; the .actor of a car is an in-memory ActorData object); the commands run in-process on those cars, and as a subprocess where nothing is read (usage). clone_car.build and kspkg.cmd_pack are stubbed for the build test.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

from support import FakeCar, mini_catalogue, mini_setting, run_tool, tmp

import clone_car
import kspkg
import tune

USAGE = tune.__doc__.split("\n\n")[1]
KEY = tune.SOUND_KEY
REAL_RENAME = os.rename
BANK = "content\\sfx\\turbo.bank"
BACKFIRE_BANK = "content\\sfx\\backfire.bank"
T = "event:/parts/turbos/"
B = "event:/parts/backfires/"
T_NONE, T_RX7 = T + "turbo_none", T + "turbo_rx7"
B_A, B_B, B_CLASSIC = B + "backfire_a", B + "backfire_b", B + "backfire_classic#8"


def entry(event, kind=None, bank=BANK, **more):
    e = {"event": event}
    if kind is not None:
        e["type"] = kind
    e["transform"] = {"scale": {"x": 1.0}}
    e["bank"] = bank
    e.update(more)
    return e


def engine():
    return entry("event:/evo_cars/ks_x/engine_int", None, "content\\sfx\\ks_x.bank")


def turbo(name, **more):
    return entry(T + name, "TurboEvent", **more)


def backfire(name, **more):
    return entry(B + name, "Backfire", BACKFIRE_BANK, **more)


def actor(*entries):
    return {"car": {"cameras": ["c1"], "audio_events": list(entries), "_order": ["cameras"] + ["audio_events"] * len(entries)}}


def sound_cat():
    return mini_catalogue(
        mini_setting("name_suffix", kind="meta", type="string", default="_MY", handler="name_suffix"),
        mini_setting("variant_name", kind="meta", type="string", default_template="{stock_variant_name}", handler="variant_name"),
        mini_setting("limiter", type="int", targets=[("@engine", "limiter")]))


class World(unittest.TestCase):
    """Fake cars in one work folder: ks_x (the default car; own sounds turbo_none and backfire_a), ks_a (turbo_rx7, backfire_classic with
    optionalParam 8, the backfire entry first), ks_b (turbo_rx7, backfire_a, its actor file is named KS_B.ACTOR), ks_n (a backfire entry
    only: backfire_b), ks_u (an actor that cannot be decoded), ks_z (no actor file) and ks_q (only a build folder: not installed)."""

    def setUp(self):
        cm = tmp()
        self.d = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.work = str(self.d / "work")
        data = {"default": "ks_x", "cars": [{"id": c, "label": "Car " + c} for c in ("ks_x", "ks_a", "ks_b", "ks_n", "ks_u", "ks_z", "ks_q")]}
        self.patch(tune, "load_cars", lambda path=None: data)
        self.cat = sound_cat()
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)
        self.first, self.fakes = None, {}
        self.add_car("ks_x", actor(engine(), turbo("turbo_none"), backfire("backfire_a")), name="Car X")
        self.add_car("ks_a", actor(backfire("backfire_classic", optionalParam=8), engine(), turbo("turbo_rx7")))
        self.add_car("ks_b", actor(engine(), turbo("turbo_rx7"), backfire("backfire_a")), file="KS_B.ACTOR")
        self.add_car("ks_n", actor(engine(), backfire("backfire_b")))
        u = self.add_car("ks_u", actor(engine()))
        u.store[u.key(os.path.join(u.car_root, "ks_u.actor"))] = ValueError("cannot decode")
        self.add_car("ks_z", None)
        os.makedirs(os.path.join(self.work, "ks_q", "build"))

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)
        return value

    def add_car(self, car_id, obj, name=None, file=None):
        fc = FakeCar(self.work, car_id)
        if self.first is None:
            self.first = fc.install(self)
        else:
            fc.store = self.first.store
        gp = fc.game_path
        fc.add("data/%s.car" % car_id, {"engine_path": gp("data/engine.carengine")})
        fc.add("data/engine.carengine", {"limiter": 7000})
        fc.add("presets/p.mechanicalcarpreset", {"brand": "B", "description": "D"})
        if obj is not None:
            fc.add(file or "%s.actor" % car_id, obj)
        if name:
            self.write(tune.stock_info_path(self.work, car_id),
                       {"car_id": car_id, "display_name": name, "brand": "Brand", "year": 1999, "property_1": "P1", "property_2": "P2",
                        "property_3": "P3", "variant_name": "Base"})
        self.fakes[car_id] = fc
        return fc

    def write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def state(self, tune_id=None, car_id="ks_x"):
        return tune.load_state(self.work, car_id, tune_id)

    def keys(self, options):
        return {slot: [o["key"] for o in found] for slot, found in options.items()}

    def run_main(self, *argv):
        out, err, code = io.StringIO(), io.StringIO(), None
        with mock.patch.object(sys, "argv", ["tune.py", *argv, "--work", self.work]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                tune.main()
            except SystemExit as e:
                code = e.code
        if isinstance(code, str):
            err.write(code + "\n")
            code = 1
        return code or 0, out.getvalue(), err.getvalue()


class TestStateKey(World):
    def test_the_key_name(self):
        self.assertEqual(KEY, "_sounds")

    def test_the_key_is_not_an_unknown_state_id_and_the_warning_skips_it(self):
        tune.save_state(self.work, "ks_x", {"limiter": 7000, KEY: {"turbo": T_RX7}, "old": 1})
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat), ["old"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tune.warn_unknown_state(self.work, "ks_x", self.cat)
        self.assertEqual(err.getvalue(), "warning: ignoring unknown setting 'old' in the saved state\n")
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}}, tune.DRAFT)
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat, tune.DRAFT), [])
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}}, "ax01")
        self.assertEqual(tune.unknown_state_ids(self.work, "ks_x", self.cat, "ax01"), [])

    def test_the_key_is_no_row_and_show_and_defaults_ignore_it(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7, "backfire": B_B}})
        for hidden in (False, True):
            self.assertNotIn(KEY, [r["id"] for r in tune.effective_rows(self.work, "ks_x", self.cat, hidden=hidden)])
        results = {}
        for command in ("show", "defaults"):
            results[command] = self.run_main(command)
            self.assertEqual(results[command][0::2], (0, ""))
            self.assertNotIn("_sounds", results[command][1])
        tune.save_state(self.work, "ks_x", {})
        for command in ("show", "defaults"):
            self.assertEqual(self.run_main(command), results[command])

    def test_the_key_is_never_an_applied_setting(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}})
        plan = tune.apply_plan(self.work, "ks_x", "ax_x", False, None, self.cat)
        self.assertEqual(plan["changed"], [])
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}, "limiter": 8000})
        plan = tune.apply_plan(self.work, "ks_x", "ax_x", False, None, self.cat)
        self.assertEqual([s["id"] for s, _ in plan["changed"]], ["limiter"])
        self.assertEqual((plan["garage"], plan["kit"]), (None, None))

    def test_set_and_unset_of_settings_keep_the_key_and_the_key_cannot_be_set_or_unset(self):
        saved = {"turbo": T_RX7}
        tune.save_state(self.work, "ks_x", {KEY: saved})
        tune.set_value(self.work, "ks_x", "limiter", "8000", self.cat)
        self.assertEqual(self.state(), {KEY: saved, "limiter": 8000})
        tune.unset_value(self.work, "ks_x", "limiter", self.cat)
        self.assertEqual(self.state(), {KEY: saved})
        for call in (lambda: tune.unset_value(self.work, "ks_x", KEY, self.cat), lambda: tune.set_value(self.work, "ks_x", KEY, "x", self.cat)):
            with self.assertRaisesRegex(ValueError, "^unknown setting '_sounds'$"):
                call()
        self.assertEqual(self.state(), {KEY: saved})
        self.assertEqual(self.run_main("unset", KEY), (1, "", "error: unknown setting '_sounds'\n"))
        self.assertEqual(self.run_main("set", "limiter", "8100")[0], 0)
        self.assertEqual(self.state(), {KEY: saved, "limiter": 8100})

    def test_duplicate_tune_copies_the_key_with_the_rest_of_the_state(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_B}})
        res = tune.duplicate_tune(self.work, "ks_x", None)
        self.assertEqual(self.state(res["id"]), {"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_B}, "name_suffix": "_MY2"})
        copied = self.state(res["id"])
        copied[KEY]["turbo"] = T_NONE
        tune.save_state(self.work, "ks_x", copied, res["id"])
        self.assertEqual(self.state()[KEY], {"turbo": T_RX7, "backfire": B_B})
        again = tune.duplicate_tune(self.work, "ks_x", res["id"])
        self.assertEqual(self.state(again["id"])[KEY], {"turbo": T_NONE, "backfire": B_B})
        tune.save_state(self.work, "ks_x", {KEY: {"backfire": B_A}}, tune.DRAFT)
        res = tune.duplicate_tune(self.work, "ks_x", tune.DRAFT)
        self.assertEqual(self.state(res["id"])[KEY], {"backfire": B_A})

    def test_new_tune_from_draft_copies_the_key_and_the_draft_keeps_it(self):
        tune.save_state(self.work, "ks_x", {"limiter": 9000, KEY: {"turbo": T_RX7}}, tune.DRAFT)
        res = tune.new_tune_from_draft(self.work, "ks_x")
        self.assertEqual(self.state(res["id"]), {"limiter": 9000, KEY: {"turbo": T_RX7}, "name_suffix": "_MY"})
        self.assertEqual(self.state(tune.DRAFT), {"limiter": 9000, KEY: {"turbo": T_RX7}})
        tune.save_state(self.work, "ks_x", {}, tune.DRAFT)
        self.assertEqual(self.state(res["id"])[KEY], {"turbo": T_RX7})

    def test_saved_sounds(self):
        self.assertEqual(tune.saved_sounds({}), {})
        self.assertEqual(tune.saved_sounds({KEY: {}}), {})
        self.assertEqual(tune.saved_sounds({KEY: {"turbo": T_RX7}}), {"turbo": T_RX7})
        for bad in ([], "turbo", 5, None, {"turbo": 5}, {"turbo": None}, {"turbo": ["x"]}):
            with self.subTest(repr(bad)):
                with self.assertRaisesRegex(ValueError, "^damaged sound choice in the saved state$"):
                    tune.saved_sounds({KEY: bad})


class TestActorPath(World):
    def test_the_actor_of_a_car_is_found_in_its_base_whatever_the_case(self):
        base = tune.car_root_of(tune.base_dir(self.work, "ks_x"), "ks_x")
        self.assertEqual(tune.actor_path(self.work, "ks_x"), os.path.join(base, "ks_x.actor"))
        self.assertEqual(os.path.basename(tune.actor_path(self.work, "ks_b")), "KS_B.ACTOR")

    def test_a_car_without_a_base_or_without_the_file_is_a_value_error(self):
        with self.assertRaisesRegex(ValueError, "^no base car in .*, run init first$"):
            tune.actor_path(self.work, "ks_q")
        with self.assertRaisesRegex(ValueError, r"^ks_z\.actor not found in "):
            tune.actor_path(self.work, "ks_z")


class TestSoundOptions(World):
    def test_the_options_of_every_installed_car_sorted_with_their_cars(self):
        options, skipped = tune.sound_options(self.work)
        self.assertEqual(self.keys(options), {"turbo": [T_NONE, T_RX7], "backfire": [B_A, B_B, B_CLASSIC]})
        self.assertEqual([(o["key"], o["cars"]) for o in options["turbo"]], [(T_NONE, ["ks_x"]), (T_RX7, ["ks_a", "ks_b"])])
        self.assertEqual([(o["key"], o["cars"]) for o in options["backfire"]],
                         [(B_A, ["ks_b", "ks_x"]), (B_B, ["ks_n"]), (B_CLASSIC, ["ks_a"])])
        self.assertEqual(options["backfire"][2], {"key": B_CLASSIC, "event": B + "backfire_classic", "bank": BACKFIRE_BANK, "optional": 8, "cars": ["ks_a"]})

    def test_a_car_whose_actor_is_missing_or_cannot_be_decoded_is_skipped_and_reported(self):
        options, skipped = tune.sound_options(self.work)
        self.assertEqual([s["car"] for s in skipped], ["ks_u", "ks_z"])
        self.assertEqual(skipped[0]["reason"], "cannot decode")
        self.assertRegex(skipped[1]["reason"], r"^ks_z\.actor not found in ")
        for found in options.values():
            self.assertFalse({"ks_u", "ks_z", "ks_q"} & {c for o in found for c in o["cars"]})

    def test_the_car_without_a_turbo_entry_offers_its_backfire_only(self):
        options, _ = tune.sound_options(self.work)
        self.assertNotIn("ks_n", [c for o in options["turbo"] for c in o["cars"]])
        self.assertIn("ks_n", [c for o in options["backfire"] for c in o["cars"]])

    def test_the_actor_file_is_found_whatever_its_case(self):
        options, _ = tune.sound_options(self.work)
        self.assertIn("ks_b", [c for o in options["backfire"] for c in o["cars"]])

    def test_an_empty_work_folder_offers_nothing(self):
        self.assertEqual(tune.sound_options(str(self.d / "empty")), ({"turbo": [], "backfire": []}, []))

    def test_reading_changes_no_file(self):
        tune.sound_options(self.work)
        self.assertEqual(self.fakes["ks_x"].saved, [])
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))


class TestSoundOwn(World):
    def test_the_stock_sound_of_each_slot(self):
        self.assertEqual(tune.sound_own(self.work, "ks_x"), {"turbo": T_NONE, "backfire": B_A})
        self.assertEqual(tune.sound_own(self.work, "ks_a"), {"turbo": T_RX7, "backfire": B_CLASSIC})

    def test_a_slot_without_an_entry_is_none(self):
        self.assertEqual(tune.sound_own(self.work, "ks_n"), {"turbo": None, "backfire": B_B})

    def test_a_car_that_cannot_be_read_is_a_value_error(self):
        for car_id, message in (("ks_q", "^no base car in "), ("ks_z", r"^ks_z\.actor not found in "), ("ks_u", "^cannot decode$")):
            with self.subTest(car_id):
                with self.assertRaisesRegex(ValueError, message):
                    tune.sound_own(self.work, car_id)


class TestSoundChoices(World):
    def test_without_a_saved_choice_nothing_is_selected(self):
        res = tune.sound_choices(self.work, "ks_x")
        self.assertEqual(set(res), {"slots", "skipped", "missing"})
        self.assertEqual(list(res["slots"]), ["turbo", "backfire"])
        self.assertEqual((res["slots"]["turbo"]["own"], res["slots"]["turbo"]["selected"]), (T_NONE, None))
        self.assertEqual((res["slots"]["backfire"]["own"], res["slots"]["backfire"]["selected"]), (B_A, None))
        options, skipped = tune.sound_options(self.work)
        self.assertEqual(({s: v["options"] for s, v in res["slots"].items()}, res["skipped"], res["missing"]), (options, skipped, []))

    def test_a_saved_choice_is_selected_per_slot(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}})
        res = tune.sound_choices(self.work, "ks_x")
        self.assertEqual((res["slots"]["turbo"]["selected"], res["slots"]["backfire"]["selected"], res["missing"]), (T_RX7, None, []))

    def test_the_draft_and_a_tune_have_their_own_choice(self):
        tune.save_state(self.work, "ks_x", {KEY: {"backfire": B_B}}, tune.DRAFT)
        tune.save_state(self.work, "ks_x", {KEY: {"backfire": B_CLASSIC}}, "ax01")
        self.assertEqual([tune.sound_choices(self.work, "ks_x", t)["slots"]["backfire"]["selected"] for t in (None, tune.DRAFT, "ax01")], [None, B_B, B_CLASSIC])

    def test_a_saved_key_that_is_no_option_any_more_is_missing_and_not_selected(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T + "turbo_gone", "backfire": B_B}})
        res = tune.sound_choices(self.work, "ks_x")
        self.assertEqual(res["missing"], [{"slot": "turbo", "key": T + "turbo_gone"}])
        self.assertEqual((res["slots"]["turbo"]["selected"], res["slots"]["backfire"]["selected"]), (None, B_B))

    def test_a_key_of_the_other_slot_is_missing(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": B_B}})
        self.assertEqual(tune.sound_choices(self.work, "ks_x")["missing"], [{"slot": "turbo", "key": B_B}])

    def test_a_saved_slot_that_does_not_exist_is_ignored_and_kept(self):
        tune.save_state(self.work, "ks_x", {KEY: {"horn": "event:/h", "turbo": T_RX7}})
        res = tune.sound_choices(self.work, "ks_x")
        self.assertEqual((res["slots"]["turbo"]["selected"], res["missing"], list(res["slots"])), (T_RX7, [], ["turbo", "backfire"]))
        tune.set_sound(self.work, "ks_x", "backfire", B_B)
        self.assertEqual(self.state()[KEY], {"horn": "event:/h", "turbo": T_RX7, "backfire": B_B})

    def test_the_skipped_cars_are_reported(self):
        self.assertEqual([s["car"] for s in tune.sound_choices(self.work, "ks_x")["skipped"]], ["ks_u", "ks_z"])

    def test_a_damaged_saved_choice_is_an_error(self):
        tune.save_state(self.work, "ks_x", {KEY: ["turbo"]})
        with self.assertRaisesRegex(ValueError, "^damaged sound choice in the saved state$"):
            tune.sound_choices(self.work, "ks_x")

    def test_a_car_without_a_base_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "^no base car in .*, run init first$"):
            tune.sound_choices(self.work, "ks_q")

    def test_a_tune_that_does_not_exist_is_an_error(self):
        with self.assertRaises(ValueError):
            tune.sound_choices(self.work, "ks_x", "not a tune")


class TestSetSound(World):
    def test_a_choice_is_stored_per_slot_and_the_rest_of_the_state_is_kept(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000})
        res = tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        self.assertEqual(self.state(), {"limiter": 8000, KEY: {"turbo": T_RX7}})
        self.assertEqual((res["slots"]["turbo"]["selected"], res["slots"]["backfire"]["selected"], res["missing"]), (T_RX7, None, []))
        res = tune.set_sound(self.work, "ks_x", "backfire", B_CLASSIC)
        self.assertEqual(self.state(), {"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        self.assertEqual((res["slots"]["turbo"]["selected"], res["slots"]["backfire"]["selected"]), (T_RX7, B_CLASSIC))
        self.assertEqual(res, tune.sound_choices(self.work, "ks_x"))

    def test_another_choice_replaces_the_old_one_of_the_slot(self):
        tune.set_sound(self.work, "ks_x", "backfire", B_B)
        tune.set_sound(self.work, "ks_x", "backfire", B_CLASSIC)
        self.assertEqual(self.state(), {KEY: {"backfire": B_CLASSIC}})

    def test_the_own_sound_of_the_car_removes_the_slot_and_an_empty_entry_is_removed(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        tune.set_sound(self.work, "ks_x", "backfire", B_B)
        res = tune.set_sound(self.work, "ks_x", "turbo", T_NONE)
        self.assertEqual(self.state(), {KEY: {"backfire": B_B}})
        self.assertEqual((res["slots"]["turbo"]["selected"], res["slots"]["turbo"]["own"]), (None, T_NONE))
        tune.set_sound(self.work, "ks_x", "backfire", B_A)
        self.assertEqual(self.state(), {})

    def test_a_car_without_the_entry_can_choose_any_option_and_its_own_backfire_removes_the_choice(self):
        tune.set_sound(self.work, "ks_n", "turbo", T_NONE)
        self.assertEqual(self.state(car_id="ks_n"), {KEY: {"turbo": T_NONE}})
        tune.set_sound(self.work, "ks_n", "backfire", B_B)
        self.assertEqual(self.state(car_id="ks_n"), {KEY: {"turbo": T_NONE}})

    def test_key_none_removes_the_slot(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        res = tune.set_sound(self.work, "ks_x", "turbo", None)
        self.assertEqual((self.state(), res["slots"]["turbo"]["selected"]), ({}, None))
        tune.save_state(self.work, "ks_x", {KEY: {}})
        tune.set_sound(self.work, "ks_x", "turbo", None)
        self.assertEqual(self.state(), {})

    def test_nothing_is_written_when_nothing_changes(self):
        real = tune.save_state
        with mock.patch.object(tune, "save_state", side_effect=real) as spy:
            tune.set_sound(self.work, "ks_x", "turbo", T_NONE)
            tune.set_sound(self.work, "ks_x", "turbo", None)
            self.assertEqual(spy.call_count, 0)
            tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
            tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
            self.assertEqual(spy.call_count, 1)

    def test_the_draft_and_a_modded_car_have_their_own_choice(self):
        tune.save_state(self.work, "ks_x", {"name_suffix": "_A"}, "ax01")
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7, tune.DRAFT)
        tune.set_sound(self.work, "ks_x", "backfire", B_B, "ax01")
        self.assertEqual((self.state(), self.state(tune.DRAFT), self.state("ax01")),
                         ({}, {KEY: {"turbo": T_RX7}}, {"name_suffix": "_A", KEY: {"backfire": B_B}}))

    def test_a_slot_that_does_not_exist_is_refused_before_anything_is_read(self):
        with mock.patch.object(tune, "sound_options", side_effect=AssertionError("read")):
            for slot in ("horn", "Turbo", None, 5):
                with self.subTest(repr(slot)):
                    with self.assertRaisesRegex(ValueError, "^unknown sound slot .*, use one of: turbo, backfire$"):
                        tune.set_sound(self.work, "ks_x", slot, T_RX7)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_a_key_that_is_no_option_of_the_slot_is_refused(self):
        for slot, key in (("turbo", T + "turbo_gone"), ("turbo", B_B), ("backfire", T_RX7), ("turbo", ""), ("backfire", B + "backfire_classic"),
                          ("turbo", T_RX7 + " ")):
            with self.subTest((slot, key)):
                with self.assertRaisesRegex(ValueError, "^unknown %s sound .*, sounds lists the sounds of the game cars$" % slot):
                    tune.set_sound(self.work, "ks_x", slot, key)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_a_key_that_is_not_text_is_refused(self):
        for key in (5, ["x"], {"a": 1}, True):
            with self.subTest(repr(key)):
                with self.assertRaisesRegex(ValueError, "^the sound key must be text, got "):
                    tune.set_sound(self.work, "ks_x", "turbo", key)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_a_car_that_cannot_be_read_or_a_damaged_state_is_an_error_and_writes_nothing(self):
        with self.assertRaisesRegex(ValueError, "^no base car in "):
            tune.set_sound(self.work, "ks_q", "turbo", T_RX7)
        with self.assertRaisesRegex(ValueError, "^ks_z.actor not found in "):
            tune.set_sound(self.work, "ks_z", "turbo", T_RX7)
        tune.save_state(self.work, "ks_x", {KEY: 5})
        with self.assertRaisesRegex(ValueError, "^damaged sound choice in the saved state$"):
            tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        self.assertEqual(self.state(), {KEY: 5})
        self.assertFalse(any(os.path.exists(tune.state_path(self.work, c)) for c in ("ks_q", "ks_z")))

    def test_a_tune_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValueError):
            tune.set_sound(self.work, "ks_x", "turbo", T_RX7, "not a tune")

    def test_no_actor_file_is_written(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        self.assertEqual(self.fakes["ks_x"].saved, [])


class TestResetSounds(World):
    def test_without_a_slot_every_choice_is_removed(self):
        tune.save_state(self.work, "ks_x", {"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_B}})
        self.assertEqual(tune.reset_sounds(self.work, "ks_x"), {"removed": True})
        self.assertEqual(self.state(), {"limiter": 8000})
        self.assertEqual(tune.reset_sounds(self.work, "ks_x"), {"removed": False})

    def test_one_slot_is_removed_and_the_other_stays(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7, "backfire": B_B}})
        self.assertEqual(tune.reset_sounds(self.work, "ks_x", slot="turbo"), {"removed": True})
        self.assertEqual(self.state(), {KEY: {"backfire": B_B}})
        self.assertEqual(tune.reset_sounds(self.work, "ks_x", slot="turbo"), {"removed": False})
        self.assertEqual(tune.reset_sounds(self.work, "ks_x", slot="backfire"), {"removed": True})
        self.assertEqual(self.state(), {})

    def test_nothing_is_written_when_there_is_nothing_to_remove(self):
        with mock.patch.object(tune, "save_state", side_effect=AssertionError("written")):
            self.assertEqual(tune.reset_sounds(self.work, "ks_x"), {"removed": False})
            self.assertEqual(tune.reset_sounds(self.work, "ks_x", slot="turbo"), {"removed": False})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_the_draft_and_a_tune(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7, tune.DRAFT)
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7, "ax01")
        self.assertEqual(tune.reset_sounds(self.work, "ks_x", tune.DRAFT), {"removed": True})
        self.assertEqual((self.state(tune.DRAFT), self.state("ax01")), ({}, {KEY: {"turbo": T_RX7}}))
        self.assertEqual(tune.reset_sounds(self.work, "ks_x", "ax01", "turbo"), {"removed": True})
        self.assertEqual(self.state("ax01"), {})

    def test_a_slot_that_does_not_exist_is_refused(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}})
        with self.assertRaisesRegex(ValueError, "^unknown sound slot 'horn', use one of: turbo, backfire$"):
            tune.reset_sounds(self.work, "ks_x", slot="horn")
        self.assertEqual(self.state(), {KEY: {"turbo": T_RX7}})

    def test_a_damaged_entry_is_removed_as_a_whole_but_not_edited_by_slot(self):
        tune.save_state(self.work, "ks_x", {KEY: 5})
        with self.assertRaisesRegex(ValueError, "^damaged sound choice in the saved state$"):
            tune.reset_sounds(self.work, "ks_x", slot="turbo")
        self.assertEqual(tune.reset_sounds(self.work, "ks_x"), {"removed": True})
        self.assertEqual(self.state(), {})

    def test_the_car_need_not_be_extracted(self):
        tune.save_state(self.work, "ks_q", {KEY: {"turbo": T_RX7}})
        self.assertEqual(tune.reset_sounds(self.work, "ks_q"), {"removed": True})


class Apply(World):
    """apply of ks_x with clone_car.build and kspkg.cmd_pack stubbed; the files of the build are the stub contents of FakeCar."""

    def setUp(self):
        super().setUp()
        self.calls, self.packed = [], []
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
        self.game = os.path.join(self.work, "no_game.kspkg")

    def rename(self, src, dst):
        old, new = self.fakes["ks_x"].key(src), self.fakes["ks_x"].key(dst)
        store = self.fakes["ks_x"].store
        moved = [k for k in store if k.startswith(old + os.sep)]
        REAL_RENAME(src, dst)
        store.update({new + k[len(old):]: store.pop(k) for k in moved})

    def build(self, car_dir, new_id, out_dir, name, year, brand, variant, stock_loc, props, pack=True):
        self.calls.append(("build", new_id))
        self.fakes["ks_x"].clone_into(out_dir, new_id)
        return ["note: from build"]

    def pack(self, indir, pkg):
        self.calls.append(("pack", indir))
        self.packed.append(sorted(os.path.relpath(os.path.join(dp, n), indir).replace(os.sep, "/") for dp, _, names in os.walk(indir) for n in names))
        with open(pkg, "wb") as f:
            f.write(b"PKG-NEW")

    def apply(self, state):
        tune.save_state(self.work, "ks_x", state)
        return tune.apply(self.work, "ks_x", catalogue=self.cat, game=self.game, install=False)

    def snapshot(self, res):
        fc = self.fakes["ks_x"]
        root = fc.key(os.path.join(res["build_dir"], "content", "cars", res["new_id"]))
        return {k[len(root):]: json.dumps(v, sort_keys=True) for k, v in fc.store.items() if k.startswith(root + os.sep)}


class TestApplyIgnoresTheKey(Apply):
    def test_a_build_with_a_saved_choice_has_the_same_package_inputs_as_one_without(self):
        plain = self.apply({"limiter": 8000})
        before = (self.snapshot(plain), plain["notes"], plain["applied"], self.packed[-1], plain["size"])
        chosen = self.apply({"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_B}})
        after = (self.snapshot(chosen), chosen["notes"], chosen["applied"], self.packed[-1], chosen["size"])
        self.assertEqual(after, before)
        self.assertEqual([a["id"] for a in chosen["applied"]], ["limiter"])
        self.assertEqual(len(self.packed), 2)

    def test_the_built_actor_keeps_the_stock_sounds(self):
        res = self.apply({KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        built = [json.loads(v) for k, v in self.snapshot(res).items() if k.endswith(".actor")]
        self.assertEqual(len(built), 1)
        events = [e["event"] for e in built[0]["car"]["audio_events"]]
        self.assertIn(T_NONE, events)
        self.assertIn(B_A, events)
        self.assertNotIn(T_RX7, events)

    def test_the_state_file_is_not_touched_by_a_build(self):
        state = {"limiter": 8000, KEY: {"turbo": T_RX7}}
        self.apply(state)
        self.assertEqual(self.state(), state)

    def test_a_choice_for_a_sound_nobody_offers_any_more_does_not_stop_the_build(self):
        res = self.apply({KEY: {"turbo": T + "turbo_gone"}})
        self.assertEqual(res["notes"], ["note: from build"])

    def test_apply_from_the_command_line_ignores_the_key_too(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}})
        with mock.patch.object(tune, "game_running", lambda: False):
            code, out, err = self.run_main("apply", "--no-install")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("applied 0 setting(s)", out)
        self.assertNotIn("_sounds", out)


class TestCommands(World):
    def test_sounds_lists_every_slot_with_the_own_sound_marked(self):
        code, out, err = self.run_main("sounds")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "turbo (own: %s, selected: -)" % T_NONE,
            "= %s  ks_x" % T_NONE,
            "  %s  ks_a, ks_b" % T_RX7,
            "backfire (own: %s, selected: -)" % B_A,
            "= %s  ks_b, ks_x" % B_A,
            "  %s  ks_n" % B_B,
            "  %s  ks_a" % B_CLASSIC])

    def test_skipped_cars_are_reported_on_stderr(self):
        code, out, err = self.run_main("sounds")
        lines = err.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "skipped ks_u: cannot decode")
        self.assertRegex(lines[1], r"^skipped ks_z: ks_z\.actor not found in ")

    def test_the_selected_sound_is_marked_with_a_star_in_place_of_the_own_mark(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        tune.set_sound(self.work, "ks_x", "backfire", B_CLASSIC)
        lines = self.run_main("sounds")[1].splitlines()
        self.assertEqual(lines[0], "turbo (own: %s, selected: %s)" % (T_NONE, T_RX7))
        self.assertEqual(lines[1:3], ["= %s  ks_x" % T_NONE, "* %s  ks_a, ks_b" % T_RX7])
        self.assertEqual(lines[3], "backfire (own: %s, selected: %s)" % (B_A, B_CLASSIC))
        self.assertEqual(lines[4:], ["= %s  ks_b, ks_x" % B_A, "  %s  ks_n" % B_B, "* %s  ks_a" % B_CLASSIC])

    def test_a_car_without_a_turbo_entry_says_none(self):
        lines = self.run_main("sounds", "--car", "ks_n")[1].splitlines()
        self.assertEqual(lines[0], "turbo (own: none, selected: -)")
        self.assertEqual([l for l in lines if l.startswith("=")], ["= %s  ks_n" % B_B])

    def test_at_most_four_cars_are_named_then_the_number_of_the_others(self):
        for i in range(5):
            self.add_car("ks_m%d" % i, actor(engine(), turbo("turbo_none")))
        lines = self.run_main("sounds")[1].splitlines()
        self.assertEqual(lines[1], "= %s  ks_m0, ks_m1, ks_m2, ks_m3 +2 more" % T_NONE)
        self.add_car("ks_m5", actor(engine(), turbo("turbo_none")))
        self.assertEqual(self.run_main("sounds")[1].splitlines()[1], "= %s  ks_m0, ks_m1, ks_m2, ks_m3 +3 more" % T_NONE)
        self.assertEqual(tune.cars_text(["a", "b", "c", "d"]), "a, b, c, d")
        self.assertEqual(tune.cars_text(["a"]), "a")

    def test_sounds_works_on_the_draft_and_on_a_modded_car(self):
        tune.save_state(self.work, "ks_x", {"name_suffix": "_A"}, "ax01")
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7, tune.DRAFT)
        tune.set_sound(self.work, "ks_x", "backfire", B_B, "ax01")
        self.assertIn("turbo (own: %s, selected: %s)" % (T_NONE, T_RX7), self.run_main("sounds", "--draft")[1])
        self.assertIn("backfire (own: %s, selected: %s)" % (B_A, B_B), self.run_main("sounds", "--tune", "ax01")[1])
        self.assertIn("selected: -)", self.run_main("sounds")[1])

    def test_a_saved_sound_that_is_gone_is_a_warning_on_stderr(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T + "turbo_gone"}})
        code, out, err = self.run_main("sounds")
        self.assertEqual(code, 0)
        self.assertIn("warning: the saved turbo sound %s is not available any more\n" % (T + "turbo_gone"), err)
        self.assertNotIn("turbo_gone", out)

    def test_sound_set_stores_the_choice_and_sounds_shows_it(self):
        self.assertEqual(self.run_main("sound-set", "turbo", T_RX7), (0, "turbo sound: %s\n" % T_RX7, ""))
        self.assertEqual(self.state(), {KEY: {"turbo": T_RX7}})
        self.assertEqual(self.run_main("sound-set", "backfire", B_CLASSIC)[1], "backfire sound: %s\n" % B_CLASSIC)
        self.assertEqual(self.state(), {KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        self.assertIn("turbo (own: %s, selected: %s)" % (T_NONE, T_RX7), self.run_main("sounds")[1])

    def test_sound_set_with_the_own_sound_removes_the_choice(self):
        self.run_main("sound-set", "turbo", T_RX7)
        code, out, err = self.run_main("sound-set", "turbo", T_NONE)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "turbo sound: %s (the own sound of the car, nothing is stored)\n" % T_NONE)
        self.assertEqual(self.state(), {})

    def test_sound_set_on_the_draft_a_tune_and_another_car(self):
        tune.save_state(self.work, "ks_x", {}, "ax01")
        self.assertEqual(self.run_main("sound-set", "turbo", T_RX7, "--draft")[0], 0)
        self.assertEqual(self.run_main("sound-set", "backfire", B_B, "--tune", "ax01")[0], 0)
        self.assertEqual(self.run_main("sound-set", "backfire", B_A, "--car", "ks_n")[0], 0)
        self.assertEqual((self.state(), self.state(tune.DRAFT), self.state("ax01"), self.state(car_id="ks_n")),
                         ({}, {KEY: {"turbo": T_RX7}}, {KEY: {"backfire": B_B}}, {KEY: {"backfire": B_A}}))

    def test_sound_reset_removes_one_slot_or_all(self):
        self.run_main("sound-set", "turbo", T_RX7)
        self.run_main("sound-set", "backfire", B_B)
        self.assertEqual(self.run_main("sound-reset", "turbo"), (0, "turbo sound selection removed from the state\n", ""))
        self.assertEqual(self.state(), {KEY: {"backfire": B_B}})
        self.assertEqual(self.run_main("sound-reset", "turbo"), (0, "turbo sound selection was not set\n", ""))
        self.assertEqual(self.run_main("sound-reset"), (0, "sound selection removed from the state\n", ""))
        self.assertEqual(self.run_main("sound-reset"), (0, "sound selection was not set\n", ""))
        self.assertEqual(self.state(), {})

    def test_sound_reset_on_the_draft_and_a_tune(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7, tune.DRAFT)
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7, "ax01")
        self.assertEqual(self.run_main("sound-reset", "--draft")[1], "sound selection removed from the state\n")
        self.assertEqual(self.state(tune.DRAFT), {})
        self.assertEqual(self.state("ax01"), {KEY: {"turbo": T_RX7}})
        self.assertEqual(self.run_main("sound-reset", "turbo", "--tune", "ax01")[1], "turbo sound selection removed from the state\n")
        self.assertEqual(self.state("ax01"), {})

    def test_runtime_errors_are_error_lines_with_exit_1(self):
        for argv, message in ((("sound-set", "horn", T_RX7), "error: unknown sound slot 'horn', use one of: turbo, backfire\n"),
                              (("sound-set", "turbo", T + "turbo_gone"), "error: unknown turbo sound %sturbo_gone, sounds lists" % T),
                              (("sound-set", "turbo", B_B), "error: unknown turbo sound %s, sounds lists" % B_B),
                              (("sound-reset", "horn"), "error: unknown sound slot 'horn', use one of: turbo, backfire\n"),
                              (("sounds", "--tune", "ax99"), "error: ks_x has no tune ax99"),
                              (("sound-set", "turbo", T_RX7, "--tune", "ax99"), "error: ks_x has no tune ax99"),
                              (("sound-reset", "--tune", "ax99"), "error: ks_x has no tune ax99"),
                              (("sounds", "--car", "ks_q"), "error: no base car in "),
                              (("sounds", "--car", "ks_nope"), "error: unknown car 'ks_nope'")):
            with self.subTest(argv):
                code, out, err = self.run_main(*argv)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith(message), err)
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))

    def test_the_usage_lists_the_commands_in_the_dispatch_order(self):
        for cmd, tail in (("sounds", "[--tune ID | --draft] [--car ID] [--work <dir>]"), ("sound-set", "<slot> <key> [--tune ID | --draft] [--car ID] [--work <dir>]"),
                          ("sound-reset", "[<slot>] [--tune ID | --draft] [--car ID] [--work <dir>]")):
            line = [l for l in USAGE.splitlines() if l.strip().startswith("python tools/tune.py " + cmd + " ")]
            self.assertEqual(len(line), 1, cmd)
            self.assertEqual(line[0].split(None, 3)[3], tail)
            self.assertEqual(tune.COMMANDS[cmd].__name__, "cmd_" + cmd.replace("-", "_"))
        names = list(tune.COMMANDS)
        self.assertEqual(names[names.index("turbo-kit") + 1:names.index("turbo-kit") + 4], ["sounds", "sound-set", "sound-reset"])
        self.assertEqual(names[-1], "ranges")

    def test_the_module_text_describes_the_state_key_and_the_commands(self):
        doc = tune.__doc__
        for text in ('"_sounds" = {"turbo": <option key>, "backfire": <option key>}', "sounds:       lists per slot", "sound-set:    chooses", "sound-reset:  removes"):
            self.assertIn(text, doc)

    def test_wrong_arguments_print_the_usage_and_exit_2(self):
        for argv in (["sounds", "x"], ["sounds", "--tune", "ax01", "--draft"], ["sounds", "--bogus", "1"], ["sound-set"], ["sound-set", "turbo"],
                     ["sound-set", "turbo", T_RX7, "x"], ["sound-set", "turbo", T_RX7, "--tune", "ax01", "--draft"], ["sound-reset", "turbo", "backfire"],
                     ["sound-reset", "--tune", "ax01", "--draft"]):
            with self.subTest(argv):
                code, out, err = self.run_main(*argv)
                self.assertEqual((code, out.strip(), err), (2, USAGE.strip(), ""))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x")))


def usage_case(name, argv):
    def test(self):
        with tmp() as d:
            r = run_tool("tune.py", *argv, cwd=d)
            self.assertEqual(os.listdir(d), [])
        self.assertEqual((r.returncode, r.stdout.strip(), r.stderr), (2, USAGE.strip(), ""))
    test.__name__ = "test_" + name
    return test


class TestCliSubprocess(unittest.TestCase):
    def test_the_usage_on_stdout_names_the_commands(self):
        with tmp() as d:
            r = run_tool("tune.py", cwd=d)
        self.assertEqual((r.returncode, r.stderr), (2, ""))
        for line in ("sounds       [--tune ID | --draft] [--car ID] [--work <dir>]", "sound-set    <slot> <key> [--tune ID | --draft] [--car ID] [--work <dir>]",
                     "sound-reset  [<slot>] [--tune ID | --draft] [--car ID] [--work <dir>]"):
            self.assertIn("python tools/tune.py " + line, r.stdout)


for _name, _argv in (("sounds_with_a_positional", ["sounds", "x"]), ("sounds_tune_with_draft", ["sounds", "--tune", "ax01", "--draft"]),
                     ("sounds_option_without_value", ["sounds", "--car"]), ("sound_set_without_operands", ["sound-set"]),
                     ("sound_set_with_one_operand", ["sound-set", "turbo"]), ("sound_set_with_three_operands", ["sound-set", "turbo", "a", "b"]),
                     ("sound_set_tune_with_draft", ["sound-set", "turbo", "a", "--tune", "ax01", "--draft"]),
                     ("sound_reset_with_two_operands", ["sound-reset", "turbo", "backfire"]),
                     ("sound_reset_tune_with_draft", ["sound-reset", "--tune", "ax01", "--draft"])):
    setattr(TestCliSubprocess, "test_usage_" + _name, usage_case(_name, _argv))


if __name__ == "__main__":
    unittest.main()
