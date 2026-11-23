"""Local web server of the tuner: serves the settings table and runs Apply through tools/tune.py.

usage:
  python tools/tuner_server.py [--port N] [--bind <address>] [--work <dir>] [--mods <dir>] [--logs <dir>] [--game <content.kspkg>]

Serves tuner/web/index.html at http://127.0.0.1:<port>/ACESCT/ (default port 8090, allowed 1024 to 65535) and, from other
devices of the home network, at http://<address of the PC>:<port>/ACESCT/; --bind <address> (default 0.0.0.0, all IPv4
addresses of the PC, as does an empty address; 127.0.0.1 serves this PC only) is the address the server listens on. Everything is served below the
fixed base path /ACESCT: GET /ACESCT redirects (301) to /ACESCT/, GET / redirects (302) to /ACESCT/, every other path
outside /ACESCT/ is a 404. Next to the page, GET /ACESCT/<name> serves six static files of tuner/web from a fixed table
(no other file, no directory access): apple-touch-icon.png, icon-192.png, icon-512.png, favicon.png (image/png),
favicon.ico (image/x-icon) and manifest.webmanifest (application/manifest+json); they are the website icon of the page
(browser tab, Add to Home Screen). The routes below are written without that prefix;
the server answers them at /ACESCT/api/... (for example GET /ACESCT/api/state). A small JSON API:
  GET  /api/state       work folder, base car, game running, installed package, background job; every car of the game
                        (id, label, display_name, extracted, tested, new_id, installed; an extracted car also "variants": id, label, error of its
                        other mechanical presets that swap physics files, shown read-only by /api/settings?variant=<id>) and the number of applicable and
                        hidden settings of the car (null while the base is missing or being extracted); the selected
                        tune ("tune"); the modded cars of all stock cars ("modded": id, stock, label, name_suffix,
                        default, installed, built; "modded_error" and an empty list when they cannot be read);
                        "default_tune_taken" (the default tune of this car exists), "proposed_new_id" (the id the next
                        modded car made from the draft gets, null when none is free) and "proposed_suffix" (its name
                        suffix); "installed" is the package of the selected modded car
  GET  /api/settings    every setting applicable to the car, with default, current value and changed flag
                        (copies_differ, plus copy_values when the copies of the value differ in the stock data;
                        "ui": "header" on name_suffix: the page shows it under its title, not in the table;
                        "base_range": {"low", "high"}, the lowest and highest default of the setting over the installed
                        cars from <work>/ranges.json (written by tune.py ranges), only on the settings that have an entry
                        there: a soft border for the page, values outside it stay allowed; "min" and "max" are the
                        catalogue's allowed limits and a different thing)
                        ?variant=<variant id> (optional, only for the stock car: no tune or "draft") answers the rows of the stock car
                        resolved with that variant's files, value = default and changed false, nothing saved is read; 400 for an
                        unknown or unreadable variant and for a variant together with a modded car; no POST route takes a variant
  GET  /api/groups      the setting groups of the catalogue in display order ("groups": name, description); static data,
                        the same for every car and tune, needs no base car
  versions              GET /api/state of a modded car also answers "versions" ([{id, name}], empty for a stock car and the draft) and
                        "mod_paths" ({package, versions_folder, state}: where the installed package, the folder of the versions and
                        the state file of the tune live; null for a stock car and the draft). The routes /api/settings, /api/set,
                        /api/unset, /api/reset_all, /api/garage, /api/garage_set, /api/garage_reset, /api/turbo, /api/turbo_set,
                        /api/turbo_reset, /api/sounds, /api/sound_set and /api/sound_reset take an optional "version" (an id of
                        "versions": query parameter for GET, body field or query parameter for POST; empty is the base) and then work on
                        that version's state; 400 for a version without a modded car, for an unknown version and for a meta or shared
                        setting (name suffix, steer_rod_ratio, ff_mult, ...: "shared": true in its row, also on the base) of a version,
                        which all versions share; POST /api/set and /api/unset of one answer 400 "<id> is shared by all versions, set it on the base". reset_all with a version clears only that version.
  POST /api/version_add {"tune": ..., "name": ..., "from": version id (optional, default the base)}   adds a version as a copy
                        of the base (or of version "from"); answers {"id"}
  POST /api/version_rename {"tune": ..., "version": ..., "name": ...}   answers {"id", "name"}; there is no route that deletes a version
  POST /api/version_lock   {"tune": ..., "version": ...}   locks a version (its kept build must match its state: 400 "Apply first, then lock it"
                        otherwise); answers {"id", "name"}; a locked version refuses every write of its state with 400 "... is locked ..."
  POST /api/version_unlock {"tune": ..., "version": ...}   unlocks a version; answers {"id", "name"}
  POST /api/set        {"id": ..., "value": ...}          POST /api/unset  {"id": ...}
                        (value: text, number, or true/false for the settings of type bool, which are on/off switches
                        and appear in the rows with type "bool" and true/false as default and value)
  POST /api/reset_all   clears every changed value         POST /api/init   extracts the stock car (background job)
  POST /api/duplicate   {"tune": source, "new_id": ..., "suffix": ...}   copies a modded car or the draft to a new modded
                        car (new_id and suffix are optional, automatic when left out); answers {"id", "stock", "name_suffix"}
  POST /api/apply       {"tune": ..., "new_id": ..., "suffix": ...}   builds and installs (background job): a modded car
                        (without "tune": the default one, which must exist) is updated, the draft ("tune": "draft") creates a new modded car (new_id and suffix are optional,
                        automatic when left out; ignored when a modded car is updated) and builds it, the draft is
                        cleared after a successful build; the job result has new_id, tune, name_suffix, created and
                        changes ({"since": "last build" or null for a first build, "settings": [{id, from, to}], "extras":
                        [{kind turbo_kit / garage / sound, slot, from, to, text}], "total"}: what differs from the last build
                        of that modded car, everything compared to the stock car on its first build, see tune.py apply); the
                        job log lists these changes (not every setting) and the notes of the build
  GET  /api/tyres       the tyre library ("tyres": id, name, source {front, rear}, changed; {id, error} for a damaged file) and
                        the tyre pairs the extracted cars offer ("sources": key, front, rear, label, cars)
  GET  /api/tyre?id=<tyre id>
                        one library tyre ("tyre": id, name, source, changed) and its settings ("rows": the tyre settings with
                        axle, default, value, changed, applicable and reason); 400 for an unknown id
  POST /api/tyre_new    {"name": ..., "source": key}      creates a library tyre; answers {"tyre": {id, name, source}}
  POST /api/tyre_rename {"id": ..., "name": ...}          POST /api/tyre_source {"id": ..., "source": key}
                        both answer {"tyre": {id, name, source, changed}}
  POST /api/tyre_set    {"id": ..., "setting": ..., "value": ...}   (value as for /api/set) answers {"row", "warnings"}
  POST /api/tyre_unset  {"id": ..., "setting": ...}       answers {"row"}
  POST /api/tyre_reset  {"id": ...}                       drops the changed values of the tyre; answers {"ok": true}
  POST /api/tyre_delete {"id": ...}                       removes the tyre (409 while a modded car or the draft selects it);
                        answers {"ok": true}
  GET  /api/garage      the tyre selection of the car and the tune: "choices" (key, kind own or stock, label, ticked, start),
                        "custom", "missing", "car" and "tune"; needs the base car
  POST /api/garage_set  {"keys": [text, ...]}             ticks exactly these tyres (own:<tyre id>, stock:<front>|<rear>);
                        answers {"result": {keys, start, maybe default}, "garage": the answer of GET /api/garage}
  POST /api/garage_reset  {}                              removes the selection; answers {"removed", "garage"}
  GET  /api/turbo       the turbo kit of the car and the tune (the turbo setup of another installed car, the donor, built into
                        a modded car that has none): "donor" (saved donor car id or null), "available" (false when the car has a
                        turbo itself or no donor exists) with "reason", "donors" (car, label, count, kind "single turbo" / "twin
                        turbo" / "<n> turbos", boost in bar, one value per turbo file; boost_ref, the engine's reference value
                        in bar or null, when boost is empty; never the car itself), "picked" (the entry of the saved donor, null
                        when it has none or is not offered any more), "car", "tune" and "has_turbo" (the car has a turbo itself);
                        needs the base car
  POST /api/turbo_set   {"donor": car id}                 chooses the donor; answers {"result": {donor, count, kind, boost, boost_ref},
                        "turbo": the answer of GET /api/turbo, "sounds", "sound_link"}: the turbo sound follows the donor, so
                        after the donor is stored the turbo sound of the car and tune is set to the donor's own turbo sound
                        (tune.sound_own; the stored choice is removed when it is the car's own sound); "sound_link" is
                        {"slot": "turbo", "key": the donor's turbo sound} and "sounds" the answer of GET /api/sounds then; both are
                        null when the donor has no turbo entry (nothing is changed); a problem of the sound step never fails the
                        donor choice: "sound_link" is {"error": text} and "sounds" null
  POST /api/turbo_reset {}                                removes the choice; answers {"removed", "turbo"}; the sound choice stays
                        A tune with a turbo kit shows the turbo settings in /api/settings (read from the kit built on that read)
                        and builds with the donor's turbo, so the page must read the settings again after every change of the
                        kit; /api/settings answers 400 with the "turbo kit: ..." message when the kit cannot be built (the donor
                        is gone, the car has a turbo).
  GET  /api/sounds      the sound picker of the car and the tune: "slots" ("turbo" and "backfire", each {"options": the sounds
                        the installed cars offer (key, event, bank, optional, cars), "own": the key of the car's own sound or null
                        when it has no entry of the slot, "selected": the key of the saved choice or null}), "missing" (saved
                        choices that are not offered any more: slot, key), "skipped" (cars whose .actor file could not be read:
                        car, reason), "car" and "tune"; needs the base car
  POST /api/sound_set   {"slot": "turbo" | "backfire", "key": option key or null}   sets the sound of the slot (null or the car's
                        own sound removes the choice); answers the new sounds like GET /api/sounds
  POST /api/sound_reset {"slot": optional}                removes the choice of that slot, without "slot" of every slot; answers
                        the new sounds like GET /api/sounds
  GET  /api/log_config  the choice of the session logger (tools/logconf.py): "rate_hz" (30 or 60), "rates" ([30, 60]) and "groups":
                        the setting groups of the catalogue in display order (id "catalogue.<group name>", name, description, rows:
                        id, label, unit, status direct / indirect / none, note, tickable, ticked, once, live), then the extra groups
                        (id, name, description, default, rows: id "<group id>.<row id>", label, description, tickable, ticked,
                        status "extra", note, once, live); only the direct settings and the extra rows are tickable; the choice is
                        <work>/log_config.json, the default choice when it is missing or invalid
  POST /api/log_config_set  {"ticked": [ids], "rate_hz": 30 | 60}   saves the choice (400, nothing written, for an unknown, greyed
                        or doubled id or another rate); answers like GET /api/log_config
  POST /api/log_config_reset  {}                          removes <work>/log_config.json (a missing file is fine), so the default
                        choice applies again; answers like GET /api/log_config
  GET  /api/log_sessions  "sessions": the newest 20 session files of the logs folder (file, size, modified, car, track, duration_s,
                        samples; the last four are null for a file without header or end line), newest first
  GET  /api/log_status  whether the logger runs: running, state ("not running", "waiting" or "logging"), file, samples, started,
                        seconds; read from <logs>/logger_status.json, "not running" when it is missing, damaged or older than 5 s
  POST /api/logger_start  {}                              starts tools/logger.py in the background (own process group, no console
                        window, it outlives the page and the server; its console output is appended to <logs>/logger_console.log)
                        with this server's work, mods and logs folders; answers {"started": true, "pid": ...} at once, without
                        waiting for the logger; 409 when the logger already runs (per the status file, or started by this server and still alive), 400 when the PC is not
                        Windows, 500 when it cannot be started
  POST /api/logger_stop   {}                              asks the running logger to stop (creates <logs>/logger_stop); answers
                        {"stopping": true}; 409 when the logger is not running
  GET  /api/log_ai_command  the AI command ("text") built from tuner/log_ai_command.txt, tuner/log_glossary.json and the rows of the
                        Logging tab, and its "size" in bytes (utf-8)
  GET  /api/log_file?file=<name>  one session file of the logs folder as text: "file", "size" (bytes) and "text" (utf-8); 400 for a
                        name that is not a plain file name ending in .jsonl, 404 for a missing file, 413 (the file is not read) for a
                        file larger than 1 MB (1048576 bytes)
  POST /api/log_copy    {"file": <name>}                  puts the session file on the clipboard of the PC (Windows, PowerShell
                        Set-Clipboard: pasting attaches the file); answers {"copied": true, "file": name, "how": "file"}; 403 for
                        a client that is not loopback (127.0.0.1 or ::1), 400 for a bad name or when the PC is not Windows, 404 for a
                        missing file, 500 with the PowerShell error text when the copy fails
The tyre library is shared by all cars: its routes ignore the car and the tune and need no base car; so do /api/groups and the ten
log routes (the choice lives in the work folder, the sessions and the status in the logs folder); the two logger routes and the three
file routes do not wait for and are not refused by a running job.
Every route takes an optional car id of the game (the list is cached in <work>/cars_index.json, see tune.py; without it
and without the game package only the tested cars of tuner/cars.json): the query parameter ?car=<id> on GET, the field
"car" in the JSON body on POST (any other id is a 400 error). Without it the default car of tuner/cars.json is used.
Every route also takes an optional tune next to the car (?tune=<x> on GET, the field "tune" on POST): absent or null is
the default tune of the car (the modded car <new_id>), "draft" the draft of the base car (the values of the base car
that are not saved as a modded car yet), any other value the id of a modded car of that car (400 otherwise).

Answers: JSON {"error": text} with 400 (bad input, unknown car or modded car, malformed JSON, new id or name suffix refused), 403 (client address that is not private, wrong Host, missing X-Tuner, a client that is not loopback on /api/log_copy), 404 (unknown path, missing session file), 405 (PUT, DELETE, PATCH, OPTIONS and HEAD, with the header Allow: GET, POST; any other method name and any malformed request get the standard HTML error page of http.server: 501, 400, 414, 431), 413 (body over 65536 bytes, session file over 1 MB on /api/log_file), 415 (Content-Type is not application/json), 409 (base car missing, another job running, edit or duplicate while a job runs, tyre library, garage, turbo kit or sound edit while a job runs, tyre deleted while a modded car selects it, game running, mods folder not expandable), 500 (internal error); /api/init and /api/apply answer 202 {"job": "started"} and the page polls GET /api/state; every other route answers 200.

The job state (GET /api/state "job") is global, there is one background job at a time for all cars. The state answer
also lists the car ("car", "cars") and the installed package of the selected modded car; the old single-car layout of the work folder
is moved into the default car's folder when the server starts.
No PIN or login: only private networks may connect. A request is refused with 403 when the address of the client is not
loopback or private (IPv4 only: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12 and 192.168.0.0/16, and also what the ipaddress module of Python
treats as private and not global, here Python 3.13, so the list depends on the Python version: 169.254.0.0/16 link-local, 0.0.0.0/8 except
0.0.0.0, 192.0.0.0/24 except 192.0.0.9 and 192.0.0.10, 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24 documentation, 198.18.0.0/15
benchmarking, 240.0.0.0/4 reserved with 255.255.255.255; refused: 0.0.0.0, 100.64.0.0/10 (carrier-grade NAT, Tailscale), every public
address and every IPv6 address), and when the Host header is not <name>:<port> with the
configured port and a name that is localhost, a loopback or private IPv4 address, or the host name of this PC. Every POST
needs the header X-Tuner: 1 and Content-Type application/json. One background job at a time; its state is kept until the
next job starts. Apply refuses to run while AssettoCorsaEVO.exe is running.
At start the server prints http://<address>:<port>/ACESCT/ (the --bind address, 127.0.0.1 when it listens on all addresses)
and, when it listens on all addresses, one line per private IPv4 address of the PC: the address to open on the phone.
<work> defaults to %USERPROFILE%\\ace_modded_cars_work, <mods> to %USERPROFILE%\\Saved Games\\ACE\\mods, <logs> to the folder
logs of the repository (the session files of the logger), <game> to the Steam default content.kspkg (see tune.py). Wrong arguments print the usage block and exit 2.
Ctrl+C while a job runs waits for it; a second Ctrl+C aborts it.

Stdlib only.
"""
import contextlib
import copy
import datetime
import http.server
import ipaddress
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import clone_car  # noqa: E402
import kspkg  # noqa: E402
import logconf  # noqa: E402
import tune  # noqa: E402

