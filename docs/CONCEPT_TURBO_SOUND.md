# Concept: turbo sound for a car that gets a turbo kit

Status: concept of 2026-11-14, nothing implemented. Written in the cloud from the official Kunos documentation (physics and audio pages, https://docs.assetto.cn/en/evo/car/physics/ and https://docs.assetto.cn/en/evo/car/audio/) and from facts already in this repository. The game files could not be inspected here, so every point marked "open" must be settled on the PC (Phase 0).

## 1. Problem

The turbo kit (TUNER_SPEC section 4h) gives a car without a turbo the turbo physics of a donor car. A turbo also has a sound (spool whistle, blow-off valve, flutter). The kit does not touch sound, so the car most likely boosts silently. Goal: find out whether and how the turbo sound can be added without breaking the engine sound of the car.

## 2. What is known

- Car sound is made with FMOD Studio 2.03.13. Each car has its own bank pair in the `sfx` folder of the car: `master_bank.bank` (audio data) and `master_bank.strings.bank` (string index). The Kunos pipeline forks template events (suffix `template`, new suffix = the car folder name), clones `master_bank_template`, marks the clone as master bank and builds with F7. The default events must not be used; the FMOD mixer page must not be touched. (Audio page.)
- The car is linked to its events in the editor: Tools menu, CarFinalState, tab "Audio events": first dropdown = event type (the only one named is `EngineInt`), button "..." = pick the bank (`master_bank.bank`), last dropdown = the event (for example `engine_int_ks_modded_car`), then "Save reference actor". (Audio page; the car page names the menu "Tools -> Gameplay -> Car Finalstate Editor", a different path for the same thing.)
- The audio page names no turbo, boost, blow-off or wastegate event, no list of event types, and no physics value that is passed to FMOD.
- The physics page says that "Max Turbo Boost" and "Bov Threshold" have no physical impact but are used as references for gameplay and audio. So the game reads boost-related values for sound.
- The physics page lists 31 controller input variables; none of them is boost or blow-off. (They are inputs of controllers, not necessarily the parameters FMOD gets.)
- Real engine files (docs/settings/coverage.md, generated from the five installed cars) contain the engine fields `bovThreshold`, `audio_throttle_limiter_tau_ms`, `turboControllers[*].stages[*]` and a block `damage` with `bovThreshold`, `turboBoostDamageK`, `turboBoostDamageThreshold`. So the engine file already carries audio-related and turbo-damage values.
- The codec already knows the file type `.carfinalstate` (CarFinalStateData, tools/car_json.py): the file where the audio events of a car are assigned can be decoded on the PC with the real schema. `.actor` is not mapped.
- Exhaust backfire sound is part of the backfire script of the car (car page), not of the turbo.

## 3. Open questions (settle on the PC)

- Q1: Is turbo sound a layer inside the engine event (driven by an FMOD parameter), or a separate event type with its own slot in "Audio events"?
- Q2: Which event types exist (the full list), and which of them do the turbo cars (for example the Mazda RX-7 FD) have assigned that a naturally aspirated car (for example the BMW) lacks?
- Q3: Can the game load an additional bank from the `sfx` folder of a car (a second bank next to `master_bank.bank`), and can an event slot point into it? Two master banks in one car are probably not possible; a donor's `master_bank.bank` may not be loadable next to the car's own.
- Q4: Which FMOD parameters does the game feed to the engine events (rpm, throttle, boost, ...) and are they the same for every car?
- Q5: Is any turbo or blow-off event in a global bank of the game (not per car)?
- Q6: Redistribution: FMOD banks are not ours; nothing derived from them may go into git or be published (same rule as for Kunos' cars).

## 4. Hypotheses

- H1: the turbo sound is a layer inside the engine event of each car. Then a car without turbo has no such layer and the only clean way is to edit the car's FMOD project (add a layer driven by the boost parameter). The tuner cannot do that; it would be a manual FMOD job following the official pipeline.
- H2: the turbo sound is a separate event with its own slot in "Audio events" (and the slot is simply empty on a car without a turbo). Then adding the sound means adding a slot entry that points at a turbo event in a bank the game can load. The tuner could do the data part (copy files, edit `.carfinalstate` through car_json), like the turbo kit does for physics.
- H3: the turbo sound is global (one generic event for all cars, played when the physics reports boost). Then the turbo kit already gives the sound and nothing is to do.

## 5. Options

- A. Borrow the donor's turbo event (needs H2 and Q3): the sound part of the turbo kit copies the donor's bank under a new name into the car's `sfx` folder and adds the turbo slot(s) to the car's `.carfinalstate`, pointing at the donor's turbo event. Pro: automatic, fits the kit design, engine note unchanged. Con: depends on Q3; two banks may clash; the donor's whistle may not fit the car; redistribution (Q6): local use only.
- B. Own turbo event in an own bank (H1 or H2): Alex builds one generic turbo bank with FMOD Studio following the official pipeline (fork the turbo template event if the SDK project has one, add his own samples); the tuner only copies that bank into the car and sets the slot. Pro: independent of donors, no redistribution problem if the samples are his. Con: manual FMOD work and samples; depends on a turbo template event existing.
- C. Use the donor's whole `master_bank.bank` instead of the car's: only as a diagnosis to learn which events make the whistle; the engine note would be wrong. Not a feature.
- D. Boost without sound (today): the safe fallback.

## 6. Plan

Phase 0, read-only investigation on the PC (about 1 to 2 hours, no game start needed):
1. List the `sfx` folder of a turbo car (Mazda RX-7 FD) and of an NA car (BMW M3 E46 CSL) in the work folder (`base\content\cars\<id>\sfx`): file names and sizes. Any bank files beyond the two? Any `GUIDs` file?
2. Read the event paths from `master_bank.strings.bank` of both cars (they are stored as plain text). A small stdlib tool `tools/bank_strings.py` that prints every printable string of at least 4 characters of a file is enough; look for `turbo`, `bov`, `boost`, `whistle`, `spool`, `flutter`, `blow`. Compare the two cars.
3. Decode the `.carfinalstate` of both cars with `python tools\car_json.py decode` (real schema): list the audio event slots (types, bank reference, event names) and diff the two cars. This answers Q1 and Q2. Also search all decoded files and the engine file for `turbo` strings near audio fields.
4. Look in the game content for global banks (any `.bank` outside the car folders) and list their event strings (Q5).
5. Write the result into docs/review/PC-REVIEW.md (new section) and choose H1, H2 or H3.

Phase 1, in-game experiments (backups first, scratch mods folder, Alex's OK), only if Phase 0 says H2:
- E1: BMW with turbo kit, no audio change: baseline (silent boost or not).
- E2: copy the donor bank as `sfx\<new name>.bank` into the BMW, add the turbo slot to its `.carfinalstate` pointing at the donor's turbo event: does the game start, does the whistle play, does the engine sound stay intact?
- E3: if E2 fails, check Q3 with a second bank only (no slot) to see whether the game accepts an extra bank at all.

Phase 2, decision gate: H3 = nothing to build. H2 and E2 works = build Option A. H2 but E2 fails or H1 = Option B as a manual guide plus a small tuner step (copy bank, set slot) or stay with Option D.

Phase 3, implementation (only after Phase 2), as an extension of the turbo kit: a "Sound" checkbox in the Turbo kit panel ("also copy the donor's turbo sound"), kit step copies the bank and patches `.carfinalstate` (through car_json), CLI `turbo-kit` lists them, tests with synthetic files, docs and a new PC checklist row. Every step follows the working contract.

## 7. Related finding for the turbo kit itself

The kit copies the top-level engine fields whose name contains "turbo", "boost" or "bov" (this includes `bovThreshold`, `turboBoostDamageK`, `turboBoostDamageThreshold`, `turboControllers`, `max_turbo_boost`). It does NOT copy the same-named fields inside the engine's `damage` block (`damage.bovThreshold`, `damage.turboBoostDamageK`, `damage.turboBoostDamageThreshold`). A car without a turbo may have zero or default values there; with boost the engine could be damaged immediately or never. Check this in the kit checklist rows (compare the `damage` block of the donor and of the NA car) and extend the kit's copy rule if needed.

## 8. Decision needed from Alex

- Run Phase 0 on the PC first (recommended, read-only), then decide on A or B.
- Whether samples or banks derived from Kunos' cars may only be used locally (recommended: local only, never in git).
- Kill criterion (decided by Alex, 2026-11-14): if Phase 0 finds no separate, easily extractable turbo event or slot (see the short task list in HANDOVER.md section 0a), the turbo sound idea is dropped and no further turbo work is planned; the turbo kit stays as it is, marked experimental.
