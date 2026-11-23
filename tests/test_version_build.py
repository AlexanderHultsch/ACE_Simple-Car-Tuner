"""Tests for the versions of a modded car in the build of tools/tune.py: apply builds each version of the tune into its own temporary folder and merges its own files into the package as a further mechanical preset (build_state, build_versions, merge_version and the helpers below them), and list_versions naming a version with a damaged meta.json by its id.

No game data and no schemas: the car is synthetic (support.FakeCar replaces tune.load_msg / save_msg with in-memory messages, a save also writes the JSON of the message into the file so that files that differ differ in their bytes); clone_car.build and kspkg.cmd_pack are stubbed.
"""
import json
import os
import shutil
import unittest

from support import FakeCar, Sandbox, backfire, engine, mini_catalogue, mini_setting, turbo

import clone_car
import kspkg
import tune

REAL_RENAME = os.rename
CAR_NOTE = "note: car file: data/x.car renamed to data/CarData.car (the paint shop of a mod car expects that name)"
CAR = "content\\cars\\ax_x\\"
PRESET = CAR + "presets\\p.mechanicalcarpreset"
THUMBS = ["generated/thumbnails/ax_x-p-vis.texture", "generated/thumbnails/ax_x-p-vis.texturemips"]
V_THUMBS = ["generated/thumbnails/ax_x-p_v01-vis.texture", "generated/thumbnails/ax_x-p_v01-vis.texturemips"]


def cat():
    return mini_catalogue(
        mini_setting("name_suffix", kind="meta", type="string", default="MY", handler="name_suffix"),
        mini_setting("variant_name", kind="meta", type="string", default_template="{stock_variant_name}", handler="variant_name"),
        mini_setting("limiter", type="int", targets=[("@engine", "limiter"), ("@car", "engine.limiter", True)]),
        mini_setting("mass", targets=[("@car", "general.totalMass")]))


