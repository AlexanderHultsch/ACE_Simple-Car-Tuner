"""Static checks of tuner/web/index.html with regular expressions only (no browser, no node).

The page is cut once into markup, <style> and <script>; the tests compare the three with each other (DOM ids, CSS classes, functions) and with tools/tuner_server.py (routes, header names, answer fields). The JS helpers are plain regexes: strings, comments and braces are only handled as far as this one file needs.
"""
import inspect
import re
import unittest

from support import ROOT

import tuner_server as ts

HTML = (ROOT / "tuner" / "web" / "index.html").read_text(encoding="utf-8")
README = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
USER_GUIDE = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
STYLE = re.search(r"<style>(.*?)</style>", HTML, re.S).group(1)
SCRIPT = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
MARKUP = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", HTML, flags=re.S)
CODE = re.sub(r"(?m)^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", SCRIPT, flags=re.S))
TITLE = "ACE - Simple Car Tuner"
# classes the script sets through a variable (addStat(.., "bad"), setMsg(.., "err")), not as a literal next to el() / classList
DYNAMIC_CLASSES = {"ok", "bad", "warn", "err"}
# the query parameter of every GET route that carries one
QUERY_PARAMS = {"/api/tyre": "id", "/api/log_file": "file"}


def function_body(name):
    """The text between the braces of a top-level function of the script (braces inside strings are not handled)."""
    m = re.search(r"(?:async )?function %s\([^)]*\) \{" % name, CODE)
    assert m, "no function %s in the script" % name
    depth, i = 1, m.end()
    while depth:
        depth += (CODE[i] == "{") - (CODE[i] == "}")
        i += 1
    return CODE[m.end():i - 1]


def dom_ids():
    return re.findall(r'\bid="([^"]+)"', MARKUP)


def referenced_ids():
    ids = set(re.findall(r"""\$\(\s*["']([^"']+)["']\s*\)""", CODE))
    ids |= set(re.findall(r"""getElementById\(\s*["']([^"']+)["']\s*\)""", CODE))
    ids |= set(re.findall(r"""querySelector(?:All)?\(\s*["']#([\w-]+)""", CODE))
    for array in re.findall(r"for \(const id of \[([^\]]*)\]", CODE):
        ids |= set(re.findall(r'"([^"]+)"', array))
    ids |= set(re.findall(r"""\bshowText\(\s*["']([^"']+)["']""", CODE))
    return ids


def css_classes():
    rules = STYLE
    while re.search(r"\{[^{}]*\}", rules):
        rules = re.sub(r"\{[^{}]*\}", " ", rules)
    return set(re.findall(r"\.([A-Za-z][\w-]*)", rules))


def used_classes():
    used = set()
    for m in re.finditer(r'\bclass="([^"]+)"', MARKUP):
        used |= set(m.group(1).split())
    for m in re.finditer(r'\bel\("[a-z0-9]+",\s*"([^"]*)"', CODE):
        used |= set(m.group(1).split())
    for m in re.finditer(r'classList\.(?:add|remove|toggle)\("([^"]+)"', CODE):
        used.add(m.group(1))
    for m in re.finditer(r'className = "([^"]+)"', CODE):
        used |= set(m.group(1).split())
    return used


def quoted_words(*objects):
    return {w for o in objects for w in re.findall(r'"(\w+)"', inspect.getsource(o))}


class TestStructure(unittest.TestCase):
    def test_the_file_is_cut_into_one_style_and_one_script(self):
        self.assertEqual(HTML.count("<style>"), 1)
        self.assertEqual(HTML.count("<script>"), 1)
        self.assertTrue(len(STYLE) > 1000 and len(SCRIPT) > 5000)
        self.assertNotIn("<script", MARKUP)

    def test_it_is_a_html5_page_in_english_with_a_viewport(self):
        self.assertTrue(HTML.startswith("<!DOCTYPE html>\n<html lang=\"en\">"))
        self.assertIn('<meta charset="utf-8">', HTML)
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', HTML)

    def test_the_page_is_ascii_only(self):
        HTML.encode("ascii")

    def test_the_page_loads_nothing_from_outside(self):
        self.assertEqual(re.findall(r"https?://", HTML), [])
        self.assertEqual(re.findall(r"\bsrc=", MARKUP), [])
        self.assertEqual(re.findall(r"@import|url\(", HTML), [])
        hrefs = re.findall(r'\bhref="([^"]*)"', MARKUP)
        self.assertEqual(hrefs, ["favicon.png", "favicon.ico", "apple-touch-icon.png", "manifest.webmanifest"])
        self.assertEqual(len(re.findall(r"<link\b", HTML)), len(hrefs))
        for href in hrefs:
            self.assertRegex(href, r"^[\w.-]+$")

    def test_brackets_of_the_script_balance(self):
        code = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', CODE)
        for opening, closing in ("()", "[]", "{}"):
            self.assertEqual(code.count(opening), code.count(closing), opening + closing)

    def test_all_dom_ids_are_unique(self):
        ids = dom_ids()
        self.assertEqual(len(ids), len(set(ids)))


class TestHead(unittest.TestCase):
    HEAD = re.search(r"<head>\n(.*?)</head>", HTML, re.S).group(1)
    BG = re.search(r"--color-bg: (#[0-9a-f]{6});", STYLE).group(1)

    def test_the_head_is_ascii_and_holds_one_title_and_one_viewport(self):
        self.HEAD.encode("ascii")
        self.assertEqual(self.HEAD.count("<title>"), 1)
        self.assertEqual(self.HEAD.count('name="viewport"'), 1)

    def test_the_icon_links_are_relative_to_the_page(self):
        for tag in ('<link rel="icon" type="image/png" sizes="32x32" href="favicon.png">',
                    '<link rel="icon" href="favicon.ico" sizes="any">',
                    '<link rel="apple-touch-icon" href="apple-touch-icon.png">',
                    '<link rel="manifest" href="manifest.webmanifest">'):
            with self.subTest(tag):
                self.assertEqual(self.HEAD.count(tag + "\n"), 1)

    def test_the_icon_files_are_served_by_the_server(self):
        for name in re.findall(r'<link [^>]*href="([^"]+)"', self.HEAD):
            with self.subTest(name):
                self.assertIn("/" + name, ts.STATIC_FILES)

    def test_the_theme_colour_is_the_dark_background_of_the_page(self):
        self.assertEqual(self.BG, "#0e1013")
        self.assertIn('<meta name="theme-color" content="%s">\n' % self.BG, self.HEAD)

    def test_the_page_can_be_added_to_the_home_screen_as_an_app(self):
        for tag in ('<meta name="apple-mobile-web-app-capable" content="yes">',
                    '<meta name="mobile-web-app-capable" content="yes">',
                    '<meta name="apple-mobile-web-app-title" content="ACE Tuner">',
                    '<meta name="apple-mobile-web-app-status-bar-style" content="black">'):
            with self.subTest(tag):
                self.assertEqual(self.HEAD.count(tag + "\n"), 1)

    def test_the_head_ends_with_the_style_and_has_no_script(self):
        self.assertNotIn("<script", self.HEAD)
        self.assertEqual(self.HEAD.count("<style>"), 1)
        self.assertTrue(self.HEAD.index("<title>") < self.HEAD.index("<link") < self.HEAD.index("<style>"))


class TestDomIds(unittest.TestCase):
    def test_every_id_the_script_looks_up_exists_in_the_markup(self):
        self.assertEqual(sorted(referenced_ids() - set(dom_ids())), [])

    def test_the_script_looks_up_a_known_set_of_ids(self):
        self.assertTrue({"status", "progress", "init-panel", "tuner", "rows", "car-select", "btn-apply", "btn-duplicate", "btn-init",
                         "btn-reset-all", "search", "changed-only", "name-host", "untested", "caption", "empty",
                         "dialog", "dialog-title", "dialog-id", "dialog-suffix", "dialog-hint", "dialog-error", "dialog-ok",
                         "dialog-cancel"}
                        <= referenced_ids(), sorted(referenced_ids()))

    def test_every_id_in_the_markup_is_referenced_by_the_script(self):
        self.assertLessEqual(set(dom_ids()) - referenced_ids(), set())


class TestFunctions(unittest.TestCase):
    def test_the_script_defines_the_functions_the_page_needs(self):
        names = set(re.findall(r"^(?:async )?function (\w+)", CODE, re.M))
        self.assertTrue({"api", "refresh", "renderStatus", "renderCars", "renderButtons", "renderProgress", "buildTable", "buildRow",
                         "loadSettings", "startJob", "resetAll", "switchCar", "applyFilter", "openDialog", "closeDialog", "submitDialog",
                         "dialogKey"} <= names, sorted(names))

    def test_every_function_is_referenced_at_least_once_besides_its_definition(self):
        for name in re.findall(r"^(?:async )?function (\w+)", CODE, re.M):
            with self.subTest(name):
                self.assertGreaterEqual(len(re.findall(r"\b%s\b" % name, CODE)), 2)

    def test_every_top_level_variable_is_used(self):
        for name in re.findall(r"^(?:let|const) (\w+)", CODE, re.M):
            with self.subTest(name):
                self.assertGreaterEqual(len(re.findall(r"(?<![\w$])%s(?![\w$])" % re.escape(name), CODE)), 2)

    def test_the_script_runs_in_strict_mode(self):
        self.assertTrue(CODE.lstrip().startswith('"use strict";'))


class TestNoInjectionSinks(unittest.TestCase):
    def test_no_html_is_ever_built_from_text(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"",
                     "setInterval(\"", "createContextualFragment", "srcdoc"):
            with self.subTest(sink):
                self.assertNotIn(sink, HTML)

    def test_no_inline_event_handlers_or_javascript_urls(self):
        self.assertEqual(re.findall(r"\son[a-z]+\s*=", MARKUP), [])
        self.assertNotIn("javascript:", HTML)

    def test_server_text_enters_the_page_as_text_only(self):
        self.assertIn("textContent", CODE)
        self.assertIn("createTextNode", CODE)


def called_paths():
    """The route paths the script writes as plain strings, plus the routes of ts.QUERY_ROUTES, which the script writes with their
    query string: "/api/tyre?id=" + encodeURIComponent(id). No other route may carry a query string."""
    paths = set(re.findall(r'"(/api/[^"?]*)"', CODE))
    return paths | {p for p, key in re.findall(r'"(/api/[^"?]*)\?(\w+)=" \+ encodeURIComponent\(', CODE) if p in ts.QUERY_ROUTES and QUERY_PARAMS[p] == key}


class TestApiContract(unittest.TestCase):
    ROUTES = list(ts.GET_ROUTES) + list(ts.POST_ROUTES)

    def test_the_script_has_one_fetch_call(self):
        self.assertEqual(len(re.findall(r"\bfetch\(", CODE)), 1)
        self.assertEqual(len(re.findall(r"XMLHttpRequest|WebSocket|sendBeacon", CODE)), 0)

    def test_every_api_path_in_the_script_is_a_route_of_the_server(self):
        paths = called_paths()
        self.assertTrue(paths)
        self.assertEqual(sorted(paths - set(self.ROUTES)), [])

    def test_every_route_of_the_server_is_called_by_the_page(self):
        self.assertEqual(sorted(set(self.ROUTES) - called_paths()), [])

    def test_get_routes_are_called_without_a_body_and_post_routes_with_one(self):
        for route in (r for r in ts.GET_ROUTES if r in self.ROUTES and r not in ts.QUERY_ROUTES):
            with self.subTest(route):
                self.assertRegex(CODE, r'api\("%s", undefined' % route)
                self.assertNotRegex(CODE, r'(?:api|startJob|writeTyre)\("%s", \{' % route)
        # a GET route with a query string carries the id of the tyre or the name of the file there and still has no body
        for route in ts.QUERY_ROUTES:
            with self.subTest(route):
                self.assertRegex(CODE, r'api\("%s\?%s=" \+ encodeURIComponent\(\w+\), undefined, selection\)' % (route, QUERY_PARAMS[route]))
                self.assertNotRegex(CODE, r'(?:api|startJob)\("%s"' % route)
                self.assertNotRegex(CODE, r'(?:api|startJob)\("%s\?%s=[^)]*, \{' % (route, QUERY_PARAMS[route]))
        for route in (r for r in ts.POST_ROUTES if r in self.ROUTES):
            with self.subTest(route):
                self.assertRegex(CODE, r'(?:api|startJob|writeTyre)\("%s", \{' % route)
                self.assertNotRegex(CODE, r'api\("%s", undefined' % route)

    def test_api_requests_are_relative_to_the_page_below_the_base_path(self):
        self.assertIn(r'res = await fetch(path.replace(/^\//, ""), opts);', function_body("api"))
        self.assertEqual(re.findall(r"\bfetch\((\w+)", CODE), ["path"])
        self.assertEqual(re.findall(r"\b(?:href|src|action)\s*=|EventSource|location\.(?!hostname\b)|window\.open|<(?:a|link|img|form|iframe)\b", re.sub(r'<link rel="[a-z-]+"[^>]*>', "", HTML)), [])

    def test_the_page_sends_the_headers_the_server_demands(self):
        body = function_body("api")
        self.assertIn('"Content-Type": "application/json"', body)
        self.assertIn('"X-Tuner": "1"', body)
        self.assertIn('method: "POST"', body)

    def test_the_car_and_the_tune_go_in_the_query_of_a_get_and_in_the_body_of_a_post(self):
        body = function_body("api")
        self.assertIn('"car=" + encodeURIComponent(target.car)', body)
        self.assertIn('"tune=" + encodeURIComponent(target.tune)', body)
        self.assertIn("{ car: target.car, tune: target.tune }", body)

    def test_every_api_call_of_the_page_passes_the_selection_which_carries_the_tune(self):
        calls = re.findall(r"await api\((.*)\);$", CODE, re.M)
        self.assertEqual(len(calls), 36, calls)
        for call in calls:
            with self.subTest(call):
                self.assertRegex(call, r", (?:want|target|r\.target|selection)$")
        plain = set(re.findall(r'\b(?:api|startJob|writeTyre)\("(/api/[a-z_]+)"', CODE))
        queried = {r for r in ts.QUERY_ROUTES if re.search(r'\bapi\("%s\?%s=" \+ encodeURIComponent\(\w+\), undefined, selection\)' % (r, QUERY_PARAMS[r]), CODE)}
        self.assertEqual(sorted(plain | queried), sorted(self.ROUTES))
        self.assertEqual(re.findall(r"async function api\((.*?)\) \{", CODE), ["path, body, target"])

    def test_the_bodies_of_apply_and_duplicate_use_the_fields_of_the_server(self):
        self.assertNotRegex(CODE, r"\bmode\b")
        self.assertEqual(re.findall(r'api\("/api/apply", (\{[^}]*\}), \w+\)', CODE), ["{ new_id: newId, suffix: suffix }"])
        self.assertEqual(re.findall(r'api\("/api/duplicate", (\{[^}]*\}), \w+\)', CODE), ["{ new_id: newId, suffix: suffix }"])
        self.assertIn('startJob("/api/apply", {})', CODE)
        sent = set(re.findall(r'"(\w+)"', inspect.getsource(ts.api_apply) + inspect.getsource(ts.api_duplicate)))
        self.assertTrue({"new_id", "suffix", "tune"} <= sent, sorted(sent))
        # an empty field sends nothing: undefined is dropped by JSON.stringify
        body = function_body("submitDialog")
        self.assertIn('const newId = $("dialog-id").value.trim() || undefined;', body)
        self.assertIn('const suffix = $("dialog-suffix").value || undefined;', body)

    def test_the_routes_of_the_page_are_the_routes_of_the_server(self):
        self.assertEqual(called_paths(), set(self.ROUTES))

    def test_the_state_fields_the_page_reads_are_sent_by_the_server(self):
        sent = quoted_words(ts.api_state, ts.installed_info, ts.modded_cars, ts.tune_proposals) | set(ts.JOB)
        read = set(re.findall(r"\bserverState\.(\w+)", CODE)) | set(re.findall(r"\binst\.(\w+)", CODE)) | set(re.findall(r"\bjob\.(\w+)", CODE))
        self.assertTrue({"base_present", "game_running", "job", "installed", "cars", "car", "work", "tune", "modded", "modded_error",
                         "proposed_new_id", "proposed_suffix", "stock_id_length"} <= read, sorted(read))
        self.assertEqual(sorted(read - sent), [])

    def test_the_row_fields_the_page_reads_are_sent_by_the_server(self):
        # the rows of the tyre editor come from tune.tyre_rows: its quoted keys and its keyword arguments
        sent = quoted_words(ts.row_json, ts.tune.tyre_rows) | set(re.findall(r"\b(\w+)=", inspect.getsource(ts.tune.tyre_rows)))
        read = set(re.findall(r"\b(?:data|d)\.(\w+)", CODE)) - {"error"}
        self.assertTrue({"id", "label", "type", "value", "default", "changed", "choices", "ui", "copy_values", "axle", "applicable",
                         "reason"} <= read, sorted(read))
        self.assertEqual(sorted(read - sent), [])

    def test_the_page_polls_in_the_documented_rhythm(self):
        consts = dict(re.findall(r"^const (\w+_MS) = (\d+);", CODE, re.M))
        poll_idle, poll_busy, debounce = (int(consts[k]) for k in ("POLL_IDLE_MS", "POLL_BUSY_MS", "DEBOUNCE_MS"))
        self.assertTrue(1000 <= poll_idle <= 60000, poll_idle)
        self.assertTrue(500 <= poll_busy < poll_idle, poll_busy)
        self.assertTrue(100 <= debounce <= 2000, debounce)
        self.assertIn("setTimeout(refresh, document.hidden ? POLL_HIDDEN_MS : (busy ? POLL_BUSY_MS : POLL_IDLE_MS))", CODE)

    def test_the_page_polls_faster_while_a_job_runs(self):
        self.assertIn("const busy = jobRunning();", CODE)


class TestCssClasses(unittest.TestCase):
    def test_every_class_the_markup_and_script_use_has_a_css_rule(self):
        self.assertEqual(sorted((used_classes() | DYNAMIC_CLASSES) - css_classes()), [])

    def test_every_css_class_is_used_by_the_markup_or_the_script(self):
        self.assertEqual(sorted(css_classes() - used_classes() - DYNAMIC_CLASSES), [])

    def test_the_dynamic_classes_are_in_the_script_as_literals(self):
        for cls in DYNAMIC_CLASSES:
            with self.subTest(cls):
                self.assertIn('"%s"' % cls, CODE)

    def test_the_class_collectors_see_the_main_classes(self):
        self.assertTrue({"panel", "strip", "namerow", "mono", "badge", "accent", "small", "changed", "valuewrap", "page", "sr-only"}
                        <= used_classes(), sorted(used_classes()))

    def test_every_css_custom_property_that_is_defined_is_used(self):
        defined = set(re.findall(r"(--[\w-]+):", STYLE))
        for name in sorted(defined):
            with self.subTest(name):
                self.assertIn("var(%s)" % name, STYLE)

    def test_every_custom_property_that_is_used_is_defined(self):
        self.assertEqual(sorted(set(re.findall(r"var\((--[\w-]+)\)", STYLE)) - set(re.findall(r"(--[\w-]+):", STYLE))), [])


