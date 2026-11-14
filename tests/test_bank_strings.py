"""Tests for tools/bank_strings.py on synthetic files: offsets, --min, chunk boundaries, --grep, --utf16, --count, folder mode, skipped files, exit codes."""
import contextlib
import io
import os
import random
import struct
import subprocess
import sys
import unittest
from unittest import mock

from support import run_tool, tmp

import bank_strings

USAGE = bank_strings.__doc__.split("\n\n")[1]

DATA = b"\x00\x01abcd\x00xy\x00hello world\xff\x00\x00tab\there\n"

WIDE = b"\x01" + "Engine".encode("utf-16-le") + b"\xffabcd\x00" + "ab".encode("utf-16-le") + b"\x01"

EVENTS = [b"event:/engine_int_ks_xyz", b"event:/engine_ext_ks_xyz", b"event:/turbo/whistle"]

TREE = {
    "z.bin": b"zulu!",
    "sub/c.bin": b"\x00\x00gamma\x00delta",
    "sub/b.bin": b"beta1\x00",
    "empty.bin": b"",
    "a.bin": b"\x00alpha\x00",
}


def riff_chunk(tag, payload):
    return tag + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")


def mini_bank():
    body = b"FEV " + riff_chunk(b"FMT ", b"\x01\x00\x00\x00\x10\x00\x00\x00") + riff_chunk(b"STRS", b"\x00".join(EVENTS) + b"\x00")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def run_main(*args):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["bank_strings.py", *map(str, args)]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            bank_strings.main()
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


def lines(text):
    return text.splitlines()


