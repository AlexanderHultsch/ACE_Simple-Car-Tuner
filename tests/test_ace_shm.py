"""Tests for tools/ace_shm.py without the game: struct sizes and offsets, channels() and session_info() on synthetic bytes (built from the structs themselves), the SharedMemory reader on a named mapping made in the test (Windows only), and the dump command with a patched source.

The game's real blocks are never opened: the block names are patched to names of this test where a source is opened.
"""
import contextlib
import ctypes
import io
import json
import math
import os
import subprocess
import sys
import unittest
from ctypes import sizeof
from unittest import mock

from support import TOOLS, run_tool

import ace_shm

USAGE = ace_shm.__doc__.split("\n\n")[1]

PHYSICS_OFFSETS = {
    "packetId": 0, "gas": 4, "gear": 16, "rpms": 20, "steerAngle": 24, "speedKmh": 28, "accG": 44, "wheelLoad": 72,
    "wheelsPressure": 88, "wheelAngularSpeed": 104, "camberRAD": 168, "suspensionTravel": 184, "rideHeight": 268,
    "turboBoost": 276, "ballast": 280, "localAngularVel": 296, "brakeTemp": 348, "clutch": 364, "tyreTempI": 368,
    "tyreContactPoint": 420, "brakeBias": 564, "currentMaxRpm": 588, "mz": 592, "fx": 608, "fy": 624, "slipRatio": 640,
    "slipAngle": 656, "tcInAction": 672, "absInAction": 676, "suspensionDamage": 680, "tyreTemp": 696, "waterTemp": 712,
    "brakeTorque": 716, "padLife": 740, "discLife": 756, "ignitionOn": 772, "absVibrations": 796,
}

SIZES = {"TyreState": 256, "DamageState": 128, "PitInfo": 64, "Electronics": 128, "Instrumentation": 128,
         "SessionState": 256, "TimingState": 256, "AssistsState": 64, "Physics": 800}

CHANNEL_NAMES = [
    "rpm", "rpm_max", "gas", "brake", "clutch", "gear", "speed_kmh", "steer", "steer_deg", "acc_g", "g_forces",
    "angular_vel", "pitch_deg", "roll_deg", "heading_deg", "wheel_load", "wheel_speed", "slip_ratio", "slip_angle_deg",
    "camber_deg", "susp_travel", "ride_height", "tyre_pressure_psi", "tyre_temp_core", "tyre_temp_in", "tyre_temp_mid",
    "tyre_temp_out", "brake_temp", "brake_torque", "brake_bias", "boost", "boost_max", "bhp", "torque", "fuel_l",
    "fuel_max_l", "max_gears", "tc_level", "tc_cut_level", "abs_level", "esc_level", "ebb_level", "engine_map",
    "diff_power_level", "diff_coast_level", "turbo_level", "performance_mode", "performance_mode_name", "diff_power_pct",
    "diff_coast_pct", "damper_levels", "tc_active", "abs_active", "esc_active", "tc_in_action", "abs_in_action",
    "engine_brake", "tyre_compound_front", "tyre_compound_rear", "cg_height", "ballast", "pad_life", "disc_life",
    "front_brake_compound", "rear_brake_compound", "electronics_min", "electronics_max", "electronics_modifiable",
]

ELECTRONICS_FIELDS = [
    "tc_level", "tc_cut_level", "abs_level", "esc_level", "ebb_level", "brake_bias", "engine_map_level", "turbo_level",
    "ers_deployment_map", "ers_recharge_map", "is_ers_heat_charging_on", "is_ers_overtake_mode_on", "is_drs_open",
    "diff_power_level", "diff_coast_level", "front_bump_damper_level", "front_rebound_damper_level",
    "rear_bump_damper_level", "rear_rebound_damper_level", "is_ignition_on", "is_pitlimiter_on",
    "active_performance_mode",
]


def fill(array, values):
    for i, v in enumerate(values):
        array[i] = v