class TestDarkTheme(unittest.TestCase):
    TOKENS = {"--color-bg": "#0e1013", "--color-bg-alt": "#16191f", "--color-bg-elevated": "#1c2028", "--color-text": "#e8eaed",
              "--color-text-muted": "#9aa1ac", "--color-border": "#2a2f38", "--color-accent": "#4f8cff",
              "--color-accent-contrast": "#0e1013"}
    ROOT_RULE = re.search(r":root \{(.*?)\n\}", STYLE, re.S).group(1)
    OUTSIDE_ROOT = STYLE.replace(ROOT_RULE, "")
    ALLOWED = {"transparent", "inherit", "currentColor", "none"}

    def test_the_tokens_of_the_site_are_defined_on_root_with_their_exact_values(self):
        for name, value in self.TOKENS.items():
            with self.subTest(name):
                self.assertRegex(self.ROOT_RULE, r"%s: %s;" % (re.escape(name), re.escape(value)))
        self.assertRegex(self.ROOT_RULE, r'--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;')
        self.assertRegex(self.ROOT_RULE, r'--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;')

    def test_the_page_is_dark_only(self):
        self.assertIn("color-scheme: dark;", self.ROOT_RULE)
        self.assertNotIn("light", re.sub(r"color-scheme: dark;", "", STYLE))
        self.assertNotIn("prefers-color-scheme", STYLE)

    def test_colours_are_written_only_in_the_root_rule(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(", self.OUTSIDE_ROOT), [])

    def test_every_colour_and_background_value_is_a_token_or_on_the_allowed_list(self):
        found = re.findall(r"(?:^|[;{\s])((?:background|color|border(?:-[a-z]+)*-color|outline-color|accent-color))\s*:\s*([^;}]+)", self.OUTSIDE_ROOT)
        self.assertTrue(len(found) > 40, len(found))
        for prop, value in found:
            with self.subTest(prop + ": " + value):
                self.assertTrue(re.fullmatch(r"var\(--[\w-]+\)", value.strip()) or value.strip() in self.ALLOWED, value)

    def test_borders_and_outlines_use_tokens_for_their_colour(self):
        for prop, value in re.findall(r"(?:^|[;{\s])((?:border(?:-(?:top|right|bottom|left))?|outline)):\s*([^;}]+)", self.OUTSIDE_ROOT):
            with self.subTest(prop + ": " + value):
                self.assertRegex(value, r"^(?:0|none|\S+ solid (?:var\(--[\w-]+\)|currentColor))$")

    def test_the_font_stacks_come_from_the_tokens(self):
        self.assertIn("font: 15px/1.45 var(--font-sans);", STYLE)
        self.assertIn(".mono { font-family: var(--font-mono); }", STYLE)

    def test_the_primary_button_is_accent_filled_with_the_contrast_text(self):
        self.assertIn("button.primary { background: var(--color-accent); border-color: var(--color-accent); color: var(--color-accent-contrast); }", STYLE)

    def test_the_focus_ring_is_two_pixels_of_the_accent(self):
        self.assertIn("outline: 2px solid var(--color-accent); outline-offset: 1px;", STYLE)


class TestTexts(unittest.TestCase):
    def test_the_title_and_the_heading_are_the_product_name(self):
        self.assertEqual(re.search(r"<title>(.*?)</title>", HTML).group(1), TITLE)
        self.assertEqual(re.search(r"<h1[^>]*>(.*?)</h1>", MARKUP).group(1), TITLE)

    def test_the_readme_and_the_user_guide_use_the_same_name(self):
        self.assertTrue(README.startswith("# " + TITLE + "\n"), README[:60])
        self.assertTrue(USER_GUIDE.startswith("# " + TITLE + ": user guide\n"), USER_GUIDE[:60])

    def test_the_readme_is_short_and_links_to_the_user_guide(self):
        self.assertLessEqual(len(README.splitlines()), 60)
        self.assertIn("](USER_GUIDE.md)", README)

    def test_the_readme_has_dropped_the_tested_cars_and_the_modded_car_passages(self):
        self.assertNotIn("Tested cars:", README)
        self.assertNotIn("A tuned copy of a car is a modded car", README)

    def test_relative_links_of_the_readme_and_the_user_guide_resolve_under_docs(self):
        for name, text in (("README.md", README), ("USER_GUIDE.md", USER_GUIDE)):
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                if re.match(r"(?:https?:|mailto:|#)", target):
                    continue
                with self.subTest(file=name, target=target):
                    self.assertTrue((ROOT / "docs" / target.split("#")[0]).is_file())

    def test_the_buttons_carry_the_labels_the_user_guide_names(self):
        for label in ("Create modded car&hellip;", "Duplicate&hellip;", "Install car (pull game files)", "Reset all"):
            with self.subTest(label):
                self.assertIn(">%s</button>" % label, MARKUP)
        self.assertIn("changed only", MARKUP)
        self.assertIn('el("button", "small", "reset")', CODE)
        for label in ("Install car (pull game files)", "Tyre Creator", "Garage tyres", "Expand all", "changed only",
                      "show advanced settings", "reset", "Reset all", "Create modded car", "Duplicate"):
            self.assertIn(label, USER_GUIDE)

    def test_the_tables_have_the_documented_columns_in_order(self):
        heads = [h.replace("<br>", " ") for h in re.findall(r'<th scope="col">(.*?)</th>', MARKUP)]
        self.assertEqual(heads, ["Variable name", "Value", "Default (for the selected car)", "Range for base cars", "Description",
                                 "Variable name", "Value", "Default (source tyre)", "Description",
                                 "File", "Car", "Track", "Duration", "Samples", "Size", "Modified", "Copy for AI"])

    def test_both_default_headers_break_the_line_directly_before_the_opening_bracket(self):
        heads = re.findall(r'<th scope="col">(Default.*?)</th>', MARKUP)
        self.assertEqual(heads, ["Default<br>(for the selected car)", "Default<br>(source tyre)"])

    def test_the_dialog_tells_the_id_rules_of_the_server(self):
        body = function_body("openDialog")
        self.assertIn('"The id has exactly " + serverState.stock_id_length +', body)
        self.assertIn('" characters: lower case letters, digits, underscore"', body)


    def test_the_header_label_and_the_stock_name_end_in_a_space_that_is_not_collapsed(self):
        body = function_body("buildHeaderRow")
        self.assertIn('el("span", "label", "Name in the game\'s car list: ")', body)
        self.assertIn('el("span", "stockname", carName() + " ")', body)
        self.assertRegex(STYLE, r"\.namerow \.label \{[^}]*white-space: pre;")
        self.assertRegex(STYLE, r"\.stockname \{[^}]*white-space: pre;")

    def test_the_dialog_says_the_game_shows_the_stock_name_a_space_and_the_suffix(self):
        panel = re.search(r'<section id="dialog".*?</section>', MARKUP, re.S).group(0)
        self.assertIn('<p class="hint">The game shows the stock car\'s name, a space and the name suffix.</p>', panel)
        self.assertLess(panel.index('id="dialog-suffix"'), panel.index("a space and the name suffix"))

    def test_the_page_never_mentions_the_old_default_and_never_joins_a_name_and_a_suffix_itself(self):
        self.assertNotIn("_MY", HTML)
        self.assertEqual(re.findall(r"underscore", HTML), ["underscore"])
        self.assertIn("underscore", function_body("openDialog"))
        self.assertNotIn("name_suffix", CODE)

    def test_the_suffix_field_is_trimmed_like_every_other_text_field(self):
        body = function_body("commit")
        self.assertIn("const text = r.field.value.trim();", body)
        self.assertNotIn("name_suffix", body)


class TestAccessibility(unittest.TestCase):
    def test_the_controls_have_accessible_names(self):
        self.assertIn('<select id="car-select" aria-label="Car"', MARKUP)
        self.assertIn('aria-label="Search settings"', MARKUP)
        self.assertIn('setAttribute("aria-label", "Value of " + d.label)', CODE)
        self.assertIn('<caption id="caption" class="sr-only">', MARKUP)

    def test_status_and_row_messages_are_live_regions(self):
        self.assertIn('id="status" class="strip" role="status" aria-live="polite"', MARKUP)
        self.assertIn('id="progress"', MARKUP)
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)

    def test_keyboard_focus_is_visible_and_the_hidden_attribute_wins(self):
        self.assertIn("button:focus-visible, input:focus-visible, select:focus-visible", STYLE)
        self.assertIn("[hidden] { display: none !important; }", STYLE)

    def test_the_native_controls_follow_the_dark_theme(self):
        self.assertIn("color-scheme: dark;", STYLE)

    def test_render_status_skips_the_rebuild_when_nothing_changed(self):
        body = function_body("renderStatus")
        guard = re.search(r"if \(sig === \w+\) return;", body)
        self.assertIsNotNone(guard, "renderStatus has no signature guard")
        self.assertLess(guard.start(), body.index("replaceChildren"))

    def test_render_cars_and_render_progress_have_the_signature_guard(self):
        self.assertIn("if (sig === carsSig) return;", function_body("renderCars"))
        self.assertIn("if (sig === jobSig) return;", function_body("renderProgress"))

    def test_the_badges_have_text_for_screen_readers(self):
        body = function_body("buildRow")
        self.assertEqual(body.count('"badge'), 2)
        self.assertGreaterEqual(body.count('"sr-only"'), 2)

    def test_the_suggested_range_is_available_to_screen_readers(self):
        self.assertIn('setAttribute("aria-description"', function_body("buildField"))


class TestCollapsibleGroups(unittest.TestCase):
    def test_a_group_header_is_a_toggle_button_inside_the_rowgroup_cell(self):
        body = function_body("buildGroup")
        self.assertIn('th.scope = "rowgroup";', body)
        self.assertIn('el("button", "grouptoggle")', body)
        self.assertIn('g.btn.type = "button";', body)
        self.assertIn('g.btn.setAttribute("aria-expanded", "false");', body)
        self.assertIn('th.appendChild(g.btn);', body)
        self.assertIn('el("span", "gname", name)', body)
        self.assertIn('chev.setAttribute("aria-hidden", "true");', body)
        self.assertIn('g.btn.addEventListener("click", () => toggleGroup(g));', body)
        self.assertIn("buildGroup(data.group)", function_body("buildTable"))

    def test_the_toggle_controls_the_rows_of_its_group(self):
        body = function_body("buildTable")
        self.assertIn('r.tr.id = "row-" + rows.length;', body)
        self.assertIn('g.btn.setAttribute("aria-controls", g.rows.map((r) => r.tr.id).join(" "));', body)

    def test_the_chevron_is_css_only_and_rotates_with_aria_expanded(self):
        self.assertRegex(STYLE, r"\.chev \{[^}]*border-right: 2px solid currentColor; border-bottom: 2px solid currentColor;[^}]*transform: rotate\(-45deg\);")
        self.assertIn('.grouptoggle[aria-expanded="true"] .chev { transform: rotate(45deg); }', STYLE)
        self.assertIn("@media (prefers-reduced-motion: reduce)", STYLE)
        self.assertNotRegex(CODE, r"\\u25|&#x?2[0-9a-f]+;")

    def test_every_group_starts_collapsed(self):
        self.assertRegex(CODE, r"(?m)^const expanded = new Set\(\);")
        self.assertIn("expanded.has(g.name)", function_body("applyFilter"))
        self.assertNotRegex(CODE, r"expanded = new Set\([^)]")

    def test_toggling_flips_the_remembered_state_and_applies_it(self):
        body = function_body("toggleGroup")
        self.assertIn("if (!expanded.delete(g.name)) expanded.add(g.name);", body)
        self.assertIn("applyFilter();", body)

    def test_the_rows_of_a_collapsed_group_are_hidden_not_removed(self):
        body = function_body("applyFilter")
        self.assertIn("r.tr.hidden = !(open && r.match);", body)
        self.assertNotIn("remove(", body)

    def test_the_count_names_the_settings_and_the_changed_ones_and_follows_the_rows(self):
        body = function_body("applyFilter")
        self.assertIn('"(" + listed + (listed === 1 ? " setting, " : " settings, ") + changed + " changed)"', body)
        self.assertIn("if (r.data.changed && !unlisted) changed += 1;", body)
        self.assertIn("if (refilter) applyFilter();", function_body("showRow"))

    def test_the_expanded_state_is_kept_by_edits_polls_and_a_table_rebuild_and_cleared_by_a_switch(self):
        self.assertIn("expanded.clear();", function_body("switchCar"))
        for name in ("buildTable", "clearTable", "showRow", "refresh", "loadSettings", "resetAll", "sendSet"):
            with self.subTest(name):
                self.assertNotIn("expanded.clear()", function_body(name))
                self.assertNotIn("new Set", function_body(name))
        self.assertEqual(len(re.findall(r"expanded\.clear\(\)", CODE)), 2)

    def test_a_filter_opens_the_groups_with_matches_without_changing_the_remembered_state(self):
        body = function_body("applyFilter")
        self.assertIn('const filtering = q !== "" || changedOnly;', body)
        self.assertIn("const open = filtering ? any : expanded.has(g.name);", body)
        self.assertIn("g.tr.hidden = !any;", body)
        self.assertNotIn("expanded.add", body)
        self.assertNotIn("expanded.delete", body)
        self.assertIn('$("search").addEventListener("input", applyFilter);', CODE)
        self.assertIn('$("changed-only").addEventListener("change", applyFilter);', CODE)

    def test_the_filter_message_logic_is_unchanged(self):
        self.assertIn('$("empty").hidden = visible > 0 || rows.length === 0;', function_body("applyFilter"))
        self.assertIn("if (any) visible += 1;", function_body("applyFilter"))

    def test_expand_all_and_collapse_all_are_buttons_next_to_the_filters_and_wired(self):
        bar = re.search(r'<div class="toolbar">.*?</div>', MARKUP, re.S).group(0)
        self.assertRegex(bar, r'(?s)id="changed-only".*<button id="btn-expand-all" type="button">Expand all</button>\s*'
                              r'<button id="btn-collapse-all" type="button">Collapse all</button>\s*<span class="spacer">')
        self.assertIn('$("btn-expand-all").addEventListener("click", () => setAllGroups(true));', CODE)
        self.assertIn('$("btn-collapse-all").addEventListener("click", () => setAllGroups(false));', CODE)
        body = function_body("setAllGroups")
        self.assertIn("for (const g of groups) expanded.add(g.name);", body)
        self.assertIn("expanded.clear();", body)
        self.assertIn("applyFilter();", body)

    def test_a_message_in_a_row_opens_its_group(self):
        self.assertIn("if (text) revealGroup(r);", function_body("setMsg"))
        body = function_body("revealGroup")
        self.assertIn("groups.includes(r.group)", body)
        self.assertIn("expanded.add(r.group.name);", body)
        self.assertIn("applyFilter();", body)
        self.assertIn("r.group = current;", function_body("buildTable"))
        self.assertIn("group: null", function_body("newRow"))

    def test_the_toggles_announce_nothing_through_a_live_region(self):
        for name in ("buildGroup", "toggleGroup", "setAllGroups", "revealGroup", "applyFilter"):
            with self.subTest(name):
                self.assertNotIn("aria-live", function_body(name))
                self.assertNotIn("role", function_body(name))
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)

    def test_the_group_toggle_has_a_visible_focus_ring_inside_its_cell(self):
        self.assertIn("button.grouptoggle:focus-visible { outline-offset: -2px; }", STYLE)


class TestAdvancedSettings(unittest.TestCase):
    TOOLBAR = re.search(r'<div class="toolbar">.*?</div>', MARKUP, re.S).group(0)

    def test_the_box_sits_next_to_changed_only_with_its_label_and_is_unchecked(self):
        self.assertIn('<label><input id="show-advanced" type="checkbox"> <span id="show-advanced-text">show advanced settings</span></label>',
                      self.TOOLBAR)
        self.assertRegex(self.TOOLBAR, r'(?s)id="changed-only".*?id="show-advanced".*?id="btn-expand-all"')
        self.assertNotRegex(re.search(r'<input id="show-advanced"[^>]*>', MARKUP).group(0), r"\bchecked\b")

    def test_the_choice_is_a_boolean_for_the_life_of_the_page(self):
        self.assertRegex(CODE, r"(?m)^let showAdvanced = false;")
        self.assertIn('showAdvanced = $("show-advanced").checked;', CODE)
        for name in ("switchCar", "buildTable", "clearTable", "loadSettings", "refresh"):
            with self.subTest(name):
                self.assertNotIn("showAdvanced", function_body(name))
                self.assertNotIn("show-advanced", function_body(name))

    def test_ticking_the_box_runs_the_filter_and_touches_no_group(self):
        m = re.search(r'\$\("show-advanced"\)\.addEventListener\("change", \(\) => \{(.*?)\}\);', CODE, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).split(), ['showAdvanced', '=', '$("show-advanced").checked;', 'applyFilter();'])
        self.assertNotIn("expanded", m.group(1))

    def test_an_advanced_row_is_unlisted_unless_the_box_is_ticked_or_the_row_is_changed(self):
        body = function_body("applyFilter")
        self.assertIn("const unlisted = !!r.data.advanced && !showAdvanced && !r.data.changed;", body)
        self.assertIn("r.match = !unlisted && (!q || r.hay.includes(q)) && (!changedOnly || r.data.changed);", body)
        self.assertIn("r.tr.hidden = !(open && r.match);", body)
        self.assertIn("g.tr.hidden = !any;", body)

    def test_the_group_counts_leave_out_the_unlisted_rows_and_the_toggle_keeps_all_rows(self):
        body = function_body("applyFilter")
        self.assertIn("if (!unlisted) listed += 1;", body)
        self.assertNotIn("g.rows.length", body)
        self.assertIn('g.btn.setAttribute("aria-controls", g.rows.map((r) => r.tr.id).join(" "));', function_body("buildTable"))

    def test_the_label_carries_the_number_of_hidden_advanced_rows(self):
        body = function_body("applyFilter")
        self.assertIn("if (unlisted) advancedHidden += 1;", body)
        self.assertIn('"show advanced settings" + (advancedHidden > 0 ? " (" + advancedHidden + " hidden)" : "")', body)
        self.assertIn('$("show-advanced-text").textContent', body)

    def test_the_filter_does_not_open_or_close_groups_for_the_box(self):
        body = function_body("applyFilter")
        self.assertNotIn("expanded.add", body)
        self.assertNotIn("expanded.delete", body)
        self.assertNotIn("expanded.clear", body)

    def test_the_tyre_creator_warns_below_the_intro_with_the_warning_class(self):
        text = ("Kunos advises against editing the tyre model values: the code that connects them is not user-controlled, and a changed "
                "calibration can make a tyre behave unpredictably (tyres may need too much slip to grip or react nervously). "
                "Change little and test in the game.")
        section = TestTabs.TYRES_PANEL.split("<section", 1)[1].split("</section>", 1)[0]
        paragraphs = re.findall(r"<p\b([^>]*)>(.*?)</p>", section)
        self.assertEqual([p[1] for p in paragraphs][1], text)
        self.assertEqual(paragraphs[1][0].strip(), 'class="msg warn"')
        self.assertTrue(paragraphs[0][1].startswith("Tyres you create here"))
        self.assertIn(".msg.warn { color: var(--color-warning); }", STYLE)

    def test_the_warning_text_reads_on_the_panel_background(self):
        tokens = dict(re.findall(r"--([\w-]+): (#[0-9a-fA-F]{6});", STYLE))
        self.assertGreaterEqual(contrast(tokens["color-warning"], tokens["color-bg-alt"]), 4.5)


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground, background):
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class TestGroupList(unittest.TestCase):
    def test_the_group_list_is_read_once_with_the_selection_and_without_a_body(self):
        body = function_body("loadGroupInfo")
        self.assertIn('const res = await api("/api/groups", undefined, target);', body)
        self.assertIn("catalogueGroups = res.groups;", body)
        self.assertIn("if (catalogueGroups) return;", body)
        self.assertRegex(CODE, r"(?m)^let catalogueGroups = null;")
        self.assertEqual(len(re.findall(r'"/api/groups"', CODE)), 1)

    def test_it_is_read_before_the_table_is_built_and_read_again_only_after_a_failed_read(self):
        body = function_body("loadSettings")
        self.assertIn("await loadGroupInfo(target);", body)
        self.assertLess(body.index("await loadGroupInfo(target);"), body.index('api("/api/settings"'))
        self.assertLess(body.index("await loadGroupInfo(target);"), body.index("buildTable(list, target);"))
        self.assertEqual(CODE.count("loadGroupInfo("), 2)
        self.assertEqual(len(re.findall(r"catalogueGroups = ", CODE)), 3)
        self.assertIn("catalogueGroups = null;", function_body("loadGroupInfo")[function_body("loadGroupInfo").index("catch"):])
        self.assertNotIn("catalogueGroups", function_body("switchCar"))
        self.assertNotIn("catalogueGroups", function_body("clearTable"))

    def test_a_failed_read_is_no_error_of_the_table(self):
        body = function_body("loadGroupInfo")
        self.assertIn("} catch (e) {", body)
        self.assertNotIn("localError", body)
        self.assertNotIn("throw", body)
        self.assertEqual(function_body("loadSettings").count("localError = e.message;"), 1)
        self.assertLess(function_body("loadSettings").index("await loadGroupInfo(target);"),
                        function_body("loadSettings").index("} catch (e) {"))

    def test_the_groups_follow_the_list_of_the_server_and_unknown_groups_come_last_in_the_order_they_appeared(self):
        body = function_body("buildTable")
        self.assertIn("const listed = (catalogueGroups || []).map((x) => x.name);", body)
        self.assertIn("const rank = (g) => (listed.includes(g.name) ? listed.indexOf(g.name) : listed.length);", body)
        self.assertIn("groups.sort((a, b) => rank(a) - rank(b));", body)

    def test_each_header_is_followed_by_the_rows_of_its_group_even_when_the_settings_of_a_group_are_spread(self):
        body = function_body("buildTable")
        self.assertIn("body.append(g.tr, ...g.rows.map((r) => r.tr));", body)
        self.assertNotIn("insertBefore", body)
        self.assertNotIn("body.appendChild", body)
        self.assertIn("groups.find((g) => g.name === data.group)", body)
        self.assertLess(body.index("groups.sort("), body.index("body.append("))
        self.assertLess(body.index("body.append("), body.index("applyFilter();"))
        self.assertIn('r.tr.id = "row-" + rows.length;', body)
        self.assertIn('g.btn.setAttribute("aria-controls", g.rows.map((r) => r.tr.id).join(" "));', body)
        self.assertIn('if (data.ui === "header") {', body)

    def test_the_description_is_a_text_element_in_the_header_cell_below_the_toggle(self):
        body = function_body("buildGroup")
        self.assertIn("const known = (catalogueGroups || []).find((x) => x.name === name);", body)
        self.assertIn("if (known && known.description) {", body)
        self.assertIn('g.desc = el("div", "gdesc", known.description);', body)
        self.assertIn('g.desc.id = "gdesc-" + groups.length;', body)
        self.assertIn("g.desc.hidden = true;", body)
        self.assertIn('g.btn.setAttribute("aria-describedby", g.desc.id);', body)
        self.assertLess(body.index("th.appendChild(g.btn);"), body.index("th.appendChild(g.desc);"))
        self.assertLess(body.index("th.appendChild(g.desc);"), body.index("g.tr.appendChild(th);"))
        self.assertIn("desc: null", body)
        self.assertNotIn("innerHTML", body)
        self.assertIn('"aria-controls"', function_body("buildTable"))
        self.assertNotIn("aria-controls", body)

    def test_the_description_is_hidden_with_the_rows_by_the_open_state_of_the_group(self):
        body = function_body("applyFilter")
        self.assertIn("if (g.desc) g.desc.hidden = !open;", body)
        self.assertLess(body.index("const open = filtering ? any : expanded.has(g.name);"), body.index("g.desc.hidden = !open;"))
        for name in ("toggleGroup", "setAllGroups", "revealGroup"):
            with self.subTest(name):
                self.assertNotIn("desc", function_body(name))

    def test_the_description_style_is_muted_normal_weight_and_not_uppercase_with_a_readable_width(self):
        rule = re.search(r"\n\.gdesc \{([^}]*)\}", STYLE).group(1)
        self.assertIn("color: var(--color-text-muted);", rule)
        self.assertIn("font-weight: normal;", rule)
        self.assertIn("text-transform: none;", rule)
        self.assertIn("letter-spacing: normal;", rule)
        self.assertRegex(rule, r"max-width: \d+ch;")
        self.assertIn("gdesc", used_classes())
        self.assertIn("gdesc", css_classes())

    def test_the_muted_text_reads_on_the_group_header_background(self):
        tokens = dict(re.findall(r"(--[\w-]+): (#[0-9a-fA-F]{6});", TestDarkTheme.ROOT_RULE))
        self.assertIn("background: var(--color-bg-elevated);", re.search(r"tr\.group th \{([^}]*)\}", STYLE).group(1))
        self.assertGreaterEqual(contrast(tokens["--color-text-muted"], tokens["--color-bg-elevated"]), 4.5)


class TestBaseRangeColumn(unittest.TestCase):
    CAR_TABLE = MARKUP.split('<caption id="caption"', 1)[1].split("</table>")[0]
    TYRE_TABLE = MARKUP.split('<caption class="sr-only">Settings of the selected tyre</caption>', 1)[1].split('id="tyre-rows"')[0]

    def test_the_header_sits_between_default_and_description_in_the_car_table_only(self):
        heads = [h.replace("<br>", " ") for h in re.findall(r'<th scope="col">(.*?)</th>', self.CAR_TABLE)]
        self.assertEqual(heads, ["Variable name", "Value", "Default (for the selected car)", "Range for base cars", "Description"])
        self.assertNotIn("Range for base cars", self.TYRE_TABLE)

    def test_the_colgroup_has_the_range_column_between_default_and_description(self):
        self.assertIn('<colgroup><col class="c-name"><col class="c-value"><col class="c-default"><col class="c-range"><col class="c-desc"></colgroup>',
                      self.CAR_TABLE)
        self.assertNotIn("c-range", self.TYRE_TABLE)
        self.assertRegex(STYLE, r"col\.c-range \{ width: \d+%; \}")

    def test_the_widths_of_the_car_table_add_up_to_100_and_the_tyre_table_keeps_its_own(self):
        car = {m[0]: int(m[1]) for m in re.findall(r"(?:#panel-car )?col\.(c-(?:name|value|default|range|desc)) \{ width: (\d+)%; \}",
                                                   "\n".join(l for l in STYLE.splitlines() if l.startswith("#panel-car ") or l.startswith("col.c-range")))}
        self.assertEqual(sorted(car), ["c-default", "c-desc", "c-name", "c-range", "c-value"])
        self.assertEqual(sum(car.values()), 100)
        tyre = [int(w) for w in re.findall(r"^col\.c-(?:name|value|default|desc) \{ width: (\d+)%; \}", STYLE, re.M)]
        self.assertEqual((len(tyre), sum(tyre)), (4, 100))

    def test_the_group_rows_span_the_columns_of_their_table(self):
        self.assertIn("th.colSpan = 5;", function_body("buildGroup"))
        self.assertIn("th.colSpan = 4;", function_body("buildTyreGroup"))

    def test_the_cell_is_added_by_the_car_table_only(self):
        self.assertIn("function buildRow(data, target, withRange) {", CODE)
        body = function_body("buildRow")
        self.assertIn("r.tr.append(nameCell, valueCell, defCell);", body)
        self.assertIn("if (withRange) r.tr.appendChild(buildRangeCell(data));", body)
        self.assertLess(body.index("buildRangeCell(data)"), body.index("r.tr.appendChild(descCell);"))
        self.assertIn("buildRow(data, target, true)", function_body("buildTable"))
        self.assertIn("buildRow(item, null);", function_body("buildTyreRows"))
        self.assertEqual(len(re.findall(r"\bbuildRow\(", CODE)), 3)

    def test_the_formatter_joins_low_and_high_with_an_en_dash_and_spaces(self):
        body = function_body("buildRangeCell")
        self.assertIn("const br = data.base_range;", body)
        self.assertIn('low + " \\u2013 " + high', body)
        self.assertIn("br.low === br.high ? low :", body)
        self.assertIn("fmtVal(data.type, br.low)", body)
        self.assertIn("fmtVal(data.type, br.high)", body)
        self.assertIn('(data.unit ? " " + data.unit : "")', body)

    def test_a_row_without_a_range_and_the_non_numeric_types_show_a_muted_en_dash(self):
        body = function_body("buildRangeCell")
        self.assertIn('if (!br || (data.type !== "int" && data.type !== "float")) {', body)
        self.assertIn('el("td", "default mono", "\\u2013")', body)
        self.assertIn('none.classList.add("range-none");', body)
        self.assertIn('none.setAttribute("aria-label", "no range");', body)
        self.assertIn(".range-none { color: var(--color-text-muted); }", STYLE)

    def test_the_cell_is_plain_text_without_tooltip_or_behaviour(self):
        body = function_body("buildRangeCell")
        for word in ("title", "addEventListener", "badge", "changed", "min", "max", "aria-description"):
            with self.subTest(word):
                self.assertNotIn(word, body)
        self.assertEqual(len(re.findall(r"\bbase_range\b", CODE)), 1)

    def test_the_server_sends_the_field_the_page_reads(self):
        self.assertIn('"base_range"', inspect.getsource(ts.row_json))


class TestPolling(unittest.TestCase):
    def test_a_hidden_tab_polls_slowly_and_refreshes_at_once_when_shown(self):
        poll_hidden, poll_idle = (int(re.search(r"^const %s = (\d+);" % k, CODE, re.M).group(1)) for k in ("POLL_HIDDEN_MS", "POLL_IDLE_MS"))
        self.assertGreater(poll_hidden, poll_idle)
        handler = re.search(r'document\.addEventListener\("visibilitychange", \(\) => \{(.*?)\}\);', CODE, re.S)
        self.assertIsNotNone(handler, "no visibilitychange handler")
        self.assertRegex(handler.group(1), r"if \(!document\.hidden\) \{\s*refresh\(\);")
        self.assertRegex(handler.group(1), r'refresh\(\);\s*if \(tabs\[activeTab\] === \$\("tab-logging"\)\) pollLogStatus\(\);')

    def test_the_status_of_the_logger_is_not_polled_while_the_page_is_hidden_and_is_read_at_once_when_it_is_shown_again(self):
        body = function_body("pollLogStatus")
        self.assertTrue(body.lstrip().startswith("if (document.hidden) return;"))
        self.assertLess(body.index("if (document.hidden) return;"), body.index("++logStatusSeq"))
        self.assertEqual(re.findall(r"setInterval\(([^)]*)\)", CODE), ["pollLogStatus, LOG_POLL_MS"])
        self.assertEqual(len(re.findall(r"\bsetTimeout\(refresh,", CODE)), 1)


class TestPanelLoads(unittest.TestCase):
    def test_the_three_panels_are_read_together_after_the_job_flags_took_the_present_state(self):
        body = function_body("loadCarPanels")
        self.assertIn("const running = jobRunning();", body)
        for flag in ("garageJobRunning", "turboJobRunning", "soundsJobRunning"):
            with self.subTest(flag):
                self.assertIn("%s = running;" % flag, body)
        self.assertRegex(body, r"loadGarage\(\);\s*loadTurbo\(\);\s*loadSounds\(\);")
        self.assertLess(body.index("soundsJobRunning = running;"), body.index("loadGarage();"))
        # besides the helper only the job-end hook and the failed write read one panel alone
        self.assertEqual(len(re.findall(r"\bloadGarage\(\);", CODE)), 3)
        self.assertEqual(len(re.findall(r"\bloadTurbo\(\);", CODE)), 3)
        self.assertEqual(len(re.findall(r"\bloadSounds\(\);", CODE)), 3)

    def test_every_site_that_read_the_three_panels_calls_the_helper_and_a_donor_choice_skips_them(self):
        self.assertEqual(len(re.findall(r"\bloadCarPanels\(\);", CODE)), 4)
        self.assertEqual(re.findall(r"async function loadSettings\((.*?)\) \{", CODE), ["withPanels = true"])
        self.assertIn("if (withPanels) loadCarPanels();", function_body("loadSettings"))
        self.assertEqual(re.findall(r"\bloadSettings\(([^)]*)\)", function_body("turboChanged")), ["false"])
        self.assertEqual(re.findall(r"\bloadSettings\(([^)]*)\)", function_body("resetAll")), [""])
        self.assertEqual(re.findall(r"\bloadSettings\(([^)]*)\)", function_body("refresh")), [""])

    def test_a_job_that_is_still_running_after_the_start_waits_for_its_end_instead_of_reading_the_panels(self):
        for name in ("startJob", "submitDialog"):
            with self.subTest(name):
                self.assertIn("if (serverState && !jobRunning()) loadCarPanels();", function_body(name))
        self.assertIn('if (tabs[i] === $("tab-car")) loadCarPanels();', function_body("selectTab"))
        self.assertIn('if (tabs[i] === $("tab-tyres")) loadTyres(true);', function_body("selectTab"))


