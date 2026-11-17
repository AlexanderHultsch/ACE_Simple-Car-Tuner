"""Tests for the sound picker part of tools/tune.py: the "_sounds" state key, actor_path, sound_options, sound_own, sound_choices, set_sound, reset_sounds, the build with a saved choice and the commands sounds, sound-set and sound-reset (the pure functions are tested in tests/test_sounds.py).

No game data and no schemas: the cars are synthetic (support.FakeCar replaces tune.load_msg / save_msg with in-memory messages, one shared store for all fake cars; the .actor of a car is an in-memory ActorData object); the commands run in-process on those cars, and as a subprocess where nothing is read (usage). clone_car.build and kspkg.cmd_pack are stubbed for the build test.
"""
import contextlib
import io
import json
import os
import shutil
import unittest
from unittest import mock

from support import (BACKFIRE, BACKFIRE_BANK, BANK, TURBO, FakeCar, Sandbox, backfire, engine, entry, mini_catalogue, mini_setting, run_main,
                     run_tool, tmp, turbo, usage_cases)

import clone_car
import kspkg
import tune

USAGE = tune.__doc__.split("\n\n")[1]
KEY = tune.SOUND_KEY
REAL_RENAME = os.rename
T, B = TURBO, BACKFIRE
T_NONE, T_RX7 = T + "turbo_none", T + "turbo_rx7"
B_A, B_B, B_CLASSIC = B + "backfire_a", B + "backfire_b", B + "backfire_classic#8"


def actor(*entries):
    return {"car": {"cameras": ["c1"], "audio_events": list(entries), "_order": ["cameras"] + ["audio_events"] * len(entries)}}


def sound_cat():
    return mini_catalogue(
        mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix"),
        mini_setting("variant_name", kind="meta", type="string", default_template="{stock_variant_name}", handler="variant_name"),
        mini_setting("limiter", type="int", targets=[("@engine", "limiter")]))


