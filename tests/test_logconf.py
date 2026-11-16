"""Tests for tools/logconf.py and tuner/log_channels.json: the channel table against the real catalogue and the known channel names, its validator, the saved choice (log_config.json), the tree of the Logging tab, the selected channels, the session list and the logger status.

No game and no game data: the sessions and the status file are written by the tests into scratch folders; the real work folder, logs folder and game folder are never touched.
"""
import copy
import json
import os
import time
import unittest

from support import ROOT, tmp

import ace_shm
import logconf
import tune

CHANNELS_FILE = ROOT / "tuner" / "log_channels.json"
CAT = tune.load_catalogue()
RAW = tune.read_json(CHANNELS_FILE)
CHAN = logconf.load_channels()
KNOWN = set(ace_shm.channels(b"", b""))

DIRECT = {
    "display_power_ps": ("bhp torque", "bhp torque rpm gas"),
    "display_torque_nm": ("bhp torque", "bhp torque rpm gas"),
    "limiter": ("rpm_max", "rpm"),
    "idle_rpm": ("rpm", "rpm gas"),
    "turbo_boost_1": ("boost_max", "boost rpm gas"),
    "turbo_boost_2": ("boost_max", "boost rpm gas"),
    "max_turbo_boost": ("boost_max", "boost rpm gas"),
    "diff_power_default": ("diff_power_level diff_coast_level diff_power_pct diff_coast_pct",
                           "diff_power_pct diff_coast_pct wheel_speed slip_ratio"),
    "diff_coast_default": ("diff_power_level diff_coast_level diff_power_pct diff_coast_pct",
                           "diff_power_pct diff_coast_pct wheel_speed slip_ratio"),
    "diff_power_max": ("electronics_max", "diff_power_pct diff_coast_pct wheel_speed slip_ratio"),
    "diff_coast_max": ("electronics_max", "diff_power_pct diff_coast_pct wheel_speed slip_ratio"),
    "steer_lock_deg": ("", "steer steer_deg angular_vel"),
    "brake_bias": ("brake_bias", "brake_bias"),
    "brake_bias_hw": ("brake_bias", "brake_bias"),
    "brake_bias_min": ("electronics_min electronics_max", "brake_bias"),
    "brake_bias_max": ("electronics_min electronics_max", "brake_bias"),
    "brake_torque": ("brake_torque", "brake_torque brake brake_temp acc_g"),
    "car_mass": ("wheel_load", "wheel_load"),
    "ride_height_front": ("ride_height", "ride_height susp_travel"),
    "ride_height_rear": ("ride_height", "ride_height susp_travel"),
    "camber_front": ("camber_deg", "camber_deg slip_angle_deg wheel_load"),
    "camber_rear": ("camber_deg", "camber_deg slip_angle_deg wheel_load"),
    "tyre_pressure_front": ("tyre_pressure_psi", "tyre_pressure_psi tyre_temp_core"),
    "tyre_pressure_rear": ("tyre_pressure_psi", "tyre_pressure_psi tyre_temp_core"),
    "fuel_start": ("fuel_l fuel_max_l", "fuel_l"),
    "tc_level": ("tc_level tc_cut_level abs_level esc_level engine_map", "tc_active abs_active esc_active slip_ratio"),
    "tc2_level": ("tc_level tc_cut_level abs_level esc_level engine_map", "tc_active abs_active esc_active slip_ratio"),
    "abs_level": ("tc_level tc_cut_level abs_level esc_level engine_map", "tc_active abs_active esc_active slip_ratio"),
    "driver_aids_off": ("tc_level tc_cut_level abs_level esc_level engine_map", "tc_active abs_active esc_active slip_ratio"),
}
NONE = {"variant_name", "name_suffix", "handbrake_torque", "caster_front", "toe_front", "toe_rear", "toe_min", "toe_max",
        "camber_min_front", "camber_max_front", "camber_min_rear", "camber_max_rear", "tyre_pressure_min", "tyre_pressure_max",
        "spring_min_front", "spring_max_front", "spring_min_rear", "spring_max_rear", "arb_min_front", "arb_max_front",
        "arb_min_rear", "arb_max_rear", "collar_front", "collar_rear"}
ENGINE_HINT = "rpm, gas, bhp, torque"
SPRING_HINT = "susp_travel, wheel_load, roll_deg, pitch_deg"
DAMPER_HINT = "susp_travel, roll_deg, pitch_deg, acc_g"
HINTS = {"Engine": ENGINE_HINT, "Gearbox & clutch": "gear, rpm, speed_kmh, wheel_speed", "Differential": "wheel_speed, slip_ratio",
         "Differential (hardware)": "wheel_speed, slip_ratio", "Steering": "steer, steer_deg, angular_vel",
         "Springs & anti-roll": SPRING_HINT, "Ride height & bump stops": "susp_travel, wheel_load", "Dampers": DAMPER_HINT,
         "Tyres": "slip_angle_deg, slip_ratio, wheel_load, acc_g, tyre_temp_core"}
DEFAULT_ROWS = ["speed", "rpm"]
BEHAVIOUR = {"speed": ["speed_kmh"], "rpm": ["rpm"], "gear": ["gear"], "gas": ["gas"], "brake": ["brake"],
             "steering": ["steer", "steer_deg"], "g_forces": ["acc_g", "g_forces"],
             "rotation": ["angular_vel", "pitch_deg", "roll_deg", "heading_deg"], "wheel_load": ["wheel_load"],
             "slip": ["slip_angle_deg", "slip_ratio"], "susp_travel": ["susp_travel"],
             "tyre_temps": ["tyre_temp_core", "tyre_temp_in", "tyre_temp_mid", "tyre_temp_out"], "brake_temp": ["brake_temp"]}
CAR_STATE = {"tyre_compounds": ("tyre_compound_front tyre_compound_rear", "tyre_compound_front tyre_compound_rear"),
             "turbo": ("turbo_level boost_max", "boost turbo_level"),
             "damper_levels": ("damper_levels", "damper_levels"),
             "engine_brake": ("engine_brake ebb_level", "engine_brake ebb_level"),
             "engine_map": ("engine_map performance_mode performance_mode_name", "engine_map performance_mode performance_mode_name"),
             "electronics_limits": ("electronics_min electronics_max electronics_modifiable", ""),
             "gears_fuel": ("max_gears fuel_max_l", ""),
             "mass_balance": ("cg_height ballast", ""),
             "brake_wear": ("pad_life disc_life front_brake_compound rear_brake_compound",
                            "pad_life disc_life front_brake_compound rear_brake_compound")}


def changed(mutate):
    """A copy of the real channel table after mutate(copy)."""
    chan = copy.deepcopy(RAW)
    mutate(chan)
    return chan


def row_of(chan, group, row):
    return next(r for g in chan["extra_groups"] if g["id"] == group for r in g["rows"] if r["id"] == row)


def group_of(chan, group):
    return next(g for g in chan["extra_groups"] if g["id"] == group)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else (data if isinstance(data, str) else json.dumps(data)).encode("utf-8"))
    return path