class TestJobRunning(unittest.TestCase):
    # page part: no edits while a job runs, the server answers them with 409 anyway
    def test_the_value_fields_and_reset_buttons_are_disabled_while_a_job_runs(self):
        body = function_body("renderButtons")
        self.assertIn("const running = jobRunning();", body)
        self.assertIn("r.field.disabled = running;", body)
        self.assertIn("r.reset.disabled = running;", body)
        self.assertIn('$("btn-reset-all").disabled = running;', body)

    def test_one_helper_says_whether_a_job_runs_and_one_says_why_the_car_panels_are_locked(self):
        self.assertIn('return !!serverState && serverState.job.state === "running";', function_body("jobRunning"))
        others = CODE.replace('serverState.job.kind === "init" && serverState.job.state === "running"', "")
        self.assertEqual(len(re.findall(r'serverState\.job\.state === "running"', others)), 1)
        body = function_body("panelLockReason")
        self.assertIn('if (!serverState) return serverError || "server not reachable";', body)
        self.assertIn('if (jobRunning()) return "a job is running";', body)
        self.assertIn('if (!serverState.base_present) return "extract the stock car first";', body)
        self.assertIn('return "";', body)
        self.assertLess(body.index("server not reachable"), body.index("a job is running"))
        self.assertLess(body.index("a job is running"), body.index("extract the stock car first"))
        for name in ("lockGarage", "lockTurbo", "lockSounds"):
            with self.subTest(name):
                self.assertRegex(function_body(name), r"(?:let|const) why = panelLockReason\(\);")
                self.assertNotIn("extract the stock car first", function_body(name))

    def test_the_header_row_is_disabled_with_the_table_rows(self):
        self.assertIn("headerRow ? rows.concat(headerRow) : rows", function_body("renderButtons"))

    def test_a_refused_edit_shows_the_server_message_in_the_row(self):
        self.assertIn("setMsg(r, e.message, \"err\")", function_body("sendSet"))
        self.assertIn("setMsg(r, e.message, \"err\")", function_body("sendUnset"))

    def test_the_progress_panel_warns_not_to_close_the_console_while_a_job_runs(self):
        body = function_body("renderProgress")
        note = body.index("Do not close the console window while this runs.")
        self.assertLess(body.index('job.state === "running"'), note)
        self.assertLess(note, body.index('job.state === "done"'))


class TestFullWidth(unittest.TestCase):
    PAGE_RULE = re.search(r"\n\.page \{([^}]*)\}", STYLE).group(1)

    def test_the_page_container_has_no_fixed_maximum_width(self):
        self.assertNotIn("1280", STYLE)
        self.assertNotIn("max-width", self.PAGE_RULE)
        self.assertIn("padding: 0 20px 40px;", self.PAGE_RULE)

    def test_no_media_rule_caps_the_page_width_either(self):
        for rule in re.findall(r"\.page \{([^}]*)\}", STYLE):
            with self.subTest(rule):
                self.assertNotIn("max-width", rule)
                self.assertNotRegex(rule, r"(?<![\w-])width:")

    def test_on_a_phone_the_value_fields_shrink_to_their_cell_and_a_checkbox_keeps_its_size(self):
        phone = re.search(r"@media \(max-width: 1000px\) \{(.*?)\n\}", STYLE, re.S).group(1)
        self.assertIn("\n  .valuewrap input, .valuewrap select { max-width: 100%; min-width: 0; }", phone)
        self.assertIn('\n  .valuewrap input[type="checkbox"] { max-width: none; }', phone)
        self.assertNotRegex(STYLE.replace(phone, ""), r"\.valuewrap[^{}]*\{[^}]*min-width")

    def test_the_readable_width_of_the_descriptions_stays(self):
        self.assertRegex(re.search(r"\n\.gdesc \{([^}]*)\}", STYLE).group(1), r"max-width: 80ch;")


class TestRunningTitle(unittest.TestCase):
    RULE = re.search(r"\n\.panel h2\.running \{([^}]*)\}", STYLE).group(1)

    def test_the_running_heading_carries_the_class_and_the_rule_uses_the_accent(self):
        self.assertEqual(self.RULE.strip(), "color: var(--color-accent);")
        self.assertIn('box.appendChild(el("h2", "running", title + ": running ..."));', function_body("renderProgress"))
        self.assertIn("running", used_classes())
        self.assertIn("running", css_classes())

    def test_only_the_running_heading_has_the_class(self):
        headings = re.findall(r'el\("h2", "([^"]*)", ([^;]*)\);', function_body("renderProgress"))
        self.assertEqual(len(headings), 5, headings)
        for cls, text in headings:
            with self.subTest(text):
                self.assertEqual(cls, "running" if "running" in text else "")
        self.assertIn('title + ": finished"', [t for _, t in headings if "finished" in t][0])
        self.assertIn('title + ": failed"', [t for _, t in headings if "failed" in t][0])

    def test_the_finished_and_error_panels_keep_their_colours(self):
        self.assertIn(".panel.ok { background: var(--color-ok-tint); color: var(--color-ok); border-color: var(--color-ok); }", STYLE)
        self.assertIn(".panel.err { background: var(--color-error-tint); color: var(--color-error); border-color: var(--color-error); }", STYLE)
        self.assertNotRegex(STYLE, r"\.panel\.(?:ok|err) h2")

    def test_the_accent_reads_on_the_panel_background(self):
        tokens = dict(re.findall(r"(--[\w-]+): (#[0-9a-fA-F]{6});", TestDarkTheme.ROOT_RULE))
        self.assertIn("background: var(--color-bg-alt);", re.search(r"\n\.panel \{([^}]*)\}", STYLE).group(1))
        self.assertGreaterEqual(contrast(tokens["--color-accent"], tokens["--color-bg-alt"]), 4.5)
        self.assertGreaterEqual(contrast(tokens["--color-text"], tokens["--color-bg-alt"]), 4.5)


class TestInstallCars(unittest.TestCase):
    def test_the_init_panel_says_install_not_extract(self):
        panel = re.search(r'<section id="init-panel".*?</section>', MARKUP, re.S).group(0)
        self.assertIn("<h2>Car not installed yet</h2>", panel)
        self.assertIn("The tuner needs the car's files from the game as its starting point. Installing pulls them once (about 20 seconds).", panel)
        self.assertIn('<button id="btn-init" class="primary" type="button">Install car (pull game files)</button>', panel)
        self.assertEqual(HTML.count("Installing pulls them once"), 1)
        for old in ("Extract stock car", "not extracted yet", "stock car from the game files"):
            with self.subTest(old):
                self.assertNotIn(old, HTML)

    def test_the_install_button_starts_the_init_job(self):
        self.assertIn('$("btn-init").addEventListener("click", () => startJob("/api/init", {}));', CODE)

    def test_the_page_has_no_install_all_tested_cars_button_or_job(self):
        self.assertNotIn("btn-install-tested", HTML)
        self.assertNotIn("install_tested", HTML)

    def test_the_progress_panel_names_the_install_job(self):
        body = function_body("renderProgress")
        self.assertIn('job.kind === "init" ? "Install car" : "Apply"', body)
        self.assertIn('if (job.kind === "init") addLine(box, "The car is installed, the table is available.");', body)
        self.assertNotIn("Extract stock car", body)

    def test_the_table_is_not_loaded_while_the_install_job_runs(self):
        body = function_body("refresh")
        self.assertIn('const extracting = !!serverState && serverState.job.kind === "init" && serverState.job.state === "running";', body)
        self.assertIn("!tableLoaded && !extracting", body)

    def test_every_job_kind_the_progress_panel_knows_is_started_by_the_server(self):
        kinds = set(re.findall(r'job\.kind === "(\w+)"', function_body("renderProgress")))
        self.assertEqual(kinds, {"apply", "init"})
        self.assertEqual(kinds - set(re.findall(r'(?:run_job|claim_job)\("(\w+)"', inspect.getsource(ts))), set())


class TestProgressDetails(unittest.TestCase):
    def test_the_changes_since_the_last_build_are_an_open_details_with_the_count_in_the_summary(self):
        body = function_body("summaryApply")
        fresh = body[:body.index('addLine(box, "Package: "')]
        self.assertIn("if (res.changes) {", fresh)
        self.assertIn("const count = ch.settings.length + ch.extras.length;", fresh)
        self.assertIn('const details = el("details");', fresh)
        self.assertIn("details.open = true;", fresh)
        self.assertIn('el("summary", "", "Changes (" + count + ")")', fresh)
        self.assertIn("details.appendChild(ul);", fresh)
        self.assertIn("box.appendChild(details);", fresh)
        self.assertNotIn("Settings applied", fresh)

    def test_the_changes_list_has_one_item_per_setting_then_one_per_extra(self):
        fresh = function_body("summaryApply")
        fresh = fresh[:fresh.index('addLine(box, "Package: "')]
        setting = 'ul.appendChild(el("li", "", c.id + ": " + fmtVal("", c.from) + " -> " + fmtVal("", c.to)));'
        extra = 'for (const e of ch.extras) ul.appendChild(el("li", "", e.text));'
        self.assertIn("for (const c of ch.settings) {", fresh)
        self.assertIn(setting, fresh)
        self.assertIn(extra, fresh)
        self.assertLess(fresh.index(setting), fresh.index(extra))
        self.assertLess(fresh.index('el("summary"'), fresh.index('const ul = el("ul");'))
        self.assertLess(fresh.index("details.appendChild(ul);"), fresh.index("box.appendChild(details);"))

    def test_the_heading_line_tells_the_first_build_the_changes_or_no_change(self):
        fresh = function_body("summaryApply")
        fresh = fresh[:fresh.index('addLine(box, "Package: "')]
        self.assertIn("if (ch.since === null) {", fresh)
        self.assertIn('addLine(box, "First build of this car: " + ch.total + (ch.total === 1 ? " changed setting" : " changed settings") +', fresh)
        self.assertIn('" compared to the stock car.");', fresh)
        self.assertIn('addLine(box, count + (count === 1 ? " change" : " changes") + " since the last build.");', fresh)
        self.assertIn('addLine(box, "No change since the last build.");', fresh)
        self.assertLess(fresh.index("First build of this car"), fresh.index("since the last build."))
        self.assertLess(fresh.index("since the last build."), fresh.index("No change since the last build."))
        self.assertNotIn("No setting was changed", HTML)
        self.assertNotIn("the stock values were built", HTML)

    def test_the_closing_lines_stay_outside_the_changes_details(self):
        body = function_body("summaryApply")
        end = body.rindex("box.appendChild(details);")
        self.assertLess(end, body.index('addLine(box, "Package: "'))
        for line in ('"Installed to: "', '"Backup of the previous install: "', "Close the game before applying again."):
            with self.subTest(line):
                self.assertLess(end, body.index(line))

    def test_a_finished_job_wraps_the_build_log_in_a_collapsed_details(self):
        body = function_body("renderProgress")
        log = body[body.index("if (job.log.length) {"):]
        done = log[log.index('if (job.state === "done") {'):log.index("} else {")]
        self.assertIn('const details = el("details");', done)
        self.assertIn('el("summary", "", "Build log")', done)
        self.assertIn("details.appendChild(pre);", done)
        self.assertIn("box.appendChild(details);", done)
        self.assertNotRegex(done, r"\bopen\b")

    def test_a_running_or_failed_job_keeps_the_log_visible_and_scrolled_to_the_end(self):
        body = function_body("renderProgress")
        log = body[body.index("if (job.log.length) {"):]
        visible = log[log.index("} else {"):]
        self.assertIn("box.appendChild(pre);", visible)
        self.assertIn("pre.scrollTop = pre.scrollHeight;", visible)
        self.assertNotIn("details", visible)

    def test_the_details_are_native_and_styled_in_the_panel_without_a_new_class(self):
        self.assertIn(".panel summary { cursor: pointer; }", STYLE)
        self.assertIn(".panel summary:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 1px; }", STYLE)
        for name in ("summaryApply", "renderProgress"):
            self.assertNotIn("addEventListener", function_body(name))

    def test_the_panel_is_rebuilt_only_when_the_job_or_the_errors_change_so_an_opened_details_stays_open(self):
        self.assertEqual(re.findall(r"\brenderProgress\(\)", CODE), ["renderProgress()", "renderProgress()"])
        self.assertEqual(len(re.findall(r"\bjobSig = ", CODE)), 2)
        self.assertIn("jobSig = sig;", function_body("renderProgress"))
        self.assertEqual(re.findall(r"\brenderProgress\(\);", function_body("refresh")), ["renderProgress();"])


class TestErrorHandling(unittest.TestCase):
    def test_a_failed_job_start_or_reset_shows_the_error(self):
        self.assertIn("localError = e.message;", function_body("startJob"))
        self.assertIn("localError = e.message;", function_body("resetAll"))
        self.assertIn("localError = e.message;", function_body("loadSettings"))

    def test_a_new_job_and_a_car_switch_clear_the_old_error(self):
        self.assertIn('localError = "";', function_body("startJob"))
        self.assertIn('localError = "";', function_body("switchCar"))

    def test_a_successful_settings_load_clears_the_old_error(self):
        body = function_body("loadSettings")
        success = body.index("tableLoaded = true;")
        self.assertIn('localError = "";', body[success:])

    def test_a_failing_api_call_becomes_an_error_with_the_server_text(self):
        body = function_body("api")
        self.assertIn('throw new Error("server not reachable")', body)
        self.assertIn("data.error", body)
        self.assertIn('"HTTP " + res.status', body)


class TestModdedCars(unittest.TestCase):
    def test_the_selector_has_the_three_groups_in_order(self):
        labels = re.findall(r'\["((?:Installed|Other|Modded) Cars)", ', function_body("renderCars"))
        self.assertEqual(labels, ["Modded Cars", "Installed Cars", "Other Cars"])
        self.assertIn('<select id="car-select" aria-label="Car"', MARKUP)
        self.assertEqual(MARKUP.count("<optgroup"), 0)

    def test_the_modded_cars_are_on_top_of_the_base_cars(self):
        body = function_body("renderCars")
        self.assertLess(body.index('["Modded Cars", '), body.index('["Installed Cars", '))
        self.assertLess(body.index('["Installed Cars", '), body.index('["Other Cars", '))

    def test_the_default_selection_does_not_depend_on_the_order_of_the_groups(self):
        body = function_body("renderCars")
        self.assertIn("select.value = choiceValue(selection);", body)
        self.assertNotIn("selectedIndex", body)
        self.assertNotIn("firstChild", body)
        self.assertNotIn("options[0]", body)
        self.assertIn("selection = { car: serverState.car, tune: serverState.tune };", function_body("refresh"))

    def test_the_installed_group_holds_the_extracted_cars_and_the_other_group_the_rest(self):
        body = function_body("renderCars")
        self.assertIn('["Installed Cars", list.filter((c) => c.extracted).sort(byName)', body)
        self.assertIn('["Other Cars", list.filter((c) => !c.extracted).sort(byName)', body)
        self.assertNotIn("c.tested", body)
        self.assertNotIn("Base Cars", HTML)

    def test_an_option_is_the_name_of_the_car_without_flags(self):
        self.assertEqual(function_body("optionText").strip(), "return c.display_name || c.label;")
        for old in ("not extracted", "(installed", "flags", '" ("'):
            with self.subTest(old):
                self.assertNotIn(old, function_body("optionText"))
                self.assertNotIn(old, function_body("renderCars"))

    def test_the_note_for_untested_cars_stays(self):
        body = function_body("renderCars")
        self.assertIn('$("untested").hidden = !entry || entry.tested;', body)
        self.assertIn("This car has not been tested with the tuner yet; check the results before you trust them.", body)

    def test_the_option_values_encode_the_target(self):
        body = function_body("renderCars")
        self.assertEqual(re.findall(r'\["(base|mod):" \+ (\w)\.id, ', body), [("mod", "m"), ("base", "c"), ("base", "c")])
        self.assertIn("o.value = value;", body)
        self.assertIn('startsWith("base:")', function_body("choiceOf"))
        self.assertIn('startsWith("mod:")', function_body("choiceOf"))
        self.assertIn("{ car: value.slice(5), tune: DRAFT }", function_body("choiceOf"))
        self.assertIn("{ car: m.stock, tune: m.id }", function_body("choiceOf"))

    def test_a_modded_option_says_whether_the_car_is_installed(self):
        body = function_body("renderCars")
        self.assertIn('m.label + (m.installed ? " - installed" : " - not installed")', body)

    def test_the_modded_group_is_absent_while_the_list_is_empty(self):
        body = function_body("renderCars")
        self.assertIn("moddedList().map(", body)
        self.assertIn("if (!options.length) continue;", body)
        self.assertIn("serverState && serverState.modded ? serverState.modded : []", function_body("moddedList"))

    def test_the_selection_survives_a_poll_and_is_part_of_the_selector_signature(self):
        body = function_body("renderCars")
        self.assertIn("JSON.stringify([optionGroups, selection])", body)
        self.assertIn("select.value = choiceValue(selection);", body)
        self.assertIn("selection = { car: serverState.car, tune: serverState.tune };", function_body("refresh"))

    def test_the_selection_is_one_object_with_car_and_tune(self):
        self.assertRegex(CODE, r"(?m)^let selection = storedSelection\(\);")
        self.assertNotRegex(CODE, r"\bcarId\b")
        self.assertIn("{ car: null, tune: DRAFT }", CODE)
        self.assertIn('const DRAFT = "draft";', CODE)
        for name in ("sendSet", "sendUnset"):
            self.assertIn("r.target)", function_body(name))
        self.assertIn("target.tune === DRAFT", function_body("buildHeaderRow"))

    def test_a_damaged_modded_state_is_shown_in_the_message_area(self):
        body = function_body("renderProgress")
        self.assertIn("serverState.modded_error", body)
        self.assertIn("errors.push(", body)
        self.assertIn("for (const text of errors) addLine(box, text);", body)
        self.assertIn("JSON.stringify([job, errors])", body)

    def test_the_header_line_names_the_kind_of_car(self):
        body = function_body("buildHeaderRow")
        self.assertIn('"Base car: Apply creates a new modded car"', body)
        self.assertIn('"Modded car " + target.tune + " of " + carName()', body)
        self.assertIn('el("span", "tunenote"', body)

    def test_the_buttons_follow_the_kind_of_car(self):
        self.assertIn('<button id="btn-apply" class="primary" type="button" disabled>Create modded car&hellip;</button>', MARKUP)
        self.assertIn('<button id="btn-duplicate" type="button" disabled>Duplicate&hellip;</button>', MARKUP)
        body = function_body("renderButtons")
        self.assertIn('draft ? "Create modded car\\u2026" : "Apply (update this car)"', body)
        self.assertIn('$("btn-duplicate").disabled = whyDuplicate !== "";', body)
        self.assertIn('whyDuplicate = "select a modded car to duplicate it"', body)
        self.assertIn('whyDuplicate = serverState.base_present ? "" : "extract the stock car first"', body)

    def test_the_old_copy_flow_is_gone(self):
        for old in ("btn-copy", "askNewCopy", "Save as new copy", "new_copy", "window.prompt", "Apply (update my car)"):
            with self.subTest(old):
                self.assertNotIn(old, HTML)

    def test_the_dialog_is_an_inline_panel_with_two_labelled_inputs(self):
        panel = re.search(r'<section id="dialog".*?</section>', MARKUP, re.S).group(0)
        self.assertIn("hidden>", panel.split("\n")[0])
        self.assertIn('aria-labelledby="dialog-title"', panel)
        for field in ("dialog-id", "dialog-suffix"):
            with self.subTest(field):
                self.assertRegex(panel, r'<label for="%s">[^<]+</label>\s*<input id="%s"[^>]*type="text"' % (field, field))
        for button in ("dialog-ok", "dialog-cancel"):
            self.assertRegex(panel, r'<button id="%s"[^>]*type="button">' % button)
        self.assertIn(">OK</button>", panel)
        self.assertIn(">Cancel</button>", panel)
        self.assertNotIn("window.prompt", CODE)
        self.assertNotIn("window.alert", CODE)

    def test_the_dialog_is_prefilled_from_the_proposals_of_the_server(self):
        body = function_body("openDialog")
        self.assertIn('$("dialog-id").value = serverState.proposed_new_id || "";', body)
        self.assertIn('create ? serverState.proposed_suffix || "" : ""', body)
        self.assertIn('create ? "" : "automatic"', body)

    def test_enter_confirms_and_escape_cancels_the_dialog(self):
        body = function_body("dialogKey")
        self.assertIn('ev.key === "Escape"', body)
        self.assertIn("closeDialog(true)", body)
        self.assertIn('ev.key === "Enter" && ev.target.tagName === "INPUT"', body)
        self.assertIn("submitDialog()", body)
        self.assertIn('$("dialog").addEventListener("keydown", dialogKey);', CODE)

    def test_the_focus_moves_into_the_panel_and_back(self):
        self.assertIn('$("dialog-id").focus();', function_body("openDialog"))
        self.assertIn("opener", function_body("openDialog"))
        body = function_body("closeDialog")
        self.assertIn("if (restoreFocus) {", body)
        self.assertIn("back.focus();", body)

    def test_a_server_error_stays_inside_the_open_panel(self):
        body = function_body("submitDialog")
        failure = body[body.index("} catch (e) {"):]
        self.assertIn("showDialogError(e.message);", failure)
        self.assertNotIn("closeDialog", failure)
        self.assertIn("mine.busy = false;", failure)
        self.assertIn('showText("dialog-error", text);', function_body("showDialogError"))

    def test_create_selects_the_new_car_when_the_job_has_created_it(self):
        body = function_body("submitDialog")
        self.assertIn("awaitCreated = { car: target.car, known: known };", body)
        self.assertIn("job.result.created", function_body("createdCar"))
        self.assertIn("{ car: awaitCreated.car, tune: job.result.new_id }", function_body("createdCar"))
        self.assertIn("if (createdCar()) return;", function_body("refresh"))

    def test_duplicate_selects_the_new_car_at_once(self):
        self.assertIn("switchCar({ car: res.stock, tune: res.id });", function_body("submitDialog"))

    def test_a_switch_closes_the_panel_and_reloads_the_table(self):
        body = function_body("switchCar")
        for part in ("storeSelection(next);", "closeDialog(false);", "tableLoaded = false;", "clearTable();", "refresh();"):
            self.assertIn(part, body)
        self.assertIn("sameSelection(next, selection)", body)

    def test_the_new_buttons_and_inputs_are_disabled_while_a_job_runs(self):
        body = function_body("renderButtons")
        self.assertIn('const locked = running || (dialog !== null && dialog.busy);', body)
        self.assertIn('for (const id of ["dialog-id", "dialog-suffix", "dialog-ok"]) $(id).disabled = locked;', body)
        self.assertIn('$("btn-duplicate").disabled = whyDuplicate !== "";', body)
        self.assertIn('if (why === "close the game first")', body)
        self.assertIn("whyDuplicate = why;", body)