class World(Sandbox):
    """Fake cars in one work folder: ks_x (the default car; own sounds turbo_none and backfire_a), ks_a (turbo_rx7, backfire_classic with
    optionalParam 8, the backfire entry first), ks_b (turbo_rx7, backfire_a, its actor file is named KS_B.ACTOR), ks_n (a backfire entry
    only: backfire_b), ks_u (an actor that cannot be decoded), ks_z (no actor file) and ks_q (only a build folder: not installed)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(tune._actor_options.clear)
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

    def state(self, tune_id=None, car_id="ks_x"):
        return tune.load_state(self.work, car_id, tune_id)

    @contextlib.contextmanager
    def loads(self):
        """The car ids of the files tune.load_msg decodes inside the block, in order."""
        found, real = [], tune.load_msg

        def counting(path):
            found.append(os.path.relpath(path, self.work).split(os.sep)[0])
            return real(path)

        with mock.patch.object(tune, "load_msg", counting):
            yield found

    def actor_key(self, car_id, name=None):
        return self.fakes[car_id].key(os.path.join(self.fakes[car_id].car_root, name or "%s.actor" % car_id))

    def touch(self, car_id, name=None):
        with open(os.path.join(self.fakes[car_id].car_root, name or "%s.actor" % car_id), "ab") as f:
            f.write(b"x")

    def keys(self, options):
        return {slot: [o["key"] for o in found] for slot, found in options.items()}

    def run_main(self, *argv):
        return run_main(tune.main, ["tune.py", *argv, "--work", self.work])


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
        self.assertEqual(self.state(res["id"]), {"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_B}, "name_suffix": "MY 2"})
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
        self.assertEqual(self.state(res["id"]), {"limiter": 9000, KEY: {"turbo": T_RX7}, "name_suffix": "MY"})
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


class TestSoundOptionsCache(World):
    def setUp(self):
        super().setUp()
        self.cold = tune.sound_options(self.work)

    def test_the_second_call_decodes_only_the_cars_that_failed_and_returns_an_equal_result(self):
        with self.loads() as warm:
            again = tune.sound_options(self.work)
        self.assertEqual((sorted(set(warm)), again), (["ks_u"], self.cold))

    def test_without_the_failing_cars_it_decodes_nothing(self):
        self.drop_cars("ks_u", "ks_z")
        options, skipped = tune.sound_options(self.work)
        with self.loads() as warm:
            self.assertEqual(tune.sound_options(self.work), (options, skipped))
        self.assertEqual(warm, [])

    def test_the_caller_gets_its_own_copy(self):
        options, skipped = tune.sound_options(self.work)
        options["turbo"][0]["cars"].append("zzz")
        options["backfire"].clear()
        skipped.clear()
        self.assertEqual(tune.sound_options(self.work), self.cold)

    def test_the_cached_audio_entries_are_not_shared_with_the_caller(self):
        found = tune.actor_sounds(self.work, "ks_x")
        found["car"]["audio_events"][0]["event"] = "changed"
        found["car"]["audio_events"].clear()
        self.assertEqual([e["event"] for e in tune.actor_sounds(self.work, "ks_x")["car"]["audio_events"]], [T_NONE, B_A])

    def test_a_changed_actor_file_is_read_again_and_only_that_car(self):
        self.fakes["ks_n"].store[self.actor_key("ks_n")] = actor(engine(), turbo("turbo_rx7"), backfire("backfire_a"))
        with self.loads() as warm:
            self.assertEqual(tune.sound_options(self.work), self.cold)
        self.assertEqual(sorted(set(warm)), ["ks_u"])
        self.touch("ks_n")
        with self.loads() as warm:
            options, _ = tune.sound_options(self.work)
        self.assertEqual((sorted(set(warm)), warm.count("ks_n")), (["ks_n", "ks_u"], 1))
        self.assertEqual([(o["key"], o["cars"]) for o in options["turbo"]], [(T_NONE, ["ks_x"]), (T_RX7, ["ks_a", "ks_b", "ks_n"])])
        self.assertEqual([(o["key"], o["cars"]) for o in options["backfire"]], [(B_A, ["ks_b", "ks_n", "ks_x"]), (B_CLASSIC, ["ks_a"])])

    def test_an_actor_file_of_another_name_is_read_again(self):
        old = os.path.join(self.fakes["ks_b"].car_root, "KS_B.ACTOR")
        os.rename(old, os.path.join(self.fakes["ks_b"].car_root, "ks_b.actor"))
        self.fakes["ks_b"].store[self.actor_key("ks_b")] = actor(engine(), turbo("turbo_none"))
        options, _ = tune.sound_options(self.work)
        self.assertEqual([(o["key"], o["cars"]) for o in options["turbo"]], [(T_NONE, ["ks_b", "ks_x"]), (T_RX7, ["ks_a"])])

    def test_forget_resolved_drops_the_options_of_that_car_only(self):
        tune.forget_resolved(self.work, "ks_a")
        with self.loads() as warm:
            tune.sound_options(self.work)
        self.assertEqual(sorted(set(warm)), ["ks_a", "ks_u"])

    def test_a_car_that_failed_is_never_cached(self):
        for _ in range(2):
            with self.loads() as warm:
                self.assertEqual([s["car"] for s in tune.sound_options(self.work)[1]], ["ks_u", "ks_z"])
            self.assertEqual(warm, ["ks_u"])
        self.fakes["ks_u"].store[self.actor_key("ks_u")] = actor(engine(), turbo("turbo_rx7"))
        options, skipped = tune.sound_options(self.work)
        self.assertEqual(([s["car"] for s in skipped], options["turbo"][1]["cars"]), (["ks_z"], ["ks_a", "ks_b", "ks_u"]))

    def test_a_car_that_cannot_be_stamped_is_not_cached(self):
        self.patch(tune, "stat_or_none", lambda path: None)
        with self.loads() as warm:
            self.assertEqual(tune.sound_options(self.work), self.cold)
        self.assertEqual(sorted(set(warm)), ["ks_a", "ks_b", "ks_n", "ks_u", "ks_x"])

    def drop_cars(self, *car_ids):
        for car_id in car_ids:
            shutil.rmtree(tune.base_dir(self.work, car_id))


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


class ApplySounds(Apply):
    """apply of ks_x with a sound choice. ks_x has the own sounds turbo_none and backfire_a; the built actor of the fake build is the
    renamed actor of ks_x, the donors are ks_a (turbo_rx7, backfire_classic#8) and ks_b (turbo_rx7, backfire_a)."""

    def put_actor(self, car_id, obj):
        fc = self.fakes[car_id]
        fc.store[fc.key(tune.actor_path(self.work, car_id))] = obj

    def built_actor(self, res):
        fc = self.fakes["ks_x"]
        return fc.store[fc.key(os.path.join(res["build_dir"], "content", "cars", res["new_id"], res["new_id"] + ".actor"))]

    def events(self, obj):
        return obj["car"]["audio_events"]

    def actors_saved(self):
        return [k for k in self.fakes["ks_x"].saved if k.lower().endswith(".actor")]

    def assertNothingBuilt(self):
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build")))

    def entry_of(self, obj, slot):
        return tune.sounds.slot_entries(obj, slot)[0][1]

    def key_of(self, obj, slot):
        return tune.sounds.option_of(self.entry_of(obj, slot))["key"]


class TestApplyWithoutAChange(ApplySounds):
    def test_without_the_key_nothing_of_the_sound_step_runs(self):
        self.patch(tune, "sound_plan", lambda *a, **k: self.fail("sound_plan"))
        self.patch(tune, "sound_options", lambda *a, **k: self.fail("sound_options"))
        res = self.apply({"limiter": 8000})
        self.assertEqual((res["sounds"], res["notes"], [a["id"] for a in res["applied"]]), ([], ["note: from build"], ["limiter"]))
        self.assertEqual(self.actors_saved(), [])

    def test_a_choice_equal_to_the_own_sounds_or_an_empty_one_builds_like_no_choice(self):
        plain = self.apply({"limiter": 8000})
        before = (self.snapshot(plain), plain["notes"], plain["applied"], self.packed[-1], plain["size"])
        for chosen in ({KEY: {"turbo": T_NONE, "backfire": B_A}}, {KEY: {"backfire": B_A}}, {KEY: {}}):
            with self.subTest(chosen):
                res = self.apply(dict(chosen, limiter=8000))
                self.assertEqual((self.snapshot(res), res["notes"], res["applied"], self.packed[-1], res["size"]), before)
                self.assertEqual(res["sounds"], [])
        self.assertEqual(self.actors_saved(), [])
        self.assertEqual(len(self.packed), 4)

    def test_the_state_file_is_not_touched_by_a_build(self):
        state = {"limiter": 8000, KEY: {"turbo": T_RX7}}
        self.apply(state)
        self.assertEqual(self.state(), state)

    def test_write_sounds_with_an_empty_plan_reads_nothing(self):
        self.assertEqual(tune.write_sounds(os.path.join(self.work, "nowhere"), "ax_x", []), [])


class TestApplyChanges(ApplySounds):
    def test_a_sound_choice_is_a_change_of_the_build_and_a_later_build_reports_what_differs(self):
        first = self.apply({KEY: {"turbo": T_RX7}})
        self.assertEqual(first["changes"], {"since": None, "settings": [], "total": 0, "extras": [
            {"kind": "sound", "slot": "turbo", "from": None, "to": T_RX7, "text": "Sound turbo: own sound -> turbo_rx7"}]})
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["sounds"], {"turbo": T_RX7})
        self.assertEqual(self.apply({KEY: {"turbo": T_RX7}})["changes"]["extras"], [])
        second = self.apply({KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        self.assertEqual(second["changes"]["extras"], [{"kind": "sound", "slot": "backfire", "from": None, "to": B_CLASSIC,
                                                        "text": "Sound backfire: own sound -> backfire_classic#8"}])
        third = self.apply({KEY: {"backfire": B_B}})
        self.assertEqual([e["text"] for e in third["changes"]["extras"]], ["Sound turbo: turbo_rx7 -> own sound", "Sound backfire: backfire_classic#8 -> backfire_b"])
        self.assertEqual(self.apply({})["changes"]["extras"][0]["text"], "Sound backfire: backfire_b -> own sound")
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["sounds"], {})

    def test_a_choice_equal_to_the_own_sound_is_no_change(self):
        self.apply({KEY: {"turbo": T_RX7}})
        res = self.apply({KEY: {"turbo": T_NONE}})
        self.assertEqual(res["changes"]["extras"], [{"kind": "sound", "slot": "turbo", "from": T_RX7, "to": None, "text": "Sound turbo: turbo_rx7 -> own sound"}])
        self.assertEqual(self.apply({KEY: {"turbo": T_NONE}})["changes"]["extras"], [])


class TestApplyChoice(ApplySounds):
    def test_turbo_only(self):
        res = self.apply({KEY: {"turbo": T_RX7}})
        self.assertEqual(res["sounds"], [{"slot": "turbo", "from": T_NONE, "to": T_RX7, "added": False}])
        self.assertEqual(res["notes"], ["note: from build", "note: sound turbo: %s -> %s" % (T_NONE, T_RX7)])
        built = self.built_actor(res)
        self.assertEqual((self.key_of(built, "turbo"), self.key_of(built, "backfire")), (T_RX7, B_A))
        self.assertEqual([os.path.basename(k) for k in self.actors_saved()], ["ax_x.actor"])

    def test_backfire_only_with_an_optional_param(self):
        res = self.apply({KEY: {"backfire": B_CLASSIC}})
        self.assertEqual(res["sounds"], [{"slot": "backfire", "from": B_A, "to": B_CLASSIC, "added": False}])
        self.assertEqual(res["notes"], ["note: from build", "note: sound backfire: %s -> %s" % (B_A, B_CLASSIC)])
        built = self.built_actor(res)
        self.assertEqual(self.entry_of(built, "backfire"), backfire("backfire_classic", optionalParam=8))
        self.assertEqual(self.key_of(built, "turbo"), T_NONE)

    def test_both_slots_in_the_order_turbo_then_backfire(self):
        res = self.apply({KEY: {"backfire": B_CLASSIC, "turbo": T_RX7}})
        self.assertEqual([(s["slot"], s["from"], s["to"], s["added"]) for s in res["sounds"]],
                         [("turbo", T_NONE, T_RX7, False), ("backfire", B_A, B_CLASSIC, False)])
        self.assertEqual(res["notes"], ["note: from build", "note: sound turbo: %s -> %s" % (T_NONE, T_RX7),
                                        "note: sound backfire: %s -> %s" % (B_A, B_CLASSIC)])
        built = self.built_actor(res)
        self.assertEqual((self.key_of(built, "turbo"), self.key_of(built, "backfire")), (T_RX7, B_CLASSIC))
        self.assertEqual(len(self.actors_saved()), 1)

    def test_a_slot_equal_to_the_own_sound_changes_nothing_and_the_other_one_is_applied(self):
        res = self.apply({KEY: {"turbo": T_NONE, "backfire": B_B}})
        self.assertEqual([s["slot"] for s in res["sounds"]], ["backfire"])
        self.assertEqual(res["notes"], ["note: from build", "note: sound backfire: %s -> %s" % (B_A, B_B)])
        self.assertEqual(self.key_of(self.built_actor(res), "turbo"), T_NONE)

    def test_only_the_entry_of_the_slot_changes_and_every_other_entry_and_field_stays(self):
        plain = self.built_actor(self.apply({"limiter": 8000}))
        res = self.apply({"limiter": 8000, KEY: {"turbo": T_RX7}})
        built = self.built_actor(res)
        self.assertEqual(len(self.events(built)), len(self.events(plain)))
        self.assertEqual([i for i, (a, b) in enumerate(zip(self.events(plain), self.events(built))) if a != b], [1])
        self.assertEqual(self.entry_of(built, "turbo"), dict(self.entry_of(plain, "turbo"), event=T_RX7))
        self.assertEqual({k: v for k, v in built["car"].items() if k != "audio_events"}, {k: v for k, v in plain["car"].items() if k != "audio_events"})

    def test_the_engine_entry_stays_as_the_clone_made_it(self):
        res = self.apply({KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        self.assertEqual(self.events(self.built_actor(res))[0], entry("event:/evo_cars/ax_x/engine_int", None, "content\\sfx\\ax_x.bank"))

    def test_a_choice_changes_no_other_file_of_the_build(self):
        plain = self.apply({"limiter": 8000})
        plain_view = (self.snapshot(plain), plain["applied"], self.packed[-1])
        chosen = self.apply({"limiter": 8000, KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})

        def without_actor(snap):
            return {k: v for k, v in snap.items() if not k.lower().endswith(".actor")}
        self.assertEqual((without_actor(self.snapshot(chosen)), chosen["applied"], self.packed[-1]),
                         (without_actor(plain_view[0]), plain_view[1], plain_view[2]))
        self.assertNotEqual(self.snapshot(chosen), plain_view[0])

    def test_a_plain_option_removes_the_optional_param_of_the_car(self):
        self.put_actor("ks_x", actor(engine(), turbo("turbo_none"), backfire("backfire_classic", optionalParam=8)))
        res = self.apply({KEY: {"backfire": B_A}})
        self.assertEqual(res["sounds"], [{"slot": "backfire", "from": B_CLASSIC, "to": B_A, "added": False}])
        self.assertEqual(self.entry_of(self.built_actor(res), "backfire"), backfire("backfire_a"))

    def test_a_car_without_a_turbo_entry_gets_one_with_the_transform_and_bank_of_the_first_donor(self):
        self.put_actor("ks_x", actor(engine(), backfire("backfire_a")))
        donor = turbo("turbo_rx7", transform={"scale": {"x": 2.5}}, bank="content\\sfx\\turbo_rx7.bank")
        self.put_actor("ks_a", actor(backfire("backfire_classic", optionalParam=8), engine(), donor))
        self.put_actor("ks_b", actor(engine(), turbo("turbo_rx7", transform={"scale": {"x": 7.0}}, bank="content\\sfx\\turbo_rx7.bank"), backfire("backfire_a")))
        res = self.apply({KEY: {"turbo": T_RX7}})
        self.assertEqual(res["sounds"], [{"slot": "turbo", "from": None, "to": T_RX7, "added": True}])
        self.assertEqual(res["notes"], ["note: from build", "note: sound turbo: - added %s" % T_RX7])
        built = self.built_actor(res)
        self.assertEqual(len(self.events(built)), 3)
        self.assertEqual(self.events(built)[2], donor)
        self.assertEqual(self.events(built)[:2], [entry("event:/evo_cars/ax_x/engine_int", None, "content\\sfx\\ax_x.bank"), backfire("backfire_a")])
        self.assertEqual(built["car"]["_order"], ["cameras"] + ["audio_events"] * 3)

    def test_an_appended_entry_with_an_optional_param_takes_the_option(self):
        self.put_actor("ks_x", actor(engine(), turbo("turbo_none")))
        res = self.apply({KEY: {"backfire": B_CLASSIC}})
        self.assertEqual(res["sounds"], [{"slot": "backfire", "from": None, "to": B_CLASSIC, "added": True}])
        self.assertEqual(self.events(self.built_actor(res))[2], backfire("backfire_classic", optionalParam=8))

    def test_the_actor_of_the_build_is_found_whatever_its_case(self):
        folder = os.path.join(self.work, "built", "ax_x")
        os.makedirs(folder)
        path = os.path.join(folder, "AX_X.ACTOR")
        with open(path, "wb"):
            pass
        fc = self.fakes["ks_x"]
        fc.store[fc.key(path)] = actor(engine(), turbo("turbo_none"))
        option = {"key": T_RX7, "event": T_RX7, "bank": BANK, "optional": None, "cars": ["ks_a"]}
        changed = tune.write_sounds(folder, "ax_x", [{"slot": "turbo", "option": option, "template": turbo("turbo_rx7")}])
        self.assertEqual(changed, [{"slot": "turbo", "from": T_NONE, "to": T_RX7, "added": False}])
        self.assertEqual(fc.saved, [fc.key(path)])
        self.assertEqual(self.entry_of(fc.store[fc.key(path)], "turbo")["event"], T_RX7)

    def test_a_second_apply_starts_from_the_base_again(self):
        first = self.apply({KEY: {"turbo": T_RX7}})
        again = self.apply({KEY: {"turbo": T_RX7}})
        self.assertEqual((self.snapshot(again), again["notes"], again["sounds"]), (self.snapshot(first), first["notes"], first["sounds"]))
        plain = self.apply({})
        self.assertEqual(self.key_of(self.built_actor(plain), "turbo"), T_NONE)
        self.assertEqual(plain["sounds"], [])

    def test_the_plan_names_the_slot_option_and_template_and_leaves_out_the_own_sound(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7, "backfire": B_A}})
        plan = tune.apply_plan(self.work, "ks_x", "ax_x", False, None, self.cat)["sounds"]
        self.assertEqual([p["slot"] for p in plan], ["turbo"])
        self.assertEqual((plan[0]["option"]["key"], plan[0]["option"]["cars"], plan[0]["template"]), (T_RX7, ["ks_a", "ks_b"], turbo("turbo_rx7")))


class TestApplyRefusals(ApplySounds):
    def test_a_saved_sound_that_is_no_option_any_more_refuses_before_anything_is_built(self):
        message = "^the saved turbo sound %s is no longer available \\(the car that had it is not installed\\), change or reset it$"
        with self.assertRaisesRegex(ValueError, message % (T + "turbo_gone")):
            self.apply({KEY: {"turbo": T + "turbo_gone"}})
        self.assertNothingBuilt()

    def test_a_key_of_the_other_slot_refuses(self):
        with self.assertRaisesRegex(ValueError, "^the saved turbo sound %s is no longer available" % B_B):
            self.apply({KEY: {"turbo": B_B}})
        self.assertNothingBuilt()

    def test_the_car_that_had_the_sound_is_not_installed_any_more(self):
        tune.set_sound(self.work, "ks_x", "turbo", T_RX7)
        for car_id in ("ks_a", "ks_b"):
            shutil.rmtree(os.path.join(self.work, car_id, "base"))
        with self.assertRaisesRegex(ValueError, "^the saved turbo sound %s is no longer available" % T_RX7):
            self.apply(self.state())
        self.assertNothingBuilt()

    def test_a_refused_apply_leaves_the_previous_build_alone(self):
        first = self.apply({KEY: {"turbo": T_RX7}})
        with open(first["package"], "rb") as f:
            before = (self.snapshot(first), f.read(), len(self.calls))
        with self.assertRaisesRegex(ValueError, "is no longer available"):
            self.apply({KEY: {"turbo": T_RX7, "backfire": B + "backfire_gone"}})
        with open(first["package"], "rb") as f:
            self.assertEqual((self.snapshot(first), f.read(), len(self.calls)), before)
        self.assertFalse(os.path.exists(first["build_dir"] + ".partial"))

    def test_the_check_does_not_write_into_a_stale_partial_folder(self):
        stale = os.path.join(self.work, "ks_x", "build", "ax_x.partial", "stale.bin")
        self.write(stale, "x")
        with self.assertRaises(ValueError):
            self.apply({KEY: {"turbo": T + "turbo_gone"}})
        self.assertTrue(os.path.isfile(stale))

    def test_a_slot_that_does_not_exist_refuses(self):
        with self.assertRaisesRegex(ValueError, "^unknown sound slot 'horn', use one of: turbo, backfire$"):
            self.apply({KEY: {"horn": "event:/h", "turbo": T_RX7}})
        self.assertNothingBuilt()

    def test_a_damaged_choice_refuses_with_the_message_of_the_other_commands(self):
        for bad in ([], "turbo", 5, {"turbo": 5}):
            with self.subTest(repr(bad)):
                with self.assertRaisesRegex(ValueError, "^damaged sound choice in the saved state$"):
                    self.apply({KEY: bad})
                self.assertNothingBuilt()

    def test_a_car_whose_own_actor_cannot_be_read_refuses(self):
        self.put_actor("ks_x", ValueError("cannot decode"))
        with self.assertRaisesRegex(ValueError, "^cannot decode$"):
            self.apply({KEY: {"turbo": T_RX7}})
        self.assertNothingBuilt()


class TestApplyFromTheDraft(ApplySounds):
    def apply_tune(self, new_id):
        return tune.apply(self.work, "ks_x", new_id, install=False, catalogue=self.cat, game=self.game)

    def test_create_from_the_draft_applies_the_sounds_of_the_draft(self):
        tune.save_state(self.work, "ks_x", {"limiter": 9000, KEY: {"turbo": T_RX7, "backfire": B_B}}, tune.DRAFT)
        created = tune.new_tune_from_draft(self.work, "ks_x")
        self.assertEqual(self.state(created["id"])[KEY], {"turbo": T_RX7, "backfire": B_B})
        res = self.apply_tune(created["id"])
        self.assertEqual([(s["slot"], s["to"]) for s in res["sounds"]], [("turbo", T_RX7), ("backfire", B_B)])
        built = self.built_actor(res)
        self.assertEqual((self.key_of(built, "turbo"), self.key_of(built, "backfire")), (T_RX7, B_B))
        self.assertEqual(self.state(tune.DRAFT)[KEY], {"turbo": T_RX7, "backfire": B_B})

    def test_a_duplicate_builds_the_sounds_of_its_source_and_the_source_keeps_its_own(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}})
        copied = tune.duplicate_tune(self.work, "ks_x", None)
        self.assertEqual(self.apply_tune(copied["id"])["sounds"][0]["to"], T_RX7)
        tune.set_sound(self.work, "ks_x", "turbo", None, copied["id"])
        self.assertEqual(self.apply_tune(copied["id"])["sounds"], [])
        self.assertEqual(self.apply_tune(None)["sounds"][0]["to"], T_RX7)

    def test_the_draft_is_not_built_into_a_tune_without_the_key(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7}}, tune.DRAFT)
        self.assertEqual(self.apply({"limiter": 8000})["sounds"], [])


