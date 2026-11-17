r"""Session logger: reads the shared memory of Assetto Corsa EVO next to the game and writes one JSON Lines file per session.

usage: python tools/logger.py [--work DIR] [--mods DIR] [--logs DIR]
  e.g. python tools/logger.py --logs D:\ace_logs

Waits until the game is running, then writes one file logs/<date>_<time>_<car>.jsonl per session: a header (car, track, PC, software,
tuner facts), a static line (the once-only values of the ticked rows, read 2 s after the start, or "moving": true when the car did
not stand), sample lines at the rate of the choice (30 or 60 Hz, only the ticked channels, none while the game is paused) and an end
line. A new file starts when the car, the track or the session changes, or when the game closes; Ctrl+C ends the open session.
--work is the work folder (default %USERPROFILE%\ace_modded_cars_work; the choice of the Logging tab, log_config.json, is read from
it when a session starts), --mods the mods folder of the game (default %USERPROFILE%\Saved Games\ACE\mods; only the file time of
<id>.kspkg is read), --logs the folder of the session files (default: the folder logs of the repository). The "tuner" entry of the
header (tools/logfacts.py) says which modded car of the tuner the game's car name is and holds its effective settings with their
stock defaults, garage tyres, turbo kit, sounds, the data of its last build (snapshot, package file time, changes) and the start time
of the game process; a car that is not found in the work folder has "matched": false and a reason. While it runs the logger writes
<logs>/logger_status.json once a second and removes it when it stops; once a second it also looks for the empty file <logs>/logger_stop (the Logging tab creates it) and, when it is there, deletes it and stops like Ctrl+C does. The game's memory is only read, never written.
Wrong arguments print this usage block and exit 2; a runtime error prints "error: ..." on stderr and exits 1.

Stdlib only.
"""
import contextlib
import ctypes
import datetime
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ace_shm  # noqa: E402
import clone_car  # noqa: E402
import kspkg  # noqa: E402
import logconf  # noqa: E402
import logfacts  # noqa: E402
import tune  # noqa: E402

LOGGER_VERSION = "1.0"
STATUS_EVERY_S = 1.0       # heartbeat of logger_status.json (the page calls it "not running" after logconf.STATUS_MAX_AGE = 5 s)
STALE_S = 5.0              # no new packet this long: reopen the blocks; if that fails the game has closed (our open handle keeps its blocks alive)
STATIC_AFTER_S = 2.0       # the static line is read after the car stood this long, or this long after the start if it never did
STANDING_KMH = 1.0
WAIT_S = 1.0               # step interval while the game is not running
IDLE_S = 0.25              # step interval while the game runs without a live session or while sampling is off (pause, replay)
MAX_SAMPLE_WAIT_S = 0.05   # longest sleep while the next sample is not due yet
POLL_S = 0.001             # a sample is due but the physics packet has not changed: look again after 1 ms
RESYNC_S = 1.0             # more than this behind schedule: drop the missed samples instead of catching up in a burst
SLUG_MAX = 40              # characters of the car name in the file name