class World(Sandbox):
    """ks_x with a car file (engine, setup, mass), engine, setup, power curve, the preset p, its carfinalstate for the visual preset vis, the
    thumbnails of that pair and an actor that lists the preset; apply with clone_car.build and kspkg.cmd_pack stubbed."""

    def setUp(self):
        super().setUp()
        self.work = str(self.d / "work")
        data = {"default": "ks_x", "cars": [{"id": "ks_x", "label": "Car X"}]}
        self.patch(tune, "load_cars", lambda path=None: data)
        self.cat = cat()
        self.patch(tune, "load_catalogue", lambda path=None: self.cat)
        self.x = x = FakeCar(self.work, "ks_x").install(self)
        gp = x.game_path
        x.add("data/x.car", {"engine_path": gp("data/engine.carengine"), "stock_setup": gp("data/setup.carsetup"),
                             "engine": {"limiter": 7000}, "general": {"totalMass": 1400.0}})
        x.add("data/engine.carengine", {"limiter": 7000, "minimum": 800, "powerCurve": gp("data/power.curve")})
        x.add("data/setup.carsetup", {"alignments": [{"camber": -1.5}]})
        x.add("data/power.curve", {"points": [{"value": 1.0}]})
        x.add("presets/p.mechanicalcarpreset", {"brand": "Brand", "description": "Name Preset Base", "note": "Standard", "is_oem": True})
        x.add("presets/ks_x_p_vis.carfinalstate", {"car_data": gp("data/x.car"), "actor_data": gp("ks_x.actor"),
                                                   "body": {"path": gp("presets/p.mechanicalcarpreset"), "design": gp("presets/vis.visualcarpreset")}})
        x.add("presets/vis.visualcarpreset", {"brand": "Brand"})
        x.add("ks_x.actor", self.actor())
        x.add("generated/thumbnails/ks_x-p-vis.texture")
        x.add("generated/thumbnails/ks_x-p-vis.texturemips")
        self.write(tune.stock_info_path(self.work, "ks_x"), {"car_id": "ks_x", "display_name": "Car X", "brand": "Brand", "year": 1999,
                                                              "property_1": "P1", "property_2": "P2", "property_3": "P3", "variant_name": "Base"})
        self.calls, self.hook = [], None
        self.patch(clone_car, "build", self.build)
        self.patch(kspkg, "cmd_pack", self.pack)
        self.patch(tune, "ensure_stock_loc", lambda work, game=None: "present")
        self.patch(os, "rename", self.rename)
        stub = tune.save_msg

        def save_and_write(path, name, obj):
            stub(path, name, obj)
            with open(kspkg.long_path(path), "wb") as f:
                f.write(json.dumps(obj, sort_keys=True).encode())
        self.patch(tune, "save_msg", save_and_write)
        self.game = os.path.join(self.work, "no_game.kspkg")

    def actor(self, *entries):
        return {"car": {"audio_events": list(entries), "customization": {"mechanical_car_presets": [self.x.game_path("presets/p.mechanicalcarpreset")]}}}

    def rename(self, src, dst):
        old, new = self.x.key(src), self.x.key(dst)
        moved = [k for k in self.x.store if k == old or k.startswith(old + os.sep)]
        REAL_RENAME(src, dst)
        self.x.store.update({new + k[len(old):]: self.x.store.pop(k) for k in moved})

    def build(self, car_dir, new_id, out_dir, name, year, brand, variant, stock_loc, props, pack=True):
        self.calls.append(("build", os.path.basename(out_dir)))
        root = self.x.clone_into(out_dir, new_id)
        if self.hook:
            self.hook(root)
        return ["note: from build"]

    def pack(self, indir, pkg):
        self.calls.append(("pack", os.path.basename(indir)))
        with open(pkg, "wb") as f:
            f.write(b"PKG-NEW")

    def version(self, name, state):
        """A version of the default tune with exactly this state."""
        v = tune.add_version(self.work, "ks_x", name)
        tune.save_version_state(self.work, "ks_x", state, v)
        return v

    def apply(self, state=None):
        if state is not None:
            tune.save_state(self.work, "ks_x", state)
        return tune.apply(self.work, "ks_x", catalogue=self.cat, game=self.game, install=False)

    def root(self, res):
        return os.path.join(res["build_dir"], "content", "cars", res["new_id"])

    def built(self, res, rel):
        return self.x.store[self.x.key(os.path.join(self.root(res), *rel.split("/")))]

    def tree(self, res):
        root = self.root(res)
        return sorted(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/") for dp, _, names in os.walk(root) for n in names)

    def snapshot(self, res):
        root = self.x.key(self.root(res))
        return {k[len(root):]: json.dumps(v, sort_keys=True) for k, v in self.x.store.items() if k.startswith(root + os.sep)}


class TestAVersionWithValues(World):
    def setUp(self):
        super().setUp()
        self.version("Grip", {"limiter": 8000, "mass": 1800})
        self.res = self.apply({})

    def test_the_package_has_the_version_copy_of_the_car_file_pointing_at_the_version_engine(self):
        res = self.res
        car = self.built(res, "data/CarData_v01.car")
        self.assertEqual(car["general"]["totalMass"], 1800.0)
        self.assertEqual(car["engine"]["limiter"], 8000)
        self.assertEqual(car["engine_path"], CAR + "data\\engine_v01.carengine")
        self.assertEqual(car["stock_setup"], CAR + "data\\setup_v01.carsetup")
        engine_copy = self.built(res, "data/engine_v01.carengine")
        self.assertEqual((engine_copy["limiter"], engine_copy["minimum"], engine_copy["powerCurve"]), (8000, 800, CAR + "data\\power_v01.curve"))

    def test_the_files_of_the_base_are_unchanged(self):
        res = self.res
        car = self.built(res, "data/CarData.car")
        self.assertEqual((car["general"]["totalMass"], car["engine"]["limiter"], car["engine_path"]), (1400.0, 7000, CAR + "data\\engine.carengine"))
        self.assertEqual(self.built(res, "data/engine.carengine")["limiter"], 7000)
        self.assertEqual(self.built(res, "presets/p.mechanicalcarpreset"),
                         {"brand": "Brand", "description": "Name Preset Base", "note": "Standard", "is_oem": True})
        final = self.built(res, "presets/ax_x_p_vis.carfinalstate")
        self.assertEqual((final["car_data"], final["body"]["path"]), (CAR + "data\\CarData.car", PRESET))

    def test_the_version_preset_has_the_name_of_the_version(self):
        self.assertEqual(self.built(self.res, "presets/p_v01.mechanicalcarpreset"),
                         {"brand": "Brand", "description": "Name Preset Grip", "note": "Grip", "is_oem": False})

    def test_the_version_carfinalstate_is_named_after_the_version_preset_and_points_at_the_version_files(self):
        final = self.built(self.res, "presets/ax_x_p_v01_vis.carfinalstate")
        self.assertEqual(final["car_data"], CAR + "data\\CarData_v01.car")
        self.assertEqual(final["body"], {"path": CAR + "presets\\p_v01.mechanicalcarpreset", "design": CAR + "presets\\vis.visualcarpreset"})
        self.assertEqual(final["actor_data"], CAR + "ax_x.actor")

    def test_the_actor_lists_the_version_preset_after_the_base_preset(self):
        self.assertEqual(self.built(self.res, "ax_x.actor")["car"]["customization"]["mechanical_car_presets"],
                         [PRESET, CAR + "presets\\p_v01.mechanicalcarpreset"])

    def test_the_thumbnails_of_the_base_are_copied_for_the_version(self):
        tree = self.tree(self.res)
        for name in THUMBS + V_THUMBS:
            self.assertIn(name, tree)

    def test_the_version_has_its_own_copy_of_every_data_file_and_nothing_else_is_added(self):
        own = ["data/CarData_v01.car", "data/engine_v01.carengine", "data/power_v01.curve", "data/setup_v01.carsetup",
               "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset"]
        base = sorted(set(self.tree(self.res)) - set(own) - set(V_THUMBS))
        self.assertEqual(base, ["ax_x.actor", "data/CarData.car", "data/engine.carengine", "data/power.curve", "data/setup.carsetup", *THUMBS,
                                "presets/ax_x_p_vis.carfinalstate", "presets/p.mechanicalcarpreset", "presets/vis.visualcarpreset"])
        self.assertTrue(set(own + V_THUMBS) <= set(self.tree(self.res)))

    def test_the_result_lists_the_version_and_one_note_tells_its_files(self):
        res = self.res
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Grip", "files": 6, "locked": False, "changes": {
            "since": None, "settings": [{"id": "limiter", "from": 7000, "to": 8000}, {"id": "mass", "from": 1400.0, "to": 1800.0}], "extras": [], "total": 2}}])
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE, "note: version v01 (Grip): 6 files of its own"])

    def test_the_build_record_and_the_changes_are_those_of_the_base(self):
        self.assertEqual(self.res["applied"], [])
        self.assertEqual(self.res["changes"], {"since": None, "settings": [], "extras": [], "total": 0})
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["settings"], {})

    def test_the_temporary_folder_of_the_version_is_gone_and_only_one_package_is_packed(self):
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x"])
        self.assertEqual([c for c in self.calls if c[0] == "pack"], [("pack", "ax_x.partial")])
        self.assertIn(("build", "ax_x_v01.partial"), self.calls)


class TestAVersionThatChangesNothing(World):
    def test_it_gets_its_own_copy_of_every_data_file_the_preset_and_the_finalstate(self):
        plain = set(self.tree(self.apply({})))
        self.version("Same", {})
        res = self.apply({})
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Same", "files": 6, "locked": False,
                                            "changes": {"since": None, "settings": [], "extras": [], "total": 0}}])
        self.assertEqual(sorted(set(self.tree(res)) - plain),
                         sorted(["data/CarData_v01.car", "data/engine_v01.carengine", "data/power_v01.curve", "data/setup_v01.carsetup",
                                 "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset"] + V_THUMBS))
        car = self.built(res, "data/CarData_v01.car")
        self.assertEqual((car["engine_path"], car["general"]["totalMass"]), (CAR + "data\\engine_v01.carengine", 1400.0))
        self.assertEqual(self.built(res, "presets/p_v01.mechanicalcarpreset")["note"], "Same")