INDEX = tune.REPO / "tuner" / "web" / "index.html"
WEB = INDEX.parent
LOGGER = tune.REPO / "tools" / "logger.py"
LOGGER_CONSOLE = "logger_console.log"
STATIC_FILES = {"/apple-touch-icon.png": (WEB / "apple-touch-icon.png", "image/png"),
                "/icon-192.png": (WEB / "icon-192.png", "image/png"),
                "/icon-512.png": (WEB / "icon-512.png", "image/png"),
                "/favicon.png": (WEB / "favicon.png", "image/png"),
                "/favicon.ico": (WEB / "favicon.ico", "image/x-icon"),
                "/manifest.webmanifest": (WEB / "manifest.webmanifest", "application/manifest+json")}
DEFAULT_PORT = 8090
DEFAULT_BIND = "0.0.0.0"
BASE_PATH = "/ACESCT"
GAME_CHECK_SECONDS = 15.0
MAX_BODY = 65536
# routes that start a background job answer 202 instead of 200
ACCEPTED = ("/api/init", "/api/apply")
# GET routes that take the raw query string as a third argument
QUERY_ROUTES = ("/api/tyre", "/api/log_file")
# GET routes that take the raw query string for the optional parameter variant (a preset of the car, shown read-only)
VARIANT_ROUTES = ("/api/settings",)
# routes that work on a version of a modded car when "version" is given (query parameter for GET, body field for POST)
VERSION_GET_ROUTES = ("/api/settings", "/api/garage", "/api/turbo", "/api/sounds")
VERSION_POST_ROUTES = ("/api/set", "/api/unset", "/api/reset_all", "/api/garage_set", "/api/garage_reset", "/api/turbo_set",
                       "/api/turbo_reset", "/api/sound_set", "/api/sound_reset")
