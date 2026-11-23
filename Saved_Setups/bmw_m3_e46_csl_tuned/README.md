# Setup: BMW M3 E46 CSL "Tuned" with the version "Drift"

Alex's BMW M3 E46 CSL as one modded car with versions, an example of what the tuner builds. Numbers only, no game data and no package. Set up this way on 2026-11-23 (folder names before: `bmw_m3_e46_csl_drift`, when the drift setup was the car itself, then `bmw_m3_e46_csl_custom`, when the Base was a stock clone).

In the game the car is called **BMW M3 E46 CSL Tuned** (setting `name_suffix` = `Tuned`, tuned-car id `ax_bmw_m3_e46_csl`). Pick the car, then its version:

| Version | What it is |
|---|---|
| Base | the stock car with the Drift version's engine, weight and revs (Alex, 2026-11-23; meant to stay as it is): the same engine and turbo values as Drift (`power_scale` 0.5714, turbo kit from the BMW M4 CSL with boost 0.3 / 2.0 bar, wastegates 0.3 / 1.5, `max_turbo_boost` 1.8, limiter 8800, nominal 8600, damage 9000, idle 800, shift 8700, display 579 PS / 400 Nm, so 571 HP in the game), mass 1450 kg, brake torque 4700, turbo sound `turbo_quattro`. Everything else (drivetrain, steering, chassis, tyres, backfire sound) is stock. In the built package its power curve, coast curve and turbo files are byte-equal to the Drift version's |
| v01 "Drift" | Alex's drift baseline of 2026-11-22, tuned step by step against the Toyota Supra MKIV's Drift preset with session logs. Alex: "This car feels amazing." Since 2026-11-23 with slower steering and a stiffer rear anti-roll bar (step 6 below): "much better to drive". Alex may keep optimising it; Lock version freezes it once it is right |

| File | What it is |
|---|---|
| `setup.json` | the saved state of the Base: `tune_state.json` of the default modded car, `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json` |
| `versions/v01/meta.json` | the version's name (`Drift`) |
| `versions/v01/setup.json` | the saved state of the version: `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\versions\v01\tune_state.json`. Setting ids as in `tuner/catalogue.json` plus the keys `_turbo`, `_sounds` and `_tyres` |
| `last_build_record.json` | the record the tuner stored at the build of 2026-11-23 18:00 (`snapshots\ax_bmw_m3_e46_csl.json`); it covers the Base only (17 settings against the stock car) |
| `versions/v01/last_build_record.json` | the record of the version at the build of 2026-11-23 18:00 (`versions\v01\snapshot.json` of the work folder; 72 settings against the stock car, the shared Variant name included) |

## What the Drift version does (71 changes against the stock car, plus the shared Variant name)

- **Power like the Supra Drift preset (571 HP, the game's own figure):** turbo kit from the BMW M4 CSL with the Supra Drift's turbo setup (boost 0.3 / 2.0 bar, wastegates 0.3 / 1.5, `max_turbo_boost` 1.8) and `power_scale` 0.5714. The game computes power as engine power x `power_scale` x (1 + boost): 357 x 0.5714 x 2.8 = 571 HP. Limiter 8800, display power 579 PS.
- **Drivetrain:** Spool (power 0.85 / coast 0.7), final ratio 3.91, gear 1 = 3.5, gear 2 = 2.1.
- **Steering and feel:** `steer_rod_ratio` 0.0022, steer ratio 14, **force feedback multiplier 2.1** (stock 1.75).
- **Chassis:** mass 1450 kg (stock 1495), springs 54000 / 55000, anti-roll bars 36000 / **40000**, spring collars 97.1 / 44.2 mm (they set the ride height, about 137 / 127 mm standing), static camber **-3.1** / -0.5 deg (about -2.3 deg front on the road), brake torque 4700.
- **Tyres:** own front and rear values (grip, peak slip angle, carcass stiffness 38000, vertical stiffness 312000, front load reference 4320, supercar thermal curve).
- **Sound:** turbo `turbo_quattro` (Audi Sport quattro), backfire `backfire_supra` (Toyota Supra MKIV). In the package this is the version's own sound part.
- TC 0, fuel 29.

## How it got here (2026-11-22, The Yard, logged)

| Step | Change | Result |
|---|---|---|
| 1 | mass 1290 -> 1450 kg | "more information in the feedback, more predictable" |
| 2 | rear anti-roll bar 6000 -> 30000, front static camber -4.2 -> -3.1, collars raised | better, more weight; roll split and camber in drift now like the Supra |
| 3 | power 1077 -> 571 HP (Supra Drift's turbo setup, `power_scale` 0.5714) | "much better"; rear wheelspin and drift angles like the Supra |
| 4 | front tyre stiffness like the Supra's supercar tyre | little change |
| 5 | force feedback multiplier 1.75 -> 2.1 | "feels amazing" (live FFB signal median 0.45 -> 0.49) |
| 6 (2026-11-23, tried as version "In progress") | `steer_rod_ratio` 0.0025 -> 0.0022, rear anti-roll bar 30000 -> 40000 (the Supra Drift's values), against the front washing out at full lock in a fast drift | "much better to drive" |

Not reachable by settings: the E46's MacPherson front axle (the Supra Drift has a double wishbone), its lighter front hubs (32 vs 60 kg) and its 50/50 weight split (Supra about 55 % front).

## Restore on another PC

1. Install the game, start `start_tuner.bat` once so the work folder exists, and use "Install car" on the BMW M3 E46 CSL, the BMW M4 CSL (donor of the turbo kit), the Audi Sport quattro (turbo sound) and the Toyota Supra MKIV (backfire sound); without the sound cars Apply refuses with "the saved ... sound ... is no longer available".
2. Stop the tuner. Copy under exactly these names (`tune_state.json` is git-ignored in the repository, which is why the copies here are called `setup.json`):
   - `setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json`;
   - `versions\v01\meta.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\versions\v01\meta.json`;
   - `versions\v01\setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\versions\v01\tune_state.json`.
3. Start the tuner and select the BMW M3 E46 CSL (it appears under Modded Cars as "BMW M3 E46 CSL Tuned"). Check Base and the version "Drift" in the Version list, then Apply with the game closed. One Apply builds both into one package. Never commit the package: it contains Kunos data.

Only the drift car, without versions: copy `versions\v01\setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json` and set the name suffix in the page.
