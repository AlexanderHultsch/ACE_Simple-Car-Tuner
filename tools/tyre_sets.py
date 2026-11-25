"""Tyre sets of the tuner: the game's tyre index and the compound builder for the tyre choice of a car.

Library module of tools/tune.py (no command line of its own). The game package content.kspkg holds the tyre files below
content\\cars\\common_phsx\\tyres\\<type folder>\\<name>.tyre. game_index lists them (read_index reads them from the package table and
caches the result in <work>/tyre_index.json), tyre_entry describes one, parse_size reads the size out of the usual file names
(road_235_35_19) and find_file gives the local copy of a tyre file (an extracted car's base folder, else extracted from the package).

A car offers its tyres as a list of "physic compounds" {tyre_compound, front_tyre_data_path, rear_tyre_data_paths} plus the
"graphic_compounds" {tyre_compound}; tyre_compound is a name of a fixed enum of the game, unique within a car. The player picks the
front and the rear tyre separately, by index of the list. build_compounds makes both lists out of the wanted front and rear tyres,
keeping the names of the car's original entries where the pair of tyres stays the same.

Stdlib only.
"""
import contextlib
import json
import os
import re

import kspkg

SHARED = "content\\cars\\common_phsx\\tyres\\"
INDEX_FILE = "tyre_index.json"
INDEX_VERSION = 1

TYPE_LABELS = {
    "road": "Road", "eco": "Eco", "supercar": "Supercar", "hypercar": "Hypercar", "vintage": "Vintage",
    "racing_slicks": "Racing slick", "racing_slicks/historic_formula": "Historic formula slick",
    "racing_wet": "Racing wet", "racing_wet/historic_formula_wet": "Historic formula wet",
    "f1_2004": "F1 2004", "f1_2025": "F1 2025", "f1_2026": "F1 2026"}
TYPE_ORDER = tuple(TYPE_LABELS)

BASE_WORDS = ("slick", "wet")
_SIZE = re.compile(r"^[^\d]*_(\d{2,3})_(\d{2})_(\d{2})$")

ROAD_NAMES = tuple("TyreCompound_Road_" + n for n in (
    "Generic", "Toyo", "GoodYear", "Bridgestone", "Hankook", "Continental", "Avon", "Pirelli", "Michelin"))
SUPERCAR_NAMES = tuple("TyreCompound_Supercar_" + n for n in (
    "Generic", "Toyo", "GoodYear", "Bridgestone", "Hankook", "Continental", "Avon", "Pirelli_Corsa", "Michelin_Cup_2", "Yokohama"))
HYPERCAR_NAMES = tuple("TyreCompound_Hypercar_" + n for n in (
    "Generic", "Toyo", "GoodYear", "Bridgestone", "Hankook", "Continental", "Avon", "Yokohama", "Pirelli_Trofeo", "Michelin_Cup_2R"))
ECO_NAMES = tuple("TyreCompound_Eco_" + n for n in (
    "Generic", "Toyo", "GoodYear", "Bridgestone", "Hankook", "Continental", "Avon", "Pirelli", "Michelin"))
SLICK_NAMES = tuple("TyreCompound_Racing_" + n for n in (
    "Generic_Slick", "Pirelli_GTWC", "Dunlop_Cup", "Hankook_Cup", "BFG_Cup", "GoodYear_Cup", "Michelin_Special", "Falken_Cup"))
WET_NAMES = tuple("TyreCompound_Racing_" + n for n in (
    "Generic_Wet", "Pirelli_GTWC_Wet", "Michelin_Cup_Wet", "BFG_Wet", "GoodYear_Wet", "Hankook_Wet", "Dunlop_Wet", "Falken_Wet"))
VINTAGE_NAMES = tuple("TyreCompound_Road_Vintage_%ss" % d for d in (1950, 1960, 1970, 1980, 1990)) + ("TyreCompound_Racing_Vintage_1980s",)
FALLBACK_NAMES = tuple("TyreCompound_Special_" + n for n in (
    "Generic", "Pirelli", "Michelin", "Bridgestone", "GoodYear", "Toyo", "Continental", "Hankook", "Avon", "Pirelli_2"))