# POST routes that only a client on the PC itself (loopback) may call
LOCAL_ROUTES = ("/api/log_copy",)
LOG_FILE_MAX = 1048576
CLIPBOARD_TIMEOUT = 15

CONFIG = {"port": DEFAULT_PORT, "work": None, "mods": None, "logs": None, "game": tune.DEFAULT_GAME}
JOB = {"kind": None, "state": "idle", "log": [], "result": None, "error": None, "thread": None}
JOB_LOCK = threading.Lock()
# STATE_LOCK serializes tune_state.json edits and row builds; JOB_LOCK guards the JOB dict (the job thread takes STATE_LOCK only to clear the draft)
STATE_LOCK = threading.Lock()
# the poll path asks for the game at most every GAME_CHECK_SECONDS (longer than the idle poll of the page); Apply always asks fresh: [time of the last check, its result]
GAME_CHECK = [float("-inf"), False]
# the logger process this server started (a list so that it can be replaced) and the lock that makes the check and the start of api_logger_start one step
LOGGER_PROC = [None]
LOGGER_LOCK = threading.Lock()
# the variants of a car as api_state lists them, cached per (work, car): (variants_stamp, [{"id", "label", "error"}]); VARIANTS_LOCK guards the dict
VARIANTS = {}
VARIANTS_LOCK = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status
        self.message = message


@contextlib.contextmanager
def bad_input():
    try:
        yield
    except ValueError as e:
        raise ApiError(400, str(e)) from None


def mods_dir():
    return clone_car.expand(CONFIG["mods"] or clone_car.DEFAULT_MODS)


def require_mods():
    try:
        return mods_dir()
    except ValueError:
        raise ApiError(409, "cannot expand the mods folder %r (pass --mods <folder>)" % (CONFIG["mods"] or clone_car.DEFAULT_MODS)) from None


def base_present(work, car_id):
    car_root = kspkg.long_path(tune.car_root_of(tune.base_dir(work, car_id), car_id))
    return os.path.isdir(car_root) and bool(os.listdir(car_root))


def logs_dir():
    try:
        return clone_car.expand(CONFIG["logs"] or logconf.default_logs_dir())
    except ValueError:
        raise ValueError("cannot expand the logs directory %r (pass --logs <folder>)" % (CONFIG["logs"] or logconf.default_logs_dir())) from None


def require_base(work, car_id):
    if not base_present(work, car_id):
        raise ApiError(409, "base car missing, run init")


game_running = tune.game_running


def game_running_cached():
    now = time.monotonic()
    if now - GAME_CHECK[0] > GAME_CHECK_SECONDS:
        GAME_CHECK[:] = [now, game_running()]
    return GAME_CHECK[1]


def installed_info(car_id, tune_id=None):
    path = os.path.join(mods_dir(), (tune.new_id_for(car_id) if tune_id in (None, tune.DRAFT) else tune_id) + ".kspkg")
    info = {"path": path, "exists": os.path.isfile(path), "bytes": None, "modified": None}
    if info["exists"]:
        st = os.stat(path)
        info["bytes"] = st.st_size
        info["modified"] = datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
    return info


def job_snapshot():
    with JOB_LOCK:
        return {"kind": JOB["kind"], "state": JOB["state"], "log": list(JOB["log"]),
                "result": JOB["result"], "error": JOB["error"]}


def claim_job(kind):
    with JOB_LOCK:
        if JOB["state"] == "running":
            raise ApiError(409, "another job is running, wait until it has finished")
        previous = {k: JOB[k] for k in ("kind", "state", "log", "result", "error")}
        JOB.update(kind=kind, state="running", log=[], result=None, error=None)
    return previous


def release_job(previous):
    with JOB_LOCK:
        JOB.update(previous)


def log_line(text):
    with JOB_LOCK:
        JOB["log"].append(text)


def finish_job(state, result=None, error=None):
    with JOB_LOCK:
        JOB.update(state=state, result=result, error=error)