def build():
    """Physics, Graphics and Static with a distinct, float32-exact value in every field the channels read."""
    ph, gr, st = ace_shm.Physics(), ace_shm.Graphics(), ace_shm.Static()
    ph.packetId, ph.gas, ph.brake, ph.clutch = 11, 0.75, 0.5, 0.25
    ph.gear, ph.rpms, ph.currentMaxRpm = 4, 7200, 8000
    ph.steerAngle, ph.speedKmh = -0.5, 123.5
    fill(ph.accG, (1.5, -2.5, 0.5))
    fill(ph.localAngularVel, (0.25, -0.5, 1.0))
    ph.pitch, ph.roll, ph.heading = 0.125, -0.25, 3.0
    fill(ph.wheelLoad, (3000.0, 3100.0, 2900.0, 2800.0))
    fill(ph.wheelAngularSpeed, (50.5, 51.5, 52.5, 53.5))
    fill(ph.slipRatio, (0.0625, -0.125, 0.25, -0.5))
    fill(ph.slipAngle, (0.0625, 0.125, -0.25, -0.5))
    fill(ph.camberRAD, (-0.03125, 0.03125, -0.0625, 0.0625))
    fill(ph.suspensionTravel, (0.0625, 0.125, 0.1875, 0.25))
    fill(ph.rideHeight, (0.0625, 0.09375))
    fill(ph.tyreTempI, (81.0, 82.0, 83.0, 84.0))
    fill(ph.tyreTempM, (85.0, 86.0, 87.0, 88.0))
    fill(ph.tyreTempO, (89.0, 90.0, 91.0, 92.0))
    fill(ph.brakeTemp, (301.0, 302.0, 303.0, 304.0))
    fill(ph.brakeTorque, (401.0, 402.0, 403.0, 404.0))
    ph.brakeBias = 0.625
    ph.tcInAction, ph.absInAction, ph.engineBrake = 1, 0, 3
    ph.cgHeight, ph.ballast = 0.5, 75.0
    fill(ph.padLife, (0.5, 0.625, 0.75, 0.875))
    fill(ph.discLife, (0.25, 0.375, 0.5, 0.625))
    ph.frontBrakeCompound, ph.rearBrakeCompound = 2, 3

    gr.packetId, gr.status = 22, 2
    gr.steer_degrees = -90
    gr.g_forces_x, gr.g_forces_y, gr.g_forces_z = 1.25, -1.75, 0.75
    for block, psi, core in ((gr.tyre_lf, 26.5, 71.0), (gr.tyre_rf, 27.5, 72.0), (gr.tyre_lr, 28.5, 73.0), (gr.tyre_rr, 29.5, 74.0)):
        block.tyre_pressure, block.tyre_temperature_c = psi, core
    gr.tyre_lf.tyre_compound_front, gr.tyre_lf.tyre_compound_rear = b"Semislick", b"Slick"
    gr.turbo_boost, gr.max_turbo_boost = 0.5, 1.5
    gr.current_bhp, gr.current_torque = 450, 520.5
    gr.fuel_liter_current_quantity, gr.max_fuel = 40.25, 100.5
    gr.max_gears = 6
    el = gr.electronics
    el.tc_level, el.tc_cut_level, el.abs_level, el.esc_level, el.ebb_level = 3, 2, 4, 5, 6
    el.engine_map_level, el.turbo_level, el.diff_power_level, el.diff_coast_level = 1, 0.5, 7, 8
    el.front_bump_damper_level, el.front_rebound_damper_level = 9, 10
    el.rear_bump_damper_level, el.rear_rebound_damper_level = 11, 12
    el.active_performance_mode = 2
    gr.performance_mode_name = b"SPORT+"
    gr.diff_power_raw_value, gr.diff_coast_raw_value = 0.25, 0.5
    gr.tc_active, gr.abs_active, gr.esc_active = True, False, True
    gr.car_model = b"BMW M4 CSL"
    for block, base in ((gr.electronics_min_limit, 0), (gr.electronics_max_limit, 10), (gr.electronics_is_modifiable, 20)):
        block.tc_level, block.abs_level, block.engine_map_level = base + 1, base + 2, base + 3
        block.brake_bias, block.turbo_level = base + 0.5, base + 0.25
    gr.electronics_is_modifiable.is_drs_open = True
    gr.electronics_is_modifiable.is_pitlimiter_on = True

    st.sm_version, st.ac_evo_version = b"v1.2", b"0.6.1"
    st.session, st.session_name, st.event_id, st.session_id = 1, b"Practice", 3, 2
    st.track = b"Monza"
    return ph, gr, st


