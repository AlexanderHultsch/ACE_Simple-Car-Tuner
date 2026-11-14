r"""Print the printable strings of binary files (FMOD .bank files, .actor files, ...) or search a folder of game files for them.

usage: python tools/bank_strings.py <file or folder> [--min N] [--grep REGEX] [--utf16] [--count]
  e.g. python tools/bank_strings.py master_bank.strings.bank --grep "event:/"
  or   python tools/bank_strings.py <work>/<car>/base --min 6 --grep "audio|sound|engine|bank"

A string is a run of at least N (--min, default 4) printable ASCII bytes (0x20-0x7E and tab). A file prints one line per
string: `<offset hex 8 digits>: <string>`, the offset is that of the first byte in the file. FMOD banks are RIFF containers
('FEV ', 'FMT ', 'STRS' chunks), their event paths (`event:/...`) are NUL-terminated strings and show up as such.
A folder is walked recursively (names sorted, depth first, symlinks and junctions are not followed); every line is prefixed
with the path relative to the folder: `<relpath>:<offset>: <string>`.
--grep keeps only strings matching REGEX (re.search, case-insensitive). --utf16 also prints UTF-16LE strings (printable
ASCII characters each followed by 0x00, at least N characters) in offset order, marked ` [utf16]`. --count prints
`<file>: <number of strings>` per file (folder mode: files without hits are left out) and a final `total: <n>` line
instead of the strings; --grep and --utf16 apply to it.
Files are read in chunks, so large banks are fine. A file or folder that cannot be read is skipped with a
`skipped <path>: <reason>` line on stderr, the exit code stays 0. Output is ASCII only (other bytes are never printed).

Exit code 0 on success, 1 on a runtime error (error: ... on stderr: path does not exist, invalid regex), 2 on bad usage
(usage block on stdout).
"""
import heapq
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kspkg  # noqa: E402

CHUNK = 1 << 20
PRINTABLE = frozenset(range(0x20, 0x7F)) | {0x09}
ASCII_RUN = rb"[\x20-\x7e\t]{%d,}"
WIDE_RUN = rb"(?:[\x20-\x7e\t]\x00){%d,}"
ASCII_TAIL = re.compile(rb"[^\x20-\x7e\t][\x20-\x7e\t]*\Z")
MOUNT_POINT = 0xA0000003


def safe(text):
    return text.encode("ascii", "backslashreplace").decode("ascii")


# Start of the part of buf that a string may still continue into the next chunk. `skip` bytes at the front are known
# to be printable (the carried part), so the search starts behind them.
def tail_start(buf, wide, skip):
    if not wide:
        m = ASCII_TAIL.search(buf, skip)
        return m.start() + 1 if m else 0
    i = len(buf)
    if i and buf[i - 1] in PRINTABLE:
        i -= 1
    while i >= 2 and buf[i - 1] == 0 and buf[i - 2] in PRINTABLE:
        i -= 2
    return i


def scan_file(path, n, wide):
    """Yield (offset, text, wide) for every string of at least n characters; an unfinished run at the end of a chunk is
    carried into the next one."""
    pat = re.compile((WIDE_RUN if wide else ASCII_RUN) % n)
    with open(path, "rb") as f:
        carry, base = b"", 0
        while True:
            chunk = f.read(CHUNK)
            buf = carry + chunk
            cut = tail_start(buf, wide, len(carry)) if chunk else len(buf)
            for m in pat.finditer(buf, 0, cut):
                raw = m.group()
                yield base + m.start(), (raw[::2] if wide else raw).decode("ascii"), wide
            if not chunk:
                return
            carry, base = buf[cut:], base + cut


def hits(path, n, utf16, rx):
    streams = [scan_file(path, n, False)]
    if utf16:
        streams.append(scan_file(path, n, True))
    for offset, text, wide in heapq.merge(*streams, key=lambda h: (h[0], h[2])):
        if rx is None or rx.search(text):
            yield offset, text, wide


def is_link(entry):
    if entry.is_symlink():
        return True
    return entry.is_dir(follow_symlinks=False) and getattr(os.lstat(entry.path), "st_reparse_tag", 0) == MOUNT_POINT


def walk(root, rel, skip):
    """Yield (relative path, full path) of the files below root, names sorted, depth first."""
    try:
        with os.scandir(root) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError as e:
        skip("\\".join(rel) or ".", e)
        return
    for entry in entries:
        sub = rel + [entry.name]
        try:
            if is_link(entry):
                continue
            if entry.is_dir(follow_symlinks=False):
                yield from walk(entry.path, sub, skip)
            elif entry.is_file(follow_symlinks=False):
                yield "\\".join(sub), entry.path
        except OSError as e:
            skip("\\".join(sub), e)


def usage():
    print(__doc__.split("\n\n")[1])
    sys.exit(2)


def main():
    try:
        pos, opts = kspkg.parse_args(sys.argv[1:], ("min", "grep"), ("utf16", "count"))
        n = int(opts.get("min", 4))
    except ValueError:
        usage()
    if len(pos) != 1 or n < 1:
        usage()
    target = kspkg.long_path(pos[0])
    if not os.path.exists(target):
        sys.exit("error: %s does not exist" % kspkg.plain_path(target))
    rx = None
    if "grep" in opts:
        try:
            rx = re.compile(opts["grep"], re.IGNORECASE)
        except re.error as e:
            sys.exit("error: invalid regex: %s" % e)
    try:
        re.compile(ASCII_RUN % n)
    except (re.error, OverflowError) as e:
        sys.exit("error: invalid --min: %s" % e)

    def skip(label, e):
        print("skipped %s: %s" % (safe(label), safe(getattr(e, "strerror", None) or str(e))), file=sys.stderr)

    folder = os.path.isdir(target)
    files = walk(target, [], skip) if folder else [(pos[0], target)]
    total = 0
    for label, path in files:
        count = 0
        try:
            for offset, text, wide in hits(path, n, "utf16" in opts, rx):
                count += 1
                if "count" not in opts:
                    print("%s%08x: %s%s" % (safe(label) + ":" if folder else "", offset, text, " [utf16]" if wide else ""))
        except OSError as e:
            skip(label, e)
            continue
        total += count
        if "count" in opts and (count or not folder):
            print("%s: %d" % (safe(label), count))
    if "count" in opts:
        print("total: %d" % total)


if __name__ == "__main__":
    main()
