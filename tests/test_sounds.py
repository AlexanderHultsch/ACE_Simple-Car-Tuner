"""Tests for tools/sounds.py: slot_entries, option_of, collect_options and set_choice on decoded ActorData objects, and set_choice against a synthetic ActorData schema (built here: no game data and no schemas/ folder needed) to see that the edited object encodes to exactly the wire bytes of the expected car.

The objects are plain dicts like the ones tools/car_json.py decodes an .actor file into (enum = name, the first entry has no type, _order / _packed / _unknown as the codec writes them).
"""
import copy
import unittest

from support import desc_enum, desc_field, desc_file, desc_message, desc_set, pb_msg, pb_str, pb_vint, tmp

import car_json as cj
import sounds

BANK = "content\\sfx\\turbo.bank"
BACKFIRE_BANK = "content\\sfx\\backfire.bank"
TURBO = "event:/parts/turbos/"
BACKFIRE = "event:/parts/backfires/"


def entry(event, kind=None, bank=BANK, **more):
    e = {"event": event}
    if kind is not None:
        e["type"] = kind
    e["transform"] = {"scale": {"x": 1.0}}
    e["bank"] = bank
    e.update(more)
    return e


def turbo(name, **more):
    return entry(TURBO + name, "TurboEvent", **more)


def backfire(name, **more):
    return entry(BACKFIRE + name, "Backfire", BACKFIRE_BANK, **more)


def engine():
    return entry("event:/evo_cars/ks_x/engine_int", None, "content\\sfx\\ks_x.bank")


def actor(*entries, order=True):
    car = {"cameras": ["c1"], "audio_events": list(entries), "lights": ["l1"]}
    if order:
        car["_order"] = ["cameras"] + ["audio_events"] * len(entries) + ["lights"]
    return {"car": car}


def option(event, bank=BANK, optional=None):
    return {"key": event if not optional else "%s#%d" % (event, optional), "event": event, "bank": bank, "optional": optional}


class TestSlotEntries(unittest.TestCase):
    def test_the_slots_and_their_enum_names(self):
        self.assertEqual(sounds.SLOTS, {"turbo": "TurboEvent", "backfire": "Backfire"})

    def test_an_entry_is_found_by_its_type_whatever_its_position(self):
        a = actor(engine(), turbo("turbo_none"), backfire("backfire_e46"), entry("event:/wheel/wheel_int", "WheelEventInt"))
        b = actor(engine(), backfire("backfire_classic"), entry("event:/wheel/wheel_int", "WheelEventInt"), entry("event:/x", "Horn"),
                  turbo("turbo_rx7"))
        self.assertEqual([i for i, _ in sounds.slot_entries(a, "turbo")], [1])
        self.assertEqual([i for i, _ in sounds.slot_entries(a, "backfire")], [2])
        self.assertEqual([i for i, _ in sounds.slot_entries(b, "turbo")], [4])
        self.assertEqual([i for i, _ in sounds.slot_entries(b, "backfire")], [1])
        self.assertEqual(sounds.slot_entries(b, "turbo")[0][1]["event"], TURBO + "turbo_rx7")
        self.assertIs(sounds.slot_entries(b, "turbo")[0][1], b["car"]["audio_events"][4])

    def test_the_first_entry_without_a_type_belongs_to_no_slot(self):
        a = actor(engine())
        self.assertNotIn("type", a["car"]["audio_events"][0])
        for slot in sounds.SLOTS:
            self.assertEqual(sounds.slot_entries(a, slot), [])

    def test_a_type_that_is_a_number_or_another_name_does_not_match(self):
        a = actor(entry("event:/a", 8), entry("event:/b", "Turbo"), entry("event:/c", "TurboEvent "))
        self.assertEqual(sounds.slot_entries(a, "turbo"), [])

    def test_several_entries_of_a_type_are_all_listed_in_file_order(self):
        a = actor(turbo("turbo_a"), backfire("backfire_a"), turbo("turbo_b"))
        self.assertEqual([(i, e["event"]) for i, e in sounds.slot_entries(a, "turbo")], [(0, TURBO + "turbo_a"), (2, TURBO + "turbo_b")])

    def test_an_object_without_audio_events_has_no_entries(self):
        for obj in ({}, {"car": {}}, {"car": {"audio_events": []}}, {"car": {"audio_events": "x"}}, {"car": 5}, None, [], {"car": {"audio_events": [5, None]}}):
            with self.subTest(repr(obj)):
                self.assertEqual(sounds.slot_entries(obj, "turbo"), [])

    def test_an_unknown_slot_is_a_value_error(self):
        for call in (lambda: sounds.slot_entries(actor(), "horn"), lambda: sounds.slot_type("Turbo"),
                     lambda: sounds.set_choice(actor(), "horn", option("e"), entry("e")), lambda: sounds.slot_entries(actor(), None)):
            with self.assertRaisesRegex(ValueError, "^unknown sound slot .*, use one of: turbo, backfire$"):
                call()