def expected_channels():
    d = math.degrees
    return {
        "rpm": 7200, "rpm_max": 8000, "gas": 0.75, "brake": 0.5, "clutch": 0.25, "gear": 3,
        "speed_kmh": 123.5, "steer": -0.5, "steer_deg": -90, "acc_g": [1.5, -2.5, 0.5],
        "g_forces": [1.25, -1.75, 0.75], "angular_vel": [0.25, -0.5, 1.0],
        "pitch_deg": d(0.125), "roll_deg": d(-0.25), "heading_deg": d(3.0),
        "wheel_load": [3000.0, 3100.0, 2900.0, 2800.0], "wheel_speed": [50.5, 51.5, 52.5, 53.5],
        "slip_ratio": [0.0625, -0.125, 0.25, -0.5],
        "slip_angle_deg": [d(0.0625), d(0.125), d(-0.25), d(-0.5)],
        "camber_deg": [d(-0.03125), d(0.03125), d(-0.0625), d(0.0625)],
        "susp_travel": [0.0625, 0.125, 0.1875, 0.25], "ride_height": [0.0625, 0.09375],
        "tyre_pressure_psi": [26.5, 27.5, 28.5, 29.5], "tyre_temp_core": [71.0, 72.0, 73.0, 74.0],
        "tyre_temp_in": [81.0, 82.0, 83.0, 84.0], "tyre_temp_mid": [85.0, 86.0, 87.0, 88.0],
        "tyre_temp_out": [89.0, 90.0, 91.0, 92.0], "brake_temp": [301.0, 302.0, 303.0, 304.0],
        "brake_torque": [401.0, 402.0, 403.0, 404.0], "brake_bias": 0.625,
        "boost": 0.5, "boost_max": 1.5, "bhp": 450, "torque": 520.5, "fuel_l": 40.25, "fuel_max_l": 100.5, "max_gears": 6,
        "tc_level": 3, "tc_cut_level": 2, "abs_level": 4, "esc_level": 5, "ebb_level": 6, "engine_map": 1,
        "diff_power_level": 7, "diff_coast_level": 8, "turbo_level": 0.5, "performance_mode": 2,
        "performance_mode_name": "SPORT+", "diff_power_pct": 0.25, "diff_coast_pct": 0.5,
        "damper_levels": [9, 10, 11, 12], "tc_active": True, "abs_active": False, "esc_active": True,
        "tc_in_action": 1, "abs_in_action": 0, "engine_brake": 3,
        "tyre_compound_front": "Semislick", "tyre_compound_rear": "Slick",
        "cg_height": 0.5, "ballast": 75.0, "pad_life": [0.5, 0.625, 0.75, 0.875], "disc_life": [0.25, 0.375, 0.5, 0.625],
        "front_brake_compound": 2, "rear_brake_compound": 3,
    }


def electronics_expected(base, drs=0, pit=0):
    table = dict.fromkeys(ELECTRONICS_FIELDS, 0)
    table.update(tc_level=base + 1, abs_level=base + 2, engine_map_level=base + 3, brake_bias=base + 0.5,
                 turbo_level=base + 0.25, is_drs_open=drs, is_pitlimiter_on=pit)
    for name in ("brake_bias", "turbo_level", "ers_recharge_map"):
        table[name] = float(table[name])
    return table


