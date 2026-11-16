"""Tuner facts of the session header of the logger: which modded car of the tuner the game's car name is, with its effective settings, its garage tyres, turbo kit and sounds, its last build and the start time of the game process.

Library module of tools/logger.py (no command line of its own). find_car(work, mods, car_name) matches the name the game reports (car_model) against the modded cars of tune.list_modded (id first, then label, spaces at the ends and case ignored) and then against the stock cars of the work folder (id or display name): {"matched": True, "modded": True, "stock_car", "tune_id", "default", "name_suffix"}, {"matched": True, "modded": False, "stock_car"} or {"matched": False, "reason"} (plus "error" when the modded cars could not be listed). tuner_facts(work, mods, car_name, game_start) is the dict stored under "tuner" in the header: find_car's keys and "game_process_start" (the argument), and for a modded car also "values" ({setting id: {"value", "default"}} of the applicable settings), "garage" ({"keys"} or None), "turbo_kit" ({"donor"} or None), "sounds" ({slot: option key}) and "build" ({"snapshot_time", "package_time" (the file time of <mods>/<tune id>.kspkg, local time with its UTC offset), "settings", "kit", "garage", "sounds", "changes"} of the snapshot of the last build, all None without one except "package_time"). A part that cannot be read is {"error": text} under its own key, the rest is kept; nothing raises. game_process_start() is the creation time of the game process (ISO text with the local UTC offset), None when it does not run. make_facts(work, mods) gives the function Logger takes as facts.

Stdlib only.
"""
import ctypes
import datetime
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import clone_car  # noqa: E402
import tune  # noqa: E402

NOT_FOUND = "car not found in the tuner work folder"
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE = ctypes.c_void_p(-1).value
FILETIME_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


class ProcessEntry(ctypes.Structure):
    """PROCESSENTRY32W of the Toolhelp API."""
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_int32), ("dwFlags", ctypes.c_uint32),
                ("szExeFile", ctypes.c_wchar * 260)]


class FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    _kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    _kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
    _kernel32.Process32FirstW.restype = ctypes.c_int32
    _kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
    _kernel32.Process32NextW.restype = ctypes.c_int32
    _kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
    _kernel32.GetProcessTimes.restype = ctypes.c_int32
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_int32


def process_id(names):
    """The id of the first running process whose exe name is one of names (ignoring case), None when there is none."""
    wanted = {n.lower() for n in names}
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, INVALID_HANDLE):
        return None
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() in wanted:
                return entry.th32ProcessID
            found = _kernel32.Process32NextW(snap, ctypes.byref(entry))
        return None
    finally:
        _kernel32.CloseHandle(snap)