class TestTabs(unittest.TestCase):
    CAR_PANEL = MARKUP[MARKUP.index('id="panel-car"'):MARKUP.index('id="panel-tyres"')]
    TYRES_PANEL = MARKUP[MARKUP.index('id="panel-tyres"'):MARKUP.index('id="panel-logging"')]
    TAB_RULE = re.search(r'button\[role="tab"\] \{(.*?)\}', STYLE, re.S).group(1)

    @staticmethod
    def tag(ident):
        return re.search(r'<[a-z]+\b[^>]*\bid="%s"[^>]*>' % ident, MARKUP).group(0)

    def test_the_tabs_are_a_tablist_of_three_buttons_with_the_three_labels(self):
        self.assertEqual(re.findall(r'<div role="tablist" aria-label="Pages">', MARKUP), ['<div role="tablist" aria-label="Pages">'])
        strip = re.search(r'<div role="tablist".*?</div>', MARKUP, re.S).group(0)
        tabs = re.findall(r'<button\b[^>]*>.*?</button>', strip, re.S)
        self.assertEqual(len(tabs), 3)
        for tab, ident, label in zip(tabs, ("tab-car", "tab-tyres", "tab-logging"), ("Car Tuner", "Tyre Creator", "Logging")):
            with self.subTest(ident):
                self.assertIn('id="%s"' % ident, tab)
                self.assertIn('role="tab"', tab)
                self.assertIn('type="button"', tab)
                self.assertTrue(tab.endswith(">%s</button>" % label), tab)
        self.assertEqual(MARKUP.count('role="tab"'), 3)

    def test_the_three_panels_are_tabpanels_labelled_by_their_tabs(self):
        self.assertEqual(MARKUP.count('role="tabpanel"'), 3)
        for tab, panel in (("tab-car", "panel-car"), ("tab-tyres", "panel-tyres"), ("tab-logging", "panel-logging")):
            with self.subTest(tab):
                self.assertIn('aria-controls="%s"' % panel, self.tag(tab))
                self.assertIn('role="tabpanel"', self.tag(panel))
                self.assertIn('aria-labelledby="%s"' % tab, self.tag(panel))

    def test_every_aria_controls_and_labelledby_of_the_tabs_names_an_existing_id(self):
        ids = set(dom_ids())
        for ident in ("tab-car", "tab-tyres", "tab-logging", "panel-car", "panel-tyres", "panel-logging"):
            with self.subTest(ident):
                tag = self.tag(ident)
                for target in re.findall(r'aria-(?:controls|labelledby)="([^"]+)"', tag):
                    self.assertIn(target, ids)

    def test_the_car_tuner_is_selected_on_load_with_a_roving_tabindex(self):
        self.assertIn('aria-selected="true"', self.tag("tab-car"))
        self.assertIn('tabindex="0"', self.tag("tab-car"))
        self.assertIn('aria-selected="false"', self.tag("tab-tyres"))
        self.assertIn('tabindex="-1"', self.tag("tab-tyres"))
        self.assertIn('aria-selected="false"', self.tag("tab-logging"))
        self.assertIn('tabindex="-1"', self.tag("tab-logging"))
        self.assertEqual(MARKUP.count('aria-selected="true"'), 1)

    def test_the_inactive_panels_are_hidden_and_the_active_one_is_not(self):
        self.assertNotRegex(self.tag("panel-car"), r"\bhidden\b")
        self.assertRegex(self.tag("panel-tyres"), r"\bhidden>$")
        self.assertRegex(self.tag("panel-logging"), r"\bhidden>$")

    def test_the_car_tuner_elements_are_inside_the_car_panel(self):
        for ident in ("car-select", "btn-apply", "btn-duplicate", "dialog", "name-host", "untested", "status",
                      "progress", "init-panel", "tuner", "search", "rows"):
            with self.subTest(ident):
                self.assertIn('id="%s"' % ident, self.CAR_PANEL)
                self.assertNotIn('id="%s"' % ident, self.TYRES_PANEL)

    def test_the_tyre_panel_keeps_its_heading_and_its_first_paragraph(self):
        self.assertIn("<h2>Tyre Creator</h2>", self.TYRES_PANEL)
        self.assertEqual(re.findall(r"<p\b[^>]*>(.*?)</p>", self.TYRES_PANEL)[0],
                         "Tyres you create here are saved once and can be ticked in the garage list of any modded car in the Car Tuner tab.")
        self.assertTrue(self.TYRES_PANEL.split("<section", 1)[1].startswith(' class="panel">\n      <h2>Tyre Creator</h2>'))

    def test_the_header_holds_the_title_only_and_the_tab_strip_follows_it(self):
        header = re.search(r'<header class="bar">.*?</header>', MARKUP, re.S).group(0)
        self.assertEqual(re.findall(r"<[a-z0-9]+", header), ["<header", "<h1"])
        self.assertLess(MARKUP.index("</header>"), MARKUP.index('role="tablist"'))
        self.assertLess(MARKUP.index('role="tablist"'), MARKUP.index('id="panel-car"'))
        self.assertLess(MARKUP.index('id="panel-car"'), MARKUP.index('id="panel-tyres"'))
        self.assertLess(MARKUP.index('id="panel-tyres"'), MARKUP.index('id="panel-logging"'))

    def test_the_script_selects_a_tab_by_flipping_aria_selected_tabindex_and_hidden_without_removing_anything(self):
        body = function_body("selectTab")
        self.assertIn('tab.setAttribute("aria-selected", k === i ? "true" : "false");', body)
        self.assertIn("tab.tabIndex = k === i ? 0 : -1;", body)
        self.assertIn("panels[k].hidden = k !== i;", body)
        self.assertIn("activeTab = i;", body)
        for sink in ("remove", "replaceChildren", "localStorage", "aria-live", "role"):
            self.assertNotIn(sink, body)
        self.assertRegex(CODE, r'(?m)^const tabs = \[\$\("tab-car"\), \$\("tab-tyres"\), \$\("tab-logging"\)\];')
        self.assertRegex(CODE, r'(?m)^const panels = \[\$\("panel-car"\), \$\("panel-tyres"\), \$\("panel-logging"\)\];')
        self.assertRegex(CODE, r"(?m)^let activeTab = 0;")

    def test_the_script_handles_click_and_the_four_keys_with_wrap_around_and_moves_the_focus(self):
        self.assertIn('tab.addEventListener("click", () => selectTab(i));', CODE)
        self.assertIn('tab.addEventListener("keydown", tabKey);', CODE)
        body = function_body("tabKey")
        self.assertIn('ev.key === "ArrowRight") next = (activeTab + 1) % tabs.length;', body)
        self.assertIn('ev.key === "ArrowLeft") next = (activeTab + tabs.length - 1) % tabs.length;', body)
        self.assertIn('ev.key === "Home") next = 0;', body)
        self.assertIn('ev.key === "End") next = tabs.length - 1;', body)
        self.assertIn("selectTab(next);", body)
        self.assertIn("tabs[next].focus();", body)
        self.assertIn("ev.preventDefault();", body)
        self.assertIn("if (ev.altKey || ev.ctrlKey || ev.metaKey) return;", body)

    def test_the_active_tab_lives_in_a_variable_only_and_changes_nothing_of_the_car_tuner(self):
        self.assertEqual(CODE.count("localStorage"), 2)
        self.assertNotIn("activeTab", function_body("storeSelection") + function_body("storedSelection"))
        for name in ("refresh", "switchCar", "applyFilter", "renderButtons", "toggleGroup", "closeDialog", "openDialog"):
            with self.subTest(name):
                self.assertNotIn("activeTab", function_body(name))
        self.assertNotRegex(function_body("tabKey") + function_body("selectTab"), r"aria-live|setAttribute\(\"role\"")

    def test_the_selected_tab_is_styled_by_aria_selected_not_by_a_class(self):
        self.assertIn('button[role="tab"][aria-selected="true"] { border-bottom-color: var(--color-accent); color: var(--color-text); }', STYLE)
        self.assertNotRegex(STYLE, r"\.(?:selected|active|current)\b")
        self.assertNotRegex(CODE, r'classList\.[a-z]+\("(?:selected|active|current)"')
        self.assertNotIn("className", function_body("selectTab"))

    def test_the_tab_style_is_muted_on_the_page_background_with_a_hover_text_and_a_comfortable_height(self):
        self.assertIn("background: transparent; color: var(--color-text-muted);", self.TAB_RULE)
        self.assertRegex(self.TAB_RULE, r"min-height: (?:4\d|[5-9]\d)px;")
        self.assertIn('button[role="tab"]:hover { border-bottom-color: transparent; color: var(--color-text); }', STYLE)
        self.assertIn("border-bottom: 1px solid var(--color-border);", re.search(r'\[role="tablist"\] \{(.*?)\}', STYLE).group(0))
        self.assertIn("border-bottom-width: 2px;", self.TAB_RULE)

    def test_the_tabs_keep_the_focus_ring_and_add_no_animation(self):
        self.assertNotRegex(STYLE, r"outline:\s*(?:none|0)")
        self.assertNotIn("transition", self.TAB_RULE)
        self.assertNotIn("animation", STYLE)

    def test_the_tab_rules_come_after_the_general_button_rules_so_that_they_win_the_hover_tie(self):
        self.assertLess(STYLE.index("button:hover:not(:disabled)"), STYLE.index('button[role="tab"]:hover'))
        self.assertLess(STYLE.index('button[role="tab"]:hover'), STYLE.index('button[role="tab"][aria-selected="true"]'))


class TestTyreCreator(unittest.TestCase):
    PANEL = MARKUP[MARKUP.index('id="panel-tyres"'):MARKUP.index('id="panel-logging"')]

    @staticmethod
    def tag(ident):
        return re.search(r'<[a-z]+\b[^>]*\bid="%s"[^>]*>' % ident, MARKUP).group(0)

    def test_the_toolbar_has_the_selector_and_the_three_buttons(self):
        bar = re.search(r'<div class="toolbar">.*?</div>', self.PANEL, re.S).group(0)
        self.assertIn('<select id="tyre-select" aria-label="Tyre"', bar)
        self.assertIn('<button id="btn-tyre-new" class="primary" type="button" disabled>New tyre&hellip;</button>', bar)
        self.assertIn('<button id="btn-tyre-rename" type="button" disabled>Rename&hellip;</button>', bar)
        self.assertIn('<button id="btn-tyre-delete" type="button" disabled>Delete</button>', bar)
        self.assertLess(bar.index("tyre-select"), bar.index("btn-tyre-new"))
        self.assertLess(bar.index("btn-tyre-new"), bar.index("btn-tyre-rename"))
        self.assertLess(bar.index("btn-tyre-rename"), bar.index("btn-tyre-delete"))

    def test_the_dialog_is_a_hidden_labelled_group_with_a_name_a_source_an_alert_and_two_buttons(self):
        panel = re.search(r'<section id="tyre-dialog".*?</section>', self.PANEL, re.S).group(0)
        first = panel.split("\n")[0]
        for part in ('class="panel dialog"', 'role="group"', 'aria-labelledby="tyre-dialog-title"'):
            self.assertIn(part, first)
        self.assertTrue(first.endswith("hidden>"), first)
        self.assertIn('<h2 id="tyre-dialog-title"></h2>', panel)
        self.assertRegex(panel, r'<label for="tyre-dialog-name">Name</label>\s*<input id="tyre-dialog-name"[^>]*type="text"')
        self.assertRegex(panel, r'<label for="tyre-dialog-source">Source tyre \(from your installed cars\)</label>\s*<select id="tyre-dialog-source">')
        self.assertIn('<p id="tyre-dialog-error" class="msg err" role="alert" hidden></p>', panel)
        self.assertIn('<button id="tyre-dialog-ok" class="primary" type="button">OK</button>', panel)
        self.assertIn('<button id="tyre-dialog-cancel" type="button">Cancel</button>', panel)
        self.assertIn('<p id="tyre-dialog-text" hidden></p>', panel)

    def test_the_editor_is_hidden_until_a_tyre_is_selected_and_has_the_source_the_reset_button_and_its_own_table(self):
        self.assertRegex(self.tag("tyre-editor"), r"\bhidden>$")
        editor = re.search(r'<section id="tyre-editor".*?</section>', self.PANEL, re.S).group(0)
        self.assertRegex(editor, r'<label class="selectrow">Source:\s*<select id="tyre-source" aria-label="Source tyre"></select>')
        self.assertIn('<button id="btn-tyre-reset" type="button">Reset all values</button>', editor)
        self.assertIn('<tbody id="tyre-rows"></tbody>', editor)
        self.assertIn('<caption class="sr-only">Settings of the selected tyre</caption>', editor)
        self.assertEqual([h.replace("<br>", " ") for h in re.findall(r'<th scope="col">(.*?)</th>', editor)],
                         ["Variable name", "Value", "Default (source tyre)", "Description"])
        self.assertNotIn('id="rows"', self.PANEL)

    def test_the_error_line_is_a_visible_alert_of_the_panel_outside_the_dialog(self):
        self.assertIn('<p id="tyre-error" class="msg err" role="alert" hidden></p>', self.PANEL)
        self.assertLess(self.PANEL.index('id="tyre-dialog"'), self.PANEL.index('id="tyre-error"'))
        body = function_body("renderTyres")
        self.assertIn('showText("tyre-error", tyreError);', body)
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)

    def test_every_tyre_route_is_called_with_the_fields_of_the_server(self):
        calls = {
            "/api/tyre_new": r'api\("/api/tyre_new", \{ name: name, source: source \}, selection\)',
            "/api/tyre_rename": r'api\("/api/tyre_rename", \{ id: mine\.id, name: name \}, selection\)',
            "/api/tyre_source": r'writeTyre\("/api/tyre_source", \{ id: entry\.id, source: key \}\)',
            "/api/tyre_set": r'api\("/api/tyre_set", \{ id: r\.tyre, setting: r\.data\.id, value: text \}, selection\)',
            "/api/tyre_unset": r'api\("/api/tyre_unset", \{ id: r\.tyre, setting: r\.data\.id \}, selection\)',
            "/api/tyre_reset": r'writeTyre\("/api/tyre_reset", \{ id: entry\.id \}\)',
            "/api/tyre_delete": r'api\("/api/tyre_delete", \{ id: mine\.id \}, selection\)',
        }
        for route, call in calls.items():
            with self.subTest(route):
                self.assertIn(route, ts.POST_ROUTES)
                self.assertEqual(len(re.findall(call, CODE)), 1)
                fields = set(re.findall(r'\b(\w+):', re.search(r'(?:api|writeTyre)\("%s", (\{[^}]*\})' % route, CODE).group(1)))
                handler = inspect.getsource(ts.POST_ROUTES[route])
                self.assertEqual(fields, set(re.findall(r'body\.get\("(\w+)"\)', handler)))
        self.assertEqual(len(re.findall(r'api\("/api/tyres", undefined, selection\)', CODE)), 1)
        self.assertEqual(len(re.findall(r'api\("/api/tyre\?id=" \+ encodeURIComponent\(id\), undefined, selection\)', CODE)), 1)
        self.assertEqual(ts.QUERY_ROUTES, ("/api/tyre", "/api/log_file"))
        self.assertIn("(path.includes(\"?\") ? \"&\" : \"?\")", function_body("api"))

    def test_the_selected_tyre_is_remembered_in_a_variable_and_falls_back_to_the_first_valid_one(self):
        self.assertRegex(CODE, r"(?m)^let tyreId = null;")
        self.assertNotIn("tyreId", function_body("storeSelection") + function_body("storedSelection"))
        body = function_body("loadTyres")
        self.assertIn("if (tyreEntry() === null) {", body)
        self.assertIn("const first = tyres.find((t) => !t.error);", body)
        self.assertIn("tyreId = first ? first.id : null;", body)
        self.assertIn("if (reload || tyreId !== before) await loadTyre();", body)
        self.assertIn("tyres.find((t) => t.id === tyreId && !t.error) || null", function_body("tyreEntry"))
        self.assertIn("if (seq !== tyreSeq) return;", body)

    def test_the_library_is_loaded_when_the_tab_is_shown_after_every_write_and_when_a_job_ends(self):
        self.assertIn('if (tabs[i] === $("tab-tyres")) loadTyres(true);', function_body("selectTab"))
        self.assertNotIn("loadTyres(", function_body("sendTyreSet"))
        self.assertNotIn("loadTyres(", function_body("sendTyreUnset"))
        self.assertIn("await loadTyres(true);", function_body("writeTyre"))
        self.assertIn('writeTyre("/api/tyre_source", { id: entry.id, source: key });', function_body("changeTyreSource"))
        self.assertIn('writeTyre("/api/tyre_reset", { id: entry.id });', function_body("resetTyre"))
        self.assertIn("await loadTyres(mine.kind !== \"rename\");", function_body("submitTyreDialog"))
        body = function_body("syncTyres")
        self.assertIn('if (tyreJobRunning && !running && !$("panel-tyres").hidden) loadTyres(true);', body)
        self.assertIn("syncTyres();", function_body("renderButtons"))
        self.assertEqual(re.findall(r"setTimeout\([^;]*[Tt]yre", CODE), [])
        self.assertEqual(re.findall(r"setInterval\(([^)]*)\)", CODE), ["pollLogStatus, LOG_POLL_MS"])

    def test_the_rows_are_loaded_when_a_tyre_is_selected_and_after_a_source_change_or_a_reset(self):
        self.assertIn('$("tyre-select").addEventListener("change", selectTyre);', CODE)
        body = function_body("selectTyre")
        self.assertIn("tyreId = id;", body)
        self.assertIn("loadTyre();", body)
        self.assertIn('$("tyre-source").addEventListener("change", changeTyreSource);', CODE)
        self.assertIn('$("btn-tyre-reset").addEventListener("click", resetTyre);', CODE)
        self.assertIn("buildTyreRows(res.rows, id);", function_body("loadTyre"))

    def test_the_empty_states_are_text_lines_not_hidden_controls(self):
        body = function_body("renderTyres")
        self.assertIn('if (tyreLoaded && tyres.length === 0) addLine(notes, "No tyres yet. Press New tyre to create one.", "empty");', body)
        self.assertIn('"No game tyres found: install a car in the Car Tuner tab first, its tyres become the sources."', body)
        self.assertIn("if (tyreLoaded && tyreSources.length === 0) {", body)
        self.assertNotRegex(body, r'btn-tyre-new"\)\.hidden')
        self.assertRegex(MARKUP, r'<div id="tyre-notes"></div>')

    def test_new_is_off_without_a_source_or_while_a_job_runs_and_rename_and_delete_without_a_tyre_or_while_a_job_runs(self):
        body = function_body("syncTyres")
        self.assertIn("const running = jobRunning();", body)
        self.assertIn('if (running) whyNew = "a job is running";', body)
        self.assertIn('else if (tyreSources.length === 0) whyNew = "install a car first (Car Tuner tab), its game tyres are the sources";', body)
        self.assertIn('if (running) whyEdit = "a job is running";', body)
        self.assertIn('else if (tyreEntry() === null) whyEdit = "select a tyre first";', body)
        self.assertIn('$("btn-tyre-new").disabled = whyNew !== "";', body)
        self.assertIn('$("btn-tyre-new").title = whyNew;', body)
        self.assertIn('for (const id of ["btn-tyre-rename", "btn-tyre-delete"]) {', body)
        self.assertIn('$(id).disabled = whyEdit !== "";', body)
        self.assertIn('$("tyre-source").disabled = running;', body)
        self.assertIn('$("btn-tyre-reset").disabled = running;', body)
        self.assertIn('for (const id of ["tyre-dialog-name", "tyre-dialog-source", "tyre-dialog-ok"]) $(id).disabled = locked;', body)
        self.assertIn("r.field.disabled = running || r.data.applicable === false;", body)
        self.assertIn("r.reset.disabled = running;", body)

    def test_the_options_are_the_names_the_damaged_files_are_not_selectable_and_the_sources_are_labelled(self):
        body = function_body("renderTyres")
        self.assertIn('el("option", "", t.error ? t.id + " (damaged)" : t.name)', body)
        self.assertIn("o.disabled = true;", body)
        self.assertIn('el("option", "", s.label)', body)
        self.assertIn('sourceText(entry.source) + " (not offered by any installed car)"', body)
        self.assertIn("gone.disabled = true;", body)
        self.assertIn("box.value = key;", body)
        self.assertIn('$("tyre-editor").hidden = entry === null;', body)
        self.assertIn('tyres.filter((t) => !t.error)', function_body("neighbourOf"))

    def test_the_rows_get_a_group_row_per_axle_in_the_order_of_the_server(self):
        body = function_body("buildTyreRows")
        self.assertIn('for (const axle of ["front", "rear"]) {', body)
        self.assertIn('buildTyreGroup(axle === "front" ? "Front tyre" : "Rear tyre")', body)
        self.assertIn("list.filter((data) => data.axle === axle)", body)
        self.assertIn("buildRow(item, null)", body)
        self.assertIn("r.save = sendTyreSet;", body)
        self.assertIn("r.clear = sendTyreUnset;", body)
        self.assertIn("r.tyre = id;", body)
        group = function_body("buildTyreGroup")
        self.assertNotIn("button", group)
        self.assertNotIn("expanded", group)
        self.assertIn('el("tr", "group")', group)
        self.assertIn('th.scope = "rowgroup";', group)
        self.assertIn("tr.group th.plain", STYLE)

    def test_the_tyre_rows_share_the_builders_of_the_car_table(self):
        self.assertIn("r.save(r, text)", function_body("commit"))
        self.assertIn("r.save(r, on)", function_body("commit"))
        self.assertIn("r.clear(r)", function_body("buildReset"))
        self.assertIn("save: sendSet, clear: sendUnset", function_body("newRow"))
        self.assertIn("Array.isArray(d.choices) && d.choices.length", function_body("buildField"))
        row = function_body("buildRow")
        self.assertIn('el("span", "badge", "unverified")', row)
        self.assertIn("if (!data.verified) {", row)
        self.assertIn('if (data.applicable === false) valueCell.appendChild(el("div", "msg warn", "Not applicable: " + data.reason));', row)
        self.assertIn('r.tr.classList.toggle("changed", data.changed);', function_body("showRow"))
        self.assertIn("showRow(r, res.row, false);", function_body("sendTyreSet"))
        self.assertIn("showRow(r, res.row, false);", function_body("sendTyreUnset"))
        self.assertNotIn("applyFilter", function_body("buildTyreRows"))

    def test_a_row_shows_the_server_text_of_a_refused_value_and_the_warnings(self):
        body = function_body("sendTyreSet")
        self.assertIn('setMsg(r, res.warnings.join(" "), "warn");', body)
        self.assertIn("setField(r);", body)
        self.assertIn('setMsg(r, e.message, "err");', body)
        self.assertIn('setMsg(r, e.message, "err");', function_body("sendTyreUnset"))
        self.assertIn('setMsg(r, "", "");', function_body("sendTyreUnset"))

    def test_the_dialog_serves_new_rename_and_delete_with_its_confirm_text(self):
        body = function_body("openTyreDialog")
        self.assertIn('"New tyre" : remove ? "Delete tyre" : "Rename tyre"', body)
        self.assertIn('"Delete tyre " + entry.name + "? This cannot be undone."', body)
        self.assertIn('$("tyre-dialog-ok").textContent = remove ? "Delete" : "OK";', body)
        self.assertIn('$("tyre-dialog-name-field").hidden = remove;', body)
        self.assertIn('$("tyre-dialog-source-field").hidden = !create;', body)
        self.assertIn('s.label + " \\u2014 " + s.cars.join(", ")', body)
        self.assertIn("if (create ? tyreSources.length === 0 : entry === null) return;", body)

    def test_the_dialog_stays_open_with_the_message_of_the_server_when_a_write_is_refused(self):
        body = function_body("submitTyreDialog")
        failure = body[body.index("} catch (e) {"):body.index("await loadTyres(")]
        self.assertIn("showTyreDialogError(e.message);", failure)
        self.assertNotIn("closeTyreDialog", failure)
        self.assertIn("mine.busy = false;", failure)
        self.assertIn("return;", failure)
        self.assertIn("tyreId = res.tyre.id;", body)
        self.assertIn("tyreId = neighbourOf(mine.id);", body)
        self.assertIn("if (tyreDialog === mine) closeTyreDialog(true);", body)
        self.assertIn('showText("tyre-dialog-error", text);', function_body("showTyreDialogError"))
        self.assertIn("if (!tyreDialog || tyreDialog.busy || jobRunning()) return;", body)

    def test_enter_confirms_and_escape_cancels_and_the_focus_goes_into_the_dialog_and_back(self):
        key = function_body("tyreDialogKey")
        self.assertIn('ev.key === "Escape"', key)
        self.assertIn("if (!tyreDialog.busy) closeTyreDialog(true);", key)
        self.assertIn('ev.key === "Enter" && ev.target.tagName === "INPUT"', key)
        self.assertIn("submitTyreDialog();", key)
        self.assertIn('$("tyre-dialog").addEventListener("keydown", tyreDialogKey);', CODE)
        opening = function_body("openTyreDialog")
        self.assertIn('$("tyre-dialog-name").focus();', opening)
        self.assertIn('$("tyre-dialog-cancel").focus();', opening)
        self.assertIn("const opener = tyreDialog ? tyreDialog.opener : document.activeElement;", opening)
        closing = function_body("closeTyreDialog")
        self.assertIn("if (restoreFocus) {", closing)
        self.assertIn('[opener, $("tyre-select"), $("btn-tyre-new")].find((n) => n && document.contains(n) && !n.disabled);', closing)
        self.assertIn('(back || $("tab-tyres")).focus();', closing)

    def test_the_new_buttons_are_wired_and_reset_all_asks_first(self):
        for kind, button in (("new", "btn-tyre-new"), ("rename", "btn-tyre-rename"), ("delete", "btn-tyre-delete")):
            with self.subTest(kind):
                self.assertIn('$("%s").addEventListener("click", () => openTyreDialog("%s"));' % (button, kind), CODE)
        self.assertIn('$("tyre-dialog-ok").addEventListener("click", submitTyreDialog);', CODE)
        self.assertIn('$("tyre-dialog-cancel").addEventListener("click", () => closeTyreDialog(true));', CODE)
        self.assertIn("window.confirm(", function_body("resetTyre"))

    def test_writes_to_the_library_go_through_the_one_queue_of_the_edits(self):
        self.assertIn("queue = queue.then(async () => {", function_body("writeTyre"))
        self.assertIn("await api(route, body, selection);", function_body("writeTyre"))
        for name in ("changeTyreSource", "resetTyre"):
            with self.subTest(name):
                self.assertIn("writeTyre(", function_body(name))
                self.assertNotIn("queue", function_body(name))

    def test_the_tab_neither_polls_nor_adds_a_second_fetch(self):
        self.assertEqual(len(re.findall(r"\bfetch\(", CODE)), 1)
        self.assertEqual(len(re.findall(r"\bpollTimer = setTimeout\(", CODE)), 1)

    def test_the_tyre_name_and_the_source_text_enter_the_page_as_text(self):
        for name in ("renderTyres", "openTyreDialog", "buildTyreGroup"):
            with self.subTest(name):
                body = function_body(name)
                self.assertIn("textContent" if name == "openTyreDialog" else "el(", body)
                self.assertNotRegex(body, r"\.html\b|innerHTML")