def write_tree(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


class FileMode(unittest.TestCase):
    def run_file(self, data, *args):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(data)
            r = run_tool("bank_strings.py", f, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return lines(r.stdout)

    def test_offsets_and_strings_of_a_synthetic_file(self):
        self.assertEqual(self.run_file(DATA), [
            "00000002: abcd",
            "0000000a: hello world",
            "00000018: tab\there",
        ])

    def test_min_changes_the_shortest_string(self):
        self.assertEqual(self.run_file(DATA, "--min", "2"), [
            "00000002: abcd",
            "00000007: xy",
            "0000000a: hello world",
            "00000018: tab\there",
        ])
        self.assertEqual(self.run_file(DATA, "--min", "11"), ["0000000a: hello world"])
        self.assertEqual(self.run_file(DATA, "--min", "12"), [])

    def test_min_1_prints_every_printable_byte_run(self):
        self.assertEqual(self.run_file(b"\x00a\x00bc\x00", "--min", "1"), ["00000001: a", "00000003: bc"])

    def test_empty_file_and_file_without_strings_print_nothing(self):
        self.assertEqual(self.run_file(b""), [])
        self.assertEqual(self.run_file(b"\x00\xff\x01ab\x7f\xfe"), [])

    def test_a_string_at_the_start_and_at_the_end_of_the_file(self):
        self.assertEqual(self.run_file(b"head\x00tail"), ["00000000: head", "00000005: tail"])

    def test_output_is_ascii_only_and_never_decodes_other_bytes(self):
        with tmp() as d:
            (d / "x.bin").write_bytes(b"caf\xc3\xa9\xe2\x82\xac\x7fgood-text\xff")
            r = run_tool("bank_strings.py", d / "x.bin")
        self.assertEqual(lines(r.stdout), ["00000009: good-text"])
        self.assertTrue(r.stdout.isascii())

    def test_mini_fmod_bank_gives_the_event_paths(self):
        data = mini_bank()
        expected = ["%08x: %s" % (data.index(e), e.decode()) for e in EVENTS]
        self.assertEqual(self.run_file(data, "--grep", "event:/"), expected)
        every = self.run_file(data)
        for tag in (b"RIFF", b"FEV ", b"STRS"):
            self.assertTrue(any(ln.startswith("%08x: %s" % (data.index(tag), tag.decode())) for ln in every), tag)
        for line in expected:
            self.assertIn(line, every)


class ChunkBoundaries(unittest.TestCase):
    def scan(self, data, chunk, *args):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(data)
            with mock.patch.object(bank_strings, "CHUNK", chunk):
                code, out, err = run_main(f, *args)
        self.assertEqual((code, err), (0, ""))
        return lines(out)

    def test_a_string_crossing_the_chunk_boundary_is_one_string_with_the_right_offset(self):
        data = b"\x00" * 5 + b"event:/engine_int" + b"\x00" + b"tail"
        for chunk in (1, 2, 3, 4, 7, 8, 9, 22, 23, 100):
            with self.subTest(chunk=chunk):
                self.assertEqual(self.scan(data, chunk), ["00000005: event:/engine_int", "00000017: tail"])

    def test_a_short_run_at_the_end_of_a_chunk_still_grows_to_the_minimum(self):
        for chunk in (1, 2, 3, 4):
            with self.subTest(chunk=chunk):
                self.assertEqual(self.scan(b"\x00\x00abc\x00" + b"\x01abcd", chunk), ["00000007: abcd"])
                self.assertEqual(self.scan(b"\x00ab" + b"cd", chunk), ["00000001: abcd"])

    def test_the_whole_synthetic_file_is_the_same_with_every_tiny_chunk_size(self):
        want = self.scan(DATA, 1 << 20, "--min", "2")
        self.assertEqual(len(want), 4)
        for chunk in range(1, 12):
            with self.subTest(chunk=chunk):
                self.assertEqual(self.scan(DATA, chunk, "--min", "2"), want)

    def test_a_utf16_string_crossing_the_chunk_boundary_is_found_whole(self):
        want = ["00000001: Engine [utf16]", "0000000e: abcd"]
        self.assertEqual(self.scan(WIDE, 1 << 20, "--utf16"), want)
        for chunk in range(1, 12):
            with self.subTest(chunk=chunk):
                self.assertEqual(self.scan(WIDE, chunk, "--utf16"), want)

    def test_random_data_gives_the_same_result_for_every_chunk_size(self):
        rnd = random.Random(20261114)
        alphabet = [0, 0, 0, 1, 0xFF, 0x09, 0x20, 0x41, 0x42, 0x43, 0x7E, 0x7F]
        data = bytes(rnd.choice(alphabet) for _ in range(3000))
        for args in (("--min", "3"), ("--min", "2", "--utf16"), ("--min", "1", "--utf16")):
            want = self.scan(data, 1 << 20, *args)
            self.assertGreater(len(want), 10)
            for chunk in (1, 2, 3, 5, 8, 13, 64, 1000):
                with self.subTest(args=args, chunk=chunk):
                    self.assertEqual(self.scan(data, chunk, *args), want)


class Grep(unittest.TestCase):
    DATA = b"\x00event:/Engine_int\x00other-thing\x00Event:/turbo\x00bank_main\x00"

    def run_file(self, *args):
        with tmp() as d:
            (d / "x.bank").write_bytes(self.DATA)
            return run_main(d / "x.bank", *args)

    def test_grep_is_case_insensitive_and_keeps_only_matching_strings(self):
        code, out, err = self.run_file("--grep", "EVENT:/")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines(out), ["00000001: event:/Engine_int", "0000001f: Event:/turbo"])

    def test_grep_is_a_search_with_regex_syntax(self):
        code, out, _ = self.run_file("--grep", "^(other|bank)")
        self.assertEqual(code, 0)
        self.assertEqual(lines(out), ["00000013: other-thing", "0000002c: bank_main"])

    def test_grep_without_a_match_prints_nothing_and_exits_0(self):
        self.assertEqual(self.run_file("--grep", "nomatch"), (0, "", ""))

    def test_invalid_regex_is_an_error_line_on_stderr_and_exit_1(self):
        code, out, err = self.run_file("--grep", "(")
        self.assertEqual(code[:7], "error: ")
        self.assertIn("regex", code)
        self.assertEqual((out, err), ("", ""))

    def test_invalid_regex_through_the_command_line(self):
        with tmp() as d:
            (d / "x.bank").write_bytes(self.DATA)
            r = run_tool("bank_strings.py", d / "x.bank", "--grep", "[")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertTrue(r.stderr.startswith("error: "), r.stderr)

    def test_grep_applies_to_the_decoded_utf16_text_without_the_marker(self):
        with tmp() as d:
            (d / "x.bin").write_bytes(WIDE)
            code, out, _ = run_main(d / "x.bin", "--utf16", "--grep", "^engine$")
            self.assertEqual((code, lines(out)), (0, ["00000001: Engine [utf16]"]))
            code, out, _ = run_main(d / "x.bin", "--utf16", "--grep", "utf16")
            self.assertEqual((code, out), (0, ""))


class Utf16(unittest.TestCase):
    def test_utf16_strings_are_printed_in_offset_order_with_a_marker(self):
        with tmp() as d:
            (d / "x.bin").write_bytes(WIDE)
            r = run_tool("bank_strings.py", d / "x.bin", "--utf16")
            plain = run_tool("bank_strings.py", d / "x.bin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(lines(r.stdout), ["00000001: Engine [utf16]", "0000000e: abcd"])
        self.assertEqual(lines(plain.stdout), ["0000000e: abcd"])

    def test_utf16_minimum_counts_characters_not_bytes(self):
        with tmp() as d:
            (d / "x.bin").write_bytes(WIDE)
            code, out, _ = run_main(d / "x.bin", "--utf16", "--min", "2")
            self.assertEqual((code, lines(out)), (0, ["00000001: Engine [utf16]", "0000000e: abcd", "00000011: dab [utf16]"]))
            code, out, _ = run_main(d / "x.bin", "--utf16", "--min", "7")
            self.assertEqual((code, out), (0, ""))

    def test_a_utf16_string_may_start_at_an_odd_offset(self):
        with tmp() as d:
            (d / "x.bin").write_bytes(b"\x01\x01" + "wide".encode("utf-16-le") + b"\x01")
            code, out, _ = run_main(d / "x.bin", "--utf16")
        self.assertEqual((code, lines(out)), (0, ["00000002: wide [utf16]"]))


class Count(unittest.TestCase):
    def test_count_in_file_mode_prints_the_file_and_the_total(self):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(DATA)
            r = run_tool("bank_strings.py", f, "--count")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(lines(r.stdout), ["%s: 3" % f, "total: 3"])

    def test_count_with_grep_counts_only_matching_strings(self):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(DATA)
            code, out, _ = run_main(f, "--count", "--grep", "^hello")
        self.assertEqual((code, lines(out)), (0, ["%s: 1" % f, "total: 1"]))

    def test_count_includes_utf16_strings(self):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(WIDE)
            code, out, _ = run_main(f, "--count", "--utf16")
        self.assertEqual((code, lines(out)), (0, ["%s: 2" % f, "total: 2"]))

    def test_count_of_a_file_without_hits_is_zero(self):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(b"\x00\x01")
            code, out, _ = run_main(f, "--count")
        self.assertEqual((code, lines(out)), (0, ["%s: 0" % f, "total: 0"]))

    def test_count_in_folder_mode_omits_files_without_hits(self):
        with tmp() as d:
            write_tree(d, TREE)
            code, out, err = run_main(d, "--count")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines(out), ["a.bin: 1", "sub\\b.bin: 1", "sub\\c.bin: 2", "z.bin: 1", "total: 5"])

    def test_count_in_folder_mode_with_grep_drops_files_without_matches(self):
        with tmp() as d:
            write_tree(d, TREE)
            code, out, _ = run_main(d, "--count", "--grep", "gamma")
        self.assertEqual((code, lines(out)), (0, ["sub\\c.bin: 1", "total: 1"]))

    def test_count_in_an_empty_folder_is_only_the_total(self):
        with tmp() as d:
            self.assertEqual(run_main(d, "--count"), (0, "total: 0\n", ""))


class FolderMode(unittest.TestCase):
    def test_lines_are_prefixed_with_the_relative_path_in_name_order_depth_first(self):
        with tmp() as d:
            write_tree(d, TREE)
            r = run_tool("bank_strings.py", d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertEqual(lines(r.stdout), [
            "a.bin:00000001: alpha",
            "sub\\b.bin:00000000: beta1",
            "sub\\c.bin:00000002: gamma",
            "sub\\c.bin:00000008: delta",
            "z.bin:00000000: zulu!",
        ])

    def test_output_does_not_depend_on_creation_order(self):
        with tmp() as d1, tmp() as d2:
            write_tree(d1, TREE)
            write_tree(d2, dict(reversed(list(TREE.items()))))
            self.assertEqual(run_tool("bank_strings.py", d1).stdout, run_tool("bank_strings.py", d2).stdout)

    def test_grep_and_min_apply_to_every_file(self):
        with tmp() as d:
            write_tree(d, TREE)
            code, out, _ = run_main(d, "--min", "5", "--grep", "A$")
        self.assertEqual((code, lines(out)), (0, ["a.bin:00000001: alpha", "sub\\c.bin:00000002: gamma",
                                                  "sub\\c.bin:00000008: delta"]))

    def test_nested_folders_and_a_trailing_separator_on_the_argument(self):
        with tmp() as d:
            write_tree(d, {"x/y/z/deep.bin": b"\x00deep-string"})
            code, out, _ = run_main(str(d) + os.sep)
        self.assertEqual((code, lines(out)), (0, ["x\\y\\z\\deep.bin:00000001: deep-string"]))

    def test_a_non_ascii_file_name_is_printed_as_ascii(self):
        with tmp() as d:
            try:
                (d / "café.bin").write_bytes(b"\x00some-text")
            except OSError:
                self.skipTest("file system does not accept the name")
            r = run_tool("bank_strings.py", d)
        self.assertEqual(lines(r.stdout), ["caf\\xe9.bin:00000001: some-text"])

    def test_symlinked_folders_and_files_are_not_followed(self):
        with tmp() as d:
            write_tree(d, {"real/x.bin": b"\x00in-real"})
            try:
                os.symlink(d / "real", d / "dirlink", target_is_directory=True)
                os.symlink(d / "real" / "x.bin", d / "filelink.bin")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available")
            code, out, err = run_main(d)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines(out), ["real\\x.bin:00000001: in-real"])

    @unittest.skipUnless(os.name == "nt", "junctions are a Windows feature")
    def test_junctions_are_not_followed(self):
        with tmp() as d:
            write_tree(d, {"real/x.bin": b"\x00in-real"})
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(d / "junc"), str(d / "real")], capture_output=True)
            if made.returncode:
                self.skipTest("cannot create a junction")
            code, out, err = run_main(d)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines(out), ["real\\x.bin:00000001: in-real"])


