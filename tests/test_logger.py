"""Tests for tools/logger.py and start_logger.bat without the game: Logger.step() driven by a scripted fake source (blocks built from the ace_shm structs), a fake clock and a fake wall clock, session files and the status file in scratch folders, the command line, and the batch file.

The game's shared memory is never opened (the source is always a fake), and the real work folder, logs folder and game folder are never touched.
"""
import contextlib
import datetime
import io
import json
import ntpath
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

from support import ROOT, run_tool

import ace_shm
import logconf
import logger
import tune

USAGE = logger.__doc__.split("\n\n")[1]
BAT = (ROOT / "start_logger.bat").read_text(encoding="ascii")
TUNER_BAT = (ROOT / "start_tuner.bat").read_text(encoding="ascii")

BASE = datetime.datetime(2026, 11, 16, 14, 30, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
BASE_TS = BASE.timestamp()
T0 = 1000.0
FIRST_FILE = "2026-11-16_14-30-05_BMW_M4_CSL.jsonl"
HEADER_KEYS = ["type", "format", "version", "car", "track", "pc", "software", "tuner"]
STATUS_KEYS = ["state", "file", "samples", "started", "updated", "pid"]


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class Wall:
    def __init__(self, clock):
        self.clock = clock

    def __call__(self):
        return BASE + datetime.timedelta(seconds=self.clock.now - T0)


class Source:
    def __init__(self, game):
        self.game, self.closed = game, 0

    def read(self):
        g = self.game
        return bytes(g.ph), bytes(g.gr), bytes(g.st)

    def close(self):
        self.closed += 1


class Game:
    """The three blocks of a running game: change the structs, call tick() for a new packet."""

    def __init__(self):
        self.ph, self.gr, self.st = ace_shm.Physics(), ace_shm.Graphics(), ace_shm.Static()
        self.ph.packetId, self.ph.speedKmh, self.ph.rpms, self.ph.currentMaxRpm = 1, 0.0, 900, 8000
        self.gr.packetId, self.gr.status, self.gr.car_model = 1, 2, b"BMW M4 CSL"
        self.st.sm_version, self.st.ac_evo_version = b"v1.2", b"0.6.1"
        self.st.track, self.st.session, self.st.session_name, self.st.event_id, self.st.session_id = b"Monza", 1, b"Practice", 3, 2
        self.running, self.opened = True, []

    def tick(self):
        self.ph.packetId += 1
        self.gr.packetId += 1

    def open(self):
        if not self.running:
            raise FileNotFoundError("game")
        self.opened.append(Source(self))
        return self.opened[-1]


class LoggerCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.work, self.logs = os.path.join(d.name, "work"), os.path.join(d.name, "logs")
        os.makedirs(self.work)
        self.game, self.clock, self.lines = Game(), Clock(), []
        self.wall = Wall(self.clock)
        self.status_path = os.path.join(self.logs, logconf.STATUS_FILE)
        self.logger = self.make()

    def make(self, **kw):
        args = dict(open_source=self.game.open, clock=self.clock, wall=self.wall, out=self.lines.append, pid=4321)
        args.update(kw)
        lg = logger.Logger(self.work, self.logs, **args)
        self.addCleanup(lg.close)
        return lg

    def config(self, ticked, rate=30):
        tune.save_json(os.path.join(self.work, "log_config.json"), {"version": 1, "rate_hz": rate, "ticked": ticked})

    def drive(self, seconds, tick=True):
        """step() for that many simulated seconds, the clock moving by what step() asks for."""
        end, waits = self.clock.now + seconds, []
        while self.clock.now < end - 1e-9:
            if tick:
                self.game.tick()
            waits.append(self.logger.step())
            self.clock.now += max(waits[-1], 1e-6)
        return waits

    def names(self):
        return sorted(n for n in os.listdir(self.logs) if n.endswith(".jsonl")) if os.path.isdir(self.logs) else []

    def records(self, name=None):
        if self.logger.session is not None:
            self.logger.session.file.flush()
        with open(os.path.join(self.logs, name or self.names()[-1]), encoding="utf-8") as f:
            return [json.loads(line) for line in f.read().splitlines()]

    def samples(self, name=None):
        return [r for r in self.records(name) if r["type"] == "s"]

    def status(self):
        with open(self.status_path, encoding="utf-8") as f:
            return json.load(f)


class TestWaiting(LoggerCase):
    def setUp(self):
        super().setUp()
        self.game.running = False

    def test_without_the_game_it_waits_one_second_and_writes_the_waiting_status(self):
        self.assertEqual(self.logger.step(), logger.WAIT_S)
        self.assertEqual(logger.WAIT_S, 1.0)
        self.assertEqual(self.status(), {"state": "waiting", "file": None, "samples": 0, "started": BASE_TS, "updated": BASE_TS, "pid": 4321})
        self.assertEqual(list(self.status()), STATUS_KEYS)

    def test_waiting_is_printed_once_not_every_tick(self):
        for _ in range(5):
            self.logger.step()
            self.clock.now += 1.0
        self.assertEqual(self.lines, ["waiting for the game ..."])

    def test_the_status_is_written_at_most_once_a_second(self):
        self.logger.step()
        for dt in (0.4, 0.4):
            self.clock.now += dt
            self.logger.step()
            self.assertEqual(self.status()["updated"], BASE_TS)
        self.clock.now += 0.3
        self.logger.step()
        self.assertEqual(self.status()["updated"], BASE_TS + 1.1)

    def test_logconf_reads_the_waiting_status_as_running(self):
        self.logger.step()
        got = logconf.logger_status(self.logs, now=BASE_TS)
        self.assertEqual((got["running"], got["state"], got["file"], got["samples"], got["seconds"]), (True, "waiting", None, 0, None))

    def test_the_game_appearing_prints_game_found_once_and_goes_on(self):
        self.logger.step()
        self.game.running = True
        self.clock.now += 1.0
        for _ in range(3):
            self.game.tick()
            self.logger.step()
            self.clock.now += 0.05
        self.assertEqual(self.lines, ["waiting for the game ...", "game found", "session started: " + self.names()[0]])
        self.assertEqual(len(self.game.opened), 1)

    def test_a_game_in_the_menu_gives_no_session_and_keeps_the_waiting_status_fresh(self):
        self.game.running = True
        self.game.gr.status = 0
        self.assertEqual(self.logger.step(), 0.25)
        self.assertEqual(self.lines, ["game found"])
        self.assertEqual(self.names(), [])
        self.assertEqual(self.status()["state"], "waiting")
        self.clock.now += 1.0
        self.logger.step()
        self.assertEqual(self.status()["updated"], BASE_TS + 1.0)


class TestSessionStart(LoggerCase):
    def test_a_session_needs_live_status_a_car_and_a_track(self):
        for status, car, track in ((3, b"BMW M4 CSL", b"Monza"), (0, b"BMW M4 CSL", b"Monza"), (1, b"BMW M4 CSL", b"Monza"),
                                   (2, b"", b"Monza"), (2, b"BMW M4 CSL", b"")):
            with self.subTest(status=status, car=car, track=track):
                self.game.gr.status, self.game.gr.car_model, self.game.st.track = status, car, track
                self.game.tick()
                self.assertEqual(self.logger.step(), 0.25)
                self.assertEqual(self.names(), [])
        self.game.gr.status, self.game.gr.car_model, self.game.st.track = 2, b"BMW M4 CSL", b"Monza"
        self.game.tick()
        self.logger.step()
        self.assertEqual(self.names(), [FIRST_FILE])
        self.assertEqual(self.lines[-1], "session started: " + FIRST_FILE)

    def test_the_header_has_every_key(self):
        self.config(["limiter", "behaviour.speed"], 60)
        self.logger.step()
        header = self.records()[0]
        self.assertEqual(list(header), HEADER_KEYS)
        self.assertEqual(header, {
            "type": "header", "format": "ace-session-log", "version": 1, "car": "BMW M4 CSL", "track": "Monza",
            "pc": {"date": "2026-11-16", "time": "14:30:05", "utc_offset": "+01:00"},
            "software": {"game_version": "0.6.1", "layout_version": "v1.2", "logger_version": "1.0",
                         "config": {"rate_hz": 60, "ticked": ["limiter", "behaviour.speed"], "once": ["rpm_max"], "live": ["rpm", "speed_kmh"]}},
            "tuner": {"matched": False}})
        self.assertEqual(logger.LOGGER_VERSION, "1.0")

    def test_without_a_config_file_the_header_holds_the_default_choice(self):
        self.logger.step()
        config = self.records()[0]["software"]["config"]
        chan = logconf.load_channels()
        default = logconf.default_config(chan)
        self.assertEqual(config, {"rate_hz": 30, "ticked": default["ticked"], **logconf.selected_channels(chan, default)})
        self.assertEqual(config["once"], [])

    def test_the_config_is_read_when_the_session_starts(self):
        self.config(["behaviour.speed"])
        self.logger.step()
        self.config(["behaviour.rpm"], 60)
        self.game.tick()
        self.clock.now += 0.04
        self.logger.step()
        self.assertEqual(self.records()[0]["software"]["config"]["ticked"], ["behaviour.speed"])
        self.assertEqual(set(self.samples()[-1]), {"type", "t", "speed_kmh"})

    def test_the_car_is_stored_verbatim_and_the_file_is_utf8(self):
        self.game.gr.car_model = "Škoda é (modded)".encode("utf-8")
        self.logger.step()
        self.assertEqual(self.records()[0]["car"], "Škoda é (modded)")
        self.assertEqual(self.names(), ["2026-11-16_14-30-05__koda____modded_.jsonl"])
        with open(os.path.join(self.logs, self.names()[0]), "rb") as f:
            self.assertIn("Škoda é".encode("utf-8"), f.read())

    def test_the_lines_are_compact_json_with_unix_line_ends(self):
        self.logger.step()
        self.logger.close()
        with open(os.path.join(self.logs, self.names()[0]), "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        for line in raw.decode("utf-8").splitlines():
            self.assertEqual(json.dumps(json.loads(line), separators=(",", ":"), ensure_ascii=False), line)

    def test_the_facts_function_gets_the_car_and_the_session_info_and_its_result_is_the_tuner_entry(self):
        calls = []

        def facts(car, info):
            calls.append((car, info))
            return {"matched": True, "tune": "ax01"}

        self.logger = self.make(facts=facts)
        self.logger.step()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "BMW M4 CSL")
        self.assertEqual(calls[0][1]["track"], "Monza")
        self.assertEqual(calls[0][1]["status_name"], "live")
        self.assertEqual(self.records()[0]["tuner"], {"matched": True, "tune": "ax01"})

    def test_facts_that_raise_are_stored_as_an_error_and_logging_goes_on(self):
        def facts(car, info):
            raise RuntimeError("no tune here")

        self.logger = self.make(facts=facts)
        self.logger.step()
        self.assertEqual(self.records()[0]["tuner"], {"matched": False, "error": "no tune here"})
        self.game.tick()
        self.clock.now += 0.04
        self.logger.step()
        self.assertEqual(len(self.samples()), 2)

    def test_the_utc_offset_has_a_sign_hours_and_minutes(self):
        zone = datetime.timezone
        for delta, want in ((datetime.timedelta(hours=1), "+01:00"), (datetime.timedelta(0), "+00:00"),
                            (-datetime.timedelta(hours=5, minutes=30), "-05:30"), (datetime.timedelta(hours=5, minutes=45), "+05:45")):
            with self.subTest(want=want):
                self.assertEqual(logger.utc_offset(BASE.astimezone(zone(delta))), want)


class TestFileNames(LoggerCase):
    def test_the_name_is_the_wall_time_and_the_slug_of_the_car(self):
        self.logger.step()
        self.assertEqual(self.names(), [FIRST_FILE])

    def test_characters_outside_the_safe_set_become_underscores(self):
        self.assertEqual(self.logger.session_name(BASE, "A/B:C*? x"), "2026-11-16_14-30-05_A_B_C___x.jsonl")
        self.assertEqual(self.logger.session_name(BASE, "a.b-c_D9"), "2026-11-16_14-30-05_a.b-c_D9.jsonl")

    def test_the_slug_has_at_most_40_characters_and_an_empty_car_is_car(self):
        self.assertEqual(self.logger.session_name(BASE, "x" * 60), "2026-11-16_14-30-05_" + "x" * 40 + ".jsonl")
        self.assertEqual(self.logger.session_name(BASE, ""), "2026-11-16_14-30-05_car.jsonl")

    def test_an_existing_file_gets_a_number_before_the_extension(self):
        os.makedirs(self.logs)
        for name in (FIRST_FILE, FIRST_FILE.replace(".jsonl", "-2.jsonl")):
            with open(os.path.join(self.logs, name), "w"):
                pass
        self.logger.step()
        self.assertIn(FIRST_FILE.replace(".jsonl", "-3.jsonl"), self.names())
        self.assertEqual(self.lines[-1], "session started: " + FIRST_FILE.replace(".jsonl", "-3.jsonl"))
        self.assertEqual(os.path.getsize(os.path.join(self.logs, FIRST_FILE)), 0)

    def test_the_logs_folder_is_created_when_the_first_session_starts(self):
        self.assertFalse(os.path.exists(self.logs))
        self.logger.step()
        self.assertTrue(os.path.isdir(self.logs))


class TestStaticLine(LoggerCase):
    def setUp(self):
        super().setUp()
        self.config(["limiter", "idle_rpm"])

    def static(self):
        return [r for r in self.records() if r["type"] == "static"]

    def test_a_standing_car_gets_the_static_line_after_two_seconds_once(self):
        self.drive(1.9)
        self.assertEqual(self.static(), [])
        self.drive(5.0)
        lines = self.static()
        self.assertEqual(len(lines), 1)
        self.assertEqual(list(lines[0]), ["type", "t", "moving", "values"])
        self.assertTrue(2.0 <= lines[0]["t"] < 2.1, lines[0]["t"])
        self.assertIs(lines[0]["moving"], False)
        self.assertEqual(lines[0]["values"], {"rpm_max": 8000, "rpm": 900})

    def test_a_moving_car_gets_the_static_line_with_moving_true_after_two_seconds(self):
        self.game.ph.speedKmh = 50.0
        self.drive(1.9)
        self.assertEqual(self.static(), [])
        self.drive(5.0)
        lines = self.static()
        self.assertEqual(len(lines), 1)
        self.assertTrue(2.0 <= lines[0]["t"] < 2.1, lines[0]["t"])
        self.assertIs(lines[0]["moving"], True)

    def test_the_speed_limit_of_standing_is_one_kmh(self):
        self.assertEqual(logger.STANDING_KMH, 1.0)
        self.game.ph.speedKmh = 0.5
        self.drive(2.2)
        self.assertIs(self.static()[0]["moving"], False)

    def test_a_car_that_stops_late_waits_for_two_seconds_of_standing(self):
        self.game.ph.speedKmh = 50.0
        self.drive(1.0)
        self.game.ph.speedKmh = 0.0
        self.drive(1.5)
        self.assertEqual(self.static(), [])
        self.drive(2.0)
        lines = self.static()
        self.assertEqual(len(lines), 1)
        self.assertIs(lines[0]["moving"], False)
        self.assertTrue(3.0 <= lines[0]["t"] < 3.2, lines[0]["t"])

    def test_moving_again_restarts_the_standing_time(self):
        self.drive(1.5)
        self.game.ph.speedKmh = 5.0
        self.drive(0.2)
        self.assertEqual(self.static(), [])
        self.game.ph.speedKmh = 0.0
        self.drive(1.5)
        self.assertEqual(self.static(), [])
        self.drive(1.0)
        self.assertIs(self.static()[0]["moving"], False)

    def test_there_is_no_static_line_without_once_channels(self):
        self.config(["behaviour.speed", "behaviour.rpm"])
        self.logger = self.make()
        self.drive(4.0)
        self.assertEqual({r["type"] for r in self.records()}, {"header", "s"})

    def test_the_static_values_are_rounded(self):
        self.config(["car_state.mass_balance"])
        self.game.ph.cgHeight, self.game.ph.ballast = 0.123456, 12.3456
        self.drive(2.5)
        values = self.static()[0]["values"]
        self.assertEqual(values, {"cg_height": 0.123, "ballast": 12.346})


class TestSamples(LoggerCase):
    def setUp(self):
        super().setUp()
        self.config(["behaviour.speed"])

    def test_the_sample_has_the_type_the_time_and_the_ticked_channels(self):
        self.game.ph.speedKmh = 123.5
        self.logger.step()
        self.assertEqual(self.samples(), [{"type": "s", "t": 0.0, "speed_kmh": 123.5}])
        self.assertEqual(list(self.samples()[0]), ["type", "t", "speed_kmh"])

    def test_30_hz_gives_30_samples_a_second(self):
        self.drive(1.2)
        times = [s["t"] for s in self.samples() if s["t"] < 1.0]
        self.assertEqual(len(times), 30)
        self.assertEqual(times[:4], [0.0, 0.033, 0.067, 0.1])
        for a, b in zip(times, times[1:]):
            self.assertAlmostEqual(b - a, 1 / 30, delta=0.002)

    def test_60_hz_gives_60_samples_a_second(self):
        self.config(["behaviour.speed"], 60)
        self.logger = self.make()
        self.drive(1.2)
        times = [s["t"] for s in self.samples() if s["t"] < 1.0]
        self.assertEqual(len(times), 60)
        self.assertEqual(times[:4], [0.0, 0.017, 0.033, 0.05])
        for a, b in zip(times, times[1:]):
            self.assertAlmostEqual(b - a, 1 / 60, delta=0.002)

    def test_step_asks_for_the_time_to_the_next_sample(self):
        waits = self.drive(0.5)
        self.assertTrue(all(0 < w <= 0.05 for w in waits), waits)
        self.assertAlmostEqual(waits[0], 1 / 30, places=6)

    def test_the_same_physics_packet_is_not_sampled_twice(self):
        self.logger.step()
        self.clock.now += 0.05
        self.logger.step()
        self.assertEqual(len(self.samples()), 1)
        self.game.tick()
        self.logger.step()
        self.assertEqual(len(self.samples()), 2)
        self.assertEqual(self.samples()[1]["t"], 0.05)

    def test_a_new_packet_before_the_next_sample_time_waits_for_it(self):
        self.logger.step()
        self.game.tick()
        self.clock.now += 0.01
        self.assertAlmostEqual(self.logger.step(), 1 / 30 - 0.01, places=6)
        self.assertEqual(len(self.samples()), 1)

    def test_no_samples_while_paused_and_the_session_goes_on_after_it(self):
        self.drive(0.3)
        before = len(self.samples())
        name = self.names()[0]
        self.game.gr.status = 3
        waits = self.drive(2.0)
        self.assertEqual(len(self.samples()), before)
        self.assertEqual(set(waits), {0.25})
        self.game.gr.status = 2
        self.drive(0.3)
        self.assertGreater(len(self.samples()), before)
        self.assertEqual(self.names(), [name])
        self.assertEqual([r["type"] for r in self.records()].count("header"), 1)
        self.assertNotIn("end", {r["type"] for r in self.records()})
        self.assertGreaterEqual(self.samples()[before]["t"], 2.3)

    def test_after_a_gap_of_over_a_second_the_schedule_starts_again_from_now(self):
        self.logger.step()
        self.clock.now += 5.0
        self.game.tick()
        self.logger.step()
        self.assertEqual([s["t"] for s in self.samples()], [0.0, 5.0])
        self.clock.now += 0.001
        self.game.tick()
        self.assertAlmostEqual(self.logger.step(), 1 / 30 - 0.001, places=6)
        self.assertEqual(len(self.samples()), 2)

    def test_values_are_rounded_to_three_digits_also_in_arrays(self):
        self.config(["behaviour.g_forces"])
        self.logger = self.make()
        for i, v in enumerate((0.123456, -0.98765, 0.5)):
            self.game.ph.accG[i] = v
        self.game.gr.g_forces_x, self.game.gr.g_forces_y, self.game.gr.g_forces_z = 1.23456, 2.0, -3.00049
        self.logger.step()
        sample = self.samples()[0]
        self.assertEqual(sample["acc_g"], [0.123, -0.988, 0.5])
        self.assertEqual(sample["g_forces"], [1.235, 2.0, -3.0])

    def test_rounding_touches_floats_only_and_goes_into_lists_and_dicts(self):
        data = {"a": [1.23456, 2, [0.0004, True]], "b": {"c": 0.00049, "d": None}, "e": "x", "f": 3, "g": False, "h": 2.5}
        self.assertEqual(logger.rounded(data), {"a": [1.235, 2, [0.0, True]], "b": {"c": 0.0, "d": None}, "e": "x", "f": 3, "g": False, "h": 2.5})
        self.assertIs(logger.rounded(True), True)
        self.assertIsInstance(logger.rounded(7), int)

    def test_an_empty_selection_gives_a_header_and_an_end_line_only(self):
        self.config([])
        self.logger = self.make()
        self.drive(3.0)
        self.logger.close()
        types = [r["type"] for r in self.records()]
        self.assertEqual(types, ["header", "end"])
        self.assertEqual(self.records()[1]["samples"], 0)

    def test_a_selection_with_once_values_only_gives_header_static_and_end(self):
        self.config(["car_state.gears_fuel"])
        self.logger = self.make()
        waits = self.drive(3.0)
        self.logger.close()
        self.assertEqual([r["type"] for r in self.records()], ["header", "static", "end"])
        self.assertEqual(self.records()[1]["values"], {"max_gears": 0, "fuel_max_l": 0.0})
        self.assertEqual(set(waits), {0.25})


class TestSessionBoundaries(LoggerCase):
    def setUp(self):
        super().setUp()
        self.config(["behaviour.speed"])
        self.drive(0.5)

    def change_and_step(self, change):
        self.clock.now += 1.0
        change()
        self.game.tick()
        at = self.clock.now
        self.logger.step()
        return at

    def assert_switched(self, at, new_car, old_name):
        names = self.names()
        self.assertEqual(len(names), 2, names)
        old, new = self.records(old_name), self.records(names[-1])
        self.assertEqual(old[-1], {"type": "end", "reason": "car, track or session changed", "duration_s": round(at - T0, 3),
                                   "samples": len([r for r in old if r["type"] == "s"])})
        self.assertEqual(new[0]["type"], "header")
        self.assertEqual(new[0]["car"], new_car)
        self.assertEqual(self.lines[-2], "session ended: car, track or session changed, %d samples" % old[-1]["samples"])
        self.assertEqual(self.lines[-1], "session started: " + names[-1])
        self.assertEqual(new[-1]["type"], "s")
        self.assertEqual(new[-1]["t"], 0.0)

    def test_another_car_ends_the_file_and_starts_the_next_in_the_same_step(self):
        old_name = self.names()[0]
        at = self.change_and_step(lambda: setattr(self.game.gr, "car_model", b"Mazda MX-5"))
        self.assert_switched(at, "Mazda MX-5", old_name)

    def test_another_track_does_the_same(self):
        old_name = self.names()[0]
        at = self.change_and_step(lambda: setattr(self.game.st, "track", b"Spa"))
        self.assert_switched(at, "BMW M4 CSL", old_name)
        self.assertEqual(self.records()[0]["track"], "Spa")

    def test_another_session_does_the_same(self):
        old_name = self.names()[0]
        at = self.change_and_step(lambda: setattr(self.game.st, "session_id", 3))
        self.assert_switched(at, "BMW M4 CSL", old_name)

    def test_the_change_waits_while_the_game_is_not_live(self):
        name = self.names()[0]
        self.game.gr.status = 3
        self.game.gr.car_model = b"Mazda MX-5"
        self.drive(1.0)
        self.assertEqual(self.names(), [name])
        self.game.gr.status = 2
        self.drive(0.1)
        self.assertEqual(len(self.names()), 2)
        self.assertEqual(self.records(name)[-1]["type"], "end")

    def test_menus_and_an_empty_car_or_track_do_not_end_the_session(self):
        name = self.names()[0]
        for status, car, track in ((0, b"", b""), (1, b"", b"Monza"), (3, b"BMW M4 CSL", b""), (0, b"BMW M4 CSL", b"Monza")):
            self.game.gr.status, self.game.gr.car_model, self.game.st.track = status, car, track
            self.drive(0.3)
        self.game.gr.status, self.game.gr.car_model, self.game.st.track = 2, b"BMW M4 CSL", b"Monza"
        self.drive(0.3)
        self.assertEqual(self.names(), [name])
        self.assertNotIn("end", {r["type"] for r in self.records()})

    def test_stale_packets_reopen_the_source_and_the_session_goes_on(self):
        name = self.names()[0]
        first = self.game.opened[0]
        self.clock.now += 4.9
        self.logger.step()
        self.assertEqual(len(self.game.opened), 1)
        self.clock.now += 0.2
        self.logger.step()
        self.assertEqual((len(self.game.opened), first.closed), (2, 1))
        self.assertIs(self.logger.source, self.game.opened[1])
        self.assertEqual(self.names(), [name])
        self.assertNotIn("end", {r["type"] for r in self.records()})
        self.assertEqual(self.lines.count("game found"), 1)
        self.clock.now += 4.0
        self.logger.step()
        self.assertEqual(len(self.game.opened), 2)
        self.clock.now += 1.1
        self.logger.step()
        self.assertEqual(len(self.game.opened), 3)
        self.assertEqual(self.names(), [name])

    def test_a_change_of_the_graphics_packet_alone_is_not_stale(self):
        for _ in range(10):
            self.game.gr.packetId += 1
            self.clock.now += 1.0
            self.logger.step()
        self.assertEqual(len(self.game.opened), 1)

    def test_stale_packets_and_no_game_end_the_session_and_go_back_to_waiting(self):
        name = self.names()[0]
        count = len(self.samples())
        self.game.running = False
        self.clock.now += 5.1
        at = self.clock.now
        self.assertEqual(self.logger.step(), logger.WAIT_S)
        self.assertEqual(self.records(name)[-1], {"type": "end", "reason": "game closed", "duration_s": round(at - T0, 3), "samples": count})
        self.assertIsNone(self.logger.source)
        self.assertIsNone(self.logger.session)
        self.assertEqual(self.game.opened[0].closed, 1)
        self.assertEqual(self.lines[-2:], ["session ended: game closed, %d samples" % count, "waiting for the game ..."])
        self.assertEqual(self.status(), {"state": "waiting", "file": None, "samples": 0, "started": BASE_TS, "updated": BASE_TS + at - T0, "pid": 4321})
        self.clock.now += 1.0
        self.logger.step()
        self.assertEqual(self.lines.count("waiting for the game ..."), 1)

    def test_the_game_coming_back_starts_a_new_file(self):
        name = self.names()[0]
        self.game.running = False
        self.clock.now += 5.1
        self.logger.step()
        self.game.running = True
        self.clock.now += 1.0
        self.game.tick()
        self.logger.step()
        self.assertEqual(len(self.names()), 2)
        self.assertEqual(self.lines[-2:], ["game found", "session started: " + self.names()[-1]])
        self.assertEqual(self.records(name)[-1]["reason"], "game closed")
        self.assertEqual(self.lines.count("waiting for the game ..."), 1)

    def test_close_ends_the_session_closes_the_source_and_removes_the_status_file(self):
        name = self.names()[0]
        count = len(self.samples())
        self.assertTrue(os.path.isfile(self.status_path))
        self.clock.now += 0.7
        self.logger.close()
        self.assertEqual(self.records(name)[-1], {"type": "end", "reason": "logger stopped", "duration_s": round(self.clock.now - T0, 3), "samples": count})
        self.assertEqual(self.game.opened[0].closed, 1)
        self.assertFalse(os.path.exists(self.status_path))
        self.assertEqual(self.lines[-1], "session ended: logger stopped, %d samples" % count)
        self.logger.close()
        self.assertEqual(self.game.opened[0].closed, 1)
        self.assertEqual([r["type"] for r in self.records(name)].count("end"), 1)

    def test_close_while_waiting_removes_the_status_file(self):
        self.logger.close()
        game_gone = self.make()
        self.game.running = False
        game_gone.step()
        self.assertTrue(os.path.isfile(self.status_path))
        game_gone.close()
        self.assertFalse(os.path.exists(self.status_path))
        game_gone.close()


class TestStatusFile(LoggerCase):
    def setUp(self):
        super().setUp()
        self.config(["behaviour.speed"])

    def test_the_status_while_logging_has_the_documented_keys(self):
        self.logger.step()
        got = self.status()
        self.assertEqual(list(got), STATUS_KEYS)
        self.assertEqual(got, {"state": "logging", "file": FIRST_FILE, "samples": 1, "started": BASE_TS, "updated": BASE_TS, "pid": 4321})

    def test_it_is_rewritten_every_second_with_the_sample_count(self):
        self.drive(0.9)
        self.assertEqual(self.status()["updated"], BASE_TS)
        self.drive(0.2)
        got = self.status()
        self.assertTrue(1.0 <= got["updated"] - BASE_TS < 1.1, got)
        self.assertTrue(30 <= got["samples"] <= 32, got)
        self.assertEqual(logger.STATUS_EVERY_S, 1.0)

    def test_the_file_is_flushed_with_the_status(self):
        self.drive(1.1)
        with open(os.path.join(self.logs, self.names()[0]), encoding="utf-8") as f:
            on_disk = f.read().splitlines()
        self.assertGreaterEqual(len(on_disk), 30)
        self.assertEqual(json.loads(on_disk[0])["type"], "header")

    def test_logconf_reads_it_as_running_and_logging(self):
        self.drive(1.2)
        got = self.status()
        status = logconf.logger_status(self.logs, now=got["updated"])
        self.assertEqual((status["running"], status["state"], status["file"], status["samples"], status["started"]),
                         (True, "logging", FIRST_FILE, got["samples"], BASE_TS))
        self.assertEqual(status["seconds"], got["updated"] - BASE_TS)
        self.assertFalse(logconf.logger_status(self.logs, now=got["updated"] + 6)["running"])

    def test_the_status_is_written_when_a_session_starts_and_after_a_change(self):
        self.drive(0.2)
        self.clock.now += 0.1
        self.game.gr.car_model = b"Mazda MX-5"
        self.game.tick()
        self.logger.step()
        got = self.status()
        self.assertEqual((got["state"], got["file"], got["samples"]), ("logging", self.names()[-1], 1))
        self.assertNotEqual(got["file"], FIRST_FILE)

    def test_the_status_file_is_written_atomically_without_a_leftover_part_file(self):
        self.drive(1.5)
        self.assertFalse([n for n in os.listdir(self.logs) if n.endswith(".tmp")])


class TestFinishedSession(LoggerCase):
    def test_logconf_lists_the_finished_session_with_car_track_duration_and_samples(self):
        self.config(["behaviour.speed"])
        self.drive(1.0)
        self.clock.now += 0.2
        self.logger.close()
        self.assertEqual(self.records()[-1]["type"], "end")
        [session] = logconf.list_sessions(self.logs)
        self.assertEqual((session["file"], session["car"], session["track"]), (FIRST_FILE, "BMW M4 CSL", "Monza"))
        self.assertEqual(session["duration_s"], self.records()[-1]["duration_s"])
        self.assertEqual(session["samples"], len(self.samples()))
        self.assertGreaterEqual(session["samples"], 30)

    def test_a_file_that_is_still_open_has_a_header_but_no_end_for_logconf(self):
        self.config([])
        self.logger.step()
        self.logger.session.file.flush()
        [session] = logconf.list_sessions(self.logs)
        self.assertEqual((session["car"], session["track"], session["duration_s"], session["samples"]), ("BMW M4 CSL", "Monza", None, None))


class TestRun(LoggerCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(logger, "timer_resolution")
        self.timer = patch.start()
        self.addCleanup(patch.stop)
        self.slept = []
        self.logger = self.make(sleep=self.slept.append)

    def test_run_sleeps_what_step_asks_for_and_stops_quietly_on_ctrl_c(self):
        self.logger.step = mock.Mock(side_effect=[0.5, 0.25, KeyboardInterrupt()])
        self.logger.run()
        self.assertEqual(self.slept, [0.5, 0.25])
        self.assertEqual(self.lines[-1], "stopped")

    def test_run_closes_the_logger_on_ctrl_c_and_asks_for_a_one_millisecond_timer(self):
        self.game.running = False
        self.logger.step()
        self.assertTrue(os.path.isfile(self.status_path))
        self.logger.step = mock.Mock(side_effect=KeyboardInterrupt())
        self.logger.run()
        self.assertFalse(os.path.exists(self.status_path))
        self.assertEqual(self.timer.call_args_list, [mock.call(True), mock.call(False)])

    def test_run_ends_an_open_session_with_logger_stopped(self):
        self.logger.step()
        name = self.names()[0]
        self.logger.step = mock.Mock(side_effect=KeyboardInterrupt())
        self.logger.run()
        self.assertEqual(self.records(name)[-1]["reason"], "logger stopped")
        self.assertEqual(self.lines[-2:], ["stopped", "session ended: logger stopped, 1 samples"])

    def test_run_closes_and_restores_the_timer_after_any_other_error_too(self):
        self.logger.step()
        self.logger.step = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertRaisesRegex(RuntimeError, "boom"):
            self.logger.run()
        self.assertFalse(os.path.exists(self.status_path))
        self.assertEqual(self.timer.call_args_list, [mock.call(True), mock.call(False)])
        self.assertEqual(self.game.opened[0].closed, 1)


class TestTimerResolution(unittest.TestCase):
    def test_a_failure_is_ignored(self):
        with mock.patch.object(logger.ctypes, "WinDLL", side_effect=OSError("no winmm"), create=True):
            logger.timer_resolution(True)
            logger.timer_resolution(False)

    @unittest.skipUnless(sys.platform == "win32", "winmm is a Windows library")
    def test_on_windows_it_asks_winmm_for_one_millisecond_and_gives_it_back(self):
        with mock.patch.object(logger.ctypes, "WinDLL") as dll:
            logger.timer_resolution(True)
            logger.timer_resolution(False)
        dll.assert_called_with("winmm")
        dll.return_value.timeBeginPeriod.assert_called_once_with(1)
        dll.return_value.timeEndPeriod.assert_called_once_with(1)

    def test_elsewhere_it_does_nothing(self):
        with mock.patch.object(logger.sys, "platform", "linux"), mock.patch.object(logger.ctypes, "WinDLL", create=True) as dll:
            logger.timer_resolution(True)
        dll.assert_not_called()


def run_main(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            logger.main(list(args))
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class FakeLogger:
    made, error = [], None

    def __init__(self, work, logs):
        FakeLogger.made.append((work, logs))

    def run(self):
        if FakeLogger.error:
            raise FakeLogger.error


class TestMain(unittest.TestCase):
    def setUp(self):
        FakeLogger.made, FakeLogger.error = [], None
        patch = mock.patch.object(logger, "Logger", FakeLogger)
        patch.start()
        self.addCleanup(patch.stop)

    def assert_usage(self, *args):
        code, out, err = run_main(*args)
        self.assertEqual(code, 2, args)
        self.assertEqual(out.strip(), USAGE.strip(), args)
        self.assertEqual(err, "", args)
        self.assertEqual(FakeLogger.made, [])

    def test_the_usage_block_is_the_paragraph_after_the_title(self):
        self.assertTrue(USAGE.startswith("usage: python tools/logger.py [--work DIR] [--logs DIR]"), USAGE)
        self.assertNotIn("\n\n", USAGE)
        self.assertNotIn("Waits until", USAGE)

    def test_help_and_wrong_arguments_print_the_usage_block_on_stdout_and_exit_2(self):
        for args in (("-h",), ("--help",), ("--bogus",), ("--bogus", "x"), ("extra",), ("--work",), ("--logs",), ("--work", "a", "extra"),
                     ("--port", "8080")):
            with self.subTest(args=args):
                self.assert_usage(*args)

    def test_the_usage_is_the_same_through_the_command_line(self):
        for args in (("--help",), ("--bogus",)):
            r = run_tool("logger.py", *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout.strip(), USAGE.strip(), args)
            self.assertEqual(r.stderr, "", args)

    def test_both_options_are_used_made_absolute_and_the_banner_is_printed(self):
        code, out, err = run_main("--work", os.path.join("rel", "w"), "--logs", os.path.join("rel", "l"))
        self.assertEqual((code, err), (0, ""))
        work, logs = os.path.abspath(os.path.join("rel", "w")), os.path.abspath(os.path.join("rel", "l"))
        self.assertEqual(FakeLogger.made, [(work, logs)])
        self.assertEqual(out, "ACE session logger: waiting for the game (Ctrl+C stops); sessions go to %s\n" % logs)

    def test_the_defaults_are_the_default_work_folder_and_the_logs_folder_of_the_repository(self):
        with mock.patch.dict(os.environ, {"USERPROFILE": os.path.abspath("profile")}), mock.patch.object(os.path, "expandvars", ntpath.expandvars):
            code, out, err = run_main()
            expected_work = tune.work_dir()
        self.assertEqual(code, 0)
        self.assertEqual(FakeLogger.made, [(expected_work, os.path.abspath(logconf.default_logs_dir()))])
        self.assertEqual(os.path.basename(FakeLogger.made[0][1]), "logs")
        self.assertEqual(os.path.basename(FakeLogger.made[0][0]), "ace_modded_cars_work")

    def test_variables_in_the_options_are_expanded(self):
        with mock.patch.dict(os.environ, {"ACET_LOG_VAR": os.path.abspath("scratch")}), mock.patch.object(os.path, "expandvars", ntpath.expandvars):
            run_main("--work", "%ACET_LOG_VAR%\\w", "--logs", "%ACET_LOG_VAR%\\l")
            want = (os.path.abspath(ntpath.expandvars("%ACET_LOG_VAR%\\w")), os.path.abspath(ntpath.expandvars("%ACET_LOG_VAR%\\l")))
        self.assertEqual(FakeLogger.made, [want])
        self.assertNotIn("%", want[0] + want[1])

    def test_an_unexpandable_work_or_logs_folder_is_an_error_line_before_anything_starts(self):
        code, out, err = run_main("--work", "%ACET_NO_SUCH_VAR%/w")
        self.assertTrue(code.startswith("error: cannot expand the work directory"), code)
        code, out, err = run_main("--logs", "%ACET_NO_SUCH_VAR%/l")
        self.assertTrue(code.startswith("error: cannot expand the logs directory"), code)
        self.assertEqual((out, FakeLogger.made), ("", []))

    def test_a_runtime_error_is_an_error_line_and_exit_1_through_the_command_line(self):
        r = run_tool("logger.py", "--work", "%ACET_NO_SUCH_VAR%/w")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertTrue(r.stderr.startswith("error: cannot expand the work directory"), r.stderr)

    def test_an_os_error_while_running_is_an_error_line(self):
        FakeLogger.error = OSError("disk full")
        code, out, err = run_main("--work", "w", "--logs", "l")
        self.assertEqual(code, "error: disk full")
        self.assertEqual(err, "")

    def test_the_real_logger_is_built_with_the_two_folders_and_run(self):
        with mock.patch.object(logger, "Logger") as cls:
            code, out, err = run_main("--work", "w", "--logs", "l")
        cls.assert_called_once_with(os.path.abspath("w"), os.path.abspath("l"))
        cls.return_value.run.assert_called_once_with()


class TestStartBat(unittest.TestCase):
    def test_it_starts_the_logger_script_of_the_repo_from_the_repo_root(self):
        self.assertIn(r"tools\logger.py", BAT)
        self.assertTrue((ROOT / "tools" / "logger.py").is_file())
        self.assertIn(r'cd /d "%~dp0"', BAT)
        self.assertEqual((ROOT / "start_logger.bat").parent, ROOT)
        self.assertLess(BAT.index(r'cd /d "%~dp0"'), BAT.index(r"tools\logger.py"))

    def test_paths_are_relative_to_the_batch_file(self):
        self.assertIn("%~dp0", BAT)
        self.assertNotRegex(BAT, r"(?i)\b[a-z]:\\users\\")

    def test_python_runs_isolated(self):
        self.assertRegex(BAT, r'"%PY%" -I tools\\logger\.py\r?\n')
        self.assertIn("--work", logger.__doc__)
        self.assertIn("--logs", logger.__doc__)

    def test_it_has_the_window_title(self):
        self.assertIn("title ACE Session Logger\n", BAT)

    def test_it_looks_for_the_same_python_as_the_tuner_start_file(self):
        mine = re.search(r'set "PY=(.*?python\.exe)"', BAT).group(1)
        self.assertEqual(mine, re.search(r'set "PY=(.*?python\.exe)"', TUNER_BAT).group(1))
        self.assertEqual(mine, r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe")

    def test_a_missing_python_stops_with_a_message_and_exit_code_1_like_the_tuner_start_file(self):
        block = re.search(r'if not exist "%PY%" \(\n.*?\n\)\n', BAT, re.S).group(0)
        self.assertEqual(block, re.search(r'if not exist "%PY%" \(\n.*?\n\)\n', TUNER_BAT, re.S).group(0))
        self.assertIn("exit /b 1", block)
        self.assertIn("pause", block)

    def test_the_window_stays_open_after_the_logger_stops(self):
        tail = BAT[BAT.index(r"tools\logger.py"):].splitlines()
        self.assertEqual(tail[1:], ["echo.", "echo The session logger has stopped.", "pause"])

    def test_it_starts_no_browser_and_takes_no_port(self):
        self.assertNotIn("start http", BAT)
        self.assertNotIn("PORT", BAT)

    def test_the_file_is_plain_ascii_without_a_byte_order_mark(self):
        raw = (ROOT / "start_logger.bat").read_bytes()
        raw.decode("ascii")
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_every_line_ends_with_crlf(self):
        raw = (ROOT / "start_logger.bat").read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertTrue(raw.endswith(b"\r\n"))

    def test_git_checks_batch_files_out_with_crlf(self):
        self.assertIn("*.bat text eol=crlf", (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines())


if __name__ == "__main__":
    unittest.main()