class TestGarage(unittest.TestCase):
    CAR_PANEL = MARKUP[MARKUP.index('id="panel-car"'):MARKUP.index('id="panel-tyres"')]
    PANEL = re.search(r'<div id="garage" class="panel garage">.*?\n      </div>\n', MARKUP, re.S).group(0)

    @staticmethod
    def tag(ident):
        return re.search(r'<[a-z]+\b[^>]*\bid="%s"[^>]*>' % ident, MARKUP).group(0)

    def test_the_panel_sits_in_the_settings_section_below_the_table(self):
        tuner = MARKUP[MARKUP.index('<section id="tuner"'):MARKUP.index('id="panel-tyres"')]
        self.assertIn('id="garage"', tuner)
        self.assertLess(tuner.index('<div class="toolbar">'), tuner.index('<div class="tablewrap">'))
        self.assertLess(tuner.index('<div class="tablewrap">'), tuner.index('id="garage"'))
        self.assertNotRegex(self.tag("garage"), r"\bhidden\b")
        self.assertIn('id="garage"', self.CAR_PANEL)
        self.assertNotIn('id="garage"', MARKUP[MARKUP.index('id="panel-tyres"'):])

    def test_the_panel_follows_the_table_and_ends_the_settings_section(self):
        tuner = MARKUP[MARKUP.index('<section id="tuner"'):MARKUP.index("</section>", MARKUP.index('<section id="tuner"'))]
        self.assertLess(tuner.index('id="empty"'), tuner.index('id="garage"'))
        self.assertEqual(tuner.count('id="garage"'), 1)

    def test_the_header_is_a_collapsed_toggle_button_with_a_chevron_the_name_and_the_summary(self):
        button = re.search(r'<button id="garage-toggle".*?</button>', self.PANEL, re.S).group(0)
        for part in ('class="grouptoggle"', 'type="button"', 'aria-expanded="false"', 'aria-controls="garage-body"'):
            self.assertIn(part, button)
        self.assertIn('<span class="chev" aria-hidden="true"></span>', button)
        self.assertIn('<span class="gname">Garage tyres</span>', button)
        self.assertIn('<span id="garage-count" class="gcount"></span>', button)
        self.assertIn("garage-body", dom_ids())

    def test_the_body_is_hidden_by_default_and_holds_the_help_the_list_the_reset_button_and_the_lines(self):
        self.assertRegex(self.tag("garage-body"), r"\bhidden>$")
        body = self.PANEL[self.PANEL.index('id="garage-body"'):]
        for text in ("Tick the tyres this car offers in the garage.", "The first ticked tyre in the list is the one the car starts on.",
                     "Own tyres (from the Tyre Creator tab) are listed first.",
                     "Unverified: whether the game accepts extra or removed tyres is not tested yet."):
            self.assertIn(text, body)
        self.assertRegex(body, r'<fieldset>\s*<legend class="sr-only">Tyres offered in the garage</legend>\s*<div id="garage-rows"></div>\s*</fieldset>')
        self.assertIn('<button id="btn-garage-reset" type="button" disabled>Reset to stock tyres</button>', body)
        self.assertIn('<p id="garage-error" class="msg err" role="alert" hidden></p>', body)
        self.assertIn('<p id="garage-missing" class="msg warn" hidden></p>', body)
        self.assertLess(body.index("<fieldset>"), body.index("btn-garage-reset"))
        self.assertLess(body.index("btn-garage-reset"), body.index('id="garage-error"'))

    def test_a_row_is_a_checkbox_in_a_label_with_the_name_and_muted_texts_for_the_kind_and_the_start(self):
        body = function_body("renderGarage")
        self.assertIn('input.type = "checkbox";', body)
        self.assertIn("input.checked = c.ticked;", body)
        self.assertIn('label.append(input, el("span", "", c.label));', body)
        self.assertIn('c.kind === "own" ? "own tyre" : "stock tyre"', body)
        self.assertIn('if (c.start) row.appendChild(el("span", "unit", "starts on this"));', body)
        self.assertIn('el("div", "garage-row")', body)
        self.assertIn("garageRows.push({ key: c.key, input: input });", body)
        self.assertNotRegex(body, r"innerHTML|\.html\b")

    def test_the_summary_counts_the_ticked_tyres_and_names_the_start(self):
        body = function_body("garageSummary")
        self.assertIn('"(" + garage.choices.filter((c) => c.ticked).length + " of " + garage.choices.length + " ticked"', body)
        self.assertIn('(start ? ", starts on " + start.label : "") + ")"', body)
        self.assertIn("garage.choices.find((c) => c.start)", body)
        self.assertIn('$("garage-count").textContent = garageSummary();', function_body("renderGarageToggle"))

    def test_the_panel_is_collapsed_by_default_and_the_toggle_flips_a_separate_variable(self):
        self.assertRegex(CODE, r"(?m)^let garageOpen = false;")
        self.assertNotRegex(CODE, r"garageOpen = true")
        body = function_body("toggleGarage")
        self.assertIn("garageOpen = !garageOpen;", body)
        self.assertNotIn("expanded", body)
        toggle = function_body("renderGarageToggle")
        self.assertIn('$("garage-toggle").setAttribute("aria-expanded", garageOpen ? "true" : "false");', toggle)
        self.assertIn('$("garage-body").hidden = !garageOpen;', toggle)
        self.assertNotIn("remove(", toggle)
        self.assertIn('$("garage-toggle").addEventListener("click", toggleGarage);', CODE)

    def test_expand_all_and_collapse_all_do_not_touch_the_garage(self):
        for name in ("setAllGroups", "toggleGroup", "applyFilter", "revealGroup"):
            with self.subTest(name):
                self.assertNotIn("garage", function_body(name).lower())
        self.assertNotIn("garage", re.search(r'<div class="toolbar">.*?</div>', MARKUP, re.S).group(0))

    def test_another_car_collapses_the_panel_and_forgets_the_old_answer(self):
        body = function_body("switchCar")
        for part in ("garageOpen = false;", "garage = null;", 'garageError = "";', "renderGarage();"):
            self.assertIn(part, body)
        self.assertEqual(len(re.findall(r"(?m)^  garageOpen = false;", CODE)), 1)

    def test_the_garage_is_read_with_the_selection_without_a_body_through_the_one_api_helper(self):
        body = function_body("loadGarage")
        self.assertIn('await api("/api/garage", undefined, target);', body)
        self.assertIn("if (!tableLoaded) return;", body)
        self.assertIn("if (seq !== garageSeq || target !== selection) return;", body)
        self.assertIn("garage = res;", body)
        self.assertIn("garageError = e.message;", body)
        self.assertIn("renderGarage();", body)
        self.assertEqual(len(re.findall(r"\bfetch\(", CODE)), 1)

    def test_the_garage_is_loaded_with_the_table_after_a_tab_change_after_a_job_and_after_create_and_apply(self):
        self.assertIn("loadGarage();", function_body("loadCarPanels"))
        self.assertLess(function_body("loadSettings").index("tableLoaded = true;"), function_body("loadSettings").index("loadCarPanels();"))
        self.assertIn('if (tabs[i] === $("tab-car")) loadCarPanels();', function_body("selectTab"))
        body = function_body("syncGarage")
        self.assertIn('if (garageJobRunning && !running && !$("panel-car").hidden) loadGarage();', body)
        self.assertIn("garageJobRunning = running;", body)
        self.assertIn("syncGarage();", function_body("renderButtons"))
        self.assertRegex(function_body("startJob"), r"await refresh\(\);\s*if \(serverState && !jobRunning\(\)\) loadCarPanels\(\);")
        self.assertRegex(function_body("submitDialog"), r"await refresh\(\);\s*if \(serverState && !jobRunning\(\)\) loadCarPanels\(\);")
        self.assertEqual(len(re.findall(r"\bpollTimer = setTimeout\(", CODE)), 1)
        self.assertEqual(re.findall(r"setInterval\(([^)]*)\)", CODE), ["pollLogStatus, LOG_POLL_MS"])
        self.assertEqual(re.findall(r"setTimeout\([^;]*[Gg]arage", CODE), [])

    def test_a_change_posts_the_ticked_keys_in_the_order_of_the_choices_through_the_shared_queue(self):
        self.assertIn('$("garage").addEventListener("change", garageChanged);', CODE)
        body = function_body("garageChanged")
        self.assertIn("garageRows.filter((g) => g.input.checked).map((g) => g.key)", body)
        self.assertIn("queue = queue.then(() => sendGarageSet(keys, target));", body)
        self.assertIn("const target = selection;", body)
        send = function_body("sendGarageSet")
        self.assertIn('await api("/api/garage_set", { keys: keys }, target);', send)
        self.assertIn("showGarage(target, res.garage);", send)
        self.assertEqual(set(re.findall(r'\b(\w+):', re.search(r'api\("/api/garage_set", (\{[^}]*\})', CODE).group(1))),
                         set(re.findall(r'body\.get\("(\w+)"\)', inspect.getsource(ts.api_garage_set))) - {"tune"})

    def test_unticking_the_last_tyre_is_prevented_with_a_message_and_no_call(self):
        body = function_body("garageChanged")
        refusal = body[body.index("if (keys.length === 0) {"):body.index("garageError = \"\";")]
        self.assertIn("row.input.checked = true;", refusal)
        self.assertIn('garageError = "Tick at least one tyre.";', refusal)
        self.assertIn("return;", refusal)
        self.assertNotIn("queue", refusal)
        self.assertNotIn("api(", refusal)
        self.assertIn("tick at least one tyre", inspect.getsource(ts.tune.set_garage))

    def test_reset_posts_garage_reset_through_the_queue_and_is_off_unless_the_selection_is_custom(self):
        self.assertIn('$("btn-garage-reset").addEventListener("click", resetGarage);', CODE)
        self.assertIn("queue = queue.then(() => sendGarageReset(target));", function_body("resetGarage"))
        self.assertIn('await api("/api/garage_reset", {}, target);', function_body("sendGarageReset"))
        self.assertIn("showGarage(target, res.garage);", function_body("sendGarageReset"))
        body = function_body("lockGarage")
        self.assertIn('if (!locked && !(garage && garage.custom)) why = "the car offers its stock tyres already";', body)
        self.assertIn('$("btn-garage-reset").disabled = why !== "";', body)
        self.assertIn('$("btn-garage-reset").title = why;', body)

    def test_the_server_answer_wins_and_a_failed_write_reads_the_garage_again_and_keeps_its_message(self):
        show = function_body("showGarage")
        self.assertIn("if (target !== selection) return;", show)
        self.assertIn("garageSeq += 1;", show)
        self.assertIn("garage = answer;", show)
        self.assertIn("renderGarage();", show)
        failed = function_body("garageFailed")
        self.assertLess(failed.index("await loadGarage();"), failed.index("garageError = e.message;"))
        self.assertIn("renderGarageLines();", failed)
        for name in ("sendGarageSet", "sendGarageReset"):
            with self.subTest(name):
                self.assertIn("await garageFailed(target, e);", function_body(name))
        self.assertEqual(inspect.getsource(ts.garage_json).count("tune.garage_choices"), 1)

    def test_the_missing_keys_are_a_warning_line_and_the_error_line_is_the_alert_of_the_panel(self):
        body = function_body("renderGarageLines")
        self.assertIn('"No longer available, Apply is refused until you change the tyre list or reset it: " + missing.join(", ")', body)
        self.assertIn("garage ? garage.missing : []", body)
        self.assertIn('$("garage-missing").hidden = missing.length === 0;', body)
        self.assertIn('showText("garage-error", garageError);', body)
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)
        self.assertNotIn("aria-live", self.PANEL)

    def test_the_checkboxes_and_the_reset_button_are_off_while_a_job_runs_or_without_a_base_car(self):
        body = function_body("lockGarage")
        self.assertIn("let why = panelLockReason();", body)
        self.assertIn("for (const g of garageRows) g.input.disabled = locked;", body)
        self.assertIn("lockGarage();", function_body("renderGarage"))
        self.assertIn("lockGarage();", function_body("syncGarage"))

    def test_the_focus_goes_back_to_the_toggled_checkbox_by_its_key_after_the_redraw(self):
        body = function_body("renderGarage")
        self.assertIn("garageRows.find((g) => g.input === document.activeElement)", body)
        self.assertIn("garageRows.find((g) => g.key === focused.key)", body)
        self.assertIn("if (back && !back.input.disabled) back.input.focus();", body)
        self.assertLess(body.index("lockGarage();"), body.index("back.input.focus();"))
        self.assertNotIn("aria-live", function_body("renderGarage") + function_body("renderGarageToggle") + function_body("toggleGarage"))

    def test_the_styles_use_tokens_and_the_chevron_of_the_group_toggle(self):
        for cls in ("garage", "garage-body", "garage-help", "garage-row"):
            with self.subTest(cls):
                self.assertIn(cls, css_classes())
                self.assertIn(cls, used_classes())
        self.assertIn(".garage-help { font-size: 13px; color: var(--color-text-muted); }", STYLE)
        self.assertIn(".garage fieldset { min-width: 0;", STYLE)
        self.assertIn(".garage { padding: 0; overflow-wrap: anywhere; }", STYLE)

    def test_the_server_routes_the_page_calls_exist_and_the_exemption_list_is_gone(self):
        for route in ("/api/garage", "/api/garage_set", "/api/garage_reset"):
            with self.subTest(route):
                self.assertTrue(route in ts.GET_ROUTES or route in ts.POST_ROUTES)
                self.assertIn(route, called_paths())
        self.assertNotIn("SERVER_ONLY", globals())
        self.assertEqual(sorted(TestApiContract.ROUTES), sorted(list(ts.GET_ROUTES) + list(ts.POST_ROUTES)))

    def test_the_fields_of_a_choice_the_page_reads_are_sent_by_the_server(self):
        source = inspect.getsource(ts.tune.garage_choices) + inspect.getsource(ts.tune.garage_entries)
        sent = quoted_words(ts.tune.garage_choices, ts.tune.garage_entries) | set(re.findall(r"\b(\w+)=", source))
        read = set(re.findall(r"\b(?:c|garage)\.(\w+)", "".join(function_body(n) for n in ("renderGarage", "garageSummary", "lockGarage", "renderGarageLines"))))
        self.assertTrue({"key", "kind", "label", "ticked", "start", "choices", "custom", "missing"} <= read, sorted(read))
        self.assertEqual(sorted(read - sent), [])


class TestTurboKit(unittest.TestCase):
    CAR_PANEL = MARKUP[MARKUP.index('id="panel-car"'):MARKUP.index('id="panel-tyres"')]
    PANEL = re.search(r'<div id="turbo" class="panel garage" hidden>.*?\n      </div>\n', MARKUP, re.S).group(0)
    FUNCTIONS = ("boostText", "turboBoostText", "turboOptionText", "turboSummary", "turboPickedText", "renderTurboToggle", "renderTurboLines", "lockTurbo",
                 "renderTurbo", "syncTurbo", "loadTurbo", "showTurbo", "turboFailed", "sendTurboSet", "sendTurboReset",
                 "turboChanged", "toggleTurbo")

    @staticmethod
    def tag(ident):
        return re.search(r'<[a-z]+\b[^>]*\bid="%s"[^>]*>' % ident, MARKUP).group(0)

    def test_the_panel_sits_directly_above_the_garage_panel_below_the_table(self):
        tuner = MARKUP[MARKUP.index('<section id="tuner"'):MARKUP.index("</section>", MARKUP.index('<section id="tuner"'))]
        self.assertEqual(tuner.count('id="turbo"'), 1)
        self.assertLess(tuner.index('id="empty"'), tuner.index('id="turbo"'))
        self.assertLess(tuner.index('id="turbo"'), tuner.index('id="garage"'))
        between = tuner[tuner.index('id="turbo"'):tuner.index('<div id="garage"')]
        self.assertEqual(between.count('class="panel garage"'), 1)
        self.assertIn('id="turbo"', self.CAR_PANEL)
        self.assertNotIn('id="turbo"', MARKUP[MARKUP.index('id="panel-tyres"'):])

    def test_the_panel_is_hidden_until_the_server_has_answered(self):
        self.assertRegex(self.tag("turbo"), r"\bhidden>$")
        self.assertIn('$("turbo").hidden = !turbo || turbo.has_turbo;', function_body("renderTurbo"))
        self.assertRegex(CODE, r"(?m)^let turbo = null;")

    def test_the_header_is_a_collapsed_toggle_button_with_a_chevron_the_name_and_the_summary(self):
        button = re.search(r'<button id="turbo-toggle".*?</button>', self.PANEL, re.S).group(0)
        for part in ('class="grouptoggle"', 'type="button"', 'aria-expanded="false"', 'aria-controls="turbo-body"'):
            self.assertIn(part, button)
        self.assertIn('<span class="chev" aria-hidden="true"></span>', button)
        self.assertIn('<span class="gname">Turbo kit</span>', button)
        self.assertIn('<span id="turbo-count" class="gcount"></span>', button)
        self.assertIn("turbo-body", dom_ids())

    def test_the_body_is_hidden_by_default_and_holds_the_help_the_select_the_picked_line_and_the_error(self):
        self.assertRegex(self.tag("turbo-body"), r"\bhidden>$")
        body = self.PANEL[self.PANEL.index('id="turbo-body"'):]
        self.assertIn("Adds the turbo setup of another installed car to this modded car. Apply copies the donor's turbo files and engine turbo "
                      "fields into your car; the turbo settings then appear in the Turbo group of the table. A turbo multiplies the engine "
                      "power on top of its curve, so lower the boost settings if the car becomes too strong. Unverified: whether the game "
                      "accepts a turbo on a car that has none is not tested yet.", body)
        self.assertIn("In the list, a boost like 0.7 / 0.9 bar is one value per turbo (the max boost of each turbo file); '(reference)' is "
                      "the engine's own reference value when the turbo files carry none, and no bar means the game data has no boost value "
                      "for that car.</p>", body)
        self.assertRegex(body, r'<label for="turbo-donor">Turbo from</label>\s*<select id="turbo-donor" disabled></select>')
        self.assertRegex(body, r'</select>\s*</div>\s*<p id="turbo-picked"></p>\s*<p id="turbo-error" class="msg err" role="alert" hidden></p>')
        self.assertNotIn("aria-live", self.PANEL)
        self.assertNotIn("<button", body)
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)

    def test_the_panel_is_collapsed_by_default_and_the_toggle_flips_a_separate_variable(self):
        self.assertRegex(CODE, r"(?m)^let turboOpen = false;")
        self.assertNotRegex(CODE, r"turboOpen = true")
        body = function_body("toggleTurbo")
        self.assertIn("turboOpen = !turboOpen;", body)
        self.assertNotIn("expanded", body)
        toggle = function_body("renderTurboToggle")
        self.assertIn('$("turbo-toggle").setAttribute("aria-expanded", turboOpen ? "true" : "false");', toggle)
        self.assertIn('$("turbo-body").hidden = !turboOpen;', toggle)
        self.assertIn('$("turbo-count").textContent = turboSummary();', toggle)
        self.assertIn('$("turbo-toggle").addEventListener("click", toggleTurbo);', CODE)
        for name in ("setAllGroups", "toggleGroup", "applyFilter", "revealGroup"):
            with self.subTest(name):
                self.assertNotIn("turbo", function_body(name).lower())

    def test_another_car_collapses_the_panel_and_forgets_the_old_answer(self):
        body = function_body("switchCar")
        for part in ("turboOpen = false;", "turbo = null;", 'turboError = "";', "renderTurbo();"):
            self.assertIn(part, body)
        self.assertEqual(len(re.findall(r"(?m)^  turboOpen = false;", CODE)), 1)

    def test_the_summary_says_none_or_the_kind_and_the_name_of_the_donor(self):
        body = function_body("turboSummary")
        self.assertIn('if (!turbo.donor) return "(none)";', body)
        self.assertIn('return "(" + turbo.picked.kind + " from " + turbo.picked.label + ")";', body)
        self.assertIn('"(" + turbo.donor + ", not available any more)"', body)

    def test_an_option_is_the_name_the_kind_and_the_boost_of_a_donor_and_the_boost_is_left_out_when_unknown(self):
        self.assertIn('entry.label + " - " + entry.kind + (boost ? ", " + boost : "")', function_body("turboOptionText"))
        self.assertIn("const boost = turboBoostText(entry);", function_body("turboOptionText"))
        self.assertIn('list.map((b) => String(Math.round(b * 100) / 100)).join(" / ")', function_body("boostText"))
        body = function_body("renderTurbo")
        self.assertIn('el("option", "", "No turbo kit (stock engine)")', body)
        self.assertIn('none.value = "";', body)
        self.assertIn("for (const entry of turbo ? turbo.donors : []) {", body)
        self.assertIn("o.value = entry.car;", body)
        self.assertIn("turboOptionText(entry)", body)
        self.assertLess(body.index("No turbo kit (stock engine)"), body.index("turboOptionText(entry)"))

    def test_the_boost_text_is_the_values_per_turbo_else_the_reference_else_nothing(self):
        body = function_body("turboBoostText")
        self.assertIn('if (entry.boost.length) return boostText(entry.boost) + " bar";', body)
        self.assertIn('return entry.boost_ref ? "~" + boostText([entry.boost_ref]) + " bar (reference)" : "";', body)
        self.assertLess(body.index("entry.boost.length"), body.index("entry.boost_ref"))
        self.assertNotIn("unknown", body)

    def test_the_saved_donor_is_preselected_and_one_that_is_gone_is_a_disabled_selected_option(self):
        body = function_body("renderTurbo")
        self.assertIn('select.value = turbo && turbo.donor ? turbo.donor : "";', body)
        self.assertIn("if (turbo && turbo.donor && !turbo.picked) {", body)
        self.assertIn('el("option", "", turbo.donor + " (not available any more)")', body)
        self.assertIn("gone.disabled = true;", body)
        self.assertLess(body.index("gone.disabled = true;"), body.index("select.value ="))

    def test_the_line_below_the_select_says_which_turbo_the_chosen_donor_has(self):
        body = function_body("turboPickedText")
        self.assertIn('"No turbo kit chosen."', body)
        self.assertIn('"No installed car has a turbo: install one first (select a car with a turbo and press Install car)."', body)
        self.assertIn("turbo.donors.length === 0", body)
        self.assertIn('" is not available any more. Choose another donor or no turbo kit."', body)
        self.assertIn('" (" + entry.count + (entry.count === 1 ? " turbo)" : " turbos)")', body)
        self.assertIn("entry.count <= 2", body)
        self.assertIn('const boost = turboBoostText(entry) ? ", boost " + turboBoostText(entry) : "";', body)
        self.assertIn('"Chosen: " + entry.kind + count + boost + ", from " + entry.label', body)
        self.assertIn('$("turbo-picked").textContent = turboPickedText();', function_body("renderTurboLines"))

    def test_the_error_line_shows_the_message_of_a_failed_write(self):
        body = function_body("renderTurboLines")
        self.assertIn('showText("turbo-error", turboError);', body)
        failed = function_body("turboFailed")
        self.assertLess(failed.index("await loadTurbo();"), failed.index("turboError = e.message;"))
        self.assertIn("renderTurboLines();", failed)
        for name in ("sendTurboSet", "sendTurboReset"):
            with self.subTest(name):
                self.assertIn("await turboFailed(target, e);", function_body(name))

    def test_the_kit_is_read_with_the_selection_without_a_body_through_the_one_api_helper(self):
        body = function_body("loadTurbo")
        self.assertIn('await api("/api/turbo", undefined, target);', body)
        self.assertIn("if (!tableLoaded) return;", body)
        self.assertIn("const seq = ++turboSeq;", body)
        self.assertIn("if (seq !== turboSeq || target !== selection) return;", body)
        self.assertIn("turbo = res;", body)
        self.assertIn("turboError = e.message;", body)
        self.assertIn("renderTurbo();", body)
        self.assertEqual(len(re.findall(r"\bfetch\(", CODE)), 1)

    def test_the_kit_is_loaded_with_the_table_after_a_tab_change_after_a_job_and_after_create_and_apply(self):
        body = function_body("loadSettings")
        self.assertIn("loadTurbo();", function_body("loadCarPanels"))
        self.assertIn("turboJobRunning = running;", function_body("loadCarPanels"))
        self.assertLess(body.index("tableLoaded = true;"), body.index("loadCarPanels();"))
        self.assertIn('if (tabs[i] === $("tab-car")) loadCarPanels();', function_body("selectTab"))
        controls = function_body("syncTurbo")
        self.assertIn('if (turboJobRunning && !running && !$("panel-car").hidden) loadTurbo();', controls)
        self.assertIn("turboJobRunning = running;", controls)
        self.assertIn("syncTurbo();", function_body("renderButtons"))
        self.assertRegex(function_body("startJob"), r"await refresh\(\);\s*if \(serverState && !jobRunning\(\)\) loadCarPanels\(\);")
        self.assertRegex(function_body("submitDialog"), r"await refresh\(\);\s*if \(serverState && !jobRunning\(\)\) loadCarPanels\(\);")
        self.assertEqual(len(re.findall(r"\bpollTimer = setTimeout\(", CODE)), 1)
        self.assertEqual(re.findall(r"setInterval\(([^)]*)\)", CODE), ["pollLogStatus, LOG_POLL_MS"])
        self.assertEqual(re.findall(r"setTimeout\([^;]*[Tt]urbo", CODE), [])

    def test_a_change_posts_the_donor_or_the_reset_through_the_shared_queue(self):
        self.assertIn('$("turbo-donor").addEventListener("change", turboChanged);', CODE)
        body = function_body("turboChanged")
        self.assertIn('const donor = $("turbo-donor").value;', body)
        self.assertIn("const target = selection;", body)
        self.assertIn("queue = queue.then(async () => {", body)
        self.assertIn('donor === "" ? await sendTurboReset(target) : await sendTurboSet(donor, target)', body)
        send = function_body("sendTurboSet")
        self.assertIn('await api("/api/turbo_set", { donor: donor }, target);', send)
        self.assertIn("showTurbo(target, res.turbo);", send)
        reset = function_body("sendTurboReset")
        self.assertIn('await api("/api/turbo_reset", {}, target);', reset)
        self.assertIn("showTurbo(target, res.turbo);", reset)
        fields = set(re.findall(r"\b(\w+):", re.search(r'api\("/api/turbo_set", (\{[^}]*\})', CODE).group(1)))
        self.assertEqual(fields, set(re.findall(r'body\.get\("(\w+)"\)', inspect.getsource(ts.api_turbo_set))) - {"tune"})

    def test_the_server_answer_wins_over_what_the_page_showed(self):
        show = function_body("showTurbo")
        self.assertIn("if (target !== selection) return;", show)
        self.assertIn("turboSeq += 1;", show)
        self.assertIn("turbo = answer;", show)
        self.assertIn("renderTurbo();", show)

    def test_the_settings_table_is_read_again_after_a_write_and_the_open_groups_are_kept(self):
        body = function_body("turboChanged")
        self.assertIn("if (done && target === selection) await loadSettings(false);", body)
        self.assertLess(body.index("sendTurboSet(donor, target)"), body.index("await loadSettings(false);"))
        self.assertNotIn("expanded", body)
        self.assertNotIn("tableLoaded", body)
        self.assertNotIn("clearTable", body)
        for name in ("sendTurboSet", "sendTurboReset"):
            with self.subTest(name):
                self.assertIn("return true;", function_body(name))
                self.assertIn("return false;", function_body(name))
        self.assertEqual(len(re.findall(r"expanded\.clear\(\)", CODE)), 2)
        self.assertNotIn("expanded.clear()", function_body("loadSettings"))

    def test_the_select_is_off_while_a_job_runs_without_a_base_car_and_with_nothing_to_choose_from(self):
        body = function_body("lockTurbo")
        self.assertIn("const why = panelLockReason();", body)
        self.assertIn("const nothing = !turbo || (turbo.donors.length === 0 && !turbo.donor);", body)
        self.assertIn('$("turbo-donor").disabled = why !== "" || nothing;', body)
        self.assertIn('$("turbo-donor").title = why;', body)
        self.assertIn("lockTurbo();", function_body("renderTurbo"))
        self.assertIn("lockTurbo();", function_body("syncTurbo"))

    def test_the_focus_stays_on_the_select_after_the_redraw(self):
        body = function_body("renderTurbo")
        self.assertIn('const select = $("turbo-donor");', body)
        self.assertIn("const focused = document.activeElement === select;", body)
        self.assertIn("if (focused && !select.disabled) select.focus();", body)
        self.assertLess(body.index("lockTurbo();"), body.index("select.focus();"))
        self.assertNotIn("aria-live", "".join(function_body(n) for n in self.FUNCTIONS))

    def test_the_page_reads_only_the_fields_of_the_answer_the_server_sends(self):
        source = inspect.getsource(ts.turbo_json)
        sent = quoted_words(ts.tune.turbo_choice, ts.tune.turbo_donor, ts.turbo_json) | set(re.findall(r"\b(\w+)=", source))
        read = set(re.findall(r"\b(?:turbo|entry)\.(\w+)", "".join(function_body(n) for n in self.FUNCTIONS)))
        self.assertTrue({"donor", "donors", "picked", "has_turbo", "label", "kind", "count", "boost", "boost_ref", "car"} <= read, sorted(read))
        self.assertEqual(sorted(read - sent - {"length"}), [])

    def test_the_server_routes_the_page_calls_exist(self):
        self.assertIn("/api/turbo", ts.GET_ROUTES)
        for route in ("/api/turbo_set", "/api/turbo_reset"):
            self.assertIn(route, ts.POST_ROUTES)
        for route in ("/api/turbo", "/api/turbo_set", "/api/turbo_reset"):
            self.assertIn(route, called_paths())

    def test_the_panel_reuses_the_garage_styles_and_the_select_takes_tokens(self):
        for cls in ("garage", "garage-body", "garage-help", "garage-row", "grouptoggle", "gname", "gcount", "chev"):
            self.assertIn(cls, css_classes())
        self.assertIn("garage-help", self.PANEL)
        rule = re.search(r'\ninput:not\(\[type="checkbox"\]\), select, \.valuewrap input \{([^}]*)\}', STYLE).group(1)
        for part in ("border: 1px solid var(--color-border);", "background: var(--color-bg);", "color: var(--color-text);"):
            self.assertIn(part, rule)
        self.assertRegex(STYLE, r"\n\.dialog \.field select, \.garage select \{[^}]*max-width: 100%;")

    def test_the_help_text_reads_on_the_panel_background(self):
        tokens = dict(re.findall(r"--([\w-]+): (#[0-9a-fA-F]{6});", STYLE))
        self.assertIn("background: var(--color-bg-alt);", re.search(r"\n\.panel \{([^}]*)\}", STYLE).group(1))
        self.assertGreaterEqual(contrast(tokens["color-text-muted"], tokens["color-bg-alt"]), 4.5)
        self.assertGreaterEqual(contrast(tokens["color-text"], tokens["color-bg-alt"]), 4.5)

    def test_the_kit_text_enters_the_page_as_text(self):
        for name in self.FUNCTIONS:
            with self.subTest(name):
                self.assertNotRegex(function_body(name), r"\.html\b|innerHTML")
        for name in ("renderTurbo", "renderTurboToggle", "renderTurboLines"):
            with self.subTest(name):
                self.assertTrue("textContent" in function_body(name) or 'el("option"' in function_body(name))