class TestChannelTable(unittest.TestCase):
    def test_the_real_table_validates_against_the_real_catalogue(self):
        logconf.validate_channels(RAW, CAT)
        self.assertEqual(logconf.load_channels(), RAW)
        self.assertEqual(RAW["version"], 1)

    def test_the_file_is_the_one_next_to_the_catalogue(self):
        self.assertEqual(logconf.CHANNELS, tune.CATALOGUE.parent / "log_channels.json")
        self.assertEqual(logconf.CHANNELS, CHANNELS_FILE)

    def test_every_catalogue_setting_is_in_the_table_in_catalogue_order(self):
        self.assertEqual(list(RAW["settings"]), [s["id"] for s in CAT["settings"]])
        self.assertEqual(len(RAW["settings"]), 143)

    def test_exactly_these_29_settings_are_direct(self):
        direct = [i for i, e in RAW["settings"].items() if e["status"] == "direct"]
        self.assertEqual(len(DIRECT), 29)
        self.assertEqual(set(direct), set(DIRECT))
        self.assertEqual(len(direct), 29)

    def test_the_channels_of_every_direct_setting(self):
        for sid, (once, live) in DIRECT.items():
            with self.subTest(sid):
                self.assertEqual((RAW["settings"][sid]["once"], RAW["settings"][sid]["live"]), (once.split(), live.split()))

    def test_exactly_these_settings_are_none(self):
        none = {i for i, e in RAW["settings"].items() if e["status"] == "none"}
        self.assertEqual(len(NONE), 24)
        self.assertEqual(none, NONE)
        for sid in NONE:
            self.assertEqual(RAW["settings"][sid]["note"], "not published by the game", sid)

    def test_every_other_setting_is_indirect(self):
        indirect = {i for i, e in RAW["settings"].items() if e["status"] == "indirect"}
        self.assertEqual(indirect, set(RAW["settings"]) - set(DIRECT) - NONE)
        self.assertEqual(len(indirect), 90)

    def test_every_non_direct_entry_has_no_channels_and_a_note(self):
        for sid, e in RAW["settings"].items():
            if e["status"] != "direct":
                with self.subTest(sid):
                    self.assertEqual((e["once"], e["live"]), ([], []))
                    self.assertTrue(e["note"].strip())

    def test_the_hint_of_an_indirect_note_follows_the_group_of_the_setting(self):
        for s in CAT["settings"]:
            e = RAW["settings"][s["id"]]
            if e["status"] != "indirect":
                continue
            if s["id"] == "clutch_max_torque":
                hint = ENGINE_HINT
            elif s["group"] == "Suspension (physical)":
                hint = DAMPER_HINT if s["id"].startswith("coilover_damper") else SPRING_HINT
            else:
                hint = HINTS[s["group"]]
            with self.subTest(s["id"]):
                self.assertEqual(e["note"], "only its effect is visible: " + hint)

    def test_every_channel_name_is_a_name_ace_shm_returns(self):
        used = set()
        for e in RAW["settings"].values():
            used.update(e["once"] + e["live"])
        for g in RAW["extra_groups"]:
            for r in g["rows"]:
                used.update(r["once"] + r["live"])
        self.assertEqual(sorted(used - KNOWN), [])
        self.assertGreater(len(used), 40)

    def test_the_extra_groups(self):
        self.assertEqual([g["id"] for g in RAW["extra_groups"]], ["behaviour", "car_state"])
        behaviour, car_state = RAW["extra_groups"]
        self.assertEqual((behaviour["name"], car_state["name"]), ("Behaviour values", "Car state"))
        self.assertEqual([r["id"] for r in behaviour["rows"]], list(BEHAVIOUR))
        for r in behaviour["rows"]:
            with self.subTest(r["id"]):
                self.assertEqual((r["once"], r["live"]), ([], BEHAVIOUR[r["id"]]))
        self.assertEqual([r["id"] for r in car_state["rows"]], list(CAR_STATE))
        for r in car_state["rows"]:
            with self.subTest(r["id"]):
                self.assertEqual((r["once"], r["live"]), tuple(c.split() for c in CAR_STATE[r["id"]]))
        for g in RAW["extra_groups"]:
            self.assertTrue(g["description"].strip())
            for r in g["rows"]:
                self.assertTrue(r["label"].strip() and r["description"].strip(), r["id"])

    def test_the_default_is_set_per_row_and_only_speed_and_rpm_are_ticked_by_default(self):
        for g in RAW["extra_groups"]:
            self.assertNotIn("default", g, g["id"])
            for r in g["rows"]:
                with self.subTest((g["id"], r["id"])):
                    self.assertIs(r["default"], g["id"] == "behaviour" and r["id"] in DEFAULT_ROWS)
        self.assertEqual([r["id"] for r in group_of(RAW, "behaviour")["rows"] if r["default"]], DEFAULT_ROWS)
        self.assertFalse(any(r["default"] for r in group_of(RAW, "car_state")["rows"]))

    def test_the_words_not_a_tuner_setting_are_nowhere_in_the_table(self):
        self.assertNotIn("not a tuner setting", CHANNELS_FILE.read_text(encoding="utf-8").lower())
        for g in RAW["extra_groups"]:
            self.assertNotIn("tuner setting", g["name"] + g["description"])
            for r in g["rows"]:
                self.assertNotIn("tuner setting", r["label"] + r["description"])

    def test_a_catalogue_setting_without_an_entry_fails_the_validation(self):
        cat = copy.deepcopy(CAT)
        cat["settings"].append(dict(cat["settings"][0], id="fake_new_setting"))
        with self.assertRaisesRegex(ValueError, "fake_new_setting"):
            logconf.validate_channels(RAW, cat)

    def test_an_entry_that_is_not_a_catalogue_setting_fails_the_validation(self):
        cat = copy.deepcopy(CAT)
        cat["settings"] = [s for s in cat["settings"] if s["id"] != "limiter"]
        with self.assertRaisesRegex(ValueError, "limiter"):
            logconf.validate_channels(RAW, cat)


