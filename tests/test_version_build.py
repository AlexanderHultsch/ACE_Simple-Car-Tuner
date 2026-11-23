"""Tests for the versions of a modded car in the build of tools/tune.py: apply builds each version of the tune into its own temporary folder and merges its own files into the package as a further mechanical preset (build_state, build_versions, merge_version and the helpers below them), and list_versions naming a version with a damaged meta.json by its id.

No game data and no schemas: the car is synthetic (support.FakeCar replaces tune.load_msg / save_msg with in-memory messages, a save also writes the JSON of the message into the file so that files that differ differ in their bytes); clone_car.build and kspkg.cmd_pack are stubbed.
"""
import json
import os
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
        self.assertEqual(car["stock_setup"], CAR + "data\\setup.carsetup")
        engine_copy = self.built(res, "data/engine_v01.carengine")
        self.assertEqual((engine_copy["limiter"], engine_copy["minimum"], engine_copy["powerCurve"]), (8000, 800, CAR + "data\\power.curve"))

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

    def test_the_version_has_only_its_own_files_and_nothing_else_is_added(self):
        own = ["data/CarData_v01.car", "data/engine_v01.carengine", "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset"]
        base = sorted(set(self.tree(self.res)) - set(own) - set(V_THUMBS))
        self.assertEqual(base, ["ax_x.actor", "data/CarData.car", "data/engine.carengine", "data/power.curve", "data/setup.carsetup", *THUMBS,
                                "presets/ax_x_p_vis.carfinalstate", "presets/p.mechanicalcarpreset", "presets/vis.visualcarpreset"])
        self.assertTrue(set(own + V_THUMBS) <= set(self.tree(self.res)))

    def test_the_result_lists_the_version_and_one_note_tells_its_files(self):
        res = self.res
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Grip", "files": 4}])
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE, "note: version v01 (Grip): 4 files of its own"])

    def test_the_build_record_and_the_changes_are_those_of_the_base(self):
        self.assertEqual(self.res["applied"], [])
        self.assertEqual(self.res["changes"], {"since": None, "settings": [], "extras": [], "total": 0})
        self.assertEqual(tune.load_snapshot(self.work, "ks_x", "ax_x")["settings"], {})

    def test_the_temporary_folder_of_the_version_is_gone_and_only_one_package_is_packed(self):
        self.assertEqual(os.listdir(os.path.join(self.work, "ks_x", "build")), ["ax_x"])
        self.assertEqual([c for c in self.calls if c[0] == "pack"], [("pack", "ax_x.partial")])
        self.assertIn(("build", "ax_x_v01.partial"), self.calls)


class TestAVersionThatChangesNothing(World):
    def test_it_gets_only_the_car_file_the_preset_and_the_finalstate(self):
        plain = set(self.tree(self.apply({})))
        self.version("Same", {})
        res = self.apply({})
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Same", "files": 3}])
        self.assertEqual(sorted(set(self.tree(res)) - plain),
                         sorted(["data/CarData_v01.car", "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset"] + V_THUMBS))
        car = self.built(res, "data/CarData_v01.car")
        self.assertEqual((car["engine_path"], car["general"]["totalMass"]), (CAR + "data\\engine.carengine", 1400.0))
        self.assertEqual(self.built(res, "presets/p_v01.mechanicalcarpreset")["note"], "Same")


class TestSeveralVersions(World):
    def test_each_version_has_its_own_names_and_the_actor_lists_them_in_order(self):
        self.version("Grip", {"limiter": 8000})
        self.version("Heavy", {"mass": 1800})
        res = self.apply({})
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Grip", "files": 4}, {"id": "v02", "name": "Heavy", "files": 3}])
        self.assertEqual(res["notes"][-2:], ["note: version v01 (Grip): 4 files of its own", "note: version v02 (Heavy): 3 files of its own"])
        self.assertEqual(self.built(res, "data/CarData_v01.car")["engine_path"], CAR + "data\\engine_v01.carengine")
        self.assertEqual(self.built(res, "data/CarData_v01.car")["general"]["totalMass"], 1400.0)
        self.assertEqual(self.built(res, "data/CarData_v02.car")["engine_path"], CAR + "data\\engine.carengine")
        self.assertEqual(self.built(res, "data/CarData_v02.car")["general"]["totalMass"], 1800.0)
        self.assertNotIn("data/engine_v02.carengine", self.tree(res))
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
        self.assertEqual(res["notes"], ["note: from build", CAR_NOTE, "note: version v01 (Loud): 6 files of its own",
                                        "note: version v01 (Loud): own sounds turbo=turbo_rx7"])
        self.assertEqual(res["versions"], [{"id": "v01", "name": "Loud", "files": 6}])
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
        self.assertEqual(self.built(res, self.SOUND[2]), {"engine": {"path": CAR + "data\\engine.carengine"},
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
        self.assertEqual(res["notes"][-1], "note: version v01 (Same): 3 files of its own")
        self.assertFalse(set(self.SOUND) & set(self.tree(res)))
        self.assertNotIn("aftermarket_parts", self.built(res, "ax_x.actor")["car"]["customization"])
        self.assertNotIn("forced_compatible_part_paths", self.built(res, "presets/p_v01.mechanicalcarpreset"))
        self.assertNotIn("not_compatible_part_paths", self.built(res, "presets/p.mechanicalcarpreset"))

    def test_a_version_without_a_sound_choice_has_no_note(self):
        self.version("Quiet", {})
        self.assertEqual(self.apply({})["notes"][-1], "note: version v01 (Quiet): 3 files of its own")


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
            "data/CarData_v01.car", "presets/ax_x_p_v01_vis.carfinalstate", "presets/p_v01.mechanicalcarpreset")})


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


class TestListVersionsWithADamagedMeta(World):
    def test_a_missing_or_damaged_meta_names_the_version_by_its_id(self):
        for name in ("Grip", "Heavy", "Light", "Odd"):
            tune.add_version(self.work, "ks_x", name)
        folder = os.path.join(self.work, "ks_x", "versions")
        os.remove(os.path.join(folder, "v02", "meta.json"))
        self.write(os.path.join(folder, "v03", "meta.json"), "{not json")
        self.write(os.path.join(folder, "v04", "meta.json"), {"name": 5})
        self.assertEqual(tune.list_versions(self.work, "ks_x"), [{"id": "v01", "name": "Grip"}, {"id": "v02", "name": "v02"},
                                                                 {"id": "v03", "name": "v03"}, {"id": "v04", "name": "v04"}])

    def test_a_version_with_a_damaged_meta_is_built_under_its_id(self):
        v = self.version("Grip", {})
        self.write(os.path.join(self.work, "ks_x", "versions", v, "meta.json"), "[]")
        res = self.apply({})
        self.assertEqual(res["versions"], [{"id": "v01", "name": "v01", "files": 3}])
        self.assertEqual(self.built(res, "presets/p_v01.mechanicalcarpreset")["note"], "v01")


if __name__ == "__main__":
    unittest.main()