def job_thread(task):
    try:
        result = task()
    except (ValueError, OSError) as e:
        log_line("error: %s" % e)
        finish_job("error", error=str(e))
    except SystemExit as e:
        log_line("error: %s" % e.code)
        finish_job("error", error=str(e.code))
    except Exception as e:
        traceback.print_exc()
        log_line("error: internal error: %s" % e)
        finish_job("error", error="internal error: %s" % e)
    else:
        finish_job("done", result)


def start_job(task):
    thread = threading.Thread(target=job_thread, args=(task,), daemon=True)
    with JOB_LOCK:
        JOB["thread"] = thread
    thread.start()


def run_job(kind, task):
    claim_job(kind)
    start_job(task)


def refuse_while_job_runs():
    if job_snapshot()["state"] == "running":
        raise ApiError(409, "a job is running, wait until it has finished")


def init_task(car_id):
    def task():
        log_line("extracting the stock car from the game package (about 20 s) ...")
        res = tune.init(CONFIG["work"], car_id, CONFIG["game"])
        log_line("base already present" if res["present"] else "extracted the stock car")
        log_line("%s: %d files, %d folders, %d bytes" % (res["dir"], res["files"], res["dirs"], res["bytes"]))
        return res
    return task


def apply_lines(res):
    lines = tune.change_lines(res)
    lines.append("package: %s (%d bytes)" % (res["package"], res["size"]))
    if res["installed"]:
        lines.append("installed: %s" % res["installed"])
        lines.append("backup: %s" % (res["backup"] or "no previous install"))
    return lines


def apply_task(car_id, new_id, created):
    def task():
        log_line("building %s, this takes a while ..." % new_id)
        res = tune.apply(CONFIG["work"], car_id, new_id, True, CONFIG["mods"], game=CONFIG["game"])
        for line in apply_lines(res):
            log_line(line)
        if created:
            with STATE_LOCK:
                tune.save_state(CONFIG["work"], car_id, {}, tune.DRAFT)
        return dict(res, created=created)
    return task


def row_json(row, setting, base_range=None):
    out = {k: row[k] for k in ("id", "group", "label", "kind", "type", "unit", "description", "verified",
                               "default", "value", "changed", "absent", "copies_differ")}
    out.update({k: setting[k] for k in ("min", "max", "choices", "ui", "advanced", "shared") if k in setting})
    if row["copies_differ"]:
        out["copy_values"] = row["copy_values"]
    if base_range:
        out["base_range"] = {"low": base_range["low"], "high": base_range["high"]}
    return out


def rows_json(work, car_id, cat, tune_id=None, version=None):
    require_base(work, car_id)
    ranges = tune.load_ranges(work)
    return [row_json(r, tune.find_setting(cat, r["id"]), ranges.get(r["id"]))
            for r in tune.effective_rows(work, car_id, cat, tune=tune_id, version=version)]


def row_of(work, car_id, cat, setting_id, tune_id=None, version=None):
    require_base(work, car_id)
    return row_json(tune.effective_row(work, car_id, setting_id, cat, tune=tune_id, version=version), tune.find_setting(cat, setting_id),
                    tune.load_ranges(work).get(setting_id))


def settings_counts(work, car_id):
    job = job_snapshot()
    if not base_present(work, car_id) or (job["kind"] == "init" and job["state"] == "running"):
        return None, None
    rows = tune.resolve_defaults(work, car_id, hidden=True)
    applicable = sum(1 for r in rows if r["applicable"])
    return applicable, len(rows) - applicable


def or_none(fn, *args):
    try:
        return fn(*args)
    except ValueError:
        return None


def tune_proposals(work, car_id):
    try:
        taken = any(t["default"] for t in tune.list_tunes(work, car_id))
    except ValueError:
        return {"default_tune_taken": False, "proposed_new_id": None, "proposed_suffix": None}
    new_id = or_none(tune.free_tune_id, work, car_id, mods_dir()) if taken else tune.new_id_for(car_id)
    return {"default_tune_taken": taken, "proposed_new_id": new_id,
            "proposed_suffix": or_none(tune.free_suffix, work, car_id, tune.name_suffix_setting()["default"])}


def modded_cars(work):
    try:
        return {"modded": tune.list_modded(work, mods_dir())}
    except ValueError as e:
        return {"modded": [], "modded_error": str(e)}


def variants_stamp(work, car_id):
    """The (folder, name, mtime_ns, size) of every file below the presets folder and the parts folder of the extracted car (what
    list_variants reads), None when they cannot be listed."""
    car_root = tune.car_root_of(tune.base_dir(work, car_id), car_id)
    stamp = []
    try:
        for rel in ("presets", "data/parts"):
            for folder, dirs, names in os.walk(kspkg.long_path(tune.find_ci(car_root, rel))):
                dirs.sort()
                for name in sorted(names):
                    st = os.stat(os.path.join(folder, name))
                    stamp.append((folder, name, st.st_mtime_ns, st.st_size))
    except (ValueError, OSError):
        return None
    return stamp


def variants_of(work, car_id):
    """The variants of an extracted car as the page lists them ([{"id", "label", "error"}]), cached per (work, car) while
    variants_stamp is unchanged; [] for a car without variants or when they cannot be read."""
    stamp, key = variants_stamp(work, car_id), (work, car_id)
    with VARIANTS_LOCK:
        hit = VARIANTS.get(key)
    if hit and stamp is not None and hit[0] == stamp:
        return copy.deepcopy(hit[1])
    try:
        found = [{k: v[k] for k in ("id", "label", "error")} for v in tune.list_variants(work, car_id)]
    except (ValueError, OSError):
        return []
    if stamp is not None and variants_stamp(work, car_id) == stamp:
        with VARIANTS_LOCK:
            VARIANTS[key] = (stamp, copy.deepcopy(found))
    return found


def car_entry_json(work, c):
    entry = {k: c[k] for k in ("id", "label", "display_name", "extracted", "tested", "new_id", "installed")}
    if c["extracted"]:
        entry["variants"] = variants_of(work, c["id"])
    return entry


def mod_info(work, car_id, tune_id):
    """The versions of the selected modded car and where its files live: {"versions": [{id, name}], "mod_paths": {package,
    versions_folder, state}}; empty versions and no paths for the base car and the draft."""
    if tune_id in (None, tune.DRAFT):
        return {"versions": [], "mod_paths": None}
    try:
        versions = tune.list_versions(work, car_id, tune_id)
    except (ValueError, OSError):
        versions = []
    return {"versions": versions,
            "mod_paths": {"package": os.path.join(mods_dir(), tune_id + ".kspkg"),
                          "versions_folder": tune.version_dir(work, car_id, tune_id),
                          "state": tune.state_path(work, car_id, tune_id)}}


def api_state(car_id, tune_id):
    require_mods()
    work, cars = CONFIG["work"], tune.load_cars()
    applicable, hidden = settings_counts(work, car_id)
    return dict(mod_info(work, car_id, tune_id), **{"work": work, "car": car_id, "tune": tune_id, "default_car": cars["default"],
                 "cars": [car_entry_json(work, c) for c in tune.list_cars(work, CONFIG["mods"], game=CONFIG["game"], sizes=False)],
                 "base_present": base_present(work, car_id), "game_running": game_running_cached(),
                 "installed": installed_info(car_id, tune_id), "stock_id_length": len(car_id),
                 "default_new_id": tune.new_id_for(car_id), "settings_applicable": applicable, "settings_hidden": hidden,
                 "job": job_snapshot()}, **modded_cars(work), **tune_proposals(work, car_id))