class TestOptionOf(unittest.TestCase):
    def test_the_key_is_the_event(self):
        self.assertEqual(sounds.option_of(turbo("turbo_rx7")), {"key": TURBO + "turbo_rx7", "event": TURBO + "turbo_rx7", "bank": BANK, "optional": None})

    def test_an_optional_param_is_appended_to_the_key(self):
        self.assertEqual(sounds.option_of(backfire("backfire_classic_turbo", optionalParam=8)),
                         {"key": BACKFIRE + "backfire_classic_turbo#8", "event": BACKFIRE + "backfire_classic_turbo", "bank": BACKFIRE_BANK, "optional": 8})

    def test_an_optional_param_of_zero_or_a_missing_one_is_no_variant(self):
        for more in ({}, {"optionalParam": 0}):
            with self.subTest(more):
                o = sounds.option_of(turbo("turbo_a", **more))
                self.assertEqual((o["key"], o["optional"]), (TURBO + "turbo_a", None))

    def test_a_missing_bank_is_none(self):
        e = turbo("turbo_a")
        del e["bank"]
        self.assertIsNone(sounds.option_of(e)["bank"])

    def test_other_fields_are_not_part_of_the_identity(self):
        self.assertEqual(sounds.option_of(turbo("turbo_a", debug=True)), sounds.option_of(turbo("turbo_a")))


class TestIsNone(unittest.TestCase):
    def test_none_events(self):
        for event in (TURBO + "turbo_none", BACKFIRE + "backfire_none", TURBO + "none", "event:/parts/turbos/TURBO_NONE", "turbo_none", "none",
                      "event:\\parts\\none"):
            with self.subTest(event):
                self.assertTrue(sounds.is_none(event))

    def test_other_events(self):
        for event in (TURBO + "turbo_rx7", TURBO + "nonexistent", TURBO + "none_turbo", TURBO + "none/turbo_a", TURBO + "turbonone", ""):
            with self.subTest(event):
                self.assertFalse(sounds.is_none(event))