class TestSeveralVersions(World):
    def test_each_version_has_its_own_names_and_the_actor_lists_them_in_order(self):
        self.version("Grip", {"limiter": 8000})
        self.version("Heavy", {"mass": 1800})
        res = self.apply({})
        self.assertEqual(res["versions"], [
            {"id": "v01", "name": "Grip", "files": 6, "locked": False, "changes": {"since": None, "settings": [{"id": "limiter", "from": 7000, "to": 8000}], "extras": [], "total": 1}},
            {"id": "v02", "name": "Heavy", "files": 6, "locked": False, "changes": {"since": None, "settings": [{"id": "mass", "from": 1400.0, "to": 1800.0}], "extras": [], "total": 1}}])
        self.assertEqual(res["notes"][-2:], ["note: version v01 (Grip): 6 files of its own", "note: version v02 (Heavy): 6 files of its own"])
        self.assertEqual(self.built(res, "data/CarData_v01.car")["engine_path"], CAR + "data\\engine_v01.carengine")
        self.assertEqual(self.built(res, "data/CarData_v01.car")["general"]["totalMass"], 1400.0)
        self.assertEqual(self.built(res, "data/CarData_v02.car")["engine_path"], CAR + "data\\engine_v02.carengine")
        self.assertEqual(self.built(res, "data/CarData_v02.car")["general"]["totalMass"], 1800.0)
        self.assertEqual(self.built(res, "data/engine_v02.carengine")["limiter"], 7000)
        self.assertEqual(self.built(res, "presets/ax_x_p_v02_vis.carfinalstate")["car_data"], CAR + "data\\CarData_v02.car")
        self.assertEqual(self.built(res, "presets/ax_x_p_v02_vis.carfinalstate")["body"]["path"], CAR + "presets\\p_v02.mechanicalcarpreset")
        self.assertEqual(self.built(res, "ax_x.actor")["car"]["customization"]["mechanical_car_presets"],
                         [PRESET, CAR + "presets\\p_v01.mechanicalcarpreset", CAR + "presets\\p_v02.mechanicalcarpreset"])
        self.assertEqual(self.built(res, "presets/p_v02.mechanicalcarpreset")["note"], "Heavy")
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x"])

    def test_the_versions_are_built_by_id(self):
        self.version("B", {})
        self.version("A", {})
        self.apply({})
        self.assertEqual([c[1] for c in self.calls if c[0] == "build"], ["ax_x.partial", "ax_x_v01.partial", "ax_x_v02.partial"])


class TestVersionPresetText(unittest.TestCase):
    def test_a_trailing_base_is_replaced_and_any_other_description_gets_the_name_after_it(self):
        self.assertEqual(tune.version_description("M3 Preset Base", "Grip"), "M3 Preset Grip")
        self.assertEqual(tune.version_description("Base", "Grip"), "Grip")
        self.assertEqual(tune.version_description("M3 Standard", "Grip"), "M3 Standard Grip")
        self.assertEqual(tune.version_description("M3 Database", "Grip"), "M3 Database Grip")
        self.assertEqual(tune.version_description("", "Grip"), "Grip")

    def test_the_copy_of_a_file_has_the_version_before_the_extension(self):
        self.assertEqual(tune.version_rel("data/CarData.car", "v01"), "data/CarData_v01.car")
        self.assertEqual(tune.version_rel("a.b/engine.x.carengine", "v02"), "a.b/engine.x_v02.carengine")
        self.assertEqual(tune.version_rel("noext", "v03"), "noext_v03")


