# Concept: Session Logger (draft for approval, 2026-11-16)

Status: **draft, not built.** Decisions of the interview with Alex on 2026-11-16 are marked (A). Open points are in section 9.

## 1. Purpose and scope

A logger that runs next to the game, reads the game's shared memory and writes what the game really does with the settings the tuner built, as JSON an AI can evaluate later. It answers two questions: (1) are the changes in the game (every setting the tuner can edit is checkable where the game shows it), and (2) how does the overall behaviour of the car change. It only records: no match flags, no verdicts (A). No dashboard, no real-life data, no driving topics (laps, lines, timing) (A).

The idea comes from the Assetto Corsa analysis of the parallel repository `AlexanderHultsch/RacingDashboard`. What we take from it: the shared memory access and the ACE layouts (`core/winmem.py`, `core/kunos.py`, `games/ace/connector.py`, layouts after Kunos' "ACE_SharedFileOut_Documentation_v1"), and the JSON Lines file idea. What we do not take: laps, sections, baselines, the trainer, the dashboard pages. Nothing is imported from the other repository: the needed code is copied into this one.

## 2. Parts

| Part | What |
|---|---|
| `tools/ace_shm.py` | `OpenFileMappingW` reader (`winmem`), the `Physics`, `Graphics` and `Static` ctypes layouts, a `parse` to a flat dict of named values; a fake-memory builder for tests; a `dump` command that prints the raw values once (to check the layouts on the PC) |
| `tools/logger.py` | the logger process: waits for the game, one session = one file, config read at session start |
| `tuner/log_channels.json` | for every setting id of `catalogue.json` (and the context group) its once-only reading, its live values and its status (section 6) |
| `tools/tuner_server.py` | routes `/api/log_config` (get, set), `/api/log_sessions` (list) and `/api/log_status` (is the logger running); same pattern as the garage and sound routes |
| `tuner/web/index.html` | the tab "Logging" next to Car Tuner and Tyre Creator |
| `start_logger.bat` | in the repository root next to `start_tuner.bat` |
| `logs/` | in the repository, git-ignored (A: inside OneDrive, large files sync; it can be moved to the work folder later) |
| `log_config.json` | the ticked channels and the sample rate, saved in the work folder by the tab |

The logger is a separate process (A: its own batch file). It uses the tuner's functions to read the expected values (effective values of the car from the work folder), so it needs the same folder layout as the tuner.

## 3. The Logging tab (A)

- Same groups as the tuner table, in the same order, expandable like the table, with the same group descriptions. One list: each tuner setting is a row with a checkbox; a group checkbox ticks the whole group.
- **Only settings the game shows directly are tickable** (A, 2026-11-16). Indirect and invisible settings stay in the list, greyed and not tickable, with a note ("not published by the game", or "only its effect is visible: use the behaviour values").
- Ticking a direct setting logs its once-only value and its live values (the channels listed for it in section 6). Nothing is logged that is not ticked. The time stamp `t` is always in every sample line.
- One extra group at the end, "Behaviour values (not a tuner setting)", tickable row by row: speed, rpm, gear, gas, brake, steering, g-forces, yaw rate, pitch and roll, wheel load, slip angle and slip ratio, suspension travel, tyre temperatures, brake temperatures. This is how the effect of the greyed settings (springs, dampers, anti-roll bars, toe, the tyre model) is recorded. Ticked by default, tickable like everything else.
- A sample rate selector (30 Hz or 60 Hz), a **logger status line** and a list of the recent session files (name, size, car, track, duration). The status line says whether the logger runs: "not running", "waiting for the game" or "logging <file>, <n> samples, <duration>". The logger writes `logs/logger_status.json` once a second (state, file, sample count, start time, process id); the route `/api/log_status` reads it and calls it "not running" when the file is older than 5 s. The tab refreshes it every 2 s while it is open.
- Saved automatically as `log_config.json`; the logger reads it when a session starts, so a change applies to the next session.

## 4. Session file (A)

One JSON Lines file per session in `logs/<date>_<time>_<car>.jsonl`, one JSON object per line, readable keys. A new file starts when the car, the track or the session changes, or when the game closes. No samples while the game is paused.

Line types:

1. `header` (not tickable, always written): everything below, for the AI to compare 1:1.
2. `static`: the once-only values of the ticked settings, read **2 s after the session goes live with the car standing** (A). If the car never stands still, the first 2 s of driving are used and the line says so (`"moving": true`).
3. `s` (sample): `{"type":"s","t":12.345,"rpm":6500, ...}` at 30 or 60 Hz, only ticked channels, values rounded to 3 to 4 digits. About 15 bytes per channel and sample: 15 channels at 60 Hz are roughly 55 MB per hour.
4. `end`: reason (game closed, car, track or session changed, logger stopped), duration, sample count.

### Header content (A, decided 2026-11-16)

- **Car:** the exact car name as the game reports it (`car_model`); a modded car shows as modded in its name. Whether the game reports the display name or the id is checked on the PC (section 9).
- **Track:** the track name only.
- **PC:** date, time and timezone offset.
- **Software:** game version, shared-memory layout version, logger version, the logger's config (ticked ids, sample rate).
- **Tuner facts (all):** tune id and stock car id, name suffix; all effective tuner values of the car, each with its stock default; the garage tyre selection; the turbo kit donor; the chosen sound options; the last build time, the installed package file time and the "changes since the last build" of that build; the game process start time (so a car built after the game started can be recognised from facts).

Not in the header (A): driver name, track configuration, track length, nation, coordinates, session names, the track conditions (removed on 2026-11-16), the car data table (every directly visible editable item is a tickable row instead).

## 5. Channels (names used in the file)

From the physics, graphics and static blocks (layouts in `ace_shm.py`); units as the game gives them, angles converted to degrees:

`rpm`, `rpm_max`, `gas`, `brake`, `clutch`, `gear`, `speed_kmh`, `steer`, `steer_deg`, `acc_g` (3), `yaw_rate`, `pitch`, `roll`, `wheel_load` (4), `wheel_speed` (4), `slip_ratio` (4), `slip_angle` (4), `camber_deg` (4), `susp_travel` (4), `ride_height` (2), `tyre_pressure_psi` (4), `tyre_temp_core` (4), `tyre_temp_in/mid/out` (4 each), `brake_temp` (4), `brake_torque` (4), `brake_bias`, `boost`, `boost_max`, `bhp`, `torque`, `fuel_l`, `fuel_max_l`, `max_gears`, and the electronics levels and flags: `tc_level`, `tc_cut_level`, `abs_level`, `esc_level`, `engine_map`, `diff_power_level`, `diff_coast_level`, `diff_power_pct`, `diff_coast_pct`, `damper_levels` (front/rear bump/rebound), `tc_active`, `abs_active`, `esc_active`. Wheel order front left, front right, rear left, rear right. Nothing is derived: gear ratios, mass and so on are computed by the AI from the raw channels.

## 6. Channel table: every tuner setting (preliminary; to be reviewed)

Status: **direct** = the game shows the value (a once-only reading, then live values): the row is tickable. **indirect** = only its effect is visible, **none** = nothing in the shared memory: both rows are greyed and **not tickable** (A); their effect is recorded through the "Behaviour values" group. The Once and Live columns below name the channels a direct row logs; for indirect rows they only say which behaviour values show the effect (a hint shown in the note).

| Group | Settings | Status | Once | Live |
|---|---|---|---|---|
| Meta | `variant_name`, `name_suffix` | none (in the header through the car name) | | |
| Display | `display_power_ps`, `display_torque_nm` | direct (what the game shows) | `bhp`, `torque` (peak is read from the series) | `bhp`, `torque`, `rpm`, `gas` |
| Engine | `limiter` | direct | `rpm_max` | `rpm` |
| | `idle_rpm` | direct (a standing car with the engine running idles at it) | `rpm` | `rpm`, `gas` |
| | `nominal_rpm`, `engine_damage_rpm`, `limiter_cycles` | indirect | | `rpm`, `gas`, `bhp`, `torque` |
| | `power_scale`, `coast_scale`, `engine_inertia`, `throttle_lag_up`, `throttle_lag_dn` | indirect | | `rpm`, `gas`, `bhp`, `torque`, `acc_g` |
| Turbo | `turbo_boost_1`, `turbo_boost_2`, `max_turbo_boost` | direct (peak boost read from the series; `boost_max` is not trusted, see the dashboard notes) | `boost_max` | `boost`, `rpm`, `gas` |
| Gearbox & clutch | `final_ratio`, `gear_1` to `gear_8` | indirect (ratio = rpm / speed per gear, computed by the AI) | `max_gears` | `gear`, `rpm`, `speed_kmh`, `clutch` |
| | `autoshift_up_rpm`, `gear_up_time`, `gear_dn_time`, `auto_cut_off_time`, `clutch_max_torque` | indirect | | `gear`, `rpm`, `speed_kmh`, `clutch`, `gas` |
| Differential | `diff_power_default`, `diff_coast_default`, `diff_power_max`, `diff_coast_max` | direct | `diff_power_level`, `diff_coast_level`, `diff_power_pct`, `diff_coast_pct` | the same, `wheel_speed`, `slip_ratio` |
| | `diff_preload_default`, `diff_preload_max` | indirect | | `wheel_speed`, `slip_ratio` |
| Differential (hardware) | all six | indirect | | `wheel_speed`, `slip_ratio`, `diff_power_pct`, `diff_coast_pct` |
| Steering | `steer_lock_deg`, `steer_ratio`, `steer_ratio_min`, `steer_ratio_max`, `steer_rod_ratio` | direct for the lock (maximum of `steer_deg`), indirect for the ratios | | `steer`, `steer_deg`, `yaw_rate` |
| Brakes | `brake_bias`, `brake_bias_min`, `brake_bias_max`, `brake_bias_hw` | direct | `brake_bias` | `brake_bias`, `brake_torque`, `brake` |
| | `brake_torque` | direct | `brake_torque` (at rest it is 0; the series shows the value under braking) | `brake_torque`, `brake`, `brake_temp`, `acc_g` |
| | `handbrake_torque` | none | | |
| Vehicle (hardware) | `car_mass` | direct (sum of `wheel_load`) | `wheel_load` | `wheel_load` |
| Springs & anti-roll | `spring_*`, `spring_min_*`, `spring_max_*`, `coilover_spring_*` | indirect | `wheel_load`, `susp_travel` | `susp_travel`, `wheel_load`, `roll`, `pitch` |
| | `arb_*`, `arb_min_*`, `arb_max_*`, `arb_stiffness_*` | indirect | | `roll`, `acc_g`, `susp_travel` |
| Ride height & bump stops | `ride_height_front`, `ride_height_rear` | direct | `ride_height` | `ride_height`, `susp_travel` |
| | `collar_*`, `bump_stop_*` | indirect | `susp_travel` | `susp_travel`, `wheel_load` |
| Dampers | `damper_*`, `coilover_damper_*` | indirect (the game shows the in-car damper click levels for cars that have them) | `damper_levels` | `susp_travel`, `roll`, `pitch`, `acc_g` |
| Alignment & tyres | `camber_front`, `camber_rear` | direct | `camber_deg` | `camber_deg`, `slip_angle`, `wheel_load` |
| | `tyre_pressure_front`, `tyre_pressure_rear` | direct | `tyre_pressure_psi` | `tyre_pressure_psi`, `tyre_temp_core` |
| | `toe_front`, `toe_rear`, `toe_min`, `toe_max`, `caster_front` | none directly; the effect shows in `slip_angle`, `tyre_temp_in/mid/out` | | `slip_angle`, `tyre_temp_in`, `tyre_temp_mid`, `tyre_temp_out`, `yaw_rate` |
| | `camber_min_*`, `camber_max_*`, `tyre_pressure_min`, `tyre_pressure_max` | none (limits of the in-game setup) | | |
| Tyres | grip, peak slip angle, load reference, stiffness, flex, heat, grain, thermal curve (front and rear, 24 settings) | indirect | | `slip_angle`, `slip_ratio`, `wheel_load`, `acc_g`, `tyre_temp_core`, `tyre_temp_in/mid/out` |
| Fuel | `fuel_start` | direct | `fuel_l`, `fuel_max_l` | `fuel_l` |
| Electronics | `tc_level`, `tc2_level`, `abs_level`, `driver_aids_off` | direct | `tc_level`, `tc_cut_level`, `abs_level`, `esc_level`, `engine_map` | `tc_active`, `abs_active`, `esc_active`, `slip_ratio` |
| Behaviour values | (not a tuner setting; every row tickable) | | | `speed_kmh`, `rpm`, `gear`, `gas`, `brake`, `steer`, `steer_deg`, `acc_g`, `yaw_rate`, `pitch`, `roll`, `wheel_load`, `slip_angle`, `slip_ratio`, `susp_travel`, `tyre_temp_core`, `tyre_temp_in/mid/out`, `brake_temp` |

Tickable after this rule (direct, 29 settings): `display_power_ps`, `display_torque_nm`, `limiter`, `idle_rpm`, `turbo_boost_1`, `turbo_boost_2`, `max_turbo_boost`, `diff_power_default`, `diff_coast_default`, `diff_power_max`, `diff_coast_max`, `steer_lock_deg`, `brake_bias`, `brake_bias_min`, `brake_bias_max`, `brake_bias_hw`, `brake_torque`, `car_mass`, `ride_height_front`, `ride_height_rear`, `camber_front`, `camber_rear`, `tyre_pressure_front`, `tyre_pressure_rear`, `fuel_start`, `tc_level`, `tc2_level`, `abs_level`, `driver_aids_off`. `handbrake_torque` is greyed (the shared memory has no handbrake torque). Every other setting is greyed. The exact status of each setting is fixed in `log_channels.json` and shown to Alex for review in package 2.

Some indirect rows are only readable after driving the situation that shows them (a limiter hit, a full-throttle pull, a brake test). The AI sees whatever the driver did; the logger does not ask for tests.

## 7. Build packages (one at a time, each tested, subagents write the code as always)

1. `tools/ace_shm.py`: layouts, parse to named values, fake memory for tests, `dump` command. Tests: layout sizes and offsets, parsing of synthetic bytes.
2. `tuner/log_channels.json` and its loader and validator (every catalogue setting present, only known channel names), `log_config.json` read and write, the server routes. Tests: validator, routes, config validation.
3. `tools/logger.py` and `start_logger.bat`: waiting for the game, session boundaries, the header, the static line after 2 s standing, sampling at 30 or 60 Hz, pause handling, the end line, `logs/` in `.gitignore`. Tests with the fake memory and a fake clock.
4. The Logging tab in the page. Tests: string-level page checks like the other panels; real check in the browser with scratch folders.
5. Docs (spec section, user guide, README bullet, handover) and PC checklist rows.

## 8. Limits

- The development laptop cannot run the game: everything is built and tested against fake memory. The real behaviour of the layouts, the car name, the 2 s standing rule and the rates is checked on the gaming PC.
- ACE publishes no spring, damper, toe, caster or tyre model values; the greyed rows are honest about that.
- `logs/` is inside OneDrive: large files will sync.
- ACE stops writing shared memory while the setup page is open; the logger sees that as no new data and writes nothing.

## 8b. Considered and declined (2026-11-16)

After a second look at the bridge (`RacingDashboard`: the physics page fields `wheelAngularSpeed`, `fx`, `fy`, `tyreContactHeading`, `suspensionTravel`, the graphics electronics tables) three extensions were offered and declined by Alex. They stay out unless he asks again:

- A tier "Measurable" (gear ratios from rpm / wheel speed, nominal rpm, autoshift rpm, toe from the contact heading, spring rates from load / travel, tyre grip from `fx`, `fy`): these settings stay greyed; the raw channels are available in the "Behaviour values" group.
- Reading the game's own log (`Saved Games\ACE\Logs`: car id, `FUEL ... setup with <n> L`, `POWER CLASS INDEX ... HP W:<kg>`) as a second source: not done; the logger reads shared memory only.
- A one-time discovery recording (`dump --record`, all raw blocks at 5 Hz while garage settings change) to find more fields: not done.

## 9. Open points

1. Does `car_model` give the display name or the id for a modded car? Decided on the PC with `dump`; the header stores whatever comes, verbatim.
2. Sample keys for array channels: `"wheel_load":[a,b,c,d]` (front left, front right, rear left, rear right).
3. Decided 2026-11-16: no track conditions in the header; only direct settings tickable; the tab shows whether the logger runs.