class TestCollectOptions(unittest.TestCase):
    def test_every_slot_is_present_even_without_cars_or_entries(self):
        self.assertEqual(sounds.collect_options({}), {"turbo": [], "backfire": []})
        self.assertEqual(sounds.collect_options({"ks_a": actor(engine()), "ks_b": {}}), {"turbo": [], "backfire": []})

    def test_options_name_the_cars_that_use_them_sorted(self):
        res = sounds.collect_options({"ks_c": actor(turbo("turbo_a"), backfire("backfire_a")), "ks_a": actor(backfire("backfire_a"), turbo("turbo_a")),
                                      "ks_b": actor(turbo("turbo_b"))})
        self.assertEqual([(o["key"], o["cars"]) for o in res["turbo"]], [(TURBO + "turbo_a", ["ks_a", "ks_c"]), (TURBO + "turbo_b", ["ks_b"])])
        self.assertEqual([(o["key"], o["cars"]) for o in res["backfire"]], [(BACKFIRE + "backfire_a", ["ks_a", "ks_c"])])
        self.assertEqual(res["turbo"][0], {"key": TURBO + "turbo_a", "event": TURBO + "turbo_a", "bank": BANK, "optional": None, "cars": ["ks_a", "ks_c"]})

    def test_the_none_event_comes_first_and_the_rest_by_event_name_ignoring_case(self):
        cars = {"ks_1": actor(turbo("turbo_rx7")), "ks_2": actor(turbo("Turbo_bmw")), "ks_3": actor(turbo("turbo_none")), "ks_4": actor(turbo("continental")),
                "ks_5": actor(turbo("turbo_Zeta")), "ks_6": actor(turbo("turbo_generic"))}
        names = [o["event"][len(TURBO):] for o in sounds.collect_options(cars)["turbo"]]
        self.assertEqual(names, ["turbo_none", "continental", "Turbo_bmw", "turbo_generic", "turbo_rx7", "turbo_Zeta"])

    def test_any_none_event_is_first_both_in_turbo_and_in_backfire(self):
        cars = {"ks_1": actor(backfire("backfire_a")), "ks_2": actor(backfire("a_none")), "ks_3": actor(backfire("backfire_none"))}
        names = [o["event"][len(BACKFIRE):] for o in sounds.collect_options(cars)["backfire"]]
        self.assertEqual(names, ["a_none", "backfire_none", "backfire_a"])

    def test_the_same_event_with_another_optional_param_is_another_option(self):
        cars = {"ks_a": actor(backfire("backfire_classic_turbo", optionalParam=8)), "ks_b": actor(backfire("backfire_classic_turbo")),
                "ks_c": actor(backfire("backfire_classic_turbo", optionalParam=8)), "ks_d": actor(backfire("backfire_classic_turbo", optionalParam=3))}
        res = sounds.collect_options(cars)["backfire"]
        self.assertEqual([(o["key"], o["optional"], o["cars"]) for o in res],
                         [(BACKFIRE + "backfire_classic_turbo", None, ["ks_b"]), (BACKFIRE + "backfire_classic_turbo#3", 3, ["ks_d"]),
                          (BACKFIRE + "backfire_classic_turbo#8", 8, ["ks_a", "ks_c"])])

    def test_a_car_that_lists_a_sound_twice_counts_once(self):
        res = sounds.collect_options({"ks_a": actor(turbo("turbo_a"), turbo("turbo_a"), turbo("turbo_b"))})
        self.assertEqual([(o["key"], o["cars"]) for o in res["turbo"]], [(TURBO + "turbo_a", ["ks_a"]), (TURBO + "turbo_b", ["ks_a"])])

    def test_entries_of_both_slots_are_found_wherever_they_are(self):
        res = sounds.collect_options({"ks_a": actor(engine(), turbo("turbo_a"), backfire("backfire_a")), "ks_b": actor(backfire("backfire_b"), engine(), turbo("turbo_b"))})
        self.assertEqual([o["key"] for o in res["turbo"]], [TURBO + "turbo_a", TURBO + "turbo_b"])
        self.assertEqual([o["key"] for o in res["backfire"]], [BACKFIRE + "backfire_a", BACKFIRE + "backfire_b"])

    def test_the_input_is_not_changed(self):
        cars = {"ks_a": actor(engine(), turbo("turbo_a"))}
        before = copy.deepcopy(cars)
        sounds.collect_options(cars)
        self.assertEqual(cars, before)