class TestVersionSounds(World):
    def setUp(self):
        super().setUp()
        self.x.store[self.x.key(os.path.join(self.x.car_root, "ks_x.actor"))] = self.actor(engine(), turbo("turbo_none"), backfire("backfire_a"))
        donor = FakeCar(self.work, "ks_a")
        donor.store = self.x.store
        donor.add("ks_a.actor", {"car": {"audio_events": [engine(), turbo("turbo_rx7")]}})
        self.addCleanup(tune._actor_options.clear)

    SOUND = ["presets/parts/physics/ax_x_v01_sound.carpart", "presets/parts/physics/ax_x_v01_sound.compatiblepart",
             "data/parts/ax_x_v01_engine.tuningpart"]
    COMPATIBLE = CAR + "presets\\parts\\physics\\ax_x_v01_sound.compatiblepart"

    def loud(self, state=None):
        self.version("Loud", dict({"_sounds": {"turbo": "event:/parts/turbos/turbo_rx7"}}, **(state or {})))
        return self.apply({})

    def test_a_version_with_another_turbo_gets_a_sound_part_and_the_notes_tell_it(self):
        res = self.loud()
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE, "note: version v01 (Loud): 9 files of its own",
                                        "note: version v01 (Loud): own sounds turbo=turbo_rx7"])
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Loud", "files": 9, "locked": False, "changes": {
            "since": None, "settings": [], "extras": [{"kind": "sound", "slot": "turbo", "from": None, "to": "event:/parts/turbos/turbo_rx7",
                                                      "text": "Sound turbo: own sound -> turbo_rx7"}], "total": 0}}])
        self.assertTrue(set(self.SOUND) <= set(self.tree(res)))

    def test_the_car_part_holds_only_the_differing_slot_and_names_the_tuning_part(self):
        part = self.built(self.loud(), self.SOUND[0])
        self.assertEqual((part["description"], part["note"], part["part_type"], part["brand"], part["no_specialization"]),
                         ("Loud sound", "Loud sound", "CarPartType_Mechanics_Engine", "Brand", {}))
        self.assertEqual(len(part["logic_parts"]), 1)
        logic = part["logic_parts"][0]
        self.assertEqual(logic["tuning_part_path"], CAR + "data\\parts\\ax_x_v01_engine.tuningpart")
        self.assertEqual(logic["car_audio_events"], [turbo("turbo_rx7")])

    def test_the_tuning_part_names_the_engine_of_the_version_and_the_compatible_part_the_car_part(self):
        res = self.loud()
        self.assertEqual(self.built(res, self.SOUND[2]), {"engine": {"path": CAR + "data\\engine_v01.carengine"},
                                                          "car_part_type": "CarPartType_Mechanics_Engine"})
        compatible = self.built(res, self.SOUND[1])
        self.assertEqual((compatible["car_part_path"], compatible["attachment_bone"]),
                         (CAR + "presets\\parts\\physics\\ax_x_v01_sound.carpart", "ENGINE"))
        self.assertEqual(compatible["attachment_relative_transform"]["scale"], {"x": 1.0, "y": 1.0, "z": 1.0})

    def test_the_tuning_part_follows_an_engine_of_the_version(self):
        res = self.loud({"limiter": 8000})
        self.assertEqual(self.built(res, self.SOUND[2])["engine"]["path"], CAR + "data\\engine_v01.carengine")

    def test_the_presets_and_the_actor_list_the_compatible_part_and_the_actor_keeps_the_base_sounds(self):
        res = self.loud()
        self.assertEqual(self.built(res, "presets/p_v01.mechanicalcarpreset")["forced_compatible_part_paths"], [self.COMPATIBLE])
        base = self.built(res, "presets/p.mechanicalcarpreset")
        self.assertEqual(base["not_compatible_part_paths"], [self.COMPATIBLE])
        self.assertNotIn("forced_compatible_part_paths", base)
        actor = self.built(res, "ax_x.actor")["car"]
        self.assertEqual(actor["customization"]["aftermarket_parts"], [self.COMPATIBLE])
        self.assertEqual(actor["audio_events"][1:], [turbo("turbo_none"), backfire("backfire_a")])
        self.assertEqual(actor["customization"]["mechanical_car_presets"], [PRESET, CAR + "presets\\p_v01.mechanicalcarpreset"])
        self.assertNotIn("ax_x_v01.actor", self.tree(res))

    def test_the_lists_that_exist_are_extended(self):
        self.x.store[self.x.key(os.path.join(self.x.car_root, "ks_x.actor"))]["car"]["customization"]["aftermarket_parts"] = ["other"]
        self.x.store[self.x.key(os.path.join(self.x.car_root, "presets", "p.mechanicalcarpreset"))]["not_compatible_part_paths"] = ["n"]
        res = self.loud()
        self.assertEqual(self.built(res, "ax_x.actor")["car"]["customization"]["aftermarket_parts"], ["other", self.COMPATIBLE])
        self.assertEqual(self.built(res, "presets/p.mechanicalcarpreset")["not_compatible_part_paths"], ["n", self.COMPATIBLE])

    def test_a_version_with_the_same_sounds_gets_no_sound_part(self):
        self.version("Same", {"_sounds": {"turbo": "event:/parts/turbos/turbo_none"}})
        res = self.apply({})
        self.assertEqual(res["notes"][-1], "note: version v01 (Same): 6 files of its own")
        self.assertFalse(set(self.SOUND) & set(self.tree(res)))
        self.assertNotIn("aftermarket_parts", self.built(res, "ax_x.actor")["car"]["customization"])
        self.assertNotIn("forced_compatible_part_paths", self.built(res, "presets/p_v01.mechanicalcarpreset"))
        self.assertNotIn("not_compatible_part_paths", self.built(res, "presets/p.mechanicalcarpreset"))

    def test_a_version_without_a_sound_choice_has_no_note(self):
        self.version("Quiet", {})
        self.assertEqual(self.apply({})["notes"][-1], "note: version v01 (Quiet): 6 files of its own")

    def test_the_sound_part_files_and_the_compatible_part_are_kept_in_their_final_state(self):
        res = self.loud()
        folder = tune.version_dir(self.work, "ks_x", "ax_x", "v01")
        with open(os.path.join(folder, "build", "build.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["sound_part"], self.COMPATIBLE)
        self.assertTrue(set(self.SOUND) <= set(record["files"]))
        self.assertEqual(record["files"], sorted(set(record["files"])))
        self.assertEqual(len(record["files"]), 9 + len(V_THUMBS))
        for rel in record["files"]:
            with open(os.path.join(folder, "build", "files", *rel.split("/")), "rb") as f, open(os.path.join(self.root(res), *rel.split("/")), "rb") as g:
                self.assertEqual(f.read(), g.read(), rel)
        with open(os.path.join(folder, "build", "files", "presets", "p_v01.mechanicalcarpreset"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["forced_compatible_part_paths"], [self.COMPATIBLE])


class TestWithoutVersions(World):
    def test_a_tune_without_versions_builds_as_before(self):
        res = self.apply({"limiter": 8000})
        self.assertEqual(res["versions"], [])
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE])
        self.assertEqual(self.calls, [("build", "ax_x.partial"), ("pack", "ax_x.partial")])
        self.assertEqual(self.built(res, "ax_x.actor")["car"]["customization"]["mechanical_car_presets"], [PRESET])
        self.assertEqual([t for t in self.tree(res) if "_v0" in t], [])
        self.assertEqual(self.built(res, "data/CarData.car")["engine"]["limiter"], 8000)
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x"])

    def test_the_default_state_applies_the_same_with_and_without_a_version_for_the_base_files(self):
        plain = self.snapshot(self.apply({"limiter": 8000}))
        self.version("Grip", {"limiter": 8000, "mass": 1800})
        with_version = self.snapshot(self.apply({"limiter": 8000}))
        changed = {k for k in plain if with_version.get(k) != plain[k]}
        self.assertEqual({k.replace(os.sep, "/") for k in changed}, {"/ax_x.actor"})
        self.assertEqual(set(with_version) - set(plain), {os.sep + os.path.join(*p.split("/")) for p in (
            "data/CarData_v01.car", "data/engine_v01.carengine", "data/power_v01.curve", "data/setup_v01.carsetup",
            "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset")})


class TestVersionRefusals(World):
    def test_a_file_that_cannot_be_decoded_and_names_a_file_of_the_version_refuses_the_build(self):
        def blob(root):
            self.write(os.path.join(root, "data", "blob.bin"), PRESET.replace("\\", "/").encode(), binary=True)
        self.hook = blob
        self.version("Grip", {"limiter": 8000})
        with self.assertRaisesRegex(ValueError, r"data/blob.bin refers to .*p.mechanicalcarpreset.*cannot be decoded"):
            self.apply({})
        self.assertFalse(os.path.exists(os.path.join(self.work, "ks_x", "build", "ax_x_v01.partial")))

    def test_a_failed_merge_removes_the_temporary_folder_of_the_version(self):
        self.version("Grip", {})
        self.patch(tune, "merge_version", lambda *a: (_ for _ in ()).throw(ValueError("merge failed")))
        with self.assertRaisesRegex(ValueError, "merge failed"):
            self.apply({})
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x.partial"])

    def test_a_version_that_cannot_be_applied_refuses_before_anything_is_built(self):
        v = self.version("Grip", {})
        tune.save_version_state(self.work, "ks_x", {"nope_setting": 1, "limiter": 8000}, v)
        self.patch(tune, "changed_settings", lambda work, car_id, new_id, cat, version=None: (_ for _ in ()).throw(ValueError("bad version")))
        with self.assertRaisesRegex(ValueError, "bad version"):
            self.apply({})
        self.assertEqual(self.calls, [])

    def test_a_carfinalstate_not_named_after_its_preset_refuses_the_build(self):
        self.x.add("presets/other_name.carfinalstate", {"car_data": self.x.game_path("data/x.car"), "body": {"path": self.x.game_path("presets/p.mechanicalcarpreset")}})
        self.version("Grip", {})
        with self.assertRaisesRegex(ValueError, "other_name.carfinalstate: a carfinalstate is named"):
            self.apply({})


class TestEveryFileTheTunerWritesIsTheVersions(World):
    def setUp(self):
        super().setUp()
        gp = self.x.game_path
        self.x.add("data/sub/deep.curve", {"points": []})
        self.x.add("presets/tyres.compatibletyres", {"front_tyre_data_path": gp("data/setup.carsetup")})
        self.x.add("presets/sub/nested.compatibletyres", {"front_tyre_data_path": ""})
        self.x.add("presets/tyres.other", {"x": 1})
        self.version("Same", {})
        self.res = self.apply({})

    def test_the_version_has_its_own_copy_of_every_file_below_data_at_any_depth(self):
        tree = self.tree(self.res)
        for rel in ("data/CarData_v01.car", "data/engine_v01.carengine", "data/power_v01.curve", "data/setup_v01.carsetup", "data/sub/deep_v01.curve"):
            self.assertIn(rel, tree)
        self.assertEqual(self.built(self.res, "data/sub/deep_v01.curve"), {"points": []})
        self.assertEqual(self.built(self.res, "data/sub/deep.curve"), {"points": []})

    def test_the_version_has_its_own_copy_of_each_compatibletyres_file_directly_in_presets_pointing_at_the_version_files(self):
        self.assertEqual(self.built(self.res, "presets/tyres_v01.compatibletyres"), {"front_tyre_data_path": CAR + "data\\setup_v01.carsetup"})
        self.assertEqual(self.built(self.res, "presets/tyres.compatibletyres"), {"front_tyre_data_path": CAR + "data\\setup.carsetup"})

    def test_other_files_of_the_presets_folder_and_nested_ones_stay_shared(self):
        tree = self.tree(self.res)
        self.assertNotIn("presets/sub/nested_v01.compatibletyres", tree)
        self.assertNotIn("presets/tyres_v01.other", tree)
        self.assertIn("presets/sub/nested.compatibletyres", tree)

    def test_the_result_counts_the_copies(self):
        self.assertEqual(self.res["versions"][0]["files"], 8)


class TestTheKeptBuildOfAVersion(World):
    FILES = ["data/CarData_v01.car", "data/engine_v01.carengine", "data/power_v01.curve", "data/setup_v01.carsetup",
             "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset"] + V_THUMBS

    def setUp(self):
        super().setUp()
        self.v = self.version("Grip", {"limiter": 8000, "mass": 1800})
        self.res = self.apply({})
        self.folder = tune.version_dir(self.work, "ks_x", "ax_x", self.v)

    def record(self):
        with open(os.path.join(self.folder, "build", "build.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_build_json_tells_the_tune_the_preset_the_files_and_the_state(self):
        record = self.record()
        self.assertEqual(sorted(record), ["files", "preset", "sound_part", "state", "time", "tune"])
        self.assertEqual(record["tune"], "ax_x")
        self.assertEqual(record["preset"], CAR + "presets\\p_v01.mechanicalcarpreset")
        self.assertIsNone(record["sound_part"])
        self.assertEqual(record["files"], sorted(self.FILES))
        self.assertEqual(record["state"], tune.read_version_state(self.work, "ks_x", self.v, "ax_x"))
        self.assertEqual(record["state"], {"limiter": 8000, "mass": 1800})
        self.assertRegex(record["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_build_files_holds_exactly_those_files_with_the_bytes_of_the_package(self):
        root = os.path.join(self.folder, "build", "files")
        kept = sorted(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/") for dp, _, names in os.walk(root) for n in names)
        self.assertEqual(kept, sorted(self.FILES))
        for rel in kept:
            with open(os.path.join(root, *rel.split("/")), "rb") as f, open(os.path.join(self.root(self.res), *rel.split("/")), "rb") as g:
                self.assertEqual(f.read(), g.read(), rel)

    def test_nothing_else_is_left_in_the_version_folder(self):
        self.assertEqual(sorted(os.listdir(self.folder)), ["build", "meta.json", "snapshot.json", "tune_state.json"])

    def test_a_second_build_replaces_the_kept_build(self):
        tune.save_version_state(self.work, "ks_x", {"limiter": 9000, "mass": 1800}, self.v)
        self.apply({})
        self.assertEqual(self.record()["state"], {"limiter": 9000, "mass": 1800})
        self.assertEqual(sorted(os.listdir(self.folder)), ["build", "meta.json", "snapshot.json", "tune_state.json"])
        with open(os.path.join(self.folder, "build", "files", "data", "engine_v01.carengine"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["limiter"], 9000)


class TestAFailedBuildKeepsTheEarlierBuildOfAVersion(World):
    def kept(self, folder):
        found = {}
        for dp, _, names in os.walk(folder):
            for n in names:
                with open(os.path.join(dp, n), "rb") as f:
                    found[os.path.relpath(os.path.join(dp, n), folder)] = f.read()
        return found

    def test_the_build_and_the_record_of_the_version_stay_as_they_were(self):
        v = self.version("Grip", {"limiter": 8000})
        self.apply({})
        folder = tune.version_dir(self.work, "ks_x", "ax_x", v)
        before = self.kept(folder)
        self.assertIn(os.path.join("build", "build.json"), before)
        self.assertIn("snapshot.json", before)
        tune.save_version_state(self.work, "ks_x", {"limiter": 9000}, v)

        def blob(root):
            self.write(os.path.join(root, "data", "blob.bin"), PRESET.replace("\\", "/").encode(), binary=True)
        self.hook = blob
        with self.assertRaisesRegex(ValueError, "data/blob.bin refers to"):
            self.apply({})
        after = self.kept(folder)
        after.pop("tune_state.json"), before.pop("tune_state.json")
        self.assertEqual(after, before)


class TestTheBuildRecordOfAVersion(World):
    def setUp(self):
        super().setUp()
        self.v = self.version("Grip", {"limiter": 8000, "mass": 1800})
        self.path = tune.version_snapshot_path(self.work, "ks_x", "ax_x", self.v)

    def test_the_first_build_lists_the_changed_settings_of_the_version(self):
        res = self.apply({})
        record = tune.read_snapshot(self.path)
        self.assertEqual(record["settings"], {"limiter": 8000, "mass": 1800.0})
        self.assertEqual(record["name"], "Car X MY")
        changes = {"since": None, "settings": [{"id": "limiter", "from": 7000, "to": 8000}, {"id": "mass", "from": 1400.0, "to": 1800.0}],
                   "extras": [], "total": 2}
        self.assertEqual(record["changes"], changes)
        self.assertEqual(res["versions"][0]["changes"], changes)

    def test_a_second_build_with_one_changed_setting_lists_exactly_that_change(self):
        self.apply({})
        tune.save_version_state(self.work, "ks_x", {"limiter": 8000, "mass": 1900}, self.v)
        res = self.apply({})
        changes = {"since": "last build", "settings": [{"id": "mass", "from": 1800.0, "to": 1900.0}], "extras": [], "total": 2}
        self.assertEqual(res["versions"][0]["changes"], changes)
        self.assertEqual(tune.read_snapshot(self.path)["changes"], changes)

    def test_a_second_build_without_a_change_says_no_change(self):
        self.apply({})
        res = self.apply({})
        changes = {"since": "last build", "settings": [], "extras": [], "total": 2}
        self.assertEqual(res["versions"][0]["changes"], changes)
        self.assertEqual(tune.read_snapshot(self.path)["changes"], changes)

    def test_a_damaged_record_counts_as_no_previous_build(self):
        self.apply({})
        self.write(self.path, "{not json")
        self.assertEqual(self.apply({})["versions"][0]["changes"]["since"], None)

    def test_the_record_of_the_base_is_not_the_record_of_the_version(self):
        self.apply({})
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["settings"], {})


class TestChangeLinesOfVersions(unittest.TestCase):
    def test_each_version_with_changes_gets_a_block_between_the_base_lines_and_the_notes(self):
        def changes(since, settings, extras, total):
            return {"since": since, "settings": settings, "extras": extras, "total": total}
        res = {"changes": changes("last build", [], [], 1), "notes": ["note: a"], "versions": [
            {"id": "v01", "name": "Grip", "files": 6, "changes": changes(None, [{"id": "limiter", "from": 7000, "to": 8000}],
                                                                           [{"kind": "turbo_kit", "from": None, "to": "A", "text": "Turbo kit: none -> A"}], 2)},
            {"id": "v02", "name": "Heavy", "files": 6, "changes": changes("last build", [{"id": "mass", "from": 1400, "to": 1800}], [], 3)},
            {"id": "v03", "name": "Same", "files": 6, "changes": changes("last build", [], [], 3)},
            {"id": "v04", "name": "Old", "files": 6}]}
        self.assertEqual(tune.change_lines(res), [
            "no change since the last build (1 changed settings compared to the stock car in total)",
            "version v01 (Grip): first build of this version: 2 changed settings compared to the stock car",
            "    limiter: 7000 -> 8000", "    Turbo kit: none -> A",
            "version v02 (Heavy): 1 change(s) since its last build (3 changed settings compared to the stock car in total)",
            "    mass: 1400 -> 1800",
            "version v03 (Same): no change since its last build (3 changed settings compared to the stock car in total)",
            "note: a"])


class TestALockedVersion(World):
    """v01 and v03 stay unlocked, v02 (another turbo sound, so it has a sound part) is locked after its build."""
    TURBO = "event:/parts/turbos/turbo_rx7"
    COMPATIBLE = CAR + "presets\\parts\\physics\\ax_x_v02_sound.compatiblepart"

    def setUp(self):
        super().setUp()
        self.x.store[self.x.key(os.path.join(self.x.car_root, "ks_x.actor"))] = self.actor(engine(), turbo("turbo_none"), backfire("backfire_a"))
        donor = FakeCar(self.work, "ks_a")
        donor.store = self.x.store
        donor.add("ks_a.actor", {"car": {"audio_events": [engine(), turbo("turbo_rx7")]}})
        self.addCleanup(tune._actor_options.clear)
        self.version("Grip", {"limiter": 8000})
        self.version("Loud", {"_sounds": {"turbo": self.TURBO}, "mass": 1800})
        self.version("Heavy", {"mass": 1700})
        self.first = self.apply({})
        self.folder = tune.version_dir(self.work, "ks_x", "ax_x", "v02")
        tune.lock_version(self.work, "ks_x", "v02")
        self.kept = tune.kept_build(self.work, "ks_x", "v02")

    def disk(self, folder):
        found = {}
        for dp, _, names in os.walk(folder):
            for n in names:
                with open(os.path.join(dp, n), "rb") as f:
                    found[os.path.relpath(os.path.join(dp, n), folder).replace(os.sep, "/")] = f.read()
        return found

    def kept_bytes(self):
        return {k: v for k, v in self.disk(self.folder).items() if k.startswith("build/") or k == "snapshot.json"}

    def package_bytes(self, res, rels):
        out = {}
        for rel in rels:
            with open(os.path.join(self.root(res), *rel.split("/")), "rb") as f:
                out[rel] = f.read()
        return out

    def test_lock_after_a_build_works_and_a_change_afterwards_is_refused(self):
        self.assertEqual([(v["id"], v["locked"], v["built"] is not None) for v in tune.list_versions(self.work, "ks_x")],
                         [("v01", False, True), ("v02", True, True), ("v03", False, True)])
        self.assertEqual(tune.list_versions(self.work, "ks_x")[1]["built"], self.kept["time"])
        with self.assertRaisesRegex(ValueError, r"^version v02 \(Loud\) is locked; unlock it to change it$"):
            tune.set_value(self.work, "ks_x", "mass", "1900", version="v02")
        tune.set_value(self.work, "ks_x", "mass", "1900", version="v03")
        with self.assertRaisesRegex(ValueError, r"^version v03 \(Heavy\) has changes that are not built yet: Apply first, then lock it$"):
            tune.lock_version(self.work, "ks_x", "v03")

    def test_its_files_in_the_package_are_the_bytes_of_its_kept_build_whatever_the_base_does(self):
        kept = self.package_bytes(self.first, self.kept["files"])
        tune.set_value(self.work, "ks_x", "limiter", "9000", version="v03")
        res = self.apply({"limiter": 9000})
        self.assertEqual(self.package_bytes(res, self.kept["files"]), kept)
        for rel in self.kept["files"]:
            with open(os.path.join(self.folder, "build", "files", *rel.split("/")), "rb") as f:
                self.assertEqual(f.read(), kept[rel], rel)
        self.assertEqual(self.built(res, "data/engine.carengine")["limiter"], 9000)
        self.assertEqual(self.built(res, "data/engine_v01.carengine")["limiter"], 8000)
        self.assertEqual(self.built(res, "data/engine_v03.carengine")["limiter"], 9000)
        with open(os.path.join(self.root(res), "data", "engine_v02.carengine"), "rb") as f:
            self.assertEqual(json.loads(f.read())["limiter"], 7000)

    def test_the_actor_lists_the_presets_in_id_order_and_the_sound_part_is_listed_and_forbidden_in_the_base_preset(self):
        res = self.apply({"limiter": 9000})
        actor = self.built(res, "ax_x.actor")["car"]["customization"]
        self.assertEqual(actor["mechanical_car_presets"], [PRESET] + [CAR + "presets\\p_%s.mechanicalcarpreset" % v for v in ("v01", "v02", "v03")])
        self.assertEqual(actor["aftermarket_parts"], [self.COMPATIBLE])
        self.assertEqual(self.built(res, "presets/p.mechanicalcarpreset")["not_compatible_part_paths"], [self.COMPATIBLE])
        self.assertEqual(self.kept["preset"], CAR + "presets\\p_v02.mechanicalcarpreset")
        self.assertEqual(self.kept["sound_part"], self.COMPATIBLE)
        with open(os.path.join(self.root(res), "presets", "p_v02.mechanicalcarpreset"), "rb") as f:
            self.assertEqual(json.loads(f.read())["forced_compatible_part_paths"], [self.COMPATIBLE])

    def test_the_sound_parts_of_locked_and_unlocked_versions_are_all_listed_and_forbidden(self):
        self.version("Loud too", {"_sounds": {"turbo": self.TURBO}})
        res = self.apply({})
        other = CAR + "presets\\parts\\physics\\ax_x_v04_sound.compatiblepart"
        self.assertEqual(self.built(res, "ax_x.actor")["car"]["customization"]["aftermarket_parts"], [self.COMPATIBLE, other])
        self.assertCountEqual(self.built(res, "presets/p.mechanicalcarpreset")["not_compatible_part_paths"], [self.COMPATIBLE, other])

    def test_it_is_not_built_and_its_build_folder_and_snapshot_stay_byte_for_byte(self):
        before = self.kept_bytes()
        self.assertIn("snapshot.json", before)
        self.calls.clear()
        self.apply({"limiter": 9000})
        self.assertEqual([c[1] for c in self.calls if c[0] == "build"], ["ax_x.partial", "ax_x_v01.partial", "ax_x_v03.partial"])
        self.assertEqual(self.kept_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.folder)), ["build", "meta.json", "snapshot.json", "tune_state.json"])

    def test_the_unlocked_versions_are_rebuilt_and_their_kept_builds_replaced(self):
        old = {v: self.disk(tune.version_dir(self.work, "ks_x", "ax_x", v)) for v in ("v01", "v03")}
        tune.set_value(self.work, "ks_x", "limiter", "9000", version="v03")
        self.apply({"limiter": 9000})
        self.assertEqual(tune.kept_build(self.work, "ks_x", "v02"), self.kept)
        for v in ("v01", "v03"):
            now = self.disk(tune.version_dir(self.work, "ks_x", "ax_x", v))
            rel = "build/files/data/engine_%s.carengine" % v
            self.assertEqual(json.loads(now[rel])["limiter"], 8000 if v == "v01" else 9000)
            self.assertEqual(json.loads(old[v][rel])["limiter"], 8000 if v == "v01" else 7000)

    def test_the_result_has_the_locked_entry_without_changes_and_one_note(self):
        res = self.apply({})
        by_id = {v["id"]: v for v in res["versions"]}
        count = len(self.kept["files"])
        self.assertEqual(by_id["v02"], {"id": "v02", "name": "Loud", "files": count, "locked": True, "built": self.kept["time"]})
        self.assertEqual((by_id["v01"]["locked"], by_id["v03"]["locked"]), (False, False))
        self.assertIn("changes", by_id["v01"])
        self.assertEqual([v["id"] for v in res["versions"]], ["v01", "v02", "v03"])
        self.assertEqual(res["notes"][-3:], ["note: version v01 (Grip): 6 files of its own",
                                             "note: version v02 (Loud): locked, %d files kept from its build of %s" % (count, self.kept["time"]),
                                             "note: version v03 (Heavy): 6 files of its own"])
        self.assertEqual([n for n in res["notes"] if "v02" in n], [res["notes"][-2]])

    def test_the_change_lines_tell_that_it_is_not_rebuilt_in_the_place_of_its_block(self):
        res = self.apply({"limiter": 9000})
        lines = tune.change_lines(res)
        line = "version v02 (Loud): locked, not rebuilt (kept from its build of %s)" % self.kept["time"]
        self.assertEqual(lines.count(line), 1)
        starts = [i for i, text in enumerate(lines) if text.startswith("version v0")]
        self.assertEqual([lines[i][:11] for i in starts], ["version v01", "version v02", "version v03"])
        self.assertEqual(lines[starts[1]], line)
        self.assertTrue(starts[0] < starts[1] < starts[2])

    def test_a_locked_version_alone_is_put_in_after_the_base(self):
        for v in ("v01", "v03"):
            shutil.rmtree(tune.version_dir(self.work, "ks_x", "ax_x", v))
        res = self.apply({})
        self.assertEqual(res["versions"], [{"id": "v02", "name": "Loud", "files": len(self.kept["files"]), "locked": True, "built": self.kept["time"]}])
        self.assertEqual(self.built(res, "ax_x.actor")["car"]["customization"]["mechanical_car_presets"], [PRESET, self.kept["preset"]])
        self.assertEqual(tune.change_lines(res)[0], "no change since the last build (0 changed settings compared to the stock car in total)")
        self.assertEqual(tune.change_lines(res)[1], "version v02 (Loud): locked, not rebuilt (kept from its build of %s)" % self.kept["time"])

    def test_a_kept_build_that_is_missing_or_damaged_refuses_before_anything_is_built(self):
        previous = self.snapshot(self.first)
        build = os.path.join(self.folder, "build")
        damage = {"missing": lambda: os.remove(os.path.join(build, "build.json")),
                  "broken": lambda: self.write(os.path.join(build, "build.json"), "{not json"),
                  "file missing": lambda: os.remove(os.path.join(build, "files", *self.kept["files"][0].split("/"))),
                  "other tune": lambda: self.write(os.path.join(build, "build.json"), dict(self.kept, tune="ax_y"))}
        saved = self.disk(build)
        for name, hurt in damage.items():
            with self.subTest(name):
                self.calls.clear()
                hurt()
                with self.assertRaisesRegex(ValueError, r"^version v02 \(Loud\) is locked but its kept build is missing or damaged; unlock it$"):
                    self.apply({"limiter": 9000})
                self.assertEqual(self.calls, [])
                self.assertEqual(self.snapshot(self.first), previous)
                self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x"])
                shutil.rmtree(build)
                for rel, data in saved.items():
                    self.write(os.path.join(build, *rel.split("/")), data, binary=True)

    def test_a_name_that_is_taken_in_the_build_is_an_error(self):
        self.hook = lambda root: self.write(os.path.join(root, "data", "CarData_v02.car"), b"x", binary=True)
        with self.assertRaisesRegex(ValueError, r"^cannot copy data/CarData_v02.car of version v02: the name is taken$"):
            self.apply({})
        with open(os.path.join(self.folder, "build", "files", "data", "CarData_v02.car"), "rb") as f:
            self.assertNotEqual(f.read(), b"x")

    def test_after_unlocking_the_version_is_built_again_and_its_kept_build_is_replaced(self):
        tune.unlock_version(self.work, "ks_x", "v02")
        tune.set_value(self.work, "ks_x", "mass", "1900", version="v02")
        res = self.apply({})
        self.assertEqual([v["locked"] for v in res["versions"]], [False, False, False])
        self.assertEqual(self.built(res, "data/CarData_v02.car")["general"]["totalMass"], 1900.0)
        self.assertEqual(tune.kept_build(self.work, "ks_x", "v02")["state"], tune.read_version_state(self.work, "ks_x", "v02"))
        self.assertNotEqual(tune.kept_build(self.work, "ks_x", "v02")["state"], self.kept["state"])


class TestListVersionsWithADamagedMeta(World):
    def test_a_missing_or_damaged_meta_names_the_version_by_its_id(self):
        for name in ("Grip", "Heavy", "Light", "Odd"):
            tune.add_version(self.work, "ks_x", name)
        folder = os.path.join(self.work, "ks_x", "versions")
        os.remove(os.path.join(folder, "v02", "meta.json"))
        self.write(os.path.join(folder, "v03", "meta.json"), "{not json")
        self.write(os.path.join(folder, "v04", "meta.json"), {"name": 5})
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [{"id": "v01", "name": "Grip", "locked": False, "built": None}, {"id": "v02", "name": "v02", "locked": False, "built": None},
                                                                 {"id": "v03", "name": "v03", "locked": False, "built": None}, {"id": "v04", "name": "v04", "locked": False, "built": None}])

    def test_a_version_with_a_damaged_meta_is_built_under_its_id(self):
        v = self.version("Grip", {})
        self.write(os.path.join(self.work, "ks_x", "versions", v, "meta.json"), "[]")
        res = self.apply({})
        self.assertEqual(res["versions"], [{"id": "v01", "name": "v01", "files": 6, "locked": False,
                                            "changes": {"since": None, "settings": [], "extras": [], "total": 0}}])
        self.assertEqual(self.built(res, "presets/p_v01.mechanicalcarpreset")["note"], "v01")


if __name__ == "__main__":
    unittest.main()
