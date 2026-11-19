"""Static checks of start_tuner.bat, start_logger.bat and tools/find_python.bat with plain text matching (no Windows, no batch interpreter).

TestBothStartFiles holds what the two start files share; TestStartTuner and TestStartLogger hold what only one of them promises;
TestFindPython holds the shared Python discovery.
"""
import re
import unittest

from support import ROOT

import logger
import tuner_server as ts

NAMES = ("start_tuner.bat", "start_logger.bat")
TUNER_BAT = (ROOT / "start_tuner.bat").read_text(encoding="ascii")
LOGGER_BAT = (ROOT / "start_logger.bat").read_text(encoding="ascii")
FIND_PYTHON_BAT = (ROOT / "tools" / "find_python.bat").read_text(encoding="ascii")
USER_GUIDE = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")


class TestBothStartFiles(unittest.TestCase):
    def test_paths_are_relative_to_the_batch_file(self):
        for name, text in zip(NAMES, (TUNER_BAT, LOGGER_BAT)):
            with self.subTest(name):
                self.assertIn("%~dp0", text)
                self.assertNotRegex(text, r"(?i)\b[a-z]:\\users\\")

    def test_the_file_is_plain_ascii_without_a_byte_order_mark(self):
        for name in NAMES:
            with self.subTest(name):
                raw = (ROOT / name).read_bytes()
                raw.decode("ascii")
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_every_line_ends_with_crlf(self):
        for name in NAMES:
            with self.subTest(name):
                raw = (ROOT / name).read_bytes()
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
                self.assertTrue(raw.endswith(b"\r\n"))

    def test_python_is_an_empty_override_line_filled_in_by_the_shared_helper_after_the_change_of_folder(self):
        for name, text in zip(NAMES, (TUNER_BAT, LOGGER_BAT)):
            with self.subTest(name):
                self.assertIn('set "PY="\n', text)
                self.assertNotIn("Python312", text)
                self.assertIn("Python 3.9 or newer", next(l for l in text.splitlines() if l.startswith("rem Optional: full path of python.exe")))
                call = r'call "%~dp0tools\find_python.bat"'
                self.assertIn(call, text)
                self.assertLess(text.index('set "PY="'), text.index(r'cd /d "%~dp0"'))
                self.assertLess(text.index(r'cd /d "%~dp0"'), text.index(call))
                self.assertLess(text.index(call), text.index('"%PY%" -I tools'))

    def test_a_missing_python_stops_with_two_lines_pause_and_exit_code_1(self):
        block = ('if not defined PY (\n'
                 '    echo Python 3.9 or newer not found.\n'
                 '    echo Install Python from python.org, or set the PY line in this file to the full path of python.exe.\n'
                 '    pause\n'
                 '    exit /b 1\n'
                 ')\n')
        for name, text in zip(NAMES, (TUNER_BAT, LOGGER_BAT)):
            with self.subTest(name):
                self.assertIn(block, text)
                self.assertLess(text.index(block), text.index('"%PY%" -I tools'))


class TestStartTuner(unittest.TestCase):
    def test_it_starts_the_server_script_of_the_repo_from_the_repo_root(self):
        self.assertIn(r'tools\tuner_server.py', TUNER_BAT)
        self.assertTrue((ROOT / "tools" / "tuner_server.py").is_file())
        self.assertIn(r'cd /d "%~dp0"', TUNER_BAT)
        self.assertEqual((ROOT / "start_tuner.bat").parent, ROOT)

    def test_python_runs_isolated_with_the_documented_port_flag(self):
        self.assertRegex(TUNER_BAT, r'"%PY%" -I tools\\tuner_server\.py --port (?:\d+|%PORT%)')
        self.assertIn("--port", ts.__doc__)

    def test_the_port_is_the_default_port_of_the_server_and_the_user_guide(self):
        self.assertEqual(set(re.findall(r"(?:--port |127\.0\.0\.1:|PORT=)(\d+)", TUNER_BAT)), {str(ts.DEFAULT_PORT)})
        self.assertEqual(ts.DEFAULT_PORT, 8090)
        self.assertIn("http://127.0.0.1:%d%s/" % (ts.DEFAULT_PORT, ts.BASE_PATH), USER_GUIDE)

    def test_the_user_guide_names_the_py_launcher_and_the_py_line(self):
        self.assertIn("`py` launcher", USER_GUIDE)
        self.assertIn("`PY` line in `start_tuner.bat`", USER_GUIDE)

    # the browser is opened after a fixed delay (ping -n 3 is about 2 s), not when the server listens
    def test_the_browser_is_opened_after_a_fixed_two_second_delay(self):
        self.assertRegex(TUNER_BAT, r'start "" /min cmd /c "ping -n 3 127\.0\.0\.1 >nul & start http://127\.0\.0\.1:(?:\d+|%PORT%)/ACESCT/"')
        self.assertIn("http://127.0.0.1:%PORT%" + ts.BASE_PATH + "/", TUNER_BAT)

    # the game package is passed on only when the user set GAME in the file
    def test_the_game_package_is_optional_and_passed_on_only_when_set(self):
        self.assertIn('set "GAME="', TUNER_BAT)
        self.assertIn("if defined GAME (", TUNER_BAT)
        self.assertIn(r'"%PY%" -I tools\tuner_server.py --port %PORT% --game "%GAME%"', TUNER_BAT)
        self.assertIn(r'"%PY%" -I tools\tuner_server.py --port %PORT%' + "\n", TUNER_BAT)
        self.assertIn("--game", ts.__doc__)

    def test_it_tells_the_user_about_the_windows_firewall_question_before_the_server_starts(self):
        line = next(l for l in TUNER_BAT.splitlines() if l.startswith("echo After the first start Windows asks"))
        self.assertIn("private network", line)
        self.assertIn("choose Allow", line)
        self.assertLess(TUNER_BAT.index(line), TUNER_BAT.index('"%PY%" -I tools'))


