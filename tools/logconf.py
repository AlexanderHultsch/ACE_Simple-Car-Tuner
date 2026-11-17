"""Channel table and settings of the session logger: tuner/log_channels.json, the saved choice <work>/log_config.json, the session files and the status of the logger process.

Library module of tools/tuner_server.py and the logger (no command line of its own). tuner/log_channels.json names, for every setting of tuner/catalogue.json, whether the game shows it (status "direct": a once-only reading and live values, tickable; "indirect" and "none": greyed, not tickable, "once" and "live" empty and a note) and which channels of tools/ace_shm.py channels() it logs ("once": read once at the start of a session, "live": in every sample). "extra_groups" are groups of tickable rows that are not tuner settings (behaviour values, car state); the id of such a row in a choice is "<group id>.<row id>". A tickable id is a direct setting id or such a row id.
The choice (log_config.json) is {"version": 1, "rate_hz": 30 or 60, "ticked": [tickable ids]}. A missing, damaged or invalid file reads as the default choice: the extra rows whose "default" is true, at 30 Hz.
Session files are logs/*.jsonl, one JSON object per line: the first line has "type": "header" (with "car" and "track"), the last line of a finished session "type": "end" (with "duration_s" and "samples"). The running logger writes logs/logger_status.json = {"state": "waiting" or "logging", "file": text or null, "samples": int, "started": epoch seconds, "updated": epoch seconds, "pid": int}; it counts as running while "updated" is at most STATUS_MAX_AGE seconds old. The empty file logs/logger_stop (STOP_FILE) asks the running logger to stop; the logger deletes it.
tuner/log_glossary.json describes every channel of ace_shm.channels() (unit, meaning, range, notes); tuner/log_ai_command.txt is the text of the AI command with the placeholders {{CHANNELS}} and {{ROWS}}, which ai_command() fills from the glossary and the rows of the Logging tab. session_file() turns the name of a session file into its path (plain names only).

Stdlib only.
"""
import contextlib
import json
import math
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ace_shm  # noqa: E402
import kspkg  # noqa: E402
import tune  # noqa: E402