class TestSetChoiceReplace(unittest.TestCase):
    def test_event_and_bank_are_replaced_and_the_other_fields_kept(self):
        obj = actor(engine(), turbo("turbo_none", debug=True), backfire("backfire_a"))
        other = copy.deepcopy(obj)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_rx7", "content\\sfx\\other.bank"), None)
        e = obj["car"]["audio_events"][1]
        self.assertEqual(e, {"event": TURBO + "turbo_rx7", "type": "TurboEvent", "debug": True, "transform": {"scale": {"x": 1.0}}, "bank": "content\\sfx\\other.bank"})
        other["car"]["audio_events"][1] = e
        self.assertEqual(obj, other)

    def test_the_other_slot_and_the_other_entries_are_not_touched(self):
        obj = actor(backfire("backfire_a", optionalParam=8), engine(), turbo("turbo_a"))
        before = copy.deepcopy(obj)
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK), None)
        self.assertEqual(obj["car"]["audio_events"][1:], before["car"]["audio_events"][1:])
        self.assertEqual(obj["car"]["audio_events"][0]["event"], BACKFIRE + "backfire_b")

    def test_a_car_with_the_entry_late_in_the_list_is_found_by_type(self):
        obj = actor(engine(), backfire("backfire_a"), entry("event:/h", "Horn"), turbo("turbo_none"))
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), None)
        self.assertEqual([e["event"] for e in obj["car"]["audio_events"]],
                         ["event:/evo_cars/ks_x/engine_int", BACKFIRE + "backfire_a", "event:/h", TURBO + "turbo_b"])

    def test_the_optional_param_of_the_option_is_set_and_replaces_an_old_one(self):
        obj = actor(backfire("backfire_a", optionalParam=3), turbo("turbo_a"))
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK, 8), None)
        self.assertEqual(obj["car"]["audio_events"][0]["optionalParam"], 8)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b", BANK, 5), None)
        self.assertEqual(obj["car"]["audio_events"][1]["optionalParam"], 5)

    def test_an_optional_param_is_removed_when_the_option_has_none(self):
        obj = actor(backfire("backfire_a", optionalParam=8), turbo("turbo_a", optionalParam=0))
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK), None)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), None)
        self.assertEqual([e for e in obj["car"]["audio_events"] if "optionalParam" in e], [])

    def test_the_entry_order_names_follow_a_removed_and_an_added_optional_param(self):
        a = backfire("backfire_a", optionalParam=8)
        a["_order"] = ["event", "type", "transform", "bank", "optionalParam"]
        t = turbo("turbo_a")
        t["_order"] = ["event", "type", "transform", "bank"]
        obj = actor(a, t)
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK), None)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b", BANK, 4), None)
        self.assertEqual(obj["car"]["audio_events"][0]["_order"], ["event", "type", "transform", "bank"])
        self.assertEqual(obj["car"]["audio_events"][1]["_order"], ["event", "type", "transform", "bank", "optionalParam"])

    def test_an_entry_without_a_bank_gets_one_and_an_option_without_a_bank_keeps_the_bank(self):
        e = turbo("turbo_a")
        del e["bank"]
        obj = actor(e)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b", BANK), None)
        self.assertEqual(obj["car"]["audio_events"][0]["bank"], BANK)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_c", None), None)
        self.assertEqual(obj["car"]["audio_events"][0]["bank"], BANK)

    def test_the_car_order_is_not_changed_by_a_replace(self):
        obj = actor(engine(), turbo("turbo_a"))
        order = list(obj["car"]["_order"])
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), None)
        self.assertEqual(obj["car"]["_order"], order)

    def test_the_template_is_not_used_when_the_car_has_an_entry(self):
        obj = actor(turbo("turbo_a"))
        template = turbo("turbo_t")
        before = copy.deepcopy(template)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), template)
        self.assertEqual((len(obj["car"]["audio_events"]), template), (1, before))

    def test_only_the_first_entry_of_a_type_is_changed(self):
        obj = actor(turbo("turbo_a"), turbo("turbo_b"))
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_c"), None)
        self.assertEqual([e["event"] for e in obj["car"]["audio_events"]], [TURBO + "turbo_c", TURBO + "turbo_b"])

    def test_it_returns_nothing(self):
        self.assertIsNone(sounds.set_choice(actor(turbo("turbo_a")), "turbo", option(TURBO + "turbo_b"), None))


class TestSetChoiceAppend(unittest.TestCase):
    def test_a_car_without_the_entry_gets_a_copy_of_the_template_with_the_option_applied(self):
        obj = actor(engine(), backfire("backfire_a"))
        template = turbo("turbo_rx7", debug=True)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b", "content\\sfx\\b.bank", 2), template)
        e = obj["car"]["audio_events"][-1]
        self.assertEqual(e, {"event": TURBO + "turbo_b", "type": "TurboEvent", "debug": True, "transform": {"scale": {"x": 1.0}}, "bank": "content\\sfx\\b.bank",
                             "optionalParam": 2})
        self.assertEqual([x["event"] for x in obj["car"]["audio_events"][:2]], ["event:/evo_cars/ks_x/engine_int", BACKFIRE + "backfire_a"])
        self.assertEqual(sounds.slot_entries(obj, "turbo"), [(2, e)])

    def test_the_template_is_copied_not_shared_or_changed(self):
        template = turbo("turbo_rx7", optionalParam=8)
        before = copy.deepcopy(template)
        obj = actor(engine())
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), template)
        self.assertEqual(template, before)
        e = obj["car"]["audio_events"][-1]
        self.assertIsNot(e, template)
        self.assertNotIn("optionalParam", e)
        e["transform"]["scale"]["x"] = 9.0
        self.assertEqual(template, before)

    def test_the_names_of_audio_events_in_the_car_order_grow_by_one_at_the_old_place(self):
        obj = actor(engine(), backfire("backfire_a"))
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), turbo("turbo_rx7"))
        self.assertEqual(obj["car"]["_order"], ["cameras", "audio_events", "audio_events", "audio_events", "lights"])
        self.assertEqual(len(obj["car"]["audio_events"]), 3)

    def test_without_a_car_order_none_is_made(self):
        obj = actor(engine(), order=False)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), turbo("turbo_rx7"))
        self.assertNotIn("_order", obj["car"])

    def test_a_car_without_any_audio_events_gets_the_list(self):
        obj = {"car": {"cameras": ["c1"], "_order": ["cameras"]}}
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK), backfire("backfire_a"))
        self.assertEqual([e["event"] for e in obj["car"]["audio_events"]], [BACKFIRE + "backfire_b"])
        self.assertEqual(obj["car"]["_order"], ["cameras", "audio_events"])

    def test_an_actor_without_a_car_is_a_value_error_and_stays_as_it_was(self):
        for obj in ({}, {"car": 5}):
            before = copy.deepcopy(obj)
            with self.assertRaisesRegex(ValueError, "^the actor has no car object$"):
                sounds.set_choice(obj, "turbo", option(TURBO + "turbo_b"), turbo("turbo_rx7"))
            self.assertEqual(obj, before)

    def test_an_unknown_slot_changes_nothing(self):
        obj = actor(engine(), turbo("turbo_a"))
        before = copy.deepcopy(obj)
        with self.assertRaises(ValueError):
            sounds.set_choice(obj, "horn", option("e"), turbo("t"))
        self.assertEqual(obj, before)