def rounded(value):
    """Floats to 3 digits, also inside lists and dicts; everything else as it is."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, list):
        return [rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    return value


def utc_offset(moment):
    """"+01:00" style offset of an aware datetime."""
    seconds = int((moment.utcoffset() or datetime.timedelta(0)).total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    return "%s%02d:%02d" % (sign, seconds // 3600, seconds % 3600 // 60)


def no_facts(car, info):
    return {"matched": False}


def console(text):
    print(text, flush=True)


class Session:
    def __init__(self, key, name, file, start, epoch, period, selection):
        self.key, self.name, self.file = key, name, file
        self.start, self.epoch, self.period = start, epoch, period
        self.once, self.live = selection["once"], selection["live"]
        self.samples = 0
        self.next_sample = start
        self.sample_id = None
        self.standing_since = None
        self.static_done = False
        self.sampling = False


class Logger:
    """One tick per step(). open_source() returns an object with read() (the three blocks) and close(); facts(car, info) gives
    the tuner facts of the header; clock() is a monotonic time in seconds, wall() an aware local datetime, out(text) prints a line."""

    def __init__(self, work, logs, open_source=ace_shm.open_source, facts=None, clock=time.monotonic, wall=None,
                 sleep=time.sleep, out=console, pid=None):
        self.work, self.logs = work, logs
        self.open_source = open_source
        self.facts = facts or no_facts
        self.clock = clock
        self.wall = wall or (lambda: datetime.datetime.now().astimezone())
        self.sleep = sleep
        self.out = out
        self.pid = os.getpid() if pid is None else pid
        self.status_path = os.path.join(logs, logconf.STATUS_FILE)
        self.stop_path = logconf.stop_path(logs)
        self.stop_requested = False
        self.started = self.wall().timestamp()
        self.source = None
        self.session = None
        self.ids = None
        self.changed = 0.0
        self.waiting_noted = False
        self.status_at = float("-inf")

    def step(self):
        """Processes one tick; returns the seconds to wait before the next call."""
        now = self.clock()
        if self.source is None:
            if not self.connect(now):
                self.wait(now)
                return WAIT_S
        physics, graphics, static = self.source.read()
        ids = ace_shm.packet_ids(physics, graphics)
        if ids != self.ids:
            self.ids, self.changed = ids, now
        elif now - self.changed >= STALE_S:
            self.source.close()
            self.source = None
            if not self.connect(now, announce=False):
                self.end("game closed", now)
                self.wait(now)
                return WAIT_S
            physics, graphics, static = self.source.read()
            self.ids = ace_shm.packet_ids(physics, graphics)
        info = ace_shm.session_info(graphics, static)
        live = info["status_name"] == "live"
        key = (info["car"], info["track"], info["session_id"])
        if live and info["car"] and info["track"]:
            if self.session is not None and key != self.session.key:
                self.end("car, track or session changed", now)
            if self.session is None:
                self.begin(key, info, now)
        s = self.session
        if s is None:
            self.status("waiting", None, 0, self.started, now)
            return IDLE_S
        channels = ace_shm.channels(physics, graphics)
        self.write_static(s, channels, now)
        self.write_sample(s, channels, ace_shm.packet_ids(physics, graphics)[0], live, now)
        if self.status("logging", s.name, s.samples, s.epoch, now):
            s.file.flush()
        if s.sampling:
            wait = s.next_sample - now
            return min(MAX_SAMPLE_WAIT_S, wait) if wait > 0 else POLL_S
        return IDLE_S

    def connect(self, now, announce=True):
        try:
            self.source = self.open_source()
        except FileNotFoundError:
            return False
        self.ids, self.changed = None, now
        if announce:
            self.out("game found")
            self.waiting_noted = False
        return True

    def wait(self, now):
        if not self.waiting_noted:
            self.out("waiting for the game ...")
            self.waiting_noted = True
        self.status("waiting", None, 0, self.started, now)

    def status(self, state, name, samples, started, now):
        """Writes logger_status.json when STATUS_EVERY_S have passed; True when it did."""
        if now - self.status_at < STATUS_EVERY_S:
            return False
        self.status_at = now
        tune.save_json(self.status_path, {"state": state, "file": name, "samples": samples, "started": started,
                                          "updated": self.wall().timestamp(), "pid": self.pid})
        self.check_stop()
        return True

    def check_stop(self):
        """A stop file in the logs folder (logconf.STOP_FILE) is deleted and sets stop_requested."""
        if os.path.exists(self.stop_path):
            logconf.clear_stop(self.logs)
            self.stop_requested = True
            self.out("stop requested")

    def session_name(self, moment, car):
        slug = re.sub(r"[^A-Za-z0-9._-]", "_", car)[:SLUG_MAX] or "car"
        stem = "%s_%s" % (moment.strftime("%Y-%m-%d_%H-%M-%S"), slug)
        name, number = stem + ".jsonl", 1
        while os.path.exists(os.path.join(self.logs, name)):
            number += 1
            name = "%s-%d.jsonl" % (stem, number)
        return name

    def tuner_facts(self, car, info):
        try:
            return self.facts(car, info)
        except Exception as e:
            return {"matched": False, "error": str(e)}

    def begin(self, key, info, now):
        chan = logconf.load_channels()
        config = logconf.load_config(self.work, chan)
        selection = logconf.selected_channels(chan, config)
        moment = self.wall()
        os.makedirs(self.logs, exist_ok=True)
        name = self.session_name(moment, info["car"])
        file = open(os.path.join(self.logs, name), "w", encoding="utf-8", newline="\n")
        s = self.session = Session(key, name, file, now, moment.timestamp(), 1.0 / config["rate_hz"], selection)
        self.line(s, {"type": "header", "format": "ace-session-log", "version": 1, "car": info["car"], "track": info["track"],
                      "pc": {"date": moment.strftime("%Y-%m-%d"), "time": moment.strftime("%H:%M:%S"), "utc_offset": utc_offset(moment)},
                      "software": {"game_version": info["game_version"], "layout_version": info["layout_version"],
                                   "logger_version": LOGGER_VERSION,
                                   "config": {"rate_hz": config["rate_hz"], "ticked": config["ticked"],
                                              "once": s.once, "live": s.live}},
                      "tuner": self.tuner_facts(info["car"], info)})
        self.status_at = float("-inf")
        self.out("session started: %s" % name)

    def end(self, reason, now):
        s = self.session
        if s is None:
            return
        self.session = None
        self.line(s, {"type": "end", "reason": reason, "duration_s": round(now - s.start, 3), "samples": s.samples})
        s.file.flush()
        s.file.close()
        self.status_at = float("-inf")
        self.out("session ended: %s, %d samples" % (reason, s.samples))

    def line(self, s, data):
        s.file.write(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n")

    def write_static(self, s, channels, now):
        if s.static_done or not s.once:
            return
        speed = channels["speed_kmh"]
        standing = speed is not None and speed < STANDING_KMH
        if not standing:
            s.standing_since = None
        elif s.standing_since is None:
            s.standing_since = now
        if standing and now - s.standing_since >= STATIC_AFTER_S:
            moving = False
        elif not standing and now >= s.start + STATIC_AFTER_S:
            moving = True
        else:
            return
        s.static_done = True
        self.line(s, {"type": "static", "t": round(now - s.start, 3), "moving": moving,
                      "values": {n: rounded(channels[n]) for n in s.once}})

    def write_sample(self, s, channels, physics_id, live, now):
        s.sampling = live and bool(s.live)
        if not s.sampling or physics_id == s.sample_id or now < s.next_sample:
            return
        if now - s.next_sample > RESYNC_S:
            s.next_sample = now
        sample = {"type": "s", "t": round(now - s.start, 3)}
        sample.update({n: rounded(channels[n]) for n in s.live})
        self.line(s, sample)
        s.samples += 1
        s.sample_id = physics_id
        s.next_sample += s.period

    def run(self):
        timer_resolution(True)
        try:
            logconf.clear_stop(self.logs)
            while not self.stop_requested:
                self.sleep(self.step())
        except KeyboardInterrupt:
            self.out("stopped")
        finally:
            self.close()
            timer_resolution(False)

    def close(self):
        """Ends an open session ("logger stopped"), closes the source and removes the status file."""
        self.end("logger stopped", self.clock())
        if self.source is not None:
            self.source.close()
            self.source = None
        with contextlib.suppress(FileNotFoundError):
            os.remove(self.status_path)


# Python before 3.11 sleeps in 15 ms steps on Windows; 3.11+ has high-resolution timers and this call is then harmless.
def timer_resolution(on):
    """Windows: asks for a 1 ms timer so that short sleeps are short; any failure is ignored."""
    if sys.platform != "win32":
        return
    try:
        winmm = ctypes.WinDLL("winmm")
        (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
    except Exception:
        pass


def logs_dir(arg=None):
    try:
        return clone_car.expand(arg or logconf.default_logs_dir())
    except ValueError:
        raise ValueError("cannot expand the logs directory %r" % (arg or logconf.default_logs_dir())) from None


def mods_dir(arg=None):
    try:
        return clone_car.expand(arg or clone_car.DEFAULT_MODS)
    except ValueError:
        raise ValueError("cannot expand the mods directory %r" % (arg or clone_car.DEFAULT_MODS)) from None


def usage():
    print(__doc__.split("\n\n")[1])
    sys.exit(2)


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        pos, opts = kspkg.parse_args(args, ("work", "mods", "logs"))
    except ValueError:
        usage()
    if pos:
        usage()
    try:
        work = tune.work_dir(opts.get("work"))
        mods = mods_dir(opts.get("mods"))
        logs = logs_dir(opts.get("logs"))
        print("ACE session logger: waiting for the game (Ctrl+C stops); sessions go to %s" % logs, flush=True)
        Logger(work, logs, facts=logfacts.make_facts(work, mods)).run()
    except (ValueError, OSError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