class SkippedFiles(unittest.TestCase):
    @staticmethod
    def failing_open(name):
        real = open

        def fake(path, *a, **k):
            if os.fspath(path).endswith(name):
                raise PermissionError(13, "Permission denied")
            return real(path, *a, **k)
        return fake

    def test_an_unreadable_file_in_a_folder_is_skipped_with_a_line_on_stderr_and_exit_0(self):
        with tmp() as d:
            write_tree(d, TREE)
            with mock.patch("builtins.open", self.failing_open("b.bin")):
                code, out, err = run_main(d)
        self.assertEqual(code, 0)
        self.assertEqual(err, "skipped sub\\b.bin: Permission denied\n")
        self.assertEqual(lines(out), [
            "a.bin:00000001: alpha",
            "sub\\c.bin:00000002: gamma",
            "sub\\c.bin:00000008: delta",
            "z.bin:00000000: zulu!",
        ])

    def test_skipped_files_are_not_counted(self):
        with tmp() as d:
            write_tree(d, TREE)
            with mock.patch("builtins.open", self.failing_open("b.bin")):
                code, out, err = run_main(d, "--count")
        self.assertEqual(code, 0)
        self.assertEqual(err, "skipped sub\\b.bin: Permission denied\n")
        self.assertEqual(lines(out), ["a.bin: 1", "sub\\c.bin: 2", "z.bin: 1", "total: 4"])

    def test_an_unreadable_single_file_is_skipped_and_exit_0(self):
        with tmp() as d:
            f = d / "x.bin"
            f.write_bytes(DATA)
            with mock.patch("builtins.open", self.failing_open("x.bin")):
                code, out, err = run_main(f)
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(err, "skipped %s: Permission denied\n" % f)

    def test_an_unreadable_folder_is_skipped(self):
        with tmp() as d:
            write_tree(d, TREE)
            real = os.scandir

            def scandir(path):
                if os.path.basename(os.fspath(path)) == "sub":
                    raise PermissionError(13, "Permission denied")
                return real(path)
            with mock.patch.object(os, "scandir", scandir):
                code, out, err = run_main(d)
        self.assertEqual(code, 0)
        self.assertEqual(err, "skipped sub: Permission denied\n")
        self.assertEqual(lines(out), ["a.bin:00000001: alpha", "z.bin:00000000: zulu!"])