def variant_rows_json(work, car_id, cat, variant):
    require_base(work, car_id)
    ranges = tune.load_ranges(work)
    return [row_json(dict(r, value=r["default"], changed=False), tune.find_setting(cat, r["id"]), ranges.get(r["id"]))
            for r in tune.resolve_defaults(work, car_id, cat, variant=variant)]


def api_settings(car_id, tune_id, query, version=None):
    variant = (urllib.parse.parse_qs(query).get("variant") or [None])[0]
    if variant is not None and tune_id not in (None, tune.DRAFT):
        raise ApiError(400, "a variant cannot be combined with a modded car")
    with STATE_LOCK, bad_input():
        if variant is not None:
            return variant_rows_json(CONFIG["work"], car_id, tune.load_catalogue(), variant)
        return rows_json(CONFIG["work"], car_id, tune.load_catalogue(), tune_id, version)


def api_groups(car_id, tune_id):
    return {"groups": tune.group_list()}


def api_set(car_id, body):
    work, cat, tune_id, version = CONFIG["work"], tune.load_catalogue(), body.get("tune"), body.get("version")
    setting_id, value = body.get("id"), body.get("value")
    if not isinstance(setting_id, str) or type(value) not in (str, int, float, bool):
        raise ApiError(400, "need id (text) and value (text, number or true/false)")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK:
        try:
            res = tune.set_value(work, car_id, setting_id, value, cat, tune=tune_id, version=version)
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        return {"row": row_of(work, car_id, cat, setting_id, tune_id, version), "warnings": res["warnings"]}


def api_unset(car_id, body):
    work, cat, tune_id, version = CONFIG["work"], tune.load_catalogue(), body.get("tune"), body.get("version")
    setting_id = body.get("id")
    if not isinstance(setting_id, str):
        raise ApiError(400, "need id (text)")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK:
        try:
            tune.unset_value(work, car_id, setting_id, cat, tune=tune_id, version=version)
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        return {"row": row_of(work, car_id, cat, setting_id, tune_id, version)}


def api_reset_all(car_id, body):
    work, tune_id, version = CONFIG["work"], body.get("tune"), body.get("version")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK:
        state = {}
        if version is not None:
            with bad_input():
                tune.save_version_state(work, car_id, state, version, tune_id)
            return {"ok": True}
        if tune.is_extra_tune(car_id, tune_id):
            suffix_id = tune.name_suffix_setting()["id"]
            kept = tune.load_state(work, car_id, tune_id)
            if suffix_id in kept:
                state[suffix_id] = tune.legacy_suffix(kept[suffix_id])
        tune.save_state(work, car_id, state, tune_id)
    return {"ok": True}


def version_name_text(body):
    name = body.get("name")
    if not isinstance(name, str):
        raise ApiError(400, "need name (text)")
    return name


def api_version_add(car_id, body):
    work, tune_id, source = CONFIG["work"], body.get("tune"), optional_text(body, "from")
    name = version_name_text(body)
    if tune_id in (None, tune.DRAFT):
        raise ApiError(400, "a version needs a modded car")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return {"id": tune.add_version(work, car_id, name, tune_id, source or None)}


def api_version_rename(car_id, body):
    work, tune_id, version = CONFIG["work"], body.get("tune"), body.get("version")
    name = version_name_text(body)
    if not isinstance(version, str):
        raise ApiError(400, "need version (text)")
    if tune_id in (None, tune.DRAFT):
        raise ApiError(400, "a version needs a modded car")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return {"id": version, "name": tune.rename_version(work, car_id, version, name, tune_id)}


def api_version_lock(car_id, body):
    work, tune_id, version = CONFIG["work"], body.get("tune"), body.get("version")
    if not isinstance(version, str):
        raise ApiError(400, "need version (text)")
    if tune_id in (None, tune.DRAFT):
        raise ApiError(400, "a version needs a modded car")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return {"id": version, "name": tune.lock_version(work, car_id, version, tune_id)}


def api_version_unlock(car_id, body):
    work, tune_id, version = CONFIG["work"], body.get("tune"), body.get("version")
    if not isinstance(version, str):
        raise ApiError(400, "need version (text)")
    if tune_id in (None, tune.DRAFT):
        raise ApiError(400, "a version needs a modded car")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return {"id": version, "name": tune.unlock_version(work, car_id, version, tune_id)}


def api_init(car_id, body):
    run_job("init", init_task(car_id))
    return {"job": "started"}


def optional_text(body, field):
    value = body.get(field)
    if value is not None and not isinstance(value, str):
        raise ApiError(400, "%s must be text" % field)
    return value


def api_duplicate(car_id, body):
    work, tune_id = CONFIG["work"], body.get("tune")
    new_id, suffix = optional_text(body, "new_id"), optional_text(body, "suffix")
    refuse_while_job_runs()
    require_base(work, car_id)
    mods = require_mods()
    with STATE_LOCK, bad_input():
        return tune.duplicate_tune(work, car_id, tune_id, new_id, suffix, mods)


def update_target(work, car_id, tune_id):
    if tune_id is None:
        tune_id = tune.new_id_for(car_id)
        if not any(t["default"] for t in tune.list_tunes(work, car_id)):
            raise ApiError(400, "no modded car selected, pick one or use the draft of the car to create it")
    with STATE_LOCK:
        suffix = tune.state_suffix(tune.load_state(work, car_id, tune_id), tune.name_suffix_setting())
        owner = tune.suffix_owner(work, car_id, suffix, exclude=tune_id)
    if owner:
        raise ApiError(400, "name suffix %s is already used by %s" % (suffix, owner))
    return tune_id


def new_target(work, car_id, new_id, suffix):
    with STATE_LOCK, bad_input():
        return tune.new_tune_from_draft(work, car_id, suffix, new_id, mods_dir())["id"]


def api_apply(car_id, body):
    work, tune_id = CONFIG["work"], body.get("tune")
    draft = tune_id == tune.DRAFT
    new_id, suffix = (optional_text(body, "new_id"), optional_text(body, "suffix")) if draft else (None, None)
    require_base(work, car_id)
    require_mods()
    if game_running():
        raise ApiError(409, "close the game first, %s is running" % tune.GAME_EXE)
    if draft:
        refuse_while_job_runs()
    previous = claim_job("apply")
    try:
        target = new_target(work, car_id, new_id, suffix) if draft else update_target(work, car_id, tune_id)
    except Exception:
        release_job(previous)
        raise
    start_job(apply_task(car_id, target, draft))
    return {"job": "started"}


def tyre_json(work, tyre_id):
    t = tune.load_tyre(work, tyre_id)
    return {"id": tyre_id, "name": t["name"], "source": {"front": t["source"]["front"], "rear": t["source"]["rear"]},
            "changed": len(t["values"])}


def tyre_row(work, tyre_id, cat, setting_id):
    return next(r for r in tune.tyre_rows(work, tyre_id, cat) if r["id"] == setting_id)


def api_tyres(car_id, tune_id):
    work = CONFIG["work"]
    return {"tyres": tune.list_tyres(work), "sources": tune.list_source_tyres(work)}


def api_tyre(car_id, tune_id, query):
    work, cat = CONFIG["work"], tune.load_catalogue()
    tyre_id = (urllib.parse.parse_qs(query).get("id") or [None])[0]
    if tyre_id is None:
        raise ApiError(400, "need id (text)")
    with STATE_LOCK, bad_input():
        return {"tyre": tyre_json(work, tyre_id), "rows": tune.tyre_rows(work, tyre_id, cat)}


def api_tyre_new(car_id, body):
    work, name, source = CONFIG["work"], body.get("name"), body.get("source")
    refuse_while_job_runs()
    if not isinstance(name, str) or not isinstance(source, str):
        raise ApiError(400, "need name (text) and source (text)")
    with STATE_LOCK, bad_input():
        return {"tyre": tune.create_tyre(work, name, source)}