ENUM = {"EngineInt": 0, "EngineExt": 1, "WheelEventInt": 2, "WindEffect": 6, "TurboEvent": 8, "Backfire": 9, "Horn": 14}


def schema_bytes():
    enum = desc_enum("AudioEventDataType", list(ENUM.items()))
    transform = desc_message("TransformData", [desc_field("x", 1, 5)])
    audio = desc_message("AudioEventData", [
        desc_field("event", 1, 9), desc_field("type", 2, 14, 1, ".AudioEventDataType"), desc_field("debug", 4, 8),
        desc_field("transform", 5, 11, 1, ".TransformData"), desc_field("bank", 6, 9), desc_field("optionalParam", 7, 5)])
    car = desc_message("CarActorData", [desc_field("cameras", 1, 9, 3), desc_field("audio_events", 9, 11, 3, ".AudioEventData"),
                                        desc_field("lights", 10, 9, 3)])
    root = desc_message("ActorData", [desc_field("car", 103, 11, 1, ".CarActorData")])
    return desc_set(desc_file("actor.proto", messages=[transform, audio, car, root], enums=[enum]))


def wire_entry(event, kind=None, bank=BANK, optional=None, debug=False):
    parts = [pb_str(1, event)]
    if kind is not None:
        parts.append(pb_vint(2, ENUM[kind]))
    if debug:
        parts.append(pb_vint(4, 1))
    parts += [pb_msg(5, pb_vint(1, 7)), pb_str(6, bank)]
    if optional is not None:
        parts.append(pb_vint(7, optional))
    return pb_msg(9, *parts)


def wire_actor(*entries):
    """cameras, the audio entries, an unknown field of a higher number and then the lights: the codec needs _order for it."""
    return pb_msg(103, pb_str(1, "c1"), pb_str(1, "c2"), *entries, pb_vint(200, 5), pb_str(10, "l1"))


