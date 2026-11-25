# Setup: BMW M3 E46 CSL "Tuned" with the versions Base and Drift

Alex's BMW M3 E46 CSL, an example of what the tuner builds. Numbers only, no game data and no package. The folder has the same structure as the tuner's work folder: one folder per original car (`ks_bmw_m3_e46_csl`), the Base at the top, each version below `versions`, own tyres below `tyres`. (Folder names before 2026-11-25: `bmw_m3_e46_csl_drift`, `bmw_m3_e46_csl_custom`, `bmw_m3_e46_csl_tuned`.)

In the game the car is called **BMW M3 E46 CSL Tuned** (original car BMW M3 E46 CSL, car name `Tuned`, tuned-car id `ax_bmw_m3_e46_csl`). Pick the car, then its version:

| Version | What it is |
|---|---|
| Base | the original car with the Drift version's engine, weight and revs (Alex, 2026-11-23; meant to stay as it is): `power_scale` 0.5714, turbo kit from the BMW M4 CSL with boost 0.3 / 2.0 bar, wastegates 0.3 / 1.5, `max_turbo_boost` 1.8, limiter 8800, nominal 8600, damage 9000, idle 800, shift 8700 (571 HP in the game), mass 1450 kg, brake torque 4700, turbo sound `turbo_quattro`, force feedback 2.1 (`ff_mult`) and steering speed 0.0022 (`steer_rod_ratio`), which all versions share. Everything else is stock, tyres included |
| v01 "Drift" | Alex's drift baseline of 2026-11-22, tuned step by step against the Toyota Supra MKIV's Drift preset with session logs. Alex: "This car feels amazing." Since 2026-11-25 it **starts on its own tyres** (see below) |

| File | What it is (place in `%USERPROFILE%\ace_modded_cars_work`) |
|---|---|
| `setup.json` | the saved state of the Base (`ks_bmw_m3_e46_csl\tune_state.json`) |
| `versions/v01/meta.json`, `versions/v01/setup.json` | name and saved state of Drift (`ks_bmw_m3_e46_csl\versions\v01\meta.json`, `...\tune_state.json`). Setting ids as in `tuner/catalogue.json` plus the keys `_turbo`, `_sounds` and `_tyres` (the tyres offered in the game) |
| `tyres/*.json` | the two own tyres Drift uses (`tyres\*.json`, shared by all cars): "Drift front" (short DF) and "Drift rear" (DR) |
| `last_build_record.json`, `versions/v01/last_build_record.json` | the records of the build of 2026-11-25 (`snapshots\ax_bmw_m3_e46_csl.json`, `versions\v01\snapshot.json`) |

`tune_state.json` is git-ignored in the repository, which is why the copies here are called `setup.json`.

## What the Drift version does

- **Power like the Supra Drift preset (571 HP, the game's own figure):** the same engine and turbo values as the Base. The game computes power as engine power x `power_scale` x (1 + boost): 357 x 0.5714 x 2.8 = 571 HP. The displayed power and torque (576 PS / 592 Nm) are calculated by the tuner.
- **Drivetrain:** Spool (power 0.85 / coast 0.7), final ratio 3.91, gear 1 = 3.5, gear 2 = 2.1.
- **Steering and feel:** `steer_rod_ratio` 0.0022, steer ratio 14, force feedback multiplier 2.1 (stock 1.75), shared with the Base.
- **Chassis:** mass 1450 kg (stock 1495), springs 54000 / 55000, anti-roll bars 36000 / 40000, spring collars 97.1 / 44.2 mm (they set the ride height, about 137 / 127 mm standing), static camber -3.1 / -0.5 deg (about -2.3 deg front on the road), brake torque 4700.
- **Tyres:** own front and rear tyre (source Road 235/35 R19 and 265/30 R19 with 12 changed values each: grip, peak slip angle, carcass stiffness 38000, vertical stiffness 312000, front load reference 4320, supercar thermal curve ...). The game offers Drift, Supercar and Road tyres; Drift starts on the Drift tyres.
- **Sound:** turbo `turbo_quattro` (Audi Sport quattro), backfire `backfire_supra` (Toyota Supra MKIV). In the package this is the version's own sound part.
- TC 0, fuel 29.

## How it got here

Steps 1 to 5 on 2026-11-22 (The Yard, logged), step 6 on 2026-11-23, step 7 on 2026-11-25.

| Step | Change | Result |
|---|---|---|
| 1 | mass 1290 -> 1450 kg | "more information in the feedback, more predictable" |
| 2 | rear anti-roll bar 6000 -> 30000, front static camber -4.2 -> -3.1, collars raised | better, more weight; roll split and camber in drift now like the Supra |
| 3 | power 1077 -> 571 HP (Supra Drift's turbo setup, `power_scale` 0.5714) | "much better"; rear wheelspin and drift angles like the Supra |
| 4 | tyre values (front stiffness like the Supra's supercar tyre) | little change. **Explained later:** the car ran on the stock Supercar tyre, so these values were not in use |
| 5 | force feedback multiplier 1.75 -> 2.1 | "feels amazing" (live FFB signal median 0.45 -> 0.49) |
| 6 | `steer_rod_ratio` 0.0025 -> 0.0022, rear anti-roll bar 30000 -> 40000 (the Supra Drift's values), tried as the version "In progress" | "much better to drive", but compared with a painted Drift that drove with the Base's setup, so not a fair comparison |
| 7 | the tyre values made into own tyres and used as start tyres (before: the stock Supercar tyre) | a first comparison of two short drives at Laguna Seca found peak lateral g 1.07 (Drift tyres) against 1.03 (Supra) |

Not reachable by settings: the E46's MacPherson front axle (the Supra Drift has a double wishbone), its lighter front hubs (32 vs 60 kg) and its 50/50 weight split (Supra about 55 % front).

## Restore on another PC

1. Install the game, start `start_tuner.bat` once so the work folder exists, and use "Install car" on the BMW M3 E46 CSL, the BMW M4 CSL (donor of the turbo kit), the Audi Sport quattro (turbo sound) and the Toyota Supra MKIV (backfire sound); without the sound cars Apply refuses with "the saved ... sound ... is no longer available".
2. Stop the tuner. Copy:
   - `setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json`;
   - `versions\v01\meta.json` and `versions\v01\setup.json` to `...\ks_bmw_m3_e46_csl\versions\v01\meta.json` and `...\versions\v01\tune_state.json`;
   - `tyres\*.json` to `%USERPROFILE%\ace_modded_cars_work\tyres\`.
3. Start the tuner and select the BMW M3 E46 CSL Tuned. Check Base and Drift in the Version list, then Apply with the game closed. Never commit the package: it contains Kunos data.