def api_tyre_rename(car_id, body):
    work, tyre_id, name = CONFIG["work"], body.get("id"), body.get("name")
    refuse_while_job_runs()
    if not isinstance(tyre_id, str) or not isinstance(name, str):
        raise ApiError(400, "need id (text) and name (text)")
    with STATE_LOCK, bad_input():
        tune.rename_tyre(work, tyre_id, name)
        return {"tyre": tyre_json(work, tyre_id)}


def api_tyre_source(car_id, body):
    work, tyre_id, source = CONFIG["work"], body.get("id"), body.get("source")
    refuse_while_job_runs()
    if not isinstance(tyre_id, str) or not isinstance(source, str):
        raise ApiError(400, "need id (text) and source (text)")
    with STATE_LOCK, bad_input():
        tune.set_tyre_source(work, tyre_id, source)
        return {"tyre": tyre_json(work, tyre_id)}


def api_tyre_set(car_id, body):
    work, cat = CONFIG["work"], tune.load_catalogue()
    tyre_id, setting_id, value = body.get("id"), body.get("setting"), body.get("value")
    refuse_while_job_runs()
    if not isinstance(tyre_id, str) or not isinstance(setting_id, str) or type(value) not in (str, int, float, bool):
        raise ApiError(400, "need id (text), setting (text) and value (text, number or true/false)")
    with STATE_LOCK, bad_input():
        res = tune.set_tyre_value(work, tyre_id, setting_id, value, cat)
        return {"row": tyre_row(work, tyre_id, cat, setting_id), "warnings": res["warnings"]}


def api_tyre_unset(car_id, body):
    work, cat = CONFIG["work"], tune.load_catalogue()
    tyre_id, setting_id = body.get("id"), body.get("setting")
    refuse_while_job_runs()
    if not isinstance(tyre_id, str) or not isinstance(setting_id, str):
        raise ApiError(400, "need id (text) and setting (text)")
    with STATE_LOCK, bad_input():
        tune.unset_tyre_value(work, tyre_id, setting_id, cat)
        return {"row": tyre_row(work, tyre_id, cat, setting_id)}


def api_tyre_reset(car_id, body):
    work, tyre_id = CONFIG["work"], body.get("id")
    refuse_while_job_runs()
    if not isinstance(tyre_id, str):
        raise ApiError(400, "need id (text)")
    with STATE_LOCK, bad_input():
        tune.reset_tyre(work, tyre_id)
    return {"ok": True}


def api_tyre_delete(car_id, body):
    work, tyre_id = CONFIG["work"], body.get("id")
    refuse_while_job_runs()
    if not isinstance(tyre_id, str):
        raise ApiError(400, "need id (text)")
    used = False
    with STATE_LOCK:
        try:
            used = tune.tyre_exists(work, tyre_id) and bool(tune.tyre_users(work, tyre_id))
            tune.delete_tyre(work, tyre_id)
        except ValueError as e:
            raise ApiError(409 if used else 400, str(e)) from None
    return {"ok": True}


def garage_json(work, car_id, tune_id, version=None):
    return dict(tune.garage_choices(work, car_id, tune_id, version), car=car_id, tune=tune_id)


def api_garage(car_id, tune_id, version=None):
    work = CONFIG["work"]
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return garage_json(work, car_id, tune_id, version)


def api_garage_set(car_id, body):
    work, tune_id, version, keys = CONFIG["work"], body.get("tune"), body.get("version"), body.get("keys")
    refuse_while_job_runs()
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise ApiError(400, "need keys (a list of text)")
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        result = tune.set_garage(work, car_id, keys, tune_id, version)
        return {"result": result, "garage": garage_json(work, car_id, tune_id, version)}


def api_garage_reset(car_id, body):
    work, tune_id, version = CONFIG["work"], body.get("tune"), body.get("version")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        res = tune.reset_garage(work, car_id, tune_id, version)
        return {"removed": res["removed"], "garage": garage_json(work, car_id, tune_id, version)}


def turbo_json(work, car_id, tune_id, version=None):
    return dict(tune.turbo_choice(work, car_id, tune_id, version), car=car_id, tune=tune_id)


def api_turbo(car_id, tune_id, version=None):
    work = CONFIG["work"]
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return turbo_json(work, car_id, tune_id, version)


def api_turbo_set(car_id, body):
    work, tune_id, version, donor = CONFIG["work"], body.get("tune"), body.get("version"), body.get("donor")
    refuse_while_job_runs()
    if not isinstance(donor, str):
        raise ApiError(400, "need donor (text)")
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        result = tune.set_turbo(work, car_id, donor, tune_id, version)
        sounds, sound_link = turbo_sound_link(work, car_id, donor, tune_id, version)
        return {"result": result, "turbo": turbo_json(work, car_id, tune_id, version), "sounds": sounds, "sound_link": sound_link}


def turbo_sound_link(work, car_id, donor, tune_id, version=None):
    try:
        key = tune.sound_own(work, donor)["turbo"]
        if key is None:
            return None, None
        view = tune.set_sound(work, car_id, "turbo", key, tune_id, version)
    except ValueError as e:
        return None, {"error": str(e)}
    return dict(view, car=car_id, tune=tune_id), {"slot": "turbo", "key": key}


def api_turbo_reset(car_id, body):
    work, tune_id, version = CONFIG["work"], body.get("tune"), body.get("version")
    refuse_while_job_runs()
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        res = tune.reset_turbo(work, car_id, tune_id, version)
        return {"removed": res["removed"], "turbo": turbo_json(work, car_id, tune_id, version)}


def sounds_json(work, car_id, tune_id, version=None):
    return dict(tune.sound_choices(work, car_id, tune_id, version), car=car_id, tune=tune_id)


def api_sounds(car_id, tune_id, version=None):
    work = CONFIG["work"]
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return sounds_json(work, car_id, tune_id, version)


def api_sound_set(car_id, body):
    work, tune_id, version, slot, key = CONFIG["work"], body.get("tune"), body.get("version"), body.get("slot"), body.get("key")
    refuse_while_job_runs()
    if not isinstance(slot, str) or not slot.strip() or not (key is None or isinstance(key, str)):
        raise ApiError(400, "need slot (text) and key (text or null)")
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        return dict(tune.set_sound(work, car_id, slot, key, tune_id, version), car=car_id, tune=tune_id)


def api_sound_reset(car_id, body):
    work, tune_id, version, slot = CONFIG["work"], body.get("tune"), body.get("version"), body.get("slot")
    refuse_while_job_runs()
    if slot is not None and not isinstance(slot, str):
        raise ApiError(400, "slot must be text")
    require_base(work, car_id)
    with STATE_LOCK, bad_input():
        tune.reset_sounds(work, car_id, tune_id, slot, version)
        return sounds_json(work, car_id, tune_id, version)


def log_config_json(chan, config):
    return {"rate_hz": config["rate_hz"], "rates": list(logconf.RATES), "groups": logconf.tree(chan, tune.load_catalogue(), config)}


def api_log_config(car_id, tune_id):
    chan = logconf.load_channels()
    return log_config_json(chan, logconf.load_config(CONFIG["work"], chan))