class TestValidateChannels(unittest.TestCase):
    def fails(self, chan, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            logconf.validate_channels(chan, CAT)

    def test_it_needs_an_object(self):
        self.fails([], "expected an object")
        self.fails(None, "expected an object")

    def test_the_version_must_be_1(self):
        for version in (2, 0, "1", 1.0, True, None):
            with self.subTest(version):
                self.fails(changed(lambda c: c.update(version=version)), "version must be 1")
        self.fails(changed(lambda c: c.pop("version")), "version must be 1")

    def test_settings_must_be_an_object(self):
        self.fails(changed(lambda c: c.update(settings=[])), "needs settings")
        self.fails(changed(lambda c: c.pop("settings")), "needs settings")

    def test_a_missing_setting_is_named(self):
        self.fails(changed(lambda c: c["settings"].pop("limiter")), "limiter .*no entry")

    def test_an_extra_setting_is_named(self):
        self.fails(changed(lambda c: c["settings"].update(bogus_id=dict(c["settings"]["limiter"]))), "bogus_id .*not a setting")

    def test_an_entry_must_be_an_object(self):
        self.fails(changed(lambda c: c["settings"].update(limiter=[])), "setting limiter: expected an object")

    def test_the_status_must_be_one_of_the_three(self):
        for status in ("extra", "Direct", "", None, 1):
            with self.subTest(status):
                self.fails(changed(lambda c: c["settings"]["limiter"].update(status=status)), "setting limiter: status must be one of")

    def test_the_note_must_be_text(self):
        self.fails(changed(lambda c: c["settings"]["limiter"].update(note=None)), "setting limiter: note must be text")

    def test_a_direct_setting_needs_a_channel_in_once_or_live(self):
        self.fails(changed(lambda c: c["settings"]["limiter"].update(once=[], live=[])), "limiter: a direct setting needs at least one channel")

    def test_a_direct_setting_with_only_once_or_only_live_is_valid(self):
        logconf.validate_channels(changed(lambda c: c["settings"]["limiter"].update(once=["rpm_max"], live=[])), CAT)
        logconf.validate_channels(changed(lambda c: c["settings"]["limiter"].update(once=[], live=["rpm"])), CAT)

    def test_an_indirect_or_none_setting_has_no_channels(self):
        for sid in ("power_scale", "toe_front"):
            for key in ("once", "live"):
                with self.subTest((sid, key)):
                    self.fails(changed(lambda c: c["settings"][sid].update({key: ["rpm"]})), "setting %s: .*has no channels" % sid)

    def test_an_indirect_or_none_setting_needs_a_note(self):
        for sid in ("power_scale", "toe_front"):
            for note in ("", "  "):
                with self.subTest((sid, note)):
                    self.fails(changed(lambda c: c["settings"][sid].update(note=note)), "setting %s: .*needs a note" % sid)

    def test_a_direct_setting_may_have_an_empty_note(self):
        logconf.validate_channels(changed(lambda c: c["settings"]["limiter"].update(note="")), CAT)

    def test_an_unknown_channel_is_named(self):
        self.fails(changed(lambda c: c["settings"]["limiter"].update(once=["rpm_maxx"])), "setting limiter: unknown channel 'rpm_maxx' in once")
        self.fails(changed(lambda c: c["settings"]["limiter"].update(live=["rpm", "nope"])), "setting limiter: unknown channel 'nope' in live")

    def test_once_and_live_must_be_lists_of_text(self):
        for key in ("once", "live"):
            for value in ("rpm", None, ["rpm", 1], [["rpm"]], {"rpm": 1}):
                with self.subTest((key, value)):
                    self.fails(changed(lambda c: c["settings"]["limiter"].update({key: value})), "limiter: %s must be a list of channel names" % key)

    def test_once_and_live_must_not_repeat_a_channel(self):
        for key in ("once", "live"):
            with self.subTest(key):
                self.fails(changed(lambda c: c["settings"]["limiter"].update({key: ["rpm", "rpm"]})), "limiter: %s lists a channel twice" % key)

    def test_extra_groups_must_be_a_list(self):
        self.fails(changed(lambda c: c.update(extra_groups={})), "needs extra_groups")
        self.fails(changed(lambda c: c.pop("extra_groups")), "needs extra_groups")

    def test_an_extra_group_needs_an_id(self):
        self.fails(changed(lambda c: c["extra_groups"][0].pop("id")), "every extra group needs an id")
        self.fails(changed(lambda c: c["extra_groups"].append("behaviour")), "every extra group needs an id")

    def test_extra_group_ids_must_be_unique(self):
        self.fails(changed(lambda c: c["extra_groups"][1].update(id="behaviour")), "extra group behaviour: the id is used twice")

    def test_an_extra_group_needs_a_name_as_text(self):
        for name in ("", "  ", None, 3):
            with self.subTest(name):
                self.fails(changed(lambda c: c["extra_groups"][0].update(name=name)), "extra group behaviour: needs a name")

    def test_an_extra_group_must_not_have_a_default_of_its_own(self):
        for default in (True, False, "true", 1, None):
            with self.subTest(default):
                self.fails(changed(lambda c: c["extra_groups"][0].update(default=default)), "extra group behaviour: default is not allowed")

    def test_the_default_of_an_extra_row_must_be_a_bool(self):
        for default in ("true", "false", 1, 0, None, []):
            with self.subTest(default):
                self.fails(changed(lambda c: row_of(c, "behaviour", "speed").update(default=default)),
                           "extra group behaviour: row speed: default must be true or false")
                self.fails(changed(lambda c: row_of(c, "car_state", "turbo").update(default=default)),
                           "extra group car_state: row turbo: default must be true or false")
        self.fails(changed(lambda c: row_of(c, "behaviour", "speed").pop("default")), "row speed: default must be true or false")
        self.fails(changed(lambda c: row_of(c, "car_state", "brake_wear").pop("default")), "row brake_wear: default must be true or false")

    def test_a_row_may_default_to_true_or_false_in_any_group(self):
        logconf.validate_channels(changed(lambda c: row_of(c, "car_state", "turbo").update(default=True)), CAT)
        logconf.validate_channels(changed(lambda c: row_of(c, "behaviour", "speed").update(default=False)), CAT)

    def test_the_description_of_an_extra_group_must_be_text(self):
        self.fails(changed(lambda c: c["extra_groups"][0].update(description=None)), "extra group behaviour: description must be text")

    def test_the_rows_of_an_extra_group_must_be_a_list(self):
        self.fails(changed(lambda c: c["extra_groups"][0].update(rows={})), "extra group behaviour: needs rows")

    def test_an_extra_row_needs_an_id(self):
        self.fails(changed(lambda c: group_of(c, "behaviour")["rows"][0].pop("id")), "behaviour: every row needs an id")

    def test_row_ids_must_be_unique_within_a_group(self):
        self.fails(changed(lambda c: group_of(c, "behaviour")["rows"][1].update(id="speed")), "behaviour: row speed: the id is used twice")

    def test_the_same_row_id_in_two_groups_is_valid(self):
        logconf.validate_channels(changed(lambda c: group_of(c, "car_state")["rows"][0].update(id="speed")), CAT)

    def test_an_extra_row_needs_a_label_as_text(self):
        for label in ("", " ", None, 5):
            with self.subTest(label):
                self.fails(changed(lambda c: row_of(c, "behaviour", "speed").update(label=label)), "row speed: needs a label")

    def test_the_description_of_an_extra_row_must_be_text(self):
        self.fails(changed(lambda c: row_of(c, "behaviour", "speed").update(description=3)), "row speed: description must be text")

    def test_an_unknown_channel_in_an_extra_row_is_named(self):
        self.fails(changed(lambda c: row_of(c, "behaviour", "speed").update(live=["speed_kmhh"])), "row speed: unknown channel 'speed_kmhh' in live")
        self.fails(changed(lambda c: row_of(c, "car_state", "turbo").update(once=["x"])), "row turbo: unknown channel 'x' in once")

    def test_once_and_live_of_an_extra_row_must_be_lists_of_unique_text(self):
        self.fails(changed(lambda c: row_of(c, "behaviour", "speed").update(live="speed_kmh")), "row speed: live must be a list")
        self.fails(changed(lambda c: row_of(c, "behaviour", "speed").update(live=["rpm", "rpm"])), "row speed: live lists a channel twice")


class TestLoadChannels(unittest.TestCase):
    def test_it_reads_the_file_at_the_given_path_and_validates_it(self):
        with tmp() as d:
            path = write(str(d / "c.json"), RAW)
            self.assertEqual(logconf.load_channels(path), RAW)
            bad = write(str(d / "bad.json"), changed(lambda c: c["settings"].pop("limiter")))
            with self.assertRaisesRegex(ValueError, "limiter"):
                logconf.load_channels(bad)
            broken = write(str(d / "broken.json"), "{not json")
            with self.assertRaises(ValueError):
                logconf.load_channels(broken)

    def test_a_missing_file_is_an_os_error(self):
        with tmp() as d, self.assertRaises(OSError):
            logconf.load_channels(str(d / "none.json"))


class TestTickableIds(unittest.TestCase):
    def test_direct_settings_in_catalogue_order_then_the_extra_rows(self):
        ids = logconf.tickable_ids(CHAN)
        order = [s["id"] for s in CAT["settings"] if s["id"] in DIRECT]
        self.assertEqual(ids[:29], order)
        self.assertEqual(ids[29:], ["behaviour." + r for r in BEHAVIOUR] + ["car_state." + r for r in CAR_STATE])
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_greyed_setting_is_not_tickable(self):
        ids = logconf.tickable_ids(CHAN)
        for sid in ("gear_1", "toe_front", "variant_name", "handbrake_torque"):
            self.assertNotIn(sid, ids)


class TestDefaultConfig(unittest.TestCase):
    def test_it_is_30_hz_with_the_rows_whose_default_is_true(self):
        config = logconf.default_config(CHAN)
        self.assertEqual(config, {"version": 1, "rate_hz": 30, "ticked": ["behaviour.speed", "behaviour.rpm"]})
        self.assertFalse(any(i.startswith("car_state.") for i in config["ticked"]))
        logconf.validate_config(config, CHAN)

    def test_a_row_that_defaults_to_false_adds_nothing_and_the_ticked_rows_follow_the_table_order(self):
        chan = changed(lambda c: (row_of(c, "behaviour", "speed").update(default=False), row_of(c, "car_state", "turbo").update(default=True),
                                  row_of(c, "car_state", "brake_wear").update(default=True), row_of(c, "behaviour", "gas").update(default=True)))
        self.assertEqual(logconf.default_config(chan)["ticked"], ["behaviour.rpm", "behaviour.gas", "car_state.turbo", "car_state.brake_wear"])
        self.assertEqual(logconf.default_config(chan)["ticked"], [i for i in logconf.tickable_ids(chan) if i in logconf.default_config(chan)["ticked"]])

    def test_a_table_without_a_default_row_ticks_nothing(self):
        chan = changed(lambda c: [r.update(default=False) for g in c["extra_groups"] for r in g["rows"]])
        self.assertEqual(logconf.default_config(chan), {"version": 1, "rate_hz": 30, "ticked": []})

    def test_a_saved_file_stays_as_saved_and_does_not_get_the_default_rows_added(self):
        with tmp() as d:
            work = str(d / "work")
            write(logconf.config_path(work), {"version": 1, "rate_hz": 60, "ticked": ["car_state.turbo"]})
            self.assertEqual(logconf.load_config(work, CHAN), {"version": 1, "rate_hz": 60, "ticked": ["car_state.turbo"]})

    def test_every_call_returns_a_new_object(self):
        a = logconf.default_config(CHAN)
        a["ticked"].append("x")
        self.assertNotIn("x", logconf.default_config(CHAN)["ticked"])


class TestValidateConfig(unittest.TestCase):
    def ok(self, **more):
        return dict({"version": 1, "rate_hz": 30, "ticked": ["limiter", "behaviour.speed"]}, **more)

    def fails(self, config, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            logconf.validate_config(config, CHAN)

    def test_a_valid_config_passes(self):
        logconf.validate_config(self.ok(), CHAN)
        logconf.validate_config(self.ok(rate_hz=60, ticked=[]), CHAN)
        logconf.validate_config(self.ok(ticked=logconf.tickable_ids(CHAN)), CHAN)

    def test_it_needs_an_object(self):
        self.fails([], "expected an object")

    def test_the_version_must_be_1(self):
        for version in (2, "1", True, None):
            with self.subTest(version):
                self.fails(self.ok(version=version), "version must be 1")

    def test_the_rate_must_be_30_or_60(self):
        for rate in (0, 15, 45, 120, "30", 30.0, True, None):
            with self.subTest(rate):
                self.fails(self.ok(rate_hz=rate), "rate_hz must be 30 or 60")

    def test_ticked_must_be_a_list_of_text(self):
        for ticked in ("limiter", None, {"limiter": 1}):
            with self.subTest(ticked):
                self.fails(self.ok(ticked=ticked), "ticked must be a list of ids")
        self.fails(self.ok(ticked=["limiter", 3]), "list of ids \\(text\\), got 3")

    def test_an_unknown_id_is_named(self):
        self.fails(self.ok(ticked=["limiter", "no_such_id"]), "unknown id no_such_id")
        self.fails(self.ok(ticked=["behaviour.nope"]), "unknown id behaviour.nope")

    def test_a_greyed_id_is_named(self):
        self.fails(self.ok(ticked=["gear_1"]), "gear_1 is greyed \\(indirect\\)")
        self.fails(self.ok(ticked=["toe_front"]), "toe_front is greyed \\(none\\)")

    def test_a_doubled_id_is_named(self):
        self.fails(self.ok(ticked=["limiter", "limiter"]), "limiter is ticked twice")
        self.fails(self.ok(ticked=["behaviour.rpm", "limiter", "behaviour.rpm"]), "behaviour.rpm is ticked twice")


class TestConfigFile(unittest.TestCase):
    def setUp(self):
        cm = tmp()
        self.d = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.work = str(self.d / "work")

    def test_the_file_is_log_config_json_in_the_work_folder(self):
        self.assertEqual(logconf.config_path(self.work), os.path.join(self.work, "log_config.json"))

    def test_a_missing_file_gives_the_default_and_writes_nothing(self):
        self.assertEqual(logconf.load_config(self.work, CHAN), logconf.default_config(CHAN))
        self.assertFalse(os.path.exists(self.work))

    def test_a_damaged_file_gives_the_default(self):
        for data in ("{not json", "", "[1, 2]", "null", b"\xff\xfe\x00", "\"text\""):
            with self.subTest(data):
                write(logconf.config_path(self.work), data)
                self.assertEqual(logconf.load_config(self.work, CHAN), logconf.default_config(CHAN))

    def test_an_invalid_file_gives_the_default(self):
        for config in ({"version": 2, "rate_hz": 30, "ticked": []}, {"version": 1, "rate_hz": 45, "ticked": []},
                       {"version": 1, "rate_hz": 30, "ticked": ["gear_1"]}, {"version": 1, "rate_hz": 30, "ticked": ["nope"]},
                       {"version": 1, "rate_hz": 30, "ticked": ["limiter", "limiter"]}, {"version": 1, "rate_hz": 30},
                       {"version": 1, "ticked": []}):
            with self.subTest(config):
                write(logconf.config_path(self.work), config)
                self.assertEqual(logconf.load_config(self.work, CHAN), logconf.default_config(CHAN))

    def test_a_config_path_that_is_a_folder_gives_the_default(self):
        os.makedirs(logconf.config_path(self.work))
        self.assertEqual(logconf.load_config(self.work, CHAN), logconf.default_config(CHAN))

    def test_a_valid_file_is_returned_normalised(self):
        write(logconf.config_path(self.work), {"version": 1, "rate_hz": 60, "extra": "x",
                                               "ticked": ["car_state.turbo", "limiter", "behaviour.speed", "fuel_start"]})
        self.assertEqual(logconf.load_config(self.work, CHAN),
                         {"version": 1, "rate_hz": 60, "ticked": ["limiter", "fuel_start", "behaviour.speed", "car_state.turbo"]})

    def test_a_valid_file_with_a_bom_is_read(self):
        write(logconf.config_path(self.work), b"\xef\xbb\xbf" + json.dumps({"version": 1, "rate_hz": 60, "ticked": ["limiter"]}).encode("utf-8"))
        self.assertEqual(logconf.load_config(self.work, CHAN), {"version": 1, "rate_hz": 60, "ticked": ["limiter"]})

    def test_save_and_load_round_trip(self):
        config = {"version": 1, "rate_hz": 60, "ticked": ["limiter", "behaviour.speed", "car_state.turbo"]}
        saved = logconf.save_config(self.work, config, CHAN)
        self.assertEqual(saved, config)
        self.assertEqual(logconf.load_config(self.work, CHAN), config)
        self.assertEqual(tune.read_json(logconf.config_path(self.work)), config)

    def test_save_creates_the_work_folder_and_leaves_no_temporary_file(self):
        logconf.save_config(self.work, logconf.default_config(CHAN), CHAN)
        self.assertEqual(os.listdir(self.work), ["log_config.json"])

    def test_save_writes_the_normalised_form(self):
        logconf.save_config(self.work, {"version": 1, "rate_hz": 30, "extra": 1, "ticked": ["behaviour.rpm", "limiter"]}, CHAN)
        self.assertEqual(tune.read_json(logconf.config_path(self.work)), {"version": 1, "rate_hz": 30, "ticked": ["limiter", "behaviour.rpm"]})

    def test_save_overwrites_an_earlier_choice(self):
        logconf.save_config(self.work, {"version": 1, "rate_hz": 60, "ticked": ["limiter"]}, CHAN)
        logconf.save_config(self.work, {"version": 1, "rate_hz": 30, "ticked": []}, CHAN)
        self.assertEqual(logconf.load_config(self.work, CHAN), {"version": 1, "rate_hz": 30, "ticked": []})

    def test_an_invalid_config_is_not_saved_and_leaves_the_old_file(self):
        with self.assertRaises(ValueError):
            logconf.save_config(self.work, {"version": 1, "rate_hz": 30, "ticked": ["gear_1"]}, CHAN)
        self.assertFalse(os.path.exists(self.work))
        logconf.save_config(self.work, {"version": 1, "rate_hz": 60, "ticked": ["limiter"]}, CHAN)
        for bad in ({"version": 1, "rate_hz": 31, "ticked": []}, {"version": 1, "rate_hz": 30, "ticked": ["nope"]}):
            with self.assertRaises(ValueError):
                logconf.save_config(self.work, bad, CHAN)
        self.assertEqual(logconf.load_config(self.work, CHAN), {"version": 1, "rate_hz": 60, "ticked": ["limiter"]})
        self.assertEqual(os.listdir(self.work), ["log_config.json"])


class TestTree(unittest.TestCase):
    def setUp(self):
        self.config = {"version": 1, "rate_hz": 30, "ticked": ["limiter", "behaviour.speed", "car_state.turbo"]}
        self.groups = logconf.tree(CHAN, CAT, self.config)

    def catalogue_groups(self):
        return self.groups[2:]

    def test_the_extra_groups_come_first_then_the_groups_with_tickable_rows_then_those_without(self):
        names = [g["name"] for g in CAT["groups"]]
        direct = {s["group"] for s in CAT["settings"] if s["id"] in DIRECT}
        with_rows = [n for n in names if n in direct]
        without_rows = [n for n in names if n not in direct]
        self.assertTrue(with_rows and without_rows)
        self.assertEqual([g["name"] for g in self.groups], ["Behaviour values", "Car state"] + with_rows + without_rows)
        self.assertEqual([g["id"] for g in self.groups], ["behaviour", "car_state"] + ["catalogue." + n for n in with_rows + without_rows])
        self.assertEqual(len(self.groups), 20)
        self.assertEqual(sorted(g["name"] for g in self.catalogue_groups()), sorted(names))
        for name in ("Meta", "Gearbox & clutch", "Springs & anti-roll", "Tyres", "Dampers"):
            self.assertIn(name, without_rows)
        for name in ("Engine", "Differential", "Brakes"):
            self.assertIn(name, with_rows)

    def test_the_groups_with_tickable_rows_have_all_a_positive_count_and_the_others_zero(self):
        counts = [g["tickable"] for g in self.catalogue_groups()]
        first_empty = counts.index(0)
        self.assertTrue(all(c > 0 for c in counts[:first_empty]))
        self.assertTrue(all(c == 0 for c in counts[first_empty:]))

    def test_a_catalogue_group_has_its_description_and_all_its_settings_with_the_tickable_ones_first(self):
        cgs = {g["name"]: g for g in CAT["groups"]}
        for g in self.catalogue_groups():
            with self.subTest(g["name"]):
                self.assertEqual(set(g), {"id", "name", "description", "tickable", "rows"})
                self.assertEqual(g["description"], cgs[g["name"]]["description"])
                ids = [s["id"] for s in CAT["settings"] if s["group"] == g["name"]]
                self.assertEqual([r["id"] for r in g["rows"]], [i for i in ids if i in DIRECT] + [i for i in ids if i not in DIRECT])
                self.assertEqual(g["tickable"], sum(i in DIRECT for i in ids))

    def test_the_rows_of_a_group_are_tickable_first_and_the_counts_add_up_to_the_tickable_rows(self):
        for g in self.groups:
            flags = [r["tickable"] for r in g["rows"]]
            with self.subTest(g["name"]):
                self.assertEqual(flags, sorted(flags, reverse=True))
                self.assertEqual(g["tickable"], sum(flags))
                self.assertIs(type(g["tickable"]), int)
        self.assertEqual(sum(g["tickable"] for g in self.groups), len(logconf.tickable_ids(CHAN)))
        by = {g["name"]: g for g in self.groups}
        self.assertEqual((by["Engine"]["tickable"], by["Meta"]["tickable"], by["Alignment & tyres"]["tickable"]), (2, 0, 4))
        self.assertEqual([r["id"] for r in by["Engine"]["rows"]][:3], ["limiter", "idle_rpm", "power_scale"])
        self.assertEqual([r["tickable"] for r in by["Engine"]["rows"]][:3], [True, True, False])
        self.assertEqual([r["id"] for r in by["Alignment & tyres"]["rows"]][:5], ["camber_front", "camber_rear", "tyre_pressure_front", "tyre_pressure_rear", "caster_front"])

    def test_groups_without_a_direct_row_are_listed_too(self):
        by = {g["name"]: g for g in self.groups}
        for name in ("Meta", "Gearbox & clutch", "Springs & anti-roll", "Dampers"):
            self.assertTrue(by[name]["rows"])
            self.assertFalse(any(r["tickable"] for r in by[name]["rows"]), name)
            self.assertEqual(by[name]["tickable"], 0)

    def test_a_catalogue_row(self):
        row = next(r for g in self.groups for r in g["rows"] if r["id"] == "limiter")
        setting = tune.find_setting(CAT, "limiter")
        self.assertEqual(row, {"id": "limiter", "label": setting["label"], "unit": setting["unit"], "status": "direct", "note": "",
                               "tickable": True, "ticked": True, "once": ["rpm_max"], "live": ["rpm"]})
        grey = next(r for g in self.groups for r in g["rows"] if r["id"] == "gear_1")
        self.assertEqual((grey["status"], grey["tickable"], grey["ticked"], grey["once"], grey["live"]), ("indirect", False, False, [], []))
        self.assertTrue(grey["note"].startswith("only its effect is visible"))

    def test_tickable_is_the_direct_status(self):
        for g in self.catalogue_groups():
            for r in g["rows"]:
                self.assertEqual(r["tickable"], r["status"] == "direct", r["id"])
                self.assertEqual(set(r), {"id", "label", "unit", "status", "note", "tickable", "ticked", "once", "live"})
                self.assertNotIn("default", r)
        self.assertEqual(sum(r["tickable"] for g in self.catalogue_groups() for r in g["rows"]), 29)

    def test_ticked_follows_the_config(self):
        ticked = [r["id"] for g in self.groups for r in g["rows"] if r["ticked"]]
        self.assertEqual(sorted(ticked), sorted(self.config["ticked"]))

    def test_the_extra_groups(self):
        behaviour, car_state = self.groups[:2]
        for g in (behaviour, car_state):
            self.assertEqual(set(g), {"id", "name", "description", "tickable", "rows"})
        self.assertEqual((behaviour["id"], behaviour["name"], behaviour["tickable"]), ("behaviour", "Behaviour values", 13))
        self.assertEqual((car_state["id"], car_state["name"], car_state["tickable"]), ("car_state", "Car state", 9))
        self.assertEqual([r["id"] for r in behaviour["rows"]], ["behaviour." + r for r in BEHAVIOUR])
        self.assertEqual([r["id"] for r in car_state["rows"]], ["car_state." + r for r in CAR_STATE])
        row = behaviour["rows"][0]
        self.assertEqual(row, {"id": "behaviour.speed", "label": "Speed", "description": row["description"], "default": True, "tickable": True,
                               "ticked": True, "status": "extra", "note": "", "once": [], "live": ["speed_kmh"]})
        for g in (behaviour, car_state):
            for r in g["rows"]:
                self.assertEqual((r["tickable"], r["status"], r["note"]), (True, "extra", ""), r["id"])
                self.assertEqual(set(r), {"id", "label", "description", "default", "tickable", "ticked", "status", "note", "once", "live"})
                self.assertIs(type(r["default"]), bool)
        self.assertEqual([r["default"] for r in behaviour["rows"]], [r in DEFAULT_ROWS for r in BEHAVIOUR])
        self.assertEqual([r["default"] for r in car_state["rows"]], [False] * len(CAR_STATE))
        self.assertEqual([r["ticked"] for r in behaviour["rows"]], [r == "speed" for r in BEHAVIOUR])
        self.assertEqual([r["ticked"] for r in car_state["rows"]], [r == "turbo" for r in CAR_STATE])

    def test_the_default_of_an_extra_row_is_the_default_of_the_table_and_not_the_ticked_state(self):
        groups = logconf.tree(CHAN, CAT, {"version": 1, "rate_hz": 30, "ticked": ["car_state.turbo"]})
        self.assertEqual([r["id"] for g in groups for r in g["rows"] if r.get("default")], ["behaviour.speed", "behaviour.rpm"])
        chan = changed(lambda c: row_of(c, "car_state", "turbo").update(default=True))
        groups = logconf.tree(chan, CAT, self.config)
        self.assertEqual([r["id"] for g in groups for r in g["rows"] if r.get("default")], ["behaviour.speed", "behaviour.rpm", "car_state.turbo"])

    def test_the_default_config_ticks_speed_and_rpm_only(self):
        groups = logconf.tree(CHAN, CAT, logconf.default_config(CHAN))
        self.assertEqual([r["id"] for g in groups for r in g["rows"] if r["ticked"]], ["behaviour.speed", "behaviour.rpm"])

    def test_the_display_order_does_not_change_the_order_of_the_tickable_ids_or_of_a_saved_choice(self):
        shown = [r["id"] for g in self.groups for r in g["rows"] if r["tickable"]]
        ids = logconf.tickable_ids(CHAN)
        self.assertNotEqual(shown, ids)
        self.assertEqual(sorted(shown), sorted(ids))
        self.assertEqual(ids[:29], [s["id"] for s in CAT["settings"] if s["id"] in DIRECT])
        self.assertEqual(ids[29:], ["behaviour." + r for r in BEHAVIOUR] + ["car_state." + r for r in CAR_STATE])
        self.assertEqual(logconf.normalised({"version": 1, "rate_hz": 30, "ticked": shown}, CHAN)["ticked"], ids)
        self.assertEqual(logconf.selected_channels(CHAN, {"version": 1, "rate_hz": 30, "ticked": shown}),
                         logconf.selected_channels(CHAN, {"version": 1, "rate_hz": 30, "ticked": ids}))

    def test_the_tree_is_json_and_does_not_share_lists_with_the_table(self):
        json.dumps(self.groups)
        self.groups[1]["rows"][0]["once"].append("x")
        self.assertNotIn("x", CHAN["extra_groups"][1]["rows"][0]["once"])
        row = next(r for g in self.groups for r in g["rows"] if r["id"] == "limiter")
        row["live"].append("x")
        self.assertEqual(CHAN["settings"]["limiter"]["live"], ["rpm"])


class TestSelectedChannels(unittest.TestCase):
    def config(self, *ticked):
        return {"version": 1, "rate_hz": 30, "ticked": list(ticked)}

    def test_nothing_ticked_selects_nothing(self):
        self.assertEqual(logconf.selected_channels(CHAN, self.config()), {"once": [], "live": []})

    def test_one_direct_setting(self):
        self.assertEqual(logconf.selected_channels(CHAN, self.config("limiter")), {"once": ["rpm_max"], "live": ["rpm"]})

    def test_the_union_has_no_repeats_and_follows_the_order_of_the_tickable_ids(self):
        sel = logconf.selected_channels(CHAN, self.config("behaviour.rpm", "idle_rpm", "limiter", "display_power_ps"))
        self.assertEqual(sel["once"], ["bhp", "torque", "rpm_max", "rpm"])
        self.assertEqual(sel["live"], ["bhp", "torque", "rpm", "gas"])

    def test_the_order_of_the_config_does_not_matter(self):
        a = logconf.selected_channels(CHAN, self.config("behaviour.rpm", "limiter", "car_state.turbo"))
        b = logconf.selected_channels(CHAN, self.config("car_state.turbo", "limiter", "behaviour.rpm"))
        self.assertEqual(a, b)
        self.assertEqual(a["once"], ["rpm_max", "turbo_level", "boost_max"])
        self.assertEqual(a["live"], ["rpm", "boost", "turbo_level"])

    def test_a_setting_and_an_extra_row_can_share_channels(self):
        sel = logconf.selected_channels(CHAN, self.config("tc_level", "driver_aids_off", "behaviour.slip"))
        self.assertEqual(sel["live"], ["tc_active", "abs_active", "esc_active", "slip_ratio", "slip_angle_deg"])
        self.assertEqual(len(sel["once"]), len(set(sel["once"])))

    def test_the_default_selection_has_speed_and_rpm(self):
        sel = logconf.selected_channels(CHAN, logconf.default_config(CHAN))
        self.assertIn("speed_kmh", sel["live"])
        self.assertIn("rpm", sel["live"])
        self.assertEqual(sel["once"], [])
        self.assertEqual(len(sel["live"]), len(set(sel["live"])))
        self.assertLessEqual(set(sel["live"]), KNOWN)

    def test_everything_ticked_selects_only_known_channels(self):
        sel = logconf.selected_channels(CHAN, self.config(*logconf.tickable_ids(CHAN)))
        self.assertLessEqual(set(sel["once"]) | set(sel["live"]), KNOWN)
        self.assertIn("pad_life", sel["once"])
        self.assertIn("bhp", sel["live"])


class TestStopFile(unittest.TestCase):
    def setUp(self):
        cm = tmp()
        self.d = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.logs = str(self.d / "logs")

    def test_the_name_is_logger_stop_and_the_path_is_in_the_logs_folder(self):
        self.assertEqual(logconf.STOP_FILE, "logger_stop")
        self.assertEqual(logconf.stop_path(self.logs), os.path.join(self.logs, "logger_stop"))

    def test_request_stop_creates_the_logs_folder_and_an_empty_file_and_returns_its_path(self):
        self.assertFalse(os.path.exists(self.logs))
        path = logconf.request_stop(self.logs)
        self.assertEqual(path, logconf.stop_path(self.logs))
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), 0)
        self.assertEqual(os.listdir(self.logs), ["logger_stop"])

    def test_request_stop_twice_or_in_an_existing_folder_is_fine(self):
        os.makedirs(self.logs)
        write(os.path.join(self.logs, "a.jsonl"), "x")
        self.assertEqual(logconf.request_stop(self.logs), logconf.request_stop(self.logs))
        self.assertEqual(sorted(os.listdir(self.logs)), ["a.jsonl", "logger_stop"])

    def test_clear_stop_removes_the_file_and_leaves_the_rest(self):
        logconf.request_stop(self.logs)
        write(os.path.join(self.logs, "a.jsonl"), "x")
        self.assertIsNone(logconf.clear_stop(self.logs))
        self.assertEqual(os.listdir(self.logs), ["a.jsonl"])

    def test_clear_stop_ignores_a_missing_file_a_missing_folder_and_other_errors(self):
        logconf.clear_stop(self.logs)
        os.makedirs(self.logs)
        logconf.clear_stop(self.logs)
        os.makedirs(logconf.stop_path(self.logs))
        logconf.clear_stop(self.logs)
        self.assertTrue(os.path.isdir(logconf.stop_path(self.logs)))

    def test_a_stop_file_is_not_a_session_and_not_a_status(self):
        logconf.request_stop(self.logs)
        self.assertEqual(logconf.list_sessions(self.logs), [])
        self.assertFalse(logconf.logger_status(self.logs)["running"])