COMPOUND_NAMES = {
    "road": ROAD_NAMES, "eco": ECO_NAMES, "supercar": SUPERCAR_NAMES, "hypercar": HYPERCAR_NAMES, "vintage": VINTAGE_NAMES,
    "racing_slicks": SLICK_NAMES, "racing_slicks/historic_formula": SLICK_NAMES,
    "racing_wet": WET_NAMES, "racing_wet/historic_formula_wet": WET_NAMES,
    "f1_2004": FALLBACK_NAMES, "f1_2025": FALLBACK_NAMES, "f1_2026": FALLBACK_NAMES}
ALL_NAMES = (ROAD_NAMES + SUPERCAR_NAMES + HYPERCAR_NAMES + ECO_NAMES + SLICK_NAMES + WET_NAMES + VINTAGE_NAMES + FALLBACK_NAMES)


def norm(path):
    """Comparison form of a game path: lower case, backslashes."""
    return path.replace("/", "\\").lower()


def parse_size(file_stem):
    """{"width", "aspect", "rim"} of a name like road_235_35_19, None for every other name."""
    m = _SIZE.match(file_stem)
    if not m:
        return None
    width, aspect, rim = map(int, m.groups())
    if 100 <= width <= 400 and 20 <= aspect <= 90 and 10 <= rim <= 24:
        return {"width": width, "aspect": aspect, "rim": rim}
    return None


def size_label(size, file_stem=""):
    """"235/35 R19"; without a size the file name with spaces, a leading word "slick" or "wet" (the type's base word) dropped."""
    if size is None:
        words = file_stem.split("_")
        if len(words) > 1 and words[0].lower() in BASE_WORDS:
            words = words[1:]
        return " ".join(words)
    return "%d/%d R%d" % (size["width"], size["aspect"], size["rim"])


def type_label(type_folder):
    return TYPE_LABELS.get(type_folder.lower(), type_folder)


def tyre_entry(path):
    """The index entry of the game path of a tyre file; ValueError for a path that is no tyre file of the shared tyres."""
    text = path.replace("/", "\\")
    if not text.lower().startswith(SHARED) or not text.lower().endswith(".tyre"):
        raise ValueError("%s is not a tyre file below %s" % (path, SHARED))
    parts = text[len(SHARED):].split("\\")
    stem = parts[-1][:-len(".tyre")]
    kind = "/".join(parts[:-1])
    size = parse_size(stem)
    label = " ".join(x for x in (type_label(kind), size_label(size, stem)) if x)
    return {"path": text, "type": kind, "type_label": type_label(kind), "file": stem, "size": size, "label": label}


def _sort_key(t):
    kind = t["type"].lower()
    order = TYPE_ORDER.index(kind) if kind in TYPE_ORDER else len(TYPE_ORDER)
    s = t["size"]
    return (order, kind, 0 if s else 1, s["width"] if s else 0, s["aspect"] if s else 0, s["rim"] if s else 0, t["file"])


def game_index(listing):
    """The tyre entries of every tyre file in the listing of game paths, without duplicates, in menu order."""
    seen, out = set(), []
    for path in listing:
        try:
            t = tyre_entry(path)
        except ValueError:
            continue
        key = norm(t["path"])
        if key not in seen:
            seen.add(key)
            out.append(t)
    return sorted(out, key=_sort_key)


def _stamp(package):
    st = os.stat(package)
    return [st.st_size, st.st_mtime_ns]


def _cached(path, stamp):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != INDEX_VERSION or data.get("stamp") != stamp:
        return None
    tyres = data.get("tyres")
    keys = {"path", "type", "type_label", "file", "size", "label"}
    if not isinstance(tyres, list) or not all(isinstance(t, dict) and keys <= set(t) for t in tyres):
        return None
    return tyres


