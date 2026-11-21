# Setup: BMW M4 CSL "Drift"

Alex's own drift setup of the BMW M4 CSL, made in the tuner on 2026-11-19 (it replaces an earlier M4 setup that was carried over from the E46; that one is in the git history, commit 597519b). Numbers only, no game data and no package.

In the game the car is called **BMW M4 CSL Drift** (setting `name_suffix` = `Drift`, tuned-car id `ax_bmw_m4_csl`).

| File | What it is |
|---|---|
| `setup.json` | the saved state of the car page (`tune_state.json` of the default modded car), copied from `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m4_csl\tune_state.json`. This is the file to restore |
| `last_build_record.json` | the record the tuner stored at the last build (`snapshots\ax_bmw_m4_csl.json`, build of 2026-11-19 16:22 UTC); same content, kept for reference |

## What the setup does (17 changes against the stock car)

- Engine: power scale 1.18, display power 650 PS and torque 800 Nm, limiter 8100 rpm (stock 7250), nominal rpm 7900, engine damage from 8300 rpm, auto shift up at 7899 rpm, clutch torque 1000 Nm.
- Turbo: boost 2.0 / 2.0 bar per turbo, `max_turbo_boost` 2.0 (stock 1.0 / 1.0 and 1.57), turbo sound `event:/parts/turbos/turbo_supra`.
- Differential: Spool, power 0.8, coast 0.06.
- Car mass 1590 kg (stock 1693), TC level 0.
- Chassis, alignment and tyres are stock.

## Measured in the game (2026-11-19, Brands Hatch, session log `2026-11-19_17-25-26_BMW_M4_CSL.jsonl`, 163 s)

- Logger: recognised as `ax_bmw_m4_csl` "Drift" (`matched_by` rpm_max); the package was built before the game started, so the game ran this build.
- Limiter works: rpm up to 8158, 1545 samples above the stock 7250.
- Power works: up to 645 bhp (stock about 550 x 1.18).
- Spool works: the two rear wheels turned at exactly the same speed in every sample under throttle (a locked axle), although the game keeps reporting the stock diff values 0.25 / 0.55.
- Drifting: rear slip angle above 10 deg for 30 % of the time above 30 km/h, up to 87 deg.
- **Boost does not reach 2.0:** it stops at 1.57 bar at full throttle. Cause: each turbo's `wastegate` is 0.785 bar (2 x 0.785 = 1.57) and limits the real boost; the tuner has no wastegate setting yet.
- Camber about -2.15 / -2.26 deg and ride height 136 / 137 mm (stock values, unchanged).

## Restore on another PC

1. Install the game, start `start_tuner.bat` once so the work folder exists, and use "Install car" on the BMW M4 CSL and on the car of the turbo sound `turbo_supra` (the Toyota Supra MKIV, `ks_toyota_supra_mkiv`; without it Apply refuses with "the saved turbo sound ... is no longer available").
2. Stop the tuner. Copy `setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m4_csl\tune_state.json` (exactly that name; it is git-ignored in the repository, which is why the copy here is called `setup.json`).
3. Start the tuner, select the BMW M4 CSL (it appears under Modded Cars as "BMW M4 CSL Drift"), check the values, then Apply with the game closed. Never commit the package: it contains Kunos data.
