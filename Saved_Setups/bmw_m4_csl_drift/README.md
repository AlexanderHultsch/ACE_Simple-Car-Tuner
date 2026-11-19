# Setup: BMW M4 CSL "Drift"

A drift setup of the BMW M4 CSL, an example of what the tuner builds: the recipe of the [BMW M3 E46 CSL Drift](../bmw_m3_e46_csl_drift/README.md) carried over to the M4 on 2026-11-19 and corrected once after measuring in the game. Numbers only, no game data and no package.

In the game the car is called **BMW M4 CSL Drift** (setting `name_suffix` = `Drift`, tuned-car id `ax_bmw_m4_csl`).

| File | What it is |
|---|---|
| `setup.json` | the saved state of the car page (`tune_state.json` of the default modded car), copied from `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m4_csl\tune_state.json` on 2026-11-19. Setting ids as in `tuner/catalogue.json` plus the keys `_turbo`, `_sounds` and `_tyres`. This is the file to restore |
| `last_build_record.json` | the record the tuner stored at the last build (`snapshots\ax_bmw_m4_csl.json`, build of 2026-11-19 14:56 UTC). Same content as `setup.json` (it leaves out values equal to the stock default); kept for reference |

## How the E46 recipe was carried over

The M4 is heavier and has its own twin turbo, so the E46 numbers were not copied 1:1:

- **Same value** (the drift recipe): Spool differential with power 0.85 / coast 0.7 (setup and hardware), power scale 1.05, coast scale 0.8, tyre pressure 28 / 23 psi, toe 0.0 / 0.1, TC 0, fuel 29, front camber limit -4.0 and rear 0.0, turbo sound `turbo_quattro`.
- **Same ratio to stock**: springs, anti-roll bars, dampers, gear 1 and 2, final ratio, car mass (-13.7 %), steering rod ratio and lock (+22 % maximum wheel angle), bump stop rates, tyre physics, rev limiter (+5 %, 7600), display power and torque.
- **Same offset from stock**: collars, ride height target, camber target, static camber, bump stop ranges; then corrected once from the measurement.
- **Rules**: coilover springs and dampers equal to the setup ones; tyre grain gains and heat partition as offsets (partition capped at 1.0); diff preload, Torsen bias, nominal rpm and the tyre thermal curve (already "hypercar") stay stock; no turbo kit.
- The stock M4's setup limits are locked (min = max for springs, anti-roll bars, steer ratio); the setup widens them to the new values.

Result: limiter 7600, gear 1 = 4.14, gear 2 = 2.66, final 3.41, mass 1461 kg, springs 43875 / 38077, anti-roll bars 18000 / 2160, collars 112.8 / 78.2 mm, static camber -4.275 / -1.35 deg, steering lock 315 deg.

## Measured in the game (2026-11-19, Brands Hatch, same pit box, standing still)

Camber -3.78 / -1.28 deg (average of left and right) against the targets -3.8 / -1.3, ride height 144.0 / 147.7 mm against 144 / 147, limiter 7600, TC 0 in the SPORT+ performance mode, pressures 28 / 23 psi. Alex: drifting is easy, maybe from the extra power.

Known limit: the M4 has an "M Active Differential" (`rear_lock_controllers` in its drivetrain) on top of the Spool the setup writes; the game reports a diff of 0.25, so the Spool probably does not act as on the E46. The tuner cannot switch that controller off yet.

## Restore on another PC

1. Install the game, start `start_tuner.bat` once so the work folder exists, and use "Install car" on the BMW M4 CSL and on the Audi Sport quattro (the car of the turbo sound `turbo_quattro`).
2. Stop the tuner. Copy `setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m4_csl\tune_state.json` (exactly that name; it is git-ignored in the repository, which is why the copy here is called `setup.json`).
3. Start the tuner, select the BMW M4 CSL (it appears under Modded Cars as "BMW M4 CSL Drift"), check the values, then Apply with the game closed. Never commit the package: it contains Kunos data.