class TestSounds(unittest.TestCase):
    CAR_PANEL = MARKUP[MARKUP.index('id="panel-car"'):MARKUP.index('id="panel-tyres"')]
    PANEL = re.search(r'<div id="sounds" class="panel garage">.*?\n      </div>\n', MARKUP, re.S).group(0)
    FUNCTIONS = ("soundShortName", "soundCarNames", "soundOptionText", "soundsChosen", "soundsSummary", "renderSoundsToggle",
                 "renderSoundsLines", "lockSounds", "renderSounds", "syncSounds", "loadSounds", "showSounds", "soundsFailed",
                 "sendSoundSet", "sendSoundReset", "soundChanged", "resetSounds", "toggleSounds")

    @staticmethod
    def tag(ident):
        return re.search(r'<[a-z]+\b[^>]*\bid="%s"[^>]*>' % ident, MARKUP).group(0)

    def test_the_panel_is_the_last_element_of_the_settings_section_directly_after_the_garage_panel(self):
        tuner = MARKUP[MARKUP.index('<section id="tuner"'):MARKUP.index("</section>", MARKUP.index('<section id="tuner"'))]
        self.assertEqual(tuner.count('id="sounds"'), 1)
        self.assertLess(tuner.index('id="garage"'), tuner.index('id="sounds"'))
        between = tuner[tuner.index('id="garage"'):tuner.index('<div id="sounds"')]
        self.assertEqual(between.count('class="panel garage"'), 1)
        self.assertTrue(tuner.rstrip().endswith(self.PANEL.rstrip()))
        self.assertNotRegex(self.tag("sounds"), r"\bhidden\b")
        self.assertIn('id="sounds"', self.CAR_PANEL)
        self.assertNotIn('id="sounds"', MARKUP[MARKUP.index('id="panel-tyres"'):])

    def test_the_header_is_a_collapsed_toggle_button_with_a_chevron_the_name_and_the_summary(self):
        button = re.search(r'<button id="sounds-toggle".*?</button>', self.PANEL, re.S).group(0)
        for part in ('class="grouptoggle"', 'type="button"', 'aria-expanded="false"', 'aria-controls="sounds-body"'):
            self.assertIn(part, button)
        self.assertIn('<span class="chev" aria-hidden="true"></span>', button)
        self.assertIn('<span class="gname">Sounds</span>', button)
        self.assertIn('<span id="sounds-count" class="gcount"></span>', button)
        self.assertIn("sounds-body", dom_ids())

    def test_the_body_is_hidden_by_default_and_holds_the_help_the_two_labelled_selects_the_reset_button_and_the_lines(self):
        self.assertRegex(self.tag("sounds-body"), r"\bhidden>$")
        body = self.PANEL[self.PANEL.index('id="sounds-body"'):]
        self.assertIn("Give this car the turbo sound and the exhaust backfire sound of another car. The first entry of each list is the "
                      "car's own sound. This changes only what the car sounds like, not how it drives. Unverified: not heard in the game "
                      "yet.", body)
        self.assertRegex(body, r'<label for="sound-turbo">Turbo sound</label>\s*<select id="sound-turbo" disabled></select>')
        self.assertRegex(body, r'<label for="sound-backfire">Backfire sound</label>\s*<select id="sound-backfire" disabled></select>')
        self.assertIn('<button id="btn-sound-reset" type="button" disabled>Reset to the car\'s own sounds</button>', body)
        self.assertIn('<p id="sounds-error" class="msg err" role="alert" hidden></p>', body)
        self.assertIn('<p id="sounds-missing" class="msg warn" hidden></p>', body)
        self.assertLess(body.index("garage-help"), body.index('id="sound-turbo"'))
        self.assertLess(body.index('id="sound-turbo"'), body.index('id="sound-backfire"'))
        self.assertLess(body.index('id="sound-backfire"'), body.index("btn-sound-reset"))
        self.assertLess(body.index("btn-sound-reset"), body.index('id="sounds-error"'))
        self.assertLess(body.index('id="sounds-error"'), body.index('id="sounds-missing"'))
        self.assertNotIn("aria-live", self.PANEL)
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)

    def test_the_panel_is_collapsed_by_default_and_the_toggle_flips_a_separate_variable(self):
        self.assertRegex(CODE, r"(?m)^let soundsOpen = false;")
        self.assertNotRegex(CODE, r"soundsOpen = true")
        body = function_body("toggleSounds")
        self.assertIn("soundsOpen = !soundsOpen;", body)
        self.assertNotIn("expanded", body)
        toggle = function_body("renderSoundsToggle")
        self.assertIn('$("sounds-toggle").setAttribute("aria-expanded", soundsOpen ? "true" : "false");', toggle)
        self.assertIn('$("sounds-body").hidden = !soundsOpen;', toggle)
        self.assertIn('$("sounds-count").textContent = soundsSummary();', toggle)
        self.assertIn('$("sounds-toggle").addEventListener("click", toggleSounds);', CODE)
        for name in ("setAllGroups", "toggleGroup", "applyFilter", "revealGroup"):
            with self.subTest(name):
                self.assertNotIn("sound", function_body(name).lower())
        self.assertNotIn("sound", re.search(r'<div class="toolbar">.*?</div>', MARKUP, re.S).group(0))

    def test_another_car_collapses_the_panel_and_forgets_the_old_answer(self):
        body = function_body("switchCar")
        for part in ("soundsOpen = false;", "sounds = null;", 'soundsError = "";', "renderSounds();", "turboSoundLink = null;"):
            self.assertIn(part, body)
        self.assertEqual(len(re.findall(r"(?m)^  soundsOpen = false;", CODE)), 1)

    def test_the_summary_counts_the_slots_with_a_choice_or_says_own_sounds(self):
        self.assertIn("SOUND_SLOTS.filter((slot) => sounds.slots[slot].selected !== null).length", function_body("soundsChosen"))
        body = function_body("soundsSummary")
        self.assertIn('n === 0 ? "(own sounds)" : "(" + n + " changed)"', body)
        self.assertIn('if (!sounds) return "";', body)
        self.assertIn('const SOUND_SLOTS = ["turbo", "backfire"];', CODE)
        self.assertEqual(set(ts.tune.sounds.SLOTS), {"turbo", "backfire"})

    def test_the_first_entry_of_a_list_is_the_own_sound_and_the_own_sound_is_left_out_of_the_rest(self):
        body = function_body("renderSounds")
        self.assertIn('el("option", "", "The car\'s own sound (" + (view && view.own !== null ? soundShortName(view.own) : "none") + ")")', body)
        self.assertIn('own.value = "";', body)
        self.assertIn("for (const option of view ? view.options : []) {", body)
        self.assertIn("if (option.key === view.own) continue;", body)
        self.assertIn("o.value = option.key;", body)
        self.assertIn("soundOptionText(option)", body)
        self.assertLess(body.index("own.value"), body.index("soundOptionText(option)"))
        self.assertIn('select.value = view && view.selected !== null ? view.selected : "";', body)
        self.assertRegex(CODE, r'(?m)^const SOUND_SELECTS = \{ turbo: \$\("sound-turbo"\), backfire: \$\("sound-backfire"\) \};$')

    def test_an_option_is_the_short_name_and_the_names_of_at_most_two_cars_and_a_count(self):
        self.assertIn('soundShortName(option.key) + " - " + soundCarNames(option.cars)', function_body("soundOptionText"))
        body = function_body("soundCarNames")
        self.assertIn("serverState && serverState.cars ? serverState.cars : []", body)
        self.assertIn("list.find((x) => x.id === id)", body)
        self.assertIn("c ? optionText(c) : id", body)
        self.assertIn('names.slice(0, 2).join(", ") + (names.length > 2 ? " +" + (names.length - 2) + " more" : "")', body)
        self.assertIn("c.display_name || c.label", function_body("optionText"))

    def test_the_short_name_strips_both_event_paths_and_shows_a_trailing_hash_number_as_a_variant(self):
        body = function_body("soundShortName")
        first, second = re.search(r'key\.replace\(/(.*?)/, ""\)\.match\(/(.*?)/\);', body).groups()
        self.assertIn("event:", first)
        self.assertIn("turbos", first)
        self.assertIn("backfires", first)
        self.assertIn('return m[1] + (m[2] ? " (variant " + m[2] + ")" : "");', body)

        def short(key):
            m = re.match(second, re.sub(first, "", key))
            return m.group(1) + (" (variant " + m.group(2) + ")" if m.group(2) else "")

        self.assertEqual(short("event:/parts/turbos/turbo_a"), "turbo_a")
        self.assertEqual(short("event:/parts/turbos/turbo_a#2"), "turbo_a (variant 2)")
        self.assertEqual(short("event:/parts/backfires/backfire_b#12"), "backfire_b (variant 12)")
        self.assertEqual(short("event:/parts/backfires/backfire_none"), "backfire_none")
        self.assertEqual(short("other/event"), "other/event")

    def test_the_sounds_are_read_with_the_selection_without_a_body_through_the_one_api_helper(self):
        body = function_body("loadSounds")
        self.assertIn('await api("/api/sounds", undefined, target);', body)
        self.assertIn("if (!tableLoaded) return;", body)
        self.assertIn("const seq = ++soundsSeq;", body)
        self.assertIn("if (seq !== soundsSeq || target !== selection) return;", body)
        self.assertEqual(body.count("if (seq !== soundsSeq || target !== selection) return;"), 2)
        self.assertIn("sounds = res;", body)
        self.assertIn("soundsError = e.message;", body)
        self.assertIn("renderSounds();", body)
        self.assertRegex(CODE, r"(?m)^let soundsSeq = 0;")
        self.assertEqual(len(re.findall(r"\bfetch\(", CODE)), 1)

    def test_the_sounds_are_loaded_wherever_the_garage_is(self):
        settings = function_body("loadSettings")
        self.assertIn("if (withPanels) loadCarPanels();", settings)
        self.assertLess(settings.index("tableLoaded = true;"), settings.index("loadCarPanels();"))
        self.assertRegex(function_body("loadCarPanels"), r"loadGarage\(\);\s*loadTurbo\(\);\s*loadSounds\(\);")
        self.assertIn("loadSounds();", function_body("loadCarPanels"))
        self.assertIn('if (tabs[i] === $("tab-car")) loadCarPanels();', function_body("selectTab"))
        controls = function_body("syncSounds")
        self.assertIn('if (soundsJobRunning && !running && !$("panel-car").hidden) loadSounds();', controls)
        self.assertIn("soundsJobRunning = running;", controls)
        self.assertIn("syncSounds();", function_body("renderButtons"))
        self.assertIn("soundsJobRunning = running;", function_body("loadCarPanels"))
        self.assertRegex(function_body("startJob"), r"await refresh\(\);\s*if \(serverState && !jobRunning\(\)\) loadCarPanels\(\);")
        self.assertRegex(function_body("submitDialog"), r"await refresh\(\);\s*if \(serverState && !jobRunning\(\)\) loadCarPanels\(\);")
        # Reset all reads the settings again, and that reads the garage, the kit and the sounds again; a donor choice reads the
        # settings again without them (the answer of the write carries the kit and the sounds)
        self.assertIn("await loadSettings();", function_body("resetAll"))
        self.assertEqual(re.findall(r"setTimeout\([^;]*[Ss]ound", CODE), [])
        self.assertEqual(re.findall(r"setInterval\(([^)]*)\)", CODE), ["pollLogStatus, LOG_POLL_MS"])

    def test_a_change_posts_the_slot_and_the_key_or_null_for_the_first_entry_through_the_shared_queue(self):
        self.assertIn('$("sounds").addEventListener("change", soundChanged);', CODE)
        body = function_body("soundChanged")
        self.assertIn("SOUND_SLOTS.find((s) => SOUND_SELECTS[s] === ev.target)", body)
        self.assertIn('const key = ev.target.value === "" ? null : ev.target.value;', body)
        self.assertIn("const target = selection;", body)
        self.assertIn("queue = queue.then(() => sendSoundSet(slot, key, target));", body)
        send = function_body("sendSoundSet")
        self.assertIn('await api("/api/sound_set", { slot: slot, key: key }, target);', send)
        self.assertIn("showSounds(target, res);", send)
        fields = set(re.findall(r"\b(\w+):", re.search(r'api\("/api/sound_set", (\{[^}]*\})', CODE).group(1)))
        self.assertEqual(fields, set(re.findall(r'body\.get\("(\w+)"\)', inspect.getsource(ts.api_sound_set))) - {"tune"})

    def test_reset_posts_sound_reset_without_a_slot_through_the_queue_and_is_off_unless_something_is_stored(self):
        self.assertIn('$("btn-sound-reset").addEventListener("click", resetSounds);', CODE)
        self.assertIn("queue = queue.then(() => sendSoundReset(target));", function_body("resetSounds"))
        reset = function_body("sendSoundReset")
        self.assertIn('await api("/api/sound_reset", {}, target);', reset)
        self.assertIn("showSounds(target, res);", reset)
        body = function_body("lockSounds")
        self.assertIn('if (!locked && soundsChosen() === 0 && !(sounds && sounds.missing.length)) why = "the car has its own sounds already";', body)
        self.assertIn('$("btn-sound-reset").disabled = why !== "";', body)
        self.assertIn('$("btn-sound-reset").title = why;', body)

    def test_the_server_answer_wins_and_a_failed_write_reads_the_sounds_again_and_keeps_its_message(self):
        show = function_body("showSounds")
        self.assertIn("if (target !== selection) return;", show)
        self.assertIn("soundsSeq += 1;", show)
        self.assertIn("sounds = answer;", show)
        self.assertIn("renderSounds();", show)
        failed = function_body("soundsFailed")
        self.assertLess(failed.index("await loadSounds();"), failed.index("soundsError = e.message;"))
        self.assertIn("renderSoundsLines();", failed)
        for name in ("sendSoundSet", "sendSoundReset"):
            with self.subTest(name):
                self.assertIn("await soundsFailed(target, e);", function_body(name))

    def test_the_missing_sounds_are_a_warning_line_and_the_error_line_is_the_alert_of_the_panel(self):
        body = function_body("renderSoundsLines")
        self.assertIn('"No longer available, Apply is refused until you change the sound or reset it: "', body)
        self.assertIn('missing.map((m) => m.slot + ": " + soundShortName(m.key)).join(", ")', body)
        self.assertIn("sounds ? sounds.missing : []", body)
        self.assertIn('$("sounds-missing").hidden = missing.length === 0;', body)
        self.assertIn('showText("sounds-error", soundsError);', body)

    def test_the_selects_and_the_reset_button_are_off_while_a_job_runs_or_without_a_base_car_or_an_answer(self):
        body = function_body("lockSounds")
        self.assertIn("let why = panelLockReason();", body)
        self.assertIn("SOUND_SELECTS[slot].disabled = locked || !sounds;", body)
        self.assertIn("SOUND_SELECTS[slot].title = why;", body)
        self.assertIn("lockSounds();", function_body("renderSounds"))
        self.assertIn("lockSounds();", function_body("syncSounds"))

    def test_the_focus_goes_back_to_the_changed_select_after_the_redraw(self):
        body = function_body("renderSounds")
        self.assertIn("SOUND_SLOTS.find((slot) => SOUND_SELECTS[slot] === document.activeElement)", body)
        self.assertIn("if (focused && !SOUND_SELECTS[focused].disabled) SOUND_SELECTS[focused].focus();", body)
        self.assertLess(body.index("lockSounds();"), body.index(".focus();"))
        self.assertNotIn("aria-live", "".join(function_body(n) for n in self.FUNCTIONS))

    def test_the_turbo_kit_answer_sets_the_sounds_and_a_hint_below_the_donor(self):
        self.assertIn('<p id="turbo-sound-link" class="msg" hidden></p>', TestTurboKit.PANEL)
        self.assertLess(TestTurboKit.PANEL.index('id="turbo-error"'), TestTurboKit.PANEL.index('id="turbo-sound-link"'))
        self.assertRegex(CODE, r"(?m)^let turboSoundLink = null;")
        send = function_body("sendTurboSet")
        self.assertIn("showTurbo(target, res.turbo);", send)
        self.assertIn("showTurboSound(target, res);", send)
        self.assertLess(send.index("showTurbo(target, res.turbo);"), send.index("showTurboSound(target, res);"))
        body = function_body("showTurboSound")
        self.assertIn("if (target !== selection) return;", body)
        self.assertIn("turboSoundLink = answer.sound_link || null;", body)
        self.assertIn("renderTurboLines();", body)
        self.assertIn("if (answer.sounds) showSounds(target, answer.sounds);", body)
        sent = quoted_words(ts.api_turbo_set, ts.turbo_sound_link)
        self.assertTrue({"sounds", "sound_link", "slot", "key", "error"} <= sent, sorted(sent))

    def test_the_hint_names_the_sound_or_says_why_it_could_not_follow_the_donor_and_nothing_for_no_link(self):
        body = function_body("turboSoundText")
        self.assertIn('if (!turboSoundLink) return "";', body)
        self.assertIn('"The sound could not follow the donor: " + turboSoundLink.error', body)
        self.assertIn('"Turbo sound set to " + soundShortName(turboSoundLink.key) + " (change it in Sounds)."', body)
        lines = function_body("renderTurboLines")
        self.assertIn('$("turbo-sound-link").textContent = turboSoundText();', lines)
        self.assertIn('$("turbo-sound-link").hidden = turboSoundLink === null;', lines)
        self.assertIn('$("turbo-sound-link").classList.toggle("warn", !!turboSoundLink && !!turboSoundLink.error);', lines)

    def test_the_hint_is_cleared_by_the_next_write_of_the_kit_and_a_donor_reset_leaves_the_sounds_alone(self):
        self.assertIn("turboSoundLink = null;", function_body("turboChanged"))
        self.assertLess(function_body("turboChanged").index("turboSoundLink = null;"), function_body("turboChanged").index("queue = queue.then"))
        reset = function_body("sendTurboReset")
        for name in ("showSounds", "showTurboSound", "loadSounds", "sounds"):
            with self.subTest(name):
                self.assertNotIn(name, reset)

    def test_the_server_routes_the_page_calls_exist_with_the_right_methods(self):
        self.assertIn("/api/sounds", ts.GET_ROUTES)
        for route in ("/api/sound_set", "/api/sound_reset"):
            self.assertIn(route, ts.POST_ROUTES)
        for route in ("/api/sounds", "/api/sound_set", "/api/sound_reset"):
            self.assertIn(route, called_paths())

    def test_the_page_reads_only_the_fields_of_the_answer_the_server_sends(self):
        sent = quoted_words(ts.tune.sound_view, ts.tune.sounds.collect_options) | set(re.findall(r"\b(\w+)=", inspect.getsource(ts.tune.sounds.collect_options)))
        read =set(re.findall(r"\b(?:sounds|view|option|m)\.(\w+)", "".join(function_body(n) for n in self.FUNCTIONS)))
        self.assertTrue({"slots", "missing", "own", "options", "selected", "key", "cars", "slot"} <= read, sorted(read))
        self.assertEqual(sorted(read - sent), [])

    def test_the_panel_reuses_the_garage_styles_and_adds_none(self):
        for cls in ("garage", "garage-body", "garage-help", "garage-row", "grouptoggle", "gname", "gcount", "chev", "msg", "warn", "err"):
            with self.subTest(cls):
                self.assertIn(cls, css_classes())
                self.assertIn(cls, used_classes() | DYNAMIC_CLASSES)
        self.assertEqual(set(re.findall(r'class="([^"]+)"', self.PANEL)),
                         {"panel garage", "grouptoggle", "chev", "gname", "gcount", "garage-body", "garage-help", "garage-row", "actions",
                          "msg err", "msg warn"})
        self.assertRegex(STYLE, r"\n\.dialog \.field select, \.garage select \{[^}]*max-width: 100%;")

    def test_the_text_of_the_panel_enters_the_page_as_text_and_the_markup_and_code_are_ascii(self):
        for name in self.FUNCTIONS + ("turboSoundText", "showTurboSound"):
            with self.subTest(name):
                self.assertNotRegex(function_body(name), r"\.html\b|innerHTML")
        for name in ("renderSoundsToggle", "renderSoundsLines"):
            with self.subTest(name):
                self.assertIn("textContent", function_body(name))
        self.assertIn('el("option", ""', function_body("renderSounds"))
        self.PANEL.encode("ascii")
        "".join(function_body(n) for n in self.FUNCTIONS).encode("ascii")