def process_created(pid):
    """The creation time of a process as an aware local datetime."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed", pid)
    try:
        created, ended, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
        if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError(ctypes.get_last_error(), "GetProcessTimes failed", pid)
    finally:
        _kernel32.CloseHandle(handle)
    ticks = created.dwHighDateTime << 32 | created.dwLowDateTime
    return (FILETIME_EPOCH + datetime.timedelta(microseconds=ticks // 10)).astimezone()


def game_process_start(names=(tune.GAME_EXE,)):
    """The creation time of the game process as ISO text with the local UTC offset (2026-11-16T18:30:12+01:00); None when no process
    of that name runs, off Windows and on any failure."""
    if sys.platform != "win32":
        return None
    try:
        pid = process_id(names)
        return None if pid is None else process_created(pid).isoformat(timespec="seconds")
    except Exception:
        return None


def same_name(wanted, text):
    return isinstance(text, str) and text.strip().lower() == wanted


def stock_names(work, car_ids):
    """{stock car id: display name or None}: stock_info.json of the car folder, else the cached car index."""
    index = {c["id"]: c["display_name"] for c in tune.load_cars_index(work, "") or []}
    names = {}
    for car_id in car_ids:
        try:
            info = tune.load_stock_info(work, car_id)
        except (ValueError, OSError):
            info = None
        names[car_id] = info["display_name"] if info else index.get(car_id)
    return names


def find_car(work, mods, car_name):
    """The car the game calls car_name (what car_model reports, trimmed and compared ignoring case): a modded car by id, then by
    label (stock name, space, suffix), then a stock car of the work folder by id or display name. When the list of modded cars cannot
    be read (a damaged tune_state.json, an unreadable catalogue) the stock cars are still searched, and an unmatched result then also
    has "error": the text of that failure."""
    wanted = car_name.strip().lower()
    modded, error = [], None
    try:
        modded = tune.list_modded(work, mods)
    except (ValueError, OSError) as e:
        error = str(e)
    for key in ("id", "label"):
        for row in modded:
            if same_name(wanted, row[key]):
                return {"matched": True, "modded": True, "stock_car": row["stock"], "tune_id": row["id"], "default": row["default"],
                        "name_suffix": row["name_suffix"]}
    folders = tune.car_folders(work)
    for car_id, name in stock_names(work, folders).items():
        if same_name(wanted, car_id) or same_name(wanted, name):
            return {"matched": True, "modded": False, "stock_car": car_id}
    return {"matched": False, "reason": NOT_FOUND} if error is None else {"matched": False, "reason": NOT_FOUND, "error": error}


def part(read, *args):
    """read(*args), or {"error": text} when it fails."""
    try:
        return read(*args)
    except Exception as e:
        return {"error": str(e)}


def effective_values(work, stock_car, tune_arg):
    rows = tune.effective_rows(work, stock_car, tune.load_catalogue(), hidden=False, tune=tune_arg)
    return {r["id"]: {"value": tune.plain(r["value"]), "default": tune.plain(r["default"])} for r in rows}


def state_parts(work, stock_car, tune_arg):
    """The garage, turbo_kit and sounds entries of the saved state of the tune; each is {"error": text} when the state or its entry is damaged."""
    try:
        state = tune.load_state(work, stock_car, tune_arg)
    except Exception as e:
        return {key: {"error": str(e)} for key in ("garage", "turbo_kit", "sounds")}

    def garage():
        keys = tune.saved_garage(state)
        return None if keys is None else {"keys": list(keys)}

    def turbo_kit():
        donor = tune.saved_turbo(state)
        return None if donor is None else {"donor": donor}

    return {"garage": part(garage), "turbo_kit": part(turbo_kit), "sounds": part(lambda: dict(tune.saved_sounds(state)))}


def package_time(mods, tune_id):
    """The file time of <mods>/<tune id>.kspkg as local ISO text with the UTC offset, None when the file is missing."""
    stat = tune.stat_or_none(os.path.join(clone_car.expand(mods or clone_car.DEFAULT_MODS), tune_id + ".kspkg"))
    if stat is None:
        return None
    return datetime.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")


def build_facts(work, mods, stock_car, tune_id):
    snapshot = tune.load_snapshot(work, stock_car, tune_id)
    if snapshot is None:
        return dict.fromkeys(("snapshot_time", "package_time", "settings", "kit", "garage", "sounds", "changes"),
                             None) | {"package_time": package_time(mods, tune_id)}
    return {"snapshot_time": snapshot["time"], "package_time": package_time(mods, tune_id), "settings": snapshot["settings"],
            "kit": snapshot["kit"], "garage": snapshot["garage"], "sounds": snapshot["sounds"], "changes": snapshot.get("changes")}


def tuner_facts(work, mods, car_name, game_start=None):
    """The "tuner" entry of the header, see the module docstring."""
    try:
        facts = find_car(work, mods, car_name)
        if facts["matched"] and facts["modded"]:
            tune_arg = None if facts["default"] else facts["tune_id"]
            facts["values"] = part(effective_values, work, facts["stock_car"], tune_arg)
            facts.update(state_parts(work, facts["stock_car"], tune_arg))
            facts["build"] = part(build_facts, work, mods, facts["stock_car"], facts["tune_id"])
    except Exception as e:
        facts = {"matched": False, "error": str(e)}
    facts["game_process_start"] = game_start
    return facts


def make_facts(work, mods, start=game_process_start):
    """The function Logger takes as facts: facts(car, info) = tuner_facts(work, mods, car, start())."""
    def facts(car, info):
        return tuner_facts(work, mods, car, start())
    return facts