def api_log_config_set(car_id, body):
    work, ticked, rate = CONFIG["work"], body.get("ticked"), body.get("rate_hz")
    if not isinstance(ticked, list) or not all(isinstance(i, str) for i in ticked) or type(rate) is not int:
        raise ApiError(400, "need ticked (a list of text) and rate_hz (a number)")
    chan = logconf.load_channels()
    with bad_input():
        config = logconf.save_config(work, {"version": logconf.VERSION, "rate_hz": rate, "ticked": ticked}, chan)
    return log_config_json(chan, config)


def api_log_config_reset(car_id, body):
    chan = logconf.load_channels()
    return log_config_json(chan, logconf.reset_config(CONFIG["work"], chan))


def api_log_sessions(car_id, tune_id):
    return {"sessions": logconf.list_sessions(logs_dir())}


def api_log_status(car_id, tune_id):
    return logconf.logger_status(logs_dir())


def api_log_ai_command(car_id, tune_id):
    text = logconf.ai_command(logconf.load_channels(), tune.load_catalogue(), logconf.load_glossary(), logconf.load_ai_template())
    return {"text": text, "size": len(text.encode("utf-8"))}


def log_file_path(name):
    logs = logs_dir()
    try:
        path = logconf.session_file(logs, name)
    except FileNotFoundError as e:
        raise ApiError(404, str(e)) from None
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    if os.path.islink(path):
        raise ApiError(404, "no session file %s" % name)
    return path


def api_log_file(car_id, tune_id, query):
    name = (urllib.parse.parse_qs(query).get("file") or [None])[0]
    if name is None:
        raise ApiError(400, "need file (text)")
    path = log_file_path(name)
    if os.path.getsize(path) > LOG_FILE_MAX:
        raise ApiError(413, "the file is larger than 1 MB: too large to copy as text")
    with open(path, "rb") as f:
        data = f.read()
    return {"file": name, "size": len(data), "text": data.decode("utf-8")}


def copy_file_to_clipboard(path):
    """Puts the file on the Windows clipboard with PowerShell Set-Clipboard (pasting attaches the file); ApiError 500 with the error
    text when that fails."""
    command = "Set-Clipboard -LiteralPath $env:TUNER_CLIP_FILE"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        res = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True,
                             timeout=CLIPBOARD_TIMEOUT, creationflags=flags,
                             env=dict(os.environ, TUNER_CLIP_FILE=path))
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ApiError(500, str(e)) from None
    if res.returncode != 0:
        raise ApiError(500, (res.stderr or "").strip() or "PowerShell failed with exit code %d" % res.returncode)


def api_log_copy(car_id, body):
    name = body.get("file")
    path = log_file_path(name)
    if sys.platform != "win32":
        raise ApiError(400, "copying a file to the clipboard needs Windows")
    copy_file_to_clipboard(path)
    return {"copied": True, "file": name, "how": "file"}


