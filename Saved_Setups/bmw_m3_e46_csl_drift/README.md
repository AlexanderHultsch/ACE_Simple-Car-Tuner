# Setup: BMW M3 E46 CSL "Drift"

Alex's own drift setup of the BMW M3 E46 CSL, saved into the repository on 2026-11-17 because the laptop that held it is no longer available. These are his own tuning values (numbers only, no game data and no package).

In the game the car is called **BMW M3 E46 CSL Drift** (setting `name_suffix` = `Drift`, tuned-car id `ax_bmw_m3_e46_csl`). Alex's own name for it, "Ben e3...Drift", was cut off in his message and never given in full; this folder is named after the car and the suffix.

| File | What it is |
|---|---|
| `setup.json` | the saved state of the car page (`tune_state.json` of the default modded car), copied unchanged from `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json` (last written 2026-11-15 19:29). Setting ids as in `tuner/catalogue.json` plus the keys `_turbo` and `_sounds`. This is the newest state and it is the one to restore |
| `last_build_record.json` | the record the tuner stored at the last build (`snapshots\ax_bmw_m3_e46_csl.json`, build of 2026-11-15 17:10 UTC): all values, the turbo kit, the garage choice, the sound choice, the display name. Kept for reference only; the installed package of that day was built from it |

The two files differ in one value: `driver_aids_off` is `true` in the build record and `false` in `setup.json` (changed after the last build). The installed package (`ax_bmw_m3_e46_csl.kspkg`, written 2026-11-15 18:11 local time) was therefore built from the older state. Nothing of this setup has been driven yet.

## What the setup does

- Spool (locked) differential, final ratio 3.91, gear 1 = 3.5, gear 2 = 2.1, limiter 8500, display power 400 PS, power scale 1.05, coast scale 0.8, car mass 1290 kg.
- Turbo kit from the BMW M4 CSL (`ks_bmw_m4_csl`, twin turbo, boost 1.0 / 1.0), turbo sound `event:/parts/turbos/turbo_quattro`. The kit needs the M4 CSL installed in the work folder (the tuner reads its turbo files from there), and the sound `turbo_quattro` must exist in the game's sound banks.
- Chassis: springs 54000 / 55000, anti-roll bars 36000 / 6000, ride height 130 / 135 mm, camber -3.5 / -0.5 deg, toe 0.0 / 0.1 deg, tyre pressure 28 / 23 psi, own tyre grip values per axle (the `tyre_*` rows), TC level 0, fuel 29.
- Tyres: only per-car tyre settings (no garage choice: `garage` is `null`).

## Restore on another PC

1. Install the game, start `start_tuner.bat` once so the work folder exists, and use "Install car" on the BMW M3 E46 CSL, on the BMW M4 CSL (the donor of the turbo kit) and on the Audi Sport quattro (the car of the turbo sound `turbo_quattro`; without it Apply refuses with "the saved turbo sound ... is no longer available") in the page.
2. Stop the tuner. Copy `setup.json` to `%USERPROFILE%\ace_modded_cars_work\ks_bmw_m3_e46_csl\tune_state.json` (the file name must be exactly that; it is git-ignored in the repository, which is why the copy here is called `setup.json`).
3. Start the tuner, select the BMW M3 E46 CSL (it appears under Modded Cars as "BMW M3 E46 CSL Drift"), check that the table shows the values above, then Apply with the game closed.
Restored and driven on the gaming PC on 2026-11-19 (Brands Hatch): Alex says it feels very good, the differential can be felt, the Audi turbo sound is there and the extra power can be felt.

4. A package built this way is not byte-identical to the one built on 2026-11-15 (new build time), but it has the same content if the same tuner version and game version are used. Never commit the package: it contains Kunos data.