class TestSessions(unittest.TestCase):
    def setUp(self):
        cm = tmp()
        self.d = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.logs = str(self.d / "logs")

    def session(self, name, lines, mtime=None, eol="\n"):
        path = write(os.path.join(self.logs, name), "".join(json.dumps(x) + eol if not isinstance(x, str) else x + eol for x in lines))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def full(self, name="a.jsonl", mtime=None, car="ks_x", track="Imola", duration=12.5, samples=3, n=3):
        return self.session(name, [{"type": "header", "car": car, "track": track}] + [{"type": "s", "t": i / 10, "rpm": 1000 + i} for i in range(n)]
                            + [{"type": "end", "reason": "game closed", "duration_s": duration, "samples": samples}], mtime)

    def test_a_missing_folder_gives_an_empty_list(self):
        self.assertEqual(logconf.list_sessions(self.logs), [])

    def test_a_folder_path_that_is_a_file_gives_an_empty_list(self):
        write(self.logs, "x")
        self.assertEqual(logconf.list_sessions(self.logs), [])

    def test_an_empty_folder_gives_an_empty_list(self):
        os.makedirs(self.logs)
        self.assertEqual(logconf.list_sessions(self.logs), [])

    def test_a_finished_session(self):
        path = self.full(mtime=1700000000)
        info, = logconf.list_sessions(self.logs)
        self.assertEqual(info, {"file": "a.jsonl", "size": os.path.getsize(path), "modified": 1700000000, "car": "ks_x", "track": "Imola",
                                "duration_s": 12.5, "samples": 3})

    def test_newest_first_by_modification_time_not_by_name(self):
        self.full("b.jsonl", mtime=1000)
        self.full("c.jsonl", mtime=3000)
        self.full("a.jsonl", mtime=2000)
        self.assertEqual([s["file"] for s in logconf.list_sessions(self.logs)], ["c.jsonl", "a.jsonl", "b.jsonl"])

    def test_the_limit_keeps_the_newest(self):
        for i in range(25):
            self.full("s%02d.jsonl" % i, mtime=1000 + i)
        sessions = logconf.list_sessions(self.logs)
        self.assertEqual([s["file"] for s in sessions], ["s%02d.jsonl" % i for i in range(24, 4, -1)])
        self.assertEqual([s["file"] for s in logconf.list_sessions(self.logs, limit=3)], ["s24.jsonl", "s23.jsonl", "s22.jsonl"])
        self.assertEqual(len(logconf.list_sessions(self.logs, limit=100)), 25)
        self.assertEqual(logconf.list_sessions(self.logs, limit=0), [])

    def test_only_jsonl_files_count(self):
        self.full("a.jsonl", mtime=1000)
        write(os.path.join(self.logs, "notes.txt"), "x")
        write(os.path.join(self.logs, "logger_status.json"), {"state": "waiting"})
        write(os.path.join(self.logs, "a.jsonl.tmp"), "x")
        os.makedirs(os.path.join(self.logs, "folder.jsonl"))
        self.assertEqual([s["file"] for s in logconf.list_sessions(self.logs)], ["a.jsonl"])

    def test_a_session_without_an_end_line_has_no_duration_or_samples(self):
        self.session("a.jsonl", [{"type": "header", "car": "ks_x", "track": "Imola"}, {"type": "s", "t": 0.1, "rpm": 900}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["track"], info["duration_s"], info["samples"]), ("ks_x", "Imola", None, None))

    def test_a_session_with_only_a_header_line(self):
        self.session("a.jsonl", [{"type": "header", "car": "ks_x", "track": "Imola"}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["track"], info["duration_s"], info["samples"]), ("ks_x", "Imola", None, None))

    def test_a_session_without_a_header_line_has_no_car_or_track(self):
        self.session("a.jsonl", [{"type": "s", "t": 0.1}, {"type": "end", "duration_s": 3, "samples": 7}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["track"], info["duration_s"], info["samples"]), (None, None, 3, 7))

    def test_header_and_end_values_of_the_wrong_type_are_none(self):
        self.session("a.jsonl", [{"type": "header", "car": 5, "track": None}, {"type": "end", "duration_s": "12", "samples": 2.5}])
        self.session("b.jsonl", [{"type": "header", "car": ["x"]}, {"type": "end", "duration_s": True, "samples": True}])
        self.session("c.jsonl", ["{\"type\": \"end\", \"duration_s\": NaN, \"samples\": 4}"])
        for info in logconf.list_sessions(self.logs):
            with self.subTest(info["file"]):
                self.assertEqual((info["car"], info["track"], info["duration_s"]), (None, None, None))
                self.assertIn(info["samples"], (None, 4))

    def test_a_header_type_must_be_header_and_an_end_type_must_be_end(self):
        self.session("a.jsonl", [{"type": "static", "car": "ks_x", "track": "Imola"}, {"type": "s", "duration_s": 3, "samples": 7}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["track"], info["duration_s"], info["samples"]), (None, None, None, None))

    def test_integers_are_kept_as_given(self):
        self.session("a.jsonl", [{"type": "header", "car": "c", "track": "t"}, {"type": "end", "duration_s": 60, "samples": 1800}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["duration_s"], info["samples"]), (60, 1800))

    def test_damaged_files_never_raise(self):
        write(os.path.join(self.logs, "a.jsonl"), b"")
        write(os.path.join(self.logs, "b.jsonl"), b"\xff\xfe\x00\x01 not json \xff")
        write(os.path.join(self.logs, "c.jsonl"), "[1, 2, 3]\n\"text\"\n")
        write(os.path.join(self.logs, "d.jsonl"), "{not json\n{also not")
        write(os.path.join(self.logs, "e.jsonl"), "\n\n   \n")
        sessions = logconf.list_sessions(self.logs)
        self.assertEqual(sorted(s["file"] for s in sessions), ["a.jsonl", "b.jsonl", "c.jsonl", "d.jsonl", "e.jsonl"])
        for s in sessions:
            with self.subTest(s["file"]):
                self.assertEqual((s["car"], s["track"], s["duration_s"], s["samples"]), (None, None, None, None))

    def test_a_damaged_file_does_not_hide_the_good_ones(self):
        self.full("good.jsonl", mtime=1000)
        write(os.path.join(self.logs, "bad.jsonl"), b"\x00\x01\x02")
        by = {s["file"]: s for s in logconf.list_sessions(self.logs)}
        self.assertEqual(by["good.jsonl"]["car"], "ks_x")
        self.assertIsNone(by["bad.jsonl"]["car"])

    def test_a_damaged_header_still_leaves_the_end_line_readable(self):
        self.session("a.jsonl", ["{broken", {"type": "end", "duration_s": 9.5, "samples": 12}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["track"], info["duration_s"], info["samples"]), (None, None, 9.5, 12))

    def test_a_long_session_reads_the_end_line_from_the_tail(self):
        path = self.full("a.jsonl", n=2000, samples=2000, duration=66.6)
        self.assertGreater(os.path.getsize(path), logconf.SESSION_TAIL * 3)
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["duration_s"], info["samples"]), ("ks_x", 66.6, 2000))

    def test_a_last_line_longer_than_the_tail_is_not_read_and_does_not_raise(self):
        self.session("a.jsonl", [{"type": "header", "car": "ks_x", "track": "Imola"}, {"type": "s", "pad": "x" * (logconf.SESSION_TAIL * 2)}])
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["duration_s"], info["samples"]), ("ks_x", None, None))

    def test_windows_line_endings_and_blank_lines_at_the_end(self):
        path = self.session("a.jsonl", [{"type": "header", "car": "ks_x", "track": "Imola"}, {"type": "end", "duration_s": 2, "samples": 5}], eol="\r\n")
        with open(path, "ab") as f:
            f.write(b"\r\n\r\n  \n")
        info, = logconf.list_sessions(self.logs)
        self.assertEqual((info["car"], info["track"], info["duration_s"], info["samples"]), ("ks_x", "Imola", 2, 5))

    def test_the_answer_is_json(self):
        self.full(mtime=1700000000.5)
        json.dumps(logconf.list_sessions(self.logs))

    def test_the_default_logs_folder_is_logs_in_the_repository(self):
        self.assertEqual(logconf.default_logs_dir(), os.path.join(str(ROOT), "logs"))


