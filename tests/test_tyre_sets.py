"""Tests for tools/tyre_sets.py: sizes and labels, tyre entries, the index and its cache, local tyre files, compound names and the compound builder.

Synthetic data only: the game package is a small package packed by kspkg.cmd_pack in a scratch folder; no game data, no real work folder.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from support import Sandbox

import kspkg
import tyre_sets as ts

S = "content\\cars\\common_phsx\\tyres\\"
FILES = {
    "road\\road_235_35_19.tyre": b"road a", "road\\road_205_55_16.tyre": b"road b", "road\\road_235_35_18.tyre": b"road c",
    "supercar\\supercar_265_30_19.tyre": b"super", "racing_slicks\\slick_275_675_19.tyre": b"slick",
    "racing_slicks\\slick_27_5_14_5_17.tyre": b"slick 2", "f1_2025\\f1_2025_front.tyre": b"f1",
    "mystery\\odd.tyre": b"odd", "road\\readme.txt": b"no tyre"}


def road(name):
    return S + "road\\" + name + ".tyre"


def pack(dst, files):
    src = tempfile.mkdtemp()
    try:
        for rel, data in files.items():
            p = os.path.join(src, "content", "cars", "common_phsx", "tyres", *rel.split("\\"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        with contextlib.redirect_stdout(io.StringIO()):
            kspkg.cmd_pack(src, dst)
    finally:
        shutil.rmtree(src)


class TestSizes(unittest.TestCase):
    def test_usual_names_are_read(self):
        for stem, want in (("road_235_35_19", (235, 35, 19)), ("supercar_265_30_19", (265, 30, 19)),
                           ("supercar_335_30_21", (335, 30, 21)), ("hypercar_255_35_22", (255, 35, 22)),
                           ("eco_175_50_13", (175, 50, 13))):
            self.assertEqual(ts.parse_size(stem), dict(zip(("width", "aspect", "rim"), want)), stem)

    def test_other_names_have_no_size(self):
        for stem in ("slick_275_675_19", "slick_27_5_14_5_17", "f12004_soft_380_660_13", "vintage_550_14", "road_99_35_19",
                     "road_401_35_19", "road_235_19_19", "road_235_91_19", "road_235_35_9", "road_235_35_25", "road", "235_35_19",
                     "road_235_35_19_x"):
            self.assertIsNone(ts.parse_size(stem), stem)

    def test_size_label(self):
        self.assertEqual(ts.size_label(ts.parse_size("road_235_35_19")), "235/35 R19")
        self.assertEqual(ts.size_label(None, "slick_275_675_19"), "275 675 19")
        self.assertEqual(ts.size_label(None, "slick_200_600_17"), "200 600 17")
        self.assertEqual(ts.size_label(None, "wet_24_5_12_5_17"), "24 5 12 5 17")
        self.assertEqual(ts.size_label(None, "f1_2025_front"), "f1 2025 front")
        self.assertEqual(ts.size_label(None, "slick"), "slick")
        self.assertEqual(ts.size_label(None, "road_slick_1"), "road slick 1")


class TestEntries(unittest.TestCase):
    def test_entry_of_a_sized_tyre(self):
        t = ts.tyre_entry(S.replace("\\", "/") + "Supercar/supercar_265_30_19.tyre")
        self.assertEqual(t, {"path": S + "Supercar\\supercar_265_30_19.tyre", "type": "Supercar", "type_label": "Supercar",
                             "file": "supercar_265_30_19", "size": {"width": 265, "aspect": 30, "rim": 19},
                             "label": "Supercar 265/30 R19"})

    def test_entry_of_nested_type_and_unsized_tyre(self):
        t = ts.tyre_entry(S + "racing_slicks\\historic_formula\\hist_front.tyre")
        self.assertEqual((t["type"], t["type_label"], t["size"], t["label"]),
                         ("racing_slicks/historic_formula", "Historic formula slick", None, "Historic formula slick hist front"))

    def test_unknown_type_shows_its_folder_name(self):
        self.assertEqual(ts.tyre_entry(S + "mystery\\odd_one.tyre")["label"], "mystery odd one")

    def test_paths_that_are_no_shared_tyres_are_refused(self):
        for p in ("content\\cars\\ks_x\\data\\a.tyre", S + "road\\a.txt", "road\\a.tyre", S[:-1]):
            with self.assertRaises(ValueError, msg=p):
                ts.tyre_entry(p)

    def test_type_labels_and_order(self):
        self.assertEqual(list(ts.TYPE_ORDER), ["road", "eco", "supercar", "hypercar", "vintage", "racing_slicks",
                                               "racing_slicks/historic_formula", "racing_wet", "racing_wet/historic_formula_wet",
                                               "f1_2004", "f1_2025", "f1_2026"])
        self.assertEqual(ts.TYPE_LABELS["racing_wet/historic_formula_wet"], "Historic formula wet")
        self.assertEqual(ts.TYPE_LABELS["f1_2026"], "F1 2026")


class TestIndex(unittest.TestCase):
    def test_order_by_type_then_size_then_unsized_by_file(self):
        listing = [S + "f1_2025\\b.tyre", S + "road\\road_235_35_19.tyre", S + "mystery\\z.tyre", S + "racing_slicks\\slick_275_675_19.tyre",
                   S + "road\\road_205_55_16.tyre", S + "road\\road_235_35_18.tyre", S + "road\\zzz.tyre", S + "eco\\eco_175_50_13.tyre",
                   S + "road\\aaa.tyre", S + "f1_2004\\a.tyre"]
        self.assertEqual([t["path"][len(S):] for t in ts.game_index(listing)],
                         ["road\\road_205_55_16.tyre", "road\\road_235_35_18.tyre", "road\\road_235_35_19.tyre", "road\\aaa.tyre",
                          "road\\zzz.tyre", "eco\\eco_175_50_13.tyre", "racing_slicks\\slick_275_675_19.tyre", "f1_2004\\a.tyre",
                          "f1_2025\\b.tyre", "mystery\\z.tyre"])

    def test_duplicates_in_any_case_and_other_files_are_dropped(self):
        listing = [road("road_235_35_19"), (S + "ROAD\\road_235_35_19.tyre").replace("\\", "/"), S + "road", S + "road\\a.curve", "content\\cars\\x"]
        self.assertEqual([t["file"] for t in ts.game_index(listing)], ["road_235_35_19"])
        self.assertEqual(ts.game_index([]), [])


class TestReadIndex(Sandbox):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pkg = os.path.join(cls.tmp.name, "content.kspkg")
        pack(cls.pkg, FILES)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reads_the_tyres_of_the_package_table(self):
        files = [t["file"] for t in ts.read_index(self.pkg)]
        self.assertEqual(files, ["road_205_55_16", "road_235_35_18", "road_235_35_19", "supercar_265_30_19", "slick_275_675_19",
                                 "slick_27_5_14_5_17", "f1_2025_front", "odd"])

    def test_missing_package(self):
        with self.assertRaises(ValueError) as cm:
            ts.read_index(str(self.d / "none.kspkg"), str(self.d))
        self.assertIn("the game package", str(cm.exception))
        self.assertIn("was not found", str(cm.exception))

    def test_cache_is_written_and_used_while_the_stamp_matches(self):
        work = str(self.d / "work")
        first = ts.read_index(self.pkg, work)
        cache = os.path.join(work, "tyre_index.json")
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        st = os.stat(self.pkg)
        self.assertEqual((data["version"], data["stamp"], data["tyres"]), (1, [st.st_size, st.st_mtime_ns], first))
        data["tyres"] = data["tyres"][:2]
        self.write(cache, data)
        self.assertEqual(len(ts.read_index(self.pkg, work)), 2)

    def test_stale_stamp_rebuilds(self):
        work = str(self.d / "work")
        ts.read_index(self.pkg, work)
        cache = os.path.join(work, "tyre_index.json")
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        data["stamp"][1] += 1
        data["tyres"] = []
        self.write(cache, data)
        self.assertEqual(len(ts.read_index(self.pkg, work)), 8)
        with open(cache, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["tyres"]), 8)

    def test_damaged_cache_rebuilds(self):
        work = str(self.d / "work")
        cache = self.write(os.path.join(work, "tyre_index.json"), "{not json")
        self.assertEqual(len(ts.read_index(self.pkg, work)), 8)
        with open(cache, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["tyres"]), 8)
        self.write(cache, {"version": 1, "stamp": ts._stamp(self.pkg), "tyres": [{"path": "x"}]})
        self.assertEqual(len(ts.read_index(self.pkg, work)), 8)
        self.write(cache, {"version": 2, "stamp": ts._stamp(self.pkg), "tyres": []})
        self.assertEqual(len(ts.read_index(self.pkg, work)), 8)

    def test_unwritable_work_folder_is_ignored(self):
        blocker = self.write(str(self.d / "file"), "x")
        self.assertEqual(len(ts.read_index(self.pkg, os.path.join(blocker, "sub"))), 8)


class TestFindFile(Sandbox):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pkg = os.path.join(cls.tmp.name, "content.kspkg")
        pack(cls.pkg, FILES)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        super().setUp()
        self.work = str(self.d / "work")

    def test_extracted_car_copy_is_found_in_any_case(self):
        p = self.write(os.path.join(self.work, "ks_a", "base", "content", "cars", "common_phsx", "tyres", "road", "Road_235_35_19.tyre"), b"mine", True)
        self.assertEqual(ts.find_file(self.work, road("road_235_35_19"), self.pkg), p)
        self.assertFalse(os.path.exists(os.path.join(self.work, "tyre_files")))

    def test_file_is_extracted_once(self):
        p = ts.find_file(self.work, road("road_235_35_19").replace("\\", "/"), self.pkg)
        self.assertEqual(p, os.path.join(self.work, "tyre_files", "content", "cars", "common_phsx", "tyres", "road", "road_235_35_19.tyre"))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"road a")
        with open(p, "wb") as f:
            f.write(b"changed")
        self.assertEqual(ts.find_file(self.work, road("road_235_35_19"), str(self.d / "gone.kspkg")), p)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"changed")

    def test_path_traversal_is_rejected(self):
        for bad in (S + "..\\..\\evil.tyre", "..\\evil.tyre", "\\content\\a.tyre", "C:\\x\\a.tyre", "", S + "road\\..\\..\\a.tyre"):
            with self.assertRaises(ValueError, msg=bad):
                ts.find_file(self.work, bad, self.pkg)
        self.assertFalse(os.path.exists(os.path.join(self.work, "tyre_files")))

    def test_missing_everywhere(self):
        with self.assertRaises(ValueError) as cm:
            ts.find_file(self.work, road("road_999_99_99"), self.pkg)
        self.assertIn("not found", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            ts.find_file(self.work, road("road_235_35_19"), str(self.d / "gone.kspkg"))
        self.assertIn("was not found", str(cm.exception))


class TestHelpers(unittest.TestCase):
    def test_same_size(self):
        a, b, c = (ts.tyre_entry(road(n)) for n in ("road_235_35_19", "road_235_35_19", "road_205_55_16"))
        d, e = ts.tyre_entry(road("a")), ts.tyre_entry(road("a"))
        self.assertTrue(ts.same_size(a, b))
        self.assertFalse(ts.same_size(a, c))
        self.assertFalse(ts.same_size(d, e))
        self.assertFalse(ts.same_size(a, d))

    def test_unique_paths(self):
        self.assertEqual(ts.unique_paths(["A\\b.tyre", "c.tyre", "a/B.tyre", "C.TYRE", "d.tyre"]), ["A\\b.tyre", "c.tyre", "d.tyre"])
        self.assertEqual(ts.unique_paths([]), [])

    def test_compound_index(self):
        paths = [road("a"), road("b")]
        self.assertEqual(ts.compound_index(paths, (S + "ROAD\\b.tyre").replace("\\", "/")), 1)
        with self.assertRaises(ValueError):
            ts.compound_index(paths, road("c"))

    def test_limits(self):
        self.assertEqual(ts.limits_of({"front": ["a", "b", "c"], "rear": ["x"]}), {"front_max": 2, "rear_max": 0})


class TestNames(unittest.TestCase):
    def test_every_tuple_and_all_names_are_free_of_duplicates(self):
        for key, names in list(ts.COMPOUND_NAMES.items()) + [("fallback", ts.FALLBACK_NAMES), ("all", ts.ALL_NAMES)]:
            self.assertEqual(len(names), len(set(names)), key)
            self.assertTrue(all(n.startswith("TyreCompound_") for n in names), key)
        self.assertEqual(set(ts.COMPOUND_NAMES), set(ts.TYPE_ORDER))
        self.assertEqual(len(ts.ALL_NAMES), 70)
        for names in ts.COMPOUND_NAMES.values():
            self.assertTrue(set(names) <= set(ts.ALL_NAMES))

    def test_mapping(self):
        self.assertEqual(ts.COMPOUND_NAMES["road"][0], "TyreCompound_Road_Generic")
        self.assertEqual(ts.COMPOUND_NAMES["racing_slicks"][0], "TyreCompound_Racing_Generic_Slick")
        self.assertEqual(ts.COMPOUND_NAMES["racing_wet/historic_formula_wet"][0], "TyreCompound_Racing_Generic_Wet")
        self.assertEqual(ts.COMPOUND_NAMES["f1_2004"], ts.FALLBACK_NAMES)
        self.assertEqual(ts.COMPOUND_NAMES["vintage"][-1], "TyreCompound_Racing_Vintage_1980s")

    def test_free_name_order_and_exhaustion(self):
        self.assertEqual(ts.free_name("road", set()), "TyreCompound_Road_Generic")
        self.assertEqual(ts.free_name("road", {"TyreCompound_Road_Generic"}), "TyreCompound_Road_Toyo")
        self.assertEqual(ts.free_name("mystery", set()), "TyreCompound_Special_Generic")
        taken = set(ts.COMPOUND_NAMES["eco"])
        self.assertEqual(ts.free_name("eco", taken), ts.FALLBACK_NAMES[0])
        taken |= set(ts.FALLBACK_NAMES)
        self.assertEqual(ts.free_name("eco", taken), ts.ROAD_NAMES[0])
        self.assertEqual(ts.free_name("eco", set(ts.ALL_NAMES) - {ts.ALL_NAMES[-1]}), ts.ALL_NAMES[-1])
        with self.assertRaises(ValueError) as cm:
            ts.free_name("road", set(ts.ALL_NAMES))
        self.assertEqual(str(cm.exception), "no free tyre name left for this car")


def stock_entry(name, front, rear):
    return {"tyre_compound": name, "front_tyre_data_path": front, "rear_tyre_data_paths": rear}


class TestBuildCompounds(unittest.TestCase):
    A, B, C = road("road_a"), road("road_b"), road("road_c")
    R0, R1 = ts.ROAD_NAMES[0], ts.ROAD_NAMES[1]

    def test_equal_lists(self):
        out = ts.build_compounds([], [self.A, self.B], [self.A, self.B])
        self.assertEqual(out["physic"], [stock_entry(self.R0, self.A, self.A), stock_entry(self.R1, self.B, self.B)])
        self.assertEqual(out["graphic"], [{"tyre_compound": self.R0}, {"tyre_compound": self.R1}])
        self.assertEqual((out["front"], out["rear"]), ([self.A, self.B], [self.A, self.B]))

    def test_longer_front_repeats_the_first_rear(self):
        out = ts.build_compounds([], [self.A, self.B, self.C], [self.B])
        self.assertEqual([(p["front_tyre_data_path"], p["rear_tyre_data_paths"]) for p in out["physic"]],
                         [(self.A, self.B), (self.B, self.B), (self.C, self.B)])
        self.assertEqual((out["front"], out["rear"]), ([self.A, self.B, self.C], [self.B]))
        self.assertEqual(ts.limits_of(out), {"front_max": 2, "rear_max": 0})

    def test_longer_rear_repeats_the_first_front(self):
        out = ts.build_compounds([], [self.A], [self.B, self.C])
        self.assertEqual([(p["front_tyre_data_path"], p["rear_tyre_data_paths"]) for p in out["physic"]],
                         [(self.A, self.B), (self.A, self.C)])
        self.assertEqual(ts.limits_of(out), {"front_max": 0, "rear_max": 1})

    def test_empty_lists_are_refused(self):
        for f, r in (([], [self.A]), ([self.A], []), ([], [])):
            with self.assertRaises(ValueError):
                ts.build_compounds([], f, r)

    def test_stock_names_are_kept_for_the_same_pair_in_any_spelling(self):
        stock = [stock_entry("TyreCompound_Road_Michelin", self.A.upper().replace("\\", "/"), self.A),
                 stock_entry("TyreCompound_Road_Generic", self.B, self.B)]
        out = ts.build_compounds(stock, [self.C, self.A], [self.C, self.A])
        self.assertEqual([p["tyre_compound"] for p in out["physic"]], [self.R0, "TyreCompound_Road_Michelin"])

    def test_a_stock_pair_that_is_not_chosen_gives_up_its_name(self):
        stock = [stock_entry(self.R0, self.A, self.A), stock_entry(self.R1, self.B, self.B)]
        out = ts.build_compounds(stock, [self.C, self.B], [self.C, self.B])
        self.assertEqual([p["tyre_compound"] for p in out["physic"]], [self.R0, self.R1])
        out = ts.build_compounds(stock, [self.C], [self.C])
        self.assertEqual([p["tyre_compound"] for p in out["physic"]], [self.R0])

    def test_a_kept_stock_name_is_not_taken_by_an_earlier_entry(self):
        stock = [stock_entry(self.R0, self.B, self.B)]
        out = ts.build_compounds(stock, [self.A, self.B], [self.A, self.B])
        self.assertEqual([p["tyre_compound"] for p in out["physic"]], [self.R1, self.R0])

    def test_names_are_unique_across_types(self):
        fronts = [road("a"), S + "supercar\\s.tyre", S + "racing_slicks\\k.tyre", S + "racing_wet\\w.tyre", S + "f1_2025\\f.tyre",
                  S + "f1_2026\\g.tyre", S + "vintage\\v.tyre", S + "unknown\\u.tyre"]
        names = [p["tyre_compound"] for p in ts.build_compounds([], fronts, fronts)["physic"]]
        self.assertEqual(names, [ts.ROAD_NAMES[0], ts.SUPERCAR_NAMES[0], ts.SLICK_NAMES[0], ts.WET_NAMES[0],
                                 ts.FALLBACK_NAMES[0], ts.FALLBACK_NAMES[1], ts.VINTAGE_NAMES[0], ts.FALLBACK_NAMES[2]])
        many = [road("t%d" % i) for i in range(12)]
        names = [p["tyre_compound"] for p in ts.build_compounds([], many, many)["physic"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[:9], list(ts.ROAD_NAMES))
        self.assertEqual(names[9:], list(ts.FALLBACK_NAMES[:3]))

    def test_own_tyres_use_the_given_type_or_road(self):
        own, slick = "own\\mine.tyre", "own\\slick.tyre"
        out = ts.build_compounds([], [own, slick, road("a")], [own, slick, road("a")], {slick.upper(): "racing_slicks"})
        self.assertEqual([p["tyre_compound"] for p in out["physic"]], [ts.ROAD_NAMES[0], ts.SLICK_NAMES[0], ts.ROAD_NAMES[1]])

    def test_stock_rear_as_a_list_of_one_counts(self):
        stock = [{"tyre_compound": "TyreCompound_Road_Avon", "front_tyre_data_path": self.A, "rear_tyre_data_paths": [self.A]}]
        out = ts.build_compounds(stock, [self.A], [self.A])
        self.assertEqual(out["physic"][0]["tyre_compound"], "TyreCompound_Road_Avon")


if __name__ == "__main__":
    unittest.main()