class TestLogging(unittest.TestCase):
    PANEL = MARKUP[MARKUP.index('id="panel-logging"'):]
    FUNCTIONS = ("fmtDuration", "logStatusText", "pollLogStatus", "stopLogPoll", "startLogPoll", "renderLogLines", "renderLogSessions",
                 "loadLogSessions", "logChannelCell", "buildLogRow", "buildLogTable", "buildLogGroup", "renderLogControls", "renderLog",
                 "loadLog", "showLog", "logFailed", "sendLogSet", "saveLog", "sendLogReset", "resetLog", "logChanged", "setAllLog", "logRateChanged",
                 "renderLoggerButtons", "beginLogRequest", "endLogRequest", "startLogger", "stopLogger", "copyText", "kiloBytes",
                 "showCopyMsg", "beginCopy", "endCopy", "copyAiCommand", "copyFileAsText", "copyFileOnPc", "onThisPc", "copySessionFile")

    @staticmethod
    def tag(ident):
        return re.search(r'<[a-z]+\b[^>]*\bid="%s"[^>]*>' % ident, MARKUP).group(0)

    def test_the_tab_is_the_third_button_and_the_panel_a_hidden_tabpanel_labelled_by_it_after_the_tyre_panel(self):
        tab = self.tag("tab-logging")
        for part in ('role="tab"', 'type="button"', 'aria-selected="false"', 'aria-controls="panel-logging"', 'tabindex="-1"'):
            self.assertIn(part, tab)
        self.assertLess(MARKUP.index('id="tab-tyres"'), MARKUP.index('id="tab-logging"'))
        self.assertLess(MARKUP.index('id="tab-logging"'), MARKUP.index('id="panel-car"'))
        panel = self.tag("panel-logging")
        self.assertIn('role="tabpanel"', panel)
        self.assertIn('aria-labelledby="tab-logging"', panel)
        self.assertRegex(panel, r"\bhidden>$")
        self.assertLess(MARKUP.index('id="panel-tyres"'), MARKUP.index('id="panel-logging"'))

    def test_the_tab_keys_walk_over_all_tabs_whatever_their_number(self):
        body = function_body("tabKey")
        self.assertIn("% tabs.length", body)
        self.assertNotRegex(body, r"% \d")
        self.assertIn('ev.key === "End") next = tabs.length - 1;', body)

    def test_selecting_the_tab_loads_the_choice_and_the_sessions_and_starts_the_poll_and_every_other_tab_stops_it(self):
        body = function_body("selectTab")
        self.assertRegex(body, r'if \(tabs\[i\] === \$\("tab-logging"\)\) \{\s*loadLog\(\);\s*loadLogSessions\(\);\s*startLogPoll\(\);\s*\} else \{\s*stopLogPoll\(\);\s*\}')

    def test_the_status_is_polled_by_one_interval_in_a_variable_that_is_cleared_before_a_new_one_and_when_the_tab_is_left(self):
        self.assertRegex(CODE, r"(?m)^const LOG_POLL_MS = 2000;")
        self.assertRegex(CODE, r"(?m)^let logPollTimer = null;")
        start = function_body("startLogPoll")
        self.assertIn("logPollTimer = setInterval(pollLogStatus, LOG_POLL_MS);", start)
        self.assertLess(start.index("stopLogPoll();"), start.index("setInterval("))
        self.assertLess(start.index("pollLogStatus();"), start.index("setInterval("))
        stop = function_body("stopLogPoll")
        self.assertIn("if (logPollTimer !== null) clearInterval(logPollTimer);", stop)
        self.assertIn("logPollTimer = null;", stop)
        self.assertEqual(re.findall(r"setInterval\(", CODE), ["setInterval("])
        self.assertEqual(len(re.findall(r"clearInterval\(", CODE)), 1)

    def test_the_four_routes_are_called_with_the_selection_and_the_two_reads_have_no_body(self):
        self.assertIn("/api/log_config", ts.GET_ROUTES)
        self.assertIn("/api/log_sessions", ts.GET_ROUTES)
        self.assertIn("/api/log_status", ts.GET_ROUTES)
        self.assertIn("/api/log_config_set", ts.POST_ROUTES)
        for route in ("/api/log_config", "/api/log_sessions", "/api/log_status"):
            with self.subTest(route):
                self.assertEqual(len(re.findall(r'await api\("%s", undefined, selection\);' % route, CODE)), 1)
        self.assertEqual(len(re.findall(r'await api\("/api/log_config_set", \{ ticked: ticked, rate_hz: rate \}, selection\);', CODE)), 1)
        self.assertIn('await api("/api/log_config", undefined, selection);', function_body("loadLog"))
        self.assertIn('await api("/api/log_sessions", undefined, selection);', function_body("loadLogSessions"))
        self.assertIn('await api("/api/log_status", undefined, selection);', function_body("pollLogStatus"))

    def test_the_saved_payload_has_the_two_keys_of_the_server_and_the_ticked_ids_in_the_order_of_the_groups(self):
        fields = set(re.findall(r"\b(\w+):", re.search(r'api\("/api/log_config_set", (\{[^}]*\})', CODE).group(1)))
        self.assertEqual(fields, {"ticked", "rate_hz"})
        self.assertEqual(fields, set(re.findall(r'body\.get\("(\w+)"\)', inspect.getsource(ts.api_log_config_set))))
        body = function_body("saveLog")
        self.assertIn("logData.groups.flatMap((g) => g.rows).filter((r) => r.tickable && r.ticked).map((r) => r.id)", body)
        self.assertIn("const rate = logData.rate_hz;", body)
        self.assertIn("logQueue = logQueue.then(() => sendLogSet(ticked, rate));", body)

    def test_a_save_is_answered_by_the_server_state_when_it_was_the_last_one_and_a_failed_save_reads_it_again(self):
        send = function_body("sendLogSet")
        self.assertRegex(send, r"logPending -= 1;\s*if \(logPending === 0\) showLog\(res\);")
        self.assertIn("await logFailed(e);", send)
        show = function_body("showLog")
        self.assertIn("logSeq += 1;", show)
        self.assertIn("logData = answer;", show)
        self.assertIn("renderLog();", show)
        failed = function_body("logFailed")
        self.assertLess(failed.index("await loadLog();"), failed.index("logError = e.message;"))
        self.assertIn("renderLogLines();", failed)
        load = function_body("loadLog")
        self.assertEqual(load.count("if (seq !== logSeq || logPending > 0) return;"), 2)
        self.assertIn("logData = res;", load)

    def test_a_change_never_saves_in_a_loop(self):
        self.assertIn('$("log-groups").addEventListener("change", logChanged);', CODE)
        self.assertIn('$("log-rate").addEventListener("change", logRateChanged);', CODE)
        self.assertEqual(len(re.findall(r"\bsaveLog\(\)", CODE)), 4)
        for name in ("renderLog", "renderLogControls", "buildLogGroup", "buildLogRow", "showLog", "loadLog", "sendLogSet", "logFailed"):
            with self.subTest(name):
                self.assertNotIn("saveLog(", function_body(name))
                self.assertNotIn("dispatchEvent", function_body(name))
        self.assertEqual(len(re.findall(r"\bapi\(\"/api/log_config_set\"", CODE)), 1)

    def test_the_heading_the_paragraph_and_the_status_line_are_in_the_panel(self):
        self.assertIn("<h2>Session logging</h2>", self.PANEL)
        self.assertIn("<p>Choose what the logger records. Press Start logger (or double-click start_logger.bat), then start the game: a "
                      "session file is written to the logs folder while the game runs. Your choices are saved at once and apply from the "
                      "next session.</p>", self.PANEL)
        self.assertIn('<p id="log-status"></p>', self.PANEL)
        self.assertLess(self.PANEL.index("<h2>Session logging</h2>"), self.PANEL.index('id="log-status"'))
        self.assertLess(self.PANEL.index('id="log-status"'), self.PANEL.index('id="log-rate"'))
        self.assertLess(self.PANEL.index('id="log-rate"'), self.PANEL.index('id="log-groups"'))
        self.assertLess(self.PANEL.index('id="log-groups"'), self.PANEL.index("<h2>Recent sessions</h2>"))
        self.assertNotIn("aria-live", self.PANEL)

    def test_the_status_line_says_not_running_waiting_or_logging_with_the_file_the_samples_and_the_time(self):
        body = function_body("logStatusText")
        self.assertIn('if (!s.running) return "Logger: not running";', body)
        self.assertIn('if (s.state === "waiting") return "Logger: waiting for the game";', body)
        self.assertIn('"Logger: logging " + s.file + ", " + s.samples + " samples, " + fmtDuration(s.seconds)', body)
        self.assertIn('$("log-status").textContent = logStatusText(s);', function_body("pollLogStatus"))

    def test_a_failing_poll_says_status_unavailable_in_the_line_and_shows_no_error(self):
        body = function_body("pollLogStatus")
        self.assertIn('$("log-status").textContent = "Logger: status unavailable";', body)
        self.assertNotIn("logError", body)
        self.assertNotIn("logSessionsError", body)
        self.assertNotIn("renderLogLines", body)
        self.assertNotIn("e.message", body)
        self.assertIn("if (seq !== logStatusSeq) return;", body)

    def test_a_new_file_name_in_the_status_reads_the_session_list_again(self):
        body = function_body("pollLogStatus")
        self.assertRegex(body, r"if \(s\.file !== logFile\) \{\s*logFile = s\.file;\s*loadLogSessions\(\);\s*\}")
        self.assertRegex(CODE, r"(?m)^let logFile = null;")

    def test_the_time_is_shown_as_minutes_and_two_digit_seconds_and_a_missing_one_as_a_dash(self):
        body = function_body("fmtDuration")
        self.assertIn('if (typeof seconds !== "number") return "-";', body)
        self.assertIn('Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0")', body)

    def test_the_toolbar_has_the_rate_select_and_the_two_buttons_for_all_rows(self):
        bar = re.search(r'<div class="toolbar">.*?</div>', self.PANEL, re.S).group(0)
        self.assertRegex(bar, r'<label class="selectrow">Sample rate\s*<select id="log-rate" aria-label="Sample rate" disabled></select>')
        self.assertIn('<button id="btn-log-all" type="button" disabled>Tick all</button>', bar)
        self.assertIn('<button id="btn-log-none" type="button" disabled>Clear all</button>', bar)
        self.assertIn('$("btn-log-all").addEventListener("click", () => setAllLog(true));', CODE)
        self.assertIn('$("btn-log-none").addEventListener("click", () => setAllLog(false));', CODE)
        body = function_body("setAllLog")
        self.assertIn("if (r.tickable) r.ticked = on;", body)
        self.assertEqual(body.count("saveLog();"), 1)

    def test_the_reset_button_follows_clear_all_in_the_toolbar_with_the_label_and_the_title_of_the_standard_set(self):
        bar = re.search(r'<div class="toolbar">.*?</div>', self.PANEL, re.S).group(0)
        self.assertIn('<button id="btn-log-reset" type="button" title="Back to the standard set: Speed, Engine rpm, Throttle and '
                      'Brake at 30 Hz" disabled>Reset to default</button>', bar)
        self.assertEqual(self.PANEL.count('id="btn-log-reset"'), 1)
        self.assertLess(bar.index('id="btn-log-all"'), bar.index('id="btn-log-none"'))
        self.assertLess(bar.index('id="btn-log-none"'), bar.index('id="btn-log-reset"'))
        self.assertIn('$("btn-log-reset").addEventListener("click", resetLog);', CODE)
        self.assertEqual(len(re.findall(r'\$\("btn-log-reset"\)\.addEventListener', CODE)), 1)

    def test_the_reset_title_names_the_default_rows_and_the_rate_of_the_server(self):
        chan = ts.logconf.load_channels()
        default = ts.logconf.default_config(chan)
        labels = [r["label"] for g in chan["extra_groups"] for r in g["rows"] if "%s.%s" % (g["id"], r["id"]) in default["ticked"]]
        self.assertEqual(labels, ["Speed", "Engine rpm", "Throttle", "Brake"])
        self.assertIn('title="Back to the standard set: %s and %s at %d Hz"' % (", ".join(labels[:-1]), labels[-1], default["rate_hz"]), self.PANEL)

    def test_the_reset_posts_an_empty_body_with_the_selection_through_the_queue_like_a_save(self):
        self.assertIn("/api/log_config_reset", ts.POST_ROUTES)
        self.assertEqual(len(re.findall(r'await api\("/api/log_config_reset", \{\}, selection\);', CODE)), 1)
        self.assertEqual(len(re.findall(r'\bapi\("/api/log_config_reset"', CODE)), 1)
        self.assertIn('await api("/api/log_config_reset", {}, selection);', function_body("sendLogReset"))
        body = function_body("resetLog")
        self.assertIn("if (!logData) return;", body)
        self.assertIn("logPending += 1;", body)
        self.assertIn("logQueue = logQueue.then(sendLogReset);", body)
        self.assertLess(body.index("logPending += 1;"), body.index("logQueue = logQueue.then(sendLogReset);"))
        self.assertIn("logSeq += 1;", body)
        self.assertNotIn("api(", body)
        self.assertNotIn("saveLog(", body)

    def test_the_answer_of_a_reset_is_shown_when_it_was_the_last_one_and_a_failed_reset_reads_the_choice_again_and_shows_the_message(self):
        send = function_body("sendLogReset")
        self.assertRegex(send, r"logPending -= 1;\s*if \(logPending === 0\) showLog\(res\);")
        self.assertRegex(send, r"catch \(e\) \{\s*logPending -= 1;\s*await logFailed\(e\);")
        self.assertEqual(send.count("logPending -= 1;"), 2)
        self.assertEqual(function_body("sendLogSet").count("logPending -= 1;"), 2)
        self.assertIn('logError = "";', function_body("resetLog"))
        self.assertLess(function_body("resetLog").index('logError = "";'), function_body("resetLog").index("renderLog();"))

    def test_the_reset_button_is_off_while_there_is_no_choice_like_the_other_two_buttons(self):
        body = function_body("renderLogControls")
        self.assertIn('$("btn-log-all").disabled = !logData;', body)
        self.assertIn('$("btn-log-none").disabled = !logData;', body)
        self.assertIn('$("btn-log-reset").disabled = !logData;', body)
        self.assertNotIn("logBusy", body)
        self.assertNotIn("btn-log-reset", function_body("renderLoggerButtons"))

    def test_the_rate_options_come_from_the_rates_of_the_server_and_are_shown_as_hz(self):
        body = function_body("renderLogControls")
        self.assertIn("for (const rate of logData ? logData.rates : []) {", body)
        self.assertIn('el("option", "", rate + " Hz")', body)
        self.assertIn("o.value = String(rate);", body)
        self.assertIn("if (logData) select.value = String(logData.rate_hz);", body)
        self.assertIn("select.disabled = !logData;", body)
        self.assertNotRegex(body, r"\b(?:30|60)\b")
        self.assertIn("logData.rate_hz = Number($(\"log-rate\").value);", function_body("logRateChanged"))
        self.assertEqual(ts.logconf.RATES, (30, 60))

    def test_a_group_is_a_group_row_with_a_cell_for_the_box_and_a_rowgroup_cell_with_the_toggle_the_name_and_the_count(self):
        body = function_body("buildLogGroup")
        self.assertIn('const tr = el("tr", "group");', body)
        self.assertIn('const tick = el("td");', body)
        self.assertIn("th.colSpan = 4;", body)
        self.assertIn('th.scope = "rowgroup";', body)
        self.assertIn('const btn = el("button", "grouptoggle");', body)
        self.assertIn('btn.type = "button";', body)
        self.assertIn('chev.setAttribute("aria-hidden", "true");', body)
        self.assertIn('btn.append(chev, el("span", "gname", g.name), el("span", "gcount", "(" + ticked + " of " + g.tickable + " ticked)"));', body)
        self.assertIn("th.appendChild(btn);", body)
        self.assertIn("tr.append(tick, th);", body)
        self.assertIn("return [tr, ...trs];", body)
        self.assertNotIn("details", body)
        self.assertNotIn("summary", body)
        self.assertNotIn("<details", MARKUP)
        self.assertNotRegex(self.PANEL, r"\bopen\b")
        self.assertRegex(CODE, r"(?m)^const logOpen = new Set\(\);")

    def test_the_group_box_sits_in_its_own_cell_and_never_inside_the_toggle_button(self):
        body = function_body("buildLogGroup")
        self.assertIn("tick.appendChild(input);", body)
        self.assertNotRegex(body, r"\b(?:btn|th)\.(?:append|appendChild)\([^;]*\binput\b")
        self.assertNotIn("btn.appendChild", body)
        self.assertLess(body.index("tick.appendChild(input);"), body.index("tr.append(tick, th);"))
        self.assertRegex(STYLE, r"tr\.group td \{[^}]*background: var\(--color-bg-elevated\);")

    def test_the_description_of_a_group_is_shown_under_the_toggle_only_while_the_group_is_open(self):
        body = function_body("buildLogGroup")
        self.assertIn("if (g.description) {", body)
        self.assertIn('desc = el("div", "gdesc", g.description);', body)
        self.assertIn('desc.id = "logdesc-" + n;', body)
        self.assertIn('btn.setAttribute("aria-describedby", desc.id);', body)
        self.assertIn("th.appendChild(desc);", body)
        self.assertLess(body.index("th.appendChild(btn);"), body.index("th.appendChild(desc);"))
        self.assertIn("if (desc) desc.hidden = !open;", body)
        self.assertNotIn("garage-help", body)

    def test_every_group_starts_closed_and_the_rows_of_a_closed_group_are_hidden_not_removed(self):
        body = function_body("buildLogGroup")
        self.assertRegex(CODE, r"(?m)^const logOpen = new Set\(\);")
        self.assertNotRegex(CODE, r"logOpen = new Set\([^)]")
        self.assertIn("const open = logOpen.has(g.id);", body)
        self.assertIn("for (const row of trs) row.hidden = !open;", body)
        self.assertNotIn("remove(", body)
        self.assertNotIn("open = true", body)
        self.assertRegex(body, r"\n  show\(\);\n  return \[tr, \.\.\.trs\];")

    def test_the_toggle_names_its_rows_and_says_whether_they_are_shown(self):
        body = function_body("buildLogGroup")
        self.assertIn('row.id = "logrow-" + n + "-" + i;', body)
        self.assertIn('btn.setAttribute("aria-controls", trs.map((row) => row.id).join(" "));', body)
        self.assertIn('btn.setAttribute("aria-expanded", open ? "true" : "false");', body)
        self.assertIn("const n = logData.groups.indexOf(g);", body)
        self.assertNotRegex(body, r"id = \"[^\"]*\" \+ g\.id")
        self.assertNotIn("aria-live", body)
        self.assertNotIn("role", body)

    def test_the_open_groups_are_remembered_by_id_and_a_click_applies_the_state_without_a_redraw(self):
        body = function_body("buildLogGroup")
        self.assertRegex(body, r'btn\.addEventListener\("click", \(\) => \{\s*if \(!logOpen\.delete\(g\.id\)\) logOpen\.add\(g\.id\);\s*show\(\);\s*\}\);')
        self.assertNotIn("renderLog", body)
        self.assertNotIn("logOpen.clear", CODE)
        self.assertNotRegex(body, r"\bexpanded\.")
        self.assertEqual(len(re.findall(r"expanded\.clear\(\)", CODE)), 2)

    def test_the_group_box_is_checked_when_all_rows_are_ticked_indeterminate_when_some_are_and_off_without_a_tickable_row(self):
        body = function_body("buildLogGroup")
        self.assertIn('const tickable = g.rows.filter((r) => r.tickable);', body)
        self.assertIn("const ticked = tickable.filter((r) => r.ticked).length;", body)
        self.assertIn('input.type = "checkbox";', body)
        self.assertIn("input.checked = tickable.length > 0 && ticked === tickable.length;", body)
        self.assertIn("input.indeterminate = ticked > 0 && ticked < tickable.length;", body)
        self.assertIn("input.disabled = tickable.length === 0;", body)
        self.assertIn('input.setAttribute("aria-label", "Tick all rows of " + g.name);', body)
        self.assertIn('logBoxes.push({ key: "group:" + g.id, input: input, rows: tickable });', body)

    def test_a_click_on_the_group_box_ticks_or_clears_all_its_tickable_rows_with_one_save_and_a_click_on_the_toggle_saves_nothing(self):
        body = function_body("logChanged")
        self.assertIn("for (const r of box.rows) r.ticked = box.input.checked;", body)
        self.assertEqual(body.count("saveLog();"), 1)
        group = function_body("buildLogGroup")
        self.assertIn("rows: tickable });", group)
        self.assertNotIn("saveLog", group)
        self.assertNotIn("dispatchEvent", group)
        self.assertEqual(len(re.findall(r'addEventListener\("change"', function_body("buildLogGroup"))), 0)
        self.assertIn('$("log-groups").addEventListener("change", logChanged);', CODE)
        self.assertEqual(len(re.findall(r"\bsaveLog\(\)", CODE)), 4)

    def test_a_change_of_a_box_sets_all_its_rows_in_the_data_and_saves_once(self):
        body = function_body("logChanged")
        self.assertIn("const box = logBoxes.find((b) => b.input === ev.target);", body)
        self.assertIn("if (!box) return;", body)
        self.assertIn("for (const r of box.rows) r.ticked = box.input.checked;", body)
        self.assertEqual(body.count("saveLog();"), 1)
        save = function_body("saveLog")
        self.assertLess(save.index("renderLog();"), save.index("logPending += 1;"))

    def test_a_row_is_a_table_row_with_a_checkbox_named_by_the_label_ticked_from_the_server_and_none_when_it_is_not_tickable(self):
        body = function_body("buildLogRow")
        self.assertIn('const tr = el("tr");', body)
        self.assertNotIn("garage-row", body)
        self.assertIn('if (!r.tickable) tr.classList.add("off");', body)
        self.assertIn('input.type = "checkbox";', body)
        self.assertIn("input.checked = r.ticked;", body)
        self.assertIn('input.setAttribute("aria-label", r.label);', body)
        self.assertNotIn("input.disabled", body)
        self.assertEqual(body.count('el("input")'), 1)
        self.assertIn('el("b", "", r.label)', body)
        self.assertIn('el("td", "unit", r.unit || "")', body)
        self.assertIn("tr.append(tick, name, el(\"td\", \"unit\", r.unit || \"\"), logChannelCell(r.once), logChannelCell(r.live));", body)

    def test_a_tickable_row_has_its_box_and_for_an_extra_row_its_description_under_the_label(self):
        body = function_body("buildLogRow")
        self.assertIn('logBoxes.push({ key: r.id, input: input, rows: [r] });', body)
        self.assertEqual(body.count("logBoxes"), 1)
        tickable, greyed = body.split("} else {", 1)
        self.assertLess(tickable.index("if (r.tickable) {"), tickable.index('const input = el("input");'))
        self.assertIn("logBoxes.push", tickable)
        self.assertNotIn("logBoxes", greyed)
        self.assertIn('if (r.description) name.appendChild(el("span", "id", r.description));', body)
        self.assertRegex(STYLE, r"\.name \.id \{[^}]*display: block;[^}]*color: var\(--color-text-muted\);")

    def test_a_greyed_row_has_a_dash_with_a_hidden_text_instead_of_a_box_and_its_badge_under_the_label_and_the_note_only_when_the_status_is_indirect(self):
        body = function_body("buildLogRow")
        self.assertIn('tick.append("-", el("span", "sr-only", "not tickable"));', body)
        self.assertIn('el("span", "badge", r.status === "indirect" ? "effect only" : "not published")', body)
        self.assertIn('if (r.status === "indirect" && r.note) line.append(" " + r.note);', body)
        self.assertNotIn("if (r.note)", body)
        self.assertLess(body.index('el("span", "badge"'), body.index("line.append(\" \" + r.note)"))
        self.assertEqual(body.count('el("span", "id"'), 2)

    def test_a_greyed_row_is_dimmed_and_italic_through_the_class_off(self):
        self.assertRegex(STYLE, r"tr\.off td \{[^}]*color: var\(--color-text-muted\);[^}]*font-style: italic;")
        self.assertNotIn(".garage-row.off", STYLE)
        self.assertIn('if (!r.tickable) tr.classList.add("off");', function_body("buildLogRow"))

    def test_the_once_and_live_cells_list_the_channel_names_comma_separated_and_a_dash_when_there_are_none(self):
        body = function_body("logChannelCell")
        self.assertIn('return el("td", "mono", names.length ? names.join(", ") : "-");', body)
        self.assertIn("logChannelCell(r.once), logChannelCell(r.live)", function_body("buildLogRow"))
        self.assertNotIn("once:", CODE)
        self.assertNotIn("logChannelText", CODE)

    def test_all_groups_are_rows_of_one_table_in_one_plain_wrapper_with_the_five_columns_in_order(self):
        body = function_body("buildLogTable")
        self.assertIn('const wrap = el("div", "tablewrap");', body)
        self.assertIn('const table = el("table");', body)
        self.assertEqual(body.count('el("table"'), 1)
        self.assertEqual(body.count('el("thead")'), 1)
        self.assertEqual(body.count('el("tbody")'), 1)
        self.assertEqual(body.count('el("div"'), 1)
        self.assertIn('for (const text of ["Tick", "Setting", "Unit", "Once", "Live"]) {', body)
        self.assertIn('th.scope = "col";', body)
        self.assertIn('if (text === "Tick") th.appendChild(el("span", "sr-only", text));', body)
        self.assertIn("else th.textContent = text;", body)
        self.assertIn('el("caption", "sr-only", "Logging channels")', body)
        self.assertIn('table.appendChild(el("thead")).appendChild(head);', body)
        self.assertIn("for (const g of logData.groups) body.append(...buildLogGroup(g));", body)
        self.assertIn("wrap.appendChild(table);", body)
        self.assertEqual(len(re.findall(r"\bbuildLogGroup\(", CODE)), 2)
        self.assertEqual(len(re.findall(r"\bbuildLogTable\(", CODE)), 2)
        self.assertIn("if (logData) box.appendChild(buildLogTable());", function_body("renderLog"))
        self.assertIn('<div id="log-groups"></div>', self.PANEL)
        self.assertEqual(self.PANEL.count("<table>"), 1)

    def test_the_log_table_has_the_colgroup_with_the_tick_column_and_the_widths_of_the_columns(self):
        body = function_body("buildLogTable")
        self.assertIn('cols.append(el("col", "c-tick"), el("col", "c-name"), el("col", "c-unit"), el("col", "c-once"), el("col"));', body)
        self.assertLess(body.index("table.appendChild(cols);"), body.index('table.appendChild(el("thead"))'))
        self.assertIn("col.c-tick { width: 44px; }", STYLE)
        widths = {"#panel-logging col.c-name": 32, "col.c-unit": 9, "col.c-once": 25}
        for selector, width in widths.items():
            self.assertIn("\n%s { width: %d%%; }" % (selector, width), STYLE)
        self.assertLess(sum(widths.values()), 100)
        self.assertRegex(STYLE, r"\ntable \{[^}]*table-layout: fixed;")
        self.assertRegex(STYLE, r"\ntd \{[^}]*overflow-wrap: anywhere;")
        self.assertNotIn("logtable", STYLE)
        self.assertNotRegex(STYLE, r"(?<!\.sessions )table[^{}]*\{[^}]*min-width")

    def test_the_unit_cells_and_header_of_the_log_table_never_break_inside_a_word_and_the_car_table_is_not_touched(self):
        self.assertIn("\n#log-groups thead th:nth-child(3), #log-groups td.unit { white-space: nowrap; }", STYLE)
        self.assertIn("\n.sessions td { overflow-wrap: normal; white-space: nowrap; }", STYLE)
        self.assertEqual(STYLE.count("white-space: nowrap"), 3)
        self.assertEqual(re.findall(r'"Unit"', function_body("buildLogTable")), ['"Unit"'])
        self.assertIn('["Tick", "Setting", "Unit", "Once", "Live"]', function_body("buildLogTable"))
        self.assertIn('el("td", "unit", r.unit || "")', function_body("buildLogRow"))
        self.assertNotRegex(STYLE, r"\n(?:td|thead th|\.unit)[^{}]*\{[^}]*white-space")

    def test_the_group_rows_of_the_log_table_are_bigger_and_stronger_than_their_rows_which_are_smaller_indented_and_guided(self):
        item = "#log-groups tbody tr:not(.group)"
        for rule in ("#log-groups tr.group th { font-size: 14px; }",
                     "#log-groups button.grouptoggle { padding-top: 10px; padding-bottom: 10px; }",
                     "#log-groups .gname { font-weight: 700; }",
                     "#log-groups .gcount, #log-groups .gdesc { font-size: 13px; }",
                     item + " { background: var(--color-bg); }",
                     item + " td { font-size: 13px; }",
                     "%s td.unit, %s td.mono { font-size: 12px; }" % (item, item),
                     item + " td:first-child { border-left: 3px solid var(--color-border); }",
                     item + " td.name { padding-left: 28px; }",
                     item + " td.name b { font-weight: 500; }"):
            with self.subTest(rule):
                self.assertEqual(STYLE.count("\n" + rule + "\n"), 1)
        media = re.search(r"@media \(max-width: 600px\) \{(.*?)\n\}", STYLE, re.S).group(1)
        self.assertIn("\n  " + item + " td.name { padding-left: 16px; }", media)
        self.assertLess(STYLE.index("\n" + item + " td.name { padding-left: 28px; }"), STYLE.index("@media (max-width: 600px)"))
        self.assertNotIn("td.name", re.search(r"@media \(max-width: 1000px\) \{(.*?)\n\}", STYLE, re.S).group(1))
        self.assertIn('el("td", "name")', function_body("buildLogRow"))
        self.assertIn('el("td", "unit", r.unit || "")', function_body("buildLogRow"))
        self.assertIn('el("td", "mono"', function_body("logChannelCell"))
        self.assertIn('el("tr", "group")', function_body("buildLogGroup"))

    def test_the_new_rules_of_the_log_table_are_all_scoped_to_it_and_the_shared_group_rules_of_the_car_table_keep_their_values(self):
        for rule in re.findall(r"\n(#log-groups[^{}]*)\{[^}]*\}", STYLE):
            with self.subTest(rule):
                for selector in rule.split(","):
                    self.assertTrue(selector.strip().startswith("#log-groups"), selector)
        self.assertRegex(STYLE, r"\ntr\.group th \{\s*padding: 0; text-align: left; font-size: 13px; letter-spacing: 0\.03em; text-transform: uppercase;")
        self.assertRegex(STYLE, r"\nbutton\.grouptoggle \{\s*display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 12px; border: 0;")
        self.assertIn("\n.gname { color: var(--color-text); }\n", STYLE)
        self.assertIn("\n.gcount { text-transform: none; letter-spacing: 0; }\n", STYLE)
        self.assertRegex(STYLE, r"\n\.gdesc \{\s*max-width: 80ch; margin: 0; padding: 0 12px 9px 35px;")
        self.assertIn("\ntr.off td { color: var(--color-text-muted); font-style: italic; }\n", STYLE)
        self.assertIn("\ntr.changed td { background: var(--color-accent-tint); }\n", STYLE)
        self.assertNotIn("font-weight", re.search(r"\n\.gname \{[^}]*\}", STYLE).group(0))

    def test_on_narrow_screens_the_unit_column_of_the_log_table_is_wider_and_the_others_give_way(self):
        media = re.search(r"@media \(max-width: 600px\) \{(.*?)\n\}", STYLE, re.S).group(1)
        self.assertEqual(sorted(re.findall(r"(\S+ )?(col\.c-\w+) \{ width: (\d+)%; \}", media)),
                         [("", "col.c-once", "22"), ("", "col.c-unit", "15"), ("#panel-logging ", "col.c-name", "28")])
        self.assertLess(28 + 15 + 22, 100)
        self.assertNotIn("c-tick", media)
        self.assertNotIn("c-live", media)
        self.assertLess(STYLE.index("col.c-unit { width: 9%; }"), STYLE.index("@media (max-width: 600px)"))
        self.assertLess(STYLE.index("#panel-logging col.c-name { width: 32%; }"), STYLE.index("@media (max-width: 600px)"))

    def test_the_header_of_the_log_table_is_the_sticky_one_of_the_car_table_and_only_the_sessions_wrapper_scrolls(self):
        self.assertRegex(STYLE, r"\nthead th \{\s*position: sticky; top: 0; z-index: 2;")
        self.assertEqual(STYLE.count("position: sticky"), 1)
        self.assertEqual(STYLE.count("overflow-x"), 1)
        self.assertIn("\n.sessions { overflow-x: auto; }", STYLE)
        self.assertNotRegex(STYLE, r"\.tablewrap[^{}]*\{[^}]*overflow(?!-wrap)")
        self.assertNotIn(".scroll", STYLE)
        self.assertNotIn("scroll", function_body("buildLogTable"))

    def test_the_groups_are_drawn_in_the_order_the_server_sends_nothing_is_sorted(self):
        for name in self.FUNCTIONS:
            with self.subTest(name):
                self.assertNotRegex(function_body(name), r"\.sort\(|\.reverse\(|localeCompare")
        self.assertIn("for (const g of logData.groups) body.append(...buildLogGroup(g));", function_body("buildLogTable"))
        self.assertIn("const trs = g.rows.map((r, i) => {", function_body("buildLogGroup"))
        self.assertEqual(ts.logconf.tree.__doc__.count("tickable rows come first"), 1)

    def test_the_start_and_stop_buttons_sit_in_the_first_panel_after_the_status_line_and_start_disabled(self):
        self.assertIn('<button id="btn-log-start" type="button" disabled>Start logger</button>', self.PANEL)
        self.assertIn('<button id="btn-log-stop" type="button" disabled>Stop logger</button>', self.PANEL)
        self.assertLess(self.PANEL.index('id="log-status"'), self.PANEL.index('id="btn-log-start"'))
        self.assertLess(self.PANEL.index('id="btn-log-start"'), self.PANEL.index('id="btn-log-stop"'))
        self.assertLess(self.PANEL.index('id="btn-log-stop"'), self.PANEL.index('id="log-rate"'))
        panel = self.PANEL[:self.PANEL.index("</section>")]
        self.assertIn('id="btn-log-stop"', panel)
        self.assertIn('$("btn-log-start").addEventListener("click", startLogger);', CODE)
        self.assertIn('$("btn-log-stop").addEventListener("click", stopLogger);', CODE)

    def test_start_is_on_while_the_logger_does_not_run_stop_while_it_runs_and_both_are_off_before_the_first_answer_and_while_busy(self):
        body = function_body("renderLoggerButtons")
        self.assertIn('$("btn-log-start").disabled = logRunning !== false || logBusy;', body)
        self.assertIn('$("btn-log-stop").disabled = logRunning !== true || logBusy;', body)
        self.assertRegex(CODE, r"(?m)^let logRunning = null;")
        self.assertRegex(CODE, r"(?m)^let logBusy = false;")
        poll = function_body("pollLogStatus")
        self.assertIn("logRunning = s.running;", poll)
        self.assertRegex(poll, r'textContent = "Logger: status unavailable";\s*logRunning = null;\s*renderLoggerButtons\(\);')
        self.assertLess(poll.index("logRunning = s.running;"), poll.index("renderLoggerButtons();", poll.index("logRunning = s.running;")))
        self.assertIn("running", ts.logconf.not_running())

    def test_start_and_stop_post_an_empty_body_with_the_selection_and_never_start_a_second_poll_loop(self):
        self.assertIn("/api/logger_start", ts.POST_ROUTES)
        self.assertIn("/api/logger_stop", ts.POST_ROUTES)
        self.assertEqual(len(re.findall(r'await api\("/api/logger_start", \{\}, selection\);', CODE)), 1)
        self.assertEqual(len(re.findall(r'await api\("/api/logger_stop", \{\}, selection\);', CODE)), 1)
        self.assertIn('await api("/api/logger_start", {}, selection);', function_body("startLogger"))
        self.assertIn('await api("/api/logger_stop", {}, selection);', function_body("stopLogger"))
        for name in ("startLogger", "stopLogger"):
            with self.subTest(name):
                body = function_body(name)
                self.assertLess(body.index("beginLogRequest();"), body.index("await api("))
                self.assertLess(body.index("await api("), body.index("await endLogRequest(message);"))
                self.assertNotIn("startLogPoll", body)
                self.assertNotIn("setInterval", body)
        self.assertEqual(re.findall(r"setInterval\(", CODE), ["setInterval("])

    def test_the_buttons_are_off_while_a_request_is_in_flight_and_the_status_is_read_once_at_once_afterwards(self):
        begin = function_body("beginLogRequest")
        self.assertLess(begin.index("logBusy = true;"), begin.index("renderLoggerButtons();"))
        end = function_body("endLogRequest")
        self.assertLess(end.index("logBusy = false;"), end.index("await pollLogStatus();"))
        self.assertLess(end.index("await pollLogStatus();"), end.rindex("renderLoggerButtons();"))
        self.assertEqual(end.count("pollLogStatus()"), 1)
        self.assertNotIn("startLogPoll", end)
        self.assertEqual(len(re.findall(r"\bpollLogStatus\(\)", CODE)), 4)

    def test_a_failed_or_refused_start_or_stop_shows_its_message_in_the_error_line_and_a_409_too(self):
        for name in ("startLogger", "stopLogger"):
            with self.subTest(name):
                body = function_body(name)
                self.assertIn('let message = "";', body)
                self.assertRegex(body, r"\} catch \(e\) \{\s*message = e\.message;\s*\}")
        end = function_body("endLogRequest")
        self.assertLess(end.index("logError = message;"), end.index("renderLogLines();"))
        self.assertLess(end.index("renderLogLines();"), end.index("await pollLogStatus();"))
        self.assertIn('logError = "";', function_body("beginLogRequest"))
        self.assertIn('const text = logError || logSessionsError;', function_body("renderLogLines"))
        self.assertIn('if (!res.ok) throw new Error((data && data.error) || ("HTTP " + res.status));', function_body("api"))
        self.assertNotIn("alert(", CODE)

    def test_the_status_words_of_the_page_are_the_ones_the_server_sends(self):
        self.assertEqual(ts.logconf.STATUSES, ("direct", "indirect", "none"))
        self.assertEqual(set(ts.logconf.not_running()), {"running", "state", "file", "samples", "started", "seconds"})
        self.assertEqual(ts.logconf.not_running()["state"], "not running")
        self.assertIn('"waiting"', inspect.getsource(ts.logconf.logger_status))

    def test_the_page_reads_only_fields_the_server_sends(self):
        group_sent = quoted_words(ts.logconf.tree, ts.log_config_json)
        status_sent = quoted_words(ts.logconf.not_running, ts.logconf.logger_status)
        session_sent = quoted_words(ts.logconf.session_file_info)
        self.assertEqual(sorted(set(re.findall(r"\blogData\.(\w+)", "".join(function_body(n) for n in self.FUNCTIONS))) - group_sent), [])
        for name, pattern, sent in (("buildLogGroup", r"\bg\.(\w+)", group_sent), ("buildLogRow", r"\br\.(\w+)", group_sent),
                                    ("logStatusText", r"\bs\.(\w+)", status_sent), ("pollLogStatus", r"\bs\.(\w+)", status_sent),
                                    ("renderLogSessions", r"\bs\.(\w+)", session_sent)):
            with self.subTest(name):
                read = set(re.findall(pattern, function_body(name)))
                self.assertTrue(read)
                self.assertEqual(sorted(read - sent), [])
        self.assertTrue({"file", "car", "track", "duration_s", "samples", "size", "modified"} <= set(re.findall(r"\bs\.(\w+)", function_body("renderLogSessions"))))
        self.assertTrue({"rate_hz", "rates", "groups"} <= set(re.findall(r"\blogData\.(\w+)", "".join(function_body(n) for n in self.FUNCTIONS))))

    def test_the_sessions_table_has_the_eight_columns_and_the_empty_text(self):
        table = re.search(r"<table>.*?</table>", self.PANEL, re.S).group(0)
        self.assertEqual(re.findall(r'<th scope="col">(.*?)</th>', table),
                         ["File", "Car", "Track", "Duration", "Samples", "Size", "Modified", "Copy for AI"])
        self.assertIn('<tbody id="log-sessions"></tbody>', table)
        self.assertIn('<caption class="sr-only">Recent session files</caption>', table)
        self.assertRegex(self.tag("log-sessions-empty"), r'class="empty" hidden>$')
        self.assertIn('<div id="log-sessions-empty" class="empty" hidden>No session files yet.</div>', self.PANEL)
        body = function_body("renderLogSessions")
        self.assertIn('s.car || "-", s.track || "-", fmtDuration(s.duration_s)', body)
        self.assertIn('s.samples === null ? "-" : String(s.samples)', body)
        self.assertIn("fmtBytes(s.size)", body)
        self.assertIn("new Date(s.modified * 1000).toLocaleString()", body)
        self.assertIn('$("log-sessions-empty").hidden = logSessions.length > 0;', body)
        self.assertIn("body.replaceChildren();", body)

    def test_a_failed_load_of_the_sessions_or_the_choice_shows_in_the_error_line_of_the_panel(self):
        self.assertIn('<p id="log-error" class="msg err" role="alert" hidden></p>', self.PANEL)
        self.assertEqual(CODE.count('setAttribute("role", "alert")'), 1)
        body = function_body("renderLogLines")
        self.assertIn('const text = logError || logSessionsError;', body)
        self.assertIn('showText("log-error", text);', body)
        self.assertIn("logSessionsError = e.message;", function_body("loadLogSessions"))
        self.assertIn("logError = e.message;", function_body("loadLog"))
        self.assertIn('logError = "";', function_body("saveLog"))

    def test_the_logging_tab_ignores_the_jobs_and_the_car_tuner(self):
        for name in self.FUNCTIONS:
            with self.subTest(name):
                body = function_body(name)
                self.assertNotRegex(body, r"\binfo\b|\bjob\b|tableLoaded|queue = queue|activeTab")
        for name in ("switchCar", "renderButtons", "refresh"):
            with self.subTest(name):
                self.assertNotRegex(function_body(name), r"\blog[A-Z]")

    def test_the_choice_is_kept_in_the_page_only_and_the_boxes_get_their_focus_back_after_the_redraw(self):
        self.assertEqual(CODE.count("localStorage"), 2)
        body = function_body("renderLog")
        self.assertIn("const focused = logBoxes.find((b) => b.input === document.activeElement);", body)
        self.assertIn("const back = focused && logBoxes.find((b) => b.key === focused.key);", body)
        self.assertIn("if (back) back.input.focus();", body)
        self.assertIn("box.replaceChildren();", body)
        self.assertIn("logBoxes = [];", body)

    def test_the_text_of_the_panel_enters_the_page_as_text_and_the_markup_and_code_are_ascii(self):
        for name in self.FUNCTIONS:
            with self.subTest(name):
                self.assertNotRegex(function_body(name), r"\.html\b|innerHTML")
        for name in ("renderLogLines", "renderLogControls"):
            with self.subTest(name):
                self.assertTrue("showText(" in function_body(name) or 'el("option"' in function_body(name))
        self.assertIn("$(id).textContent = text;", function_body("showText"))
        self.PANEL.encode("ascii")
        "".join(function_body(n) for n in self.FUNCTIONS).encode("ascii")

    def test_the_panel_reuses_the_styles_of_the_car_table_and_adds_the_ones_for_greyed_rows_the_box_cell_and_the_log_columns(self):
        for cls in ("panel", "toolbar", "selectrow", "msg", "err", "empty", "tablewrap", "sr-only", "garage-help", "gname",
                    "gcount", "gdesc", "grouptoggle", "chev", "group", "unit", "badge", "name", "id", "mono", "actions", "off",
                    "c-tick", "c-name", "c-unit", "c-once"):
            with self.subTest(cls):
                self.assertIn(cls, css_classes())
                self.assertIn(cls, used_classes() | DYNAMIC_CLASSES)
        self.assertEqual(set(re.findall(r'class="([^"]+)"', self.PANEL)),
                         {"panel", "actions", "toolbar", "selectrow", "msg err", "garage-help", "tablewrap sessions", "sr-only", "empty"})
        for cls in ("scroll", "logtable"):
            with self.subTest(cls):
                self.assertNotIn(cls, css_classes())
                self.assertNotIn(cls, used_classes())