class TestLoggerStatus(unittest.TestCase):
    def setUp(self):
        cm = tmp()
        self.d = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.logs = str(self.d / "logs")

    def status(self, **more):
        return dict({"state": "logging", "file": "2026-11-16_12-00_ks_x.jsonl", "samples": 120, "started": 1000.0, "updated": 1100.0, "pid": 4242}, **more)

    def put(self, data):
        return write(os.path.join(self.logs, "logger_status.json"), data)

    NOT_RUNNING = {"running": False, "state": "not running", "file": None, "samples": None, "started": None, "seconds": None}

    def test_no_file_is_not_running(self):
        self.assertEqual(logconf.logger_status(self.logs, now=1100), self.NOT_RUNNING)
        os.makedirs(self.logs)
        self.assertEqual(logconf.logger_status(self.logs, now=1100), self.NOT_RUNNING)

    def test_a_fresh_logging_file_is_running_with_the_seconds_since_the_start(self):
        self.put(self.status())
        self.assertEqual(logconf.logger_status(self.logs, now=1102.5),
                         {"running": True, "state": "logging", "file": "2026-11-16_12-00_ks_x.jsonl", "samples": 120, "started": 1000.0,
                          "seconds": 102.5})

    def test_a_waiting_file_is_running_without_seconds(self):
        self.put(self.status(state="waiting", file=None, samples=0))
        self.assertEqual(logconf.logger_status(self.logs, now=1101),
                         {"running": True, "state": "waiting", "file": None, "samples": 0, "started": 1000.0, "seconds": None})

    def test_a_file_that_is_five_seconds_old_is_running_and_older_is_not(self):
        self.put(self.status())
        self.assertTrue(logconf.logger_status(self.logs, now=1105)["running"])
        self.assertEqual(logconf.logger_status(self.logs, now=1105.01), self.NOT_RUNNING)
        self.assertEqual(logconf.logger_status(self.logs, now=5000), self.NOT_RUNNING)
        self.assertEqual(logconf.STATUS_MAX_AGE, 5)

    def test_a_stale_waiting_file_is_not_running(self):
        self.put(self.status(state="waiting", file=None, samples=0))
        self.assertEqual(logconf.logger_status(self.logs, now=1200), self.NOT_RUNNING)

    def test_damaged_files_are_not_running(self):
        for data in ("{not json", "", "[1]", "null", b"\xff\xfe", "\"logging\""):
            with self.subTest(data):
                self.put(data)
                self.assertEqual(logconf.logger_status(self.logs, now=1100), self.NOT_RUNNING)

    def test_a_file_with_a_wrong_or_missing_field_is_not_running(self):
        for more in ({"state": "stopped"}, {"state": None}, {"file": 5}, {"samples": "120"}, {"samples": True}, {"samples": 1.5},
                     {"started": "1000"}, {"started": None}, {"updated": "1100"}, {"updated": None}, {"pid": "4242"}, {"pid": None}):
            with self.subTest(more):
                self.put(self.status(**more))
                self.assertEqual(logconf.logger_status(self.logs, now=1100), self.NOT_RUNNING)
        for key in ("state", "file", "samples", "started", "updated", "pid"):
            with self.subTest("without " + key):
                data = self.status()
                del data[key]
                self.put(data)
                self.assertEqual(logconf.logger_status(self.logs, now=1100), self.NOT_RUNNING)

    def test_now_defaults_to_the_current_time(self):
        self.put(self.status(started=time.time() - 30, updated=time.time()))
        answer = logconf.logger_status(self.logs)
        self.assertTrue(answer["running"])
        self.assertAlmostEqual(answer["seconds"], 30, delta=5)
        self.put(self.status(started=time.time() - 90, updated=time.time() - 60))
        self.assertEqual(logconf.logger_status(self.logs), self.NOT_RUNNING)

    def test_the_answer_is_json(self):
        self.put(self.status())
        json.dumps(logconf.logger_status(self.logs, now=1101))


if __name__ == "__main__":
    unittest.main()
