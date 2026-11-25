"""Tests for tools/tuner_server.py: the real Handler on a ThreadingHTTPServer in this process (127.0.0.1, port 0, one thread), main() with a stub server, the pure helpers and the CLI conventions.

Work and mods folders are temp dirs. Everything that needs the game or the schemas is stubbed (support.FakeCar replaces tune.load_msg / save_msg, tune.init / tune.apply are recorders, game_running is a switch, subprocess.run fails the test if called); only the committed tuner/web/index.html is read. Server and job threads are stopped in addCleanup.
"""
import ast
import contextlib
import email.message
import http.client
import http.server
import inspect
import io
import json
import ntpath
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse
from unittest import mock

from support import ROOT, FakeCar, Sandbox, mini_catalogue, mini_setting, run_main, run_tool, tmp, usage_cases

import clone_car
import kspkg
import logconf
import tune
import tuner_server as ts

USAGE = ts.__doc__.split("\n\n")[1]
REAL_GAME_RUNNING = ts.game_running
REAL_CATALOGUE = tune.load_catalogue()
GAME_ARGV = ["tasklist", "/FI", "IMAGENAME eq AssettoCorsaEVO.exe", "/NH", "/FO", "CSV"]
STATE_KEYS = {"work", "car", "tune", "default_car", "cars", "base_present", "game_running", "installed", "stock_id_length",
              "default_new_id", "settings_applicable", "settings_hidden", "job", "modded", "default_tune_taken",
              "proposed_new_id", "proposed_suffix", "versions", "base_name", "mod_paths"}
MODDED_KEYS = {"id", "stock", "label", "name_suffix", "default", "installed", "built"}
CAR_KEYS = {"id", "label", "display_name", "extracted", "tested", "new_id", "installed"}
JOB_KEYS = {"kind", "state", "log", "result", "error"}
ROW_KEYS = {"id", "group", "label", "kind", "type", "unit", "description", "verified", "default", "value", "changed",
            "absent", "copies_differ"}
INIT_RESULT = {"present": False, "dir": "/w/ks_x/base/content/cars/ks_x", "files": 3, "dirs": 1, "bytes": 10}
APPLY_RESULT = {"new_id": "ax_x", "tune": "ax_x", "name_suffix": "MY", "build_dir": "/w/ks_x/build/ax_x", "package": "/w/ks_x/build/ax_x/ax_x.kspkg", "size": 7,
                "applied": [{"id": "limiter", "old": 7000, "new": 8000, "files": ["data/engine.carengine", "data/x.car"]}],
                "notes": ["note: from build"], "installed": "/m/ax_x.kspkg", "backup": None,
                "changes": {"since": None, "settings": [{"id": "limiter", "from": 7000, "to": 8000}], "extras": [], "total": 1}}
GS = "content\\cars\\common_phsx\\"
ROAD_A, ROAD_B, SLICK_S = GS + "tyres\\road\\a.tyre", GS + "tyres\\road\\b.tyre", GS + "tyres\\slick\\s.tyre"
SETS_CHOICE = {"sets": [{"front": "game:" + ROAD_A, "rear": "game:" + ROAD_A}, {"front": "game:" + SLICK_S, "rear": "game:" + SLICK_S}], "split": False}
TURBO_KEYS = {"donor", "available", "reason", "donors", "picked", "car", "tune", "has_turbo"}
TWIN = {"car": "ks_b", "label": "Twin B", "count": 2, "kind": "twin turbo", "boost": [0.7, 0.7], "boost_ref": None}
OWN = {"car": "ks_t", "label": "Car T", "count": 1, "kind": "single turbo", "boost": [1.0], "boost_ref": None}
SINGLE = {"car": "ks_a", "label": "Single A", "count": 1, "kind": "single turbo", "boost": [0.9], "boost_ref": None}
SOUND_KEYS = {"slots", "missing", "skipped", "car", "tune"}
SLOT_KEYS = {"options", "own", "selected"}
OPTION_KEYS = {"key", "event", "bank", "optional", "cars"}
TURBO_BANK, BACKFIRE_BANK = "content\\sfx\\turbo.bank", "content\\sfx\\backfire.bank"
TE, BE = "event:/parts/turbos/", "event:/parts/backfires/"
T_NONE, T_RX7 = TE + "turbo_none", TE + "turbo_rx7"
B_A, B_B, B_CLASSIC = BE + "backfire_a", BE + "backfire_b", BE + "backfire_classic#8"
JOB_RUNNING = {"error": "a job is running, wait until it has finished"}


def limiter():
    return mini_setting("limiter", type="int", min=3000, max=12000, targets=[("@engine", "limiter"), ("@car", "engine.limiter", True)])


def aids_off():
    return mini_setting("aids_off", kind="flag", type="bool", value=0, targets=[("@setup", "electronics.tc1")])


def suffix():
    return mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix", ui="header")


def boost():
    return mini_setting("boost", type="float", targets=[("@turbo[0]", "max_boost")])


def tyre_dy(axle):
    return mini_setting("tyre_dy_" + axle, group="Tyres", unit="mu", min=0.5, max=2.5, targets=[("@tyre_" + axle, "modelData.Dy0")])


def audio(event, kind=None, bank=TURBO_BANK, **more):
    e = {"event": event}
    if kind is not None:
        e["type"] = kind
    e.update({"transform": {"scale": {"x": 1.0}}, "bank": bank}, **more)
    return e


def actor_of(*entries):
    return {"car": {"cameras": ["c1"], "audio_events": list(entries), "_order": ["cameras"] + ["audio_events"] * len(entries)}}


def forbidden_host(port):
    return "forbidden host: open the tuner with the address the console prints (http://<address of the PC>:%d/ACESCT/)" % port


def gated(test, fn):
    """A job body for tune.init / tune.apply: records the call, waits for test.gate when one is set, then returns or raises."""
    def stub(*args, **kw):
        test.calls.append((fn, args, kw))
        test.entered.set()
        if test.gate is not None:
            test.gate.wait(10)
        if test.errors.get(fn):
            raise test.errors[fn]
        return dict(INIT_RESULT) if fn == "init" else dict(APPLY_RESULT, new_id=args[2], tune=args[2])
    return stub


def symlink_or_skip(test, target, path):
    try:
        os.symlink(target, path)
    except (OSError, NotImplementedError, AttributeError):
        test.skipTest("symbolic links cannot be created here")


class Env(Sandbox):
    """CONFIG and JOB patched, stdout / stderr captured, game_running / tune.init / tune.apply stubbed, no subprocess."""

    def setUp(self):
        super().setUp()
        self.work, self.mods, self.logs = str(self.d / "work"), str(self.d / "mods"), str(self.d / "logs")
        self.out, self.err = io.StringIO(), io.StringIO()
        self.patch(sys, "stdout", self.out)
        self.patch(sys, "stderr", self.err)
        self.patch_dict(ts.CONFIG, {"port": 0, "work": self.work, "mods": self.mods, "logs": self.logs})
        self.patch_dict(ts.JOB, {"kind": None, "state": "idle", "log": [], "result": None, "error": None})
        self.addCleanup(self.drain)
        self.game_up, self.gate, self.calls, self.errors = False, None, [], {}
        self.entered = threading.Event()
        self.patch(ts, "game_running", lambda: self.game_up)
        self.patch_list(ts.GAME_CHECK, [float("-inf"), False])
        self.patch(tune.subprocess, "run", mock.Mock(side_effect=AssertionError("a subprocess was started")))
        self.patch(tune, "init", gated(self, "init"))
        self.patch(tune, "apply", gated(self, "apply"))
        self.data = {"default": "ks_x", "cars": [{"id": "ks_x", "label": "Car X"}]}
        self.cat = mini_catalogue(limiter(), aids_off(), suffix(), boost())
        self.patch(tune, "load_cars", lambda path=None: self.data)
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)

    def patch_list(self, target, values):
        saved = list(target)
        target[:] = values
        self.addCleanup(target.__setitem__, slice(None), saved)

    def patch_dict(self, target, values):
        p = mock.patch.dict(target, values)
        p.start()
        self.addCleanup(p.stop)

    def drain(self):
        if self.gate is None:
            return
        self.gate.set()
        end = time.monotonic() + 5
        while ts.job_snapshot()["state"] == "running" and time.monotonic() < end:
            time.sleep(0.01)

    def hold_jobs(self):
        self.gate = threading.Event()

    def wait_job(self, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            snap = ts.job_snapshot()
            if snap["state"] != "running":
                return snap
            time.sleep(0.01)
        self.fail("the job did not finish: %r" % ts.job_snapshot())

    def finish_held_job(self):
        self.gate.set()
        return self.wait_job()


class ServerCase(Env):
    """Env plus a running server and request helpers; make_car() builds the stubbed extracted car ks_x."""
    handler = ts.Handler

    def setUp(self):
        super().setUp()
        self.fc = FakeCar(self.work, "ks_x").install(self)
        index = [{"id": "ks_x", "display_name": "Car X", "brand": "B", "year": 1999},
                 {"id": "ks_y", "display_name": "Car Y", "brand": "B", "year": 2000}]
        self.write(os.path.join(self.work, "cars_index.json"), index)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = self.server.server_address[1]
        ts.CONFIG["port"] = self.port
        self.host = "127.0.0.1:%d" % self.port
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.001}, daemon=True)
        thread.start()
        self.addCleanup(self.stop_server, thread)

    def stop_server(self, thread):
        self.server.shutdown()
        self.server.server_close()
        thread.join(5)

    def make_car(self):
        gp = self.fc.game_path
        self.car = {"engine_path": gp("data/engine.carengine"), "stock_setup": gp("data/setup.carsetup"), "engine": {"limiter": 7000}}
        self.engine = {"limiter": 7000, "turbos_to_load": []}
        self.setup = {"electronics": {"tc1": 2}}
        self.fc.add("data/x.car", self.car)
        self.fc.add("data/engine.carengine", self.engine)
        self.fc.add("data/setup.carsetup", self.setup)
        self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_x", "display_name": "Car X", "brand": "Brand", "year": 1999})

    def state_file(self, car="ks_x"):
        return tune.state_path(self.work, car)

    def saved_state(self):
        with open(self.state_file(), encoding="utf-8") as f:
            return json.load(f)

    def request(self, method, path, body=None, host=None, headers=None, post_headers=True, prefix=True):
        """One request on a new connection; the path gets the base path /ACESCT unless it starts with it or prefix=False;
        host=False sends no Host header, a headers value of None drops that header."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            if prefix and not path.startswith(ts.BASE_PATH):
                path = ts.BASE_PATH + path
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            send = {}
            if host is not False:
                send["Host"] = self.host if host is None else host
            if method == "POST" and post_headers:
                send.update({"X-Tuner": "1", "Content-Type": "application/json"})
            data = None
            if body is not None:
                data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                send["Content-Length"] = str(len(data))
            send.update(headers or {})
            for key, value in send.items():
                if value is not None:
                    conn.putheader(key, value)
            conn.endheaders(data)
            resp = conn.getresponse()
            return Reply(resp.status, resp.msg, resp.read())
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, {} if body is None else body, **kw)


class Reply:
    def __init__(self, status, headers, data):
        self.status, self.headers, self.data = status, headers, data

    @property
    def json(self):
        return json.loads(self.data.decode("utf-8"))


# -------------------------------------------------------------------------------------------------- routes and status codes
class TestRoutes(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_route_tables(self):
        self.assertEqual(sorted(ts.GET_ROUTES), ["/api/garage", "/api/groups", "/api/log_ai_command", "/api/log_config", "/api/log_file",
                                                 "/api/log_sessions", "/api/log_status",
                                                 "/api/settings", "/api/sounds", "/api/state", "/api/turbo", "/api/tyre", "/api/tyre_index", "/api/tyres"])
        self.assertEqual(sorted(ts.POST_ROUTES), ["/api/apply", "/api/duplicate", "/api/garage_reset", "/api/garage_set", "/api/init",
                                                  "/api/log_config_reset", "/api/log_config_set", "/api/log_copy", "/api/logger_start", "/api/logger_stop", "/api/reset_all", "/api/set", "/api/sound_reset", "/api/sound_set", "/api/turbo_reset",
                                                  "/api/turbo_set", "/api/tyre_delete", "/api/tyre_new", "/api/tyre_rename",
                                                  "/api/tyre_reset", "/api/tyre_set", "/api/tyre_source", "/api/tyre_unset", "/api/unset",
                                                  "/api/version_add", "/api/version_lock", "/api/version_rename", "/api/version_unlock"])
        self.assertEqual(ts.ACCEPTED, ("/api/init", "/api/apply"))
        self.assertEqual(ts.QUERY_ROUTES, ("/api/tyre", "/api/log_file"))
        self.assertTrue(set(ts.QUERY_ROUTES) <= set(ts.GET_ROUTES))
        self.assertEqual(ts.LOCAL_ROUTES, ("/api/log_copy",))
        self.assertTrue(set(ts.LOCAL_ROUTES) <= set(ts.POST_ROUTES))

    def test_the_index_page_is_served_from_the_repo_file(self):
        r = self.get("/")
        with open(ts.INDEX, "rb") as f:
            self.assertEqual((r.status, r.data), (200, f.read()))
        self.assertEqual(r.headers.get("Content-Type"), "text/html; charset=utf-8")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")
        self.assertEqual(r.headers.get("Content-Length"), str(len(r.data)))

    def test_the_page_ignores_a_query(self):
        self.assertEqual(self.get("/?car=ks_x").status, 200)

    def test_state_is_json_with_the_documented_keys(self):
        r = self.get("/api/state")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control")),
                         (200, "application/json; charset=utf-8", "no-store"))
        self.assertEqual(set(r.json), STATE_KEYS)
        self.assertEqual(r.json["job"], {"kind": None, "state": "idle", "log": [], "result": None, "error": None})

    def test_settings_is_a_json_list_of_rows(self):
        r = self.get("/api/settings")
        self.assertEqual((r.status, r.headers.get("Content-Type")), (200, "application/json; charset=utf-8"))
        self.assertIsInstance(r.json, list)
        self.assertEqual([row["id"] for row in r.json], ["limiter", "aids_off", "name_suffix"])

    def test_post_routes_answer_json_with_their_documented_shape(self):
        s = self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.assertEqual((s.status, set(s.json)), (200, {"row", "warnings"}))
        u = self.post("/api/unset", {"id": "limiter"})
        self.assertEqual((u.status, set(u.json)), (200, {"row"}))
        r = self.post("/api/reset_all")
        self.assertEqual((r.status, r.json), (200, {"ok": True}))

    def test_job_routes_answer_202_started(self):
        i = self.post("/api/init")
        self.assertEqual((i.status, i.json), (202, {"job": "started"}))
        self.wait_job()
        a = self.post("/api/apply", {"tune": "draft"})
        self.assertEqual((a.status, a.json), (202, {"job": "started"}))

    def test_unknown_paths_are_404_json(self):
        for path in ("/api/nothing", "/index.html", "/api/state/", "/favicon.svg", "/api/set", "/api"):
            with self.subTest(path):
                r = self.get(path)
                self.assertEqual((r.status, r.json), (404, {"error": "not found"}))

    def test_a_get_route_is_not_a_post_route_and_back(self):
        self.assertEqual(self.post("/api/state").status, 404)
        self.assertEqual(self.post("/").status, 404)
        self.assertEqual(self.get("/api/reset_all").status, 404)

    def test_the_route_of_the_removed_install_all_tested_cars_button_is_404(self):
        r = self.post("/api/install_tested")
        self.assertEqual((r.status, r.json), (404, {"error": "not found"}))
        self.assertEqual(ts.job_snapshot()["state"], "idle")

    def test_traversal_attempts_are_404_and_never_read_a_file(self):
        for path in ("/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/..%2f..%2fetc%2fpasswd", "/api/../../etc/passwd",
                     "/static/../tools/tuner_server.py", "/tools/tuner_server.py", "/tuner/web/index.html", "/%00",
                     "/....//....//etc/passwd", "/%252e%252e/etc/passwd"):
            with self.subTest(path):
                r = self.get(path)
                self.assertEqual((r.status, r.json), (404, {"error": "not found"}))
                self.assertNotIn(b"root:", r.data)

    def test_other_methods_are_405_with_a_json_error_and_the_allow_header(self):
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method):
                r = self.request(method, "/api/set")
                self.assertEqual((r.status, r.json), (405, {"error": "method not allowed"}))
                self.assertEqual((r.headers.get("Allow"), r.headers.get("Content-Type")), ("GET, POST", "application/json; charset=utf-8"))
        self.assertEqual(self.request("PUT", "/api/set").headers.get("Access-Control-Allow-Origin"), None)

    def test_head_and_options_are_405_with_the_allow_header_and_the_framing_headers(self):
        for method in ("HEAD", "OPTIONS"):
            with self.subTest(method):
                r = self.request(method, "/")
                self.assertEqual(r.status, 405)
                self.assertEqual((r.headers.get("Allow"), r.headers.get("X-Frame-Options")), ("GET, POST", "DENY"))
                self.assertIn("frame-ancestors", r.headers.get("Content-Security-Policy", ""))
                self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), None)
        self.assertEqual(self.request("HEAD", "/").data, b"")

    def test_an_unexpected_exception_is_a_500_with_only_the_class_name(self):
        def boom(car, tune_id):
            raise RuntimeError("secret detail")
        with mock.patch.dict(ts.GET_ROUTES, {"/api/state": boom}):
            r = self.get("/api/state")
        self.assertEqual((r.status, r.json), (500, {"error": "internal error: RuntimeError"}))
        self.assertIn("RuntimeError: secret detail", self.err.getvalue())

    def test_value_and_os_errors_are_a_500_with_their_text(self):
        for exc in (ValueError("bad stock info"), OSError("disk gone")):
            def boom(car, tune_id, exc=exc):
                raise exc
            with self.subTest(type(exc).__name__), mock.patch.dict(ts.GET_ROUTES, {"/api/state": boom}):
                r = self.get("/api/state")
                self.assertEqual((r.status, r.json), (500, {"error": str(exc)}))


class TestBasePath(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def raw(self, path, **kw):
        return self.get(path, prefix=False, **kw)

    def test_the_base_path_is_fixed(self):
        self.assertEqual(ts.BASE_PATH, "/ACESCT")

    def test_the_page_is_served_at_the_base_path_with_a_slash(self):
        r = self.raw("/ACESCT/")
        with open(ts.INDEX, "rb") as f:
            self.assertEqual((r.status, r.data), (200, f.read()))
        self.assertEqual(r.headers.get("Content-Type"), "text/html; charset=utf-8")
        self.assertEqual(self.raw("/ACESCT/?car=ks_x").status, 200)

    def test_the_base_path_without_a_slash_is_a_301_to_the_page(self):
        for path in ("/ACESCT", "/ACESCT?car=ks_x"):
            with self.subTest(path):
                r = self.raw(path)
                self.assertEqual((r.status, r.headers.get("Location"), r.data), (301, "/ACESCT/", b""))

    def test_the_root_is_a_302_to_the_page(self):
        for path in ("/", "/?car=ks_x"):
            with self.subTest(path):
                r = self.raw(path)
                self.assertEqual((r.status, r.headers.get("Location"), r.data), (302, "/ACESCT/", b""))

    def test_the_redirects_carry_the_framing_headers_and_no_cors_headers(self):
        for path in ("/", "/ACESCT"):
            with self.subTest(path):
                r = self.raw(path)
                self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
                self.assertIn("frame-ancestors 'none'", r.headers.get("Content-Security-Policy", ""))
                self.assertEqual(r.headers.get("Cache-Control"), "no-store")
                self.assertEqual([h for h in r.headers if h.lower().startswith("access-control")], [])

    def test_the_redirects_check_the_host_first(self):
        for path in ("/", "/ACESCT"):
            with self.subTest(path):
                r = self.raw(path, host="evil.example")
                self.assertEqual((r.status, r.json, r.headers.get("Location")), (403, {"error": forbidden_host(self.port)}, None))

    def test_the_api_lives_below_the_base_path_only(self):
        r = self.raw("/ACESCT/api/state")
        self.assertEqual((r.status, set(r.json)), (200, STATE_KEYS))
        r = self.raw("/api/state")
        self.assertEqual((r.status, r.json), (404, {"error": "not found"}))
        r = self.request("POST", "/api/set", {"id": "limiter", "value": "8000"}, prefix=False)
        self.assertEqual((r.status, r.json), (404, {"error": "not found"}))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_every_other_path_is_404_json(self):
        for path in ("/ACESCT2", "/ACESCT2/", "/ACESCTx/api/state", "/ACESCT/x/api/state", "/acesct/", "/acesct/api/state", "/ACESCT//api/state",
                     "/ACESCT/api", "/ACESCT/api/state/", "/ACESCT/index.html", "/ACESCT/ACESCT/", "/index.html", "/api/groups"):
            with self.subTest(path):
                r = self.raw(path)
                self.assertEqual((r.status, r.json), (404, {"error": "not found"}))

    def test_a_post_to_the_page_or_a_redirect_is_404(self):
        for path in ("/", "/ACESCT", "/ACESCT/"):
            with self.subTest(path):
                self.assertEqual(self.request("POST", path, {}, prefix=False).status, 404)

    def test_the_quiet_poll_filter_matches_the_prefixed_state_path(self):
        self.assertEqual(self.raw("/ACESCT/api/state").status, 200)
        self.assertEqual(self.raw("/ACESCT/api/state?car=ks_x").status, 200)
        self.assertNotIn("/api/state", self.err.getvalue())
        self.assertEqual(self.raw("/api/state").status, 404)
        self.assertIn('"GET /api/state HTTP/1.1" 404 -', self.err.getvalue())


STATIC = {"apple-touch-icon.png": "image/png", "icon-192.png": "image/png", "icon-512.png": "image/png", "favicon.png": "image/png",
          "favicon.ico": "image/x-icon", "manifest.webmanifest": "application/manifest+json"}


class TestStaticFiles(ServerCase):
    def file(self, name):
        return (ROOT / "tuner" / "web" / name).read_bytes()

    def test_the_table_holds_exactly_the_six_files_of_the_web_folder(self):
        self.assertEqual({k: v[1] for k, v in ts.STATIC_FILES.items()}, {"/" + k: v for k, v in STATIC.items()})
        self.assertEqual({k: v[0].name for k, v in ts.STATIC_FILES.items()}, {"/" + k: k for k in STATIC})
        for path, _ in ts.STATIC_FILES.values():
            self.assertEqual(path.parent, ts.INDEX.parent)
            self.assertTrue(path.is_file(), path)

    def test_each_file_is_served_below_the_base_path_with_its_content_type_and_bytes(self):
        for name, ctype in STATIC.items():
            with self.subTest(name):
                r = self.get("/" + name)
                self.assertEqual((r.status, r.headers.get("Content-Type"), r.data), (200, ctype, self.file(name)))
                self.assertEqual(r.headers.get("Content-Length"), str(len(r.data)))
                self.assertEqual(r.headers.get_all("Cache-Control"), ["no-store"])
                self.assertGreater(len(r.data), 100)

    def test_the_answers_carry_the_framing_headers_and_no_cors_headers(self):
        for name in STATIC:
            with self.subTest(name):
                r = self.get("/" + name)
                self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
                self.assertIn("frame-ancestors 'none'", r.headers.get("Content-Security-Policy", ""))
                self.assertEqual([h for h in r.headers if h.lower().startswith("access-control")], [])

    def test_a_query_is_ignored(self):
        self.assertEqual(self.get("/icon-192.png?v=2").data, self.file("icon-192.png"))

    def test_every_other_file_name_is_404_json(self):
        for path in ("/ACESCT/secret.txt", "/ACESCT/../x", "/ACESCT/icon-192.png/extra", "/ACESCT/ICON-192.PNG", "/ACESCT/icon-192.png/",
                     "/ACESCT//icon-192.png", "/ACESCT/%69con-192.png", "/ACESCT/icon-192.png%00", "/ACESCT/..%2ficon-192.png",
                     "/ACESCT/../tuner/web/icon-192.png", "/ACESCT/icons/icon-192.png", "/ACESCT/manifest.json", "/ACESCT/favicon.svg",
                     "/ACESCT/icon-180.png", "/ACESCT/web/icon-192.png", "/ACESCT/icon-192.png.bak", "/ACESCT/index.html",
                     "/ACESCT/tune.py", "/icon-192.png", "/favicon.ico", "/manifest.webmanifest", "/apple-touch-icon.png"):
            with self.subTest(path):
                r = self.get(path, prefix=False)
                self.assertEqual((r.status, r.json), (404, {"error": "not found"}))

    def test_the_host_is_checked(self):
        for name in STATIC:
            with self.subTest(name):
                r = self.get("/" + name, host="evil.example")
                self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))
                self.assertEqual(self.get("/" + name, host=False).status, 403)
        self.assertEqual(self.get("/icon-192.png", host="localhost:%d" % self.port).status, 200)

    def test_a_post_is_404(self):
        for name in STATIC:
            with self.subTest(name):
                r = self.post("/" + name)
                self.assertEqual((r.status, r.json), (404, {"error": "not found"}))

    def test_head_is_405_as_for_the_page(self):
        r = self.request("HEAD", "/icon-192.png")
        self.assertEqual((r.status, r.headers.get("Allow"), r.data), (405, "GET, POST", b""))

    def test_a_missing_file_is_a_500_json_error(self):
        with mock.patch.dict(ts.STATIC_FILES, {"/icon-192.png": (self.d / "gone.png", "image/png")}):
            r = self.get("/icon-192.png")
        self.assertEqual(r.status, 500)
        self.assertEqual(set(r.json), {"error"})

    def test_the_page_is_still_html_and_json_is_still_json(self):
        self.assertEqual(self.get("/").headers.get("Content-Type"), "text/html; charset=utf-8")
        self.assertEqual(self.get("/api/nothing").headers.get("Content-Type"), "application/json; charset=utf-8")


ICON_SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512, "favicon.png": 32}


def png_header(data):
    """(width, height, bit depth, colour type) of a PNG whose first chunk after the signature is IHDR."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "signature"
    length, kind = struct.unpack(">I4s", data[8:16])
    assert (length, kind) == (13, b"IHDR"), (length, kind)
    width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, depth, colour


class TestIconFiles(unittest.TestCase):
    WEB = ROOT / "tuner" / "web"

    def test_each_png_has_the_signature_and_an_ihdr_of_its_size_in_8_bit_rgb(self):
        for name, size in ICON_SIZES.items():
            with self.subTest(name):
                self.assertEqual(png_header((self.WEB / name).read_bytes()), (size, size, 8, 2))

    def test_the_ico_has_the_header_of_one_image_that_is_a_32_pixel_png(self):
        ico = (self.WEB / "favicon.ico").read_bytes()
        self.assertEqual(ico[:6], b"\x00\x00\x01\x00\x01\x00")
        width, height = ico[6], ico[7]
        size, offset = struct.unpack("<II", ico[14:22])
        self.assertEqual((width, height), (32, 32))
        self.assertEqual(offset + size, len(ico))
        self.assertEqual(png_header(ico[offset:offset + size]), (32, 32, 8, 2))

    def test_the_manifest_is_json_and_names_the_two_app_icons(self):
        manifest = json.loads((self.WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        sources = [icon["src"] for icon in manifest["icons"]]
        self.assertIn("icon-192.png", sources)
        self.assertIn("icon-512.png", sources)


class ForeignHandler(ts.Handler):
    """A Handler whose client always comes from a public address."""
    @property
    def client_address(self):
        return ("8.8.8.8", 4711)

    @client_address.setter
    def client_address(self, value):
        pass


class TestForeignClient(ServerCase):
    handler = ForeignHandler

    def setUp(self):
        super().setUp()
        self.make_car()

    def test_a_public_client_is_403_for_every_route_and_changes_nothing(self):
        for r in (self.get("/"), self.get("/api/state"), self.get("/nothing"), self.get("/", prefix=False), self.get("/ACESCT", prefix=False),
                  self.post("/api/set", {"id": "limiter", "value": "8000"}), self.post("/api/init")):
            self.assertEqual((r.status, r.json), (403, {"error": "forbidden client address"}))
            self.assertEqual([h for h in r.headers if h.lower().startswith("access-control")], [])
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertEqual(ts.job_snapshot()["state"], "idle")

    def test_the_client_address_is_checked_before_the_host(self):
        r = self.get("/api/state", host="evil.example")
        self.assertEqual((r.status, r.json), (403, {"error": "forbidden client address"}))
        self.assertEqual(self.get("/api/state", host=False).json, {"error": "forbidden client address"})

    def test_a_public_client_gets_no_static_file(self):
        for name in STATIC:
            with self.subTest(name):
                r = self.get("/" + name)
                self.assertEqual((r.status, r.json), (403, {"error": "forbidden client address"}))
                self.assertNotEqual(r.data, (ROOT / "tuner" / "web" / name).read_bytes())


# -------------------------------------------------------------------------------------------------- request checks
class TestHostAndHeaders(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_the_two_allowed_hosts_are_accepted(self):
        for host in ("127.0.0.1:%d", "localhost:%d", "LOCALHOST:%d"):
            with self.subTest(host):
                self.assertEqual(self.get("/api/state", host=host % self.port).status, 200)

    def test_every_other_host_is_403(self):
        for host in ("evil.example", "evil.example:%d" % self.port, "127.0.0.1", "localhost", "[::1]:%d" % self.port,
                     "127.0.0.1:%d.evil.example" % self.port, "127.0.0.1:%d" % (self.port + 1), "0.0.0.0:%d" % self.port,
                     ""):
            with self.subTest(host):
                r = self.get("/api/state", host=host)
                self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))

    def test_private_hosts_with_the_port_and_the_machine_name_are_accepted(self):
        with mock.patch.object(ts.socket, "gethostname", return_value="MyPC"):
            for host in ("localhost:%d", "127.0.0.1:%d", "127.1.2.3:%d", "192.168.1.20:%d", "10.0.0.5:%d", "172.16.0.1:%d", "172.31.255.1:%d",
                         "MyPC:%d", "MYPC:%d", "mypc:%d"):
                with self.subTest(host):
                    self.assertEqual(self.get("/api/state", host=host % self.port).status, 200)

    def test_other_hosts_are_403_with_the_machine_name_set(self):
        with mock.patch.object(ts.socket, "gethostname", return_value="MyPC"):
            for host in ("localhost:%d" % (self.port + 1), "192.168.1.20:%d" % (self.port + 1), "192.168.1.20", "MyPC", "MyPC:%d" % (self.port + 1),
                         "evil.example:%d" % self.port, "8.8.8.8:%d" % self.port, "172.32.0.1:%d" % self.port, "100.64.0.1:%d" % self.port,
                         "[::1]:%d" % self.port, "192.168.1.20.evil.example:%d" % self.port, "MyPC.evil.example:%d" % self.port,
                         "MyPC.local:%d" % self.port, "other-pc:%d" % self.port, "0.0.0.0:%d" % self.port, ":%d" % self.port):
                with self.subTest(host):
                    r = self.get("/api/state", host=host)
                    self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))

    def test_a_missing_host_header_is_403(self):
        self.assertEqual(self.get("/api/state", host=False).status, 403)

    def test_the_host_is_checked_for_the_page_posts_and_unknown_paths_too(self):
        self.assertEqual(self.get("/", host="evil.example").status, 403)
        self.assertEqual(self.get("/nothing", host="evil.example").status, 403)
        self.assertEqual(self.post("/api/reset_all", host="evil.example").status, 403)
        self.assertFalse(os.path.exists(self.state_file()))

    def test_a_post_without_x_tuner_is_403_and_changes_nothing(self):
        r = self.post("/api/set", {"id": "limiter", "value": "8000"}, headers={"X-Tuner": None})
        self.assertEqual((r.status, r.json), (403, {"error": "missing header X-Tuner: 1"}))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_x_tuner_must_be_exactly_1(self):
        for value in ("0", "true", "", "1 "):
            with self.subTest(repr(value)):
                self.assertEqual(self.post("/api/reset_all", headers={"X-Tuner": value}).status, 403)

    def test_a_post_with_another_content_type_is_415(self):
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "application/jsonx", None):
            with self.subTest(ctype):
                r = self.post("/api/set", {"id": "limiter", "value": "8000"}, headers={"Content-Type": ctype})
                self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_content_type_parameters_and_case_are_accepted(self):
        for ctype in ("application/json; charset=utf-8", "Application/JSON", "application/json ;charset=utf-8"):
            with self.subTest(ctype):
                self.assertEqual(self.post("/api/reset_all", headers={"Content-Type": ctype}).status, 200)

    def test_the_post_headers_are_checked_before_the_route(self):
        self.assertEqual(self.post("/api/nothing", headers={"X-Tuner": None}).status, 403)
        self.assertEqual(self.post("/api/nothing").status, 404)

    def test_a_get_needs_no_x_tuner_and_no_content_type(self):
        self.assertEqual(self.get("/api/state").status, 200)

    def test_no_cors_headers_are_ever_sent(self):
        for r in (self.get("/api/state"), self.get("/api/state", host="evil.example"), self.get("/nothing")):
            self.assertEqual([h for h in r.headers if h.lower().startswith("access-control")], [])


class TestBodies(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def set_raw(self, raw, **kw):
        return self.request("POST", "/api/set", raw, **kw)

    def test_malformed_json_is_400(self):
        for raw in (b"{bad", b'{"id": "limiter", "value": }', b"\xff\xfe{}", b"'x'", b"{} {}"):
            with self.subTest(raw):
                r = self.set_raw(raw)
                self.assertEqual((r.status, r.json), (400, {"error": "body is not valid JSON"}))

    def test_a_deeply_nested_body_is_400_and_not_an_internal_error(self):
        for raw in (b"[" * 60000, b"[" * 30000 + b"]" * 30000):
            with self.subTest(raw[:6]):
                r = self.set_raw(raw)
                self.assertEqual((r.status, r.json), (400, {"error": "body is not valid JSON"}))
        self.assertNotIn("Traceback", self.err.getvalue())

    def test_json_that_is_not_an_object_is_400(self):
        for raw in (b"[1, 2]", b"5", b'"x"', b"null", b"true"):
            with self.subTest(raw):
                r = self.set_raw(raw)
                self.assertEqual((r.status, r.json), (400, {"error": "body must be a JSON object"}))

    def test_an_empty_or_blank_body_is_an_empty_object(self):
        for raw in (b"", b"  \n"):
            with self.subTest(raw):
                r = self.set_raw(raw)
                self.assertEqual((r.status, r.json["error"]), (400, "need id (text) and value (text, number or true/false)"))
        self.assertEqual(self.request("POST", "/api/reset_all", None).status, 200)

    def test_wrong_field_types_are_400(self):
        for body in ({"id": 5, "value": "1"}, {"id": None, "value": "1"}, {"value": "1"}, {"id": "limiter"},
                     {"id": "limiter", "value": None}, {"id": "limiter", "value": [1]}, {"id": "limiter", "value": {"a": 1}},
                     {"id": ["limiter"], "value": 1}):
            with self.subTest(body):
                r = self.post("/api/set", body)
                self.assertEqual((r.status, r.json), (400, {"error": "need id (text) and value (text, number or true/false)"}))
        for body in ({"id": 5}, {}, {"id": None}):
            with self.subTest(body):
                self.assertEqual(self.post("/api/unset", body).json, {"error": "need id (text)"})
        self.assertFalse(os.path.exists(self.state_file()))

    def test_value_types_text_number_and_bool_are_accepted(self):
        for value in ("8000", 8000):
            with self.subTest(repr(value)):
                self.assertEqual(self.post("/api/set", {"id": "limiter", "value": value}).status, 200)
        self.assertEqual(self.post("/api/set", {"id": "aids_off", "value": True}).status, 200)

    def test_the_body_limit_is_65536_bytes(self):
        self.assertEqual(ts.MAX_BODY, 65536)
        pad = b" " * (ts.MAX_BODY - len(b'{"id": "limiter", "value": 8000}'))
        raw = b'{"id": "limiter", "value": 8000}' + pad
        self.assertEqual(len(raw), 65536)
        r = self.set_raw(raw)
        self.assertEqual((r.status, r.json["row"]["value"]), (200, 8000))

    def test_a_longer_body_is_413_before_it_is_read(self):
        r = self.request("POST", "/api/set", None, headers={"Content-Length": str(ts.MAX_BODY + 1)})
        self.assertEqual((r.status, r.json), (413, {"error": "request body too large"}))
        big = self.request("POST", "/api/set", None, headers={"Content-Length": "100000000"})
        self.assertEqual(big.status, 413)
        self.assertFalse(os.path.exists(self.state_file()))

    def test_a_bad_content_length_is_400(self):
        r = self.request("POST", "/api/set", None, headers={"Content-Length": "abc"})
        self.assertEqual((r.status, r.json), (400, {"error": "bad Content-Length"}))
        r = self.request("POST", "/api/set", None, headers={"Content-Length": "-5"})
        self.assertEqual(r.status, 400)

    def test_a_non_ascii_value_survives_the_json_round_trip(self):
        r = self.post("/api/set", {"id": "name_suffix", "value": "_M\u00dcNCHEN"})
        self.assertEqual(r.json["row"]["value"], "_M\u00dcNCHEN")
        self.assertEqual(self.saved_state(), {"name_suffix": "_M\u00dcNCHEN"})


    def test_a_suffix_is_saved_trimmed_with_inner_space_runs_collapsed(self):
        r = self.post("/api/set", {"id": "name_suffix", "value": "  Super   charged "})
        self.assertEqual((r.status, r.json["row"]["value"]), (200, "Super charged"))
        self.assertEqual(self.saved_state(), {"name_suffix": "Super charged"})

    def test_a_suffix_of_only_spaces_or_with_a_tab_is_refused(self):
        for value in ("   ", "a	b"):
            with self.subTest(value):
                r = self.post("/api/set", {"id": "name_suffix", "value": value})
                self.assertEqual((r.status, r.json), (400, {"error": "name_suffix expects 1 to 30 characters without control characters"}))


class TestCarIds(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_an_unknown_car_in_the_query_is_400_for_both_get_routes(self):
        for path in ("/api/state?car=../x", "/api/state?car=nope", "/api/settings?car=nope", "/api/state?car=%2e%2e%2fx",
                     "/api/settings?car=ks_x/../ks_y"):
            with self.subTest(path):
                r = self.get(path)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith("unknown car"), r.json)

    def test_an_unknown_car_in_the_body_is_400_for_every_post_route(self):
        for path in ("/api/set", "/api/unset", "/api/reset_all", "/api/init", "/api/apply"):
            with self.subTest(path):
                r = self.post(path, {"car": "../x", "id": "limiter", "value": "1", "mode": "update"})
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith("unknown car"), r.json)
        self.assertFalse(os.path.exists(os.path.join(self.work, "..", "x")))
        self.assertEqual(self.calls, [])
        self.assertEqual(ts.job_snapshot()["state"], "idle")

    def test_a_close_match_is_suggested(self):
        r = self.get("/api/state?car=ks_xx")
        self.assertIn("close matches: ks_x", r.json["error"])

    def test_the_car_must_be_text(self):
        for value in (5, ["ks_x"], {"id": "ks_x"}, True):
            with self.subTest(repr(value)):
                r = self.post("/api/reset_all", {"car": value})
                self.assertEqual((r.status, r.json), (400, {"error": "car must be text"}))

    def test_a_null_car_means_the_default_car(self):
        self.assertEqual(self.post("/api/reset_all", {"car": None}).status, 200)
        self.assertTrue(os.path.exists(self.state_file()))

    def test_a_game_car_that_is_not_in_cars_json_is_accepted(self):
        r = self.get("/api/state?car=ks_y")
        self.assertEqual((r.status, r.json["car"], r.json["base_present"], r.json["default_new_id"]), (200, "ks_y", False, "ax_y"))

    def test_without_a_car_the_default_car_is_used(self):
        self.assertEqual(self.get("/api/state").json["car"], "ks_x")

    def test_a_blank_car_query_means_the_default_car(self):
        self.assertEqual(self.get("/api/state?car=").json["car"], "ks_x")

    def test_the_body_car_wins_over_the_query_car(self):
        self.assertEqual(self.post("/api/reset_all?car=ks_y", {"car": "ks_x"}).status, 200)
        self.assertTrue(os.path.exists(self.state_file("ks_x")))
        self.assertFalse(os.path.exists(self.state_file("ks_y")))

    def test_the_query_car_is_used_when_the_body_has_none(self):
        r = self.post("/api/set?car=ks_y", {"id": "limiter", "value": "8000"})
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_without_the_game_car_list_only_the_tested_cars_are_known(self):
        os.remove(os.path.join(self.work, "cars_index.json"))
        self.patch(tune, "DEFAULT_GAME", os.path.join(self.work, "no_game.kspkg"))
        self.assertEqual([c["id"] for c in self.get("/api/state").json["cars"]], ["ks_x"])
        r = self.get("/api/state?car=ks_y")
        self.assertEqual(r.status, 400)
        self.assertIn("car list of the game is not available", r.json["error"])


# -------------------------------------------------------------------------------------------------- state and settings
class TestStateAndSettings(ServerCase):
    def test_state_without_a_base_car(self):
        r = self.get("/api/state").json
        self.assertEqual((r["work"], r["car"], r["default_car"], r["base_present"], r["game_running"]), (self.work, "ks_x", "ks_x", False, False))
        self.assertEqual((r["stock_id_length"], r["default_new_id"], r["settings_applicable"], r["settings_hidden"]), (4, "ax_x", None, None))
        self.assertEqual(r["installed"], {"path": os.path.join(os.path.abspath(self.mods), "ax_x.kspkg"), "exists": False, "bytes": None, "modified": None})

    def test_state_lists_every_game_car_with_its_flags(self):
        cars = self.get("/api/state").json["cars"]
        self.assertEqual([set(c) for c in cars], [CAR_KEYS, CAR_KEYS])
        self.assertEqual([(c["id"], c["display_name"], c["tested"], c["extracted"], c["new_id"], c["installed"]) for c in cars],
                         [("ks_x", "Car X", True, False, "ax_x", False), ("ks_y", "Car Y", False, False, "ax_y", False)])

    def test_state_with_a_base_car_counts_applicable_and_hidden_settings(self):
        self.make_car()
        r = self.get("/api/state").json
        self.assertEqual((r["base_present"], r["settings_applicable"], r["settings_hidden"]), (True, 3, 1))
        self.assertTrue(r["cars"][0]["extracted"])

    def test_an_empty_car_folder_is_no_base(self):
        os.makedirs(self.fc.car_root)
        self.assertFalse(self.get("/api/state").json["base_present"])

    def test_the_counts_are_null_while_the_car_is_being_extracted(self):
        self.make_car()
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        r = self.get("/api/state").json
        self.assertEqual((r["base_present"], r["settings_applicable"], r["settings_hidden"]), (True, None, None))
        self.finish_held_job()
        self.assertEqual(self.get("/api/state").json["settings_applicable"], 3)

    def test_state_reports_the_game_and_the_installed_package(self):
        self.make_car()
        self.game_up = True
        os.makedirs(self.mods)
        with open(os.path.join(self.mods, "ax_x.kspkg"), "wb") as f:
            f.write(b"12345")
        r = self.get("/api/state").json
        self.assertTrue(r["game_running"])
        self.assertEqual((r["installed"]["exists"], r["installed"]["bytes"]), (True, 5))
        self.assertTrue(r["cars"][0]["installed"])
        self.assertFalse(r["cars"][1]["installed"])

    def test_settings_rows_carry_the_documented_fields(self):
        self.make_car()
        rows = {r["id"]: r for r in self.get("/api/settings").json}
        self.assertEqual(set(rows["limiter"]), ROW_KEYS | {"min", "max"})
        self.assertEqual((rows["limiter"]["default"], rows["limiter"]["value"], rows["limiter"]["changed"], rows["limiter"]["copies_differ"]),
                         (7000, 7000, False, False))
        self.assertEqual(set(rows["name_suffix"]), ROW_KEYS | {"ui"})
        self.assertEqual((rows["name_suffix"]["ui"], rows["name_suffix"]["default"]), ("header", "MY"))
        self.assertEqual((rows["aids_off"]["type"], rows["aids_off"]["default"], rows["aids_off"]["value"]), ("bool", False, False))

    def write_ranges(self, ranges):
        return self.write(os.path.join(self.work, tune.RANGES_FILE), ranges)

    def test_settings_rows_carry_the_base_range_of_the_settings_that_have_an_entry(self):
        self.make_car()
        self.write_ranges({"limiter": {"low": 5000, "high": 9000.5}, "boost": {"low": 1, "high": 2}, "gone": {"low": 0, "high": 1}})
        r = self.get("/api/settings")
        rows = {x["id"]: x for x in r.json}
        self.assertEqual(r.status, 200)
        self.assertEqual(rows["limiter"]["base_range"], {"low": 5000, "high": 9000.5})
        self.assertEqual(set(rows["limiter"]), ROW_KEYS | {"min", "max", "base_range"})
        self.assertEqual((rows["limiter"]["min"], rows["limiter"]["max"]), (3000, 12000))
        self.assertNotIn("base_range", rows["aids_off"])
        self.assertNotIn("base_range", rows["name_suffix"])
        self.assertEqual(set(rows), {"limiter", "aids_off", "name_suffix"})

    def test_settings_rows_have_no_base_range_without_a_ranges_file(self):
        self.make_car()
        self.assertFalse(os.path.exists(os.path.join(self.work, tune.RANGES_FILE)))
        r = self.get("/api/settings")
        self.assertEqual((r.status, [x["id"] for x in r.json]), (200, ["limiter", "aids_off", "name_suffix"]))
        self.assertEqual([x["id"] for x in r.json if "base_range" in x], [])

    def test_settings_rows_have_no_base_range_from_a_damaged_ranges_file(self):
        self.make_car()
        self.write(os.path.join(self.work, tune.RANGES_FILE), "{not json")
        r = self.get("/api/settings")
        self.assertEqual(r.status, 200)
        self.assertEqual([x["id"] for x in r.json if "base_range" in x], [])

    def test_settings_not_applicable_to_the_car_are_left_out(self):
        self.make_car()
        self.assertNotIn("boost", [r["id"] for r in self.get("/api/settings").json])

    def test_copies_that_differ_are_listed_with_their_values(self):
        self.make_car()
        self.car["engine"]["limiter"] = 6500
        row = self.get("/api/settings").json[0]
        self.assertTrue(row["copies_differ"])
        self.assertEqual(row["copy_values"], [{"target": "@engine limiter", "value": 7000}, {"target": "@car engine.limiter", "value": 6500}])

    def test_settings_show_the_saved_state(self):
        self.make_car()
        self.write(self.state_file(), {"limiter": 8000})
        row = self.get("/api/settings").json[0]
        self.assertEqual((row["value"], row["default"], row["changed"]), (8000, 7000, True))


class TestCalculatedRows(ServerCase):
    """The displayed power and torque without a saved value are calculated from the engine settings (power curve 100/300/200 Nm at 1000/5000/7000 rpm, spec sheet 400 PS and 500 Nm)."""

    def setUp(self):
        super().setUp()
        self.make_car()
        self.addCleanup(tune._engine_inputs.clear)
        self.engine["powerCurve"] = self.fc.game_path("data/power.curve")
        self.fc.add("data/power.curve", {"points": [{"t": 1000.0, "value": 100.0}, {"t": 5000.0, "value": 300.0}, {"t": 7000.0, "value": 200.0}]})
        self.fc.add("presets/p.mechanicalcarpreset", {"car_specs": {"items": [{"key": "KEY_POWER", "value": 400.0}, {"key": "KEY_TORQUE", "value": 500.0}]}})
        self.cat = mini_catalogue(
            limiter(), suffix(),
            mini_setting("power_scale", kind="curve_scale", default=1.0, curve_from={"file": "@engine", "path": "powerCurve"}, targets=[]),
            mini_setting("display_power_ps", targets=[("@mech_preset", "car_specs.items[key=KEY_POWER].value")]),
            mini_setting("display_torque_nm", targets=[("@mech_preset", "car_specs.items[key=KEY_TORQUE].value")]))

    def rows(self):
        return {r["id"]: r for r in self.get("/api/settings").json}

    def test_the_rows_carry_calculated_only_when_it_applies(self):
        rows = self.rows()
        self.assertEqual([(rows[i]["value"], rows[i]["changed"], "calculated" in rows[i]) for i in ("display_power_ps", "display_torque_nm")],
                         [(400.0, False, False), (500.0, False, False)])
        self.write(self.state_file(), {"power_scale": 1.2})
        rows = self.rows()
        self.assertEqual(set(rows["display_power_ps"]), ROW_KEYS | {"calculated"})
        self.assertEqual([(rows[i]["value"], rows[i]["default"], rows[i]["changed"], rows[i]["calculated"]) for i in ("display_power_ps", "display_torque_nm")],
                         [(480.0, 400.0, True, True), (600.0, 500.0, True, True)])
        for sid in ("limiter", "power_scale", "name_suffix"):
            self.assertNotIn("calculated", rows[sid])

    def test_a_typed_value_is_an_override_without_the_flag_and_unset_returns_to_the_calculated_one(self):
        self.write(self.state_file(), {"power_scale": 1.2})
        r = self.post("/api/set", {"id": "display_power_ps", "value": "450"}).json
        self.assertEqual((r["row"]["value"], r["row"]["changed"], "calculated" in r["row"]), (450.0, True, False))
        self.assertEqual(self.saved_state(), {"power_scale": 1.2, "display_power_ps": 450.0})
        rows = self.rows()
        self.assertEqual(("calculated" in rows["display_power_ps"], rows["display_torque_nm"]["calculated"]), (False, True))
        r = self.post("/api/unset", {"id": "display_power_ps"}).json
        self.assertEqual((r["row"]["value"], r["row"]["changed"], r["row"]["calculated"]), (480.0, True, True))
        self.assertEqual(self.saved_state(), {"power_scale": 1.2})

    def test_a_lower_limiter_is_calculated_too(self):
        self.write(self.state_file(), {"limiter": 4000})
        self.assertEqual([self.rows()[i]["value"] for i in ("display_power_ps", "display_torque_nm")], [264.0, 417.0])
        self.assertEqual(self.get("/api/state").status, 200)


class TestMissingBase(ServerCase):
    def assertNoBase(self, r):
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_settings_set_unset_and_apply_are_409_without_a_base(self):
        self.assertNoBase(self.get("/api/settings"))
        self.assertNoBase(self.post("/api/set", {"id": "limiter", "value": "8000"}))
        self.assertNoBase(self.post("/api/unset", {"id": "limiter"}))
        self.assertNoBase(self.post("/api/apply", {"mode": "update"}))
        self.assertEqual(self.calls, [])
        self.assertEqual(ts.job_snapshot()["state"], "idle")

    def test_set_and_unset_create_no_state_file_without_a_base(self):
        self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.post("/api/unset", {"id": "limiter"})
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x")))

    def test_the_input_checks_come_before_the_base_check(self):
        self.assertEqual(self.post("/api/set", {"id": 5, "value": 1}).status, 400)
        self.assertEqual(self.post("/api/apply", {"tune": "draft", "new_id": 5}).status, 400)
        self.assertEqual(self.post("/api/apply", {"tune": "draft", "suffix": ["_X"]}).status, 400)
        self.assertEqual(self.post("/api/duplicate", {"new_id": 5}).status, 400)

    def test_init_needs_no_base(self):
        self.assertEqual(self.post("/api/init").status, 202)

    def test_reset_all_without_a_base_is_409(self):
        self.assertNoBase(self.post("/api/reset_all"))

    def test_reset_all_without_a_base_creates_no_state_file(self):
        self.post("/api/reset_all")
        self.assertFalse(os.path.exists(self.state_file()), "tune_state.json was created for a car that was never extracted")


# -------------------------------------------------------------------------------------------------- set / unset / reset_all and the state file
class TestStateRoutes(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_set_answers_with_the_new_row(self):
        r = self.post("/api/set", {"id": "limiter", "value": "8000"})
        row = r.json["row"]
        self.assertEqual((r.json["warnings"], row["id"], row["value"], row["default"], row["changed"]), ([], "limiter", 8000, 7000, True))
        self.assertEqual(set(row), ROW_KEYS | {"min", "max"})

    def test_set_and_unset_answer_a_row_with_the_base_range(self):
        self.write(os.path.join(self.work, tune.RANGES_FILE), {"limiter": {"low": 5000, "high": 9000}})
        for path, body in (("/api/set", {"id": "limiter", "value": "8000"}), ("/api/unset", {"id": "limiter"})):
            with self.subTest(path):
                row = self.post(path, body).json["row"]
                self.assertEqual(row["base_range"], {"low": 5000, "high": 9000})
                self.assertEqual(set(row), ROW_KEYS | {"min", "max", "base_range"})

    def test_set_answers_a_row_without_base_range_when_the_setting_has_no_entry_or_there_is_no_file(self):
        self.assertNotIn("base_range", self.post("/api/set", {"id": "limiter", "value": "8000"}).json["row"])
        self.write(os.path.join(self.work, tune.RANGES_FILE), {"boost": {"low": 1, "high": 2}})
        self.assertNotIn("base_range", self.post("/api/set", {"id": "limiter", "value": "8100"}).json["row"])
        self.assertNotIn("base_range", self.post("/api/set", {"id": "aids_off", "value": True}).json["row"])

    def test_set_persists_the_coerced_value_in_the_state_file(self):
        self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.post("/api/set", {"id": "aids_off", "value": True})
        self.assertEqual(self.saved_state(), {"limiter": 8000, "aids_off": True})
        self.assertEqual(os.path.dirname(self.state_file()), os.path.join(self.work, "ks_x"))

    def test_set_outside_the_suggested_range_warns_but_stores(self):
        r = self.post("/api/set", {"id": "limiter", "value": "20000"})
        self.assertEqual((r.status, r.json["warnings"]), (200, ["limiter=20000 is outside the suggested range 3000..12000"]))
        self.assertEqual(self.saved_state(), {"limiter": 20000})

    def test_set_with_a_bad_value_is_400_and_changes_nothing(self):
        self.write(self.state_file(), {"limiter": 7500})
        r = self.post("/api/set", {"id": "limiter", "value": "fast"})
        self.assertEqual(r.status, 400)
        self.assertIn("limiter expects an integer", r.json["error"])
        self.assertEqual(self.saved_state(), {"limiter": 7500})

    def test_set_of_an_unknown_setting_is_400(self):
        r = self.post("/api/set", {"id": "nope", "value": "1"})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown setting 'nope'"}))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_set_of_a_setting_the_car_does_not_have_is_400(self):
        r = self.post("/api/set", {"id": "boost", "value": "1.5"})
        self.assertEqual(r.status, 400)
        self.assertIn("boost is not applicable to ks_x", r.json["error"])
        self.assertFalse(os.path.exists(self.state_file()))

    def test_unset_removes_the_entry_and_answers_with_the_default_row(self):
        self.write(self.state_file(), {"limiter": 8000, "aids_off": True})
        r = self.post("/api/unset", {"id": "limiter"})
        self.assertEqual((r.status, r.json["row"]["value"], r.json["row"]["changed"]), (200, 7000, False))
        self.assertEqual(self.saved_state(), {"aids_off": True})

    def test_unset_of_a_value_that_was_never_set_is_a_noop(self):
        r = self.post("/api/unset", {"id": "limiter"})
        self.assertEqual((r.status, r.json["row"]["changed"]), (200, False))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_unset_of_an_unknown_setting_is_400(self):
        self.assertEqual(self.post("/api/unset", {"id": "nope"}).json, {"error": "unknown setting 'nope'"})

    def test_reset_all_writes_an_empty_state(self):
        self.write(self.state_file(), {"limiter": 8000, "aids_off": True})
        r = self.post("/api/reset_all")
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual(self.saved_state(), {})
        self.assertFalse(any(row["changed"] for row in self.get("/api/settings").json))

    def test_reset_all_drops_the_garage_turbo_and_sound_choices_with_the_values(self):
        self.write(self.state_file(), {"limiter": 8000, tune.TYRE_KEY: ["own:soft"], tune.TURBO_KEY: {"donor": "ks_b"},
                                       tune.SOUND_KEY: {"turbo": "event:/parts/turbos/turbo_rx7"}})
        self.assertEqual(self.post("/api/reset_all").status, 200)
        self.assertEqual(self.saved_state(), {})

    def test_the_state_is_kept_per_car(self):
        self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.assertFalse(os.path.exists(self.state_file("ks_y")))

    def test_a_saved_value_shows_up_in_the_settings_list(self):
        self.post("/api/set", {"id": "limiter", "value": "8000"})
        row = self.get("/api/settings").json[0]
        self.assertEqual((row["value"], row["changed"]), (8000, True))

    def test_every_state_write_happens_under_state_lock(self):
        held = []
        real = tune.save_state

        def spy(*args, **kw):
            held.append(ts.STATE_LOCK.locked())
            return real(*args, **kw)
        self.patch(tune, "save_state", spy)
        self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.post("/api/unset", {"id": "limiter"})
        self.post("/api/reset_all")
        self.assertEqual(held, [True, True, True])

    def test_the_settings_list_is_built_under_state_lock(self):
        held = []
        real = tune.effective_rows

        def spy(*args, **kw):
            held.append(ts.STATE_LOCK.locked())
            return real(*args, **kw)
        self.patch(tune, "effective_rows", spy)
        self.get("/api/settings")
        self.assertEqual(held, [True])

    def test_two_edits_at_the_same_time_are_both_kept(self):
        real = tune.load_state

        def slow(*args, **kw):
            state = real(*args, **kw)
            time.sleep(0.05)
            return state
        self.patch(tune, "load_state", slow)
        start, results = threading.Barrier(2), []

        def send(body):
            start.wait(5)
            results.append(self.post("/api/set", body).status)
        threads = [threading.Thread(target=send, args=(b,)) for b in ({"id": "limiter", "value": "8000"}, {"id": "aids_off", "value": True})]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(results, [200, 200])
        self.assertEqual(self.saved_state(), {"limiter": 8000, "aids_off": True})


# -------------------------------------------------------------------------------------------------- apply and init
class TuneCase(ServerCase):
    """ServerCase with the stub car ks_x extracted and helpers for modded cars (tunes) of it."""

    def setUp(self):
        super().setUp()
        self.make_car()

    def make_tune(self, tune_id=None, state=None):
        """A modded car of ks_x with the given saved values (tune_id None = the default tune ax_x)."""
        tune.save_state(self.work, "ks_x", dict(state or {}), tune_id)

    def tune_state(self, tune_id=None):
        return tune.load_state(self.work, "ks_x", tune_id)

    def tune_ids(self):
        return [t["id"] for t in tune.list_tunes(self.work, "ks_x")]

    def put_package(self, name, data=b"12345"):
        os.makedirs(self.mods, exist_ok=True)
        with open(os.path.join(self.mods, name + ".kspkg"), "wb") as f:
            f.write(data)

    def game_arg(self):
        return os.path.expandvars(tune.DEFAULT_GAME)


class TestApplyRoute(TuneCase):
    def test_a_new_id_or_suffix_that_is_not_text_is_400_for_the_draft(self):
        for body, text in (({"new_id": 5}, "new_id must be text"), ({"new_id": ["ax_y"]}, "new_id must be text"),
                           ({"suffix": 5}, "suffix must be text"), ({"suffix": {"a": 1}}, "suffix must be text")):
            with self.subTest(body):
                r = self.post("/api/apply", dict(body, tune="draft"))
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual((self.calls, self.tune_ids(), ts.job_snapshot()["state"]), ([], [], "idle"))

    def test_an_explicit_new_id_that_is_not_a_plain_same_length_id_is_400_and_creates_nothing(self):
        for new_id in ("../../x", "../x", "AX_Y", "ax y", "ax_yy", "ax", "ax-y", "ax_\u00e9", "ax/y", "a\x00b_", ""):
            with self.subTest(new_id):
                r = self.post("/api/apply", {"tune": "draft", "new_id": new_id})
                self.assertEqual(r.status, 400, r.json)
        self.assertEqual((self.calls, self.tune_ids(), ts.job_snapshot()["state"]), ([], [], "idle"))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tunes")))

    def slow_new_tune(self, delay=0.3):
        real, created = tune.new_tune_from_draft, []

        def slow(*args, **kw):
            time.sleep(delay)
            created.append(real(*args, **kw))
            return created[-1]
        self.patch(tune, "new_tune_from_draft", slow)
        return created

    def test_two_draft_applies_at_the_same_time_create_one_modded_car(self):
        self.hold_jobs()
        created = self.slow_new_tune()
        start, results = threading.Barrier(2), []

        def send():
            start.wait(5)
            results.append(self.post("/api/apply", {"tune": "draft"}).status)
        threads = [threading.Thread(target=send) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(results), [202, 409])
        self.assertEqual((len(created), self.tune_ids()), (1, ["ax_x"]))
        self.finish_held_job()

    def test_a_refused_draft_apply_restores_the_job_state_and_the_next_apply_runs(self):
        r = self.post("/api/apply", {"tune": "draft", "new_id": "ks_x"})
        self.assertEqual((r.status, r.json), (400, {"error": "new id equals the old id 'ks_x'"}))
        self.assertEqual(ts.job_snapshot(), {"kind": None, "state": "idle", "log": [], "result": None, "error": None})
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        self.assertEqual(self.wait_job()["state"], "done")

    def test_a_refused_apply_keeps_the_previous_finished_job_displayed(self):
        for state, result, error in (("done", {"new_id": "ax01"}, None), ("error", None, "boom")):
            with self.subTest(state):
                ts.JOB.update(kind="init", state=state, log=["a", "b"], result=result, error=error)
                before = ts.job_snapshot()
                self.assertEqual(self.post("/api/apply", {"tune": "draft", "new_id": "ks_x"}).status, 400)
                self.assertEqual(self.post("/api/apply", {"tune": "nope"}).status, 400)
                self.assertEqual(self.post("/api/apply", {}).status, 400)
                self.assertEqual(ts.job_snapshot(), before)

    def test_a_running_job_is_never_overwritten_by_a_refused_apply(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.make_tune(None, {"name_suffix": "_A"})
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        before = ts.job_snapshot()
        for body in ({"tune": "draft"}, {"tune": "ax01"}, {}):
            with self.subTest(body):
                self.assertEqual(self.post("/api/apply", body).status, 409)
        self.assertEqual((ts.job_snapshot()["kind"], ts.job_snapshot()["state"]), (before["kind"], "running"))
        self.finish_held_job()

    def test_an_unexpected_error_while_the_target_is_made_restores_the_job_and_does_not_leave_it_running(self):
        self.patch(tune, "new_tune_from_draft", mock.Mock(side_effect=RuntimeError("disk exploded")))
        r = self.post("/api/apply", {"tune": "draft"})
        self.assertEqual((r.status, r.json), (500, {"error": "internal error: RuntimeError"}))
        self.assertEqual(ts.job_snapshot(), {"kind": None, "state": "idle", "log": [], "result": None, "error": None})
        self.assertEqual(self.calls, [])

    def test_the_stock_id_and_the_id_of_an_existing_default_car_are_refused_as_new_ids(self):
        stock = self.post("/api/apply", {"tune": "draft", "new_id": "ks_x"})
        self.assertEqual((stock.status, stock.json["error"]), (400, "new id equals the old id 'ks_x'"))
        self.make_tune()
        default = self.post("/api/apply", {"tune": "draft", "new_id": "ax_x"})
        self.assertEqual((default.status, default.json["error"]), (400, "ax_x is already a tune of ks_x"))
        self.assertEqual((self.calls, self.tune_ids()), ([], ["ax_x"]))

    def test_a_new_id_that_another_modded_car_or_a_package_uses_is_400(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.put_package("ax02")
        for new_id in ("ax01", "ax02"):
            with self.subTest(new_id):
                r = self.post("/api/apply", {"tune": "draft", "new_id": new_id})
                self.assertEqual((r.status, r.json["error"]), (400, "tuned car id %s is already used or reserved" % new_id))
        self.assertEqual((self.calls, self.tune_ids()), ([], ["ax01"]))

    def test_an_explicit_suffix_that_another_modded_car_uses_is_400_and_creates_nothing(self):
        self.make_tune(None, {"name_suffix": "_A"})
        r = self.post("/api/apply", {"tune": "draft", "suffix": "_A"})
        self.assertEqual((r.status, r.json), (400, {"error": "car name already used by ax_x"}))
        self.assertEqual((self.calls, self.tune_ids()), ([], ["ax_x"]))
        bad = self.post("/api/apply", {"tune": "draft", "suffix": ""})
        self.assertEqual(bad.status, 400)
        self.assertEqual(self.tune_ids(), ["ax_x"])

    def test_the_draft_creates_the_first_modded_car_under_the_default_id_and_builds_it(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        r = self.post("/api/apply", {"tune": "draft"})
        self.assertEqual((r.status, r.json), (202, {"job": "started"}))
        snap = self.wait_job()
        self.assertEqual(self.calls, [("apply", (self.work, "ks_x", "ax_x", True, self.mods), {"game": self.game_arg()})])
        self.assertEqual((snap["kind"], snap["state"], snap["error"]), ("apply", "done", None))
        self.assertEqual(snap["result"], dict(APPLY_RESULT, created=True))
        self.assertEqual(self.tune_ids(), ["ax_x"])
        self.assertEqual(self.tune_state(), {"limiter": 8000, "name_suffix": "MY"})

    def test_the_second_modded_car_of_the_draft_gets_a_counter_id_and_the_next_suffix(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        self.post("/api/apply", {"tune": "draft"})
        self.wait_job()
        self.make_tune(tune.DRAFT, {"limiter": 9000})
        self.post("/api/apply", {"tune": "draft"})
        snap = self.wait_job()
        self.assertEqual([c[1][2] for c in self.calls], ["ax_x", "ax01"])
        self.assertEqual((snap["result"]["new_id"], snap["result"]["tune"], snap["result"]["created"]), ("ax01", "ax01", True))
        self.assertEqual(self.tune_ids(), ["ax_x", "ax01"])
        self.assertEqual(self.tune_state("ax01"), {"limiter": 9000, "name_suffix": "MY 2"})
        self.assertEqual(self.tune_state(), {"limiter": 8000, "name_suffix": "MY"})

    def test_an_explicit_new_id_and_suffix_are_used_for_the_draft(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        self.post("/api/apply", {"tune": "draft", "new_id": "ax_z", "suffix": "_Z"})
        snap = self.wait_job()
        self.assertEqual(self.calls[0][1][2], "ax_z")
        self.assertEqual((snap["result"]["new_id"], snap["result"]["created"]), ("ax_z", True))
        self.assertEqual(self.tune_state("ax_z"), {"limiter": 8000, "name_suffix": "_Z"})
        self.assertEqual(self.tune_ids(), ["ax_z"])

    def test_the_draft_is_cleared_after_a_successful_build(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000, "aids_off": True})
        self.post("/api/apply", {"tune": "draft"})
        self.wait_job()
        self.assertEqual(self.tune_state(tune.DRAFT), {})
        self.assertFalse(any(r["changed"] for r in self.get("/api/settings?tune=draft").json))

    def test_the_draft_is_cleared_under_state_lock(self):
        held = []
        real = tune.save_state

        def spy(work, car, state, tune_id=None):
            held.append((tune_id, ts.STATE_LOCK.locked()))
            return real(work, car, state, tune_id)
        self.patch(tune, "save_state", spy)
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        self.post("/api/apply", {"tune": "draft"})
        self.wait_job()
        self.assertEqual(held[-1], (tune.DRAFT, True))

    def test_a_failed_build_keeps_the_draft_and_leaves_the_created_modded_car_listed(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        self.errors["apply"] = ValueError("clone self-check failed")
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        snap = self.wait_job()
        self.assertEqual((snap["state"], snap["error"], snap["result"]), ("error", "clone self-check failed", None))
        self.assertEqual(self.tune_state(tune.DRAFT), {"limiter": 8000})
        self.assertEqual(self.tune_ids(), ["ax_x"])
        self.assertEqual([m["id"] for m in self.get("/api/state").json["modded"]], ["ax_x"])

    def test_a_retry_after_a_failed_build_creates_one_more_modded_car(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        self.errors["apply"] = ValueError("boom")
        self.post("/api/apply", {"tune": "draft"})
        self.wait_job()
        self.errors.clear()
        self.post("/api/apply", {"tune": "draft"})
        self.wait_job()
        self.assertEqual(self.tune_ids(), ["ax_x", "ax01"])
        self.assertEqual(self.tune_state(tune.DRAFT), {})

    def test_an_empty_draft_creates_a_modded_car_with_the_stock_values(self):
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        self.wait_job()
        self.assertEqual(self.tune_state(), {"name_suffix": "MY"})

    def test_a_modded_car_is_updated_under_its_own_id(self):
        self.make_tune("ax01", {"limiter": 8000, "name_suffix": "_A"})
        self.make_tune(tune.DRAFT, {"limiter": 9000})
        r = self.post("/api/apply", {"tune": "ax01"})
        self.assertEqual((r.status, r.json), (202, {"job": "started"}))
        snap = self.wait_job()
        self.assertEqual(self.calls, [("apply", (self.work, "ks_x", "ax01", True, self.mods), {"game": self.game_arg()})])
        self.assertEqual((snap["state"], snap["error"]), ("done", None))
        self.assertEqual(snap["result"], dict(APPLY_RESULT, new_id="ax01", tune="ax01", created=False))
        self.assertEqual(self.tune_ids(), ["ax01"])
        self.assertEqual(self.tune_state(tune.DRAFT), {"limiter": 9000})

    def test_the_job_result_in_the_state_answer_carries_the_changes(self):
        self.make_tune()
        self.post("/api/apply", {})
        self.wait_job()
        result = self.get("/api/state").json["job"]["result"]
        self.assertEqual(result["changes"], APPLY_RESULT["changes"])
        self.assertEqual(result["applied"], APPLY_RESULT["applied"])

    def test_the_job_result_carries_every_kind_of_change_unchanged(self):
        changes = {"since": "last build", "total": 4, "settings": [{"id": "a", "from": 1.5, "to": 2.5}, {"id": "b", "from": False, "to": True}],
                   "extras": [{"kind": "turbo_kit", "from": None, "to": "A", "text": "Turbo kit: none -> A"},
                              {"kind": "sound", "slot": "turbo", "from": "e1", "to": None, "text": "Sound turbo: e1 -> own sound"}]}
        self.patch(tune, "apply", lambda *a, **k: dict(APPLY_RESULT, changes=changes))
        self.make_tune()
        self.post("/api/apply", {})
        snap = self.wait_job()
        self.assertEqual(self.get("/api/state").json["job"]["result"]["changes"], changes)
        self.assertEqual(snap["log"][1:5], ["4 change(s) since the last build (4 changed settings compared to the stock car in total)",
                                            "  a: 1.5 -> 2.5", "  b: false -> true", "  Turbo kit: none -> A"])

    def test_without_a_tune_the_default_modded_car_is_updated(self):
        self.make_tune()
        self.assertEqual(self.post("/api/apply", {}).status, 202)
        snap = self.wait_job()
        self.assertEqual(self.calls, [("apply", (self.work, "ks_x", "ax_x", True, self.mods), {"game": self.game_arg()})])
        self.assertEqual((snap["state"], snap["result"]["created"]), ("done", False))
        self.assertEqual(self.post("/api/apply", {"tune": None}).status, 202)

    def test_without_a_tune_and_without_a_default_modded_car_apply_is_400(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        r = self.post("/api/apply", {})
        self.assertEqual((r.status, r.json), (400, {"error": "no modded car selected, pick one or use the draft of the car to create it"}))
        self.assertEqual((self.calls, self.tune_ids(), ts.job_snapshot()["state"]), ([], ["ax01"], "idle"))

    def test_an_update_ignores_new_id_and_suffix_in_the_body(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.post("/api/apply", {"tune": "ax01", "new_id": "../../x", "suffix": 5})
        self.wait_job()
        self.assertEqual(self.calls[0][1][2], "ax01")
        self.assertEqual((self.tune_ids(), self.tune_state("ax01")), (["ax01"], {"name_suffix": "_A"}))

    def test_an_update_whose_suffix_another_modded_car_uses_is_400_with_the_message(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.make_tune("ax01", {"name_suffix": "_A"})
        r = self.post("/api/apply", {"tune": "ax01"})
        self.assertEqual((r.status, r.json), (400, {"error": "car name _A is already used by ax_x"}))
        self.assertEqual(self.post("/api/apply", {}).json, {"error": "car name _A is already used by ax01"})
        self.assertEqual((self.calls, ts.job_snapshot()["state"]), ([], "idle"))

    def test_a_suffix_conflict_found_by_tune_apply_ends_the_job_in_the_error_state(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.errors["apply"] = ValueError("car name _A is already used by ax_x")
        self.assertEqual(self.post("/api/apply", {"tune": "ax01"}).status, 202)
        snap = self.wait_job()
        self.assertEqual((snap["state"], snap["error"]), ("error", "car name _A is already used by ax_x"))

    def test_an_unknown_modded_car_is_400_and_starts_no_job(self):
        r = self.post("/api/apply", {"tune": "ax01"})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car ax01 of ks_x"}))
        self.assertEqual((self.calls, ts.job_snapshot()["state"]), ([], "idle"))

    def test_the_apply_log_has_the_build_line_and_the_result_lines(self):
        self.make_tune()
        self.post("/api/apply", {})
        self.assertEqual(self.wait_job()["log"], [
            "building ax_x, this takes a while ...", "first build of this car: 1 changed settings compared to the stock car",
            "  limiter: 7000 -> 8000", "note: from build",
            "package: /w/ks_x/build/ax_x/ax_x.kspkg (7 bytes)", "installed: /m/ax_x.kspkg", "backup: no previous install"])

    def test_apply_is_refused_while_the_game_runs_and_creates_no_modded_car(self):
        self.game_up = True
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        r = self.post("/api/apply", {"tune": "draft"})
        self.assertEqual((r.status, r.json), (409, {"error": "close the game first, AssettoCorsaEVO.exe is running"}))
        self.assertEqual((self.calls, self.tune_ids(), ts.job_snapshot()["state"]), ([], [], "idle"))
        self.make_tune()
        self.assertEqual(self.post("/api/apply", {}).status, 409)
        self.assertEqual(self.tune_state(tune.DRAFT), {"limiter": 8000})

    def test_apply_is_allowed_again_once_the_game_is_closed(self):
        self.game_up = True
        self.post("/api/apply", {"tune": "draft"})
        self.game_up = False
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)

    def test_the_configured_game_package_reaches_tune_apply(self):
        ts.CONFIG["game"] = "other.kspkg"
        self.post("/api/apply", {"tune": "draft"})
        self.wait_job()
        args, kw = self.calls[0][1:]
        self.assertIn("other.kspkg", list(args) + list(kw.values()))

    def test_an_unexpandable_mods_folder_is_a_409_and_starts_no_job_and_creates_no_modded_car(self):
        ts.CONFIG["mods"] = "%ACE_TEST_NO_SUCH_VAR%/m"
        r = self.post("/api/apply", {"tune": "draft"})
        self.assertEqual((r.status, r.json), (409, {"error": "cannot expand the mods folder '%ACE_TEST_NO_SUCH_VAR%/m' (pass --mods <folder>)"}))
        self.assertEqual((self.calls, ts.job_snapshot()["state"], self.tune_ids()), ([], "idle", []))

    def test_a_running_job_refuses_the_draft_before_a_modded_car_is_created(self):
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        self.entered.wait(5)
        r = self.post("/api/apply", {"tune": "draft"})
        self.assertEqual(r.status, 409, r.json)
        self.assertEqual(self.tune_ids(), [])
        self.finish_held_job()

    def test_a_failing_apply_ends_in_the_error_state(self):
        self.errors["apply"] = ValueError("no base car in x, run init first")
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        snap = self.wait_job()
        self.assertEqual((snap["state"], snap["error"], snap["result"]), ("error", "no base car in x, run init first", None))
        self.assertEqual(snap["log"][-1], "error: no base car in x, run init first")

    def test_the_proposed_ids_of_the_state_are_what_apply_from_the_draft_creates(self):
        for _ in range(3):
            state = self.get("/api/state").json
            self.post("/api/apply", {"tune": "draft"})
            new_id = self.wait_job()["result"]["new_id"]
            self.assertEqual(new_id, state["proposed_new_id"])
            self.assertEqual(self.tune_state(new_id)["name_suffix"], state["proposed_suffix"])


class TestInitRoute(ServerCase):
    def test_init_runs_tune_init_as_a_job_with_the_default_game_path(self):
        r = self.post("/api/init")
        self.assertEqual((r.status, r.json), (202, {"job": "started"}))
        snap = self.wait_job()
        self.assertEqual(self.calls, [("init", (self.work, "ks_x", os.path.expandvars(tune.DEFAULT_GAME)), {})])
        self.assertEqual((snap["kind"], snap["state"], snap["result"], snap["error"]), ("init", "done", INIT_RESULT, None))
        self.assertEqual(snap["log"], ["extracting the stock car from the game package (about 20 s) ...", "extracted the stock car",
                                       "/w/ks_x/base/content/cars/ks_x: 3 files, 1 folders, 10 bytes"])

    def test_the_configured_game_package_reaches_tune_init(self):
        ts.CONFIG["game"] = "other.kspkg"
        self.post("/api/init")
        self.wait_job()
        args, kw = self.calls[0][1:]
        self.assertIn("other.kspkg", list(args) + list(kw.values()))

    def test_init_of_a_present_base_says_so(self):
        self.patch(tune, "init", lambda *a, **k: dict(INIT_RESULT, present=True))
        self.post("/api/init")
        self.assertEqual(self.wait_job()["log"][1], "base already present")

    def test_init_for_another_game_car(self):
        self.post("/api/init", {"car": "ks_y"})
        self.wait_job()
        self.assertEqual(self.calls[0][1][1], "ks_y")

    def test_a_failing_init_ends_in_the_error_state(self):
        self.errors["init"] = ValueError("game package not found: x")
        self.post("/api/init")
        snap = self.wait_job()
        self.assertEqual((snap["state"], snap["error"], snap["log"][-1]), ("error", "game package not found: x", "error: game package not found: x"))


# -------------------------------------------------------------------------------------------------- tunes: resolution, state, edits, duplicate
class TestTuneResolution(TuneCase):
    def setUp(self):
        super().setUp()
        self.make_tune("ax01", {"name_suffix": "_A"})

    def test_without_a_tune_the_state_echoes_null(self):
        for path in ("/api/state", "/api/state?car=ks_x", "/api/state?tune=", "/api/state?tune"):
            with self.subTest(path):
                self.assertEqual(self.get(path).json["tune"], None)

    def test_the_draft_and_a_modded_car_are_echoed(self):
        self.assertEqual(self.get("/api/state?tune=draft").json["tune"], "draft")
        self.assertEqual(self.get("/api/state?car=ks_x&tune=ax01").json["tune"], "ax01")

    def test_the_draft_needs_no_modded_car(self):
        os.remove(tune.state_path(self.work, "ks_x", "ax01"))
        self.assertEqual(self.tune_ids(), [])
        self.assertEqual(self.get("/api/state?tune=draft").status, 200)
        self.assertEqual(self.get("/api/settings?tune=draft").status, 200)

    def test_the_default_modded_car_can_be_selected_only_when_it_exists(self):
        r = self.get("/api/state?tune=ax_x")
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car ax_x of ks_x"}))
        self.make_tune()
        self.assertEqual(self.get("/api/state?tune=ax_x").json["tune"], "ax_x")

    def test_an_unknown_modded_car_is_400_on_both_get_routes(self):
        for path in ("/api/state?tune=nope", "/api/settings?tune=nope", "/api/state?tune=../x", "/api/state?tune=%2e%2e%2fx",
                     "/api/state?tune=DRAFT", "/api/state?tune=ax02", "/api/state?tune=ks_x"):
            with self.subTest(path):
                r = self.get(path)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith("unknown modded car "), r.json)
                self.assertTrue(r.json["error"].endswith(" of ks_x"), r.json)

    def test_a_modded_car_of_another_stock_car_is_unknown(self):
        tune.save_state(self.work, "ks_y", {}, "ax02")
        r = self.get("/api/state?tune=ax02")
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car ax02 of ks_x"}))
        self.assertEqual(self.get("/api/state?car=ks_y&tune=ax02").json["tune"], "ax02")
        self.assertEqual(self.get("/api/state?car=ks_y&tune=ax01").status, 400)

    def test_an_unknown_modded_car_is_400_on_every_post_route(self):
        for path in ("/api/set", "/api/unset", "/api/reset_all", "/api/init", "/api/duplicate", "/api/apply"):
            with self.subTest(path):
                r = self.post(path, {"tune": "nope", "id": "limiter", "value": "1"})
                self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))
        self.assertEqual((self.calls, ts.job_snapshot()["state"], self.tune_ids()), ([], "idle", ["ax01"]))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))

    def test_the_tune_must_be_text(self):
        for value in (5, ["draft"], {"id": "ax01"}, True, 0, 1.5):
            for path in ("/api/set", "/api/reset_all", "/api/duplicate", "/api/apply"):
                with self.subTest(repr(value), path=path):
                    r = self.post(path, {"tune": value, "id": "limiter", "value": "1"})
                    self.assertEqual((r.status, r.json), (400, {"error": "tune must be text"}))

    def test_a_null_tune_is_the_default_tune(self):
        self.assertEqual(self.post("/api/set", {"id": "limiter", "value": "8000", "tune": None}).status, 200)
        self.assertEqual(self.saved_state(), {"limiter": 8000})

    def test_an_empty_text_tune_in_the_body_is_unknown(self):
        r = self.post("/api/reset_all", {"tune": ""})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car  of ks_x"}))

    def test_a_post_takes_the_tune_from_the_query_when_the_body_has_none_and_the_body_wins(self):
        self.post("/api/set?tune=ax01", {"id": "limiter", "value": "8000"})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})
        self.post("/api/set?tune=ax01", {"id": "limiter", "value": "9000", "tune": "draft"})
        self.assertEqual((self.tune_state("ax01")["limiter"], self.tune_state("draft")), (8000, {"limiter": 9000}))

    def test_an_unknown_car_is_reported_before_an_unknown_tune(self):
        r = self.get("/api/state?car=nope&tune=nope")
        self.assertTrue(r.json["error"].startswith("unknown car"), r.json)

    def test_request_tune(self):
        self.assertIsNone(ts.request_tune(None, "", "ks_x"))
        self.assertIsNone(ts.request_tune(None, "car=ks_x", "ks_x"))
        self.assertEqual(ts.request_tune(None, "tune=ax01", "ks_x"), "ax01")
        self.assertEqual(ts.request_tune("draft", "tune=ax01", "ks_x"), "draft")
        self.assertEqual(ts.request_tune("ax01", "tune=nope", "ks_x"), "ax01")
        self.assertEqual(ts.request_tune(None, "a=1&tune=draft&b=2", "ks_x"), "draft")
        for value, query, text in (("nope", "", "unknown modded car nope of ks_x"), (None, "tune=nope", "unknown modded car nope of ks_x"),
                                   (5, "", "tune must be text"), (["ax01"], "", "tune must be text")):
            with self.subTest(value, query=query), self.assertRaises(ts.ApiError) as cm:
                ts.request_tune(value, query, "ks_x")
            self.assertEqual((cm.exception.status, cm.exception.message), (400, text))


class TestStateOfTunes(TuneCase):
    def test_a_car_without_modded_cars_proposes_the_default_id_and_suffix(self):
        r = self.get("/api/state").json
        self.assertEqual((r["modded"], r["default_tune_taken"], r["proposed_new_id"], r["proposed_suffix"]), ([], False, "ax_x", "MY"))
        self.assertNotIn("modded_error", r)
        self.assertEqual(r["default_new_id"], "ax_x")

    def test_the_modded_cars_are_listed_with_their_flags(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.make_tune("ax01", {"name_suffix": "_B"})
        self.put_package("ax01")
        build = os.path.join(tune.build_dir(self.work, "ks_x"), "ax_x")
        os.makedirs(build)
        with open(os.path.join(build, "ax_x.kspkg"), "wb"):
            pass
        r = self.get("/api/state").json
        self.assertEqual([set(m) for m in r["modded"]], [MODDED_KEYS, MODDED_KEYS])
        self.assertEqual(r["modded"], [
            {"id": "ax_x", "stock": "ks_x", "label": "Car X _A", "name_suffix": "_A", "default": True, "installed": False, "built": True},
            {"id": "ax01", "stock": "ks_x", "label": "Car X _B", "name_suffix": "_B", "default": False, "installed": True, "built": False}])

    def test_legacy_suffixes_on_disk_are_listed_converted_with_a_space_in_the_label(self):
        self.make_tune(None, {"name_suffix": "_MY"})
        self.make_tune("ax01", {"name_suffix": "_MY2"})
        self.make_tune("ax02", {"name_suffix": "_Drift"})
        r = self.get("/api/state").json
        self.assertEqual([(m["id"], m["label"], m["name_suffix"]) for m in r["modded"]],
                         [("ax02", "Car X _Drift", "_Drift"), ("ax_x", "Car X MY", "MY"), ("ax01", "Car X MY 2", "MY 2")])
        self.assertEqual(r["proposed_suffix"], "MY 3")
        self.assertEqual(self.saved_state(), {"name_suffix": "_MY"})

    def test_the_list_is_the_one_of_tune_list_modded_for_the_configured_mods_folder(self):
        self.make_tune("ax01", {"name_suffix": "_B"})
        seen = []

        def spy(work, mods_dir=None):
            seen.append((work, mods_dir))
            return [{"id": "ax01"}]
        self.patch(tune, "list_modded", spy)
        self.assertEqual(self.get("/api/state").json["modded"], [{"id": "ax01"}])
        self.assertEqual(seen, [(self.work, os.path.abspath(self.mods))])

    def test_the_modded_cars_of_every_stock_car_are_listed(self):
        self.make_tune("ax01", {"name_suffix": "_B"})
        tune.save_state(self.work, "ks_y", {"name_suffix": "_C"}, "ax02")
        self.assertEqual(sorted(m["id"] for m in self.get("/api/state").json["modded"]), ["ax01", "ax02"])
        self.assertEqual(sorted(m["id"] for m in self.get("/api/state?car=ks_y").json["modded"]), ["ax01", "ax02"])

    def test_a_list_that_cannot_be_read_gives_an_empty_list_and_the_error_text(self):
        def broken(work, mods_dir=None):
            raise ValueError("tune_state.json: expected an object")
        self.patch(tune, "list_modded", broken)
        r = self.get("/api/state")
        self.assertEqual(r.status, 200)
        self.assertEqual((r.json["modded"], r.json["modded_error"]), ([], "tune_state.json: expected an object"))
        self.assertEqual((r.json["proposed_new_id"], r.json["default_tune_taken"]), ("ax_x", False))

    def test_a_damaged_state_file_does_not_make_the_state_a_500(self):
        self.write(self.state_file(), "[1, 2]")
        r = self.get("/api/state")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json["modded"], [])
        self.assertIn("expected an object", r.json["modded_error"])
        self.assertEqual((r.json["default_tune_taken"], r.json["proposed_new_id"], r.json["proposed_suffix"]), (False, None, None))

    def test_an_existing_default_modded_car_is_taken_and_the_next_id_and_suffix_are_proposed(self):
        self.make_tune()
        r = self.get("/api/state").json
        self.assertEqual((r["default_tune_taken"], r["proposed_new_id"], r["proposed_suffix"]), (True, "ax01", "MY 2"))
        self.make_tune("ax01", {"name_suffix": "MY 2"})
        r = self.get("/api/state").json
        self.assertEqual((r["proposed_new_id"], r["proposed_suffix"]), ("ax02", "MY 3"))

    def test_a_build_folder_alone_takes_the_default_modded_car(self):
        os.makedirs(os.path.join(tune.build_dir(self.work, "ks_x"), "ax_x"))
        r = self.get("/api/state").json
        self.assertEqual((r["default_tune_taken"], r["proposed_new_id"], [m["id"] for m in r["modded"]]), (True, "ax01", ["ax_x"]))

    def test_installed_packages_take_their_ids_out_of_the_proposals(self):
        self.make_tune()
        self.put_package("ax01")
        self.assertEqual(self.get("/api/state").json["proposed_new_id"], "ax02")

    def test_the_proposals_are_per_stock_car(self):
        self.make_tune()
        r = self.get("/api/state?car=ks_y").json
        self.assertEqual((r["default_tune_taken"], r["proposed_new_id"], r["proposed_suffix"]), (False, "ax_y", "MY"))

    def test_no_free_id_proposes_null(self):
        self.make_tune()

        def full(*args, **kw):
            raise ValueError("no free tuned car id left for ks_x")
        self.patch(tune, "free_tune_id", full)
        r = self.get("/api/state")
        self.assertEqual((r.status, r.json["proposed_new_id"], r.json["default_tune_taken"]), (200, None, True))

    def test_installed_is_the_package_of_the_selected_modded_car(self):
        self.make_tune("ax01", {"name_suffix": "_B"})
        self.put_package("ax01", b"123456")
        sel = self.get("/api/state?tune=ax01").json["installed"]
        self.assertEqual((sel["path"], sel["exists"], sel["bytes"]), (os.path.join(os.path.abspath(self.mods), "ax01.kspkg"), True, 6))
        self.assertRegex(sel["modified"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_installed_of_the_draft_and_of_no_tune_is_the_package_of_the_default_id(self):
        self.put_package("ax01")
        self.put_package("ax_x", b"12")
        for path in ("/api/state", "/api/state?tune=draft"):
            with self.subTest(path):
                inst = self.get(path).json["installed"]
                self.assertEqual((os.path.basename(inst["path"]), inst["exists"], inst["bytes"]), ("ax_x.kspkg", True, 2))
        os.remove(os.path.join(self.mods, "ax_x.kspkg"))
        self.make_tune("ax01", {"name_suffix": "_B"})
        self.assertFalse(self.get("/api/state?tune=draft").json["installed"]["exists"])
        self.assertTrue(self.get("/api/state?tune=ax01").json["installed"]["exists"])

    def test_installed_info_for_a_tune(self):
        self.assertTrue(ts.installed_info("ks_x", "ax01")["path"].endswith("ax01.kspkg"))
        for tune_id in (None, "draft"):
            self.assertTrue(ts.installed_info("ks_x", tune_id)["path"].endswith("ax_x.kspkg"))

    def test_the_cars_list_keeps_the_default_package_flag(self):
        self.make_tune("ax01", {"name_suffix": "_B"})
        self.put_package("ax01")
        self.assertFalse(self.get("/api/state?tune=ax01").json["cars"][0]["installed"])

    def test_an_unexpandable_mods_folder_is_409_with_a_tune_too(self):
        ts.CONFIG["mods"] = "%ACE_TEST_NO_SUCH_VAR%/m"
        self.assertEqual(self.get("/api/state?tune=draft").status, 409)


class TestSettingsOfTunes(TuneCase):
    def row(self, rows, setting_id="limiter"):
        return next(r for r in rows if r["id"] == setting_id)

    def test_settings_show_the_values_of_the_selected_modded_car(self):
        self.make_tune("ax01", {"limiter": 8000, "name_suffix": "_A"})
        rows = self.get("/api/settings?tune=ax01").json
        self.assertEqual([r["id"] for r in rows], ["limiter", "aids_off", "name_suffix"])
        self.assertEqual((self.row(rows)["value"], self.row(rows)["default"], self.row(rows)["changed"]), (8000, 7000, True))
        self.assertEqual((self.row(rows, "name_suffix")["value"], self.row(rows, "name_suffix")["changed"]), ("_A", True))

    def test_the_page_row_of_a_legacy_suffix_shows_the_converted_value(self):
        self.make_tune(None, {"name_suffix": "_MY2"})
        rows = self.get("/api/settings").json
        row = [x for x in rows if x["id"] == "name_suffix"][0]
        self.assertEqual((row["value"], row["default"], row["changed"]), ("MY 2", "MY", True))

    def test_settings_of_the_draft_start_from_the_stock_defaults(self):
        self.make_tune(None, {"limiter": 8000})
        rows = self.get("/api/settings?tune=draft").json
        self.assertEqual((self.row(rows)["value"], self.row(rows)["changed"]), (7000, False))
        self.assertEqual(self.row(rows, "name_suffix")["value"], "MY")

    def test_settings_without_a_tune_are_those_of_the_default_modded_car(self):
        self.make_tune("ax01", {"limiter": 9000, "name_suffix": "_A"})
        self.make_tune(tune.DRAFT, {"limiter": 6000})
        self.assertEqual(self.row(self.get("/api/settings").json)["value"], 7000)
        self.make_tune(None, {"limiter": 8000})
        self.assertEqual(self.row(self.get("/api/settings").json)["value"], 8000)
        self.assertEqual(self.row(self.get("/api/settings?tune=ax_x").json)["value"], 8000)

    def test_settings_of_a_tune_are_409_without_a_base(self):
        tune.save_state(self.work, "ks_y", {"name_suffix": "_C"}, "ax02")
        for tune_id in ("draft", "ax02"):
            with self.subTest(tune_id):
                r = self.get("/api/settings?car=ks_y&tune=" + tune_id)
                self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_set_on_a_modded_car_changes_only_its_state(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        r = self.post("/api/set", {"id": "limiter", "value": "8000", "tune": "ax01"})
        self.assertEqual((r.status, r.json["row"]["value"], r.json["row"]["changed"], r.json["warnings"]), (200, 8000, True, []))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))

    def test_set_on_the_draft_needs_only_the_base_car(self):
        r = self.post("/api/set", {"id": "limiter", "value": "8000", "tune": "draft"})
        self.assertEqual((r.status, r.json["row"]["value"]), (200, 8000))
        self.assertEqual(self.tune_state("draft"), {"limiter": 8000})
        self.assertEqual(os.path.basename(tune.state_path(self.work, "ks_x", "draft")), "draft_state.json")
        self.assertEqual(self.tune_ids(), [])
        self.assertFalse(os.path.exists(self.state_file()))

    def test_set_on_a_tune_without_a_base_is_409_and_writes_nothing(self):
        tune.save_state(self.work, "ks_y", {"name_suffix": "_C"}, "ax02")
        for tune_id in ("draft", "ax02"):
            with self.subTest(tune_id):
                r = self.post("/api/set", {"car": "ks_y", "tune": tune_id, "id": "limiter", "value": "8000"})
                self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertEqual(tune.load_state(self.work, "ks_y", "ax02"), {"name_suffix": "_C"})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_y", "draft")))

    def test_the_default_the_draft_and_a_modded_car_keep_separate_values(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.post("/api/set", {"id": "limiter", "value": "9000", "tune": "ax01"})
        self.post("/api/set", {"id": "limiter", "value": "6000", "tune": "draft"})
        self.assertEqual(self.saved_state(), {"limiter": 8000})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 9000})
        self.assertEqual(self.tune_state("draft"), {"limiter": 6000})
        for query, value in (("", 8000), ("?tune=ax_x", 8000), ("?tune=ax01", 9000), ("?tune=draft", 6000)):
            with self.subTest(query):
                self.assertEqual(self.row(self.get("/api/settings" + query).json)["value"], value)

    def test_set_with_a_bad_value_on_a_tune_changes_nothing(self):
        self.make_tune("ax01", {"limiter": 7500, "name_suffix": "_A"})
        r = self.post("/api/set", {"id": "limiter", "value": "fast", "tune": "ax01"})
        self.assertEqual(r.status, 400)
        self.assertEqual(self.tune_state("ax01"), {"limiter": 7500, "name_suffix": "_A"})

    def test_unset_on_a_modded_car_and_on_the_draft(self):
        self.make_tune("ax01", {"limiter": 8000, "aids_off": True, "name_suffix": "_A"})
        self.make_tune(tune.DRAFT, {"limiter": 6000})
        self.make_tune(None, {"limiter": 5000})
        r = self.post("/api/unset", {"id": "limiter", "tune": "ax01"})
        self.assertEqual((r.status, r.json["row"]["value"], r.json["row"]["changed"]), (200, 7000, False))
        self.assertEqual(self.tune_state("ax01"), {"aids_off": True, "name_suffix": "_A"})
        r = self.post("/api/unset", {"id": "limiter", "tune": "draft"})
        self.assertEqual((r.status, self.tune_state("draft")), (200, {}))
        self.assertEqual(self.saved_state(), {"limiter": 5000})

    def test_edits_on_a_tune_are_refused_while_a_job_runs(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "ax01"}).status, 202)
        for path, body in (("/api/set", {"id": "limiter", "value": "8000"}), ("/api/unset", {"id": "limiter"}), ("/api/reset_all", {}),
                           ("/api/duplicate", {})):
            for tune_id in ("ax01", "draft"):
                with self.subTest(path, tune=tune_id):
                    self.assertEqual(self.post(path, dict(body, tune=tune_id)).status, 409)
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})

    def test_every_state_write_for_a_tune_happens_under_state_lock(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        held = []
        real = tune.save_state

        def spy(*args, **kw):
            held.append(ts.STATE_LOCK.locked())
            return real(*args, **kw)
        self.patch(tune, "save_state", spy)
        self.post("/api/set", {"id": "limiter", "value": "8000", "tune": "ax01"})
        self.post("/api/unset", {"id": "limiter", "tune": "ax01"})
        self.post("/api/reset_all", {"tune": "ax01"})
        self.post("/api/reset_all", {"tune": "draft"})
        self.post("/api/duplicate", {"tune": "ax01"})
        self.assertEqual(held, [True] * 5)

    def test_the_settings_of_a_tune_are_built_under_state_lock(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        held = []
        real = tune.effective_rows

        def spy(*args, **kw):
            held.append((kw.get("tune"), ts.STATE_LOCK.locked()))
            return real(*args, **kw)
        self.patch(tune, "effective_rows", spy)
        self.get("/api/settings?tune=ax01")
        self.assertEqual(held, [("ax01", True)])


class TestVariants(TuneCase):
    """The mechanical presets of a car (sub cars): listed in /api/state, shown read-only by /api/settings?variant=."""

    def setUp(self):
        super().setUp()
        self.addCleanup(ts.VARIANTS.clear)
        self.addCleanup(tune._resolved.clear)
        self.fc.add("presets/p.mechanicalcarpreset", {"brand": "Brand", "description": "Name Preset Base"})
        self.add_variant()

    def add_variant(self, name="q_drift", note="Drift"):
        gp = self.fc.game_path
        self.fc.add("presets/%s.mechanicalcarpreset" % name, {"note": note, "description": "Name Preset " + name,
                                                             "forced_compatible_part_paths": [gp("presets/parts/%s_engine.compatiblepart" % name)]})
        self.fc.add("presets/parts/%s_engine.compatiblepart" % name, {"car_part_path": gp("presets/parts/%s_engine.carpart" % name)})
        self.fc.add("presets/parts/%s_engine.carpart" % name, {"logic_parts": [{"tuning_part_path": gp("data/parts/%s_engine.tuningpart" % name)}]})
        self.fc.add("data/parts/%s_engine.tuningpart" % name, {"engine": {"path": gp("data/drift.carengine")}})
        self.fc.add("data/drift.carengine", {"limiter": 8000, "turbos_to_load": []})

    def variants(self, car="ks_x"):
        return next(c for c in self.get("/api/state").json["cars"] if c["id"] == car).get("variants")

    def test_state_lists_the_variants_of_an_extracted_car(self):
        self.assertEqual(self.variants(), [{"id": "q_drift", "label": "Drift", "error": None}])

    def test_a_car_without_variants_has_an_empty_list_and_a_car_that_is_not_extracted_has_none(self):
        os.remove(os.path.join(self.fc.car_root, "presets", "q_drift.mechanicalcarpreset"))
        self.assertEqual(self.variants(), [])
        self.assertIsNone(self.variants("ks_y"))

    def test_a_variant_with_a_broken_chain_is_listed_with_its_error(self):
        os.remove(os.path.join(self.fc.car_root, "presets", "parts", "q_drift_engine.carpart"))
        found = self.variants()
        self.assertEqual([(v["id"], v["label"]) for v in found], [("q_drift", "Drift")])
        self.assertIn("q_drift_engine.carpart", found[0]["error"])

    def test_state_does_not_fail_when_the_variants_cannot_be_listed(self):
        with mock.patch.object(tune, "list_variants", side_effect=ValueError("broken")):
            r = self.get("/api/state")
        self.assertEqual(r.status, 200)
        self.assertEqual(next(c for c in r.json["cars"] if c["id"] == "ks_x")["variants"], [])

    def test_the_variants_are_read_again_only_when_the_preset_or_part_files_change(self):
        with mock.patch.object(tune, "list_variants", wraps=tune.list_variants) as listing:
            for _ in range(3):
                self.assertEqual(len(self.variants()), 1)
            self.assertEqual(listing.call_count, 1)
            with open(os.path.join(self.fc.car_root, "presets", "q_drift.mechanicalcarpreset"), "ab") as f:
                f.write(b"x")
            self.variants()
            self.assertEqual(listing.call_count, 2)
            with open(os.path.join(self.fc.car_root, "data", "parts", "q_drift_engine.tuningpart"), "ab") as f:
                f.write(b"x")
            self.variants()
            self.assertEqual(listing.call_count, 3)

    def test_the_variant_settings_show_the_values_of_the_variant_as_defaults_and_values(self):
        self.make_tune(tune.DRAFT, {"limiter": 9000})
        r = self.get("/api/settings?variant=q_drift")
        rows = {x["id"]: x for x in r.json}
        self.assertEqual(r.status, 200)
        self.assertEqual((rows["limiter"]["default"], rows["limiter"]["value"], rows["limiter"]["changed"]), (8000, 8000, False))
        self.assertEqual(set(rows["limiter"]), ROW_KEYS | {"min", "max", "copy_values"})
        self.assertEqual([x["id"] for x in r.json], ["limiter", "aids_off", "name_suffix"])
        self.assertEqual(self.get("/api/settings").json[0]["default"], 7000)

    def test_the_variant_settings_carry_the_base_range_and_accept_the_draft_tune(self):
        self.write(os.path.join(self.work, tune.RANGES_FILE), {"limiter": {"low": 5000, "high": 9000}})
        r = self.get("/api/settings?tune=draft&variant=q_drift")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json[0]["base_range"], {"low": 5000, "high": 9000})

    def test_a_variant_together_with_a_modded_car_is_400(self):
        self.make_tune("ax01", {"limiter": 8500})
        r = self.get("/api/settings?tune=ax01&variant=q_drift")
        self.assertEqual((r.status, r.json), (400, {"error": "a variant cannot be combined with a modded car"}))

    def test_an_unknown_variant_is_400(self):
        r = self.get("/api/settings?variant=nope")
        self.assertEqual((r.status, r.json), (400, {"error": "ks_x has no variant nope"}))

    def test_a_variant_that_cannot_be_read_is_400(self):
        os.remove(os.path.join(self.fc.car_root, "presets", "parts", "q_drift_engine.carpart"))
        r = self.get("/api/settings?variant=q_drift")
        self.assertEqual(r.status, 400)
        self.assertIn("variant q_drift of ks_x cannot be read", r.json["error"])

    def test_a_variant_without_a_base_car_is_409(self):
        r = self.get("/api/settings?car=ks_y&variant=q_drift")
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_no_write_route_takes_a_variant(self):
        r = self.post("/api/set?tune=draft&variant=q_drift", {"id": "limiter", "value": 8100, "variant": "q_drift"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.tune_state(tune.DRAFT), {"limiter": 8100})
        self.assertEqual(self.tune_ids(), [])
        rows = {x["id"]: x for x in self.get("/api/settings?variant=q_drift").json}
        self.assertEqual((rows["limiter"]["value"], rows["limiter"]["changed"]), (8000, False))
        for route in ts.POST_ROUTES:
            self.assertNotIn("variant", inspect.getsource(ts.POST_ROUTES[route]))

    def test_only_the_settings_route_reads_the_variant(self):
        self.assertEqual(ts.VARIANT_ROUTES, ("/api/settings",))
        self.assertTrue(set(ts.VARIANT_ROUTES) <= set(ts.GET_ROUTES))
        self.assertTrue(set(ts.VARIANT_ROUTES).isdisjoint(ts.QUERY_ROUTES))


class TestResetAllOfTunes(TuneCase):
    def test_the_default_modded_car_is_cleared_completely(self):
        self.make_tune(None, {"limiter": 8000, "name_suffix": "_A"})
        self.assertEqual(self.post("/api/reset_all").json, {"ok": True})
        self.assertEqual(self.saved_state(), {})
        self.assertEqual(self.post("/api/reset_all", {"tune": "ax_x"}).status, 200)
        self.assertEqual(self.saved_state(), {})

    def test_the_draft_is_cleared_completely(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000, "name_suffix": "_A"})
        self.make_tune("ax01", {"limiter": 9000, "name_suffix": "_B"})
        r = self.post("/api/reset_all", {"tune": "draft"})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual(self.tune_state("draft"), {})
        self.assertEqual(self.tune_state("ax01"), {"limiter": 9000, "name_suffix": "_B"})

    def test_another_modded_car_keeps_its_name_suffix(self):
        self.make_tune(None, {"limiter": 8000, "name_suffix": "_A"})
        self.make_tune("ax01", {"limiter": 9000, "aids_off": True, "name_suffix": "_B"})
        r = self.post("/api/reset_all", {"tune": "ax01"})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_B"})
        self.assertEqual(self.saved_state(), {"limiter": 8000, "name_suffix": "_A"})
        self.assertEqual([t["name_suffix"] for t in tune.list_tunes(self.work, "ks_x")], ["_A", "_B"])
        rows = self.get("/api/settings?tune=ax01").json
        self.assertEqual([r["changed"] for r in rows], [False, False, True])

    def test_a_legacy_suffix_is_kept_converted_by_a_reset(self):
        self.make_tune(None, {"name_suffix": "_MY"})
        self.make_tune("ax01", {"limiter": 9000, "name_suffix": "_MY2"})
        self.post("/api/reset_all", {"tune": "ax01"})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "MY 2"})

    def test_a_modded_car_without_a_saved_suffix_is_reset_to_an_empty_state(self):
        self.make_tune("ax01", {"limiter": 9000})
        self.post("/api/reset_all", {"tune": "ax01"})
        self.assertEqual(self.tune_state("ax01"), {})
        self.assertEqual(self.tune_ids(), ["ax01"])

    def test_reset_all_of_a_tune_without_a_base_is_409_and_writes_nothing(self):
        tune.save_state(self.work, "ks_y", {"name_suffix": "_C", "limiter": 1}, "ax02")
        for tune_id in ("draft", "ax02"):
            with self.subTest(tune_id):
                r = self.post("/api/reset_all", {"car": "ks_y", "tune": tune_id})
                self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertEqual(tune.load_state(self.work, "ks_y", "ax02"), {"name_suffix": "_C", "limiter": 1})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_y", "draft")))


class TestDuplicateRoute(TuneCase):
    def test_a_legacy_source_suffix_is_counted_up_from_its_converted_form(self):
        self.make_tune(None, {"limiter": 8000, "name_suffix": "_MY"})
        r = self.post("/api/duplicate", {})
        self.assertEqual((r.status, r.json), (200, {"id": "ax01", "stock": "ks_x", "name_suffix": "MY 2"}))
        self.assertEqual(self.tune_state("ax01"), {"limiter": 8000, "name_suffix": "MY 2"})
        self.assertEqual(self.saved_state(), {"limiter": 8000, "name_suffix": "_MY"})

    def test_the_default_modded_car_is_copied_with_an_automatic_id_and_suffix(self):
        self.make_tune(None, {"limiter": 8000, "name_suffix": "_A"})
        r = self.post("/api/duplicate", {})
        self.assertEqual((r.status, r.json), (200, {"id": "ax01", "stock": "ks_x", "name_suffix": "_A 2"}))
        self.assertEqual(self.tune_state("ax01"), {"limiter": 8000, "name_suffix": "_A 2"})
        self.assertEqual(self.saved_state(), {"limiter": 8000, "name_suffix": "_A"})
        self.assertEqual(self.tune_ids(), ["ax_x", "ax01"])

    def test_a_modded_car_is_copied_and_the_counter_goes_on(self):
        self.make_tune("ax01", {"limiter": 8000, "name_suffix": "_A"})
        self.make_tune("ax02", {"limiter": 9000, "name_suffix": "_B"})
        r = self.post("/api/duplicate", {"tune": "ax01"})
        self.assertEqual((r.status, r.json), (200, {"id": "ax03", "stock": "ks_x", "name_suffix": "_A 2"}))
        self.assertEqual(self.tune_state("ax03"), {"limiter": 8000, "name_suffix": "_A 2"})
        self.assertEqual(self.tune_state("ax01"), {"limiter": 8000, "name_suffix": "_A"})

    def test_the_draft_is_copied_and_stays_as_it_is(self):
        self.make_tune(tune.DRAFT, {"limiter": 8000})
        r = self.post("/api/duplicate", {"tune": "draft"})
        self.assertEqual((r.status, r.json), (200, {"id": "ax01", "stock": "ks_x", "name_suffix": "MY"}))
        self.assertEqual(self.tune_state("ax01"), {"limiter": 8000, "name_suffix": "MY"})
        self.assertEqual(self.tune_state("draft"), {"limiter": 8000})

    def test_an_explicit_id_and_suffix_are_used(self):
        self.make_tune(None, {"name_suffix": "_A"})
        r = self.post("/api/duplicate", {"new_id": "ax_z", "suffix": "_Z"})
        self.assertEqual((r.status, r.json), (200, {"id": "ax_z", "stock": "ks_x", "name_suffix": "_Z"}))
        self.assertEqual(self.tune_state("ax_z"), {"name_suffix": "_Z"})

    def test_null_id_and_suffix_mean_automatic(self):
        self.make_tune(None, {"name_suffix": "_A"})
        r = self.post("/api/duplicate", {"new_id": None, "suffix": None})
        self.assertEqual((r.json["id"], r.json["name_suffix"]), ("ax01", "_A 2"))

    def test_an_id_that_is_used_is_400_with_the_message_and_changes_nothing(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.make_tune("ax01", {"name_suffix": "_B"})
        self.put_package("ax02")
        for new_id, text in (("ax01", "tuned car id ax01 is already used or reserved"), ("ax02", "tuned car id ax02 is already used or reserved"),
                             ("ax_x", "ax_x is already a tune of ks_x"), ("ax_y", "tuned car id ax_y is already used or reserved"),
                             ("ks_x", "new id equals the old id 'ks_x'")):
            with self.subTest(new_id):
                r = self.post("/api/duplicate", {"new_id": new_id})
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual(self.tune_ids(), ["ax_x", "ax01"])

    def test_an_id_that_is_not_a_plain_same_length_id_is_400(self):
        for new_id in ("../../x", "../x", "AX_Y", "ax y", "ax_yy", "ax", "ax-y", "ax_\u00e9", "ax/y", "a\x00b_", ""):
            with self.subTest(new_id):
                self.assertEqual(self.post("/api/duplicate", {"new_id": new_id}).status, 400)
        self.assertEqual(self.tune_ids(), [])
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "tunes")))

    def test_a_suffix_that_another_modded_car_uses_is_400_with_the_message(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.make_tune("ax01", {"name_suffix": "_B"})
        r = self.post("/api/duplicate", {"suffix": "_B"})
        self.assertEqual((r.status, r.json), (400, {"error": "car name already used by ax01"}))
        self.assertEqual(self.post("/api/duplicate", {"suffix": ""}).status, 400)
        self.assertEqual(self.post("/api/duplicate", {"suffix": "x" * 31}).status, 400)
        self.assertEqual(self.tune_ids(), ["ax_x", "ax01"])

    def test_an_id_or_suffix_that_is_not_text_is_400(self):
        for body, text in (({"new_id": 5}, "new_id must be text"), ({"new_id": ["ax01"]}, "new_id must be text"),
                           ({"suffix": 5}, "suffix must be text"), ({"suffix": True}, "suffix must be text")):
            with self.subTest(body):
                self.assertEqual(self.post("/api/duplicate", body).json, {"error": text})
        self.assertEqual(self.tune_ids(), [])

    def test_duplicate_is_409_while_a_job_runs_and_writes_nothing(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        self.entered.wait(5)
        r = self.post("/api/duplicate", {})
        self.assertEqual(r.status, 409, r.json)
        self.assertEqual(self.tune_ids(), ["ax_x"])
        self.finish_held_job()
        self.assertEqual(self.post("/api/duplicate", {}).status, 200)

    def test_duplicate_needs_the_base_car(self):
        tune.save_state(self.work, "ks_y", {"name_suffix": "_C"}, "ax02")
        for tune_id in (None, "draft", "ax02"):
            with self.subTest(tune_id):
                r = self.post("/api/duplicate", {"car": "ks_y", "tune": tune_id})
                self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertEqual([t["id"] for t in tune.list_tunes(self.work, "ks_y")], ["ax02"])

    def test_an_unexpandable_mods_folder_is_409(self):
        ts.CONFIG["mods"] = "%ACE_TEST_NO_SUCH_VAR%/m"
        r = self.post("/api/duplicate", {})
        self.assertEqual((r.status, r.json), (409, {"error": "cannot expand the mods folder '%ACE_TEST_NO_SUCH_VAR%/m' (pass --mods <folder>)"}))
        self.assertEqual(self.tune_ids(), [])

    def test_a_duplicate_shows_up_in_the_state_and_starts_no_job(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.post("/api/duplicate", {})
        state = self.get("/api/state").json
        self.assertEqual([(m["id"], m["label"]) for m in state["modded"]], [("ax_x", "Car X _A"), ("ax01", "Car X _A 2")])
        self.assertEqual((state["job"]["state"], self.calls), ("idle", []))

    def test_the_duplicate_is_not_built_or_installed(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.post("/api/duplicate", {})
        self.assertFalse(os.path.exists(os.path.join(tune.build_dir(self.work, "ks_x"), "ax01")))
        self.assertFalse(os.path.exists(os.path.join(self.mods, "ax01.kspkg")))
        modded = {m["id"]: m for m in self.get("/api/state").json["modded"]}
        self.assertEqual((modded["ax01"]["built"], modded["ax01"]["installed"]), (False, False))

    def test_the_automatic_id_takes_the_installed_packages_into_account(self):
        self.make_tune(None, {"name_suffix": "_A"})
        self.put_package("ax01")
        self.assertEqual(self.post("/api/duplicate", {}).json["id"], "ax02")

    def test_the_default_modded_car_is_the_source_when_no_tune_is_given_even_if_it_does_not_exist(self):
        r = self.post("/api/duplicate", {})
        self.assertEqual((r.status, r.json), (200, {"id": "ax01", "stock": "ks_x", "name_suffix": "MY"}))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "MY"})


# -------------------------------------------------------------------------------------------------- setting groups
class TestGroupsRoute(TuneCase):
    """GET /api/groups: the group list of the catalogue, static, independent of the car, the tune and the base car."""

    def setUp(self):
        super().setUp()
        self.cat = mini_catalogue(limiter(), suffix(), tyre_dy("front"))
        self.cat["groups"] = [{"name": "Tyres", "description": "Grip and türkis"}, {"name": "G", "description": "General"}]

    def expected(self):
        return {"groups": [{"name": "Tyres", "description": "Grip and türkis"}, {"name": "G", "description": "General"}]}

    def test_it_answers_the_groups_with_name_and_description_in_catalogue_order(self):
        r = self.get("/api/groups")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control")),
                         (200, "application/json; charset=utf-8", "no-store"))
        self.assertEqual(r.json, self.expected())
        self.assertEqual(r.json, {"groups": tune.group_list()})
        self.assertEqual([g["name"] for g in r.json["groups"]], ["Tyres", "G"])
        self.assertEqual([set(g) for g in r.json["groups"]], [{"name", "description"}] * 2)

    def test_the_groups_of_the_real_catalogue_are_answered_in_the_order_of_the_file(self):
        real = tune.read_json(tune.CATALOGUE)
        self.patch(tune, "load_catalogue", lambda path=None: real)
        r = self.get("/api/groups")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json, {"groups": [{"name": g["name"], "description": g["description"]} for g in real["groups"]]})
        self.assertGreater(len(r.json["groups"]), 1)

    def test_it_needs_no_base_car(self):
        self.assertFalse(ts.base_present(self.work, "ks_y"))
        self.assertEqual(self.get("/api/settings?car=ks_y").status, 409)
        r = self.get("/api/groups?car=ks_y")
        self.assertEqual((r.status, r.json), (200, self.expected()))

    def test_it_is_the_same_for_the_draft_the_default_tune_and_a_modded_car(self):
        self.make_tune("ax01", {"limiter": 9000})
        self.make_tune(None, {"limiter": 8000})
        for query in ("", "?tune=draft", "?tune=ax01", "?tune=ax_x", "?car=ks_x&tune=ax01"):
            with self.subTest(query):
                r = self.get("/api/groups" + query)
                self.assertEqual((r.status, r.json), (200, self.expected()))

    def test_the_dispatcher_still_resolves_the_car_and_the_tune(self):
        r = self.get("/api/groups?car=nope")
        self.assertEqual(r.status, 400)
        self.assertTrue(r.json["error"].startswith("unknown car"), r.json)
        r = self.get("/api/groups?tune=nope")
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))

    def test_it_needs_neither_the_state_lock_nor_an_idle_job_and_writes_nothing(self):
        with ts.STATE_LOCK:
            self.assertEqual(self.get("/api/groups").status, 200)
        ts.JOB["state"] = "running"
        self.assertEqual(self.get("/api/groups").status, 200)
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertEqual(self.tune_ids(), [])

    def test_it_checks_the_host_and_is_405_for_other_methods_and_404_for_a_post(self):
        r = self.get("/api/groups", host="evil.example")
        self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method):
                r = self.request(method, "/api/groups")
                self.assertEqual((r.status, r.json, r.headers.get("Allow")), (405, {"error": "method not allowed"}, "GET, POST"))
        self.assertEqual(self.post("/api/groups").status, 404)

    def test_the_handler_gets_the_resolved_car_and_tune_and_no_query(self):
        seen = []
        with mock.patch.dict(ts.GET_ROUTES, {"/api/groups": lambda car, tune_id: seen.append((car, tune_id)) or {"groups": []}}):
            r = self.get("/api/groups?id=soft&tune=draft")
        self.assertEqual((r.status, r.json, seen), (200, {"groups": []}, [("ks_x", "draft")]))
        self.assertNotIn("/api/groups", ts.QUERY_ROUTES)


# -------------------------------------------------------------------------------------------------- session logger
class LogCase(ServerCase):
    """ServerCase with the real catalogue (the channel table is checked against it); the logs folder is a scratch folder (ts.CONFIG["logs"])."""

    def setUp(self):
        super().setUp()
        self.patch(tune, "load_catalogue", lambda path=None: REAL_CATALOGUE)
        self.config_file = logconf.config_path(self.work)
        self.status_file = os.path.join(self.logs, "logger_status.json")

    def groups(self, reply):
        return {g["id"]: g for g in reply.json["groups"]}

    def ticked(self, reply):
        return [r["id"] for g in reply.json["groups"] for r in g["rows"] if r["ticked"]]

    def session(self, name, mtime, car="ks_x"):
        path = self.write(os.path.join(self.logs, name), json.dumps({"type": "header", "car": car, "track": "Imola"}) + "\n"
                          + json.dumps({"type": "end", "duration_s": 5.5, "samples": 9}) + "\n")
        os.utime(path, (mtime, mtime))


class TestLogConfigRoute(LogCase):
    """GET /api/log_config and POST /api/log_config_set: the choice of the logger, saved in <work>/log_config.json."""

    def valid(self, **more):
        return dict({"ticked": ["limiter", "behaviour.speed"], "rate_hz": 60}, **more)

    def test_the_default_choice_when_there_is_no_file(self):
        r = self.get("/api/log_config")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control")),
                         (200, "application/json; charset=utf-8", "no-store"))
        self.assertEqual(set(r.json), {"rate_hz", "rates", "groups"})
        self.assertEqual((r.json["rate_hz"], r.json["rates"]), (30, [30, 60]))
        self.assertEqual(self.ticked(r), ["behaviour.speed", "behaviour.rpm", "behaviour.gas", "behaviour.brake"])
        self.assertFalse(os.path.exists(self.config_file))

    def test_the_groups_are_the_tree_of_the_channel_table(self):
        r = self.get("/api/log_config")
        chan = logconf.load_channels()
        self.assertEqual(r.json["groups"], logconf.tree(chan, REAL_CATALOGUE, logconf.default_config(chan)))
        ids = [g["id"] for g in r.json["groups"]]
        self.assertEqual(ids[:2], ["behaviour", "car_state"])
        self.assertEqual(sorted(ids[2:]), sorted("catalogue." + g["name"] for g in REAL_CATALOGUE["groups"]))
        counts = [g["tickable"] for g in r.json["groups"][2:]]
        self.assertEqual(counts, sorted(counts, key=lambda c: c == 0))

    def test_the_saved_choice_is_answered(self):
        self.write(self.config_file, {"version": 1, "rate_hz": 60, "ticked": ["limiter", "car_state.turbo"]})
        r = self.get("/api/log_config")
        self.assertEqual((r.status, r.json["rate_hz"]), (200, 60))
        self.assertEqual(self.ticked(r), ["car_state.turbo", "limiter"])

    def test_a_damaged_or_invalid_file_answers_the_default_choice(self):
        for data in ("{not json", json.dumps({"version": 1, "rate_hz": 45, "ticked": []}),
                     json.dumps({"version": 1, "rate_hz": 60, "ticked": ["gear_1"]})):
            with self.subTest(data):
                self.write(self.config_file, data)
                r = self.get("/api/log_config")
                self.assertEqual((r.status, r.json["rate_hz"]), (200, 30))
                self.assertEqual(self.ticked(r), ["behaviour.speed", "behaviour.rpm", "behaviour.gas", "behaviour.brake"])

    def test_set_saves_the_choice_and_answers_like_get(self):
        r = self.post("/api/log_config_set", self.valid())
        self.assertEqual((r.status, r.headers.get("Content-Type")), (200, "application/json; charset=utf-8"))
        self.assertEqual(r.json["rate_hz"], 60)
        self.assertEqual(self.ticked(r), ["behaviour.speed", "limiter"])
        self.assertEqual(self.get("/api/log_config").json, r.json)
        with open(self.config_file, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 1, "rate_hz": 60, "ticked": ["limiter", "behaviour.speed"]})

    def test_set_with_nothing_ticked_is_a_valid_choice(self):
        r = self.post("/api/log_config_set", {"ticked": [], "rate_hz": 30})
        self.assertEqual((r.status, self.ticked(r)), (200, []))
        self.assertEqual(self.ticked(self.get("/api/log_config")), [])

    def test_set_normalises_the_order_and_a_later_set_replaces_the_choice(self):
        self.post("/api/log_config_set", {"ticked": ["car_state.turbo", "behaviour.rpm", "fuel_start"], "rate_hz": 60})
        self.assertEqual(self.ticked(self.get("/api/log_config")), ["behaviour.rpm", "car_state.turbo", "fuel_start"])
        with open(self.config_file, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["ticked"], ["fuel_start", "behaviour.rpm", "car_state.turbo"])
        self.post("/api/log_config_set", {"ticked": ["limiter"], "rate_hz": 30})
        r = self.get("/api/log_config")
        self.assertEqual((r.json["rate_hz"], self.ticked(r)), (30, ["limiter"]))

    def test_only_direct_settings_and_extra_rows_are_tickable_in_the_answer(self):
        r = self.get("/api/log_config")
        direct = [row["id"] for g in r.json["groups"][2:] for row in g["rows"] if row["tickable"]]
        self.assertEqual(len(direct), 33)
        self.assertIn("limiter", direct)
        self.assertNotIn("gear_1", direct)

    def test_a_bad_body_is_a_400_and_writes_nothing(self):
        bodies = [{}, {"ticked": []}, {"rate_hz": 30}, {"ticked": "limiter", "rate_hz": 30}, {"ticked": None, "rate_hz": 30},
                  {"ticked": ["limiter", 5], "rate_hz": 30}, {"ticked": ["limiter"], "rate_hz": "30"}, {"ticked": ["limiter"], "rate_hz": True},
                  {"ticked": ["limiter"], "rate_hz": 30.0}, {"ticked": ["limiter"], "rate_hz": 45}, {"ticked": ["limiter"], "rate_hz": 0},
                  {"ticked": ["no_such_id"], "rate_hz": 30}, {"ticked": ["behaviour.nope"], "rate_hz": 30},
                  {"ticked": ["gear_1"], "rate_hz": 30}, {"ticked": ["toe_front"], "rate_hz": 30}, {"ticked": ["limiter", "limiter"], "rate_hz": 30}]
        for body in bodies:
            with self.subTest(body):
                r = self.post("/api/log_config_set", body)
                self.assertEqual(r.status, 400)
                self.assertEqual(set(r.json), {"error"})
                self.assertIsInstance(r.json["error"], str)
                self.assertFalse(os.path.exists(self.config_file))
                self.assertFalse(os.path.exists(self.config_file + ".tmp"))

    def test_the_error_names_an_unknown_greyed_or_doubled_id_and_a_bad_rate(self):
        for ticked, rate, text in ((["no_such_id"], 30, "unknown id no_such_id"), (["gear_1"], 30, "gear_1 is greyed"),
                                   (["limiter", "limiter"], 30, "limiter is ticked twice"), (["limiter"], 45, "rate_hz must be 30 or 60")):
            with self.subTest(text):
                r = self.post("/api/log_config_set", {"ticked": ticked, "rate_hz": rate})
                self.assertEqual(r.status, 400)
                self.assertIn(text, r.json["error"])

    def test_a_bad_body_leaves_the_saved_choice_alone(self):
        self.post("/api/log_config_set", self.valid())
        with open(self.config_file, "rb") as f:
            before = f.read()
        self.assertEqual(self.post("/api/log_config_set", {"ticked": ["gear_1"], "rate_hz": 30}).status, 400)
        with open(self.config_file, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_malformed_bodies_are_the_usual_400_413_and_415(self):
        self.assertEqual(self.post("/api/log_config_set", b"{not json").status, 400)
        self.assertEqual(self.post("/api/log_config_set", b"[1]").status, 400)
        self.assertEqual(self.request("POST", "/api/log_config_set", None, headers={"Content-Length": str(ts.MAX_BODY + 1)}).status, 413)
        r = self.post("/api/log_config_set", self.valid(), headers={"Content-Type": "text/plain"})
        self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        self.assertFalse(os.path.exists(self.config_file))

    def test_the_header_rule_of_every_post_route(self):
        r = self.post("/api/log_config_set", self.valid(), headers={"X-Tuner": None})
        self.assertEqual((r.status, r.json), (403, {"error": "missing header X-Tuner: 1"}))
        r = self.post("/api/log_config_set", self.valid(), headers={"X-Tuner": "0"})
        self.assertEqual(r.status, 403)
        r = self.post("/api/log_config_set", self.valid(), post_headers=False)
        self.assertEqual(r.status, 403)
        r = self.post("/api/log_config_set", self.valid(), host="evil.example")
        self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))
        self.assertFalse(os.path.exists(self.config_file))

    def test_methods_and_paths(self):
        self.assertEqual(self.post("/api/log_config").status, 404)
        self.assertEqual(self.get("/api/log_config_set").status, 404)
        for method in ("PUT", "DELETE", "PATCH"):
            for path in ("/api/log_config", "/api/log_config_set"):
                with self.subTest((method, path)):
                    r = self.request(method, path)
                    self.assertEqual((r.status, r.json, r.headers.get("Allow")), (405, {"error": "method not allowed"}, "GET, POST"))
        self.assertEqual(self.get("/api/log_config", host="evil.example").status, 403)

    def test_it_needs_no_base_car_and_the_dispatcher_still_resolves_the_car_and_the_tune(self):
        self.assertFalse(ts.base_present(self.work, "ks_y"))
        self.assertEqual(self.get("/api/log_config?car=ks_y").status, 200)
        self.assertEqual(self.post("/api/log_config_set", self.valid(car="ks_y")).status, 200)
        r = self.get("/api/log_config?car=nope")
        self.assertEqual(r.status, 400)
        self.assertTrue(r.json["error"].startswith("unknown car"), r.json)
        os.remove(self.config_file)
        r = self.post("/api/log_config_set", self.valid(car="nope"))
        self.assertEqual(r.status, 400)
        self.assertFalse(os.path.exists(self.config_file))
        r = self.get("/api/log_config?tune=nope")
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))

    def test_the_choice_is_the_same_for_every_car_and_tune(self):
        self.post("/api/log_config_set", self.valid())
        for query in ("", "?car=ks_y", "?tune=draft", "?car=ks_x&tune=draft"):
            with self.subTest(query):
                self.assertEqual(self.ticked(self.get("/api/log_config" + query)), ["behaviour.speed", "limiter"])

    def test_it_needs_neither_the_state_lock_nor_an_idle_job(self):
        with ts.STATE_LOCK:
            self.assertEqual(self.get("/api/log_config").status, 200)
            self.assertEqual(self.post("/api/log_config_set", self.valid()).status, 200)
        ts.JOB["state"] = "running"
        self.assertEqual(self.get("/api/log_config").status, 200)
        self.assertEqual(self.post("/api/log_config_set", self.valid(rate_hz=30)).status, 200)

    def test_the_handlers_get_the_resolved_car_and_tune(self):
        seen = []
        with mock.patch.dict(ts.GET_ROUTES, {"/api/log_config": lambda car, tune_id: seen.append((car, tune_id)) or {"rate_hz": 30}}):
            r = self.get("/api/log_config?tune=draft")
        self.assertEqual((r.status, r.json, seen), (200, {"rate_hz": 30}, [("ks_x", "draft")]))
        self.assertNotIn("/api/log_config", ts.QUERY_ROUTES)
        self.assertNotIn("/api/log_config_set", ts.ACCEPTED)

    def test_a_damaged_channel_table_is_a_500_with_the_text(self):
        with mock.patch.object(logconf, "load_channels", side_effect=ValueError("log channels: broken")):
            r = self.get("/api/log_config")
            self.assertEqual((r.status, r.json), (500, {"error": "log channels: broken"}))
            r = self.post("/api/log_config_set", self.valid())
            self.assertEqual((r.status, r.json), (500, {"error": "log channels: broken"}))
        self.assertFalse(os.path.exists(self.config_file))


class TestLogConfigResetRoute(LogCase):
    """POST /api/log_config_reset: removes <work>/log_config.json, so the default choice of the channel table applies again."""

    DEFAULT = ["behaviour.speed", "behaviour.rpm", "behaviour.gas", "behaviour.brake"]

    def everything(self):
        return {"ticked": logconf.tickable_ids(logconf.load_channels()), "rate_hz": 60}

    def test_the_saved_file_is_removed_and_the_answer_is_the_default_choice(self):
        self.post("/api/log_config_set", self.everything())
        self.assertTrue(os.path.exists(self.config_file))
        r = self.post("/api/log_config_reset", {})
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control")),
                         (200, "application/json; charset=utf-8", "no-store"))
        self.assertEqual(set(r.json), {"rate_hz", "rates", "groups"})
        self.assertEqual((r.json["rate_hz"], r.json["rates"]), (30, [30, 60]))
        self.assertEqual(self.ticked(r), self.DEFAULT)
        self.assertFalse(os.path.exists(self.config_file))

    def test_the_answer_is_the_answer_of_get_and_a_later_get_returns_the_default(self):
        self.post("/api/log_config_set", self.everything())
        r = self.post("/api/log_config_reset", {})
        self.assertEqual(r.json, self.get("/api/log_config").json)
        chan = logconf.load_channels()
        self.assertEqual(r.json["groups"], logconf.tree(chan, REAL_CATALOGUE, logconf.default_config(chan)))
        self.assertEqual(self.ticked(self.get("/api/log_config")), self.DEFAULT)

    def test_a_missing_file_is_fine(self):
        self.assertFalse(os.path.exists(self.config_file))
        r = self.post("/api/log_config_reset", {})
        self.assertEqual((r.status, r.json["rate_hz"], self.ticked(r)), (200, 30, self.DEFAULT))
        self.assertFalse(os.path.exists(self.config_file))

    def test_a_second_reset_and_a_save_after_a_reset_are_fine(self):
        self.post("/api/log_config_set", self.everything())
        self.assertEqual(self.post("/api/log_config_reset", {}).status, 200)
        self.assertEqual(self.post("/api/log_config_reset", {}).status, 200)
        r = self.post("/api/log_config_set", {"ticked": ["limiter"], "rate_hz": 60})
        self.assertEqual((r.status, r.json["rate_hz"], self.ticked(r)), (200, 60, ["limiter"]))
        self.assertEqual(self.ticked(self.get("/api/log_config")), ["limiter"])

    def test_the_body_is_not_read_for_fields(self):
        self.post("/api/log_config_set", self.everything())
        r = self.post("/api/log_config_reset", {"ticked": ["limiter"], "rate_hz": 60})
        self.assertEqual((r.status, r.json["rate_hz"], self.ticked(r)), (200, 30, self.DEFAULT))

    def test_a_file_that_cannot_be_removed_is_a_500_and_stays(self):
        os.makedirs(self.config_file)
        r = self.post("/api/log_config_reset", {})
        self.assertEqual((r.status, set(r.json)), (500, {"error"}))
        self.assertTrue(os.path.isdir(self.config_file))

    def test_malformed_bodies_are_the_usual_400_413_and_415_and_remove_nothing(self):
        self.post("/api/log_config_set", self.everything())
        self.assertEqual(self.post("/api/log_config_reset", b"{not json").status, 400)
        self.assertEqual(self.post("/api/log_config_reset", b"[1]").status, 400)
        self.assertEqual(self.request("POST", "/api/log_config_reset", None, headers={"Content-Length": str(ts.MAX_BODY + 1)}).status, 413)
        r = self.post("/api/log_config_reset", {}, headers={"Content-Type": "text/plain"})
        self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        self.assertTrue(os.path.exists(self.config_file))

    def test_the_header_rule_of_every_post_route(self):
        self.post("/api/log_config_set", self.everything())
        r = self.post("/api/log_config_reset", {}, headers={"X-Tuner": None})
        self.assertEqual((r.status, r.json), (403, {"error": "missing header X-Tuner: 1"}))
        r = self.post("/api/log_config_reset", {}, headers={"X-Tuner": "0"})
        self.assertEqual(r.status, 403)
        r = self.post("/api/log_config_reset", {}, post_headers=False)
        self.assertEqual(r.status, 403)
        r = self.post("/api/log_config_reset", {}, host="evil.example")
        self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))
        self.assertTrue(os.path.exists(self.config_file))

    def test_methods_and_paths(self):
        self.post("/api/log_config_set", self.everything())
        self.assertEqual(self.get("/api/log_config_reset").status, 404)
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method):
                r = self.request(method, "/api/log_config_reset")
                self.assertEqual((r.status, r.json, r.headers.get("Allow")), (405, {"error": "method not allowed"}, "GET, POST"))
        self.assertTrue(os.path.exists(self.config_file))

    def test_it_needs_no_base_car_and_the_dispatcher_still_resolves_the_car_and_the_tune(self):
        self.assertFalse(ts.base_present(self.work, "ks_y"))
        self.assertEqual(self.post("/api/log_config_reset", {"car": "ks_y"}).status, 200)
        self.post("/api/log_config_set", self.everything())
        r = self.post("/api/log_config_reset", {"car": "nope"})
        self.assertEqual(r.status, 400)
        self.assertTrue(r.json["error"].startswith("unknown car"), r.json)
        self.assertTrue(os.path.exists(self.config_file))
        r = self.post("/api/log_config_reset", {"tune": "nope"})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))
        self.assertTrue(os.path.exists(self.config_file))

    def test_it_needs_neither_the_state_lock_nor_an_idle_job(self):
        with ts.STATE_LOCK:
            self.assertEqual(self.post("/api/log_config_reset", {}).status, 200)
        ts.JOB["state"] = "running"
        self.assertEqual(self.post("/api/log_config_reset", {}).status, 200)

    def test_it_is_no_job_and_no_query_route(self):
        self.assertNotIn("/api/log_config_reset", ts.ACCEPTED)
        self.assertNotIn("/api/log_config_reset", ts.QUERY_ROUTES)
        self.assertNotIn("/api/log_config_reset", ts.LOCAL_ROUTES)

    def test_a_damaged_channel_table_is_a_500_with_the_text_and_removes_nothing(self):
        self.post("/api/log_config_set", self.everything())
        with mock.patch.object(logconf, "load_channels", side_effect=ValueError("log channels: broken")):
            r = self.post("/api/log_config_reset", {})
            self.assertEqual((r.status, r.json), (500, {"error": "log channels: broken"}))
        self.assertTrue(os.path.exists(self.config_file))


class TestLogSessionsRoute(LogCase):
    """GET /api/log_sessions: the newest session files of the logs folder (--logs)."""

    def test_a_missing_logs_folder_gives_an_empty_list(self):
        r = self.get("/api/log_sessions")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.json), (200, "application/json; charset=utf-8", {"sessions": []}))

    def test_the_sessions_come_newest_first_with_their_header_and_end_values(self):
        self.session("a.jsonl", 1000, car="ks_a")
        self.session("b.jsonl", 3000, car="ks_b")
        self.session("c.jsonl", 2000, car="ks_c")
        r = self.get("/api/log_sessions")
        self.assertEqual([s["file"] for s in r.json["sessions"]], ["b.jsonl", "c.jsonl", "a.jsonl"])
        self.assertEqual(set(r.json["sessions"][0]), {"file", "size", "modified", "car", "track", "duration_s", "samples"})
        self.assertEqual(r.json["sessions"][0], dict(logconf.list_sessions(self.logs)[0]))
        self.assertEqual((r.json["sessions"][0]["car"], r.json["sessions"][0]["track"], r.json["sessions"][0]["duration_s"],
                          r.json["sessions"][0]["samples"], r.json["sessions"][0]["modified"]), ("ks_b", "Imola", 5.5, 9, 3000))

    def test_only_the_newest_20_are_listed(self):
        for i in range(23):
            self.session("s%02d.jsonl" % i, 1000 + i)
        sessions = self.get("/api/log_sessions").json["sessions"]
        self.assertEqual((len(sessions), sessions[0]["file"], sessions[-1]["file"]), (20, "s22.jsonl", "s03.jsonl"))

    def test_a_damaged_file_is_listed_with_empty_values(self):
        self.write(os.path.join(self.logs, "bad.jsonl"), "{broken")
        s, = self.get("/api/log_sessions").json["sessions"]
        self.assertEqual((s["file"], s["car"], s["track"], s["duration_s"], s["samples"]), ("bad.jsonl", None, None, None, None))

    def test_the_folder_is_the_logs_option_of_the_server(self):
        other = str(self.d / "other_logs")
        self.session("here.jsonl", 1000)
        self.write(os.path.join(other, "there.jsonl"), "{}")
        ts.CONFIG["logs"] = other
        self.assertEqual([s["file"] for s in self.get("/api/log_sessions").json["sessions"]], ["there.jsonl"])

    def test_it_needs_no_base_car_and_no_idle_job_and_writes_nothing(self):
        ts.JOB["state"] = "running"
        with ts.STATE_LOCK:
            self.assertEqual(self.get("/api/log_sessions?car=ks_y").status, 200)
        self.assertFalse(os.path.exists(self.logs))
        self.assertEqual(self.get("/api/log_sessions?car=nope").status, 400)

    def test_methods_and_paths(self):
        self.assertEqual(self.post("/api/log_sessions").status, 404)
        self.assertEqual(self.request("PUT", "/api/log_sessions").status, 405)
        self.assertEqual(self.get("/api/log_sessions", host="evil.example").status, 403)


class TestLogStatusRoute(LogCase):
    """GET /api/log_status: whether the logger runs, from <logs>/logger_status.json."""
    NOT_RUNNING = {"running": False, "state": "not running", "file": None, "samples": None, "started": None, "seconds": None}

    def put(self, **more):
        now = time.time()
        data = dict({"state": "logging", "file": "x.jsonl", "samples": 40, "started": now - 20, "updated": now, "pid": 7}, **more)
        self.write(self.status_file, data)

    def test_no_file_is_not_running(self):
        r = self.get("/api/log_status")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.json), (200, "application/json; charset=utf-8", self.NOT_RUNNING))

    def test_a_fresh_logging_file_is_running(self):
        self.put()
        r = self.get("/api/log_status")
        self.assertEqual(set(r.json), set(self.NOT_RUNNING))
        self.assertEqual((r.json["running"], r.json["state"], r.json["file"], r.json["samples"]), (True, "logging", "x.jsonl", 40))
        self.assertAlmostEqual(r.json["seconds"], 20, delta=5)

    def test_a_fresh_waiting_file_is_running_without_seconds(self):
        self.put(state="waiting", file=None, samples=0)
        r = self.get("/api/log_status")
        self.assertEqual((r.json["running"], r.json["state"], r.json["file"], r.json["seconds"]), (True, "waiting", None, None))

    def test_a_file_older_than_5_seconds_is_not_running(self):
        self.put(updated=time.time() - 30)
        self.assertEqual(self.get("/api/log_status").json, self.NOT_RUNNING)

    def test_a_damaged_file_is_not_running(self):
        self.write(self.status_file, "{not json")
        self.assertEqual(self.get("/api/log_status").json, self.NOT_RUNNING)

    def test_the_file_is_read_from_the_logs_option_of_the_server(self):
        other = str(self.d / "other_logs")
        self.put()
        ts.CONFIG["logs"] = other
        self.assertEqual(self.get("/api/log_status").json, self.NOT_RUNNING)

    def test_it_needs_no_base_car_and_writes_nothing(self):
        self.assertEqual(self.get("/api/log_status?car=ks_y").status, 200)
        self.assertFalse(os.path.exists(self.logs))
        self.assertEqual(self.get("/api/log_status?tune=nope").status, 400)

    def test_methods_and_paths(self):
        self.assertEqual(self.post("/api/log_status").status, 404)
        self.assertEqual(self.request("DELETE", "/api/log_status").status, 405)
        self.assertEqual(self.get("/api/log_status", host="evil.example").status, 403)


class TestLoggerRoutes(LogCase):
    """POST /api/logger_start and /api/logger_stop: start the logger in the background, ask it to stop. subprocess.Popen is a mock, no process is started."""
    PID = 4321
    ROUTES = ("/api/logger_start", "/api/logger_stop")

    def setUp(self):
        super().setUp()
        self.spawned = []
        self.proc = mock.Mock(pid=self.PID)
        self.popen = self.patch(ts.subprocess, "Popen", mock.Mock(side_effect=self.fake_popen))
        self.patch_list(ts.LOGGER_PROC, [None])
        self.stop_file = logconf.stop_path(self.logs)
        self.console = os.path.join(self.logs, "logger_console.log")

    def fake_popen(self, args, **kw):
        out = kw["stdout"]
        self.spawned.append({"stdout_closed": out.closed, "stop_file": os.path.exists(self.stop_file)})
        return self.proc

    def running(self):
        now = time.time()
        self.write(self.status_file, {"state": "logging", "file": "x.jsonl", "samples": 40, "started": now - 20, "updated": now, "pid": 7})

    def start_on(self, platform, body=None):
        with mock.patch.object(sys, "platform", platform), \
                mock.patch.object(ts.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
                mock.patch.object(ts.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            return self.post("/api/logger_start", body)

    def test_the_logger_route_paths_are_post_routes_without_a_job(self):
        for path in self.ROUTES:
            self.assertIn(path, ts.POST_ROUTES)
            self.assertNotIn(path, ts.GET_ROUTES)
            self.assertNotIn(path, ts.ACCEPTED)
            self.assertNotIn(path, ts.QUERY_ROUTES)

    def test_start_runs_the_logger_with_this_servers_folders_and_answers_the_pid(self):
        r = self.start_on("win32")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.json), (200, "application/json; charset=utf-8", {"started": True, "pid": self.PID}))
        self.popen.assert_called_once()
        args, kw = self.popen.call_args
        self.assertEqual(args, ([sys.executable, "-I", "-B", str(tune.REPO / "tools" / "logger.py"),
                                 "--work", self.work, "--mods", clone_car.expand(self.mods), "--logs", clone_car.expand(self.logs)],))
        self.assertEqual(set(kw), {"cwd", "stdin", "stdout", "stderr", "close_fds", "creationflags"})
        self.assertEqual((kw["cwd"], kw["stdin"], kw["stderr"], kw["close_fds"]),
                         (str(tune.REPO), ts.subprocess.DEVNULL, ts.subprocess.STDOUT, True))

    def test_off_windows_start_is_400_and_starts_nothing(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform):
                r = self.start_on(platform)
                self.assertEqual((r.status, r.headers.get("Content-Type"), r.json),
                                 (400, "application/json; charset=utf-8", {"error": "the logger needs Windows"}))
        self.popen.assert_not_called()
        self.assertFalse(os.path.exists(self.logs))
        self.assertIsNone(ts.LOGGER_PROC[0])

    def test_off_windows_the_refusal_comes_before_the_running_check_and_the_stop_file_stays(self):
        self.running()
        self.write(self.stop_file, "")
        self.assertEqual(self.start_on("linux").status, 400)
        self.assertTrue(os.path.exists(self.stop_file))

    def test_a_logger_started_by_this_server_that_still_lives_is_a_409_without_a_status_file(self):
        self.proc.poll.return_value = None
        self.assertEqual(self.start_on("win32").status, 200)
        self.assertIs(ts.LOGGER_PROC[0], self.proc)
        self.assertFalse(os.path.exists(self.status_file))
        r = self.start_on("win32")
        self.assertEqual((r.status, r.json), (409, {"error": "the logger already runs"}))
        self.popen.assert_called_once()

    def test_a_logger_that_has_exited_may_be_started_again(self):
        self.proc.poll.return_value = None
        self.assertEqual(self.start_on("win32").status, 200)
        self.proc.poll.return_value = 0
        self.assertEqual(self.start_on("win32").status, 200)
        self.assertEqual(self.popen.call_count, 2)

    def test_two_starts_at_the_same_time_start_one_logger(self):
        self.proc.poll.return_value = None
        self.popen.side_effect = lambda args, **kw: (time.sleep(0.3), self.proc)[1]
        start, results = threading.Barrier(2), []

        def send():
            start.wait(5)
            results.append(self.post("/api/logger_start").status)
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(ts.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
                mock.patch.object(ts.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            threads = [threading.Thread(target=send) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
        self.assertEqual(sorted(results), [200, 409])
        self.popen.assert_called_once()

    def test_the_logger_script_is_the_logger_of_the_tools_folder(self):
        self.assertEqual(ts.LOGGER, tune.REPO / "tools" / "logger.py")
        self.assertTrue(ts.LOGGER.is_file())

    def test_start_uses_the_work_mods_and_logs_options_of_the_server(self):
        mods, logs = str(self.d / "m2"), str(self.d / "l2")
        ts.CONFIG.update(mods=mods, logs=logs)
        self.assertEqual(self.start_on("win32").status, 200)
        args = self.popen.call_args[0][0]
        self.assertEqual(args[4:], ["--work", self.work, "--mods", clone_car.expand(mods), "--logs", clone_car.expand(logs)])
        self.assertTrue(os.path.isfile(os.path.join(logs, "logger_console.log")))
        self.assertFalse(os.path.exists(self.logs))

    def test_the_console_output_goes_to_the_log_file_opened_for_appending_and_closed_afterwards(self):
        self.write(self.console, "old line")
        self.assertEqual(self.start_on("win32").status, 200)
        out = self.popen.call_args[1]["stdout"]
        self.assertEqual((out.name, out.mode), (os.path.join(clone_car.expand(self.logs), "logger_console.log"), "ab"))
        self.assertEqual(self.spawned, [{"stdout_closed": False, "stop_file": False}])
        self.assertTrue(out.closed)
        with open(self.console, "rb") as f:
            self.assertEqual(f.read(), b"old line")

    def test_start_creates_the_logs_folder_and_the_log_file(self):
        self.assertFalse(os.path.exists(self.logs))
        self.assertEqual(self.start_on("win32").status, 200)
        self.assertTrue(os.path.isfile(self.console))

    def test_on_windows_the_logger_gets_its_own_process_group_and_no_console_window(self):
        self.assertEqual(self.start_on("win32").status, 200)
        self.assertEqual(self.popen.call_args[1]["creationflags"], 0x200 | 0x08000000)

    def test_elsewhere_there_are_no_creation_flags(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform):
                self.popen.reset_mock()
                with mock.patch.object(sys, "platform", platform):
                    self.assertEqual(ts.spawn_logger(self.work, self.mods, self.logs), self.PID)
                self.assertEqual(self.popen.call_args[1]["creationflags"], 0)

    def test_a_stale_stop_file_is_removed_before_the_logger_starts(self):
        self.write(self.stop_file, "")
        self.assertEqual(self.start_on("win32").status, 200)
        self.assertEqual(self.spawned, [{"stdout_closed": False, "stop_file": False}])
        self.assertFalse(os.path.exists(self.stop_file))

    def test_start_while_the_logger_runs_is_a_409_and_starts_nothing(self):
        for status in ("logging", "waiting"):
            with self.subTest(status):
                self.write(self.status_file, {"state": status, "file": None, "samples": 0, "started": time.time(), "updated": time.time(), "pid": 7})
                r = self.start_on("win32")
                self.assertEqual((r.status, r.json), (409, {"error": "the logger already runs"}))
        self.popen.assert_not_called()
        self.assertFalse(os.path.exists(self.console))

    def test_start_while_the_logger_runs_leaves_a_stop_file_alone(self):
        self.running()
        self.write(self.stop_file, "")
        self.assertEqual(self.start_on("win32").status, 409)
        self.assertTrue(os.path.exists(self.stop_file))

    def test_an_old_or_damaged_status_file_does_not_block_a_start(self):
        for text in (json.dumps({"state": "logging", "file": None, "samples": 0, "started": 1, "updated": time.time() - 30, "pid": 7}), "{not json"):
            with self.subTest(text):
                self.write(self.status_file, text)
                self.assertEqual(self.start_on("win32").status, 200)

    def test_a_failing_spawn_is_a_500_with_the_text(self):
        self.popen.side_effect = OSError("cannot start the logger")
        r = self.start_on("win32")
        self.assertEqual((r.status, r.json), (500, {"error": "cannot start the logger"}))
        self.assertTrue(self.popen.call_args[1]["stdout"].closed)

    def test_an_unexpandable_folder_is_a_500_and_starts_nothing(self):
        ts.CONFIG["mods"] = "%ACE_TEST_NO_SUCH_VAR%/m"
        r = self.start_on("win32")
        self.assertEqual(r.status, 500)
        self.assertIn("cannot expand", r.json["error"])
        self.popen.assert_not_called()

    def test_start_does_not_wait_for_the_logger(self):
        self.assertEqual(self.start_on("win32").status, 200)
        self.assertEqual(self.proc.method_calls, [])

    def test_stop_asks_the_running_logger_to_stop_and_answers(self):
        self.running()
        r = self.post("/api/logger_stop")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.json), (200, "application/json; charset=utf-8", {"stopping": True}))
        self.assertTrue(os.path.isfile(self.stop_file))
        self.assertEqual(os.path.getsize(self.stop_file), 0)
        self.popen.assert_not_called()

    def test_stop_while_the_logger_does_not_run_is_a_409_and_writes_nothing(self):
        for text in (None, json.dumps({"state": "logging", "file": None, "samples": 0, "started": 1, "updated": time.time() - 30, "pid": 7}), "{not json"):
            with self.subTest(text):
                if text is not None:
                    self.write(self.status_file, text)
                r = self.post("/api/logger_stop")
                self.assertEqual((r.status, r.json), (409, {"error": "the logger is not running"}))
                self.assertFalse(os.path.exists(self.stop_file))
        self.popen.assert_not_called()

    def test_stop_reads_the_logs_option_of_the_server(self):
        self.running()
        ts.CONFIG["logs"] = str(self.d / "other_logs")
        self.assertEqual(self.post("/api/logger_stop").status, 409)
        self.assertFalse(os.path.exists(self.stop_file))

    def test_bad_bodies_are_the_usual_400_413_and_415(self):
        self.running()
        for path in self.ROUTES:
            with self.subTest(path):
                self.assertEqual(self.post(path, b"{not json").status, 400)
                self.assertEqual(self.post(path, b"[1]").status, 400)
                self.assertEqual(self.request("POST", path, None, headers={"Content-Length": str(ts.MAX_BODY + 1)}).status, 413)
                r = self.post(path, {}, headers={"Content-Type": "text/plain"})
                self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        self.assertFalse(os.path.exists(self.stop_file))
        self.popen.assert_not_called()

    def test_the_header_rule_of_every_post_route(self):
        self.running()
        for path in self.ROUTES:
            with self.subTest(path):
                r = self.post(path, headers={"X-Tuner": None})
                self.assertEqual((r.status, r.json), (403, {"error": "missing header X-Tuner: 1"}))
                self.assertEqual(self.post(path, headers={"X-Tuner": "0"}).status, 403)
                self.assertEqual(self.post(path, post_headers=False).status, 403)
                r = self.post(path, host="evil.example")
                self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))
        self.assertFalse(os.path.exists(self.stop_file))
        self.popen.assert_not_called()

    def test_methods_and_paths(self):
        for path in self.ROUTES:
            with self.subTest(path):
                self.assertEqual(self.get(path).status, 404)
                for method in ("PUT", "DELETE", "PATCH"):
                    r = self.request(method, path)
                    self.assertEqual((r.status, r.json, r.headers.get("Allow")), (405, {"error": "method not allowed"}, "GET, POST"))
        self.popen.assert_not_called()

    def test_they_need_no_base_car_and_no_idle_job_and_the_dispatcher_still_resolves_the_car_and_the_tune(self):
        self.assertFalse(ts.base_present(self.work, "ks_y"))
        ts.JOB["state"] = "running"
        with ts.STATE_LOCK:
            self.assertEqual(self.start_on("win32", {"car": "ks_y"}).status, 200)
            self.running()
            self.assertEqual(self.post("/api/logger_stop", {"car": "ks_y"}).status, 200)
        self.popen.reset_mock()
        os.remove(self.stop_file)
        os.remove(self.status_file)
        r = self.post("/api/logger_start", {"car": "nope"})
        self.assertEqual(r.status, 400)
        self.assertTrue(r.json["error"].startswith("unknown car"), r.json)
        self.assertEqual(self.post("/api/logger_start", {"tune": "nope"}).status, 400)
        self.popen.assert_not_called()


class TestLogAiCommandRoute(LogCase):
    """GET /api/log_ai_command: the AI command built from the template, the glossary and the rows of the Logging tab."""

    def command(self):
        return logconf.ai_command(logconf.load_channels(), REAL_CATALOGUE, logconf.load_glossary(), logconf.load_ai_template())

    def test_the_answer_is_the_text_of_the_command_and_its_size_in_bytes(self):
        r = self.get("/api/log_ai_command")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control")),
                         (200, "application/json; charset=utf-8", "no-store"))
        self.assertEqual(set(r.json), {"text", "size"})
        self.assertEqual(r.json["text"], self.command())
        self.assertEqual(r.json["size"], len(r.json["text"].encode("utf-8")))
        self.assertGreater(r.json["size"], 20000)

    def test_the_text_holds_the_template_the_glossary_of_every_channel_and_the_rows(self):
        text = self.get("/api/log_ai_command").json["text"]
        self.assertTrue(text.startswith("ROLE\n"))
        for part in ("GLOSSARY OF THE VALUES IN THE LOG", "TUNER ROWS: WHAT CAN BE LOGGED AND WHERE IT COMES FROM",
                     "NOT VISIBLE TO THE GAME (cannot be logged, never ask for them)"):
            self.assertEqual(text.count(part), 1, part)
        for name in logconf.channel_names():
            self.assertIn("- %s [" % name, text)
        self.assertNotIn("{{", text)
        text.encode("ascii")

    def test_it_needs_no_base_car_and_no_idle_job_and_writes_nothing(self):
        ts.JOB["state"] = "running"
        with ts.STATE_LOCK:
            self.assertEqual(self.get("/api/log_ai_command?car=ks_y").status, 200)
        self.assertFalse(os.path.exists(self.logs))
        self.assertFalse(os.path.exists(self.config_file))
        self.assertEqual(self.get("/api/log_ai_command?car=nope").status, 400)

    def test_the_handler_gets_the_resolved_car_and_tune_and_no_query(self):
        seen = []
        with mock.patch.dict(ts.GET_ROUTES, {"/api/log_ai_command": lambda car, tune_id: seen.append((car, tune_id)) or {"text": "", "size": 0}}):
            self.assertEqual(self.get("/api/log_ai_command?tune=draft").status, 200)
        self.assertEqual(seen, [("ks_x", "draft")])
        self.assertNotIn("/api/log_ai_command", ts.QUERY_ROUTES)
        self.assertNotIn("/api/log_ai_command", ts.ACCEPTED)

    def test_a_damaged_glossary_or_template_is_a_500_with_the_text(self):
        for name, error in (("load_glossary", "log glossary: broken"), ("load_ai_template", "AI command template: broken"),
                            ("load_channels", "log channels: broken")):
            with self.subTest(name), mock.patch.object(logconf, name, side_effect=ValueError(error)):
                r = self.get("/api/log_ai_command")
                self.assertEqual((r.status, r.json), (500, {"error": error}))

    def test_methods_and_paths(self):
        self.assertEqual(self.post("/api/log_ai_command").status, 404)
        self.assertEqual(self.request("PUT", "/api/log_ai_command").status, 405)
        self.assertEqual(self.get("/api/log_ai_command", host="evil.example").status, 403)


class TestLogFileRoute(LogCase):
    """GET /api/log_file?file=<name>: the text of one session file of the logs folder, up to 1 MB."""

    def put(self, name, data):
        path = os.path.join(self.logs, name)
        os.makedirs(self.logs, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def fetch(self, name):
        return self.get("/api/log_file?file=" + urllib.parse.quote(name, safe=""))

    def test_the_answer_is_the_name_the_size_in_bytes_and_the_utf_8_text(self):
        text = '{"type":"header","car":"Café X"}\n{"type":"end","duration_s":1,"samples":0}\n'
        self.put("a.jsonl", text)
        r = self.fetch("a.jsonl")
        self.assertEqual((r.status, r.headers.get("Content-Type")), (200, "application/json; charset=utf-8"))
        self.assertEqual(r.json, {"file": "a.jsonl", "size": len(text.encode("utf-8")), "text": text})
        self.assertGreater(r.json["size"], len(text))

    def test_a_name_with_spaces_and_an_apostrophe_is_url_decoded(self):
        self.put("my file's 1.jsonl", "{}\n")
        r = self.fetch("my file's 1.jsonl")
        self.assertEqual((r.status, r.json["file"], r.json["text"]), (200, "my file's 1.jsonl", "{}\n"))

    def test_the_text_keeps_its_line_ends(self):
        self.put("crlf.jsonl", b"{}\r\n{}\n")
        self.assertEqual(self.fetch("crlf.jsonl").json["text"], "{}\r\n{}\n")

    def test_a_bad_name_is_400_and_reads_nothing(self):
        self.put("a.jsonl", "{}\n")
        self.put("a.txt", "{}\n")
        for name in ("..\\a.jsonl", "../a.jsonl", "..", "a/b.jsonl", "sub\\a.jsonl", os.path.join(self.logs, "a.jsonl"), "/etc/a.jsonl",
                     "C:a.jsonl", "a.jsonl:stream", "a.txt", "a", "a.jsonl.txt", ".jsonl.exe", " "):
            with self.subTest(name), mock.patch.object(ts, "open", create=True, side_effect=AssertionError("a file was opened")):
                r = self.fetch(name)
                self.assertEqual(r.status, 400, r.data)
                self.assertIn("error", r.json)

    def test_a_missing_file_parameter_is_400(self):
        for path in ("/api/log_file", "/api/log_file?file=", "/api/log_file?other=a.jsonl"):
            with self.subTest(path):
                self.assertEqual((self.get(path).status, self.get(path).json), (400, {"error": "need file (text)"}))

    def test_a_symbolic_link_is_404_and_its_target_is_not_read(self):
        outside = os.path.join(str(self.d), "outside.txt")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("secret\n")
        inside = self.put("real.jsonl", "{}\n")
        symlink_or_skip(self, outside, os.path.join(self.logs, "link.jsonl"))
        symlink_or_skip(self, inside, os.path.join(self.logs, "inner.jsonl"))
        for name in ("link.jsonl", "inner.jsonl"):
            with self.subTest(name):
                r = self.fetch(name)
                self.assertEqual((r.status, r.json), (404, {"error": "no session file %s" % name}))
                self.assertNotIn(b"secret", r.data)
        self.assertEqual(self.fetch("real.jsonl").status, 200)

    def test_a_missing_file_is_404_and_so_is_a_folder_with_such_a_name(self):
        r = self.fetch("nope.jsonl")
        self.assertEqual((r.status, r.json), (404, {"error": "no session file nope.jsonl"}))
        os.makedirs(os.path.join(self.logs, "dir.jsonl"))
        self.assertEqual(self.fetch("dir.jsonl").status, 404)

    def test_a_file_of_exactly_1_mb_is_sent_and_a_larger_one_is_413_without_being_read(self):
        self.put("edge.jsonl", b"x" * 1048576)
        r = self.fetch("edge.jsonl")
        self.assertEqual((r.status, r.json["size"], len(r.json["text"])), (200, 1048576, 1048576))
        self.put("big.jsonl", b"x" * 1048577)
        with mock.patch.object(ts, "open", create=True, side_effect=AssertionError("the file was opened")):
            r = self.fetch("big.jsonl")
        self.assertEqual((r.status, r.json), (413, {"error": "the file is larger than 1 MB: too large to copy as text"}))

    def test_the_folder_is_the_logs_option_of_the_server(self):
        other = str(self.d / "other_logs")
        self.put("here.jsonl", "{}\n")
        os.makedirs(other)
        with open(os.path.join(other, "there.jsonl"), "wb") as f:
            f.write(b"[]\n")
        ts.CONFIG["logs"] = other
        self.assertEqual(self.fetch("here.jsonl").status, 404)
        self.assertEqual(self.fetch("there.jsonl").json["text"], "[]\n")

    def test_the_raw_query_is_the_third_argument_and_the_file_comes_from_it(self):
        seen = []

        def spy(car, tune_id, query):
            seen.append((car, tune_id, query))
            return {}
        with mock.patch.dict(ts.GET_ROUTES, {"/api/log_file": spy}):
            self.assertEqual(self.get("/api/log_file?file=a.jsonl&car=ks_x&tune=draft").status, 200)
        self.assertEqual(seen, [("ks_x", "draft", "file=a.jsonl&car=ks_x&tune=draft")])
        self.assertIn("/api/log_file", ts.QUERY_ROUTES)
        self.put("a.jsonl", "{}\n")
        self.assertEqual(self.get("/api/log_file?file=a.jsonl&car=ks_y&tune=draft").json["file"], "a.jsonl")

    def test_it_needs_no_base_car_and_no_idle_job_and_writes_nothing(self):
        self.put("a.jsonl", "{}\n")
        before = sorted(os.listdir(self.logs))
        ts.JOB["state"] = "running"
        with ts.STATE_LOCK:
            self.assertEqual(self.get("/api/log_file?file=a.jsonl&car=ks_y").status, 200)
        self.assertEqual(sorted(os.listdir(self.logs)), before)
        self.assertEqual(self.get("/api/log_file?file=a.jsonl&car=nope").status, 400)

    def test_methods_and_paths(self):
        self.put("a.jsonl", "{}\n")
        self.assertEqual(self.post("/api/log_file", {"file": "a.jsonl"}).status, 404)
        self.assertEqual(self.request("DELETE", "/api/log_file?file=a.jsonl").status, 405)
        self.assertEqual(self.get("/api/log_file?file=a.jsonl", host="evil.example").status, 403)

    def test_a_client_on_the_home_network_may_read_the_file(self):
        self.assertNotIn("/api/log_file", ts.LOCAL_ROUTES)


class LanHandler(ts.Handler):
    """A Handler whose client always comes from a private address of the home network, not from the PC itself."""
    @property
    def client_address(self):
        return ("192.168.1.20", 4711)

    @client_address.setter
    def client_address(self, value):
        pass


class CopyCase(LogCase):
    """LogCase with subprocess.run replaced by a recorder (the clipboard and PowerShell are never touched) and helpers for a session file."""
    NO_WINDOW = 0x08000000

    def setUp(self):
        super().setUp()
        self.completed = mock.Mock(returncode=0, stdout="", stderr="")
        self.run = self.patch(ts.subprocess, "run", mock.Mock(return_value=self.completed))

    def put(self, name="a.jsonl", data="{}\n"):
        path = os.path.join(self.logs, name)
        os.makedirs(self.logs, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        return os.path.abspath(path)

    def copy_on(self, platform, name="a.jsonl", body=None, **kw):
        with mock.patch.object(sys, "platform", platform), mock.patch.object(ts.subprocess, "CREATE_NO_WINDOW", self.NO_WINDOW, create=True):
            return self.post("/api/log_copy", {"file": name} if body is None else body, **kw)


class TestLogCopyRoute(CopyCase):
    """POST /api/log_copy: puts a session file on the clipboard of the PC with PowerShell (subprocess.run is a recorder)."""

    def test_the_powershell_call_has_exactly_the_documented_arguments(self):
        path = self.put()
        r = self.copy_on("win32")
        self.assertEqual((r.status, r.headers.get("Content-Type"), r.json), (200, "application/json; charset=utf-8", {"copied": True, "file": "a.jsonl", "how": "file"}))
        self.run.assert_called_once()
        args, kw = self.run.call_args
        self.assertEqual(args, (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Set-Clipboard -LiteralPath $env:TUNER_CLIP_FILE"],))
        self.assertEqual(kw, {"capture_output": True, "text": True, "timeout": 15, "creationflags": self.NO_WINDOW,
                              "env": dict(os.environ, TUNER_CLIP_FILE=path)})
        self.assertEqual(ts.CLIPBOARD_TIMEOUT, 15)

    def test_an_apostrophe_in_the_name_or_the_folder_reaches_powershell_through_the_environment(self):
        path = self.put("it's.jsonl")
        self.assertEqual(self.copy_on("win32", "it's.jsonl").status, 200)
        self.assertEqual(self.run.call_args[0][0][4], "Set-Clipboard -LiteralPath $env:TUNER_CLIP_FILE")
        self.assertEqual(self.run.call_args[1]["env"]["TUNER_CLIP_FILE"], path)
        other = str(self.d / "o'brien")
        ts.CONFIG["logs"] = other
        self.write(os.path.join(other, "b.jsonl"), "{}\n")
        self.assertEqual(self.copy_on("win32", "b.jsonl").status, 200)
        self.assertEqual(self.run.call_args[0][0][4], "Set-Clipboard -LiteralPath $env:TUNER_CLIP_FILE")
        self.assertIn("o'brien", self.run.call_args[1]["env"]["TUNER_CLIP_FILE"])

    def test_the_path_is_the_absolute_path_of_the_file_in_the_logs_folder_from_session_file_only(self):
        path = self.put("c.jsonl")
        with mock.patch.object(logconf, "session_file", wraps=logconf.session_file) as spy:
            self.assertEqual(self.copy_on("win32", "c.jsonl").status, 200)
        spy.assert_called_once_with(clone_car.expand(self.logs), "c.jsonl")
        self.assertTrue(os.path.isabs(path))
        self.assertEqual(self.run.call_args[1]["env"]["TUNER_CLIP_FILE"], path)

    def test_no_part_of_the_path_is_in_the_command_whatever_characters_it_has(self):
        names = ["it's.jsonl", "a`b.jsonl", "$env_x $(y).jsonl", "a;b.jsonl", "O\u2019Brien \u00e9\u4e2d.jsonl", "x'; calc ; '.jsonl",
                 "\u2018q\u201a.jsonl", "a&b^c.jsonl" if os.name == "nt" else "a&b|c.jsonl"]
        folder = str(self.d / "o'b`r$;\u00e9\u2019")
        ts.CONFIG["logs"] = folder
        for name in names:
            with self.subTest(name):
                self.write(os.path.join(folder, name), "{}\n")
                self.assertEqual(self.copy_on("win32", name).status, 200)
                args, kw = self.run.call_args
                self.assertEqual(args[0], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Set-Clipboard -LiteralPath $env:TUNER_CLIP_FILE"])
                command = args[0][4]
                for part in (name, os.path.splitext(name)[0], folder, os.path.basename(folder), "'", "`;"):
                    self.assertNotIn(part, command)
                self.assertEqual(kw["env"]["TUNER_CLIP_FILE"], os.path.abspath(os.path.join(folder, name)))

    def test_the_environment_of_the_call_keeps_the_environment_of_the_server(self):
        path = self.put()
        with mock.patch.dict(os.environ, {"TUNER_TEST_KEEP": "kept"}):
            ts.copy_file_to_clipboard(path)
        env = self.run.call_args[1]["env"]
        self.assertEqual((env["TUNER_TEST_KEEP"], env["TUNER_CLIP_FILE"]), ("kept", path))
        self.assertNotIn("TUNER_CLIP_FILE", os.environ)

    def test_a_path_that_is_a_powershell_attack_string_is_only_data(self):
        path = "C:\\Users\\O\u2019Brien\\x'; Remove-Item -Recurse C:\\ ; `$(calc)\\a.jsonl"
        ts.copy_file_to_clipboard(path)
        command = self.run.call_args[0][0][4]
        self.assertEqual(command, "Set-Clipboard -LiteralPath $env:TUNER_CLIP_FILE")
        self.assertEqual(self.run.call_args[1]["env"]["TUNER_CLIP_FILE"], path)

    def test_a_symbolic_link_is_404_and_nothing_runs(self):
        outside = os.path.join(str(self.d), "outside.txt")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("secret\n")
        self.put()
        symlink_or_skip(self, outside, os.path.join(self.logs, "link.jsonl"))
        r = self.copy_on("win32", "link.jsonl")
        self.assertEqual((r.status, r.json), (404, {"error": "no session file link.jsonl"}))
        self.run.assert_not_called()
        self.assertEqual(self.copy_on("win32").status, 200)

    def test_the_powershell_call_is_one_small_function_and_no_shell_is_used(self):
        path = self.put()
        ts.copy_file_to_clipboard(path)
        self.run.assert_called_once()
        self.assertNotIn("shell", self.run.call_args[1])
        self.assertIsInstance(self.run.call_args[0][0], list)

    def test_off_windows_the_creation_flags_are_zero(self):
        self.put()
        with mock.patch.object(sys, "platform", "linux"):
            ts.copy_file_to_clipboard(os.path.join(self.logs, "a.jsonl"))
        self.assertEqual(self.run.call_args[1]["creationflags"], 0)

    def test_a_bad_name_is_400_and_a_missing_file_404_and_nothing_runs(self):
        self.put()
        for name, status in (("..\\a.jsonl", 400), ("a/b.jsonl", 400), ("C:a.jsonl", 400), ("a.txt", 400), ("", 400), (None, 400), (5, 400),
                             ("nope.jsonl", 404)):
            with self.subTest(name):
                r = self.copy_on("win32", name)
                self.assertEqual(r.status, status, r.data)
                self.assertIn("error", r.json)
        self.assertEqual(self.copy_on("win32", body={}).status, 400)
        self.assertEqual(self.copy_on("win32", body={"file": ["a.jsonl"]}).status, 400)
        self.assertEqual(self.copy_on("win32", "nope.jsonl").json, {"error": "no session file nope.jsonl"})
        self.run.assert_not_called()

    def test_off_windows_it_is_400_and_nothing_runs(self):
        self.put()
        r = self.copy_on("linux")
        self.assertEqual((r.status, r.json), (400, {"error": "copying a file to the clipboard needs Windows"}))
        self.run.assert_not_called()

    def test_a_bad_name_is_refused_before_the_platform_check(self):
        self.assertEqual(self.copy_on("linux", "..\\x.jsonl").status, 400)
        self.assertEqual(self.copy_on("linux", "nope.jsonl").status, 404)

    def test_a_non_zero_return_code_is_a_500_with_the_error_text_of_powershell(self):
        self.put()
        self.completed.returncode, self.completed.stderr = 1, "Set-Clipboard : access denied\r\n"
        r = self.copy_on("win32")
        self.assertEqual((r.status, r.json), (500, {"error": "Set-Clipboard : access denied"}))

    def test_a_non_zero_return_code_without_text_says_the_exit_code(self):
        self.put()
        self.completed.returncode, self.completed.stderr = 3, ""
        r = self.copy_on("win32")
        self.assertEqual((r.status, r.json), (500, {"error": "PowerShell failed with exit code 3"}))
        self.completed.stderr = None
        self.assertEqual(self.copy_on("win32").json, {"error": "PowerShell failed with exit code 3"})

    def test_a_timeout_or_an_os_error_is_a_500_with_the_text_of_the_exception(self):
        self.put()
        self.run.side_effect = subprocess.TimeoutExpired(["powershell.exe"], 15)
        r = self.copy_on("win32")
        self.assertEqual((r.status, r.json), (500, {"error": str(subprocess.TimeoutExpired(["powershell.exe"], 15))}))
        self.assertIn("timed out after 15", r.json["error"])
        self.run.side_effect = FileNotFoundError("powershell.exe not found")
        r = self.copy_on("win32")
        self.assertEqual((r.status, r.json), (500, {"error": "powershell.exe not found"}))
        self.run.side_effect = PermissionError("access is denied")
        self.assertEqual(self.copy_on("win32").json, {"error": "access is denied"})

    def test_it_needs_no_base_car_and_no_idle_job_and_writes_nothing(self):
        self.put()
        before = sorted(os.listdir(self.logs))
        ts.JOB["state"] = "running"
        with ts.STATE_LOCK:
            self.assertEqual(self.copy_on("win32", body={"file": "a.jsonl", "car": "ks_y"}).status, 200)
        self.assertEqual(sorted(os.listdir(self.logs)), before)
        self.assertEqual(self.copy_on("win32", body={"file": "a.jsonl", "car": "nope"}).status, 400)

    def test_it_is_a_post_route_with_the_usual_checks(self):
        self.put()
        self.assertEqual(self.get("/api/log_copy").status, 404)
        self.assertEqual(self.copy_on("win32", post_headers=False).status, 403)
        self.assertEqual(self.copy_on("win32", host="evil.example").status, 403)
        self.assertEqual(self.request("PUT", "/api/log_copy").status, 405)
        self.assertNotIn("/api/log_copy", ts.ACCEPTED)
        self.assertNotIn("/api/log_copy", ts.QUERY_ROUTES)
        self.run.assert_not_called()

    def test_a_client_on_this_pc_may_call_it_and_the_check_is_the_loopback_test(self):
        for address in ("127.0.0.1", "127.0.0.2", "::1"):
            with self.subTest(address):
                self.assertTrue(ts.loopback_ip(address))
        for address in ("192.168.1.20", "10.0.0.1", "8.8.8.8", "::2", "fe80::1", "", "localhost", "x"):
            with self.subTest(address):
                self.assertFalse(ts.loopback_ip(address))


class TestLogCopyFromTheNetwork(CopyCase):
    """The same route called by a client of the home network (192.168.1.20): refused, and nothing runs."""
    handler = LanHandler
    MESSAGE = {"error": "the file can only be copied on the PC where the tuner runs"}

    def test_a_client_that_is_not_loopback_is_403_and_nothing_runs(self):
        self.put()
        r = self.copy_on("win32")
        self.assertEqual((r.status, r.json), (403, self.MESSAGE))
        self.run.assert_not_called()

    def test_the_refusal_comes_before_the_name_and_the_platform_checks(self):
        for platform, name in (("win32", "nope.jsonl"), ("win32", "..\\x.jsonl"), ("linux", "a.jsonl")):
            with self.subTest((platform, name)):
                self.assertEqual(self.copy_on(platform, name).json, self.MESSAGE)
        self.assertEqual(self.copy_on("win32", body={"file": "a" * 1000}).json, self.MESSAGE)
        self.run.assert_not_called()

    def test_the_other_checks_of_the_server_still_come_first(self):
        self.put()
        self.assertEqual(self.copy_on("win32", host="evil.example").status, 403)
        self.assertEqual(self.copy_on("win32", host="evil.example").json, {"error": forbidden_host(self.port)})
        self.assertEqual(self.copy_on("win32", post_headers=False).json, {"error": "missing header X-Tuner: 1"})

    def test_the_other_routes_still_answer_such_a_client(self):
        self.put()
        self.assertEqual(self.get("/api/log_file?file=a.jsonl").status, 200)
        self.assertEqual(self.get("/api/log_ai_command").status, 200)
        self.assertEqual(self.get("/api/log_sessions").status, 200)
        self.assertEqual(self.post("/api/log_config_set", {"ticked": [], "rate_hz": 30}).status, 200)


class TestLogsDir(Env):
    def test_the_option_value_is_expanded_and_made_absolute(self):
        ts.CONFIG["logs"] = os.path.join("rel", "logs")
        self.assertEqual(ts.logs_dir(), os.path.abspath(os.path.join("rel", "logs")))
        ts.CONFIG["logs"] = "%ACE_TEST_LOGS_VAR%/l" if os.name == "nt" else "$ACE_TEST_LOGS_VAR/l"
        with mock.patch.dict(os.environ, {"ACE_TEST_LOGS_VAR": "C:\\scratch" if os.name == "nt" else "/scratch"}):
            self.assertEqual(ts.logs_dir(), os.path.abspath(os.path.expandvars(ts.CONFIG["logs"])))

    def test_without_the_option_it_is_the_logs_folder_of_the_repository(self):
        ts.CONFIG["logs"] = None
        self.assertEqual(ts.logs_dir(), os.path.abspath(logconf.default_logs_dir()))
        self.assertEqual(os.path.basename(ts.logs_dir()), "logs")

    def test_an_unexpandable_folder_is_an_error(self):
        ts.CONFIG["logs"] = "%ACE_TEST_NO_SUCH_VAR%/l"
        with self.assertRaisesRegex(ValueError, "cannot expand the logs directory"):
            ts.logs_dir()


# -------------------------------------------------------------------------------------------------- tyre library and garage
def pack_tyres(dst, names):
    """A game package with the shared tyre files names (below content\\cars\\common_phsx\\tyres) as files with placeholder bytes."""
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


class TyreCase(TuneCase):
    """TuneCase with the tyre settings in the catalogue, three shared tyre files and one preset (stock sets a+b and s+s) in ks_x; the game
    package never exists (self.game), so only the extracted tyre files count."""

    def setUp(self):
        super().setUp()
        self.cat = mini_catalogue(limiter(), aids_off(), suffix(), boost(), tyre_dy("front"), tyre_dy("rear"))
        self.game = os.path.join(self.work, "no_game.kspkg")
        self.patch_dict(ts.CONFIG, {"game": self.game})
        self.fc.add_shared("tyres/road/a.tyre", {"modelData": {"Dy0": 1.25}})
        self.fc.add_shared("tyres/road/b.tyre", {"modelData": {"Dy0": 1.0}})
        self.fc.add_shared("tyres/slick/s.tyre", {"modelData": {"Dy0": 1.5}})
        self.fc.add("presets/p.compatibletyres", {"physic_compounds": [
            {"front_tyre_data_path": ROAD_A, "rear_tyre_data_paths": ROAD_B},
            {"front_tyre_data_path": SLICK_S, "rear_tyre_data_paths": [SLICK_S]}]})

    def make_package(self, names):
        """A game package with these tyre files (below tyres\\) that the server reads as the game of its config."""
        pkg = str(self.d / "content.kspkg")
        pack_tyres(pkg, names)
        self.patch_dict(ts.CONFIG, {"game": pkg})
        return pkg

    def make_tyre(self, name="Soft", source=ROAD_A):
        return tune.create_tyre(self.work, name, source, game=self.game)["id"]

    def use(self, tyre_id="soft", tune_id=None, version=None):
        """Save a tyre choice with the library tyre as the front tyre in a state."""
        tune.set_tyres(self.work, "ks_x", {"sets": [{"front": "own:" + tyre_id, "rear": "game:" + ROAD_B}], "split": False},
                       tune_id, version, game=self.game)

    def library_bytes(self):
        folder, out = os.path.join(self.work, "tyres"), {}
        for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            with open(os.path.join(folder, n), "rb") as f:
                out[n] = f.read()
        return out


class TestOldTyreValuesRoutes(TyreCase):
    """The old Tyres section: a new value is refused with the pointer to the Tyre Creator, a saved one can still be removed, and its rows
    carry the hint "ui": "hidden" for the page."""

    REFUSED = "tyre values are edited in the Tyre Creator: choose or create a tyre there"

    def test_set_of_a_tyre_setting_is_400_for_the_default_tune_a_modded_car_and_a_version_and_writes_nothing(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        for extra in ({}, {"tune": "ax01"}, {"tune": "draft"}, {"tune": "ax01", "version": vid}):
            for setting_id in ("tyre_dy_front", "tyre_dy_rear"):
                with self.subTest(setting_id, **extra):
                    r = self.post("/api/set", dict(extra, id=setting_id, value="1.4"))
                    self.assertEqual((r.status, r.json), (400, {"error": self.REFUSED}))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid, "ax01"), {})
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", tune.DRAFT)))

    def test_set_of_a_setting_of_the_car_still_works(self):
        r = self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.assertEqual((r.status, r.json["row"]["value"]), (200, 8000))

    def test_unset_of_a_saved_old_value_removes_it_and_answers_the_row(self):
        self.make_tune(None, {"tyre_dy_front": 1.4, "tyre_dy_rear": 1.25, "limiter": 7500})
        r = self.post("/api/unset", {"id": "tyre_dy_front"})
        self.assertEqual((r.status, r.json["row"]["id"]), (200, "tyre_dy_front"))
        self.assertEqual(self.tune_state(), {"tyre_dy_rear": 1.25, "limiter": 7500})
        self.assertEqual(self.post("/api/unset", {"id": "tyre_dy_front"}).status, 200)
        self.assertEqual(self.tune_state(), {"tyre_dy_rear": 1.25, "limiter": 7500})

    def test_a_saved_old_value_of_a_version_can_be_removed(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        tune.save_version_state(self.work, "ks_x", {"tyre_dy_rear": 1.25}, vid, "ax01")
        self.assertEqual(self.post("/api/unset", {"id": "tyre_dy_rear", "tune": "ax01", "version": vid}).status, 200)
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid, "ax01"), {})

    def test_the_row_of_a_tyre_setting_of_the_real_catalogue_carries_the_hint_hidden(self):
        setting = next(s for s in tune.read_catalogue(tune.CATALOGUE)["settings"] if s["id"] == "tyre_grip_lateral_front")
        row = {k: setting.get(k) for k in ("id", "group", "label", "kind", "type", "unit", "description", "verified")}
        row.update(default=1.2, value=1.4, changed=True, absent=False, copies_differ=False)
        out = ts.row_json(row, setting)
        self.assertEqual((out["ui"], out["group"], out["value"], out["changed"]), ("hidden", "Tyres", 1.4, True))


class TestTyreRoutesRebuilt(TyreCase):
    """The tyre routes and the routes of the tyre choice answer for real: no 501, the same checks and the job lock as the rest."""

    ROUTES_GET = ("/api/tyre_index", "/api/tyres", "/api/tyre?id=soft", "/api/garage")
    ROUTES_POST = (("/api/tyre_new", {"name": "Other", "source": ROAD_A}), ("/api/tyre_rename", {"id": "soft", "name": "Hard"}),
                   ("/api/tyre_source", {"id": "soft", "source": SLICK_S}), ("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": 1.5}),
                   ("/api/tyre_unset", {"id": "soft", "setting": "tyre_dy"}), ("/api/tyre_reset", {"id": "soft"}),
                   ("/api/tyre_delete", {"id": "soft"}), ("/api/garage_set", {"choice": SETS_CHOICE}), ("/api/garage_reset", {}))

    def test_no_route_answers_501_and_the_text_being_rebuilt_is_gone(self):
        self.make_tyre("Soft")
        self.assertNotIn("being rebuilt", inspect.getsource(ts))
        self.assertNotIn("not_available", dir(ts))
        for path in self.ROUTES_GET:
            with self.subTest(path):
                self.assertEqual(self.get(path).status, 200)
        for path, body in self.ROUTES_POST:
            with self.subTest(path):
                self.assertNotEqual(self.post(path, body).status, 501)
                if not tune.tyre_exists(self.work, "soft"):
                    self.make_tyre("Soft")

    def test_every_route_is_registered_and_the_raw_query_goes_to_the_tyre_route_only(self):
        for path in ("/api/tyre_index", "/api/tyres", "/api/tyre", "/api/garage"):
            self.assertIn(path, ts.GET_ROUTES)
        for path, _ in self.ROUTES_POST:
            self.assertIn(path, ts.POST_ROUTES)
        self.assertEqual(ts.QUERY_ROUTES, ("/api/tyre", "/api/log_file"))
        self.assertEqual(self.post("/api/tyre_index", {}).status, 404)
        self.assertEqual(self.get("/api/tyre_new").status, 404)

    def test_the_routes_check_the_host_the_headers_and_the_methods(self):
        r = self.post("/api/tyre_new", self.ROUTES_POST[0][1], headers={"X-Tuner": None})
        self.assertEqual((r.status, r.json), (403, {"error": "missing header X-Tuner: 1"}))
        r = self.post("/api/garage_set", self.ROUTES_POST[7][1], headers={"Content-Type": "text/plain"})
        self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        r = self.post("/api/garage_reset", {}, host="evil.example")
        self.assertEqual((r.status, r.json), (403, {"error": forbidden_host(self.port)}))
        for path in self.ROUTES_GET:
            self.assertEqual(self.get(path, host="evil.example").status, 403, path)
        for method in ("PUT", "DELETE", "PATCH"):
            for path in ("/api/tyre_index", "/api/tyre_new", "/api/garage"):
                r = self.request(method, path)
                self.assertEqual((r.status, r.headers.get("Allow")), (405, "GET, POST"), (method, path))
        big = self.post("/api/garage_set", {"choice": {"sets": [], "pad": "x" * 70000}})
        self.assertEqual(big.status, 413)

    def test_the_routes_are_refused_while_a_job_runs_and_change_nothing(self):
        self.make_tyre("Soft")
        self.make_tune("ax01", {"name_suffix": "_A"})
        before = self.library_bytes()
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        self.entered.wait(5)
        for path, body in self.ROUTES_POST:
            with self.subTest(path):
                r = self.post(path, dict(body, tune="ax01"))
                self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        for path in self.ROUTES_GET:
            with self.subTest(path):
                self.assertEqual(self.get(path).status, 200)
        self.assertEqual(self.library_bytes(), before)
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})
        self.finish_held_job()
        self.assertEqual(self.post("/api/tyre_reset", {"id": "soft"}).status, 200)

    def test_an_unknown_car_or_modded_car_is_400(self):
        for path in ("/api/tyre_index?car=nope", "/api/tyres?car=nope", "/api/tyre?id=soft&car=nope", "/api/garage?car=nope"):
            with self.subTest(path):
                r = self.get(path)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith("unknown car"), r.json)
        self.assertEqual(self.get("/api/tyres?tune=nope").json, {"error": "unknown modded car nope of ks_x"})
        r = self.post("/api/tyre_new", {"tune": "nope", "name": "Other", "source": SLICK_S})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))


class TestTyreIndexRoute(TyreCase):
    def test_without_the_package_the_extracted_files_are_listed(self):
        r = self.get("/api/tyre_index")
        self.assertEqual(r.status, 200)
        self.assertEqual(set(r.json), {"tyres", "types", "package"})
        self.assertFalse(r.json["package"])
        self.assertEqual([t["path"] for t in r.json["tyres"]], [ROAD_A, ROAD_B, SLICK_S])
        self.assertEqual(r.json["tyres"][0], {"path": ROAD_A, "file": "a", "type": "road", "type_label": "Road", "label": "Road a",
                                              "width": None, "aspect": None, "rim": None})
        self.assertEqual(r.json["types"], [{"type": "road", "label": "Road", "count": 2},
                                           {"type": "slick", "label": "slick", "count": 1}])

    def test_with_the_package_the_types_follow_the_order_of_tyre_sets_and_unknown_folders_come_last(self):
        self.make_package(["zzz\\zzz_1.tyre", "supercar\\supercar_265_30_19.tyre", "road\\road_235_35_19.tyre", "road\\road_195_65_15.tyre",
                           "racing_wet\\wet_200_60_15.tyre", "road\\readme.tyre"])
        r = self.get("/api/tyre_index")
        self.assertTrue(r.json["package"])
        self.assertEqual(r.json["types"], [{"type": "road", "label": "Road", "count": 3}, {"type": "supercar", "label": "Supercar", "count": 1},
                                           {"type": "racing_wet", "label": "Racing wet", "count": 1}, {"type": "zzz", "label": "zzz", "count": 1}])
        self.assertEqual([t["type"] for t in r.json["tyres"]], ["road", "road", "road", "supercar", "racing_wet", "zzz"])
        sized = {t["file"]: t for t in r.json["tyres"]}
        self.assertEqual((sized["road_235_35_19"]["width"], sized["road_235_35_19"]["aspect"], sized["road_235_35_19"]["rim"]), (235, 35, 19))
        self.assertEqual(sized["road_235_35_19"]["label"], "Road 235/35 R19")
        self.assertEqual(sized["road_235_35_19"]["type_label"], "Road")
        self.assertEqual((sized["readme"]["width"], sized["readme"]["aspect"], sized["readme"]["rim"]), (None, None, None))
        self.assertEqual(sum(t["count"] for t in r.json["types"]), len(r.json["tyres"]))

    def test_the_index_is_read_from_the_game_of_the_config_and_needs_no_base_car(self):
        self.make_package(["road\\road_235_35_19.tyre"])
        self.assertFalse(ts.base_present(self.work, "ks_y"))
        self.assertEqual([t["file"] for t in self.get("/api/tyre_index?car=ks_y").json["tyres"]], ["road_235_35_19"])
        self.assertEqual(self.get("/api/tyre_index?tune=draft").json, self.get("/api/tyre_index").json)

    def test_no_package_and_no_extracted_car_is_an_empty_list(self):
        shutil.rmtree(os.path.join(self.work, "ks_x"))
        self.assertEqual(self.get("/api/tyre_index").json, {"tyres": [], "types": [], "package": False})

    def test_the_game_read_goes_through_the_cached_index_of_tune(self):
        pkg = self.make_package(["road\\road_235_35_19.tyre"])
        self.get("/api/tyre_index")
        self.assertTrue(os.path.isfile(os.path.join(self.work, "tyre_index.json")))
        seen = []
        self.patch(tune, "available_tyres", lambda work, game=None: seen.append((work, game)) or [])
        self.get("/api/tyre_index")
        self.assertEqual(seen, [(self.work, pkg)])


class TestTyreLibraryRoutes(TyreCase):
    def test_tyres_lists_the_library_with_the_source_label_the_changes_and_the_users(self):
        self.make_tyre("Soft")
        self.make_tyre("Hard", SLICK_S)
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.5", self.cat)
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        self.use("soft", "ax01", vid)
        self.use("soft", "draft")
        r = self.get("/api/tyres")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json, {"tyres": [
            {"id": "hard", "name": "Hard", "short": "HA", "source": SLICK_S, "source_label": "slick s", "changed": 0, "error": None, "users": []},
            {"id": "soft", "name": "Soft", "short": "SO", "source": ROAD_A, "source_label": "Road a", "changed": 1, "error": None,
             "users": ["ks_x / ax01 / v01", "ks_x (draft)"]}]})

    def test_a_damaged_file_and_an_old_front_rear_tyre_are_listed_with_their_error_only(self):
        self.write(os.path.join(self.work, "tyres", "old.json"), {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        self.write(os.path.join(self.work, "tyres", "bad.json"), [])
        r = self.get("/api/tyres")
        self.assertEqual([(t["id"], t["name"], t["users"]) for t in r.json["tyres"]], [("bad", None, []), ("old", None, [])])
        self.assertTrue(all(t["error"] for t in r.json["tyres"]))
        self.assertIn("old front/rear form", r.json["tyres"][1]["error"])
        self.assertEqual(set(r.json["tyres"][0]), {"id", "name", "short", "source", "source_label", "changed", "error", "users"})

    def test_an_empty_library_is_an_empty_list(self):
        self.assertEqual(self.get("/api/tyres").json, {"tyres": []})

    def test_tyre_answers_the_name_the_short_the_source_and_the_rows_without_an_axle(self):
        self.make_tyre("Soft")
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.75", self.cat)
        r = self.get("/api/tyre?id=soft")
        self.assertEqual(r.status, 200)
        self.assertEqual({k: v for k, v in r.json.items() if k != "rows"},
                         {"id": "soft", "name": "Soft", "short": "SO", "source": ROAD_A, "source_label": "Road a", "groups": [],
                          "types": [{"type": "road", "label": "Road", "total": 2}, {"type": "slick", "label": "slick", "total": 1}]})
        self.assertEqual([row["id"] for row in r.json["rows"]], ["tyre_dy"])
        row = r.json["rows"][0]
        self.assertEqual((row["default"], row["value"], row["changed"], row["applicable"], row["reason"]), (1.25, 1.75, True, True, None))
        self.assertEqual((row["min"], row["max"], row["unit"], row["group"]), (0.5, 2.5, "mu", "Tyres"))
        self.assertNotIn("axle", row)
        self.assertEqual(set(row), {"id", "label", "group", "unit", "type", "kind", "description", "verified", "min", "max", "default", "value",
                                    "changed", "applicable", "reason", "type_ranges"})
        self.assertEqual(row["type_ranges"], {"road": {"low": 1.0, "high": 1.25, "count": 2}, "slick": {"low": 1.5, "high": 1.5, "count": 1}})

    def with_tyre_groups(self):
        flag = dict(mini_setting("tyre_flag", kind="flag", type="bool", group="Other", targets=[("@tyre", "modelData.flag")]), absent=False)
        absent = dict(mini_setting("tyre_brake", group="Other", targets=[("@tyre", "modelData.brakeDXMod")]), absent=0)
        settings = [dict(s, tyre_group="Grip") if s["id"] == "tyre_dy_front" else s for s in self.cat["settings"]]
        self.cat = dict(self.cat, settings=settings, tyre_groups=[{"name": "Grip", "description": "dg"}, {"name": "Other", "description": "do"}],
                        tyre_settings=[flag, absent])

    def test_tyre_answers_the_tyre_groups_and_every_field_with_its_group_and_no_range(self):
        self.with_tyre_groups()
        self.make_tyre("Soft")
        r = self.get("/api/tyre?id=soft")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json["groups"], [{"name": "Grip", "description": "dg"}, {"name": "Other", "description": "do"}])
        rows = {row["id"]: row for row in r.json["rows"]}
        self.assertEqual(list(rows), ["tyre_dy", "tyre_flag", "tyre_brake"])
        self.assertEqual([rows[i]["group"] for i in rows], ["Grip", "Other", "Other"])
        for row in rows.values():
            self.assertNotIn("base_range", row)
        self.assertEqual((rows["tyre_flag"]["default"], rows["tyre_flag"]["applicable"], rows["tyre_flag"]["kind"]), (False, True, "flag"))
        self.assertEqual((rows["tyre_brake"]["default"], rows["tyre_brake"]["applicable"]), (0.0, True))

    def test_tyre_set_and_unset_rows_have_no_range_and_a_bool_can_be_set(self):
        self.with_tyre_groups()
        self.make_tyre("Soft")
        r = self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": 1.3})
        self.assertNotIn("base_range", r.json["row"])
        r = self.post("/api/tyre_unset", {"id": "soft", "setting": "tyre_dy"})
        self.assertNotIn("base_range", r.json["row"])
        r = self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_flag", "value": "yes"})
        self.assertEqual((r.status, r.json["row"]["value"], r.json["row"]["changed"], "base_range" in r.json["row"]), (200, True, True, False))
        r = self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_flag", "value": False})
        self.assertEqual((r.json["row"]["value"], r.json["row"]["changed"]), (False, False))

    def test_tyre_answers_the_types_and_every_row_the_values_by_type(self):
        self.with_tyre_groups()
        self.fc.store[self.fc.key(os.path.join(self.fc.shared, "tyres", "road", "a.tyre"))]["modelData"]["flag"] = True
        self.make_tyre("Soft")
        r = self.get("/api/tyre?id=soft")
        self.assertEqual(r.json["types"], [{"type": "road", "label": "Road", "total": 2}, {"type": "slick", "label": "slick", "total": 1}])
        rows = {row["id"]: row for row in r.json["rows"]}
        self.assertEqual(rows["tyre_dy"]["type_ranges"], {"road": {"low": 1.0, "high": 1.25, "count": 2}, "slick": {"low": 1.5, "high": 1.5, "count": 1}})
        self.assertEqual(rows["tyre_flag"]["type_ranges"], {"road": {"values": [False, True], "count": 1}, "slick": {"values": [False], "count": 0}})
        self.assertEqual(rows["tyre_brake"]["type_ranges"], {})

    def test_tyre_set_and_unset_rows_carry_the_values_by_type(self):
        self.with_tyre_groups()
        self.make_tyre("Soft")
        for r in (self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": 1.3}),
                  self.post("/api/tyre_unset", {"id": "soft", "setting": "tyre_dy"})):
            self.assertEqual(r.json["row"]["type_ranges"], {"road": {"low": 1.0, "high": 1.25, "count": 2}, "slick": {"low": 1.5, "high": 1.5, "count": 1}})
        r = self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_flag", "value": True})
        self.assertEqual(r.json["row"]["type_ranges"], {"road": {"values": [False], "count": 0}, "slick": {"values": [False], "count": 0}})

    def test_tyre_answers_no_types_and_empty_values_by_type_when_the_ranges_cannot_be_computed(self):
        self.make_tyre("Soft")
        with mock.patch.object(tune, "tyre_ranges", side_effect=ValueError("no table")):
            r = self.get("/api/tyre?id=soft")
        self.assertEqual((r.status, r.json["types"], [row["type_ranges"] for row in r.json["rows"]]), (200, [], [{}]))

    def test_tyre_errors(self):
        self.make_tyre("Soft")
        self.write(os.path.join(self.work, "tyres", "old.json"), {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        for path, text in (("/api/tyre", "need id (text)"), ("/api/tyre?id=nope", "no tyre 'nope' in the library"),
                           ("/api/tyre?id=..%2Fx", "bad tyre id"), ("/api/tyre?id=old", "")):
            with self.subTest(path):
                r = self.get(path)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith(text), r.json)

    def test_tyre_new_answers_the_id_and_saves_the_tyre(self):
        r = self.post("/api/tyre_new", {"name": "Slick Soft", "source": ROAD_A})
        self.assertEqual((r.status, r.json), (200, {"id": "slick_soft"}))
        self.assertEqual(tune.load_tyre(self.work, "slick_soft"), {"version": tune.TYRE_VERSION, "name": "Slick Soft", "short": "SS", "source": ROAD_A, "values": {}})
        r = self.post("/api/tyre_new", {"name": "Wet", "source": "s", "short": "W1"})
        self.assertEqual((r.status, r.json), (200, {"id": "wet"}))
        self.assertEqual((tune.load_tyre(self.work, "wet")["short"], tune.load_tyre(self.work, "wet")["source"]), ("W1", SLICK_S))
        self.assertEqual(self.post("/api/tyre_new", {"name": "Null", "source": "a", "short": None}).status, 200)

    def test_tyre_new_errors_create_nothing(self):
        self.make_tyre("Soft")
        before = self.library_bytes()
        for body, text in (({"name": "X"}, "need name (text) and source (text)"), ({"source": ROAD_A}, "need name (text) and source (text)"),
                           ({"name": 5, "source": ROAD_A}, "need name (text) and source (text)"),
                           ({"name": "X", "source": ["a"]}, "need name (text) and source (text)"),
                           ({"name": "X", "source": ROAD_A, "short": 5}, "short must be text"),
                           ({"name": "X", "source": ROAD_A, "short": "abcd"}, "a tyre short name needs 1 to 3 characters"),
                           ({"name": "X", "source": ROAD_A, "short": "ab"}, "a tyre short name needs 1 to 3 characters"),
                           ({"name": "X", "source": ROAD_A, "short": ""}, "a tyre short name needs 1 to 3 characters"),
                           ({"name": "soft", "source": ROAD_A}, "a tyre named 'Soft' exists already"),
                           ({"name": "", "source": ROAD_A}, "a tyre name needs 1 to 40 characters"),
                           ({"name": "X", "source": "nope"}, "unknown tyre 'nope'"),
                           ({"name": "X", "source": "content\\cars\\ks_x\\data\\a.tyre"}, "unknown tyre")):
            with self.subTest(body):
                r = self.post("/api/tyre_new", body)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(self.library_bytes(), before)

    def test_tyre_new_takes_a_source_that_is_only_in_the_package(self):
        self.make_package(["road\\road_205_55_16.tyre"])
        r = self.post("/api/tyre_new", {"name": "Far", "source": "road_205_55_16"})
        self.assertEqual((r.status, r.json), (200, {"id": "far"}))
        self.assertEqual(tune.load_tyre(self.work, "far")["source"], GS + "tyres\\road\\road_205_55_16.tyre")
        self.assertEqual(self.post("/api/tyre_new", {"name": "Near", "source": ROAD_A}).status, 400)

    def test_tyre_rename_takes_an_optional_short_name(self):
        self.make_tyre("Soft")
        r = self.post("/api/tyre_rename", {"id": "soft", "name": "Harder", "short": "H2"})
        self.assertEqual((r.status, r.json), (200, {"tyre": {"id": "soft", "name": "Harder", "short": "H2", "source": ROAD_A, "changed": 0}}))
        r = self.post("/api/tyre_rename", {"id": "soft", "name": "Harder 2"})
        self.assertEqual(r.json["tyre"]["short"], "H2")
        for short, text in ((5, "short must be text"), ("abcd", "a tyre short name needs 1 to 3 characters"), ("", "a tyre short name needs")):
            r = self.post("/api/tyre_rename", {"id": "soft", "name": "Harder 2", "short": short})
            self.assertEqual(r.status, 400)
            self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(tune.load_tyre(self.work, "soft")["short"], "H2")

    def test_tyre_source_answers_the_tyre_and_keeps_the_values(self):
        self.make_tyre("Soft")
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.5", self.cat)
        r = self.post("/api/tyre_source", {"id": "soft", "source": "road\\b.tyre".replace("road\\", GS + "tyres\\road\\")})
        self.assertEqual((r.status, r.json), (200, {"tyre": {"id": "soft", "name": "Soft", "short": "SO", "source": ROAD_B, "changed": 1}}))
        self.assertEqual(self.post("/api/tyre_source", {"id": "soft", "source": "s"}).json["tyre"]["source"], SLICK_S)
        self.assertEqual(tune.load_tyre(self.work, "soft")["values"], {"tyre_dy": 1.5})

    def test_tyre_source_errors(self):
        self.make_tyre("Soft")
        before = self.library_bytes()
        for body, text in (({"id": "soft"}, "need id (text) and source (text)"), ({"source": "a"}, "need id (text) and source (text)"),
                           ({"id": 5, "source": "a"}, "need id (text) and source (text)"), ({"id": "soft", "source": "nope"}, "unknown tyre 'nope'"),
                           ({"id": "nope", "source": "a"}, "no tyre 'nope' in the library"), ({"id": "../x", "source": "a"}, "bad tyre id")):
            with self.subTest(body):
                r = self.post("/api/tyre_source", body)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(self.library_bytes(), before)

    def test_tyre_set_answers_the_row_and_the_range_warnings(self):
        self.make_tyre("Soft")
        r = self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": "1.5"})
        self.assertEqual((r.status, r.json["warnings"]), (200, []))
        self.assertEqual((r.json["row"]["id"], r.json["row"]["value"], r.json["row"]["changed"], r.json["row"]["default"]), ("tyre_dy", 1.5, True, 1.25))
        self.assertNotIn("axle", r.json["row"])
        r = self.post("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": 3.5})
        self.assertEqual(r.status, 200)
        self.assertEqual(len(r.json["warnings"]), 1)
        self.assertIn("2.5", r.json["warnings"][0])
        self.assertEqual(tune.load_tyre(self.work, "soft")["values"], {"tyre_dy": 3.5})

    def test_tyre_set_and_unset_errors(self):
        self.make_tyre("Soft")
        before = self.library_bytes()
        for path, body, text in (("/api/tyre_set", {"id": "soft", "setting": "tyre_dy"}, "need id (text), setting (text) and value"),
                                 ("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": None}, "need id (text), setting (text) and value"),
                                 ("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": [1]}, "need id (text), setting (text) and value"),
                                 ("/api/tyre_set", {"id": 5, "setting": "tyre_dy", "value": 1}, "need id (text), setting (text) and value"),
                                 ("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": "abc"}, ""),
                                 ("/api/tyre_set", {"id": "soft", "setting": "limiter", "value": 1}, "limiter is not a tyre setting"),
                                 ("/api/tyre_set", {"id": "soft", "setting": "nope", "value": 1}, ""),
                                 ("/api/tyre_set", {"id": "nope", "setting": "tyre_dy", "value": 1}, "no tyre 'nope' in the library"),
                                 ("/api/tyre_unset", {"id": "soft"}, "need id (text) and setting (text)"),
                                 ("/api/tyre_unset", {"setting": "tyre_dy"}, "need id (text) and setting (text)"),
                                 ("/api/tyre_unset", {"id": "soft", "setting": "limiter"}, "limiter is not a tyre setting"),
                                 ("/api/tyre_unset", {"id": "nope", "setting": "tyre_dy"}, "no tyre 'nope' in the library")):
            with self.subTest(path, body=body):
                r = self.post(path, body)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(self.library_bytes(), before)

    def test_tyre_unset_answers_the_row_back_on_its_default(self):
        self.make_tyre("Soft")
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.5", self.cat)
        r = self.post("/api/tyre_unset", {"id": "soft", "setting": "tyre_dy"})
        self.assertEqual((r.status, r.json["row"]["value"], r.json["row"]["changed"]), (200, 1.25, False))
        self.assertEqual(set(r.json), {"row"})
        self.assertEqual(tune.load_tyre(self.work, "soft")["values"], {})
        self.assertEqual(self.post("/api/tyre_unset", {"id": "soft", "setting": "tyre_dy"}).status, 200)

    def test_every_new_library_write_happens_under_state_lock(self):
        held = []
        for name in ("save_tyre",):
            def spy(*args, _name=name, _real=getattr(tune, name), **kw):
                held.append((_name, ts.STATE_LOCK.locked()))
                return _real(*args, **kw)
            self.patch(tune, name, spy)
        for path, body in (("/api/tyre_new", {"name": "Soft", "source": ROAD_A}), ("/api/tyre_source", {"id": "soft", "source": "s"}),
                           ("/api/tyre_set", {"id": "soft", "setting": "tyre_dy", "value": 1.5}), ("/api/tyre_unset", {"id": "soft", "setting": "tyre_dy"})):
            self.assertEqual(self.post(path, body).status, 200, path)
        self.assertEqual(held, [("save_tyre", True)] * 4)


class TestTyreChoiceRoutes(TyreCase):
    """GET /api/garage, POST /api/garage_set and /api/garage_reset: the tyre choice of the draft, a modded car and its versions."""

    def state_choice(self, tune_id=None, version=None):
        state = tune.read_version_state(self.work, "ks_x", version, tune_id) if version else tune.load_state(self.work, "ks_x", tune_id)
        return state.get(tune.TYRE_KEY)

    def test_the_answer_is_the_choice_of_the_engine_plus_the_own_tyres(self):
        self.make_tyre("Soft")
        self.make_tyre("Hard", SLICK_S)
        r = self.get("/api/garage")
        self.assertEqual(r.status, 200)
        self.assertEqual({k: v for k, v in r.json.items() if k != "own"}, dict(tune.tyre_choices(self.work, "ks_x"), car="ks_x", tune=None))
        self.assertEqual(r.json["own"], [{"key": "own:hard", "label": "Hard", "source_label": "slick s"},
                                         {"key": "own:soft", "label": "Soft", "source_label": "Road a"}])
        self.assertTrue(r.json["default"])
        self.assertEqual(r.json["stock_sets"], [{"front": "game:" + ROAD_A, "rear": "game:" + ROAD_B, "label": "Road a / Road b"},
                                                {"front": "game:" + SLICK_S, "rear": "game:" + SLICK_S, "label": "slick s / slick s"}])
        self.assertEqual((r.json["split"], r.json["start_front"], r.json["start_rear"]), (False, "game:" + ROAD_A, "game:" + ROAD_B))
        self.assertEqual(set(r.json), {"default", "stock_sets", "sets", "split", "fronts", "rears", "start_front", "start_rear", "labels", "car", "tune", "own"})

    def test_a_damaged_library_file_is_not_offered(self):
        self.make_tyre("Soft")
        self.write(os.path.join(self.work, "tyres", "bad.json"), [])
        self.assertEqual([o["key"] for o in self.get("/api/garage").json["own"]], ["own:soft"])

    def test_the_answer_needs_the_base_car(self):
        r = self.get("/api/garage?car=ks_y")
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        r = self.post("/api/garage_set", {"car": "ks_y", "choice": SETS_CHOICE})
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        r = self.post("/api/garage_reset", {"car": "ks_y"})
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_set_saves_a_choice_of_sets_for_the_draft_the_modded_car_and_a_version(self):
        self.make_tyre("Soft")
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        choice = {"sets": [{"front": "own:soft", "rear": "own:soft"}, {"front": "game:" + ROAD_A, "rear": "game:" + ROAD_B}], "split": False,
                  "start_front": "game:" + ROAD_A, "start_rear": "game:" + ROAD_B}
        for body, where in (({"tune": "draft"}, ("draft", None)), ({"tune": "ax01"}, ("ax01", None)), ({"tune": "ax01", "version": vid}, ("ax01", vid))):
            with self.subTest(body):
                r = self.post("/api/garage_set", dict(body, choice=choice))
                self.assertEqual((r.status, r.json), (200, {"ok": True}))
                self.assertEqual(self.state_choice(*where), choice)
        self.assertEqual(self.tune_state("ax01")[tune.TYRE_KEY], choice)
        self.assertFalse(os.path.exists(self.state_file()))
        r = self.get("/api/garage?tune=ax01&version=" + vid)
        self.assertEqual((r.json["default"], r.json["sets"], r.json["tune"]), (False, choice["sets"], "ax01"))

    def test_the_default_tune_is_the_state_file_without_a_tune(self):
        self.make_tune()
        r = self.post("/api/garage_set", {"choice": SETS_CHOICE})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual(self.tune_state()[tune.TYRE_KEY]["sets"], SETS_CHOICE["sets"])

    def test_a_split_choice_is_saved_with_its_fronts_and_rears(self):
        choice = {"split": True, "fronts": ["game:" + ROAD_A, "game:" + SLICK_S], "rears": ["game:" + ROAD_B], "start_front": "game:" + SLICK_S,
                  "start_rear": "game:" + ROAD_B}
        self.assertEqual(self.post("/api/garage_set", {"tune": "draft", "choice": choice}).json, {"ok": True})
        self.assertEqual(self.state_choice("draft"), choice)
        r = self.get("/api/garage?tune=draft")
        self.assertEqual((r.json["split"], r.json["sets"], r.json["fronts"], r.json["rears"], r.json["start_front"]),
                         (True, [], choice["fronts"], choice["rears"], "game:" + SLICK_S))

    def test_the_choice_of_the_original_sets_removes_the_saved_choice(self):
        self.post("/api/garage_set", {"tune": "draft", "choice": SETS_CHOICE})
        self.assertIn(tune.TYRE_KEY, tune.load_state(self.work, "ks_x", "draft"))
        original = {"sets": [{"front": "game:" + ROAD_A, "rear": "game:" + ROAD_B}, {"front": "game:" + SLICK_S, "rear": "game:" + SLICK_S}], "split": False}
        self.assertEqual(self.post("/api/garage_set", {"tune": "draft", "choice": original}).json, {"ok": True})
        self.assertNotIn(tune.TYRE_KEY, tune.load_state(self.work, "ks_x", "draft"))
        self.assertTrue(self.get("/api/garage?tune=draft").json["default"])

    def test_set_errors_save_nothing(self):
        self.make_tyre("Soft")
        self.make_tune("ax01", {"name_suffix": "_A"})
        bad_start = dict(SETS_CHOICE, start_front="game:" + ROAD_B)
        for body, text in (({}, "need choice (an object)"), ({"choice": None}, "need choice (an object)"), ({"choice": [1]}, "need choice (an object)"),
                           ({"choice": "x"}, "need choice (an object)"), ({"choice": {}}, "sets must be a list with at least one set"),
                           ({"choice": {"sets": []}}, "sets must be a list with at least one set"),
                           ({"choice": {"sets": [{"front": "game:x"}]}}, "a set is {front, rear}"),
                           ({"choice": {"sets": [{"front": "road\\a", "rear": "road\\a"}]}}, "bad tyre key"),
                           ({"choice": dict(SETS_CHOICE, extra=1)}, "unknown field 'extra' in the tyre choice"),
                           ({"choice": dict(SETS_CHOICE, split="yes")}, "split must be true or false"),
                           ({"choice": {"split": True, "fronts": ["game:" + ROAD_A]}}, "rears must be a list of tyre keys"),
                           ({"choice": bad_start}, "start_front"),
                           ({"choice": {"sets": [{"front": "game:" + GS + "tyres\\road\\nope.tyre", "rear": "game:" + ROAD_B}], "split": False}}, "unknown tyre"),
                           ({"choice": {"sets": [{"front": "own:ghost", "rear": "own:ghost"}], "split": False}}, "no tyre 'ghost' in the library")):
            for extra in ({}, {"tune": "ax01"}):
                with self.subTest(body, extra=extra):
                    r = self.post("/api/garage_set", dict(body, **extra))
                    self.assertEqual(r.status, 400)
                    self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))

    def test_a_saved_choice_that_is_damaged_is_400_for_the_read(self):
        self.make_tune("ax01", {"name_suffix": "_A", tune.TYRE_KEY: {"sets": "x"}})
        r = self.get("/api/garage?tune=ax01")
        self.assertEqual(r.status, 400)
        self.assertTrue(r.json["error"], r.json)

    def test_reset_removes_the_choice_of_that_state_only(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        for tune_id, version in (("ax01", None), ("ax01", vid), ("draft", None)):
            tune.set_tyres(self.work, "ks_x", SETS_CHOICE, tune_id, version, game=self.game)
        r = self.post("/api/garage_reset", {"tune": "ax01", "version": vid})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertIsNone(self.state_choice("ax01", vid))
        self.assertIsNotNone(self.state_choice("ax01"))
        self.assertIsNotNone(self.state_choice("draft"))
        self.assertEqual(self.post("/api/garage_reset", {"tune": "ax01"}).json, {"ok": True})
        self.assertEqual(self.post("/api/garage_reset", {"tune": "draft"}).json, {"ok": True})
        self.assertEqual(self.post("/api/garage_reset", {"tune": "draft"}).json, {"ok": True})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})

    def test_a_version_needs_a_modded_car_and_must_exist(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        for path, body in (("/api/garage", None), ("/api/garage_set", {"choice": SETS_CHOICE}), ("/api/garage_reset", {})):
            for tune_id, version, text in (("draft", "v01", "a version needs a modded car"), ("ax01", "v02", "unknown version v02 of ax01")):
                with self.subTest(path, tune=tune_id):
                    if body is None:
                        r = self.get("%s?tune=%s&version=%s" % (path, tune_id, version))
                    else:
                        r = self.post(path, dict(body, tune=tune_id, version=version))
                    self.assertEqual((r.status, r.json), (400, {"error": text}))

    def test_a_locked_version_refuses_the_choice_and_its_reset_with_400(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        tune.set_tyres(self.work, "ks_x", SETS_CHOICE, "ax01", vid, game=self.game)
        meta_path = tune.version_meta_path(self.work, "ks_x", vid, "ax01")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        tune.save_json(meta_path, dict(meta, locked=True))
        before = tune.read_version_state(self.work, "ks_x", vid, "ax01")
        text = "version v01 (Heavy) is locked; unlock it to change it"
        for path, body in (("/api/garage_set", {"choice": {"sets": [{"front": "game:" + SLICK_S, "rear": "game:" + SLICK_S}], "split": False}}),
                           ("/api/garage_reset", {})):
            with self.subTest(path):
                r = self.post(path, dict(body, tune="ax01", version=vid))
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual(tune.read_version_state(self.work, "ks_x", vid, "ax01"), before)
        self.assertEqual(self.get("/api/garage?tune=ax01&version=" + vid).status, 200)

    def test_the_writes_happen_under_state_lock(self):
        held = []
        for name in ("set_tyres", "reset_tyres"):
            def spy(*args, _name=name, _real=getattr(tune, name), **kw):
                held.append((_name, ts.STATE_LOCK.locked()))
                return _real(*args, **kw)
            self.patch(tune, name, spy)
        self.assertEqual(self.post("/api/garage_set", {"tune": "draft", "choice": SETS_CHOICE}).status, 200)
        self.assertEqual(self.post("/api/garage_reset", {"tune": "draft"}).status, 200)
        self.assertEqual(held, [("set_tyres", True), ("reset_tyres", True)])

    def test_the_game_of_the_config_is_the_package_the_tyres_are_checked_against(self):
        pkg = self.make_package(["road\\road_235_35_19.tyre"])
        good = {"sets": [{"front": "game:" + GS + "tyres\\road\\road_235_35_19.tyre", "rear": "game:" + GS + "tyres\\road\\road_235_35_19.tyre"}], "split": False}
        self.assertEqual(self.post("/api/garage_set", {"tune": "draft", "choice": good}).json, {"ok": True})
        self.assertEqual(self.state_choice("draft")["sets"], good["sets"])
        r = self.post("/api/garage_set", {"tune": "draft", "choice": SETS_CHOICE})
        self.assertEqual(r.status, 400)
        self.assertIn("unknown tyre", r.json["error"])
        self.assertTrue(os.path.isfile(pkg))


class TestTyreWorkingRoutes(TyreCase):
    def test_the_library_routes_need_no_base_car(self):
        self.make_tyre("Soft")
        self.assertFalse(ts.base_present(self.work, "ks_y"))
        r = self.post("/api/tyre_rename", {"car": "ks_y", "id": "soft", "name": "Hard"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.post("/api/tyre_reset", {"car": "ks_y", "id": "soft"}).status, 200)
        self.assertEqual(self.post("/api/tyre_delete", {"car": "ks_y", "id": "soft"}).status, 200)

    def test_the_raw_query_is_the_third_argument_of_a_query_route_only(self):
        seen, two = [], []

        def spy(car, tune_id, query):
            seen.append((car, tune_id, query))
            return {}
        with mock.patch.dict(ts.GET_ROUTES, {"/api/tyre": spy}):
            self.assertEqual(self.get("/api/tyre?id=soft&car=ks_x&tune=draft").status, 200)
        self.assertEqual(seen, [("ks_x", "draft", "id=soft&car=ks_x&tune=draft")])
        with mock.patch.dict(ts.GET_ROUTES, {"/api/state": lambda car, tune_id: two.append((car, tune_id)) or {}}):
            self.assertEqual(self.get("/api/state?id=soft&tune=draft").status, 200)
        self.assertEqual(two, [("ks_x", "draft")])

    def test_the_existing_get_routes_ignore_an_id_parameter(self):
        self.make_tyre("Soft")
        self.assertEqual(self.get("/api/state?id=soft").json["car"], "ks_x")
        self.assertEqual(self.get("/api/settings?id=nope").json, self.get("/api/settings").json)

    def test_tyre_rename_answers_with_the_tyre(self):
        self.make_tyre("Soft")
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.5", self.cat)
        r = self.post("/api/tyre_rename", {"id": "soft", "name": "Hard"})
        self.assertEqual((r.status, r.json), (200, {"tyre": {"id": "soft", "name": "Hard", "short": "SO", "source": ROAD_A, "changed": 1}}))
        self.assertEqual(tune.load_tyre(self.work, "soft")["values"], {"tyre_dy": 1.5})
        self.assertEqual(self.post("/api/tyre_rename", {"id": "soft", "name": "HARD"}).status, 200)

    def test_tyre_rename_errors(self):
        self.make_tyre("Soft")
        self.make_tyre("Hard", SLICK_S)
        before = self.library_bytes()
        for body, status, text in (({"id": "soft", "name": "hard"}, 400, "a tyre named 'Hard' exists already"),
                                   ({"id": "soft", "name": ""}, 400, "a tyre name needs"),
                                   ({"id": "nope", "name": "X"}, 400, "no tyre 'nope' in the library"),
                                   ({"id": "../x", "name": "X"}, 400, "bad tyre id"),
                                   ({"id": "soft"}, 400, "need id (text) and name (text)"),
                                   ({"name": "X"}, 400, "need id (text) and name (text)"),
                                   ({"id": 5, "name": "X"}, 400, "need id (text) and name (text)"),
                                   ({"id": "soft", "name": 5}, 400, "need id (text) and name (text)")):
            with self.subTest(body):
                r = self.post("/api/tyre_rename", body)
                self.assertEqual(r.status, status)
                self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(self.library_bytes(), before)

    def test_a_tyre_saved_in_the_old_form_is_400_for_a_rename(self):
        self.write(os.path.join(self.work, "tyres", "old.json"), {"version": 1, "name": "Old", "source": {"front": ROAD_A, "rear": ROAD_B}, "values": {}})
        r = self.post("/api/tyre_rename", {"id": "old", "name": "New"})
        self.assertEqual(r.status, 400)
        self.assertIn("old front/rear form", r.json["error"])

    def test_tyre_reset_drops_every_changed_value(self):
        self.make_tyre("Soft")
        tune.set_tyre_value(self.work, "soft", "tyre_dy", "1.5", self.cat)
        r = self.post("/api/tyre_reset", {"id": "soft"})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual(tune.load_tyre(self.work, "soft")["values"], {})
        self.assertEqual(self.post("/api/tyre_reset", {"id": "soft"}).json, {"ok": True})

    def test_tyre_reset_and_delete_errors(self):
        self.make_tyre("Soft")
        before = self.library_bytes()
        for path in ("/api/tyre_reset", "/api/tyre_delete"):
            for body, text in (({"id": "nope"}, "no tyre 'nope' in the library"), ({"id": "../x"}, "bad tyre id"),
                               ({"id": "A"}, "bad tyre id"), ({}, "need id (text)"), ({"id": 5}, "need id (text)"),
                               ({"id": None}, "need id (text)"), ({"id": ["soft"]}, "need id (text)")):
                with self.subTest(path, body=body):
                    r = self.post(path, body)
                    self.assertEqual(r.status, 400)
                    self.assertTrue(r.json["error"].startswith(text), r.json)
        self.assertEqual(self.library_bytes(), before)

    def test_tyre_delete_removes_the_file(self):
        self.make_tyre("Soft")
        self.make_tyre("Slicky", SLICK_S)
        r = self.post("/api/tyre_delete", {"id": "soft"})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual([t["id"] for t in tune.list_tyres(self.work)], ["slicky"])
        self.assertEqual(self.post("/api/tyre_delete", {"id": "soft"}).status, 400)

    def test_a_tyre_a_state_uses_is_409_until_the_choice_is_gone(self):
        self.make_tyre("Soft")
        self.make_tune("ax01", {"name_suffix": "_A"})
        vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        self.use("soft", "ax01")
        r = self.post("/api/tyre_delete", {"id": "soft"})
        self.assertEqual((r.status, r.json), (409, {"error": "tyre soft is used by ks_x / ax01"}))
        self.use("soft", "ax01", vid)
        self.use("soft", "draft")
        r = self.post("/api/tyre_delete", {"id": "soft"})
        self.assertEqual((r.status, r.json), (409, {"error": "tyre soft is used by ks_x / ax01, ks_x / ax01 / v01, ks_x (draft)"}))
        for tune_id, version in (("ax01", None), ("ax01", vid), ("draft", None)):
            self.assertEqual(self.post("/api/tyre_delete", {"id": "soft"}).status, 409)
            tune.reset_tyres(self.work, "ks_x", tune_id, version)
        r = self.post("/api/tyre_delete", {"id": "soft"})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertFalse(tune.tyre_exists(self.work, "soft"))

    def test_a_tyre_the_default_modded_car_uses_is_409(self):
        self.make_tyre("Soft")
        self.make_tune()
        self.use("soft")
        r = self.post("/api/tyre_delete", {"id": "soft"})
        self.assertEqual((r.status, r.json), (409, {"error": "tyre soft is used by ks_x / ax_x"}))

    def test_a_missing_tyre_is_400_not_409_even_when_a_state_names_it(self):
        self.make_tune("ax01", {"name_suffix": "_A", tune.TYRE_KEY: {"sets": [{"front": "own:ghost", "rear": "game:x"}], "split": False}})
        r = self.post("/api/tyre_delete", {"id": "ghost"})
        self.assertEqual((r.status, r.json), (400, {"error": "no tyre 'ghost' in the library"}))

    def test_every_library_write_of_a_working_route_happens_under_state_lock(self):
        held = []
        for name in ("save_tyre", "delete_tyre"):
            def spy(*args, _name=name, _real=getattr(tune, name), **kw):
                held.append((_name, ts.STATE_LOCK.locked()))
                return _real(*args, **kw)
            self.patch(tune, name, spy)
        self.make_tyre("Soft")
        held.clear()
        for path, body in (("/api/tyre_rename", {"id": "soft", "name": "Hard"}), ("/api/tyre_reset", {"id": "soft"}), ("/api/tyre_delete", {"id": "soft"})):
            self.assertEqual(self.post(path, body).status, 200, path)
        self.assertEqual(held, [("save_tyre", True), ("delete_tyre", True)])


class TurboCase(TuneCase):
    """TuneCase with two donor cars next to ks_x (no turbo): ks_a has one turbo (boost 0.9, name from the car index) and ks_b two
    (boost 0.7 and 0.7, name from its stock info), ks_t one (boost 1.0): all three are donors of ks_x, and each is the car under test
    where the car itself has a turbo."""

    def setUp(self):
        super().setUp()
        self.write(os.path.join(self.work, "cars_index.json"),
                   [{"id": "ks_x", "display_name": "Car X", "brand": "B", "year": 1999}, {"id": "ks_y", "display_name": "Car Y", "brand": "B", "year": 2000},
                    {"id": "ks_a", "display_name": "Single A", "brand": "B", "year": 2001}, {"id": "ks_b", "display_name": "Twin B", "brand": "B", "year": 2002},
                    {"id": "ks_t", "display_name": "Car T", "brand": "B", "year": 2003}])
        self.add_car("ks_a", ["t0.turbo"], [0.9])
        self.add_car("ks_b", ["t0.turbo", "t1.turbo"], [0.7, 0.7])
        self.add_car("ks_t", ["t0.turbo"], [1.0])
        self.write(tune.stock_info_path(self.work, "ks_b"), {"car_id": "ks_b", "display_name": "Twin B", "brand": "Brand", "year": 1999})

    def add_car(self, car_id, turbos, boost):
        fc = FakeCar(self.work, car_id)
        fc.store = self.fc.store
        gp = fc.game_path
        fc.add("data/%s.car" % car_id, {"engine_path": gp("data/engine.carengine")})
        fc.add("data/engine.carengine", {"limiter": 7000, "turbos_to_load": [gp("data/" + t) for t in turbos],
                                         "turbos": [{"max_boost": b} for b in boost]})
        for t, b in zip(turbos, boost):
            fc.add("data/" + t, {"max_boost": b})
        return fc

    def turbo(self, query=""):
        return self.get("/api/turbo" + query)

    def kit(self, donor):
        return {tune.TURBO_KEY: {"donor": donor}}


class TestTurboRoutes(TurboCase):
    def test_turbo_of_the_default_car_offers_the_donors_and_has_no_kit(self):
        r = self.turbo()
        self.assertEqual((r.status, r.headers.get("Content-Type"), set(r.json)), (200, "application/json; charset=utf-8", TURBO_KEYS))
        self.assertEqual((r.json["car"], r.json["tune"], r.json["donor"], r.json["picked"]), ("ks_x", None, None, None))
        self.assertEqual((r.json["available"], r.json["reason"], r.json["has_turbo"]), (True, "", False))
        self.assertEqual(r.json["donors"], [OWN, SINGLE, TWIN])
        self.assertEqual(r.json, dict(tune.turbo_choice(self.work, "ks_x"), car="ks_x", tune=None, has_turbo=False))

    def test_a_car_with_a_turbo_of_its_own_has_turbo_and_no_choice_and_is_not_its_own_donor(self):
        r = self.turbo("?car=ks_t")
        self.assertEqual((r.status, r.json["has_turbo"], r.json["available"], r.json["reason"]), (200, True, False, "the car has a turbo already"))
        self.assertEqual(r.json["donors"], [SINGLE, TWIN])
        r = self.turbo("?car=ks_a")
        self.assertEqual((r.json["has_turbo"], [d["car"] for d in r.json["donors"]]), (True, ["ks_t", "ks_b"]))

    def test_without_any_donor_the_choice_is_not_available_and_the_car_has_no_turbo(self):
        for car_id in ("ks_a", "ks_b", "ks_t"):
            shutil.rmtree(tune.base_dir(self.work, car_id))
        r = self.turbo()
        self.assertEqual((r.status, r.json["donors"], r.json["available"], r.json["reason"], r.json["has_turbo"]),
                         (200, [], False, "no installed car has a turbo", False))

    def test_turbo_echoes_the_tune_and_reads_its_own_state(self):
        self.make_tune("ax01", dict({"name_suffix": "_A"}, **self.kit("ks_b")))
        r = self.turbo("?tune=ax01")
        self.assertEqual((r.json["tune"], r.json["donor"], r.json["picked"]), ("ax01", "ks_b", TWIN))
        self.assertEqual(self.turbo("?tune=draft").json["tune"], "draft")
        self.assertIsNone(self.turbo("?tune=draft").json["donor"])
        self.assertIsNone(self.turbo().json["donor"])

    def test_turbo_names_a_saved_donor_that_is_not_offered_any_more(self):
        self.make_tune(None, self.kit("ks_gone"))
        r = self.turbo()
        self.assertEqual((r.status, r.json["donor"], r.json["picked"], r.json["available"]), (200, "ks_gone", None, True))

    def test_turbo_needs_the_base_car(self):
        r = self.turbo("?car=ks_y")
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertEqual(self.turbo("?car=ks_y&tune=draft").status, 409)

    def test_turbo_with_a_damaged_kit_is_400(self):
        self.make_tune(None, {tune.TURBO_KEY: "ks_b"})
        r = self.turbo()
        self.assertEqual((r.status, r.json), (400, {"error": "damaged turbo kit in the saved state"}))

    def test_turbo_is_read_under_state_lock(self):
        held, real = [], tune.turbo_choice

        def spy(*args, **kw):
            held.append(ts.STATE_LOCK.locked())
            return real(*args, **kw)
        self.patch(tune, "turbo_choice", spy)
        self.turbo()
        self.assertEqual(held, [True])

    def test_turbo_set_chooses_the_donor_of_the_default_tune(self):
        r = self.post("/api/turbo_set", {"donor": "ks_b"})
        self.assertEqual((r.status, set(r.json)), (200, {"result", "turbo", "sounds", "sound_link"}))
        self.assertEqual(r.json["result"], {"donor": "ks_b", "count": 2, "kind": "twin turbo", "boost": [0.7, 0.7], "boost_ref": None})
        self.assertEqual(r.json["turbo"], self.turbo().json)
        self.assertEqual((r.json["turbo"]["donor"], r.json["turbo"]["picked"], r.json["turbo"]["has_turbo"]), ("ks_b", TWIN, False))
        self.assertEqual(self.saved_state(), self.kit("ks_b"))

    def test_turbo_set_names_the_kind_and_the_boost_of_each_donor(self):
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual((r.json["result"]["kind"], r.json["result"]["boost"], r.json["turbo"]["picked"]["kind"], r.json["turbo"]["picked"]["boost"]),
                         ("single turbo", [0.9], "single turbo", [0.9]))

    def test_turbo_and_turbo_set_carry_the_reference_boost_of_a_donor_without_a_boost(self):
        engine_key = self.fc.key(os.path.join(tune.car_root_of(tune.base_dir(self.work, "ks_a"), "ks_a"), "data", "engine.carengine"))
        turbo_key = self.fc.key(os.path.join(tune.car_root_of(tune.base_dir(self.work, "ks_a"), "ks_a"), "data", "t0.turbo"))
        del self.fc.store[engine_key]["turbos"]
        self.fc.store[engine_key]["max_turbo_boost"] = 1.2
        self.fc.store[turbo_key].clear()
        ref = dict(SINGLE, boost=[], boost_ref=1.2)
        self.assertEqual(self.turbo().json["donors"], [OWN, ref, TWIN])
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual(r.json["result"], {"donor": "ks_a", "count": 1, "kind": "single turbo", "boost": [], "boost_ref": 1.2})
        self.assertEqual(r.json["turbo"]["picked"], ref)

    def test_turbo_set_replaces_the_donor_and_keeps_the_other_values_of_the_state(self):
        self.write(self.state_file(), {"limiter": 8000})
        self.post("/api/turbo_set", {"donor": "ks_b"})
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual((r.status, r.json["turbo"]["donor"]), (200, "ks_a"))
        self.assertEqual(self.saved_state(), {"limiter": 8000, tune.TURBO_KEY: {"donor": "ks_a"}})

    def test_turbo_set_of_a_modded_car_changes_only_its_state(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        r = self.post("/api/turbo_set", {"donor": "ks_b", "tune": "ax01"})
        self.assertEqual((r.status, r.json["turbo"]["tune"], r.json["turbo"]["donor"]), (200, "ax01", "ks_b"))
        self.assertEqual(self.tune_state("ax01"), dict({"name_suffix": "_A"}, **self.kit("ks_b")))
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))
        self.assertEqual(self.turbo("?tune=ax01").json, r.json["turbo"])

    def test_turbo_set_of_the_draft_needs_no_modded_car(self):
        r = self.post("/api/turbo_set", {"donor": "ks_a", "tune": "draft"})
        self.assertEqual((r.status, r.json["turbo"]["tune"]), (200, "draft"))
        self.assertEqual(self.tune_state("draft"), self.kit("ks_a"))
        self.assertEqual(self.tune_ids(), [])
        self.assertFalse(os.path.exists(self.state_file()))

    def test_turbo_set_with_a_donor_that_is_not_text_is_400_and_writes_nothing(self):
        for body in ({}, {"donor": None}, {"donor": 5}, {"donor": ["ks_b"]}, {"donor": {"car": "ks_b"}}, {"donor": True}):
            with self.subTest(body):
                r = self.post("/api/turbo_set", body)
                self.assertEqual((r.status, r.json), (400, {"error": "need donor (text)"}))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_turbo_set_with_a_refused_donor_is_400_with_the_message_and_changes_nothing(self):
        self.write(self.state_file(), {"limiter": 8000, tune.TURBO_KEY: {"donor": "ks_a"}})
        for body, text in (({"donor": "ks_zz"}, "ks_zz is not an installed car with a turbo"),
                           ({"donor": "ks_y"}, "ks_y is not an installed car with a turbo"),
                           ({"donor": "ks_x"}, "ks_x cannot be its own turbo donor"),
                           ({"donor": ""}, " is not an installed car with a turbo"),
                           ({"donor": "ks_b", "car": "ks_t"}, "ks_t has a turbo already")):
            with self.subTest(body):
                r = self.post("/api/turbo_set", body)
                self.assertEqual(r.status, 400)
                self.assertTrue(r.json["error"].endswith(text), r.json)
        self.assertEqual(self.saved_state(), {"limiter": 8000, tune.TURBO_KEY: {"donor": "ks_a"}})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_t")))

    def test_turbo_set_without_a_base_is_409_and_writes_nothing(self):
        for tune_id in (None, "draft"):
            with self.subTest(tune_id):
                r = self.post("/api/turbo_set", {"car": "ks_y", "donor": "ks_b", "tune": tune_id})
                self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_y")))

    def test_turbo_set_with_an_unknown_modded_car_is_400(self):
        r = self.post("/api/turbo_set", {"donor": "ks_b", "tune": "nope"})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))

    def test_turbo_reset_removes_the_kit_and_keeps_the_other_values(self):
        self.write(self.state_file(), {"limiter": 8000, tune.TURBO_KEY: {"donor": "ks_b"}})
        r = self.post("/api/turbo_reset", {})
        self.assertEqual((r.status, set(r.json), r.json["removed"]), (200, {"removed", "turbo"}, True))
        self.assertEqual((r.json["turbo"]["donor"], r.json["turbo"]["picked"], set(r.json["turbo"])), (None, None, TURBO_KEYS))
        self.assertEqual(r.json["turbo"], self.turbo().json)
        self.assertEqual(self.saved_state(), {"limiter": 8000})

    def test_turbo_reset_without_a_kit_changes_nothing(self):
        r = self.post("/api/turbo_reset")
        self.assertEqual((r.status, r.json["removed"], r.json["turbo"]["donor"]), (200, False, None))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_turbo_reset_of_a_modded_car_and_of_the_draft(self):
        self.make_tune("ax01", dict({"name_suffix": "_A"}, **self.kit("ks_b")))
        self.make_tune(tune.DRAFT, dict({"limiter": 8000}, **self.kit("ks_a")))
        self.make_tune(None, self.kit("ks_a"))
        r = self.post("/api/turbo_reset", {"tune": "ax01"})
        self.assertEqual((r.status, r.json["removed"], r.json["turbo"]["tune"]), (200, True, "ax01"))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})
        self.assertEqual(self.post("/api/turbo_reset", {"tune": "draft"}).json["removed"], True)
        self.assertEqual(self.tune_state("draft"), {"limiter": 8000})
        self.assertEqual(self.saved_state(), self.kit("ks_a"))

    def test_turbo_reset_without_a_base_is_409(self):
        r = self.post("/api/turbo_reset", {"car": "ks_y"})
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_turbo_reset_with_a_damaged_kit_still_removes_it(self):
        self.write(self.state_file(), {tune.TURBO_KEY: "ks_b"})
        r = self.post("/api/turbo_reset", {})
        self.assertEqual((r.status, r.json["removed"], r.json["turbo"]["donor"]), (200, True, None))
        self.assertEqual(self.saved_state(), {})

    def test_the_kit_writes_happen_under_state_lock(self):
        held = []
        for name in ("set_turbo", "reset_turbo"):
            def spy(*args, _name=name, _real=getattr(tune, name), **kw):
                held.append((_name, ts.STATE_LOCK.locked()))
                return _real(*args, **kw)
            self.patch(tune, name, spy)
        self.assertEqual(self.post("/api/turbo_set", {"donor": "ks_b"}).status, 200)
        self.assertEqual(self.post("/api/turbo_reset", {}).status, 200)
        self.assertEqual(held, [("set_turbo", True), ("reset_turbo", True)])

    def test_both_writes_are_409_while_a_job_runs_and_change_nothing(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        self.entered.wait(5)
        for path, body in (("/api/turbo_set", {"donor": "ks_b"}), ("/api/turbo_reset", {})):
            for tune_id in (None, "ax01", "draft"):
                with self.subTest(path, tune=tune_id):
                    r = self.post(path, dict(body, tune=tune_id))
                    self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        r = self.post("/api/turbo_set", {"donor": 5})
        self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))
        self.assertEqual(self.turbo().status, 200)
        self.finish_held_job()
        self.assertEqual(self.post("/api/turbo_set", {"donor": "ks_b"}).status, 200)

    def test_the_routes_check_the_host_the_post_headers_and_the_method(self):
        self.assertEqual(self.post("/api/turbo_set", {"donor": "ks_b"}, headers={"X-Tuner": None}).status, 403)
        r = self.post("/api/turbo_reset", {}, headers={"Content-Type": "text/plain"})
        self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        self.assertEqual(self.get("/api/turbo", host="evil.example").status, 403)
        self.assertEqual(self.post("/api/turbo_set", {"donor": "ks_b"}, host="evil.example").status, 403)
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertEqual(self.get("/api/turbo_set").status, 404)
        self.assertEqual(self.get("/api/turbo_reset").status, 404)
        self.assertEqual(self.post("/api/turbo", {}).status, 404)
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method):
                r = self.request(method, "/api/turbo")
                self.assertEqual((r.status, r.headers.get("Allow")), (405, "GET, POST"))

    def test_the_statuses_of_the_turbo_routes_are_200_not_202(self):
        self.assertTrue({"/api/turbo", "/api/turbo_set", "/api/turbo_reset"}.isdisjoint(ts.ACCEPTED))
        self.assertTrue({"/api/turbo"}.isdisjoint(ts.QUERY_ROUTES))


class TestSettingsWithATurboKit(TurboCase):
    def test_the_settings_of_a_tune_with_a_kit_are_read_from_the_kit_root(self):
        asked = []

        def kit_root(work, car_id, donor):
            asked.append((work, car_id, donor))
            return tune.base_dir(work, car_id)
        self.patch(tune, "kit_root", kit_root)
        self.make_tune("ax01", dict({"limiter": 8000, "name_suffix": "_A"}, **self.kit("ks_b")))
        r = self.get("/api/settings?tune=ax01")
        self.assertEqual(r.status, 200)
        self.assertEqual(next(row["value"] for row in r.json if row["id"] == "limiter"), 8000)
        self.assertEqual(set(asked), {(self.work, "ks_x", "ks_b")})
        self.assertEqual(self.get("/api/settings?tune=draft").status, 200)
        self.assertEqual(set(asked), {(self.work, "ks_x", "ks_b")})

    def test_the_settings_of_the_draft_and_the_default_tune_with_a_kit_use_it_too(self):
        asked = []
        self.patch(tune, "kit_root", lambda work, car_id, donor: asked.append(donor) or tune.base_dir(work, car_id))
        self.make_tune(tune.DRAFT, self.kit("ks_a"))
        self.make_tune(None, dict({"name_suffix": "_D"}, **self.kit("ks_b")))
        self.assertEqual(self.get("/api/settings?tune=draft").status, 200)
        self.assertEqual(self.get("/api/settings").status, 200)
        self.assertEqual(asked, ["ks_a", "ks_b"])

    def test_the_settings_of_a_tune_whose_donor_is_gone_are_400_with_the_turbo_kit_message(self):
        for tune_id, state in (("ax01", {"name_suffix": "_A", tune.TURBO_KEY: {"donor": "ks_gone"}}), (tune.DRAFT, self.kit("ks_gone")),
                               (None, self.kit("ks_gone"))):
            with self.subTest(tune_id):
                self.make_tune(tune_id, state)
                r = self.get("/api/settings" + ("" if tune_id is None else "?tune=" + tune_id))
                self.assertEqual((r.status, r.json), (400, {"error": "turbo kit: ks_gone is not an installed car with a turbo"}))

    def test_the_settings_of_a_car_that_has_a_turbo_but_a_saved_kit_are_400(self):
        tune.save_state(self.work, "ks_t", self.kit("ks_b"), tune.DRAFT)
        r = self.get("/api/settings?car=ks_t&tune=draft")
        self.assertEqual((r.status, r.json), (400, {"error": "turbo kit: ks_t has a turbo already"}))

    def test_removing_the_kit_makes_the_settings_readable_again(self):
        self.make_tune(None, self.kit("ks_gone"))
        self.assertEqual(self.get("/api/settings").status, 400)
        self.assertEqual(self.post("/api/turbo_reset", {}).json["removed"], True)
        self.assertEqual(self.get("/api/settings").status, 200)


# -------------------------------------------------------------------------------------------------- sound picker
class SoundCase(TurboCase):
    """TurboCase with an .actor file in every installed car: ks_x (own sounds turbo_none and backfire_a), ks_a (turbo_rx7, backfire_classic
    with optionalParam 8), ks_b (a backfire entry only: backfire_b, no turbo entry although the car has turbos) and ks_t (the same sounds
    as ks_x)."""

    def setUp(self):
        super().setUp()
        for car_id, entries in (("ks_x", [audio(TE + "turbo_none", "TurboEvent"), audio(BE + "backfire_a", "Backfire", BACKFIRE_BANK)]),
                                ("ks_a", [audio(BE + "backfire_classic", "Backfire", BACKFIRE_BANK, optionalParam=8), audio(TE + "turbo_rx7", "TurboEvent")]),
                                ("ks_b", [audio(BE + "backfire_b", "Backfire", BACKFIRE_BANK)]),
                                ("ks_t", [audio(TE + "turbo_none", "TurboEvent"), audio(BE + "backfire_a", "Backfire", BACKFIRE_BANK)])):
            fc = FakeCar(self.work, car_id)
            fc.store = self.fc.store
            fc.add("%s.actor" % car_id, actor_of(audio("event:/evo_cars/%s/engine_int" % car_id, None, "content\\sfx\\%s.bank" % car_id), *entries))

    def sounds(self, query=""):
        return self.get("/api/sounds" + query)

    def remove_actor(self, car_id):
        del self.fc.store[self.fc.key(tune.actor_path(self.work, car_id))]

    def keys_of(self, reply, slot):
        return [o["key"] for o in reply.json["slots"][slot]["options"]]


class TestSoundsRoute(SoundCase):
    def test_sounds_of_the_default_car_offers_the_sounds_of_all_installed_cars(self):
        r = self.sounds()
        self.assertEqual((r.status, r.headers.get("Content-Type"), set(r.json)), (200, "application/json; charset=utf-8", SOUND_KEYS))
        self.assertEqual((r.json["car"], r.json["tune"], r.json["missing"], r.json["skipped"]), ("ks_x", None, [], []))
        self.assertEqual(list(r.json["slots"]), ["turbo", "backfire"])
        self.assertEqual([set(s) for s in r.json["slots"].values()], [SLOT_KEYS, SLOT_KEYS])
        self.assertEqual((self.keys_of(r, "turbo"), self.keys_of(r, "backfire")), ([T_NONE, T_RX7], [B_A, B_B, B_CLASSIC]))
        self.assertEqual([(o["key"], o["cars"]) for o in r.json["slots"]["turbo"]["options"]], [(T_NONE, ["ks_t", "ks_x"]), (T_RX7, ["ks_a"])])
        self.assertEqual(r.json["slots"]["backfire"]["options"][2],
                         {"key": B_CLASSIC, "event": BE + "backfire_classic", "bank": BACKFIRE_BANK, "optional": 8, "cars": ["ks_a"]})
        self.assertEqual([set(o) for o in r.json["slots"]["turbo"]["options"]], [OPTION_KEYS, OPTION_KEYS])
        self.assertEqual((r.json["slots"]["turbo"]["own"], r.json["slots"]["turbo"]["selected"]), (T_NONE, None))
        self.assertEqual((r.json["slots"]["backfire"]["own"], r.json["slots"]["backfire"]["selected"]), (B_A, None))
        self.assertEqual(r.json, dict(tune.sound_choices(self.work, "ks_x"), car="ks_x", tune=None))

    def test_a_car_without_an_entry_of_a_slot_has_no_own_sound_there(self):
        r = self.sounds("?car=ks_b")
        self.assertEqual((r.status, r.json["car"], r.json["slots"]["turbo"]["own"], r.json["slots"]["backfire"]["own"]), (200, "ks_b", None, B_B))

    def test_the_saved_choice_is_selected_and_a_choice_that_is_no_option_any_more_is_missing(self):
        self.make_tune(None, {tune.SOUND_KEY: {"turbo": T_RX7, "backfire": BE + "backfire_gone"}})
        r = self.sounds()
        self.assertEqual((r.json["slots"]["turbo"]["selected"], r.json["slots"]["backfire"]["selected"]), (T_RX7, None))
        self.assertEqual(r.json["missing"], [{"slot": "backfire", "key": BE + "backfire_gone"}])

    def test_sounds_echoes_the_tune_and_reads_its_own_state(self):
        self.make_tune("ax01", {"name_suffix": "_A", tune.SOUND_KEY: {"backfire": B_B}})
        r = self.sounds("?tune=ax01")
        self.assertEqual((r.status, r.json["tune"], r.json["slots"]["backfire"]["selected"]), (200, "ax01", B_B))
        r = self.sounds("?tune=draft")
        self.assertEqual((r.json["tune"], r.json["slots"]["backfire"]["selected"]), ("draft", None))
        self.assertIsNone(self.sounds().json["slots"]["backfire"]["selected"])
        self.make_tune(tune.DRAFT, {tune.SOUND_KEY: {"turbo": T_RX7}})
        self.assertEqual(self.sounds("?tune=draft").json["slots"]["turbo"]["selected"], T_RX7)

    def test_a_car_whose_actor_cannot_be_read_is_skipped_and_reported(self):
        self.remove_actor("ks_t")
        r = self.sounds()
        self.assertEqual((r.status, [s["car"] for s in r.json["skipped"]], set(r.json["skipped"][0])), (200, ["ks_t"], {"car", "reason"}))
        self.assertIsInstance(r.json["skipped"][0]["reason"], str)
        self.assertEqual(r.json["slots"]["turbo"]["options"][0]["cars"], ["ks_x"])

    def test_sounds_needs_the_base_car(self):
        r = self.sounds("?car=ks_y")
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertEqual(self.sounds("?car=ks_y&tune=draft").status, 409)

    def test_sounds_with_a_damaged_choice_is_400(self):
        self.make_tune(None, {tune.SOUND_KEY: 5})
        r = self.sounds()
        self.assertEqual((r.status, r.json), (400, {"error": "damaged sound choice in the saved state"}))

    def test_sounds_of_a_car_whose_own_actor_cannot_be_read_is_400(self):
        self.remove_actor("ks_x")
        r = self.sounds()
        self.assertEqual(r.status, 400)
        self.assertIn("error", r.json)

    def test_sounds_are_read_under_state_lock(self):
        held, real = [], tune.sound_choices

        def spy(*args, **kw):
            held.append(ts.STATE_LOCK.locked())
            return real(*args, **kw)
        self.patch(tune, "sound_choices", spy)
        self.sounds()
        self.assertEqual(held, [True])

    def test_sounds_reads_change_no_file(self):
        self.sounds()
        self.sounds("?tune=draft")
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))


class TestSoundSetRoute(SoundCase):
    def test_sound_set_chooses_the_sound_of_the_default_tune_and_answers_like_the_get(self):
        r = self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7})
        self.assertEqual((r.status, set(r.json)), (200, SOUND_KEYS))
        self.assertEqual((r.json["slots"]["turbo"]["selected"], r.json["slots"]["backfire"]["selected"], r.json["missing"]), (T_RX7, None, []))
        self.assertEqual((r.json["car"], r.json["tune"]), ("ks_x", None))
        self.assertEqual(r.json, self.sounds().json)
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"turbo": T_RX7}})

    def test_sound_set_keeps_the_other_slot_and_the_other_values_of_the_state(self):
        self.write(self.state_file(), {"limiter": 8000})
        self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7})
        r = self.post("/api/sound_set", {"slot": "backfire", "key": B_CLASSIC})
        self.assertEqual((r.status, r.json["slots"]["turbo"]["selected"], r.json["slots"]["backfire"]["selected"]), (200, T_RX7, B_CLASSIC))
        self.assertEqual(self.saved_state(), {"limiter": 8000, tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_CLASSIC}})
        r = self.post("/api/sound_set", {"slot": "backfire", "key": B_B})
        self.assertEqual(self.saved_state(), {"limiter": 8000, tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}})

    def test_the_own_sound_of_the_car_removes_the_choice(self):
        self.write(self.state_file(), {"limiter": 8000, tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}})
        r = self.post("/api/sound_set", {"slot": "turbo", "key": T_NONE})
        self.assertEqual((r.status, r.json["slots"]["turbo"]["selected"], r.json["slots"]["turbo"]["own"]), (200, None, T_NONE))
        self.assertEqual(self.saved_state(), {"limiter": 8000, tune.SOUND_KEY: {"backfire": B_B}})
        self.post("/api/sound_set", {"slot": "backfire", "key": B_A})
        self.assertEqual(self.saved_state(), {"limiter": 8000})

    def test_key_null_removes_the_choice(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"turbo": T_RX7}})
        r = self.post("/api/sound_set", {"slot": "turbo", "key": None})
        self.assertEqual((r.status, r.json["slots"]["turbo"]["selected"]), (200, None))
        self.assertEqual(self.saved_state(), {})
        self.assertEqual(self.post("/api/sound_set", {"slot": "turbo", "key": None}).status, 200)

    def test_sound_set_of_a_modded_car_changes_only_its_state(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        r = self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7, "tune": "ax01"})
        self.assertEqual((r.status, r.json["tune"], r.json["slots"]["turbo"]["selected"]), (200, "ax01", T_RX7))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", tune.SOUND_KEY: {"turbo": T_RX7}})
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))
        self.assertEqual(self.sounds("?tune=ax01").json, r.json)

    def test_sound_set_of_the_draft_needs_no_modded_car(self):
        r = self.post("/api/sound_set", {"slot": "backfire", "key": B_B, "tune": "draft"})
        self.assertEqual((r.status, r.json["tune"]), (200, "draft"))
        self.assertEqual(self.tune_state("draft"), {tune.SOUND_KEY: {"backfire": B_B}})
        self.assertEqual(self.tune_ids(), [])
        self.assertFalse(os.path.exists(self.state_file()))

    def test_sound_set_of_another_car_uses_that_cars_own_sound(self):
        r = self.post("/api/sound_set", {"car": "ks_a", "slot": "turbo", "key": T_RX7})
        self.assertEqual((r.status, r.json["car"], r.json["slots"]["turbo"]["selected"]), (200, "ks_a", None))
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_a")))

    def test_sound_set_with_a_slot_or_key_of_the_wrong_kind_is_400_and_writes_nothing(self):
        text = "need slot (text) and key (text or null)"
        for body in ({}, {"key": T_RX7}, {"slot": None, "key": T_RX7}, {"slot": 5, "key": T_RX7}, {"slot": ["turbo"], "key": T_RX7},
                     {"slot": "", "key": T_RX7}, {"slot": "  ", "key": T_RX7}, {"slot": "turbo", "key": 5}, {"slot": "turbo", "key": ["x"]},
                     {"slot": "turbo", "key": {"a": 1}}, {"slot": "turbo", "key": True}):
            with self.subTest(body):
                r = self.post("/api/sound_set", body)
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_sound_set_with_a_refused_slot_or_key_is_400_with_the_message_and_changes_nothing(self):
        self.write(self.state_file(), {"limiter": 8000, tune.SOUND_KEY: {"turbo": T_RX7}})
        for body, text in (({"slot": "horn", "key": T_RX7}, "unknown sound slot 'horn', use one of: turbo, backfire"),
                           ({"slot": "Turbo", "key": T_RX7}, "unknown sound slot 'Turbo', use one of: turbo, backfire"),
                           ({"slot": "turbo", "key": TE + "turbo_gone"}, "unknown turbo sound %sturbo_gone, sounds lists the sounds of the game cars" % TE),
                           ({"slot": "turbo", "key": B_B}, "unknown turbo sound %s, sounds lists the sounds of the game cars" % B_B),
                           ({"slot": "backfire", "key": ""}, "unknown backfire sound , sounds lists the sounds of the game cars")):
            with self.subTest(body):
                r = self.post("/api/sound_set", body)
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual(self.saved_state(), {"limiter": 8000, tune.SOUND_KEY: {"turbo": T_RX7}})

    def test_sound_set_with_a_damaged_saved_choice_is_400_and_changes_nothing(self):
        self.write(self.state_file(), {tune.SOUND_KEY: 5})
        r = self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7})
        self.assertEqual((r.status, r.json), (400, {"error": "damaged sound choice in the saved state"}))
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: 5})

    def test_sound_set_without_a_base_is_409_and_writes_nothing(self):
        for tune_id in (None, "draft"):
            with self.subTest(tune_id):
                r = self.post("/api/sound_set", {"car": "ks_y", "slot": "turbo", "key": T_RX7, "tune": tune_id})
                self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_y")))

    def test_sound_set_with_an_unknown_modded_car_is_400(self):
        r = self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7, "tune": "nope"})
        self.assertEqual((r.status, r.json), (400, {"error": "unknown modded car nope of ks_x"}))

    def test_a_car_that_is_not_text_is_400(self):
        r = self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7, "car": 5})
        self.assertEqual((r.status, r.json), (400, {"error": "car must be text"}))


class TestSoundResetRoute(SoundCase):
    def test_sound_reset_without_a_slot_removes_every_choice_and_answers_like_the_get(self):
        self.write(self.state_file(), {"limiter": 8000, tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}})
        r = self.post("/api/sound_reset", {})
        self.assertEqual((r.status, set(r.json)), (200, SOUND_KEYS))
        self.assertEqual((r.json["slots"]["turbo"]["selected"], r.json["slots"]["backfire"]["selected"]), (None, None))
        self.assertEqual(r.json, self.sounds().json)
        self.assertEqual(self.saved_state(), {"limiter": 8000})

    def test_sound_reset_with_a_slot_removes_that_slot_only(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}})
        r = self.post("/api/sound_reset", {"slot": "turbo"})
        self.assertEqual((r.status, r.json["slots"]["turbo"]["selected"], r.json["slots"]["backfire"]["selected"]), (200, None, B_B))
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"backfire": B_B}})
        self.assertEqual(self.post("/api/sound_reset", {"slot": "turbo", "tune": None}).status, 200)
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"backfire": B_B}})
        self.post("/api/sound_reset", {"slot": "backfire"})
        self.assertEqual(self.saved_state(), {})

    def test_sound_reset_without_a_choice_changes_nothing(self):
        r = self.post("/api/sound_reset")
        self.assertEqual((r.status, set(r.json), r.json["slots"]["turbo"]["selected"]), (200, SOUND_KEYS, None))
        self.assertEqual(self.post("/api/sound_reset", {"slot": "backfire"}).status, 200)
        self.assertFalse(os.path.exists(self.state_file()))

    def test_sound_reset_of_a_modded_car_and_of_the_draft(self):
        self.make_tune("ax01", {"name_suffix": "_A", tune.SOUND_KEY: {"turbo": T_RX7}})
        self.make_tune(tune.DRAFT, {tune.SOUND_KEY: {"backfire": B_B}, "limiter": 8000})
        self.make_tune(None, {tune.SOUND_KEY: {"turbo": T_RX7}})
        r = self.post("/api/sound_reset", {"tune": "ax01"})
        self.assertEqual((r.status, r.json["tune"], r.json["slots"]["turbo"]["selected"]), (200, "ax01", None))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A"})
        self.assertEqual(self.post("/api/sound_reset", {"tune": "draft"}).status, 200)
        self.assertEqual(self.tune_state("draft"), {"limiter": 8000})
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"turbo": T_RX7}})

    def test_sound_reset_with_a_slot_that_does_not_exist_or_is_not_text_is_400(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"turbo": T_RX7}})
        for body, text in (({"slot": "horn"}, "unknown sound slot 'horn', use one of: turbo, backfire"),
                           ({"slot": ""}, "unknown sound slot '', use one of: turbo, backfire"),
                           ({"slot": 5}, "slot must be text"), ({"slot": ["turbo"]}, "slot must be text")):
            with self.subTest(body):
                r = self.post("/api/sound_reset", body)
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"turbo": T_RX7}})

    def test_sound_reset_without_a_base_is_409(self):
        r = self.post("/api/sound_reset", {"car": "ks_y"})
        self.assertEqual((r.status, r.json), (409, {"error": "base car missing, run init"}))

    def test_sound_reset_without_a_slot_removes_a_damaged_choice(self):
        self.write(self.state_file(), {tune.SOUND_KEY: 5})
        r = self.post("/api/sound_reset", {})
        self.assertEqual((r.status, r.json["slots"]["turbo"]["selected"]), (200, None))
        self.assertEqual(self.saved_state(), {})


class TestSoundRoutesShared(SoundCase):
    def test_the_sound_writes_happen_under_state_lock(self):
        held = []
        for name in ("set_sound", "reset_sounds"):
            def spy(*args, _name=name, _real=getattr(tune, name), **kw):
                held.append((_name, ts.STATE_LOCK.locked()))
                return _real(*args, **kw)
            self.patch(tune, name, spy)
        self.assertEqual(self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7}).status, 200)
        self.assertEqual(self.post("/api/sound_reset", {}).status, 200)
        self.assertEqual(held, [("set_sound", True), ("reset_sounds", True)])

    def test_both_writes_are_409_while_a_job_runs_and_change_nothing(self):
        self.make_tune("ax01", {"name_suffix": "_A", tune.SOUND_KEY: {"turbo": T_RX7}})
        self.write(self.state_file(), {tune.SOUND_KEY: {"backfire": B_B}})
        with open(self.state_file(), "rb") as f:
            before = f.read()
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        self.entered.wait(5)
        for path, body in (("/api/sound_set", {"slot": "turbo", "key": T_RX7}), ("/api/sound_reset", {})):
            for tune_id in (None, "ax01", "draft"):
                with self.subTest(path, tune=tune_id):
                    r = self.post(path, dict(body, tune=tune_id))
                    self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        r = self.post("/api/sound_set", {"slot": 5})
        self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        with open(self.state_file(), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", tune.SOUND_KEY: {"turbo": T_RX7}})
        self.assertFalse(os.path.exists(tune.state_path(self.work, "ks_x", "draft")))
        self.assertEqual(self.sounds().status, 200)
        self.finish_held_job()
        self.assertEqual(self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7}).status, 200)

    def test_the_routes_check_the_host_the_post_headers_and_the_method(self):
        self.assertEqual(self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7}, headers={"X-Tuner": None}).status, 403)
        r = self.post("/api/sound_reset", {}, headers={"Content-Type": "text/plain"})
        self.assertEqual((r.status, r.json), (415, {"error": "Content-Type must be application/json"}))
        self.assertEqual(self.get("/api/sounds", host="evil.example").status, 403)
        self.assertEqual(self.post("/api/sound_set", {"slot": "turbo", "key": T_RX7}, host="evil.example").status, 403)
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertEqual(self.get("/api/sound_set").status, 404)
        self.assertEqual(self.get("/api/sound_reset").status, 404)
        self.assertEqual(self.post("/api/sounds", {}).status, 404)
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method):
                r = self.request(method, "/api/sounds")
                self.assertEqual((r.status, r.headers.get("Allow")), (405, "GET, POST"))

    def test_the_statuses_of_the_sound_routes_are_200_not_202(self):
        self.assertTrue({"/api/sounds", "/api/sound_set", "/api/sound_reset"}.isdisjoint(ts.ACCEPTED))
        self.assertTrue({"/api/sounds"}.isdisjoint(ts.QUERY_ROUTES))

    def test_the_sound_routes_take_the_car_and_the_tune_like_every_route(self):
        self.assertEqual(self.sounds("?car=nope").status, 400)
        self.assertEqual(self.sounds("?tune=nope").json, {"error": "unknown modded car nope of ks_x"})
        self.assertEqual(self.post("/api/sound_reset", {"car": "nope"}).status, 400)


class TestKitLinkedSound(SoundCase):
    def test_choosing_a_donor_with_a_turbo_sound_sets_the_turbo_sound_to_the_donors(self):
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual((r.status, set(r.json)), (200, {"result", "turbo", "sounds", "sound_link"}))
        self.assertEqual(r.json["sound_link"], {"slot": "turbo", "key": T_RX7})
        self.assertEqual((set(r.json["sounds"]), r.json["sounds"]["slots"]["turbo"]["selected"], r.json["sounds"]["slots"]["backfire"]["selected"]),
                         (SOUND_KEYS, T_RX7, None))
        self.assertEqual(r.json["sounds"], self.sounds().json)
        self.assertEqual(self.saved_state(), dict(self.kit("ks_a"), **{tune.SOUND_KEY: {"turbo": T_RX7}}))

    def test_the_old_answer_keys_of_turbo_set_stay_as_they_were(self):
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual(r.json["result"], {"donor": "ks_a", "count": 1, "kind": "single turbo", "boost": [0.9], "boost_ref": None})
        self.assertEqual((r.json["turbo"], set(r.json["turbo"])), (self.turbo().json, TURBO_KEYS))
        self.assertEqual((r.json["turbo"]["donor"], r.json["turbo"]["picked"]), ("ks_a", SINGLE))

    def test_a_donor_without_a_turbo_entry_leaves_the_sound_alone(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}})
        r = self.post("/api/turbo_set", {"donor": "ks_b"})
        self.assertEqual((r.status, r.json["sounds"], r.json["sound_link"]), (200, None, None))
        self.assertEqual(r.json["result"], {"donor": "ks_b", "count": 2, "kind": "twin turbo", "boost": [0.7, 0.7], "boost_ref": None})
        self.assertEqual(r.json["turbo"]["donor"], "ks_b")
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}, tune.TURBO_KEY: {"donor": "ks_b"}})

    def test_a_donor_whose_sound_is_the_cars_own_stores_no_sound_choice(self):
        r = self.post("/api/turbo_set", {"donor": "ks_t"})
        self.assertEqual((r.status, r.json["sound_link"]), (200, {"slot": "turbo", "key": T_NONE}))
        self.assertEqual((r.json["sounds"]["slots"]["turbo"]["selected"], r.json["sounds"]["slots"]["turbo"]["own"]), (None, T_NONE))
        self.assertEqual(self.saved_state(), self.kit("ks_t"))

    def test_a_donor_whose_sound_is_the_cars_own_removes_an_earlier_choice(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"turbo": T_RX7, "backfire": B_B}})
        r = self.post("/api/turbo_set", {"donor": "ks_t"})
        self.assertEqual(r.json["sound_link"], {"slot": "turbo", "key": T_NONE})
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"backfire": B_B}, tune.TURBO_KEY: {"donor": "ks_t"}})

    def test_another_donor_replaces_the_turbo_sound_and_the_backfire_sound_is_never_touched(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"backfire": B_B}})
        self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual(self.saved_state()[tune.SOUND_KEY], {"turbo": T_RX7, "backfire": B_B})
        self.post("/api/turbo_set", {"donor": "ks_t"})
        self.assertEqual(self.saved_state()[tune.SOUND_KEY], {"backfire": B_B})

    def test_the_link_of_a_modded_car_and_of_the_draft_changes_only_their_state(self):
        self.make_tune("ax01", {"name_suffix": "_A"})
        r = self.post("/api/turbo_set", {"donor": "ks_a", "tune": "ax01"})
        self.assertEqual((r.status, r.json["sounds"]["tune"], r.json["sounds"]["slots"]["turbo"]["selected"]), (200, "ax01", T_RX7))
        self.assertEqual(self.tune_state("ax01"), dict({"name_suffix": "_A", tune.SOUND_KEY: {"turbo": T_RX7}}, **self.kit("ks_a")))
        r = self.post("/api/turbo_set", {"donor": "ks_a", "tune": "draft"})
        self.assertEqual((r.json["sounds"]["tune"], self.tune_state("draft")), ("draft", dict({tune.SOUND_KEY: {"turbo": T_RX7}}, **self.kit("ks_a"))))
        self.assertFalse(os.path.exists(self.state_file()))

    def test_a_problem_of_the_sound_step_keeps_the_donor_and_is_reported(self):
        def broken(*args, **kw):
            raise ValueError("sound step failed")
        self.patch(tune, "set_sound", broken)
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual((r.status, set(r.json), r.json["sounds"], r.json["sound_link"]),
                         (200, {"result", "turbo", "sounds", "sound_link"}, None, {"error": "sound step failed"}))
        self.assertEqual((r.json["result"]["donor"], r.json["turbo"]["donor"]), ("ks_a", "ks_a"))
        self.assertEqual(self.saved_state(), self.kit("ks_a"))

    def test_a_donor_whose_actor_cannot_be_read_keeps_the_donor_and_is_reported(self):
        self.remove_actor("ks_a")
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual((r.status, r.json["sounds"], set(r.json["sound_link"])), (200, None, {"error"}))
        self.assertIsInstance(r.json["sound_link"]["error"], str)
        self.assertEqual(r.json["turbo"]["donor"], "ks_a")
        self.assertEqual(self.saved_state(), self.kit("ks_a"))

    def test_a_damaged_saved_sound_choice_keeps_the_donor_and_is_reported(self):
        self.write(self.state_file(), {tune.SOUND_KEY: 5})
        r = self.post("/api/turbo_set", {"donor": "ks_a"})
        self.assertEqual((r.status, r.json["sounds"], r.json["sound_link"]), (200, None, {"error": "damaged sound choice in the saved state"}))
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: 5, tune.TURBO_KEY: {"donor": "ks_a"}})

    def test_a_refused_donor_is_400_and_the_sound_is_not_touched(self):
        self.write(self.state_file(), {tune.SOUND_KEY: {"turbo": T_NONE}})
        for body in ({"donor": "ks_zz"}, {"donor": "ks_x"}, {"donor": 5}, {"donor": "ks_a", "car": "ks_t"}):
            with self.subTest(body):
                self.assertEqual(self.post("/api/turbo_set", body).status, 400)
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"turbo": T_NONE}})

    def test_turbo_reset_leaves_the_sound_choice_untouched(self):
        self.write(self.state_file(), dict(self.kit("ks_a"), **{tune.SOUND_KEY: {"turbo": T_RX7}}))
        r = self.post("/api/turbo_reset", {})
        self.assertEqual((r.status, set(r.json), r.json["removed"]), (200, {"removed", "turbo"}, True))
        self.assertEqual(self.saved_state(), {tune.SOUND_KEY: {"turbo": T_RX7}})

    def test_the_link_happens_under_state_lock(self):
        held, real = [], tune.set_sound

        def spy(*args, **kw):
            held.append(ts.STATE_LOCK.locked())
            return real(*args, **kw)
        self.patch(tune, "set_sound", spy)
        self.assertEqual(self.post("/api/turbo_set", {"donor": "ks_a"}).status, 200)
        self.assertEqual(held, [True])


# -------------------------------------------------------------------------------------------------- versions of a modded car
class TestVersionRoutes(SoundCase):
    """The optional "version" of the car-bound routes, /api/version_add, /api/version_rename and the versions and mod_paths of /api/state:
    ax01 is a modded car of ks_x with the base state {limiter 8000, suffix _A} and the version v01 Heavy {limiter 9000}."""

    def setUp(self):
        super().setUp()
        self.make_tune("ax01", {"name_suffix": "_A", "limiter": 8000})
        self.vid = tune.add_version(self.work, "ks_x", "Heavy", "ax01")
        tune.save_version_state(self.work, "ks_x", {"limiter": 9000}, self.vid, "ax01")

    def version_state(self, version=None, tune_id="ax01"):
        return tune.read_version_state(self.work, "ks_x", version or self.vid, tune_id)

    def test_state_lists_the_versions_and_where_the_modded_car_lives(self):
        r = self.get("/api/state?tune=ax01")
        self.assertEqual(r.json["versions"], [{"id": "v01", "name": "Heavy", "locked": False, "built": None}])
        self.assertEqual(r.json["mod_paths"], {"package": os.path.join(self.mods, "ax01.kspkg"),
                                               "versions_folder": tune.version_dir(self.work, "ks_x", "ax01"),
                                               "state": tune.state_path(self.work, "ks_x", "ax01")})
        self.assertEqual(os.path.basename(r.json["mod_paths"]["versions_folder"]), "versions")
        self.assertFalse(os.path.exists(r.json["mod_paths"]["package"]))

    def test_state_has_no_versions_for_the_base_car_and_the_draft(self):
        for query in ("", "?tune=draft"):
            with self.subTest(query):
                r = self.get("/api/state" + query)
                self.assertEqual((r.json["versions"], r.json["mod_paths"]), ([], None))

    def test_a_modded_car_without_versions_has_an_empty_list_and_its_paths(self):
        self.make_tune("ax02", {"name_suffix": "_B"})
        r = self.get("/api/state?tune=ax02")
        self.assertEqual(r.json["versions"], [])
        self.assertEqual(r.json["mod_paths"]["package"], os.path.join(self.mods, "ax02.kspkg"))

    def test_settings_of_a_version_read_its_state_and_the_base_stays_as_it_is(self):
        rows = {r["id"]: r for r in self.get("/api/settings?tune=ax01&version=v01").json}
        self.assertEqual((rows["limiter"]["value"], rows["limiter"]["changed"]), (9000, True))
        self.assertEqual(rows["name_suffix"]["value"], "_A")
        base = {r["id"]: r for r in self.get("/api/settings?tune=ax01").json}
        self.assertEqual(base["limiter"]["value"], 8000)
        self.assertEqual({r["id"]: r["value"] for r in self.get("/api/settings?tune=ax01&version=").json}, {i: r["value"] for i, r in base.items()})

    def test_set_with_a_version_writes_only_the_state_of_the_version(self):
        r = self.post("/api/set", {"tune": "ax01", "version": "v01", "id": "limiter", "value": "9500"})
        self.assertEqual((r.status, r.json["row"]["value"]), (200, 9500))
        self.assertEqual(self.version_state(), {"limiter": 9500})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})
        self.assertFalse(os.path.exists(self.state_file()))

    def test_set_with_the_query_parameter_works_too(self):
        r = self.post("/api/set?version=v01", {"tune": "ax01", "id": "limiter", "value": "9600"})
        self.assertEqual((r.status, self.version_state()), (200, {"limiter": 9600}))

    def test_unset_with_a_version_removes_the_value_of_the_version_only(self):
        r = self.post("/api/unset", {"tune": "ax01", "version": "v01", "id": "limiter"})
        self.assertEqual((r.status, r.json["row"]["changed"]), (200, False))
        self.assertEqual(self.version_state(), {})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})

    def test_a_meta_setting_cannot_be_set_or_unset_on_a_version(self):
        for route, body in (("/api/set", {"id": "name_suffix", "value": "_Z"}), ("/api/unset", {"id": "name_suffix"})):
            with self.subTest(route):
                r = self.post(route, dict(body, tune="ax01", version="v01"))
                self.assertEqual((r.status, r.json), (400, {"error": "name_suffix is shared by all versions, set it on the base"}))
        self.assertEqual((self.version_state(), self.tune_state("ax01")), ({"limiter": 9000}, {"name_suffix": "_A", "limiter": 8000}))

    def share_aids_off(self):
        next(s for s in self.cat["settings"] if s["id"] == "aids_off")["shared"] = True

    def test_the_rows_carry_the_shared_flag_only_for_the_settings_marked_shared(self):
        self.share_aids_off()
        for query in ("?tune=ax01&version=v01", "?tune=ax01"):
            rows = {r["id"]: r for r in self.get("/api/settings" + query).json}
            self.assertEqual({i for i, r in rows.items() if r.get("shared")}, {"aids_off"}, query)
            self.assertEqual([r["shared"] for r in rows.values() if "shared" in r], [True], query)

    def test_a_shared_setting_cannot_be_set_or_unset_on_a_version_but_can_on_the_base(self):
        self.share_aids_off()
        for route, body in (("/api/set", {"id": "aids_off", "value": True}), ("/api/unset", {"id": "aids_off"})):
            with self.subTest(route):
                r = self.post(route, dict(body, tune="ax01", version="v01"))
                self.assertEqual((r.status, r.json), (400, {"error": "aids_off is shared by all versions, set it on the base"}))
        self.assertEqual((self.version_state(), self.tune_state("ax01")), ({"limiter": 9000}, {"name_suffix": "_A", "limiter": 8000}))
        r = self.post("/api/set", {"tune": "ax01", "id": "aids_off", "value": True})
        self.assertEqual((r.status, r.json["row"]["shared"]), (200, True))
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000, "aids_off": True})
        self.assertEqual(self.post("/api/unset", {"tune": "ax01", "id": "aids_off"}).status, 200)

    def test_reset_all_with_a_version_clears_only_that_version(self):
        tune.save_version_state(self.work, "ks_x", {"limiter": 9000, "aids_off": True}, "v01", "ax01")
        other = tune.add_version(self.work, "ks_x", "Light", "ax01", "v01")
        r = self.post("/api/reset_all", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, r.json), (200, {"ok": True}))
        self.assertEqual(self.version_state(), {})
        self.assertEqual(self.version_state(other), {"limiter": 9000, "aids_off": True})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})

    def test_a_version_without_a_modded_car_or_an_unknown_version_is_400(self):
        for route, method, body in (("/api/settings", "GET", None), ("/api/garage", "GET", None), ("/api/turbo", "GET", None),
                                    ("/api/sounds", "GET", None), ("/api/set", "POST", {"id": "limiter", "value": "8000"}),
                                    ("/api/unset", "POST", {"id": "limiter"}), ("/api/reset_all", "POST", {}),
                                    ("/api/garage_set", "POST", {"choice": SETS_CHOICE}), ("/api/garage_reset", "POST", {}),
                                    ("/api/turbo_set", "POST", {"donor": "ks_a"}), ("/api/turbo_reset", "POST", {}),
                                    ("/api/sound_set", "POST", {"slot": "turbo", "key": T_RX7}), ("/api/sound_reset", "POST", {})):
            for tune_id, version, text in (("draft", "v01", "a version needs a modded car"), (None, "v01", "a version needs a modded car"),
                                           ("ax01", "v02", "unknown version v02 of ax01"), ("ax01", "../x", "unknown version ../x of ax01")):
                with self.subTest(route=route, tune=tune_id, version=version):
                    if method == "GET":
                        query = "?version=%s" % urllib.parse.quote(version) + ("&tune=%s" % tune_id if tune_id else "")
                        r = self.get(route + query)
                    else:
                        r = self.post(route, dict(body, version=version, **({"tune": tune_id} if tune_id else {})))
                    self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual((self.version_state(), self.tune_state("ax01")), ({"limiter": 9000}, {"name_suffix": "_A", "limiter": 8000}))
        self.assertFalse(os.path.exists(self.state_file()))
        self.assertEqual(self.tune_state("draft"), {})

    def test_a_version_that_is_not_text_is_400(self):
        r = self.post("/api/set", {"tune": "ax01", "version": 1, "id": "limiter", "value": "8000"})
        self.assertEqual((r.status, r.json), (400, {"error": "version must be text"}))

    def test_turbo_set_and_reset_with_a_version_use_the_state_of_the_version(self):
        r = self.post("/api/turbo_set", {"tune": "ax01", "version": "v01", "donor": "ks_b"})
        self.assertEqual((r.status, r.json["turbo"]["donor"]), (200, "ks_b"))
        self.assertEqual(self.version_state(), {"limiter": 9000, tune.TURBO_KEY: {"donor": "ks_b"}})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})
        self.assertEqual(self.turbo("?tune=ax01&version=v01").json["donor"], "ks_b")
        self.assertIsNone(self.turbo("?tune=ax01").json["donor"])
        r = self.post("/api/turbo_reset", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, r.json["removed"], self.version_state()), (200, True, {"limiter": 9000}))

    def test_sound_set_and_reset_with_a_version_use_the_state_of_the_version(self):
        r = self.post("/api/sound_set", {"tune": "ax01", "version": "v01", "slot": "turbo", "key": T_RX7})
        self.assertEqual((r.status, r.json["slots"]["turbo"]["selected"]), (200, T_RX7))
        self.assertEqual(self.version_state(), {"limiter": 9000, tune.SOUND_KEY: {"turbo": T_RX7}})
        self.assertEqual(self.tune_state("ax01"), {"name_suffix": "_A", "limiter": 8000})
        self.assertEqual(self.sounds("?tune=ax01&version=v01").json["slots"]["turbo"]["selected"], T_RX7)
        self.assertIsNone(self.sounds("?tune=ax01").json["slots"]["turbo"]["selected"])
        r = self.post("/api/sound_reset", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, self.version_state()), (200, {"limiter": 9000}))

    def test_version_add_copies_the_base_without_the_meta_settings_and_answers_the_id(self):
        r = self.post("/api/version_add", {"tune": "ax01", "name": "Light"})
        self.assertEqual((r.status, r.json), (200, {"id": "v02"}))
        self.assertEqual(self.version_state("v02"), {"limiter": 8000})
        self.assertEqual([v["name"] for v in self.get("/api/state?tune=ax01").json["versions"]], ["Heavy", "Light"])

    def test_version_add_from_a_version_copies_that_version(self):
        r = self.post("/api/version_add", {"tune": "ax01", "name": "Heavier", "from": "v01"})
        self.assertEqual((r.status, r.json, self.version_state("v02")), (200, {"id": "v02"}, {"limiter": 9000}))

    def test_version_add_errors_are_400_and_add_nothing(self):
        for body, text in (({"tune": "ax01"}, "need name (text)"), ({"tune": "ax01", "name": 5}, "need name (text)"),
                           ({"tune": "ax01", "name": "  "}, "a version name must be 1 to 40 characters without control characters"),
                           ({"tune": "ax01", "name": "heavy"}, "version name heavy is already used by v01"),
                           ({"tune": "ax01", "name": "X", "from": "v09"}, "ks_x has no version v09 of ax01"),
                           ({"tune": "ax01", "name": "X", "from": 3}, "from must be text"),
                           ({"tune": "draft", "name": "X"}, "a version needs a modded car"), ({"name": "X"}, "a version needs a modded car")):
            with self.subTest(body):
                r = self.post("/api/version_add", body)
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual([v["id"] for v in tune.list_versions(self.work, "ks_x", "ax01")], ["v01"])

    def test_version_rename_renames_and_keeps_the_id_and_the_state(self):
        r = self.post("/api/version_rename", {"tune": "ax01", "version": "v01", "name": "Very heavy"})
        self.assertEqual((r.status, r.json), (200, {"id": "v01", "name": "Very heavy"}))
        self.assertEqual(self.get("/api/state?tune=ax01").json["versions"], [{"id": "v01", "name": "Very heavy", "locked": False, "built": None}])
        self.assertEqual(self.version_state(), {"limiter": 9000})
        self.assertEqual(self.post("/api/version_rename", {"tune": "ax01", "version": "v01", "name": "heavy"}).status, 200)

    def test_version_rename_errors_are_400(self):
        self.post("/api/version_add", {"tune": "ax01", "name": "Light"})
        for body, text in (({"tune": "ax01", "name": "X"}, "need version (text)"), ({"tune": "ax01", "version": "v01"}, "need name (text)"),
                           ({"tune": "ax01", "version": "v01", "name": "light"}, "version name light is already used by v02"),
                           ({"tune": "ax01", "version": "v07", "name": "X"}, "ks_x has no version v07 of ax01"),
                           ({"tune": "draft", "version": "v01", "name": "X"}, "a version needs a modded car")):
            with self.subTest(body):
                r = self.post("/api/version_rename", body)
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual([v["name"] for v in tune.list_versions(self.work, "ks_x", "ax01")], ["Heavy", "Light"])

    def keep_build(self, version=None, tune_id="ax01", time="2026-11-23T12:40:24Z"):
        folder = os.path.join(tune.version_dir(self.work, "ks_x", tune_id, version or self.vid), "build")
        os.makedirs(os.path.join(folder, "files", "data"))
        with open(os.path.join(folder, "files", "data", "CarData_v01.car"), "wb") as f:
            f.write(b"car")
        tune.save_json(os.path.join(folder, "build.json"), {"tune": tune_id, "preset": "p", "parts": [], "files": ["data/CarData_v01.car"],
                                                            "time": time, "state": self.version_state(version, tune_id)})

    def test_version_lock_locks_a_version_with_a_matching_kept_build_and_unlock_frees_it(self):
        self.keep_build()
        r = self.post("/api/version_lock", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, r.json), (200, {"id": "v01", "name": "Heavy"}))
        self.assertEqual(self.get("/api/state?tune=ax01").json["versions"], [{"id": "v01", "name": "Heavy", "locked": True, "built": "2026-11-23T12:40:24Z"}])
        self.assertEqual(self.post("/api/version_lock", {"tune": "ax01", "version": "v01"}).status, 200)
        r = self.post("/api/version_unlock", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, r.json), (200, {"id": "v01", "name": "Heavy"}))
        self.assertEqual(self.get("/api/state?tune=ax01").json["versions"], [{"id": "v01", "name": "Heavy", "locked": False, "built": "2026-11-23T12:40:24Z"}])
        self.assertEqual(self.post("/api/version_unlock", {"tune": "ax01", "version": "v01"}).status, 200)
        self.assertEqual(self.post("/api/set", {"tune": "ax01", "version": "v01", "id": "limiter", "value": "9100"}).status, 200)

    def test_version_lock_without_a_kept_build_or_with_unbuilt_changes_is_400(self):
        r = self.post("/api/version_lock", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, r.json), (400, {"error": "version v01 (Heavy) has no kept build: Apply first, then lock it"}))
        self.keep_build()
        tune.save_version_state(self.work, "ks_x", {"limiter": 9100}, "v01", "ax01")
        r = self.post("/api/version_lock", {"tune": "ax01", "version": "v01"})
        self.assertEqual((r.status, r.json), (400, {"error": "version v01 (Heavy) has changes that are not built yet: Apply first, then lock it"}))
        self.assertFalse(self.get("/api/state?tune=ax01").json["versions"][0]["locked"])

    def test_version_lock_and_unlock_errors_are_400(self):
        for route in ("/api/version_lock", "/api/version_unlock"):
            for body, text in (({"tune": "ax01"}, "need version (text)"), ({"tune": "ax01", "version": 1}, "need version (text)"),
                               ({"tune": "ax01", "version": "v07"}, "ks_x has no version v07 of ax01"),
                               ({"tune": "draft", "version": "v01"}, "a version needs a modded car"),
                               ({"version": "v01"}, "a version needs a modded car")):
                with self.subTest(route=route, body=body):
                    r = self.post(route, body)
                    self.assertEqual((r.status, r.json), (400, {"error": text}))

    def test_version_lock_and_unlock_are_refused_while_a_job_runs(self):
        self.keep_build()
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "ax01"}).status, 202)
        for route in ("/api/version_lock", "/api/version_unlock"):
            with self.subTest(route):
                r = self.post(route, {"tune": "ax01", "version": "v01"})
                self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        self.finish_held_job()

    def test_version_lock_and_unlock_are_post_routes_with_the_header_check(self):
        for route in ("/api/version_lock", "/api/version_unlock"):
            with self.subTest(route):
                self.assertEqual(self.get(route).status, 404)
                r = self.post(route, {"tune": "ax01", "version": "v01"}, headers={"X-Tuner": None})
                self.assertEqual((r.status, r.json), (403, {"error": "missing header X-Tuner: 1"}))

    def assert_locked_refusals(self, routes, text="version v01 (Heavy) is locked; unlock it to change it"):
        before = self.version_state()
        for route, body in routes:
            with self.subTest(route):
                r = self.post(route, dict(body, tune="ax01", version="v01"))
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual(self.version_state(), before)

    def test_the_setting_routes_and_rename_answer_400_on_a_locked_version(self):
        self.keep_build()
        self.assertEqual(self.post("/api/version_lock", {"tune": "ax01", "version": "v01"}).status, 200)
        self.assert_locked_refusals((("/api/set", {"id": "limiter", "value": "9100"}), ("/api/unset", {"id": "limiter"}), ("/api/reset_all", {}),
                                     ("/api/turbo_set", {"donor": "ks_b"}), ("/api/sound_set", {"slot": "turbo", "key": T_RX7}),
                                     ("/api/version_rename", {"name": "Other"})))
        self.assertEqual(self.get("/api/state?tune=ax01").json["versions"][0]["name"], "Heavy")

    def test_the_reset_routes_answer_400_on_a_locked_version_that_has_something_to_reset(self):
        tune.save_version_state(self.work, "ks_x", {"limiter": 9000, tune.TURBO_KEY: {"donor": "ks_b"}, tune.SOUND_KEY: {"turbo": T_RX7}},
                                "v01", "ax01")
        self.keep_build()
        self.assertEqual(self.post("/api/version_lock", {"tune": "ax01", "version": "v01"}).status, 200)
        self.assert_locked_refusals((("/api/reset_all", {}), ("/api/turbo_reset", {}), ("/api/sound_reset", {}),
                                     ("/api/sound_reset", {"slot": "turbo"})))
        self.assertEqual(sorted(ts.VERSION_POST_ROUTES), sorted(["/api/set", "/api/unset", "/api/reset_all", "/api/garage_set", "/api/garage_reset",
                                                                  "/api/turbo_set", "/api/turbo_reset", "/api/sound_set", "/api/sound_reset"]))

    def test_there_is_no_route_that_deletes_a_version(self):
        self.assertEqual([r for r in list(ts.GET_ROUTES) + list(ts.POST_ROUTES) if "version" in r],
                         ["/api/version_add", "/api/version_rename", "/api/version_lock", "/api/version_unlock"])
        self.assertEqual(self.post("/api/version_delete", {"tune": "ax01", "version": "v01"}).status, 404)

    def test_version_writes_are_refused_while_a_job_runs(self):
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "ax01"}).status, 202)
        for route, body in (("/api/version_add", {"name": "X"}), ("/api/version_rename", {"version": "v01", "name": "X"}),
                            ("/api/set", {"version": "v01", "id": "limiter", "value": "8000"})):
            with self.subTest(route):
                r = self.post(route, dict(body, tune="ax01"))
                self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        self.finish_held_job()


# -------------------------------------------------------------------------------------------------- job lifecycle
class TestJobs(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_a_second_job_while_one_runs_is_409_for_init_and_apply(self):
        tune.save_state(self.work, "ks_x", {})
        self.hold_jobs()
        self.assertEqual(self.post("/api/init").status, 202)
        self.entered.wait(5)
        for path, body, text in (("/api/init", {}, "another job is running, wait until it has finished"),
                                 ("/api/apply", {}, "another job is running, wait until it has finished"),
                                 ("/api/apply", {"tune": "draft"}, "a job is running, wait until it has finished")):
            with self.subTest(path, body=body):
                r = self.post(path, body)
                self.assertEqual((r.status, r.json), (409, {"error": text}))
        self.assertEqual([c[0] for c in self.calls], ["init"])
        self.assertEqual([t["id"] for t in tune.list_tunes(self.work, "ks_x")], ["ax_x"])
        self.finish_held_job()

    def test_a_job_that_is_running_shows_in_the_state(self):
        self.hold_jobs()
        self.post("/api/apply", {"tune": "draft"})
        self.entered.wait(5)
        job = self.get("/api/state").json["job"]
        self.assertEqual(set(job), JOB_KEYS)
        self.assertEqual((job["kind"], job["state"], job["result"], job["error"]), ("apply", "running", None, None))
        self.assertEqual(job["log"], ["building ax_x, this takes a while ..."])
        self.finish_held_job()
        self.assertEqual(self.get("/api/state").json["job"]["state"], "done")

    def test_the_state_of_a_finished_job_is_kept_until_the_next_job(self):
        self.post("/api/init")
        done = self.wait_job()
        self.assertEqual(self.get("/api/state").json["job"], done)
        self.assertEqual(self.get("/api/state").json["job"], done)
        self.assertEqual(self.get("/api/state?car=ks_y").json["job"], done)

    def test_a_new_job_starts_with_an_empty_result_and_log(self):
        self.post("/api/init")
        self.wait_job()
        self.hold_jobs()
        self.entered.clear()
        self.post("/api/apply", {"tune": "draft"})
        job = ts.job_snapshot()
        self.assertEqual((job["kind"], job["state"], job["result"], job["error"]), ("apply", "running", None, None))
        self.assertNotIn("extracted the stock car", job["log"])
        self.finish_held_job()

    def test_a_failed_job_does_not_block_the_next_one(self):
        self.errors["init"] = ValueError("x")
        self.post("/api/init")
        self.assertEqual(self.wait_job()["state"], "error")
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)

    def test_the_game_check_is_not_used_by_init(self):
        self.game_up = True
        self.assertEqual(self.post("/api/init").status, 202)

    def test_set_is_refused_while_a_job_runs(self):
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        r = self.post("/api/set", {"id": "limiter", "value": "8000"})
        self.assertEqual(r.status, 409, r.json)

    def test_unset_is_refused_while_a_job_runs(self):
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        r = self.post("/api/unset", {"id": "limiter"})
        self.assertEqual(r.status, 409, r.json)

    def test_reset_all_is_refused_while_a_job_runs(self):
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        r = self.post("/api/reset_all")
        self.assertEqual(r.status, 409, r.json)


class TestJobFunctions(Env):
    def test_the_job_starts_idle(self):
        self.assertEqual(ts.job_snapshot(), {"kind": None, "state": "idle", "log": [], "result": None, "error": None})

    def test_claim_job_marks_the_job_running_and_clears_the_old_one(self):
        ts.JOB.update(kind="init", state="done", log=["old"], result={"x": 1}, error="old error")
        ts.claim_job("apply")
        self.assertEqual(ts.job_snapshot(), {"kind": "apply", "state": "running", "log": [], "result": None, "error": None})

    def test_a_second_claim_while_running_is_refused_and_keeps_the_first(self):
        ts.claim_job("init")
        ts.log_line("one")
        with self.assertRaises(ts.ApiError) as cm:
            ts.claim_job("apply")
        self.assertEqual((cm.exception.status, cm.exception.message), (409, "another job is running, wait until it has finished"))
        self.assertEqual((ts.job_snapshot()["kind"], ts.job_snapshot()["log"]), ("init", ["one"]))

    def test_a_claim_is_possible_after_done_and_after_error(self):
        for state in ("done", "error"):
            with self.subTest(state):
                ts.JOB.update(state=state)
                ts.claim_job("apply")
                self.assertEqual(ts.job_snapshot()["state"], "running")

    def test_finish_job_sets_state_result_and_error(self):
        ts.claim_job("init")
        ts.finish_job("done", {"files": 3})
        self.assertEqual(ts.job_snapshot(), {"kind": "init", "state": "done", "log": [], "result": {"files": 3}, "error": None})
        ts.finish_job("error", error="boom")
        self.assertEqual(ts.job_snapshot(), {"kind": "init", "state": "error", "log": [], "result": None, "error": "boom"})

    def test_log_line_appends_in_order(self):
        ts.log_line("a")
        ts.log_line("b")
        self.assertEqual(ts.job_snapshot()["log"], ["a", "b"])

    def test_the_snapshot_is_a_copy_of_the_log(self):
        ts.log_line("a")
        snap = ts.job_snapshot()
        snap["log"].append("b")
        self.assertEqual(ts.JOB["log"], ["a"])

    def test_job_thread_success_is_done_with_the_result(self):
        ts.claim_job("init")
        ts.job_thread(lambda: {"ok": 1})
        self.assertEqual((ts.job_snapshot()["state"], ts.job_snapshot()["result"], ts.job_snapshot()["error"]), ("done", {"ok": 1}, None))

    def test_job_thread_value_and_os_errors_end_in_error_with_a_log_line(self):
        for exc in (ValueError("bad value"), OSError("disk full")):
            with self.subTest(type(exc).__name__):
                ts.claim_job("apply")

                def task(exc=exc):
                    raise exc
                ts.job_thread(task)
                snap = ts.job_snapshot()
                self.assertEqual((snap["state"], snap["error"], snap["log"]), ("error", str(exc), ["error: %s" % exc]))

    def test_job_thread_system_exit_ends_in_error_with_its_text(self):
        ts.claim_job("apply")

        def task():
            raise SystemExit("clone self-check failed")
        ts.job_thread(task)
        snap = ts.job_snapshot()
        self.assertEqual((snap["state"], snap["error"], snap["log"]), ("error", "clone self-check failed", ["error: clone self-check failed"]))

    def test_job_thread_unexpected_error_is_internal_and_prints_a_traceback(self):
        ts.claim_job("apply")

        def task():
            raise RuntimeError("boom")
        ts.job_thread(task)
        snap = ts.job_snapshot()
        self.assertEqual((snap["state"], snap["error"], snap["log"]), ("error", "internal error: boom", ["error: internal error: boom"]))
        self.assertIn("RuntimeError: boom", self.err.getvalue())

    def test_run_job_claims_first_and_runs_the_task_in_a_daemon_thread(self):
        self.hold_jobs()
        seen = []
        ts.run_job("init", lambda: (seen.append(threading.current_thread()), self.gate.wait(5), "r")[2])
        self.assertEqual(ts.job_snapshot()["state"], "running")
        with self.assertRaises(ts.ApiError):
            ts.run_job("apply", lambda: None)
        self.gate.set()
        self.assertEqual((self.wait_job()["state"], ts.job_snapshot()["result"]), ("done", "r"))
        self.assertTrue(seen[0].daemon)
        self.assertIsNot(seen[0], threading.current_thread())


# -------------------------------------------------------------------------------------------------- logging, headers, game check
class TestLogging(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_an_idle_poll_is_not_logged(self):
        self.assertEqual(self.get("/api/state").status, 200)
        self.assertEqual(self.get("/api/state?car=ks_x").status, 200)
        self.assertNotIn("/api/state", self.err.getvalue())

    def test_other_requests_are_logged_with_their_status(self):
        self.get("/api/settings")
        self.get("/nothing")
        log = self.err.getvalue()
        self.assertIn('"GET /ACESCT/api/settings HTTP/1.1" 200 -', log)
        self.assertIn('"GET /ACESCT/nothing HTTP/1.1" 404 -', log)

    def test_a_failing_state_request_is_logged(self):
        self.assertEqual(self.get("/api/state?car=nope").status, 400)
        self.assertIn("/api/state?car=nope", self.err.getvalue())

    def test_a_forbidden_state_request_is_logged(self):
        self.assertEqual(self.get("/api/state", host="evil.example").status, 403)
        self.assertIn("/api/state", self.err.getvalue())


class TestFramingHeaders(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_every_response_forbids_framing(self):
        replies = {"page": self.get("/"), "state": self.get("/api/state"), "404": self.get("/nothing"),
                   "403": self.get("/api/state", host="evil.example"), "400": self.post("/api/set", b"{bad"),
                   "202": self.post("/api/init")}
        missing = []
        for label, r in replies.items():
            if r.headers.get("X-Frame-Options") not in ("DENY", "SAMEORIGIN"):
                missing.append(label + ": X-Frame-Options")
            if not re.search(r"frame-ancestors\s+('none'|'self')", r.headers.get("Content-Security-Policy", "")):
                missing.append(label + ": Content-Security-Policy frame-ancestors")
        self.assertEqual(missing, [])


class TestHardeningHeaders(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def replies(self):
        return {"page": self.get("/"), "state": self.get("/api/state"), "404": self.get("/nothing"),
                "403": self.get("/api/state", host="evil.example"), "400": self.post("/api/set", b"{bad"),
                "202": self.post("/api/init"), "static": self.get("/favicon.png"), "redirect": self.get("/ACESCT"),
                "405": self.request("PUT", "/api/state"),
                "413": self.request("POST", "/api/set", None, headers={"Content-Length": str(ts.MAX_BODY + 1)}),
                "415": self.post("/api/set", {}, headers={"Content-Type": "text/plain"}),
                "501": self.request("BREW", "/ACESCT/")}

    def test_every_response_says_nosniff_and_sends_no_referrer(self):
        replies = self.replies()
        self.assertEqual({label: r.status for label, r in replies.items()},
                         {"page": 200, "state": 200, "404": 404, "403": 403, "400": 400, "202": 202, "static": 200, "redirect": 301,
                          "405": 405, "413": 413, "415": 415, "501": 501})
        wrong = [label for label, r in replies.items()
                 if (r.headers.get("X-Content-Type-Options"), r.headers.get("Referrer-Policy")) != ("nosniff", "no-referrer")]
        self.assertEqual(wrong, [])

    def test_each_header_is_sent_once(self):
        for label, r in self.replies().items():
            with self.subTest(label):
                self.assertEqual(r.headers.get_all("X-Content-Type-Options"), ["nosniff"])
                self.assertEqual(r.headers.get_all("Referrer-Policy"), ["no-referrer"])
                self.assertEqual(len(r.headers.get_all("X-Frame-Options")), 1)

    def test_the_server_header_names_no_python_version(self):
        for label, r in self.replies().items():
            with self.subTest(label):
                self.assertEqual(r.headers.get("Server", "").strip(), "TunerServer")
                self.assertNotIn("Python", r.headers.get("Server", ""))
        self.assertEqual(ts.Handler.sys_version, "")
        self.assertEqual(ts.Handler.server_version, "TunerServer")


class TestConnectionTimeout(ServerCase):
    def raw(self, data):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(sock.close)
        sock.sendall(data)
        return sock

    def closed_within(self, sock, seconds):
        """The bytes the server sent until it closed the connection; fails when it is still open after seconds."""
        sock.settimeout(seconds)
        start, received = time.monotonic(), b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    return received, time.monotonic() - start
                received += chunk
        except socket.timeout:
            self.fail("the server still holds the connection after %s s" % seconds)

    def test_a_client_that_stops_sending_is_dropped_after_30_seconds(self):
        self.assertEqual(ts.Handler.timeout, 30)

    def test_a_half_request_line_is_closed_by_the_server_after_the_timeout(self):
        with mock.patch.object(ts.Handler, "timeout", 0.3):
            received, elapsed = self.closed_within(self.raw(b"GET /ACESCT/api/sta"), 5)
        self.assertEqual(received, b"")
        self.assertGreaterEqual(elapsed, 0.2)

    def test_half_request_headers_are_closed_by_the_server_after_the_timeout(self):
        with mock.patch.object(ts.Handler, "timeout", 0.3):
            self.assertEqual(self.closed_within(self.raw(b"GET /ACESCT/ HTTP/1.1\r\nHost: x\r\n"), 5)[0], b"")

    def test_a_short_body_does_not_hold_the_connection_for_ever(self):
        head = ("POST /ACESCT/api/set HTTP/1.1\r\nHost: %s\r\nX-Tuner: 1\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\nabc"
                % self.host)
        with mock.patch.object(ts.Handler, "timeout", 0.3):
            self.closed_within(self.raw(head.encode("ascii")), 5)

    def test_a_silent_connection_does_not_stop_other_requests(self):
        with mock.patch.object(ts.Handler, "timeout", 0.5):
            idle = self.raw(b"")
            self.assertEqual(self.get("/api/groups").status, 200)
            self.closed_within(idle, 5)


class TestGameRunning(unittest.TestCase):
    def run_with(self, result=None, error=None):
        run = mock.Mock(return_value=result, side_effect=error)
        with mock.patch.object(tune.subprocess, "run", run):
            return REAL_GAME_RUNNING(), run

    def done(self, code, out):
        return tune.subprocess.CompletedProcess(GAME_ARGV, code, stdout=out, stderr=b"")

    def test_it_asks_tasklist_with_a_fixed_argument_list(self):
        _, run = self.run_with(self.done(0, b""))
        run.assert_called_once_with(GAME_ARGV, capture_output=True, timeout=5)

    def test_the_game_is_running_when_tasklist_lists_the_exe(self):
        self.assertTrue(self.run_with(self.done(0, b'"AssettoCorsaEVO.exe","1234","Console","1","1,000 K"\r\n'))[0])
        self.assertTrue(self.run_with(self.done(0, b'"assettocorsaevo.EXE","1234"\r\n'))[0])

    def test_the_game_is_not_running_when_tasklist_finds_nothing(self):
        self.assertFalse(self.run_with(self.done(0, b"INFO: No tasks are running which match the specified criteria.\r\n"))[0])
        self.assertFalse(self.run_with(self.done(0, b""))[0])

    def test_a_failing_tasklist_means_not_running(self):
        self.assertFalse(self.run_with(self.done(1, b'"AssettoCorsaEVO.exe","1"'))[0])

    def test_a_missing_or_slow_tasklist_means_not_running(self):
        self.assertFalse(self.run_with(error=FileNotFoundError("tasklist"))[0])
        self.assertFalse(self.run_with(error=tune.subprocess.TimeoutExpired("tasklist", 5))[0])

    def test_non_ascii_output_does_not_raise(self):
        self.assertFalse(self.run_with(self.done(0, b"\xff\xfe\x00 nothing"))[0])


class TestStatePollCost(ServerCase):
    def setUp(self):
        super().setUp()
        self.make_car()

    def test_three_quick_polls_start_at_most_one_tasklist(self):
        run = mock.Mock(return_value=tune.subprocess.CompletedProcess(GAME_ARGV, 0, stdout=b"INFO: No tasks", stderr=b""))
        self.patch(ts, "game_running", REAL_GAME_RUNNING)
        self.patch(tune.subprocess, "run", run)
        statuses = [self.get("/api/state").status for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 200])
        self.assertLessEqual(run.call_count, 1, "tasklist was started %d times for 3 polls" % run.call_count)

    def test_the_poll_check_asks_again_after_the_cache_time(self):
        calls = []
        self.patch(ts, "game_running", lambda: calls.append(1) or True)
        ts.GAME_CHECK[:] = [time.monotonic() - 20, False]
        self.assertTrue(ts.game_running_cached())
        self.assertTrue(ts.game_running_cached())
        self.assertEqual(len(calls), 1)
        ts.GAME_CHECK[0] -= 20
        self.assertTrue(ts.game_running_cached())
        self.assertEqual(len(calls), 2)

    def test_an_unexpandable_mods_folder_is_a_409_for_the_state(self):
        ts.CONFIG["mods"] = "%ACE_TEST_NO_SUCH_VAR%/m"
        r = self.get("/api/state")
        self.assertEqual((r.status, r.json), (409, {"error": "cannot expand the mods folder '%ACE_TEST_NO_SUCH_VAR%/m' (pass --mods <folder>)"}))

    def test_apply_always_checks_the_game_itself(self):
        run = mock.Mock(return_value=tune.subprocess.CompletedProcess(GAME_ARGV, 0, stdout=b"INFO: No tasks", stderr=b""))
        self.patch(ts, "game_running", REAL_GAME_RUNNING)
        self.patch(tune.subprocess, "run", run)
        self.get("/api/state")
        before = run.call_count
        self.assertEqual(self.post("/api/apply", {"tune": "draft"}).status, 202)
        self.assertEqual(run.call_count, before + 1)


# -------------------------------------------------------------------------------------------------- pure helpers
class TestHelpers(Env):
    def test_api_error_carries_status_and_message(self):
        e = ts.ApiError(409, "nope")
        self.assertIsInstance(e, Exception)
        self.assertEqual((e.status, e.message, str(e), e.args), (409, "nope", "nope", ("nope",)))

    def test_check_host(self):
        ts.CONFIG["port"] = 8765
        for host in ("127.0.0.1:8765", "localhost:8765", "LocalHost:8765"):
            ts.check_host(host)
        for host in (None, "", "127.0.0.1", "localhost", "127.0.0.1:80", "127.0.0.1:8765x", "evil:8765", "[::1]:8765", "x127.0.0.1:8765"):
            with self.subTest(host), self.assertRaises(ts.ApiError) as cm:
                ts.check_host(host)
            self.assertEqual((cm.exception.status, cm.exception.message), (403, forbidden_host(8765)))

    def test_check_host_follows_the_configured_port(self):
        ts.CONFIG["port"] = 9000
        ts.check_host("127.0.0.1:9000")
        with self.assertRaises(ts.ApiError):
            ts.check_host("127.0.0.1:8765")

    def test_check_host_accepts_localhost_private_addresses_and_the_machine_name(self):
        ts.CONFIG["port"] = 8080
        with mock.patch.object(ts.socket, "gethostname", return_value="MyPC"):
            for host in ("localhost:8080", "127.0.0.1:8080", "192.168.1.20:8080", "10.0.0.5:8080", "172.16.0.1:8080", "MyPC:8080", "mypc:8080"):
                with self.subTest(host):
                    ts.check_host(host)

    def test_check_host_refuses_everything_else(self):
        ts.CONFIG["port"] = 8080
        with mock.patch.object(ts.socket, "gethostname", return_value="MyPC"):
            for host in (None, "", "192.168.1.20", "MyPC", "192.168.1.20:8081", "192.168.1.20:80800", "192.168.1.20:", "evil.example:8080",
                         "8.8.8.8:8080", "[::1]:8080", "192.168.1.20.evil.example:8080", "MyPC.local:8080", "172.32.0.1:8080",
                         "100.64.0.1:8080", "0.0.0.0:8080", ":8080", "1:8080"):
                with self.subTest(host), self.assertRaises(ts.ApiError) as cm:
                    ts.check_host(host)
                self.assertEqual((cm.exception.status, cm.exception.message), (403, forbidden_host(8080)))

    def test_check_host_needs_no_dns_lookup(self):
        ts.CONFIG["port"] = 8080
        with mock.patch.object(ts.socket, "getaddrinfo", side_effect=AssertionError("a DNS lookup")), \
                mock.patch.object(ts.socket, "gethostbyname", side_effect=AssertionError("a DNS lookup")):
            ts.check_host("192.168.1.20:8080")
            with self.assertRaises(ts.ApiError):
                ts.check_host("evil.example:8080")

    def test_private_ip(self):
        for address in ("127.0.0.1", "127.1.2.3", "192.168.1.5", "10.1.2.3", "172.16.0.1", "172.31.255.255"):
            with self.subTest(address):
                self.assertTrue(ts.private_ip(address))
        for address in ("8.8.8.8", "100.64.0.1", "172.32.0.1", "0.0.0.0", "::1", "fe80::1", "", "garbage", "192.168.1", "192.168.1.5.6", "192.168.1.5:80",
                        "[::1]", None, "1"):
            with self.subTest(address):
                self.assertFalse(ts.private_ip(address))

    def test_private_ip_at_the_edges_of_the_documented_ranges(self):
        for address in ("10.0.0.0", "10.255.255.255", "127.0.0.0", "127.255.255.255", "172.16.0.0", "192.168.0.0", "192.168.255.255"):
            with self.subTest(address):
                self.assertTrue(ts.private_ip(address))
        for address in ("9.255.255.255", "11.0.0.0", "126.255.255.255", "128.0.0.0", "172.15.255.255", "192.167.255.255", "192.169.0.0",
                        "100.127.255.255", "::ffff:192.168.1.1", "fc00::1"):
            with self.subTest(address):
                self.assertFalse(ts.private_ip(address))

    def test_bad_input_turns_a_value_error_into_a_400_without_context(self):
        with self.assertRaises(ts.ApiError) as cm, ts.bad_input():
            raise ValueError("nope")
        self.assertEqual((cm.exception.status, cm.exception.message, cm.exception.__suppress_context__), (400, "nope", True))

    def test_bad_input_leaves_other_errors_and_normal_exits_alone(self):
        with self.assertRaises(ts.ApiError) as cm, ts.bad_input():
            raise ts.ApiError(409, "busy")
        self.assertEqual((cm.exception.status, cm.exception.message), (409, "busy"))
        with self.assertRaises(KeyError), ts.bad_input():
            raise KeyError("k")
        with ts.bad_input():
            pass

    def test_check_client_accepts_loopback_and_private_addresses(self):
        for address in ("192.168.1.5", "10.1.2.3", "127.0.0.1"):
            with self.subTest(address):
                ts.check_client(address)

    def test_check_client_refuses_public_shared_and_unparsable_addresses(self):
        for address in ("8.8.8.8", "100.64.0.1", "172.32.0.1", "garbage", "", None):
            with self.subTest(address), self.assertRaises(ts.ApiError) as cm:
                ts.check_client(address)
            self.assertEqual((cm.exception.status, cm.exception.message), (403, "forbidden client address"))

    def probe_socket(self, address=("192.168.1.20", 5555), error=None):
        probe = mock.MagicMock()
        probe.__enter__.return_value = probe
        probe.getsockname.return_value = address
        if error:
            probe.connect.side_effect = error
        return probe

    def lan(self, infos, probe):
        with mock.patch.object(ts.socket, "gethostname", return_value="MyPC"), \
                mock.patch.object(ts.socket, "getaddrinfo", **infos) as lookup, \
                mock.patch.object(ts.socket, "socket", return_value=probe) as make:
            found = ts.lan_addresses()
        return found, lookup, make

    def infos(self, *addresses):
        return {"return_value": [(ts.socket.AF_INET, ts.socket.SOCK_STREAM, 6, "", (a, 0)) for a in addresses]}

    def test_lan_addresses_keeps_private_non_loopback_addresses_without_duplicates(self):
        probe = self.probe_socket(("10.0.0.7", 5555))
        found, lookup, make = self.lan(self.infos("192.168.1.20", "127.0.0.1", "8.8.8.8", "192.168.1.20", "169.254.3.4", "100.64.0.1", "10.0.0.7",
                                                  "0.0.0.0"), probe)
        self.assertEqual(found, ["192.168.1.20", "169.254.3.4", "10.0.0.7"])
        lookup.assert_called_once_with("MyPC", None, ts.socket.AF_INET)

    def test_lan_addresses_asks_the_routing_table_with_a_udp_connect_and_sends_nothing(self):
        probe = self.probe_socket(("192.168.1.20", 5555))
        found, _, make = self.lan(self.infos(), probe)
        self.assertEqual(found, ["192.168.1.20"])
        make.assert_called_once_with(ts.socket.AF_INET, ts.socket.SOCK_DGRAM)
        probe.connect.assert_called_once_with(("10.255.255.255", 1))
        for name in ("send", "sendto", "sendall"):
            getattr(probe, name).assert_not_called()

    def test_lan_addresses_drops_a_loopback_or_public_probe_result(self):
        for address in ("127.0.0.1", "8.8.8.8", "0.0.0.0"):
            with self.subTest(address):
                self.assertEqual(self.lan(self.infos(), self.probe_socket((address, 1)))[0], [])

    def test_lan_addresses_ignores_failing_lookups(self):
        probe = self.probe_socket(("192.168.1.20", 5555))
        found, _, _ = self.lan({"side_effect": ts.socket.gaierror(11001, "getaddrinfo failed")}, probe)
        self.assertEqual(found, ["192.168.1.20"])
        failing = self.probe_socket(error=OSError(101, "Network is unreachable"))
        found, _, _ = self.lan(self.infos("10.0.0.7"), failing)
        self.assertEqual(found, ["10.0.0.7"])
        found, _, _ = self.lan({"side_effect": OSError("no network")}, failing)
        self.assertEqual(found, [])

    def headers(self, **kw):
        msg = email.message.Message()
        for key, value in kw.items():
            msg[key.replace("_", "-")] = value
        return msg

    def test_check_post_headers_accepts_the_page_headers(self):
        ts.check_post_headers(self.headers(X_Tuner="1", Content_Type="application/json"))
        ts.check_post_headers(self.headers(x_tuner="1", content_type="Application/JSON; charset=utf-8"))

    def test_check_post_headers_refuses_a_missing_or_wrong_x_tuner(self):
        for h in (self.headers(Content_Type="application/json"), self.headers(X_Tuner="2", Content_Type="application/json")):
            with self.assertRaises(ts.ApiError) as cm:
                ts.check_post_headers(h)
            self.assertEqual((cm.exception.status, cm.exception.message), (403, "missing header X-Tuner: 1"))

    def test_check_post_headers_refuses_another_content_type(self):
        for h in (self.headers(X_Tuner="1"), self.headers(X_Tuner="1", Content_Type="text/plain"),
                  self.headers(X_Tuner="1", Content_Type="json")):
            with self.assertRaises(ts.ApiError) as cm:
                ts.check_post_headers(h)
            self.assertEqual((cm.exception.status, cm.exception.message), (415, "Content-Type must be application/json"))

    def test_parse_port_accepts_ports_of_a_user_server(self):
        for text, port in (("8765", 8765), ("1024", 1024), ("5000", 5000), ("65535", 65535)):
            self.assertEqual(ts.parse_port(text), port)

    def test_parse_port_rejects_everything_else(self):
        for text in ("0", "65536", "99999999999", "-1", "abc", "", "1.5", "80x", "0x50", "8 0", "+80"):
            with self.subTest(text), self.assertRaisesRegex(ValueError, r"^--port must be a number from \d+ to 65535$"):
                ts.parse_port(text)

    def test_parse_port_rejects_port_80(self):
        with self.assertRaisesRegex(ValueError, "--port"):
            ts.parse_port("80")

    def test_mods_dir_expands_variables_and_makes_the_path_absolute(self):
        with mock.patch.dict(os.environ, {"ACE_TEST_MODS": str(self.d)}):
            ts.CONFIG["mods"] = "$ACE_TEST_MODS/m"
            self.assertEqual(ts.mods_dir(), os.path.join(str(self.d), "m"))
        ts.CONFIG["mods"] = "rel/mods"
        self.assertEqual(ts.mods_dir(), os.path.abspath("rel/mods"))

    def test_mods_dir_refuses_a_variable_that_cannot_be_expanded(self):
        ts.CONFIG["mods"] = "%ACE_TEST_NO_SUCH_VAR%/m"
        with self.assertRaises(ValueError):
            ts.mods_dir()

    def test_mods_dir_defaults_to_the_game_mods_folder(self):
        ts.CONFIG["mods"] = None
        with mock.patch.dict(os.environ, {"USERPROFILE": str(self.d)}), mock.patch.object(os.path, "expandvars", ntpath.expandvars):
            self.assertEqual(ts.mods_dir(), os.path.abspath(os.path.expandvars(clone_car.DEFAULT_MODS)))

    def test_installed_info_without_a_package(self):
        self.assertEqual(ts.installed_info("ks_x"), {"path": os.path.join(self.mods, "ax_x.kspkg"), "exists": False, "bytes": None, "modified": None})

    def test_installed_info_with_a_package(self):
        os.makedirs(self.mods)
        path = os.path.join(self.mods, "ax_x.kspkg")
        with open(path, "wb") as f:
            f.write(b"123456")
        os.utime(path, (1700000000, 1700000000))
        info = ts.installed_info("ks_x")
        self.assertEqual((info["path"], info["exists"], info["bytes"]), (path, True, 6))
        self.assertRegex(info["modified"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_installed_info_names_the_package_after_the_new_id(self):
        self.assertTrue(ts.installed_info("ks_bmw_m3")["path"].endswith("ax_bmw_m3.kspkg"))

    def test_apply_lines_with_an_install_and_a_backup(self):
        changes = {"since": "last build", "total": 5, "settings": [{"id": "a", "from": 1.5, "to": 2.0}, {"id": "b", "from": None, "to": True}],
                   "extras": [{"kind": "sound", "slot": "turbo", "from": None, "to": "e/turbo_rx7", "text": "Sound turbo: own sound -> turbo_rx7"}]}
        res = dict(APPLY_RESULT, changes=changes, notes=["n1", "n2"], backup="/b/old.kspkg")
        self.assertEqual(ts.apply_lines(res), [
            "3 change(s) since the last build (5 changed settings compared to the stock car in total)", "  a: 1.5 -> 2.0", "  b: - -> true",
            "  Sound turbo: own sound -> turbo_rx7", "n1", "n2",
            "package: /w/ks_x/build/ax_x/ax_x.kspkg (7 bytes)", "installed: /m/ax_x.kspkg", "backup: /b/old.kspkg"])

    def test_apply_lines_without_an_install(self):
        res = dict(APPLY_RESULT, changes={"since": "last build", "settings": [], "extras": [], "total": 0}, notes=[], installed=None)
        self.assertEqual(ts.apply_lines(res), ["no change since the last build (0 changed settings compared to the stock car in total)",
                                               "package: /w/ks_x/build/ax_x/ax_x.kspkg (7 bytes)"])

    def test_apply_lines_of_a_first_build_name_the_total_and_do_not_list_the_applied_settings(self):
        res = dict(APPLY_RESULT, applied=[{"id": "x", "old": 1, "new": 2, "files": ["f"]}] * 3, notes=[], installed=None,
                   changes={"since": None, "settings": [{"id": "x", "from": 1, "to": 2}], "extras": [], "total": 3})
        self.assertEqual(ts.apply_lines(res), ["first build of this car: 3 changed settings compared to the stock car", "  x: 1 -> 2",
                                               "package: /w/ks_x/build/ax_x/ax_x.kspkg (7 bytes)"])

    def test_request_car(self):
        self.write_index([{"id": "ks_x", "display_name": "Car X"}, {"id": "ks_y", "display_name": "Car Y"}])
        self.assertEqual(ts.request_car(None, ""), "ks_x")
        self.assertEqual(ts.request_car(None, "car=ks_y"), "ks_y")
        self.assertEqual(ts.request_car(None, "a=1&car=ks_y&b=2"), "ks_y")
        self.assertEqual(ts.request_car(None, "car=ks%5Fy"), "ks_y")
        self.assertEqual(ts.request_car("ks_x", "car=ks_y"), "ks_x")
        self.assertEqual(ts.request_car(None, "car="), "ks_x")
        self.assertEqual(ts.request_car("", "car=ks_y"), "ks_x")

    def test_request_car_refuses_unknown_and_non_text_cars(self):
        self.write_index([{"id": "ks_x", "display_name": "Car X"}])
        for value, query, text in (("../x", "", "unknown car"), (None, "car=../x", "unknown car"), (5, "", "car must be text"),
                                   (["ks_x"], "", "car must be text")):
            with self.subTest(value, query=query), self.assertRaises(ts.ApiError) as cm:
                ts.request_car(value, query)
            self.assertEqual(cm.exception.status, 400)
            self.assertTrue(cm.exception.message.startswith(text), cm.exception.message)

    def test_request_car_without_a_car_list_knows_only_the_tested_cars(self):
        self.patch(tune, "load_cars_index", lambda work, game=None: None)
        self.assertEqual(ts.request_car("ks_x", ""), "ks_x")
        with self.assertRaises(ts.ApiError) as cm:
            ts.request_car("ks_y", "")
        self.assertEqual(cm.exception.status, 400)

    def write_index(self, index):
        os.makedirs(self.work, exist_ok=True)
        with open(os.path.join(self.work, "cars_index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f)

    def test_row_json_keeps_the_documented_fields_only(self):
        row = {k: k for k in ROW_KEYS}
        row.update(copies_differ=False, targets=["secret"], reason=None, applicable=True, ok=True)
        s = {"min": 1, "max": 5, "choices": ["a"], "ui": "header", "targets": ["x"], "handler": "h"}
        out = ts.row_json(row, s)
        self.assertEqual(set(out), ROW_KEYS | {"min", "max", "choices", "ui"})
        self.assertEqual((out["min"], out["max"], out["choices"], out["ui"]), (1, 5, ["a"], "header"))
        self.assertNotIn("copy_values", out)

    def test_row_json_passes_advanced_only_when_the_setting_has_it(self):
        row = {k: k for k in ROW_KEYS}
        row.update(copies_differ=False)
        self.assertNotIn("advanced", ts.row_json(row, {"min": 1}))
        out = ts.row_json(row, {"advanced": True})
        self.assertEqual((set(out), out["advanced"]), (ROW_KEYS | {"advanced"}, True))

    def test_row_json_adds_the_copy_values_only_when_the_copies_differ(self):
        row = {k: k for k in ROW_KEYS}
        row.update(copies_differ=True, copy_values=[{"target": "t", "value": 1}])
        out = ts.row_json(row, {})
        self.assertEqual((set(out), out["copy_values"]), (ROW_KEYS | {"copy_values"}, [{"target": "t", "value": 1}]))

    def test_row_json_adds_the_base_range_only_when_one_is_given(self):
        row = {k: k for k in ROW_KEYS}
        row.update(copies_differ=False)
        self.assertNotIn("base_range", ts.row_json(row, {"min": 1}))
        self.assertNotIn("base_range", ts.row_json(row, {"min": 1}, None))
        out = ts.row_json(row, {"min": 1}, {"low": 2, "high": 3, "extra": 4})
        self.assertEqual((set(out), out["base_range"], out["min"]), (ROW_KEYS | {"min", "base_range"}, {"low": 2, "high": 3}, 1))

    def test_rows_json_needs_a_base_car(self):
        with self.assertRaises(ts.ApiError) as cm:
            ts.rows_json(self.work, "ks_x", self.cat)
        self.assertEqual((cm.exception.status, cm.exception.message), (409, "base car missing, run init"))

    def test_rows_json_of_a_stub_car(self):
        fc = FakeCar(self.work, "ks_x").install(self)
        gp = fc.game_path
        fc.add("data/x.car", {"engine_path": gp("data/e.carengine"), "stock_setup": gp("data/s.carsetup"), "engine": {"limiter": 7000}})
        fc.add("data/e.carengine", {"limiter": 7000, "turbos_to_load": []})
        fc.add("data/s.carsetup", {"electronics": {"tc1": 2}})
        write_state = {"limiter": 8000}
        tune.save_state(self.work, "ks_x", write_state)
        rows = ts.rows_json(self.work, "ks_x", self.cat)
        self.assertEqual([r["id"] for r in rows], ["limiter", "aids_off", "name_suffix"])
        self.assertEqual((rows[0]["value"], rows[0]["default"], rows[0]["changed"]), (8000, 7000, True))
        self.assertEqual(ts.row_of(self.work, "ks_x", self.cat, "aids_off")["id"], "aids_off")

    def test_base_present_needs_a_non_empty_car_folder(self):
        fc = FakeCar(self.work, "ks_x")
        self.assertFalse(ts.base_present(self.work, "ks_x"))
        os.makedirs(fc.car_root)
        self.assertFalse(ts.base_present(self.work, "ks_x"))
        fc.add("data/x.car")
        self.assertTrue(ts.base_present(self.work, "ks_x"))


# -------------------------------------------------------------------------------------------------- main()
class StubServer:
    """Stands for ThreadingHTTPServer in main(): records its construction order and raises what the test says in serve_forever."""
    log = []
    serve_error = KeyboardInterrupt
    bind_error = None

    def __init__(self, address, handler):
        StubServer.log.append("server")
        if StubServer.bind_error:
            raise StubServer.bind_error
        self.address, self.handler, self.closed = address, handler, False
        StubServer.last = self

    def serve_forever(self):
        StubServer.log.append("serve")
        if StubServer.serve_error:
            raise StubServer.serve_error

    def server_close(self):
        self.closed = True
        StubServer.log.append("close")


class TestServerClass(unittest.TestCase):
    def test_the_port_is_not_shared(self):
        self.assertEqual(ts.Server.allow_reuse_address, os.name != "nt")
        self.assertTrue(issubclass(ts.Server, http.server.ThreadingHTTPServer))

    def test_the_reuse_rule_is_false_on_windows_and_the_default_elsewhere(self):
        tree = ast.parse(inspect.getsource(ts.Server))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and n.targets[0].id == "allow_reuse_address")
        expr = compile(ast.Expression(node.value), "<allow_reuse_address>", "eval")
        for name, wanted in (("nt", False), ("posix", True)):
            with self.subTest(name):
                self.assertEqual(eval(expr, {"os": types.SimpleNamespace(name=name)}), wanted)

    def bind(self, name):
        server = ts.Server.__new__(ts.Server)
        server.socket = mock.Mock()
        with mock.patch.object(http.server.HTTPServer, "server_bind") as base, \
                mock.patch.object(ts.os, "name", name), \
                mock.patch.object(ts.socket, "SO_EXCLUSIVEADDRUSE", -5, create=True):
            ts.Server.server_bind(server)
        base.assert_called_once_with(server)
        return server.socket.setsockopt

    def test_windows_binds_exclusively_before_the_bind(self):
        self.bind("nt").assert_called_once_with(ts.socket.SOL_SOCKET, -5, 1)

    def test_other_systems_set_no_socket_option(self):
        self.bind("posix").assert_not_called()


class TestRealServer(Env):
    def test_the_server_class_answers_below_the_base_path_on_a_real_socket(self):
        server = ts.Server(("127.0.0.1", 0), ts.Handler)
        port = ts.CONFIG["port"] = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.001}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for path, status in (("/ACESCT/", 200), ("/ACESCT", 301), ("/", 302), ("/api/state", 404)):
            with self.subTest(path):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn.request("GET", path)
                    self.assertEqual(conn.getresponse().status, status)
                finally:
                    conn.close()


class TestServerRestartAndDisconnects(Env):
    def serve(self, handler=ts.Handler, port=0):
        server = ts.Server(("127.0.0.1", port), handler)
        ts.CONFIG["port"] = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.001}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def exchange(self, port):
        data = ("GET /ACESCT/ HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % port).encode("ascii")
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            sock.sendall(data)
            received = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    return received
                received += chunk
        except ConnectionError:
            return b""
        finally:
            sock.close()

    @unittest.skipIf(os.name == "nt", "Windows binds exclusively and does not reuse the address")
    def test_the_port_can_be_bound_again_at_once_after_a_page_was_served(self):
        server = ts.Server(("127.0.0.1", 0), ts.Handler)
        port = ts.CONFIG["port"] = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.001}, daemon=True)
        thread.start()
        self.assertTrue(self.exchange(port).startswith(b"HTTP/1.0 200"))
        server.shutdown()
        thread.join(5)
        server.server_close()
        again = ts.Server(("127.0.0.1", port), ts.Handler)
        again.server_close()

    def test_a_client_that_disconnects_inside_a_handler_prints_no_traceback(self):
        for error in (BrokenPipeError("broken pipe"), ConnectionResetError("reset"), ConnectionAbortedError("aborted")):
            with self.subTest(type(error).__name__):
                class Dropping(ts.Handler):
                    def do_GET(self):
                        raise error
                port = self.serve(Dropping).server_address[1]
                self.exchange(port)
                self.assertEqual(self.err.getvalue(), "")

    def test_a_real_error_inside_a_handler_still_prints_its_traceback(self):
        class Broken(ts.Handler):
            def do_GET(self):
                raise RuntimeError("handler bug")
        port = self.serve(Broken).server_address[1]
        self.exchange(port)
        self.assertIn("Traceback", self.err.getvalue())
        self.assertIn("RuntimeError: handler bug", self.err.getvalue())

    def test_handle_error_is_quiet_for_connection_errors_only(self):
        server = ts.Server.__new__(ts.Server)
        for error, quiet in ((BrokenPipeError(), True), (ConnectionResetError(), True), (ConnectionAbortedError(), True),
                             (OSError("disk"), False), (ValueError("x"), False), (TimeoutError(), False)):
            with self.subTest(type(error).__name__):
                self.err.seek(0)
                self.err.truncate()
                try:
                    raise error
                except Exception:
                    server.handle_error(mock.Mock(), ("127.0.0.1", 1))
                self.assertEqual(self.err.getvalue() == "", quiet)


class TestMain(Env):
    def setUp(self):
        super().setUp()
        StubServer.log, StubServer.serve_error, StubServer.bind_error = [], KeyboardInterrupt, None
        self.patch(ts, "Server", StubServer)
        self.patch(tune, "load_cars_index", lambda work, *a, **k: StubServer.log.append("index"))
        self.lan = ["192.168.1.20"]
        self.patch(ts, "lan_addresses", lambda: self.lan)
        self.argv = ["--port", "8765", "--work", self.work, "--mods", self.mods]

    def run_main(self, *argv):
        """main() with the given arguments; returns what it exits with (None when it returns)."""
        with mock.patch.object(sys, "argv", ["tuner_server.py", *argv]):
            try:
                ts.main()
            except SystemExit as e:
                return e.code
        return None

    def test_start_binds_every_address_with_the_handler_and_prints_the_urls(self):
        self.lan = ["192.168.1.20", "10.0.0.7"]
        self.assertIsNone(self.run_main(*self.argv))
        self.assertEqual((StubServer.last.address, StubServer.last.handler), (("0.0.0.0", 8765), ts.Handler))
        self.assertEqual(self.out.getvalue(), "tuner running on http://127.0.0.1:8765/ACESCT/\n"
                         "reachable in the home network: http://192.168.1.20:8765/ACESCT/\n"
                         "reachable in the home network: http://10.0.0.7:8765/ACESCT/\nstopped\n")

    def test_start_prints_only_the_local_url_when_the_pc_has_no_private_address(self):
        self.lan = []
        self.run_main(*self.argv)
        self.assertEqual(self.out.getvalue(), "tuner running on http://127.0.0.1:8765/ACESCT/\nstopped\n")

    def test_bind_127_0_0_1_serves_this_pc_only_and_prints_one_url(self):
        self.assertIsNone(self.run_main(*self.argv, "--bind", "127.0.0.1"))
        self.assertEqual(StubServer.last.address, ("127.0.0.1", 8765))
        self.assertEqual(self.out.getvalue(), "tuner running on http://127.0.0.1:8765/ACESCT/\nstopped\n")

    def test_a_loopback_bind_prints_its_own_address_and_no_home_network_lines(self):
        self.lan = ["192.168.1.20"]
        for bind in ("127.0.0.1", "localhost", "127.0.0.2"):
            with self.subTest(bind):
                self.out.seek(0)
                self.out.truncate()
                self.run_main(*self.argv, "--bind", bind)
                self.assertEqual(self.out.getvalue(), "tuner running on http://%s:8765/ACESCT/\nstopped\n" % bind)

    def test_a_bind_to_one_private_address_prints_that_address_only(self):
        self.lan = ["192.168.1.20", "10.0.0.7"]
        self.run_main(*self.argv, "--bind", "192.168.1.20")
        self.assertEqual(self.out.getvalue(), "tuner running on http://192.168.1.20:8765/ACESCT/\nstopped\n")

    def test_an_empty_bind_listens_on_every_address_and_prints_like_the_default(self):
        self.run_main(*self.argv, "--bind", "")
        self.assertEqual(StubServer.last.address, ("", 8765))
        self.assertEqual(self.out.getvalue(), "tuner running on http://127.0.0.1:8765/ACESCT/\n"
                         "reachable in the home network: http://192.168.1.20:8765/ACESCT/\nstopped\n")

    def test_bind_takes_any_address_of_the_option(self):
        self.run_main(*self.argv, "--bind", "192.168.1.20")
        self.assertEqual(StubServer.last.address, ("192.168.1.20", 8765))

    def test_the_default_bind_is_every_ipv4_address(self):
        self.assertEqual(ts.DEFAULT_BIND, "0.0.0.0")
        self.run_main("--work", self.work)
        self.assertEqual(StubServer.last.address[0], "0.0.0.0")

    def test_a_bind_address_that_cannot_be_used_is_an_error_line(self):
        StubServer.bind_error = OSError(10049, "address not valid in its context")
        self.assertEqual(self.run_main(*self.argv, "--bind", "203.0.113.9"), "error: cannot listen on 203.0.113.9:8765 ([Errno 10049] address not valid in its context); is the tuner already running? use --port N")
        self.assertEqual(self.out.getvalue(), "")

    def test_start_sets_config_from_the_options(self):
        self.run_main(*self.argv)
        self.assertEqual((ts.CONFIG["port"], ts.CONFIG["work"], ts.CONFIG["mods"]), (8765, os.path.abspath(self.work), self.mods))

    def test_the_default_port_is_8090(self):
        self.run_main("--work", self.work)
        self.assertEqual((ts.DEFAULT_PORT, StubServer.last.address), (8090, ("0.0.0.0", 8090)))
        self.assertIn("http://127.0.0.1:8090/ACESCT/\n", self.out.getvalue())

    def test_ctrl_c_closes_the_server_and_returns(self):
        self.assertIsNone(self.run_main(*self.argv))
        self.assertEqual(StubServer.log[-2:], ["serve", "close"])
        self.assertTrue(StubServer.last.closed)

    def test_the_server_is_closed_after_an_unexpected_error_too(self):
        StubServer.serve_error = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            self.run_main(*self.argv)
        self.assertTrue(StubServer.last.closed)

    def test_a_bad_port_is_an_error_line(self):
        exit_text = self.run_main("--port", "abc", "--work", self.work)
        self.assertTrue(exit_text.startswith("error: --port must be a number from"), exit_text)
        self.assertEqual(StubServer.log, [])

    def test_an_unexpandable_work_folder_is_an_error_line(self):
        exit_text = self.run_main("--work", "%ACE_TEST_NO_SUCH_VAR%/w")
        self.assertTrue(exit_text.startswith("error: cannot expand the work directory"), exit_text)

    def test_a_port_that_cannot_be_bound_is_an_error_line(self):
        StubServer.bind_error = OSError(98, "Address already in use")
        self.assertEqual(self.run_main(*self.argv), "error: cannot listen on 0.0.0.0:8765 ([Errno 98] Address already in use); is the tuner already running? use --port N")
        self.assertEqual(self.out.getvalue(), "")

    def test_the_old_single_car_layout_is_moved_into_the_default_car_folder(self):
        os.makedirs(os.path.join(self.work, "base"))
        with open(os.path.join(self.work, "base", "x.bin"), "wb"):
            pass
        with open(os.path.join(self.work, "tune_state.json"), "w") as f:
            f.write("{}")
        self.run_main(*self.argv)
        self.assertTrue(os.path.isfile(os.path.join(self.work, "ks_x", "base", "x.bin")))
        self.assertTrue(os.path.isfile(os.path.join(self.work, "ks_x", "tune_state.json")))
        self.assertIn("moved the old single-car layout of", self.out.getvalue())
        self.assertIn("base, tune_state.json", self.out.getvalue())

    def test_every_option_of_the_usage_block_is_accepted(self):
        values = {"port": "8765", "bind": "127.0.0.1", "work": self.work, "mods": self.mods, "logs": self.logs, "game": "game.kspkg"}
        flags = re.findall(r"\[--(\w+) ", USAGE)
        self.assertTrue({"port", "bind", "work", "mods", "logs"} <= set(flags), flags)
        self.assertIsNone(self.run_main(*[w for flag in flags for w in ("--" + flag, values[flag])]))

    def test_the_logs_option_is_accepted_and_kept_in_the_config(self):
        self.assertIsNone(self.run_main(*self.argv, "--logs", self.logs))
        self.assertEqual(ts.CONFIG["logs"], self.logs)
        self.assertEqual(ts.logs_dir(), os.path.abspath(self.logs))

    def test_the_logs_folder_defaults_to_the_logs_folder_of_the_repository(self):
        self.run_main(*self.argv)
        self.assertIsNone(ts.CONFIG["logs"])
        self.assertEqual(ts.logs_dir(), os.path.abspath(logconf.default_logs_dir()))

    def test_the_logs_option_creates_nothing(self):
        self.run_main(*self.argv, "--logs", self.logs)
        self.assertFalse(os.path.exists(self.logs))

    def test_an_unexpandable_logs_folder_is_an_error_line_before_the_server_is_created(self):
        exit_text = self.run_main(*self.argv, "--logs", "%ACE_TEST_NO_SUCH_VAR%/l")
        self.assertTrue(exit_text.startswith("error: cannot expand the logs directory"), exit_text)
        self.assertEqual(StubServer.log, [])

    def test_the_game_option_is_accepted_and_kept_in_the_config(self):
        self.assertIsNone(self.run_main(*self.argv, "--game", "game.kspkg"))
        self.assertEqual(ts.CONFIG.get("game"), os.path.expandvars("game.kspkg"))

    def test_the_listening_server_is_created_before_the_car_index_is_loaded(self):
        self.run_main(*self.argv)
        self.assertIn("server", StubServer.log)
        self.assertIn("index", StubServer.log)
        self.assertLess(StubServer.log.index("server"), StubServer.log.index("index"), StubServer.log)

    def test_the_game_option_reaches_the_car_index(self):
        seen = []
        self.patch(tune, "load_cars_index", lambda work, *a, **k: seen.append(a))
        self.run_main(*self.argv, "--game", "game.kspkg")
        self.assertEqual(seen, [("game.kspkg",)])

    def test_the_game_defaults_to_the_steam_package(self):
        self.run_main(*self.argv)
        self.assertEqual(ts.CONFIG["game"], os.path.expandvars(tune.DEFAULT_GAME))

    def test_a_job_that_runs_at_ctrl_c_is_announced(self):
        self.hold_jobs()
        ts.run_job("apply", lambda: self.gate.wait(10))
        self.addCleanup(self.gate.set)
        main = threading.Thread(target=lambda: self.run_main(*self.argv), daemon=True)
        main.start()
        main.join(0.3)
        self.assertIn("a job is still running", self.out.getvalue())
        self.gate.set()
        main.join(5)
        self.assertTrue(self.out.getvalue().endswith("stopped\n"))

    def test_the_car_index_is_loaded_once_per_start(self):
        self.run_main(*self.argv)
        self.assertEqual(StubServer.log.count("index"), 1)

    def test_ctrl_c_waits_for_a_running_job(self):
        self.hold_jobs()
        ts.run_job("apply", lambda: self.gate.wait(10))
        exits = []
        main = threading.Thread(target=lambda: exits.append(self.run_main(*self.argv)), daemon=True)
        self.addCleanup(main.join, 5)
        self.addCleanup(self.gate.set)
        main.start()
        main.join(0.3)
        self.assertTrue(main.is_alive(), "main() returned while the job was still running")
        self.gate.set()
        main.join(5)
        self.assertFalse(main.is_alive())
        self.assertEqual(exits, [None])

    def test_ctrl_c_without_a_job_returns_at_once(self):
        main = threading.Thread(target=lambda: self.run_main(*self.argv), daemon=True)
        main.start()
        main.join(5)
        self.assertFalse(main.is_alive())


# -------------------------------------------------------------------------------------------------- CLI conventions
class TestCli(unittest.TestCase):
    pass


usage_cases(TestCli, USAGE, (("positional", ["foo"]), ("positional_after_options", ["--port", "8765", "foo"]),
                             ("unknown_option", ["--bogus", "1"]), ("help", ["--help"]), ("port_without_value", ["--port"]),
                             ("work_without_value", ["--work"]), ("mods_without_value", ["--mods"]), ("logs_without_value", ["--logs"]),
                             ("bind_without_value", ["--bind"])), ts, real=("positional",))


class TestCliRuntimeErrors(unittest.TestCase):
    def run_server(self, *argv):
        with tmp() as d:
            return run_main(ts.main, ["tuner_server.py", *argv], cwd=d)

    def test_a_port_below_1024_is_an_error_line_on_stderr_with_exit_1(self):
        with tmp() as d:
            r = run_tool("tuner_server.py", "--port", "80", cwd=d)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, "", "error: --port must be a number from 1024 to 65535\n"))

    def test_a_bad_port_is_an_error_line_on_stderr_with_exit_1(self):
        for port in ("abc", "0", "70000", "-1"):
            with self.subTest(port):
                code, out, err = self.run_server("--port", port)
                self.assertEqual((code, out), (1, ""))
                self.assertRegex(err, r"^error: --port must be a number from \d+ to 65535\n$")

    def test_an_unexpandable_work_folder_is_an_error_line_on_stderr_with_exit_1(self):
        code, out, err = self.run_server("--work", "%ACE_TEST_NO_SUCH_VAR%/w")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: cannot expand the work directory"), err)


class TestUsageText(unittest.TestCase):
    def test_usage_block_is_the_first_paragraph_after_the_title(self):
        self.assertEqual(len(ts.__doc__.split("\n\n")[0].splitlines()), 1)
        self.assertTrue(USAGE.startswith("usage:\n  python tools/tuner_server.py [--port N]"), USAGE)
        self.assertIn("[--bind <address>]", USAGE)
        self.assertIn("[--logs <dir>]", USAGE)

    def test_the_documented_defaults_match_the_code(self):
        self.assertIn("default port 8090", ts.__doc__)
        self.assertEqual(ts.DEFAULT_PORT, 8090)
        self.assertIn("--bind <address> (default 0.0.0.0", ts.__doc__)
        self.assertIn("http://127.0.0.1:<port>/ACESCT/", ts.__doc__)
        self.assertIn("http://<address of the PC>:<port>/ACESCT/", ts.__doc__)
        self.assertIn("fixed base path " + ts.BASE_PATH, ts.__doc__)

    def test_the_documented_checks_are_the_ones_of_the_code(self):
        doc = " ".join(ts.__doc__.split())
        for text in ("client is not loopback or private", "or the host name of this PC", "(301)", "(302)"):
            self.assertIn(text, doc)

    def test_every_documented_route_exists(self):
        for route in re.findall(r"^  (?:GET|POST) +(/api/\w+)", ts.__doc__, re.M):
            self.assertIn(route, list(ts.GET_ROUTES) + list(ts.POST_ROUTES))
        for route in re.findall(r"POST (/api/\w+)", ts.__doc__):
            self.assertIn(route, ts.POST_ROUTES)
        for route in list(ts.GET_ROUTES) + list(ts.POST_ROUTES):
            self.assertIn(route, ts.__doc__)


class TestBaseNameRoutes(SoundCase):
    """base_name of /api/state and "base" as the version of /api/version_rename: ax01 is a modded car of ks_x (stock variant text "Standard")
    with the version v01 Heavy."""

    def setUp(self):
        super().setUp()
        self.cat = mini_catalogue(limiter(), suffix(), mini_setting("variant_name", kind="meta", type="string", default_template="{stock_variant_name}",
                                                                    handler="variant_name", ui="hidden"))
        self.stock_info(variant_name="Standard")
        self.make_tune("ax01", {"name_suffix": "_A", "limiter": 8000})
        self.make_tune("ax02", {"name_suffix": "_B"})
        tune.add_version(self.work, "ks_x", "Heavy", "ax01")

    def stock_info(self, **kw):
        info = {"car_id": "ks_x", "display_name": "Car X", "brand": "Brand", "year": 1999, "property_1": "P1", "property_2": "P2", "property_3": "P3"}
        info.update(kw)
        self.write(tune.stock_info_path(self.work, "ks_x"), info)

    def rename(self, name, version="base", tune_id="ax01"):
        return self.post("/api/version_rename", {"tune": tune_id, "version": version, "name": name})

    def test_state_has_the_name_of_the_base_of_the_selected_modded_car(self):
        self.assertEqual(self.get("/api/state?tune=ax01").json["base_name"], "Base")
        self.assertEqual(self.get("/api/state?tune=ax02").json["base_name"], "Standard")

    def test_state_has_none_for_a_stock_car_the_draft_and_a_car_without_a_variant_line(self):
        for query in ("", "?tune=draft"):
            with self.subTest(query):
                self.assertIsNone(self.get("/api/state" + query).json["base_name"])
        self.stock_info(variant_name="")
        self.assertIsNone(self.get("/api/state?tune=ax01").json["base_name"])

    def test_renaming_the_base_answers_the_id_and_the_name_and_state_follows(self):
        r = self.rename("  Daily  ")
        self.assertEqual((r.status, r.json), (200, {"id": "base", "name": "Daily"}))
        self.assertEqual(self.get("/api/state?tune=ax01").json["base_name"], "Daily")
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax01")["variant_name"], "Daily")
        self.assertEqual([v["name"] for v in self.get("/api/state?tune=ax01").json["versions"]], ["Heavy"])

    def test_the_rows_do_not_change_but_carry_the_hidden_hint_and_the_name(self):
        rows = {r["id"]: r for r in self.get("/api/settings?tune=ax01").json}
        self.assertEqual((rows["variant_name"]["ui"], rows["variant_name"]["value"]), ("hidden", "Base"))
        self.rename("Daily")
        rows = {r["id"]: r for r in self.get("/api/settings?tune=ax01").json}
        self.assertEqual((rows["variant_name"]["value"], rows["variant_name"]["changed"]), ("Daily", True))

    def test_the_errors_are_400_and_nothing_is_written(self):
        before = tune.load_state(self.work, "ks_x", "ax01")
        for body, text in (({"tune": "ax01", "version": "base", "name": "heavy"}, "base name heavy is already used by version v01"),
                           ({"tune": "ax01", "version": "base", "name": ""}, "a version name must be 1 to 40 characters without control characters"),
                           ({"tune": "ax01", "version": "base"}, "need name (text)"),
                           ({"tune": "draft", "version": "base", "name": "X"}, "a version needs a modded car"),
                           ({"tune": "ax09", "version": "base", "name": "X"}, "unknown modded car ax09 of ks_x")):
            with self.subTest(body):
                r = self.post("/api/version_rename", body)
                self.assertEqual((r.status, r.json), (400, {"error": text}))
        self.assertEqual(tune.load_state(self.work, "ks_x", "ax01"), before)

    def test_a_car_without_a_variant_line_cannot_name_its_base(self):
        self.stock_info(variant_name="")
        r = self.rename("Daily")
        self.assertEqual((r.status, r.json), (400, {"error": "the base of this car has no name in the game's menu"}))

    def test_a_version_cannot_take_the_name_of_the_base_through_add_or_rename(self):
        r = self.post("/api/version_add", {"tune": "ax01", "name": "base"})
        self.assertEqual((r.status, r.json), (400, {"error": "version name base is already used by the base"}))
        r = self.rename("BASE", "v01")
        self.assertEqual((r.status, r.json), (400, {"error": "version name BASE is already used by the base"}))
        self.assertEqual(self.rename("Daily").status, 200)
        self.assertEqual(self.post("/api/version_add", {"tune": "ax01", "name": "Base"}).status, 200)

    def test_a_locked_version_does_not_stop_the_rename_of_the_base(self):
        folder = os.path.join(tune.version_dir(self.work, "ks_x", "ax01", "v01"), "meta.json")
        self.write(folder, {"name": "Heavy", "locked": True})
        self.assertEqual(self.rename("Daily").status, 200)
        self.assertEqual(self.rename("Light", "v01").status, 400)

    def test_a_job_that_runs_refuses_it_like_every_version_write(self):
        self.hold_jobs()
        self.assertEqual(self.post("/api/apply", {"tune": "ax01"}).status, 202)
        r = self.rename("Daily")
        self.assertEqual((r.status, r.json), (409, JOB_RUNNING))
        self.finish_held_job()


if __name__ == "__main__":
    unittest.main()
