# ACE - Simple Car Tuner

**Tune any Assetto Corsa EVO car in minutes, in one simple table. From your PC or your phone.**

Pick a car, change what matters to the way it drives, and take your own version out on track next to the original. No file hunting, no guesswork, no hex editor.

## Why you will like it

- **Every car of the game.** Select any of the game's cars, install it with one click and start tuning.
- **One simple table.** More than a hundred settings per car with their real names: engine, turbo, gearbox, differential, steering, brakes, springs, dampers, anti-roll bars, ride height, alignment, tyres, driver aids and fuel.
- **Always know where you stand.** Next to every value you see the car's stock default, the range found across the cars of the game and a plain-English description based on the official documentation.
- **Your own cars next to the originals.** Make as many modded cars as you like. They appear in the game's car list right beside the stock car, which is never touched.
- **Your own tyres.** Create tyre compounds and choose which ones a car offers in the garage.
- **A turbo for cars without one.** Give a car the turbo setup of another car and tune its boost (experimental, not tested in the game yet).
- **Borrow sounds.** Give your car the turbo and backfire sound of any other car of the game (not heard in the game yet).
- **See what the game really does.** A session logger records the values the game reports while you drive (camber, ride height, boost, brake bias and more) as a file an AI can compare with your settings (not tried with the game yet).
- **Safe by design.** Every install keeps a backup of the previous version, so you can always go back.
- **On your phone, too.** Open the tuner from your phone or tablet on the same Wi-Fi and add it to your iPhone home screen like an app.
- **One double-click to start.** Run `start_tuner.bat` and the tuner opens in your browser.

## Get started

1. You need Windows, **Assetto Corsa EVO** (from Steam; its SDK is optional) and **Python 3.9 or newer**.
2. One time only: read the field names out of the SDK or the game with a single command (see the [user guide](USER_GUIDE.md)).
3. Double-click **`start_tuner.bat`**.
4. Pick a car, change some values, press **Create modded car**, start the game and drive.

The full step-by-step guide is in the [user guide](USER_GUIDE.md). The project is young: how each setting feels in the game is still being checked, and settings marked "unverified" in the table are best guesses.

## More

- Example setups: [BMW M3 E46 CSL Custom with the version Drift](../Saved_Setups/bmw_m3_e46_csl_custom/README.md) and [BMW M4 CSL Drift](../Saved_Setups/bmw_m4_csl_drift/README.md), cars built and driven with the tuner (the E46 as a stock-valued Base plus a Drift version), with what was measured in the game and how to load them.
- [User guide](USER_GUIDE.md): installation, every button and the details.
- [Project state](TUNER_SPEC.md): what works, what is verified, what is open.
- [Handover](HANDOVER.md): notes for continuing the work.

## Credits and rights

Not affiliated with KUNOS Simulazioni; requires a legal copy of Assetto Corsa EVO. Car data, field names and game files belong to Kunos and stay out of this repository. Do not publish tuned versions of Kunos' cars.