class Usage(unittest.TestCase):
    def assert_usage(self, *args):
        r = run_tool("bank_strings.py", *args)
        self.assertEqual(r.returncode, 2, args)
        self.assertEqual(r.stdout.strip(), USAGE.strip(), args)
        self.assertEqual(r.stderr, "", args)

    def test_usage_block_is_the_paragraph_after_the_title(self):
        self.assertTrue(USAGE.startswith("usage: python tools/bank_strings.py <file or folder>"), USAGE)
        self.assertNotIn("Exit code", USAGE)

    def test_no_arguments_print_the_usage_block_on_stdout_and_exit_2(self):
        self.assert_usage()

    def test_wrong_arguments_print_the_usage_block_and_exit_2(self):
        with tmp() as d:
            self.assert_usage(d, d)
            self.assert_usage(d, "--bogus")
            self.assert_usage(d, "--min")
            self.assert_usage(d, "--grep")
            self.assert_usage(d, "--min", "abc")
            self.assert_usage(d, "--min", "0")
            self.assert_usage(d, "--min", "-3")
            self.assert_usage("--count")

    def test_a_nonexistent_path_is_an_error_line_on_stderr_and_exit_1(self):
        with tmp() as d:
            r = run_tool("bank_strings.py", d / "does-not-exist")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertTrue(r.stderr.startswith("error: "), r.stderr)
        self.assertIn("does-not-exist", r.stderr)

    def test_an_absurd_minimum_is_an_error_line_not_a_traceback(self):
        with tmp() as d:
            r = run_tool("bank_strings.py", d, "--min", "99999999999999")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("error: "), r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