CHANNELS = tune.REPO / "tuner" / "log_channels.json"
GLOSSARY = tune.REPO / "tuner" / "log_glossary.json"
AI_TEMPLATE = tune.REPO / "tuner" / "log_ai_command.txt"
VERSION = 1
RATES = (30, 60)
DEFAULT_RATE = 30
STATUSES = ("direct", "indirect", "none")
CONFIG_FILE = "log_config.json"
STATUS_FILE = "logger_status.json"
STATUS_MAX_AGE = 5
STOP_FILE = "logger_stop"
SESSION_TAIL = 4096
AI_PLACEHOLDERS = ("{{CHANNELS}}", "{{ROWS}}")
ASCII_FIXES = {"°": "deg", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"'}
GREYED_STATUS_WORDS = (("indirect", "judged only through their effect"), ("none", "not published"))


def channel_names():
    """The channel names of ace_shm.channels() in the order it builds them."""
    return list(ace_shm.channels(b"", b""))


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def check_names(where, entry, known):
    for key in ("once", "live"):
        names = entry.get(key)
        if not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
            raise ValueError("%s: %s must be a list of channel names" % (where, key))
        if len(set(names)) != len(names):
            raise ValueError("%s: %s lists a channel twice" % (where, key))
        unknown = [n for n in names if n not in known]
        if unknown:
            raise ValueError("%s: unknown channel %r in %s" % (where, unknown[0], key))


def validate_setting(sid, entry, known):
    where = "log channels: setting %s" % sid
    if not isinstance(entry, dict):
        raise ValueError("%s: expected an object" % where)
    if entry.get("status") not in STATUSES:
        raise ValueError("%s: status must be one of %s" % (where, ", ".join(STATUSES)))
    if not isinstance(entry.get("note"), str):
        raise ValueError("%s: note must be text" % where)
    check_names(where, entry, known)
    if entry["status"] == "direct":
        if not (entry["once"] or entry["live"]):
            raise ValueError("%s: a direct setting needs at least one channel in once or live" % where)
    else:
        if entry["once"] or entry["live"]:
            raise ValueError("%s: a setting with status %s has no channels (once and live stay empty)" % (where, entry["status"]))
        if not is_text(entry["note"]):
            raise ValueError("%s: a setting with status %s needs a note" % (where, entry["status"]))


def validate_extra_row(r, where, row_ids, known):
    if not isinstance(r, dict) or not is_text(r.get("id")):
        raise ValueError("%s: every row needs an id (text)" % where)
    row_where = "%s: row %s" % (where, r["id"])
    if r["id"] in row_ids:
        raise ValueError("%s: the id is used twice" % row_where)
    row_ids.append(r["id"])
    if not is_text(r.get("label")):
        raise ValueError("%s: needs a label (text)" % row_where)
    if not isinstance(r.get("description"), str):
        raise ValueError("%s: description must be text" % row_where)
    if type(r.get("default")) is not bool:
        raise ValueError("%s: default must be true or false" % row_where)
    check_names(row_where, r, known)


def validate_extra_group(g, known, group_ids):
    if not isinstance(g, dict) or not is_text(g.get("id")):
        raise ValueError("log channels: every extra group needs an id (text)")
    where = "log channels: extra group %s" % g["id"]
    if g["id"] in group_ids:
        raise ValueError("%s: the id is used twice" % where)
    group_ids.append(g["id"])
    if not is_text(g.get("name")):
        raise ValueError("%s: needs a name (text)" % where)
    if not isinstance(g.get("description"), str):
        raise ValueError("%s: description must be text" % where)
    if "default" in g:
        raise ValueError("%s: default is not allowed (it is set in every row)" % where)
    if not isinstance(g.get("rows"), list):
        raise ValueError("%s: needs rows, a list" % where)
    row_ids = []
    for r in g["rows"]:
        validate_extra_row(r, where, row_ids, known)


def validate_channels(chan, catalogue):
    """Raises ValueError with a clear message unless the channel table is valid for the catalogue: version 1; settings has exactly
    the catalogue's setting ids; every status is direct, indirect or none; a direct setting names at least one channel, an
    indirect or none setting has no channels and a note; every channel name is one of ace_shm.channels(); the extra groups
    have unique ids and no group default, texts as names and labels, unique row ids within the group, and a bool default in every row."""
    if not isinstance(chan, dict):
        raise ValueError("log channels: expected an object")
    if type(chan.get("version")) is not int or chan["version"] != VERSION:
        raise ValueError("log channels: version must be %d" % VERSION)
    settings = chan.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("log channels: needs settings, an object with one entry per setting id")
    wanted = [s["id"] for s in catalogue["settings"]]
    missing = [i for i in wanted if i not in settings]
    if missing:
        raise ValueError("log channels: setting %s of the catalogue has no entry" % ", ".join(missing))
    extra = [i for i in settings if i not in wanted]
    if extra:
        raise ValueError("log channels: entry %s is not a setting of the catalogue" % ", ".join(map(str, extra)))
    known = set(channel_names())
    for sid, entry in settings.items():
        validate_setting(sid, entry, known)
    groups = chan.get("extra_groups")
    if not isinstance(groups, list):
        raise ValueError("log channels: needs extra_groups, a list")
    group_ids = []
    for g in groups:
        validate_extra_group(g, known, group_ids)


def load_channels(path=None):
    """tuner/log_channels.json (or the file at path), validated against the catalogue."""
    chan = tune.read_json(path or CHANNELS)
    validate_channels(chan, tune.load_catalogue())
    return chan


def extra_row_id(group, row):
    return "%s.%s" % (group["id"], row["id"])


def extra_rows(chan):
    """[("<group id>.<row id>", row)] of every extra row, in table order."""
    return [(extra_row_id(g, r), r) for g in chan["extra_groups"] for r in g["rows"]]


def extra_ids(chan):
    return [i for i, _ in extra_rows(chan)]


def tickable_ids(chan):
    """The ids a choice may tick: the direct settings in catalogue order, then "<group id>.<row id>" of every extra row."""
    return [sid for sid, e in chan["settings"].items() if e["status"] == "direct"] + extra_ids(chan)


def default_config(chan):
    """The choice without a file: 30 Hz and the extra rows whose default is true."""
    return {"version": VERSION, "rate_hz": DEFAULT_RATE,
            "ticked": [i for i, r in extra_rows(chan) if r["default"]]}


def config_path(work):
    return os.path.join(work, CONFIG_FILE)


def validate_config(config, chan):
    """Raises ValueError unless config is {"version": 1, "rate_hz": 30 or 60, "ticked": [unique tickable ids]}; an unknown or
    greyed id is named in the message."""
    if not isinstance(config, dict):
        raise ValueError("log config: expected an object")
    if type(config.get("version")) is not int or config["version"] != VERSION:
        raise ValueError("log config: version must be %d" % VERSION)
    if type(config.get("rate_hz")) is not int or config["rate_hz"] not in RATES:
        raise ValueError("log config: rate_hz must be %s" % " or ".join(map(str, RATES)))
    ticked = config.get("ticked")
    if not isinstance(ticked, list):
        raise ValueError("log config: ticked must be a list of ids")
    tickable = tickable_ids(chan)
    seen = set()
    for i in ticked:
        if not isinstance(i, str):
            raise ValueError("log config: ticked must be a list of ids (text), got %r" % (i,))
        if i not in tickable:
            entry = chan["settings"].get(i)
            if entry is not None:
                raise ValueError("log config: %s is greyed (%s) and cannot be ticked" % (i, entry["status"]))
            raise ValueError("log config: unknown id %s" % i)
        if i in seen:
            raise ValueError("log config: %s is ticked twice" % i)
        seen.add(i)


def normalised(config, chan):
    """config with only its three keys and the ticked ids in the order of tickable_ids()."""
    ticked = set(config["ticked"])
    return {"version": VERSION, "rate_hz": config["rate_hz"], "ticked": [i for i in tickable_ids(chan) if i in ticked]}


def load_config(work, chan):
    """The saved choice of <work>/log_config.json, normalised; default_config(chan) when the file is missing, damaged or invalid."""
    try:
        config = tune.read_json(config_path(work))
        validate_config(config, chan)
    except (ValueError, OSError):
        return default_config(chan)
    return normalised(config, chan)


def save_config(work, config, chan):
    """Validates config (ValueError, nothing is written), then writes it normalised to <work>/log_config.json; returns what was written."""
    validate_config(config, chan)
    saved = normalised(config, chan)
    tune.save_json(config_path(work), saved)
    return saved


def reset_config(work, chan):
    """Removes <work>/log_config.json (a missing file is fine; any other OSError propagates); returns default_config(chan)."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(kspkg.long_path(config_path(work)))
    return default_config(chan)


def tree(chan, catalogue, config):
    """The groups of the Logging tab in display order: the extra groups in the order of the table, then the catalogue groups with
    at least one tickable row (catalogue order), then the catalogue groups without one (catalogue order). Inside a group the
    tickable rows come first, the others last, each part in its table order. A group is {"id", "name", "description",
    "tickable" (the number of its tickable rows), "rows"}. A catalogue row is {"id": setting id, "label", "unit", "status",
    "note", "tickable", "ticked", "once", "live"}; an extra row {"id": "<group id>.<row id>", "label", "description", "default",
    "tickable": true, "ticked", "status": "extra", "note": "", "once", "live"}."""
    ticked = set(config["ticked"])
    extra, with_rows, without_rows = [], [], []
    for g in catalogue["groups"]:
        rows = []
        for s in catalogue["settings"]:
            if s["group"] != g["name"]:
                continue
            e = chan["settings"][s["id"]]
            rows.append({"id": s["id"], "label": s["label"], "unit": s["unit"], "status": e["status"], "note": e["note"],
                         "tickable": e["status"] == "direct", "ticked": s["id"] in ticked, "once": list(e["once"]),
                         "live": list(e["live"])})
        rows = [r for r in rows if r["tickable"]] + [r for r in rows if not r["tickable"]]
        count = sum(r["tickable"] for r in rows)
        (with_rows if count else without_rows).append(
            {"id": "catalogue." + g["name"], "name": g["name"], "description": g["description"], "tickable": count, "rows": rows})
    for g in chan["extra_groups"]:
        rows = []
        for r in g["rows"]:
            rid = extra_row_id(g, r)
            rows.append({"id": rid, "label": r["label"], "description": r["description"], "default": r["default"], "tickable": True,
                         "ticked": rid in ticked, "status": "extra", "note": "", "once": list(r["once"]), "live": list(r["live"])})
        extra.append({"id": g["id"], "name": g["name"], "description": g["description"], "tickable": len(rows), "rows": rows})
    return extra + with_rows + without_rows


def selected_channels(chan, config):
    """{"once": [...], "live": [...]}: the channel names of the ticked rows without repeats, in the order of tickable_ids()."""
    ticked = set(config["ticked"])
    rows = dict(chan["settings"])
    rows.update(extra_rows(chan))
    out = {"once": [], "live": []}
    for i in tickable_ids(chan):
        if i in ticked:
            for key in out:
                out[key] += [n for n in rows[i][key] if n not in out[key]]
    return out


def default_logs_dir():
    return str(tune.REPO / "logs")


def stop_path(logs_dir):
    return os.path.join(logs_dir, STOP_FILE)


def request_stop(logs_dir):
    """Creates the empty file that asks the running logger to stop; returns its path."""
    path = stop_path(logs_dir)
    os.makedirs(logs_dir, exist_ok=True)
    with open(path, "wb"):
        pass
    return path


def clear_stop(logs_dir):
    """Removes the stop file if it is there; errors are ignored."""
    with contextlib.suppress(OSError):
        os.remove(stop_path(logs_dir))


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def line_object(raw):
    """The JSON object of one line of bytes, None when the line is not one."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def session_ends(path, size):
    """(first line, last line) of a session file as JSON objects, None where a line is missing or not an object."""
    with open(path, "rb") as f:
        first = f.readline(1 << 20)
        f.seek(max(0, size - SESSION_TAIL))
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    return line_object(first), line_object(lines[-1]) if lines else None


def session_file_info(path, name, st):
    info = {"file": name, "size": st.st_size, "modified": st.st_mtime, "car": None, "track": None, "duration_s": None, "samples": None}
    try:
        first, last = session_ends(path, st.st_size)
    except OSError:
        return info
    if first and first.get("type") == "header":
        info["car"] = first["car"] if isinstance(first.get("car"), str) else None
        info["track"] = first["track"] if isinstance(first.get("track"), str) else None
    if last and last.get("type") == "end":
        if is_number(last.get("duration_s")):
            info["duration_s"] = last["duration_s"]
        if isinstance(last.get("samples"), int) and not isinstance(last["samples"], bool):
            info["samples"] = last["samples"]
    return info


def list_sessions(logs_dir, limit=20):
    """The newest limit session files (logs/*.jsonl, by modification time) as {"file", "size", "modified" (epoch seconds), "car",
    "track", "duration_s", "samples"}; the last four are None where the file has no header or end line. [] for a missing folder."""
    try:
        names = [n for n in os.listdir(logs_dir) if n.lower().endswith(".jsonl")]
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(logs_dir, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if os.path.isfile(path):
            found.append((st.st_mtime, name, st))
    found.sort(key=lambda f: (f[0], f[1]), reverse=True)
    return [session_file_info(os.path.join(logs_dir, name), name, st) for _, name, st in found[:max(0, limit)]]


def not_running():
    return {"running": False, "state": "not running", "file": None, "samples": None, "started": None, "seconds": None}


def logger_status(logs_dir, now=None):
    """{"running", "state" ("not running", "waiting" or "logging"), "file", "samples", "started", "seconds" (since started while
    logging, else None)} from logs/logger_status.json. Running only when the file is valid and was updated at most STATUS_MAX_AGE
    seconds before now (default: the current time); a missing, damaged or stale file is "not running" with the rest None."""
    now = time.time() if now is None else now
    try:
        data = tune.read_json(os.path.join(logs_dir, STATUS_FILE))
    except (ValueError, OSError):
        return not_running()
    if not (isinstance(data, dict) and data.get("state") in ("waiting", "logging")
            and "file" in data and (data["file"] is None or isinstance(data["file"], str))
            and isinstance(data.get("samples"), int) and not isinstance(data["samples"], bool)
            and is_number(data.get("started")) and is_number(data.get("updated"))
            and isinstance(data.get("pid"), int) and not isinstance(data["pid"], bool)):
        return not_running()
    if now - data["updated"] > STATUS_MAX_AGE:
        return not_running()
    return {"running": True, "state": data["state"], "file": data["file"], "samples": data["samples"], "started": data["started"],
            "seconds": now - data["started"] if data["state"] == "logging" else None}


def validate_glossary(glossary):
    """Raises ValueError with a clear message unless the glossary is valid: version 1; channels has exactly the channel names of
    ace_shm.channels(); every entry has the text keys unit, meaning and range (not empty) and notes (may be empty)."""
    if not isinstance(glossary, dict):
        raise ValueError("log glossary: expected an object")
    if type(glossary.get("version")) is not int or glossary["version"] != VERSION:
        raise ValueError("log glossary: version must be %d" % VERSION)
    channels = glossary.get("channels")
    if not isinstance(channels, dict):
        raise ValueError("log glossary: needs channels, an object with one entry per channel")
    wanted = channel_names()
    missing = [n for n in wanted if n not in channels]
    if missing:
        raise ValueError("log glossary: channel %s has no entry" % ", ".join(missing))
    extra = [n for n in channels if n not in wanted]
    if extra:
        raise ValueError("log glossary: entry %s is not a channel" % ", ".join(map(str, extra)))
    for name, entry in channels.items():
        where = "log glossary: channel %s" % name
        if not isinstance(entry, dict):
            raise ValueError("%s: expected an object" % where)
        for key in ("unit", "meaning", "range"):
            if not is_text(entry.get(key)):
                raise ValueError("%s: %s must be text (not empty)" % (where, key))
        if not isinstance(entry.get("notes"), str):
            raise ValueError("%s: notes must be text" % where)


def load_glossary(path=None):
    """tuner/log_glossary.json (or the file at path), validated."""
    glossary = tune.read_json(path or GLOSSARY)
    validate_glossary(glossary)
    return glossary


def load_ai_template(path=None):
    """The text of tuner/log_ai_command.txt (or the file at path); ValueError unless {{CHANNELS}} and {{ROWS}} each occur once."""
    with open(path or AI_TEMPLATE, encoding="utf-8") as f:
        template = f.read()
    for placeholder in AI_PLACEHOLDERS:
        if template.count(placeholder) != 1:
            raise ValueError("AI command template: %s must occur exactly once" % placeholder)
    return template


def ascii_text(text):
    return "".join(c if c.isascii() else ASCII_FIXES.get(c, "?") for c in text)


def one_line(text):
    return " ".join(text.split())


def names_text(names):
    return ", ".join(names) if names else "none"


def glossary_section(glossary):
    lines = ["GLOSSARY OF THE VALUES IN THE LOG"]
    for name, e in glossary["channels"].items():
        line = "- %s [%s]: %s Range: %s." % (name, e["unit"], e["meaning"], e["range"])
        if e["notes"].strip():
            line += " Notes: " + e["notes"]
        lines.append(one_line(line))
    return "\n".join(lines)


def row_line(row, setting):
    if row["status"] == "extra":
        text = "- %s (row %s): %s Reads once: %s; live: %s" % (row["label"], row["id"], row["description"], names_text(row["once"]), names_text(row["live"]))
    else:
        parts = ["id %s" % row["id"], "unit %s" % (row["unit"] or "-")]
        if is_number(setting.get("min")) and is_number(setting.get("max")):
            parts.append("tuner limits %g to %g" % (setting["min"], setting["max"]))
        text = "- %s (%s): reads once: %s; live: %s" % (row["label"], ", ".join(parts), names_text(row["once"]), names_text(row["live"]))
    return one_line(text)


def rows_section(chan, catalogue, config):
    settings = {s["id"]: s for s in catalogue["settings"]}
    groups = tree(chan, catalogue, config)
    lines = ["TUNER ROWS: WHAT CAN BE LOGGED AND WHERE IT COMES FROM",
             "A row is one checkbox in the Logging tab of the tuner page. Ticking a row logs its once channels once per session and its "
             "live channels in every sample, at 30 or 60 Hz."]
    for g in groups:
        rows = [r for r in g["rows"] if r["tickable"]]
        if rows:
            lines.append(one_line("GROUP %s: %s" % (g["name"], g["description"])))
            lines += [row_line(r, settings.get(r["id"], {})) for r in rows]
    lines.append("NOT VISIBLE TO THE GAME (cannot be logged, never ask for them)")
    for status, words in GREYED_STATUS_WORDS:
        rows = [r for g in groups for r in g["rows"] if not r["tickable"] and r["status"] == status]
        if rows:
            lines.append(one_line("- %s: %s" % (words, "; ".join("%s (%s)" % (r["label"], r["id"]) for r in rows))))
    return "\n".join(lines)


def ai_command(chan, catalogue, glossary, template, config=None):
    """The template with {{CHANNELS}} replaced by the glossary of the values in the log (one line per channel, in the order of the
    glossary) and {{ROWS}} by the rows of the Logging tab (the tickable rows of every group with their once and live channels and the
    tuner limits, then the rows the game does not show); config is the choice the rows are listed for (default: the default choice).
    ASCII only; ValueError when a placeholder is left in the result."""
    config = default_config(chan) if config is None else config
    sections = {"{{CHANNELS}}": glossary_section(glossary), "{{ROWS}}": rows_section(chan, catalogue, config)}
    text = re.sub("|".join(map(re.escape, sections)), lambda m: sections[m.group(0)], template)
    if "{{" in text or "}}" in text:
        raise ValueError("AI command: a placeholder is left in the text")
    return ascii_text(text)


def session_file(logs_dir, name):
    """The absolute path of the session file name in logs_dir. ValueError unless name is a plain file name (no path separator, no
    drive, no ..) that ends in .jsonl; FileNotFoundError when logs_dir has no such file."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("the session file name must be text")
    if any(c in name for c in "/\\:\0") or ".." in name or os.path.isabs(name):
        raise ValueError("the session file name must be a plain file name")
    if not name.lower().endswith(".jsonl"):
        raise ValueError("the session file name must end in .jsonl")
    path = os.path.join(logs_dir, name)
    if not os.path.isfile(path):
        raise FileNotFoundError("no session file %s" % name)
    return os.path.abspath(path)