def read_index(package, work=None):
    """game_index of the package table, cached in <work>/tyre_index.json while the package file stays the same."""
    if not os.path.isfile(package):
        raise ValueError("the game package %s was not found" % package)
    stamp = _stamp(package)
    cache = os.path.join(work, INDEX_FILE) if work else None
    if cache:
        hit = _cached(cache, stamp)
        if hit is not None:
            return hit
    with open(package, "rb") as f:
        _, entries, _ = kspkg.read_table(f)
    tyres = game_index(e["path"] for e in entries if not e["flags"] & kspkg.FLAG_DIR)
    if cache:
        part = cache + ".tmp"
        try:
            os.makedirs(work, exist_ok=True)
            with open(part, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"version": INDEX_VERSION, "stamp": stamp, "tyres": tyres}, f, indent=2)
                f.write("\n")
            os.replace(part, cache)
        except OSError:
            with contextlib.suppress(OSError):
                os.remove(part)
    return tyres


def _parts(game_path):
    text = game_path.replace("/", "\\")
    parts = [p for p in text.split("\\") if p not in ("", ".")]
    if text.startswith("\\") or not parts or any(p == ".." or ":" in p for p in parts):
        raise ValueError("unsafe tyre path %r" % game_path)
    return parts


def _find_ci(root, parts):
    """The existing file below root that matches parts case-insensitively, or None."""
    cur = root
    for name in parts:
        try:
            names = os.listdir(kspkg.long_path(cur))
        except OSError:
            return None
        hit = next((n for n in sorted(names) if n.lower() == name.lower()), None)
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur if os.path.isfile(kspkg.long_path(cur)) else None


def find_file(work, game_path, package):
    """Local path of a tyre file: the copy in an extracted car's base folder, else <work>/tyre_files/<game path>
    (extracted from the package when it is not there yet); ValueError when there is none."""
    parts = _parts(game_path)
    try:
        cars = sorted(os.listdir(kspkg.long_path(work)))
    except OSError:
        cars = []
    for car in cars:
        hit = _find_ci(os.path.join(work, car, "base"), parts)
        if hit:
            return hit
    folder = os.path.join(work, "tyre_files")
    hit = _find_ci(folder, parts)
    if hit:
        return hit
    if not os.path.isfile(package):
        raise ValueError("the game package %s was not found" % package)
    wanted = "\\".join(parts).lower()
    with open(package, "rb") as f:
        key, entries, _ = kspkg.read_table(f)
        e = next((e for e in entries if e["path"].lower() == wanted and not e["flags"] & kspkg.FLAG_DIR), None)
        if e is None:
            raise ValueError("%s not found in %s" % (game_path, package))
        dst = _extract(f, key, e, folder, parts)
    return kspkg.plain_path(dst)