class TestStartLogger(unittest.TestCase):
    def test_it_starts_the_logger_script_of_the_repo_from_the_repo_root(self):
        self.assertIn(r"tools\logger.py", LOGGER_BAT)
        self.assertTrue((ROOT / "tools" / "logger.py").is_file())
        self.assertIn(r'cd /d "%~dp0"', LOGGER_BAT)
        self.assertEqual((ROOT / "start_logger.bat").parent, ROOT)
        self.assertLess(LOGGER_BAT.index(r'cd /d "%~dp0"'), LOGGER_BAT.index(r"tools\logger.py"))

    def test_python_runs_isolated(self):
        self.assertRegex(LOGGER_BAT, r'"%PY%" -I tools\\logger\.py\r?\n')
        self.assertIn("--work", logger.__doc__)
        self.assertIn("--logs", logger.__doc__)
        self.assertIn("--mods", logger.__doc__)

    def test_it_has_the_window_title(self):
        self.assertIn("title ACE Session Logger\n", LOGGER_BAT)

    def test_it_finds_the_same_python_as_the_tuner_start_file(self):
        line = lambda text: next(l for l in text.splitlines() if l.startswith("rem Optional: full path of python.exe"))
        self.assertEqual(line(LOGGER_BAT), line(TUNER_BAT))
        self.assertEqual(re.search(r'call "[^"]*find_python\.bat"', LOGGER_BAT).group(0), re.search(r'call "[^"]*find_python\.bat"', TUNER_BAT).group(0))

    def test_a_missing_python_stops_with_a_message_and_exit_code_1_like_the_tuner_start_file(self):
        block = re.search(r'if not defined PY \(\n.*?\n\)\n', LOGGER_BAT, re.S).group(0)
        self.assertEqual(block, re.search(r'if not defined PY \(\n.*?\n\)\n', TUNER_BAT, re.S).group(0))
        self.assertIn("exit /b 1", block)
        self.assertIn("pause", block)

    def test_the_window_stays_open_after_the_logger_stops(self):
        tail = LOGGER_BAT[LOGGER_BAT.index(r"tools\logger.py"):].splitlines()
        self.assertEqual(tail[1:], ["echo.", "echo The session logger has stopped.", "pause"])

    def test_it_starts_no_browser_and_takes_no_port(self):
        self.assertNotIn("start http", LOGGER_BAT)
        self.assertNotIn("PORT", LOGGER_BAT)

    def test_git_checks_batch_files_out_with_crlf(self):
        self.assertIn("*.bat text eol=crlf", (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines())


class TestFindPython(unittest.TestCase):
    def test_the_helper_exists_next_to_the_other_tools_and_is_plain_ascii_with_crlf(self):
        path = ROOT / "tools" / "find_python.bat"
        self.assertTrue(path.is_file())
        raw = path.read_bytes()
        raw.decode("ascii")
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertTrue(raw.endswith(b"\r\n"))

    def test_it_carries_py_out_to_the_caller_and_prints_nothing(self):
        self.assertNotRegex(FIND_PYTHON_BAT, r"(?im)^\s*setlocal")
        self.assertNotRegex(FIND_PYTHON_BAT, r"(?im)^\s*echo (?!off)")
        self.assertNotRegex(FIND_PYTHON_BAT, r"(?im)^\s*pause")

    def test_it_probes_the_override_the_py_launcher_python_on_path_and_the_install_folders_in_this_order(self):
        order = [
            'call :probe "%PY_OVERRIDE%"',
            'py -3 -c "import sys; print(sys.executable)"',
            'python -c "import sys; print(sys.executable)"',
            r'"%LOCALAPPDATA%\Programs\Python\Python3*"',
            r'"%ProgramFiles%\Python3*"',
        ]
        positions = [FIND_PYTHON_BAT.index(part) for part in order]
        self.assertEqual(positions, sorted(positions))

    def test_the_failing_probes_are_silent_and_the_result_is_only_taken_when_python_is_3_9_or_newer(self):
        self.assertIn('"%~1" -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul', FIND_PYTHON_BAT)
        self.assertIn('if not errorlevel 1 set "PY=%~1"', FIND_PYTHON_BAT)
        self.assertEqual(FIND_PYTHON_BAT.count("2^>nul"), 2)

    def test_a_candidate_is_only_taken_when_the_file_exists_and_a_found_python_is_kept(self):
        probe = FIND_PYTHON_BAT[FIND_PYTHON_BAT.index(":probe"):]
        self.assertIn("if defined PY exit /b 0", probe)
        self.assertIn('if not exist "%~1" exit /b 0', probe)
        self.assertEqual(len(re.findall(r"(?m)^if not defined PY for ", FIND_PYTHON_BAT)), 4)


if __name__ == "__main__":
    unittest.main()
