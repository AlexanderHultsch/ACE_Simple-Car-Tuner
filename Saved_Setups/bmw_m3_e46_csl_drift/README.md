# Setup: BMW M3 E46 CSL "Drift"

Alex's own drift setup of the BMW M3 E46 CSL, an example of what the tuner builds. These are his own tuning values (numbers only, no game data and no package). First saved on 2026-11-17, updated on 2026-11-19 after it was driven and measured on the gaming PC.

In the game the car is called **BMW M3 E46 CSL Drift** (setting `name_suffix` = `Drift`, tuned-car id `ax_bmw_m3_e46_csl`).

| File | What it is |
|---|---|
| `setup.json` | the saved state of the car page (`tune_state.json` of the default modded car), copied from `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json` on 2026-11-19. Setting ids as in `tuner/catalogue.json` plus the keys `_turbo`, `_sounds` and `_tyres`. This is the file to restore |
| `last_build_record.json` | the record the tuner stored at the last build (`snapshots\ax_bmw_m3_e46_csl.json`, build of 2026-11-19 14:31 UTC): the changed values, the turbo kit, the garage choice, the sound choice, the display name. Same content as `setup.json` (it leaves out values equal to the stock default); kept for reference |

## What the setup does

- Spool (locked) differential, final ratio 3.91, gear 1 = 3.5, gear 2 = 2.1, limiter 8500, display power 400 PS, power scale 1.05, coast scale 0.8, car mass 1290 kg.
- Turbo kit from the BMW M4 CSL (`ks_bmw_m4_csl`, twin turbo, boost 1.0 / 1.0, capped at 1.57 bar by `max_turbo_boost`), turbo sound `event:/parts/turbos/turbo_quattro` of the Audi Sport quattro.
- Chassis: springs 54000 / 55000, anti-roll bars 36000 / 6000, spring collars 91.8 / 41.2 mm (they set the ride height; the target 130 / 135 mm alone does nothing), static camber -4.2 / -0.5 deg (the camber the game drives with; the target camber -3.5 / -0.5 alone does nothing), toe 0.0 / 0.1 deg, tyre pressure 28 / 23 psi, own tyre grip values per axle (the `tyre_*` rows), steering lock 450 deg, TC level 0, fuel 29.
- Tyres: only per-car tyre settings (no garage choice: `_tyres` is `null`).

## Measured in the game (2026-11-19, Brands Hatch, standing still)

Rev limiter 8500, boost up to 1.57 bar, diff 85 %, pressure gap front/rear as set, camber -3.93 / -0.53 deg (average of left and right), ride height about 125 / 133 mm. A further round would use front static camber about -3.8 and slightly higher collars to reach -3.5 deg and 130 / 135 mm. Alex: "it feels very good", the differential can be felt, the Audi turbo sound is there, the extra power can be felt.

## Restore on another PC

1. Install the game, start `start_tuner.bat` once so the work folder exists, and use "Install car" on the BMW M3 E46 CSL, on the BMW M4 CSL (the donor of the turbo kit: the tuner reads its turbo files from the work folder) and on the Audi Sport quattro (the car of the turbo sound `turbo_quattro`; without it Apply refuses with "the saved turbo sound ... is no longer available").
2. Stop the tuner. Copy `setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json` (the file name must be exactly that; it is git-ignored in the repository, which is why the copy here is called `setup.json`).
3. Start the tuner, select the BMW M3 E46 CSL (it appears under Modded Cars as "BMW M3 E46 CSL Drift"), check that the table shows the values above, then Apply with the game closed.
4. A package built this way is not byte-identical to the installed one (new build time), but it has the same content with the same tuner and game version. Never commit the package: it contains Kunos data.