def _extract(f, key, e, folder, parts):
    dst = kspkg.safe_path(folder, "\\".join(parts))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".tmp"
    try:
        with open(part, "wb") as out:
            kspkg.copy_entry(f, e, key, out.write)
        os.replace(part, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(part)
        raise
    return dst


def _local_tyres(work):
    """{norm(game path): local path} of every shared tyre file below the base of an extracted car (sorted by car) and then below
    <work>/tyre_files; the first copy of a path wins (the order find_file looks in)."""
    try:
        cars = sorted(os.listdir(kspkg.long_path(work)))
    except OSError:
        cars = []
    found = {}
    for root in [os.path.join(work, c, "base") for c in cars] + [os.path.join(work, "tyre_files")]:
        top = os.path.join(root, "content", "cars", "common_phsx", "tyres")
        for dp, _, names in os.walk(kspkg.long_path(top)):
            rel = os.path.relpath(dp, kspkg.long_path(top))
            parts = ["content", "cars", "common_phsx", "tyres"] + ([] if rel == "." else rel.split(os.sep))
            for n in names:
                if n.lower().endswith(".tyre"):
                    found.setdefault(norm("\\".join(parts + [n])), kspkg.plain_path(os.path.join(dp, n)))
    return found


def find_files(work, game_paths, package):
    """{norm(game path): local path} for the tyre files of game_paths that can be had, like find_file for many at once: one walk over
    the extracted tyre files and one read of the package table; a file that is in neither place is extracted into <work>/tyre_files
    (when the package is there); a path that cannot be had (not in the package, unreadable, unsafe) is left out."""
    local = _local_tyres(work)
    out, missing = {}, []
    for path in game_paths:
        hit = local.get(norm(path))
        if hit:
            out[norm(path)] = hit
        else:
            missing.append(path)
    if not missing or not os.path.isfile(package):
        return out
    folder = os.path.join(work, "tyre_files")
    with open(package, "rb") as f:
        key, entries, _ = kspkg.read_table(f)
        by_path = {e["path"].lower(): e for e in entries if not e["flags"] & kspkg.FLAG_DIR}
        for path in missing:
            try:
                parts = _parts(path)
                e = by_path.get("\\".join(parts).lower())
                if e is not None:
                    out[norm(path)] = kspkg.plain_path(_extract(f, key, e, folder, parts))
            except (ValueError, OSError):
                continue
    return out


def same_size(a, b):
    return a["size"] is not None and a["size"] == b["size"]


def unique_paths(paths):
    """The paths without duplicates (case and slashes ignored), the first one wins, order kept."""
    seen, out = set(), []
    for p in paths:
        if norm(p) not in seen:
            seen.add(norm(p))
            out.append(p)
    return out


def free_name(type_folder, taken):
    """The first compound name for tyres of this type that is not in taken."""
    for name in COMPOUND_NAMES.get(type_folder.lower(), FALLBACK_NAMES) + FALLBACK_NAMES + ALL_NAMES:
        if name not in taken:
            return name
    raise ValueError("no free tyre name left for this car")


def _stock_pair(c):
    rear = c.get("rear_tyre_data_paths")
    if isinstance(rear, list) and len(rear) == 1:
        rear = rear[0]
    front = c.get("front_tyre_data_path")
    if not isinstance(front, str) or not isinstance(rear, str) or not isinstance(c.get("tyre_compound"), str):
        return None
    return norm(front), norm(rear)


def build_compounds(stock, fronts, rears, types=None):
    """The physic and graphic compound lists for the wanted front and rear tyres of a car (see the module text).
    stock: the car's original physic compounds; types: {path: type folder} for tyres outside the shared tyre folder.
    Returns {"physic", "graphic", "front", "rear"}."""
    if not fronts or not rears:
        raise ValueError("a car needs at least one front and one rear tyre")
    n = max(len(fronts), len(rears))
    pairs = [(fronts[i] if i < len(fronts) else fronts[0], rears[i] if i < len(rears) else rears[0]) for i in range(n)]
    stock_names = {}
    for c in stock:
        pair = _stock_pair(c)
        if pair is not None:
            stock_names.setdefault(pair, c["tyre_compound"])
    kinds = {norm(p): t for p, t in (types or {}).items()}
    names = [stock_names.get((norm(f), norm(r))) for f, r in pairs]
    taken = {x for x in names if x}
    for i, (front, _) in enumerate(pairs):
        if names[i] is None:
            try:
                kind = kinds.get(norm(front)) or tyre_entry(front)["type"]
            except ValueError:
                kind = "road"
            names[i] = free_name(kind, taken)
            taken.add(names[i])
    return {"physic": [{"tyre_compound": names[i], "front_tyre_data_path": f, "rear_tyre_data_paths": r}
                       for i, (f, r) in enumerate(pairs)],
            "graphic": [{"tyre_compound": x} for x in names], "front": list(fronts), "rear": list(rears)}


def compound_index(paths, path):
    """Index of a path in a list of tyre paths (slashes and case ignored); ValueError when it is not in it."""
    key = norm(path)
    for i, p in enumerate(paths):
        if norm(p) == key:
            return i
    raise ValueError("%s is not one of the car's tyres" % path)


def limits_of(compounds):
    """The highest tyre index of each axle, for the setup limits."""
    return {"front_max": len(compounds["front"]) - 1, "rear_max": len(compounds["rear"]) - 1}