class Layout(unittest.TestCase):
    def test_nested_and_physics_sizes(self):
        for name, size in SIZES.items():
            with self.subTest(name):
                self.assertEqual(sizeof(getattr(ace_shm, name)), size)

    def test_physics_offsets_match_the_documentation(self):
        for name, offset in PHYSICS_OFFSETS.items():
            with self.subTest(name):
                self.assertEqual(getattr(ace_shm.Physics, name).offset, offset)

    def test_the_documented_flag_fields_have_names_and_the_sizes_stay(self):
        def names(struct):
            return [n for n, _ in struct._fields_]
        self.assertEqual(names(ace_shm.DamageState), [
            "damage_front", "damage_rear", "damage_left", "damage_right", "damage_center", "damage_suspension_lf",
            "damage_suspension_rf", "damage_suspension_lr", "damage_suspension_rr", "_reserved"])
        self.assertEqual(names(ace_shm.PitInfo), ["damage", "fuel", "tyres_lf", "tyres_rf", "tyres_lr", "tyres_rr", "_reserved"])
        self.assertEqual(names(ace_shm.SessionState)[-7:], [
            "disconnected_from_server", "restart_season_enabled", "ui_enable_drive", "ui_enable_setup",
            "is_ready_to_next_blinking", "show_waiting_for_players", "_reserved"])
        self.assertNotIn("flags", names(ace_shm.SessionState))
        self.assertEqual(names(ace_shm.AssistsState), [
            "auto_gear", "auto_blip", "auto_clutch", "auto_clutch_on_start", "manual_ignition_e_start", "auto_pit_limiter",
            "standing_start_assist", "auto_steer", "arcade_stability_control", "_reserved"])
        self.assertEqual(ace_shm.SessionState._reserved.size, 140)
        self.assertEqual(ace_shm.AssistsState._reserved.size, 48)
        self.assertEqual(ace_shm.PitInfo._reserved.size, 58)
        self.assertEqual(ace_shm.DamageState._reserved.size, 92)
        self.assertEqual(ace_shm.DamageState.damage_suspension_rr.offset, 32)
        self.assertEqual(ace_shm.AssistsState.auto_steer.offset, 8)

    def test_the_session_flags_and_assists_land_in_the_graphics_block(self):
        gr = ace_shm.Graphics()
        gr.session_state.show_waiting_for_players = True
        gr.assists_state.standing_start_assist = 1
        gr.car_damage.damage_suspension_rr = 0.5
        gr.pit_info.tyres_rr = -3
        again = ace_shm.Graphics.from_buffer_copy(bytes(gr))
        self.assertTrue(again.session_state.show_waiting_for_players)
        self.assertEqual(again.assists_state.standing_start_assist, 1)
        self.assertEqual(again.car_damage.damage_suspension_rr, 0.5)
        self.assertEqual(again.pit_info.tyres_rr, -3)