class TestApplyCommand(ApplySounds):
    def test_the_command_prints_the_sound_notes(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        with mock.patch.object(tune, "game_running", lambda: False):
            code, out, err = self.run_main("apply", "--no-install")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("first build of this car: 0 changed settings compared to the stock car\n  Sound turbo: own sound -> turbo_rx7\n"
                      "  Sound backfire: own sound -> backfire_classic#8\n"
                      "note: from build\nnote: sound turbo: %s -> %s\nnote: sound backfire: %s -> %s\n" % (T_NONE, T_RX7, B_A, B_CLASSIC), out)
        self.assertNotIn("_sounds", out)

    def test_a_vanished_sound_is_an_error_line_with_exit_1_and_nothing_is_built(self):
        tune.save_state(self.work, "ks_x", {KEY: {"turbo": T + "turbo_gone"}})
        with mock.patch.object(tune, "game_running", lambda: False):
            code, out, err = self.run_main("apply", "--no-install")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: the saved turbo sound %s is no longer available" % (T + "turbo_gone")), err)
        self.assertEqual(self.calls, [])

    def test_the_server_lines_name_the_notes(self):
        import tuner_server
        res = self.apply({KEY: {"turbo": T_RX7}})
        self.assertIn("note: sound turbo: %s -> %s" % (T_NONE, T_RX7), tuner_server.apply_lines(res))


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


class TestCliSubprocess(unittest.TestCase):
    def test_the_usage_on_stdout_names_the_commands(self):
        with tmp() as d:
            r = run_tool("tune.py", cwd=d)
        self.assertEqual((r.returncode, r.stderr), (2, ""))
        for line in ("sounds       [--tune ID | --draft] [--car ID] [--work <dir>]", "sound-set    <slot> <key> [--tune ID | --draft] [--car ID] [--work <dir>]",
                     "sound-reset  [<slot>] [--tune ID | --draft] [--car ID] [--work <dir>]"):
            self.assertIn("python tools/tune.py " + line, r.stdout)


usage_cases(TestCliSubprocess, USAGE, (("sounds_with_a_positional", ["sounds", "x"]), ("sounds_tune_with_draft", ["sounds", "--tune", "ax01", "--draft"]),
                                       ("sounds_option_without_value", ["sounds", "--car"]), ("sound_set_without_operands", ["sound-set"]),
                                       ("sound_set_with_one_operand", ["sound-set", "turbo"]), ("sound_set_with_three_operands", ["sound-set", "turbo", "a", "b"]),
                                       ("sound_set_tune_with_draft", ["sound-set", "turbo", "a", "--tune", "ax01", "--draft"]),
                                       ("sound_reset_with_two_operands", ["sound-reset", "turbo", "backfire"]),
                                       ("sound_reset_tune_with_draft", ["sound-reset", "--tune", "ax01", "--draft"])), tune, check_empty=True)


if __name__ == "__main__":
    unittest.main()
