"""Sound picker of the tuner: the turbo and backfire sound of a car, read from and written into the decoded .actor file of a car.

Library module of tools/tune.py (no command line of its own). The functions work on the object that tools/car_json.py decodes an .actor file into (message ActorData): car.audio_events is a list of entries {event, type, debug, transform, bank, optionalParam}; type is an enum name, and the first entry of a car (the interior engine sound, enum value 0) has no type at all. A sound slot is found by its type, never by the position of the entry: the entries come in another order in every car.
A sound is identified by its option key: the event text, with "#<optionalParam>" appended when the entry has an optionalParam other than 0 (the same event with another optionalParam is another option). The options of a slot are the sounds the cars offer; the "none" event of a slot (turbo_none, backfire_none: the last part of the event path is none or ends with _none) is the silent one and comes first.
Slots: turbo = entries of type TurboEvent, backfire = entries of type Backfire.

Stdlib only.
"""
import copy

SLOTS = {"turbo": "TurboEvent", "backfire": "Backfire"}


def slot_type(slot):
    """The enum name of the entries of a slot; ValueError for a slot that does not exist."""
    if slot not in SLOTS:
        raise ValueError("unknown sound slot %r, use one of: %s" % (slot, ", ".join(SLOTS)))
    return SLOTS[slot]


def audio_events(obj):
    """The audio_events list of a decoded ActorData, [] when the object has none."""
    car = obj.get("car") if isinstance(obj, dict) else None
    events = car.get("audio_events") if isinstance(car, dict) else None
    return events if isinstance(events, list) else []


def slot_entries(obj, slot):
    """[(index, entry)] of the audio entries of the slot's type, in file order."""
    kind = slot_type(slot)
    return [(i, e) for i, e in enumerate(audio_events(obj)) if isinstance(e, dict) and e.get("type") == kind]


def is_none(event):
    """Whether an event is the silent one of its slot: the last path segment is none or ends with _none."""
    last = event.lower().replace("\\", "/").rsplit("/", 1)[-1]
    return last == "none" or last.endswith("_none")


def option_of(entry):
    """The identity of the sound of an audio entry: {key, event, bank, optional}; key is the event text plus "#<optionalParam>"
    when optionalParam is set and not 0, optional is that number or None."""
    event = entry.get("event", "")
    optional = entry.get("optionalParam") or None
    return {"key": "%s#%s" % (event, optional) if optional else event, "event": event, "bank": entry.get("bank"), "optional": optional}


def own_key(obj, slot):
    """The option key of the first entry of the slot, None when the car has no entry of the slot's type."""
    found = slot_entries(obj, slot)
    return option_of(found[0][1])["key"] if found else None


def option_order(option):
    """Sort key of an option: the silent (none) sound first, then the event text ignoring case, then optionalParam (none = 0), then the key."""
    return (not is_none(option["event"]), option["event"].lower(), option["optional"] or 0, option["key"])


def collect_options(per_car):
    """The sounds the cars offer, from {car id: decoded ActorData}: {slot: [option plus "cars" (sorted car ids that use it)]}, every slot
    present; sorted by event text ignoring case, the none events first."""
    found = {slot: {} for slot in SLOTS}
    for car_id, obj in per_car.items():
        for slot in SLOTS:
            for _, entry in slot_entries(obj, slot):
                option = option_of(entry)
                found[slot].setdefault(option["key"], dict(option, cars=set()))["cars"].add(car_id)
    return {slot: [dict(o, cars=sorted(o["cars"])) for o in sorted(options.values(), key=option_order)] for slot, options in found.items()}


def apply_option(entry, option, edit):
    """Put the sound option into an audio entry; edit is the function tune.set_field(obj, key, value) that sets a field and keeps the wire
    bookkeeping (_order) valid (passed in because tune imports this module)."""
    edit(entry, "event", option["event"])
    if option.get("bank") is not None:
        edit(entry, "bank", option["bank"])
    if option.get("optional"):
        edit(entry, "optionalParam", option["optional"])
    elif "optionalParam" in entry:
        del entry["optionalParam"]
        order = entry.get("_order")
        if isinstance(order, list) and "optionalParam" in order:
            order.remove("optionalParam")


def set_choice(obj, slot, option, template_entry, edit):
    """Give the car in obj (a decoded ActorData, changed in place) the sound option for slot. The first entry of the slot's type gets the
    event, bank and optionalParam of the option (optionalParam is removed when the option has none) and keeps its other fields; a car
    without such an entry gets a copy of template_entry (a full entry of a car that uses the option) with the option applied, appended
    to audio_events. The wire bookkeeping (_order) is kept valid by edit, the function tune.set_field(obj, key, value) (required: tune
    imports this module, so it is passed in)."""
    slot_type(slot)
    found = slot_entries(obj, slot)
    if found:
        apply_option(found[0][1], option, edit)
        return
    car = obj.get("car")
    if not isinstance(car, dict):
        raise ValueError("the actor has no car object")
    entry = copy.deepcopy(template_entry)
    apply_option(entry, option, edit)
    edit(car, "audio_events", audio_events(obj) + [entry])