class Channels(unittest.TestCase):
    def test_the_expected_table_names_exactly_the_documented_channels(self):
        self.assertEqual(len(CHANNEL_NAMES), len(set(CHANNEL_NAMES)))
        self.assertEqual(sorted(CHANNEL_NAMES), sorted(set(expected_channels()) | {"electronics_min", "electronics_max", "electronics_modifiable"}))

    def test_every_channel_has_the_right_value(self):
        ph, gr, st = build()
        got = ace_shm.channels(bytes(ph), bytes(gr))
        self.assertEqual(sorted(got), sorted(CHANNEL_NAMES))
        for name, want in expected_channels().items():
            with self.subTest(name):
                self.assertEqual(got[name], want)
                self.assertEqual(type(got[name]), type(want))

    def test_the_electronics_tables_hold_every_field_but_the_padding_as_ints_and_floats(self):
        ph, gr, st = build()
        got = ace_shm.channels(bytes(ph), bytes(gr))
        for name, base, drs, pit in (("electronics_min", 0, 0, 0), ("electronics_max", 10, 0, 0), ("electronics_modifiable", 20, 1, 1)):
            with self.subTest(name):
                self.assertEqual(list(got[name]), ELECTRONICS_FIELDS)
                self.assertEqual(got[name], electronics_expected(base, drs, pit))
                for field, value in got[name].items():
                    self.assertIn(type(value), (int, float), field)
        self.assertIs(type(got["electronics_modifiable"]["is_drs_open"]), int)

    def test_array_order_is_front_left_front_right_rear_left_rear_right(self):
        ph, gr, st = build()
        gr.tyre_lf.tyre_pressure, gr.tyre_rf.tyre_pressure, gr.tyre_lr.tyre_pressure, gr.tyre_rr.tyre_pressure = 1.0, 2.0, 3.0, 4.0
        got = ace_shm.channels(bytes(ph), bytes(gr))
        self.assertEqual(got["tyre_pressure_psi"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(got["wheel_load"][0], 3000.0)
        self.assertEqual(got["wheel_load"][3], 2800.0)
        self.assertEqual(got["ride_height"], [0.0625, 0.09375])

    def test_the_gear_is_minus_one_for_reverse_zero_for_neutral(self):
        ph, gr, st = build()
        for raw, want in ((0, -1), (1, 0), (2, 1), (8, 7)):
            ph.gear = raw
            self.assertEqual(ace_shm.channels(bytes(ph), bytes(gr))["gear"], want, raw)

    def test_radians_become_degrees_where_the_name_says_so(self):
        ph, gr, st = build()
        ph.pitch, ph.roll, ph.heading = math.pi / 2, -math.pi / 4, math.pi
        fill(ph.slipAngle, (math.pi / 2, 0.0, 0.0, -math.pi / 2))
        fill(ph.camberRAD, (math.pi / 6, 0.0, 0.0, -math.pi / 6))
        got = ace_shm.channels(bytes(ph), bytes(gr))
        self.assertAlmostEqual(got["pitch_deg"], 90.0, places=4)
        self.assertAlmostEqual(got["roll_deg"], -45.0, places=4)
        self.assertAlmostEqual(got["heading_deg"], 180.0, places=4)
        self.assertAlmostEqual(got["slip_angle_deg"][0], 90.0, places=4)
        self.assertAlmostEqual(got["slip_angle_deg"][3], -90.0, places=4)
        self.assertAlmostEqual(got["camber_deg"][0], 30.0, places=4)
        self.assertAlmostEqual(got["camber_deg"][3], -30.0, places=4)

    def test_nan_and_infinity_become_none_and_the_result_is_json(self):
        ph, gr, st = build()
        ph.speedKmh = float("nan")
        ph.wheelLoad[1] = float("inf")
        ph.pitch = float("-inf")
        gr.current_torque = float("nan")
        gr.electronics_max_limit.turbo_level = float("inf")
        got = ace_shm.channels(bytes(ph), bytes(gr))
        self.assertIsNone(got["speed_kmh"])
        self.assertEqual(got["wheel_load"], [3000.0, None, 2900.0, 2800.0])
        self.assertIsNone(got["pitch_deg"])
        self.assertIsNone(got["torque"])
        self.assertIsNone(got["electronics_max"]["turbo_level"])
        json.dumps(got, allow_nan=False)

    def test_json_round_trip(self):
        ph, gr, st = build()
        got = ace_shm.channels(bytes(ph), bytes(gr))
        self.assertEqual(json.loads(json.dumps(got, allow_nan=False)), got)

    def test_short_blocks_are_zero_padded(self):
        ph, gr, st = build()
        got = ace_shm.channels(bytes(ph)[:24], bytes(gr)[:12])
        self.assertEqual(got["rpm"], 7200)
        self.assertEqual(got["gear"], 3)
        self.assertEqual(got["rpm_max"], 0)
        self.assertEqual(got["wheel_load"], [0.0] * 4)
        self.assertEqual(got["tyre_pressure_psi"], [0.0] * 4)
        self.assertEqual(got["electronics_min"], dict.fromkeys(ELECTRONICS_FIELDS, 0) | {"brake_bias": 0.0, "turbo_level": 0.0, "ers_recharge_map": 0.0})
        self.assertEqual(sorted(got), sorted(CHANNEL_NAMES))

    def test_empty_blocks_give_zeros_with_gear_minus_one(self):
        got = ace_shm.channels(b"", b"")
        self.assertEqual(sorted(got), sorted(CHANNEL_NAMES))
        self.assertEqual((got["gear"], got["rpm"], got["performance_mode_name"]), (-1, 0, ""))
        json.dumps(got, allow_nan=False)

    def test_blocks_longer_than_the_struct_are_cut(self):
        ph, gr, st = build()
        got = ace_shm.channels(bytes(ph) + b"\xff" * 16, bytes(gr) + b"\xff" * 16)
        self.assertEqual(got["rpm"], 7200)

    def test_tyre_compounds_are_decoded_text(self):
        ph, gr, st = build()
        gr.tyre_lf.tyre_compound_front, gr.tyre_lf.tyre_compound_rear = b"  Slick \xc3\xa9", b"\xff"
        got = ace_shm.channels(bytes(ph), bytes(gr))
        self.assertEqual(got["tyre_compound_front"], "Slick é")
        self.assertEqual(got["tyre_compound_rear"], "�")
        self.assertEqual(ace_shm.text(b"  abc \n"), "abc")


class SessionInfo(unittest.TestCase):
    def test_info_fields(self):
        ph, gr, st = build()
        self.assertEqual(ace_shm.session_info(bytes(gr), bytes(st)), {
            "status": 2, "status_name": "live", "car": "BMW M4 CSL", "track": "Monza", "session_id": "3-2-1-Practice",
            "game_version": "0.6.1", "layout_version": "v1.2", "packet": [22]})

    def test_status_names(self):
        ph, gr, st = build()
        for number, name in ((0, "off"), (1, "replay"), (2, "live"), (3, "pause"), (4, "unknown"), (-1, "unknown")):
            gr.status = number
            info = ace_shm.session_info(bytes(gr), bytes(st))
            self.assertEqual((info["status"], info["status_name"]), (number, name))

    def test_short_blocks_and_json(self):
        info = ace_shm.session_info(b"", b"")
        self.assertEqual((info["status_name"], info["car"], info["track"], info["session_id"], info["packet"]),
                         ("off", "", "", "0-0-0-", [0]))
        json.dumps(info, allow_nan=False)

    def test_packet_ids(self):
        ph, gr, st = build()
        self.assertEqual(ace_shm.packet_ids(bytes(ph), bytes(gr)), (11, 22))
        self.assertEqual(ace_shm.packet_ids(b"", b""), (0, 0))


class Missing(unittest.TestCase):
    def test_a_missing_mapping_is_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            ace_shm.SharedMemory("Local\\acet_test_missing_%d" % os.getpid(), 16)

    def test_open_source_without_the_blocks_is_file_not_found(self):
        name = "Local\\acet_test_missing_%d" % os.getpid()
        with mock.patch.multiple(ace_shm, PHYSICS_TAG=name + "_p", GRAPHICS_TAG=name + "_g", STATIC_TAG=name + "_s"):
            with self.assertRaises(FileNotFoundError):
                ace_shm.open_source()


@unittest.skipUnless(sys.platform == "win32", "named shared memory is a Windows feature")
class RealMapping(unittest.TestCase):
    def setUp(self):
        k = self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileMappingW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_wchar_p]
        k.CreateFileMappingW.restype = ctypes.c_void_p
        k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handles = []
        self.addCleanup(self.close_handles)

    def close_handles(self):
        for handle in self.handles:
            self.kernel.CloseHandle(handle)

    def make(self, name, data, size=4096):
        handle = self.kernel.CreateFileMappingW(ctypes.c_void_p(-1), None, 0x04, 0, size, name)
        self.assertTrue(handle, "CreateFileMappingW failed")
        self.handles.append(handle)
        view = self.kernel.MapViewOfFile(handle, 0x0002, 0, 0, 0)
        self.assertTrue(view, "MapViewOfFile failed")
        ctypes.memmove(view, data, len(data))
        self.kernel.UnmapViewOfFile(view)

    def test_read_and_read_at_return_the_bytes_of_the_mapping(self):
        name = "Local\\acet_test_%d" % os.getpid()
        data = bytes(i % 251 for i in range(4096))
        self.make(name, data)
        memory = ace_shm.SharedMemory(name, 4096)
        try:
            self.assertEqual(memory.read(), data)
            self.assertEqual(memory.read_at(10, 20), data[10:30])
            self.assertEqual(memory.read_at(4090, 10), data[4090:] + b"\0" * 4)
            self.assertEqual(memory.read_at(5000, 4), b"\0" * 4)
            self.assertEqual(memory.read_at(-1, 4), b"\0" * 4)
            self.assertEqual(memory.read_at(0, 0), b"")
        finally:
            memory.close()
        memory.close()
        self.assertIsNone(memory.view)

    def test_size_cuts_or_pads_the_read(self):
        name = "Local\\acet_test_size_%d" % os.getpid()
        data = bytes(i % 251 for i in range(4096))
        self.make(name, data)
        small, big = ace_shm.SharedMemory(name, 16), ace_shm.SharedMemory(name, 5000)
        whole = ace_shm.SharedMemory(name)
        try:
            self.assertEqual(small.read(), data[:16])
            self.assertEqual(big.read(), data + b"\0" * (5000 - 4096))
            self.assertEqual(whole.read(), data)
        finally:
            for memory in (small, big, whole):
                memory.close()
                memory.close()

    def test_a_source_reads_the_three_blocks_and_closes_twice(self):
        base = "Local\\acet_test_src_%d" % os.getpid()
        ph, gr, st = build()
        self.make(base + "_p", bytes(ph))
        self.make(base + "_g", bytes(gr), size=8192)
        self.make(base + "_s", bytes(st))
        with mock.patch.multiple(ace_shm, PHYSICS_TAG=base + "_p", GRAPHICS_TAG=base + "_g", STATIC_TAG=base + "_s"):
            source = ace_shm.open_source()
        try:
            physics, graphics, static = source.read()
        finally:
            source.close()
        source.close()
        self.assertEqual(physics, bytes(ph))
        self.assertEqual(graphics, bytes(gr)[:sizeof(ace_shm.Graphics)].ljust(sizeof(ace_shm.Graphics), b"\0"))
        self.assertEqual(static, bytes(st))
        self.assertEqual(ace_shm.channels(physics, graphics)["rpm"], 7200)

    def test_a_source_with_one_block_missing_is_file_not_found(self):
        base = "Local\\acet_test_part_%d" % os.getpid()
        ph, gr, st = build()
        self.make(base + "_p", bytes(ph))
        with mock.patch.multiple(ace_shm, PHYSICS_TAG=base + "_p", GRAPHICS_TAG=base + "_g", STATIC_TAG=base + "_s"):
            with self.assertRaises(FileNotFoundError):
                ace_shm.open_source()


class FakeSource:
    def __init__(self):
        ph, gr, st = build()
        self.blocks = (bytes(ph), bytes(gr), bytes(st))
        self.closed = 0

    def read(self):
        return self.blocks

    def close(self):
        self.closed += 1


class FakeClock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def run_main(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ace_shm.main(list(args))
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class Cli(unittest.TestCase):
    def assert_usage(self, *args):
        r = run_tool("ace_shm.py", *args)
        self.assertEqual(r.returncode, 2, args)
        self.assertEqual(r.stdout.strip(), USAGE.strip(), args)
        self.assertEqual(r.stderr, "", args)

    def test_usage_block_is_the_paragraph_after_the_title(self):
        self.assertTrue(USAGE.startswith("usage: python tools/ace_shm.py dump [--wait SECONDS]"), USAGE)
        self.assertNotIn("Exit code", USAGE)

    def test_no_arguments_print_the_usage_block_on_stdout_and_exit_2(self):
        self.assert_usage()

    def test_wrong_arguments_print_the_usage_block_and_exit_2(self):
        for args in (("bogus",), ("dump", "extra"), ("dump", "--bogus"), ("dump", "--wait"), ("dump", "--wait", "abc"),
                     ("dump", "--wait", "-1"), ("dump", "--wait", "nan"), ("--wait", "1")):
            with self.subTest(args=args):
                self.assert_usage(*args)

    def test_the_game_not_running_is_an_error_line_and_exit_1(self):
        clock = FakeClock()
        with mock.patch.object(ace_shm, "open_source", side_effect=FileNotFoundError("x")), mock.patch.object(ace_shm, "time", clock):
            code, out, err = run_main("dump", "--wait", "0")
        self.assertEqual(code, "error: the game is not running (no shared memory)")
        self.assertEqual((out, err, clock.slept), ("", "", []))

    def test_the_game_not_running_through_the_command_line(self):
        code = (
            "import sys; sys.path.insert(0, %r); import ace_shm\n"
            "def missing(): raise FileNotFoundError('x')\n"
            "ace_shm.open_source = missing\n"
            "ace_shm.main(['dump', '--wait', '0'])\n"
        ) % str(TOOLS)
        r = subprocess.run([sys.executable, "-B", "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, "error: the game is not running (no shared memory)\n")

    def test_dump_waits_and_retries_every_half_second_until_the_blocks_appear(self):
        clock, source = FakeClock(), FakeSource()
        with mock.patch.object(ace_shm, "open_source", side_effect=[FileNotFoundError(), FileNotFoundError(), source]), \
                mock.patch.object(ace_shm, "time", clock):
            code, out, err = run_main("dump", "--wait", "2")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(clock.slept, [0.5, 0.5])
        self.assertEqual(source.closed, 1)
        self.assertEqual(set(json.loads(out)), {"info", "channels"})

    def test_dump_gives_up_after_the_wait(self):
        clock = FakeClock()
        with mock.patch.object(ace_shm, "open_source", side_effect=FileNotFoundError()), mock.patch.object(ace_shm, "time", clock):
            code, out, err = run_main("dump", "--wait", "1")
        self.assertEqual(code, "error: the game is not running (no shared memory)")
        self.assertEqual(clock.slept, [0.5, 0.5])

    def test_dump_prints_info_and_channels_as_indented_json(self):
        source = FakeSource()
        with mock.patch.object(ace_shm, "open_source", return_value=source):
            code, out, err = run_main("dump")
        self.assertEqual((code, err), (0, ""))
        data = json.loads(out)
        self.assertEqual(list(data), ["info", "channels"])
        ph, gr, st = build()
        self.assertEqual(data["info"], ace_shm.session_info(bytes(gr), bytes(st)))
        self.assertEqual(sorted(data["channels"]), sorted(CHANNEL_NAMES))
        self.assertEqual(data["channels"]["rpm"], 7200)
        self.assertIn("\n  ", out)
        self.assertEqual(source.closed, 1)

    def test_a_read_error_is_an_error_line_and_the_source_is_closed(self):
        source = FakeSource()
        source.read = mock.Mock(side_effect=OSError("boom"))
        with mock.patch.object(ace_shm, "open_source", return_value=source):
            code, out, err = run_main("dump")
        self.assertEqual(code, "error: boom")
        self.assertEqual(source.closed, 1)


if __name__ == "__main__":
    unittest.main()