def spawn_logger(work, mods, logs):
    """Starts tools/logger.py in the background (own process group, no console window on Windows) with its console output appended
    to <logs>/logger_console.log; returns the process id."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, LOGGER_CONSOLE), "ab") as console:
        proc = subprocess.Popen([sys.executable, "-I", "-B", str(LOGGER), "--work", work, "--mods", mods, "--logs", logs],
                                cwd=str(tune.REPO), stdin=subprocess.DEVNULL, stdout=console, stderr=subprocess.STDOUT,
                                close_fds=True, creationflags=flags)
    LOGGER_PROC[0] = proc
    return proc.pid


def api_logger_start(car_id, body):
    if sys.platform != "win32":
        raise ApiError(400, "the logger needs Windows")
    logs = logs_dir()
    with LOGGER_LOCK:
        if logconf.logger_status(logs)["running"] or (LOGGER_PROC[0] is not None and LOGGER_PROC[0].poll() is None):
            raise ApiError(409, "the logger already runs")
        logconf.clear_stop(logs)
        return {"started": True, "pid": spawn_logger(CONFIG["work"], mods_dir(), logs)}


def api_logger_stop(car_id, body):
    logs = logs_dir()
    if not logconf.logger_status(logs)["running"]:
        raise ApiError(409, "the logger is not running")
    logconf.request_stop(logs)
    return {"stopping": True}


def request_car(value, query):
    if value is None:
        value = (urllib.parse.parse_qs(query).get("car") or [None])[0]
    if value is not None and not isinstance(value, str):
        raise ApiError(400, "car must be text")
    with bad_input():
        return tune.pick_car(tune.load_cars(), value, tune.load_cars_index(CONFIG["work"], CONFIG["game"]))


def request_tune(value, query, car_id):
    if value is None:
        value = (urllib.parse.parse_qs(query).get("tune") or [None])[0]
    if value is not None and not isinstance(value, str):
        raise ApiError(400, "tune must be text")
    if value is not None and value != tune.DRAFT and value not in [t["id"] for t in tune.list_tunes(CONFIG["work"], car_id)]:
        raise ApiError(400, "unknown modded car %s of %s" % (value, car_id))
    return value


def request_version(value, query, car_id, tune_id):
    if value is None:
        value = (urllib.parse.parse_qs(query).get("version") or [None])[0]
    if value is not None and not isinstance(value, str):
        raise ApiError(400, "version must be text")
    if not value:
        return None
    if tune_id in (None, tune.DRAFT):
        raise ApiError(400, "a version needs a modded car")
    with bad_input():
        known = [v["id"] for v in tune.list_versions(CONFIG["work"], car_id, tune_id)]
    if value not in known:
        raise ApiError(400, "unknown version %s of %s" % (value, tune_id))
    return value


GET_ROUTES = {"/api/state": api_state, "/api/settings": api_settings, "/api/groups": api_groups, "/api/tyres": api_tyres,
              "/api/tyre": api_tyre, "/api/garage": api_garage, "/api/turbo": api_turbo,
              "/api/sounds": api_sounds, "/api/log_config": api_log_config, "/api/log_sessions": api_log_sessions,
              "/api/log_status": api_log_status,
              "/api/log_ai_command": api_log_ai_command, "/api/log_file": api_log_file}
POST_ROUTES = {"/api/set": api_set, "/api/unset": api_unset, "/api/reset_all": api_reset_all,
               "/api/init": api_init, "/api/duplicate": api_duplicate,
               "/api/version_add": api_version_add, "/api/version_rename": api_version_rename,
               "/api/version_lock": api_version_lock, "/api/version_unlock": api_version_unlock,
               "/api/apply": api_apply, "/api/tyre_new": api_tyre_new, "/api/tyre_rename": api_tyre_rename,
               "/api/tyre_source": api_tyre_source, "/api/tyre_set": api_tyre_set, "/api/tyre_unset": api_tyre_unset,
               "/api/tyre_reset": api_tyre_reset, "/api/tyre_delete": api_tyre_delete, "/api/garage_set": api_garage_set,
               "/api/garage_reset": api_garage_reset, "/api/turbo_set": api_turbo_set, "/api/turbo_reset": api_turbo_reset,
               "/api/sound_set": api_sound_set, "/api/sound_reset": api_sound_reset, "/api/log_config_set": api_log_config_set,
               "/api/log_config_reset": api_log_config_reset, "/api/logger_start": api_logger_start, "/api/logger_stop": api_logger_stop, "/api/log_copy": api_log_copy}


def private_ip(text):
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return ip.version == 4 and (ip.is_loopback or ip.is_private) and not ip.is_global and not ip.is_unspecified


# DNS rebinding: a hostile site resolving to a private address sends its own Host header
def check_host(host):
    name, colon, port = (host or "").lower().rpartition(":")
    if not colon or port != str(CONFIG["port"]) or not (name == "localhost" or private_ip(name) or name == socket.gethostname().lower()):
        raise ApiError(403, "forbidden host: open the tuner with the address the console prints (http://<address of the PC>:%d%s/)" % (CONFIG["port"], BASE_PATH))


# only private networks may connect, even though the server listens on every address of the PC
def check_client(address):
    if not private_ip(address):
        raise ApiError(403, "forbidden client address")


def loopback_ip(text):
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def lan_addresses():
    found = []
    try:
        found += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    addresses = []
    for address in found:
        if private_ip(address) and not ipaddress.ip_address(address).is_loopback and address not in addresses:
            addresses.append(address)
    return addresses


# a cross-site form or no-cors fetch cannot send X-Tuner or application/json without a preflight, and no CORS is answered
def check_post_headers(headers):
    if headers.get("X-Tuner") != "1":
        raise ApiError(403, "missing header X-Tuner: 1")
    if headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
        raise ApiError(415, "Content-Type must be application/json")


class Redirect(Exception):
    def __init__(self, status, location):
        Exception.__init__(self, location)
        self.status = status
        self.location = location


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "TunerServer"
    sys_version = ""
    # a client that stops sending is dropped after 30 s instead of holding a thread for ever
    timeout = 30
    body_read = False

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def method_not_allowed(self):
        self.send_payload(405, {"error": "method not allowed"}, {"Allow": "GET, POST"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = method_not_allowed

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if length < 0:
            raise ApiError(400, "bad Content-Length")
        if length > MAX_BODY:
            raise ApiError(413, "request body too large")
        raw = self.rfile.read(length)
        self.body_read = True
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            raise ApiError(400, "body is not valid JSON") from None
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        return body

    # an unread body makes Windows reset the connection, so the client would miss the error response
    def discard_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < length <= MAX_BODY:
            self.rfile.read(length)

    def dispatch(self, method):
        check_client(self.client_address[0])
        check_host(self.headers.get("Host"))
        path, _, query = self.path.partition("?")
        if method == "POST":
            check_post_headers(self.headers)
        if method == "GET" and path == "/":
            raise Redirect(302, BASE_PATH + "/")
        if method == "GET" and path == BASE_PATH:
            raise Redirect(301, BASE_PATH + "/")
        if method == "GET" and path == BASE_PATH + "/":
            with open(INDEX, "rb") as f:
                return 200, f.read()
        path = path[len(BASE_PATH):] if path.startswith(BASE_PATH + "/") else None
        if method == "GET" and path in STATIC_FILES:
            file, ctype = STATIC_FILES[path]
            with open(file, "rb") as f:
                return 200, (f.read(), ctype)
        route = (GET_ROUTES if method == "GET" else POST_ROUTES).get(path)
        if route is None:
            raise ApiError(404, "not found")
        if path in LOCAL_ROUTES and not loopback_ip(self.client_address[0]):
            raise ApiError(403, "the file can only be copied on the PC where the tuner runs")
        if method == "POST":
            body = self.read_body()
            car_id = request_car(body.get("car"), query)
            body["tune"] = request_tune(body.get("tune"), query, car_id)
            if path in VERSION_POST_ROUTES:
                body["version"] = request_version(body.get("version"), query, car_id, body["tune"])
            payload = route(car_id, body)
        else:
            car_id = request_car(None, query)
            tune_id = request_tune(None, query, car_id)
            version = request_version(None, query, car_id, tune_id) if path in VERSION_GET_ROUTES else None
            if path in VARIANT_ROUTES:
                payload = route(car_id, tune_id, query, version)
            elif path in VERSION_GET_ROUTES:
                payload = route(car_id, tune_id, version)
            else:
                payload = route(car_id, tune_id, query) if path in QUERY_ROUTES else route(car_id, tune_id)
        return (202 if path in ACCEPTED else 200), payload

    def handle_request(self, method):
        headers = None
        try:
            status, payload = self.dispatch(method)
        except Redirect as e:
            status, payload, headers = e.status, b"", {"Location": e.location}
        except ApiError as e:
            if method == "POST" and not self.body_read:
                self.discard_body()
            status, payload = e.status, {"error": e.message}
        except (ValueError, OSError) as e:
            status, payload = 500, {"error": str(e)}
        except Exception as e:
            traceback.print_exc()
            status, payload = 500, {"error": "internal error: %s" % type(e).__name__}
        self.send_payload(status, payload, headers)

    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        http.server.BaseHTTPRequestHandler.end_headers(self)

    def send_payload(self, status, payload, headers=None):
        if isinstance(payload, tuple):
            data, ctype = payload
        elif isinstance(payload, bytes):
            data, ctype = payload, "text/html; charset=utf-8"
        else:
            data, ctype = json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # the page polls /api/state every few seconds; keep that out of the console
    def log_request(self, code="-", size="-"):
        if getattr(self, "path", "").partition("?")[0] == BASE_PATH + "/api/state" and str(code) == "200":
            return
        http.server.BaseHTTPRequestHandler.log_request(self, code, size)


class Server(http.server.ThreadingHTTPServer):
    # Windows: no address reuse (another process could take the port), see server_bind; elsewhere the default keeps a restart possible while old connections are in TIME_WAIT
    allow_reuse_address = os.name != "nt"

    def handle_error(self, request, client_address):
        if not issubclass(sys.exc_info()[0], ConnectionError):
            http.server.ThreadingHTTPServer.handle_error(self, request, client_address)

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        http.server.ThreadingHTTPServer.server_bind(self)


def parse_port(text):
    if not text.isdigit() or not 1024 <= int(text) <= 65535:
        raise ValueError("--port must be a number from 1024 to 65535")
    return int(text)


def usage():
    print(__doc__.split("\n\n")[1])
    sys.exit(2)


def wait_for_job():
    thread = JOB["thread"]
    if job_snapshot()["state"] != "running" or thread is None:
        return
    print("a job is still running, wait for it or press Ctrl+C again to abort it ...", flush=True)
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass


def print_urls(bind, port):
    everywhere = bind in ("", DEFAULT_BIND)
    print("tuner running on http://%s:%d%s/" % ("127.0.0.1" if everywhere else bind, port, BASE_PATH), flush=True)
    if everywhere:
        for address in lan_addresses():
            print("reachable in the home network: http://%s:%d%s/" % (address, port, BASE_PATH), flush=True)


def listen(bind, port):
    try:
        return Server((bind, port), Handler)
    except OSError as e:
        sys.exit("error: cannot listen on %s:%d (%s); is the tuner already running? use --port N" % (bind, port, e))


def main():
    try:
        pos, opts = kspkg.parse_args(sys.argv[1:], ("port", "bind", "work", "mods", "logs", "game"))
    except ValueError:
        usage()
    if pos:
        usage()
    try:
        tune.load_catalogue()
        port = parse_port(opts.get("port", str(DEFAULT_PORT)))
        CONFIG.update(port=port, work=tune.work_dir(opts.get("work")), mods=opts.get("mods"), logs=opts.get("logs"),
                      game=os.path.expandvars(opts.get("game", tune.DEFAULT_GAME)))
        logs_dir()
        default_car = tune.load_cars()["default"]
        moved = tune.migrate_old_layout(CONFIG["work"], default_car)
        if moved:
            print("moved the old single-car layout of %s into %s: %s" % (
                CONFIG["work"], tune.car_work(CONFIG["work"], default_car), ", ".join(moved)))
        bind = opts.get("bind", DEFAULT_BIND)
        server = listen(bind, port)
        tune.load_cars_index(CONFIG["work"], CONFIG["game"])
    except (ValueError, OSError) as e:
        sys.exit("error: %s" % e)
    print_urls(bind, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        wait_for_job()
        print("stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