class TestOnTheWire(unittest.TestCase):
    """set_choice on a decoded actor of a synthetic ActorData schema: the encoded result is byte for byte the actor built by hand."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tmp()
        base = cls._tmp.__enter__()
        (base / "acevo.desc").write_bytes(schema_bytes())
        cls.sch = cj.load_schema(base / "acevo.desc")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.__exit__(None, None, None)

    def decode(self, wire):
        obj, err = cj.roundtrip(self.sch, "ActorData", wire, text=False)
        self.assertIsNone(err)
        return obj

    def encode(self, obj):
        return cj.encode_msg(self.sch, "ActorData", obj)

    def test_the_decoded_actor_has_the_shape_the_functions_expect(self):
        obj = self.decode(wire_actor(wire_entry("event:/e/engine_int", None, "b"), wire_entry(TURBO + "turbo_none", "TurboEvent")))
        self.assertEqual([e.get("type") for e in obj["car"]["audio_events"]], [None, "TurboEvent"])
        self.assertIn("_order", obj["car"])
        self.assertEqual(sounds.option_of(sounds.slot_entries(obj, "turbo")[0][1])["key"], TURBO + "turbo_none")

    def test_replace_event_and_bank(self):
        wire = wire_actor(wire_entry("event:/e/engine_int", None, "b"), wire_entry(TURBO + "turbo_none", "TurboEvent", debug=True), wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK))
        obj = self.decode(wire)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_generic", "content\\sfx\\other.bank"), None)
        self.assertEqual(self.encode(obj), wire_actor(wire_entry("event:/e/engine_int", None, "b"),
                                                      wire_entry(TURBO + "turbo_generic", "TurboEvent", "content\\sfx\\other.bank", debug=True),
                                                      wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK)))

    def test_remove_the_optional_param(self):
        wire = wire_actor(wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK, 8), wire_entry(TURBO + "turbo_a", "TurboEvent"))
        obj = self.decode(wire)
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK), None)
        self.assertEqual(self.encode(obj), wire_actor(wire_entry(BACKFIRE + "backfire_b", "Backfire", BACKFIRE_BANK), wire_entry(TURBO + "turbo_a", "TurboEvent")))

    def test_add_and_change_the_optional_param(self):
        wire = wire_actor(wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK), wire_entry(TURBO + "turbo_a", "TurboEvent", optional=3))
        obj = self.decode(wire)
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK, 8), None)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_a", BANK, 5), None)
        self.assertEqual(self.encode(obj), wire_actor(wire_entry(BACKFIRE + "backfire_b", "Backfire", BACKFIRE_BANK, 8),
                                                      wire_entry(TURBO + "turbo_a", "TurboEvent", optional=5)))

    def test_an_entry_with_its_own_wire_order_keeps_encoding(self):
        entry_wire = pb_msg(9, pb_str(6, BACKFIRE_BANK), pb_str(1, BACKFIRE + "backfire_a"), pb_vint(2, ENUM["Backfire"]), pb_vint(7, 8))
        obj = self.decode(wire_actor(entry_wire))
        self.assertIn("_order", obj["car"]["audio_events"][0])
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK), None)
        self.assertEqual(self.encode(obj), wire_actor(pb_msg(9, pb_str(6, BACKFIRE_BANK), pb_str(1, BACKFIRE + "backfire_b"), pb_vint(2, ENUM["Backfire"]))))
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_c", BACKFIRE_BANK, 4), None)
        self.assertEqual(self.encode(obj), wire_actor(pb_msg(9, pb_str(6, BACKFIRE_BANK), pb_str(1, BACKFIRE + "backfire_c"), pb_vint(2, ENUM["Backfire"]), pb_vint(7, 4))))

    def test_append_for_a_car_without_the_entry(self):
        template = self.decode(wire_actor(wire_entry(TURBO + "turbo_rx7", "TurboEvent")))["car"]["audio_events"][0]
        wire = wire_actor(wire_entry("event:/e/engine_int", None, "b"), wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK))
        obj = self.decode(wire)
        sounds.set_choice(obj, "turbo", option(TURBO + "turbo_rx7"), template)
        self.assertEqual(self.encode(obj), wire_actor(wire_entry("event:/e/engine_int", None, "b"), wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK),
                                                      wire_entry(TURBO + "turbo_rx7", "TurboEvent")))
        again = self.decode(self.encode(obj))
        self.assertEqual([i for i, _ in sounds.slot_entries(again, "turbo")], [2])

    def test_append_with_an_optional_param_into_a_car_without_audio_events(self):
        template = self.decode(wire_actor(wire_entry(BACKFIRE + "backfire_a", "Backfire", BACKFIRE_BANK)))["car"]["audio_events"][0]
        obj = self.decode(pb_msg(103, pb_str(1, "c1"), pb_vint(200, 5), pb_str(10, "l1")))
        sounds.set_choice(obj, "backfire", option(BACKFIRE + "backfire_b", BACKFIRE_BANK, 8), template)
        self.assertEqual(self.encode(obj), pb_msg(103, pb_str(1, "c1"), pb_vint(200, 5), pb_str(10, "l1"), wire_entry(BACKFIRE + "backfire_b", "Backfire", BACKFIRE_BANK, 8)))


if __name__ == "__main__":
    unittest.main()