class TestLoggingCopy(unittest.TestCase):
    """The AI command button, the Copy for AI column of the sessions table and the copy helper (string-level checks, no browser)."""
    PANEL = TestLogging.PANEL
    SECTION = PANEL[PANEL.index("<h2>Recent sessions</h2>"):]
    TOO_LARGE = "larger than 1 MB"

    def test_the_ai_command_button_and_the_status_paragraph_sit_above_the_table_in_the_recent_sessions_section(self):
        self.assertIn('<div class="actions">\n        <button id="btn-log-ai" type="button">Copy AI command</button>\n      </div>', self.SECTION)
        self.assertIn('<p id="log-copy-msg" class="garage-help" role="status" hidden></p>', self.SECTION)
        self.assertLess(self.SECTION.index("<h2>Recent sessions</h2>"), self.SECTION.index('id="btn-log-ai"'))
        self.assertLess(self.SECTION.index('id="btn-log-ai"'), self.SECTION.index('id="log-copy-msg"'))
        self.assertLess(self.SECTION.index('id="log-copy-msg"'), self.SECTION.index("<table>"))
        self.assertEqual(self.PANEL.count('id="btn-log-ai"'), 1)
        self.assertEqual(self.PANEL.count('id="log-copy-msg"'), 1)
        self.assertRegex(STYLE, r"#log-copy-msg \+ \.tablewrap \{[^}]*margin-top: \d+px;")
        self.assertIn('$("btn-log-ai").addEventListener("click", copyAiCommand);', CODE)

    def test_the_three_routes_are_called_with_the_selection_the_two_reads_without_a_body_and_the_copy_with_the_file_name(self):
        for route in ("/api/log_ai_command", "/api/log_file"):
            self.assertIn(route, ts.GET_ROUTES)
        self.assertIn("/api/log_file", ts.QUERY_ROUTES)
        self.assertIn("/api/log_copy", ts.POST_ROUTES)
        self.assertEqual(len(re.findall(r'await api\("/api/log_ai_command", undefined, selection\);', CODE)), 1)
        self.assertEqual(len(re.findall(r'await api\("/api/log_file\?file=" \+ encodeURIComponent\(name\), undefined, selection\);', CODE)), 1)
        self.assertEqual(len(re.findall(r'await api\("/api/log_copy", \{ file: name \}, selection\);', CODE)), 1)
        self.assertIn('await api("/api/log_ai_command", undefined, selection);', function_body("copyAiCommand"))
        self.assertIn('await api("/api/log_file?file=" + encodeURIComponent(name), undefined, selection);', function_body("copyFileAsText"))
        self.assertIn('await api("/api/log_copy", { file: name }, selection);', function_body("copyFileOnPc"))
        self.assertEqual(ts.QUERY_ROUTES.index("/api/log_file"), 1)
        self.assertIn('.get("file")', inspect.getsource(ts.api_log_file))
        self.assertIn('body.get("file")', inspect.getsource(ts.api_log_copy))

    def test_the_page_reads_only_fields_the_server_sends(self):
        self.assertEqual(set(re.findall(r"\bres\.(\w+)", function_body("copyAiCommand"))), {"text", "size"})
        self.assertEqual(set(re.findall(r"\bres\.(\w+)", function_body("copyFileAsText"))), {"text", "size"})
        self.assertTrue({"text", "size"} <= set(re.findall(r'"(\w+)"', inspect.getsource(ts.api_log_ai_command))))
        self.assertTrue({"text", "size", "file"} <= set(re.findall(r'"(\w+)"', inspect.getsource(ts.api_log_file))))

    def test_the_ai_command_button_fetches_the_text_copies_it_and_says_how_big_it_was(self):
        body = function_body("copyAiCommand")
        self.assertIn('const button = $("btn-log-ai");', body)
        self.assertLess(body.index("beginCopy(button);"), body.index("await api("))
        self.assertLess(body.index("await api("), body.index("await copyText(res.text);"))
        self.assertLess(body.index("await copyText(res.text);"), body.index('showCopyMsg("AI command copied ("'))
        self.assertIn('showCopyMsg("AI command copied (" + kiloBytes(res.size) + " KB)");', body)
        self.assertRegex(body, r"\} catch \(e\) \{\s*logError = e\.message;\s*\}\s*endCopy\(button\);")
        self.assertIn("return (size / 1024).toFixed(1);", function_body("kiloBytes"))

    def test_the_page_is_on_the_pc_for_127_0_0_1_localhost_and_ipv6_loopback_only(self):
        body = function_body("onThisPc")
        self.assertIn('return ["127.0.0.1", "localhost", "[::1]", "::1"].includes(window.location.hostname);', body)
        self.assertEqual(len(re.findall(r"\blocation\.", CODE)), 1)
        self.assertEqual(re.findall(r"\blocation\.(\w+)", HTML), ["hostname"])

    def test_on_the_pc_the_server_copies_the_file_and_the_text_is_the_fallback_that_says_so(self):
        decide = function_body("copySessionFile")
        self.assertIn("showCopyMsg(onThisPc() ? await copyFileOnPc(name) : await copyFileAsText(name));", decide)
        pc = function_body("copyFileOnPc")
        self.assertRegex(pc, r"try \{\s*await api\(\"/api/log_copy\", \{ file: name \}, selection\);\s*\} catch \(e\) \{")
        self.assertIn('return (await copyFileAsText(name)) + ". The file itself could not be copied: " + e.message;', pc)
        self.assertIn('throw new Error(e2.message + ". The file itself could not be copied either: " + e.message);', pc)
        self.assertRegex(pc, r"(?s)\} catch \(e\) \{\s*try \{\s*return \(await copyFileAsText\(name\)\).*?\} catch \(e2\) \{\s*throw new Error\(")
        self.assertIn('return name + " copied: paste it into the chat with Ctrl+V";', pc)
        self.assertLess(pc.index("catch (e)"), pc.index("copyFileAsText(name)"))
        self.assertNotIn("copyText(", pc)

    def test_from_another_device_the_text_of_the_file_is_copied_and_a_413_adds_the_hint_to_open_the_page_on_the_pc(self):
        body = function_body("copyFileAsText")
        self.assertIn('encodeURIComponent(name)', body)
        self.assertLess(body.index("await api("), body.index("await copyText(res.text);"))
        self.assertIn('return name + " copied as text (" + kiloBytes(res.size) + " KB)";', body)
        self.assertIn('const hint = !onThisPc() && e.message.includes("%s") ? " Open the page on the PC to copy the file itself." : "";' % self.TOO_LARGE, body)
        self.assertIn("throw new Error(e.message + hint);", body)
        self.assertIn("the file is larger than 1 MB: too large to copy as text", inspect.getsource(ts.api_log_file))
        self.assertIn(self.TOO_LARGE, inspect.getsource(ts.api_log_file))
        self.assertEqual(ts.LOG_FILE_MAX, 1048576)

    def test_a_failure_shows_in_the_error_line_a_success_in_the_status_paragraph_and_the_next_copy_clears_both(self):
        begin = function_body("beginCopy")
        self.assertIn('logError = "";', begin)
        self.assertIn('showCopyMsg("");', begin)
        self.assertIn("renderLogLines();", begin)
        show = function_body("showCopyMsg")
        self.assertIn('showText("log-copy-msg", text);', show)
        for name in ("copyAiCommand", "copySessionFile"):
            with self.subTest(name):
                body = function_body(name)
                self.assertIn("logError = e.message;", body)
                self.assertIn("showCopyMsg(", body)
                self.assertNotIn("setMsg(", body)
                self.assertNotIn("alert(", body)
        self.assertIn("renderLogLines();", function_body("endCopy"))

    def test_both_buttons_are_off_while_their_own_request_runs_and_on_again_afterwards_whatever_happened(self):
        self.assertIn("button.disabled = true;", function_body("beginCopy"))
        self.assertIn("button.disabled = false;", function_body("endCopy"))
        for name in ("copyAiCommand", "copySessionFile"):
            with self.subTest(name):
                body = function_body(name)
                self.assertLess(body.index("beginCopy(button);"), body.index("await "))
                self.assertGreater(body.index("endCopy(button);"), body.rindex("catch (e)"))
                self.assertEqual(body.count("endCopy(button);"), 1)
        self.assertIn("async function copySessionFile(name, button) {", CODE)

    def test_every_session_row_has_a_small_copy_file_button_in_the_last_cell(self):
        body = function_body("renderLogSessions")
        self.assertIn('const button = el("button", "small", "Copy file");', body)
        self.assertIn('button.type = "button";', body)
        self.assertIn('button.setAttribute("aria-label", "Copy file " + s.file);', body)
        self.assertIn('button.addEventListener("click", () => copySessionFile(s.file, button));', body)
        self.assertLess(body.index("for (const text of cells)"), body.index('el("button", "small", "Copy file")'))
        self.assertLess(body.index("copy.appendChild(button);"), body.index("tr.appendChild(copy);"))
        self.assertLess(body.index("tr.appendChild(copy);"), body.index("body.appendChild(tr);"))
        self.assertRegex(STYLE, r"button\.small \{[^}]*font-size: 12px;")

    def test_the_text_copy_uses_the_clipboard_api_on_a_secure_page_and_a_hidden_text_box_with_the_copy_command_otherwise(self):
        body = function_body("copyText")
        self.assertIn("if (window.isSecureContext && navigator.clipboard) {", body)
        self.assertIn("await navigator.clipboard.writeText(text);", body)
        self.assertLess(body.index("navigator.clipboard.writeText(text)"), body.index('el("textarea"'))
        self.assertIn('const area = el("textarea", "sr-only", text);', body)
        self.assertIn('area.setAttribute("readonly", "");', body)
        self.assertIn("document.body.appendChild(area);", body)
        self.assertIn("area.select();", body)
        self.assertIn('done = document.execCommand("copy");', body)
        self.assertLess(body.index('document.execCommand("copy")'), body.index("area.remove();"))
        self.assertLess(body.index("area.remove();"), body.index("if (!done) throw new Error("))
        self.assertEqual(body.count("area.remove();"), 1)
        self.assertNotIn("style", body)
        self.assertNotIn("innerHTML", body)

    def test_the_text_copy_falls_back_when_the_clipboard_api_rejects_and_throws_when_both_ways_fail(self):
        body = function_body("copyText")
        self.assertRegex(body, r"try \{\s*await navigator\.clipboard\.writeText\(text\);\s*return;\s*\} catch \(e\) \{")
        self.assertRegex(body, r"try \{\s*done = document\.execCommand\(\"copy\"\);\s*\} catch \(e\) \{\s*done = false;\s*\}")
        self.assertIn('if (!done) throw new Error("the text could not be copied to the clipboard");', body)
        self.assertEqual(len(re.findall(r"navigator\.clipboard", CODE)), 2)
        self.assertEqual(len(re.findall(r"execCommand", CODE)), 1)
        for name in ("copyAiCommand", "copyFileAsText"):
            self.assertIn("await copyText(res.text);", function_body(name))

    def test_the_copy_code_is_ascii_and_builds_no_html(self):
        code = "".join(function_body(n) for n in ("copyText", "kiloBytes", "showCopyMsg", "beginCopy", "endCopy", "copyAiCommand",
                                                   "copyFileAsText", "copyFileOnPc", "onThisPc", "copySessionFile", "renderLogSessions"))
        code.encode("ascii")
        self.assertNotRegex(code, r"\.html\b|innerHTML|insertAdjacentHTML")


if __name__ == "__main__":
    unittest.main()
