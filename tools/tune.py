"""Settings engine of the tuner: read defaults, keep the chosen values, build and install the tuned car.

usage:
  python tools/tune.py cars     [--tested | --modded] [--game <content.kspkg>] [--mods <dir>] [--work <dir>]
  python tools/tune.py init     [--car ID] [--game <content.kspkg>] [--work <dir>]
  python tools/tune.py defaults [--car ID] [--tune ID | --variant ID] [--version ID] [--hidden] [--work <dir>]
  python tools/tune.py variants [--car ID] [--work <dir>]
  python tools/tune.py versions [--car ID] [--tune ID] [--work <dir>]
  python tools/tune.py version-add    <name> [--from ID] [--car ID] [--tune ID] [--work <dir>]
  python tools/tune.py version-rename <id|base> <name> [--car ID] [--tune ID] [--work <dir>]
  python tools/tune.py version-lock   <id> [--car ID] [--tune ID] [--work <dir>]
  python tools/tune.py version-unlock <id> [--car ID] [--tune ID] [--work <dir>]
  python tools/tune.py set      <id> <value> [--car ID] [--tune ID] [--version ID] [--work <dir>]
  python tools/tune.py unset    <id> [--car ID] [--tune ID] [--version ID] [--work <dir>]
  python tools/tune.py show     [--car ID] [--tune ID] [--version ID] [--work <dir>]
  python tools/tune.py apply    [--car ID] [--tune ID | --new-id ID] [--no-install] [--mods <dir>] [--work <dir>]
  python tools/tune.py duplicate [--car ID] [--tune ID | --draft] [--new-id ID] [--suffix TEXT] [--mods <dir>] [--work <dir>]
  python tools/tune.py tyres        [--work <dir>]
  python tools/tune.py tyre-index   [--type TYPE] [--game <content.kspkg>] [--work <dir>]
  python tools/tune.py tyre-new     --name <text> --source <path|name> [--short XX] [--game <content.kspkg>] [--work <dir>]
  python tools/tune.py tyre-show    <id> [--game <content.kspkg>] [--work <dir>]
  python tools/tune.py tyre-set     <id> <setting> <value> [--work <dir>]
  python tools/tune.py tyre-unset   <id> <setting> [--work <dir>]
  python tools/tune.py tyre-delete  <id> [--work <dir>]
  python tools/tune.py tyres-convert --name <text> [--tune ID | --draft] [--version ID] [--car ID] [--game <content.kspkg>] [--work <dir>]
  python tools/tune.py garage       [--tune ID | --draft] [--car ID] [--work <dir>]
  python tools/tune.py garage-set   <file> [--tune ID | --draft] [--car ID] [--game <content.kspkg>] [--work <dir>]
  python tools/tune.py garage-reset [--tune ID | --draft] [--car ID] [--work <dir>]
  python tools/tune.py turbo-donors [--car ID] [--work <dir>]
  python tools/tune.py turbo-add    <donor> [--tune ID | --draft] [--car ID] [--work <dir>]
  python tools/tune.py turbo-remove [--tune ID | --draft] [--car ID] [--work <dir>]
  python tools/tune.py turbo-kit    [--tune ID | --draft] [--car ID] [--work <dir>]
  python tools/tune.py sounds       [--tune ID | --draft] [--car ID] [--work <dir>]
  python tools/tune.py sound-set    <slot> <key> [--tune ID | --draft] [--version ID] [--car ID] [--work <dir>]
  python tools/tune.py sound-reset  [<slot>] [--tune ID | --draft] [--version ID] [--car ID] [--work <dir>]
  python tools/tune.py ranges       [--work <dir>]

--car ID picks any car of the game (default: the default car of tuner/cars.json); an id that is not a game car is
rejected with the closest matches. The game's cars come from system/cars.table, read once and cached in
<work>/cars_index.json (id, display_name, brand, year of every car), never refreshed by the tool: delete the file after a game update to rebuild it. When there is no cache and the game package is not
reachable, the tested cars of tuner/cars.json (a default car, a free-text "note" that no code reads, and a list of {id, label}) are the only cars.
Cars outside that list are untested: init and apply print "note: <id> is not in the tested list; results are
unverified". <car> below is the chosen stock car id, <new_id> its tuned copy (default: ax_ plus the stock id without
its ks_, e.g. ks_bmw_m3_e46_csl -> ax_bmw_m3_e46_csl; other prefixes: ax plus the id without its first two
characters; same length as the stock id).
Work folder layout: <work>/<car>/{base, build/<new_id>, snapshots/<new_id>.json, tune_state.json, stock_info.json} per car,
shared <work>/backups, <work>/stock_loc/en.cars.loc and <work>/cars_index.json. The first command that runs moves the
old single-car layout (<work>/base, build, tune_state.json, stock_info.json, defaults.json) into <work>/<default car>
and prints what moved.
Modded cars (tuned copies of a stock car; library functions list_tunes, list_modded, duplicate_tune, new_tune_from_draft):
the first one is the default tune <new_id> with the files above; every further one has its own tuned-car id (same length
as the stock id) and lives in <work>/<car>/tunes/<id>/{tune_state.json, meta.json = {"stock": <car>}}; the unsaved working
state of a stock car is <work>/<car>/draft_state.json (state functions take tune=None for the default tune, DRAFT or an id).
Every modded car of a stock car has its own name suffix; the suffix of a copy is counted up (MY -> MY 2 -> MY 3).

cars:    table of every game car sorted by display name: id, display name (stock_info.json when extracted, else the
          game's name), extracted yes/no, tested yes/no (listed in tuner/cars.json), new id, installed yes/no
          (<new_id>.kspkg in the mods folder), size of the extracted stock car. --tested lists only the tested cars.
          Without the cache and the game package (--game, default the Steam install) only the tested cars are
          listed, with a note. --modded lists the modded cars instead: id, stock car, label (stock name, a space and the suffix),
          suffix, installed yes/no (<id>.kspkg in the mods folder), built yes/no (build/<id>/<id>.kspkg).
init:    extracts the stock car from the game package into <work>/<car>/base (skipped when already there), the game's
          stock en.cars.loc into <work>/stock_loc once, and writes <work>/<car>/stock_info.json (car id, display name,
          brand, year, property_1..3 as enum names from the game's system/cars.table, variant_name = stock text of the
          car's *_preset_base line in en.cars.loc or "") when missing or incomplete. The other commands create that file
          on first need; without it the name is derived from the car's preset. Also extracts the shared tyre files the
          car names (see below) next to the car folder, into <work>/<car>/base/content/cars/common_phsx/...; defaults,
          set, show and apply do that on first need for bases extracted earlier. Without the game package the tyre
          settings are hidden ("shared tyre files not extracted").
defaults: reads every applicable setting of tuner/catalogue.json from <work>/<car>/base and prints the table. A setting is applicable when all its required targets resolve for the car; the
          others are hidden: their number is printed, --hidden lists each with its reason. When the copies of a value of
          an applicable setting disagree in the stock data, they are listed in the section "copies differ in the stock
          data" (the default shown is the value of the first required target); that is not an error.
variants: lists the other mechanical presets of the extracted stock car (library functions list_variants, variant_seed): every
          presets/*.mechanicalcarpreset except the base preset (the first in sorted order, @mech_preset) that replaces role files
          through its parts. Each part is followed like the game does: forced_compatible_part_paths and compatible_part_paths of
          the preset -> .compatiblepart -> car_part_path -> .carpart -> logic_parts[].tuning_part_path -> .tuningpart. Its
          engine, gearbox, drivetrain, clutch, setup, setup_limits and suspensions (coilover_path_front, coilover_path_rear) members
          name the replacement files, listed as the roles @engine, @gearbox, @drivetrain, @clutch, @setup, @limits, @coilover_front
          and @coilover_rear with the path relative to the car folder. Every other member (suspensions_geometry, engine_tune,
          electronics, wing, aero_package, performance_modes_tuning, brakes, brake_system) is only named as "not shown". A
          preset that replaces no role file is visual only and is not listed; a file missing or undecodable on the way is the "error"
          of that preset only. A variant = {"id": the preset file name without extension in lower case, "label": the preset's note,
          else its description, "preset": path relative to the car folder, "roles": {role: path}, "not_shown": [...], "error": text
          or None}; two tuning parts that name different files for one role are an error. The command prints id, label, roles, the
          members not shown and the error of each variant, or says that the car has none. Nothing is written.
defaults --variant ID: shows the defaults of that variant (viewing only; it cannot be combined with --tune): the stock car read
          with the role files of the variant and its preset as @mech_preset, so @turbo[N] follows the variant's engine while @car and
          @tyre_front / @tyre_rear stay those of the stock car. An unknown variant or one with an error is an error
          (resolve_defaults(..., variant=ID), only together with tune None).
versions: lists the base and the versions of a modded car (library functions list_versions, add_version, rename_version,
          load_version_state, save_version_state): a version is a further complete setup of the same modded car, shown in the game as a
          further version of that car (like a preset). The saved state of the tune is its base version; each version has its own state
          in <tune folder>/versions/<id>/{tune_state.json, meta.json = {"name": text}} (the tune folder is <work>/<car> for the default
          tune, <work>/<car>/tunes/<id> for any other; the draft has no versions). The ids are v01 .. v99 (the first free number); the
          state has the format of tune_state.json (setting ids, _turbo, _sounds, _tyres). Every setting may differ per version except
          the shared settings (kind "meta": name_suffix, variant_name, and the settings with "shared": true in the catalogue, the ones
          that live only in the .car file, which the game takes from the base for a version: steer_rod_ratio, ff_mult, steer_lock_deg,
          car_mass, arb_stiffness_front, arb_stiffness_rear, driver_aids_off; library function shared_ids): a version always uses the
          value of the base (the stock default when the base has none), the entries of its state for them are ignored on load. The name is free text: 1 to 40 characters after trimming, no control characters, unique among
          the versions of the tune ignoring case. The command prints "base: <name of the base>" ("base" for a car whose base has no name) and then "<id>: <name>" of each version ("<id>: <name> (locked)"
          for a locked one).
version-add: creates a version named <name> as a copy of the base state (--from ID: of that version's state) and prints its id. The
          shared settings are not copied. version-rename: gives a version another name (same rules, the id stays); the id base gives the base its name (the saved variant_name; no version may have it, and no version may take the name of the base, which is "Base" until set when the tune has a version).
version-lock: locks a version (library functions lock_version, unlock_version, kept_build): "locked": true in its meta.json (the other keys
          stay). Only possible when the build kept for the version (<version folder>/build/{build.json, files/}, written by apply) was made
          from the state the version has now ("Apply first, then lock it"). apply does not rebuild a locked version: the files of its kept
          build go into the package byte for byte; it cannot be changed (state, rename) until version-unlock removes the lock.
          --version ID (set, unset, show, defaults; library functions effective_rows, effective_row, changed_settings,
          unknown_state_ids, warn_unknown_state, set_value, unset_value, resolve_defaults, root_for take version=) works on the state of
          that version of the tune given by --tune (default: the default tune): the values come from the version's state (shared settings
          from the base), the defaults and the build root are those of the tune except that the turbo kit is the version's own "_turbo".
          set and unset of a shared setting refuse with "<id> is shared by all versions, set it on the base"; --version cannot be combined
          with --variant or --draft. apply builds every version into the package as a further mechanical preset of the car (see apply).
set/unset/show: edit and print <work>/<car>/tune_state.json ({setting id: value}). show lists applicable settings
          only, set refuses a setting that is not applicable to the car. Entries of the state whose id is not in the
          catalogue are ignored with a warning (show, apply) and kept in the file (remove them with unset).
          --tune ID (also accepted by defaults and apply) picks the modded car whose state is shown or changed, an id
          from cars --modded (default: the default tune <new_id>, the state file above); an unknown id is an error.
          defaults prints the stock values, which do not depend on a tune: --tune is only checked there.
          Displayed power and torque (display_power_ps, display_torque_nm) without a saved value are calculated from the engine settings
          (library functions engine_figures, engine_inputs, calculated_display): the stock displayed value x the peak power (torque) of the tune's
          engine (its power_scale, limiter, turbo_boost_<n> and turbo_wastegate_<n> and its turbo kit) / the peak of the stock engine, rounded to a
          whole number; a curve is evaluated at every rpm from 500 to the limiter, linear between its points, times 1 + the summed boost (each turbo
          gives min(max_boost, wastegate), max_boost alone without a wastegate). Offered only when it differs from the stock displayed value by
          at least 1 and every figure can be calculated; then the row of effective_rows has "calculated": true, "changed": true, and show adds
          the trailing column "calculated" to such rows (no other line changes), and apply writes the number like a saved value. A saved value (set) wins and unset goes back to it.
apply:    refuses to install while AssettoCorsaEVO.exe runs (--no-install builds anyway). Always starts from the pristine <work>/<car>/base: clones the car
          under the new id into <work>/<car>/build/<new_id>.partial, writes every changed setting into ALL its resolved
          target files, packs <new_id>.kspkg, renames the folder to build/<new_id> (a failed run keeps the previous
          build and leaves only the .partial folder, removed by the next run) and (unless --no-install) installs the
          package to the mods folder (default %USERPROFILE%\\Saved Games\\ACE\\mods) with a backup of the previous package in <work>/backups. Only changed
          settings must be applicable. For a car other than the default car, the stock info must exist. Tyres: for each
          axle (front, rear) that has at least one changed tyre setting, the stock tyre file (shared, from base) is
          copied to content/cars/<new_id>/data/tyres/<new_id>_front.tyre (_rear), the changed values are written there,
          and the references to the stock file are pointed at the copy: the entries of the .car's frontTyreCompounds
          (rearTyreCompounds) and the front_tyre_data_path (rear_tyre_data_paths) of every presets/*.compatibletyres
          that name the stock file (compared case-insensitively). Other compounds and the shared files stay untouched;
          an axle without a changed tyre setting gets no file and no changed reference. A changed tyre setting of a
          car whose tyre file is inside the car folder (not shared) is refused: not supported yet. A saved sound choice (see Sound
          picker below) is written into the car's .actor file as the last step. After that the car file of the build (the file @car
          resolves to) is renamed to data/CarData.car, the name the paint shop of a mod car expects, unless it is named cardata.car
          already (case-insensitive), with a note; every reference to it (game path content\\cars\\<new_id>\\data\\<name>.car, e.g. the
          car_data of the presets/*.carfinalstate) is rewritten by rename_files(car_root, {old path: new path}): the files of the car
          folder are decoded and only those with a changed text are written back; a file that is not decodable or holds the old path
          outside a text field is an error. The build only; the tuner reads the stock car, a turbo kit root or the base, never a build.
          Versions (library functions build_state, build_versions, merge_version): the base is built as above; each version of the tune
          (by id) is then built from its own state into <new_id>_<version>.partial with the same tune id and merged into the build, the
          temporary folder removed. A version's own files are the files of its build that differ from the base build or are missing there,
          the base mechanical preset and its carfinalstate(s), every file below data/ and every presets/*.compatibletyres
          (the files the tuner writes, so a version shares none of them with the base), plus every file that names one of them (by game path,
          repeated); the car file (data/CarData.car), the actor, the moddedcarcontent, uiresources and generated files are never among them
          (the game saves a painted version with the base's data/CarData.car, so a version has no car file of its own and its carfinalstate
          keeps naming the base's; its physics reach the car as forced car parts, see below). They are copied with
          _<version> before the extension (data/engine_v01.carengine; the carfinalstate becomes <car id>_<preset>_<version>_<visual preset the version
          uses>.carfinalstate, with <visual preset>_<version> there when the version has its own copy of the visual preset, else the base's)
          and the copies name each other; the version's preset gets the version name as note and description (a trailing Base replaced; " <version>"
          added when its slug, the description lower-cased with every run of non-word characters replaced by "_", equals another preset's) and
          is_oem false, is appended to car.customization.mechanical_car_presets of the actor and gets the thumbnails of the base preset
          (<car id>-<preset>-<visual preset>.texture/.texturemips, copied under the version preset and the visual preset the version uses). The
          visual presets its preset names (visual_preset_paths) and their car designs (car_design_path) that the actor does not list yet are
          appended to car.customization.visual_car_presets and car_designs (compatible_rims stays), and uiresources/localization/en.cars.loc
          of the build (created when the car has none) gets the line <tune id>_<slug of the preset's description>=<version name> (the game's
          menu text). The rims of the version presets (compatible_rim) that car.customization.compatible_rims and aftermarket_rims of the actor
          do not list are appended to car.customization.aftermarket_rims (the game crashes in the paint shop on a rim the actor does not list;
          the Supra MKIV's drift rim is listed there too), and when one was appended the base preset and the preset of every unlocked version
          list every other rim of the car (the base's compatible_rim and those appended) in not_compatible_rim_paths; the preset of a locked
          version is not changed. A version the game would not show or that would crash it (a visual preset not listed or missing, no
          carfinalstate presets/<car id>_<preset>_<visual preset>.carfinalstate naming the preset, no localization line; a rim of the preset or of
          its carfinalstate (rims.path) that the actor does not list, a compatible_rim missing in the build, a carfinalstate body.design that is
          not one of the preset's visual_preset_paths, a car design of a visual preset that car_designs does not list) stops the apply before
          the pack with "version <id> (<name>) would not show in the game: ..." or, for a rim, "version <id> (<name>) would crash the game: ...".
          The result lists "versions" = [{id, name, files, locked, changes}] and one note per version. After the pack each built version keeps
          its build in <version folder>/build (files/ and build.json, see store_version_build) and its own record snapshot.json with its "changes".
          A locked version (version-lock) is not built: apply copies the files of its kept build into the build (a name that is taken is
          an error), lists its preset and parts like a built one's, leaves its build/ and
          snapshot.json untouched and reports {id, name, files, locked: true, built: time of its kept build} and the note "locked, <N> files
          kept from its build of <time>"; a locked version whose kept build is missing or damaged is an error before anything is built.
          A version gets its physics and sounds as car parts of its own instead of a car file and an actor of its own (add_version_physics,
          add_version_parts): from the car file of its build the tuning parts data/parts/<new id>_<version>_<key>.tuningpart (TuningPart) for
          engine, drivetrain, gearbox, clutch, geometry (suspensions.front_suspension_path, rear_suspension_path), coilovers
          (suspensions.coilover_front_path, coilover_rear_path), brakes (brakes_path), setuplimits (setupLimits) and setup (stock_setup),
          each written only when the car file has the field(s) as text and the file(s) are among the version's copies (a file shared outside
          the car folder gives none), naming the copies. They sit in the car parts presets/parts/physics/<new id>_<version>_<kind>.carpart
          (CarPartData, description and note "<version name> <kind>", brand of the base preset; written when they have a tuning): sound (part
          type CarPartType_Mechanics_Engine: engine, and as car_audio_events the audio entries of the version's actor that differ from the
          base's, see Sound picker; a version with differing sounds but no engine tuning is refused), drivetrain
          (CarPartType_Mechanics_Differential: drivetrain, gearbox, clutch) and suspension (CarPartType_Mechanics_SuspensionGeometry_Front:
          geometry, coilovers, brakes, setuplimits, setup), each with a .compatiblepart (CompatiblePartData; bone ENGINE for the sound part
          only). The compatible parts, in the order sound, drivetrain, suspension, are listed in the forced_compatible_part_paths of the
          version's preset, in the parts of each carfinalstate of the version ({path, guid, pguid, type}, after its existing ones, in the order
          drivetrain, suspension, sound; guid = the UUID with the number b of the carfinalstate's livery_linker, a livery_linker with an a other
          than 0 is refused) and, for every version in the order of the versions, in car.customization.aftermarket_parts of the actor; the base
          preset and the preset of every unlocked version list the compatible parts of the other versions in not_compatible_part_paths (the
          preset of a locked version is never changed). A base preset that already forces a part of one of the three part types is refused
          with "version <id>: the preset of the car already forces a <part type> part (<path>)". A version the game would crash on (its
          carfinalstate's car_data or a forced part, its car part, tuning part or a file of the car folder those name missing in the build, a
          forced part that the actor's aftermarket_parts or the carfinalstate's parts do not list) is refused like a rim fault. The files
          of the parts count among the version's own files and the note "note: version <id> (<name>): own sounds <slot>=<event>, ..." tells
          differing sounds. The actor of the build is the base's. The kept build's build.json lists the compatible parts as "parts" (a
          build.json of the older form, with "sound_part", is no kept build: apply, then lock again).
          An unlocked version whose own state file holds a shared setting (not meta) with a value other than the base's effective value
          adds the note "note: version <id> (<name>): its own <setting id> <value> is ignored (shared by all versions, <base value>)".
          --tune ID builds that modded car: its own state, its id as the new id, its name suffix; --tune and --new-id
          cannot be combined. A suffix that another modded car of the same stock car uses is refused before building.
          --new-id ID alone builds the state of the tune with that id (the default tune when it is left out); an id
          that is not a modded car is refused once the stock car has modded cars, but accepted for a stock car without any
          (old "new copy" use: no state, defaults only).
          What a build reports is the change since the last build of the same modded car (library functions make_snapshot,
          load_snapshot, save_snapshot, build_changes, change_lines). After the package is packed (a failed build changes nothing),
          apply compares the build with <work>/<car>/snapshots/<new_id>.json, the record of the previous build = {"version": 1,
          "settings": {setting id: value} of the changed settings, "kit": null or {"donor", "label", "kind", "boost"}, "garage": null
          or the tyre choice {"fronts", "rears" (tyre keys), "start_front", "start_rear", "labels": {key: label}}, "sounds": {slot: option key} of the changed slots, "name", "time"}, then writes
          the record of this build (--no-install builds too) with the "changes" of this build added (the result key below; records of
          older builds lack it and are valid without it, a reader ignores its content when comparing). A missing, unreadable, damaged
          or other-version record counts as no previous build. The result key "changes" = {"since": "last build" or None (first build), "settings": [{id, from, to}] in
          catalogue order (a value set back to the default goes to the stock value), "extras": [{kind turbo_kit / garage / sound, slot
          (sound only), from, to, text}] for the turbo kit, the tyre choice and the sound slots, "total": the number of settings
          that differ from the stock car}; a first build lists everything compared to the stock car, every later one only the
          difference to the last build (floats within the tolerance of same() are equal). The result keys "applied" (all changed
          settings compared to the stock car) and "notes" are unchanged. change_lines(result) gives the lines the command and the
          server log print: the count line, one line per setting and per extra, then the notes.
duplicate: copies the saved values of a modded car (--tune SRC; default the default tune), or of the unsaved draft (--draft),
          to a new modded car of the stock car and prints its id and name suffix. --new-id picks the id (valid, same length
          as the stock id, unused; the default id <new_id> only while the default tune has neither state nor build),
          default the first free <new_id> with its last two characters replaced by 01 .. 99; --mods adds the packages in
          that folder to the ids that are taken. --suffix picks the name suffix (must not be used by another modded car of
          the stock car); default the suffix of the source, counted up when taken.
Tyre library (library functions find_tyre, list_tyres, load_tyre, create_tyre, rename_tyre, set_tyre_source, set_tyre_value,
unset_tyre_value, reset_tyre, tyre_rows, tyre_users, delete_tyre; no car needed, so these commands take no --car): a library tyre is
a single tyre: a name, a short name, a source (the game path of a .tyre file below content\\cars\\common_phsx) and the changed values
of the tyre fields relative to that source. It is kept in <work>/tyres/<id>.json = {"version": 2, "name", "short", "source",
"values": {field id: value}}; a file of version 1 (the old front/rear form) is listed with an error and must be created again. The
id is 1 to 24 characters a-z, 0-9, _ made from the name, the name is 1 to 40 characters and unique ignoring case, the short name 1 to 3
characters A-Z 0-9 (default: the first letters of the last two words of the name, or the first two letters of a single word; the
name in the game is "<name> (<short>)"). The fields (tyre_fields): first the settings of the group Tyres whose id ends _front, without
the _front: the same id (tyre_grip_lateral), the label without the word front, the front setting's type, unit, range and target
paths and its tyre_group as the group; the _rear settings are not used by the library. Then the catalogue's tyre_settings (id, group,
label, kind value or flag, type float, bool or enum, unit, description, verified, targets of the file @tyre; no min or max): "absent" (0 for a
float, false for a bool) says that the tyre file may not store the field, its default is then that value and setting another value adds
the field; setting the default again changes nothing. tyre_groups lists the groups of the fields (name, description) in display order;
tyre_group_list gives them, and tyre_fields returns the fields in that order. tyre_ranges(work, catalogue, game) reads every available tyre
once and gives the values by tyre type, cached in <work>/tyre_ranges.json while the package and the field list stay the same: {"total": tyres
read, "types": [{type, label, total}]: the types (the folder of the tyre) of the tyres read, in the order of tyre_sets.TYPE_ORDER,
unknown ones last, total = the tyres of that type read; tyre_type_list gives them, "by_type": {field id: {type: entry}}: for a float
field {low, high, count} over the tyres of the type that store it, for a bool or an enum field {values, count}: the distinct values as the
editor shows them (false before true; an enum's choice names in the order of the choices, the file stem for a path that is no choice) and
the number of tyres of the type that store the field; a bool with "absent" counts a tyre that does not store it as false in values, not in
count; a type in which no tyre stores a float or enum field, or a bool without "absent", has no entry}. tyre_rows adds the entries of a
field as "type_ranges" ({type: entry}, {} when there are none or they cannot be computed). The tyres to choose from (tyre_sets.read_index of the game package, else
the extracted tyre files) are listed by tyre-index; a source is one of them, given as its game path or its file name. The tyre
choice of a modded car is the object "_tyres" in its state file (tune_state.json, a version's tune_state.json, draft_state.json):
{"sets": [{"front": key, "rear": key}], "split": false, "start_front": key, "start_rear": key}, or with split true
{"split": true, "fronts": [key], "rears": [key], "start_front", "start_rear"}; a key is "game:<game path of a .tyre below
common_phsx>" or "own:<library tyre id>". Without split the front tyres are the fronts of the sets and the rear tyres their rears (each
once, in order); the player picks the front and the rear tyre apart. The start tyres (default: the first of each list) are the tyres
the car starts on. It is not a setting: never reported as unknown, shown in show or counted as an applied setting, and duplicate and
Create copy it with the rest of the state. No "_tyres" entry = the car is not touched; the choice of exactly the car's own sets
(stock_sets: the physic_compounds of the presets of the car's own base, as game keys) removes the entry. An old saved list of
"stock:<front>|<rear>" entries is read as sets; an old entry with an "own:" key is an error (choose the tyres again), a damaged
entry too. Library functions tyre_choices, set_tyres, reset_tyres, stock_sets. tyre-delete refuses while a state, a version or the
draft lists the library tyre. apply with a choice writes data/tyres/own_<id>.tyre (the source file with the changed values, "name"
and "shortName" set) of every own tyre into the car, the physic_compounds and graphic_compounds of every presets/*.compatibletyres
from the tyres (tyre_sets.build_compounds), and the start tyre of each wheel into the setup file (alignments[i].compound, index in
the front or rear list; wheels 0 and 1 front, 2 and 3 rear) and the highest index into the setup limits file
(alignments[i].compound.max, is_modifiable true); the .car file's tyre lists are not changed. A state with a choice and saved values
of the tyre settings of the car (tyre_*_front, tyre_*_rear) is refused before anything is written; a car without setup files for the
start tyre too. Whether the game takes the result is tested for the choice and the start tyre, not for own tyres.
tyres:        lists the library: id, name, short, source, number of changed values; a damaged or old file is listed with its error.
tyre-index:   lists the tyres to choose from: label, file, type; --type keeps one type (the folder name or its label). Without the
          game package only the extracted tyre files are listed.
tyre-new:     creates a library tyre from a game path or file name of tyre-index (--short sets the short name) and prints its id.
tyre-show:    prints the tyre fields with their value, the default read from the source file and the unit; changed ones are marked *; a field whose default cannot be read from the source file is listed with the reason.
tyre-set/tyre-unset: change or remove one value of a library tyre; set refuses an id that is not a tyre field.
tyres-convert: turns the saved values of the old Tyres section of a state (the 24 settings tyre_*_front, tyre_*_rear; library function
          convert_tyres) into library tyres and a tyre choice, and removes them from the state (--tune, --draft, --version pick the
          state, default: the base of the default tune). Per axle the values saved for it go into an own tyre named "<name> front" /
          "<name> rear" (" 2", " 3" ... appended while the name is taken), made from the tyre file the settings act on (the first front /
          rear tyre of the car file in the car's base); an own tyre with the same source and values is used again instead of a new
          one. An axle without saved values stays on that file as a game tyre. The choice has the converted pair as first set and as
          start tyres, then the stock sets of the car that differ from it. Refused: a state with a tyre choice ("reset the tyre
          values or the choice first"), without saved tyre values, a locked version, a source that cannot be read. The command
          prints what was created or used per axle, the number of sets and the start tyres. set refuses these 24 settings ("tyre values
          are edited in the Tyre Creator: choose or create a tyre there"); a saved value is still applied (apply adds a note
          that names tyres-convert) and unset removes it. The settings carry "ui": "hidden", so the page shows no Tyres group.
tyre-delete:  removes a library tyre that no modded car uses.
garage:       shows the tyre choice of the car: the sets, the front and the rear tyres with the start tyre, or the default (the car's
          own tyres). The commands take --car, --tune and --draft like show.
garage-set:   sets the choice from a JSON file with the object of "_tyres" above; every key is checked (a game tyre of tyre-index,
          a library tyre). The car's own choice is the default and removes the entry.
garage-reset: removes the choice (the car is not touched any more).
Turbo kit (library functions has_turbo, turbo_kind, list_turbo_donors, turbo_choice, set_turbo, reset_turbo): a modded car without a
turbo can take the turbo setup of a donor, an installed car whose engine lists turbo files. The choice is the object "_turbo" =
{"donor": <stock car id of the donor>} in the state file (tune_state.json, draft_state.json). Like "_tyres" it is not a setting: never
reported as unknown, shown in show or counted as an applied setting, and duplicate and Create copy it with the rest of the state; no
"_turbo" entry = the car is not touched. A donor is an extracted car (base folder present) whose engine (@engine) lists turbos_to_load
files that are all present in its base; turbo_listing reads the files, their number and the max_boost of each turbo file (the
engine's turbos list stands in when a file gives none and the list has a number for every file; boost_ref is the engine's
max_turbo_boost when no boost is known).
turbo-donors: lists the donors (car id, name, kind: no turbo / single turbo / twin turbo / <n> turbos, boost in bar); with --car it adds the
          kit the car has chosen in its default tune ("chosen: <donor>" or "no turbo kit chosen"). It extracts nothing.
turbo-add:    chooses the donor for a car that has no turbo itself and has been extracted; turbo-remove removes the choice.
Kit root (library functions kit_root, root_for): a car with a saved kit is read and built from <work>/<car>/kit/<donor>/, a complete tree like base
for that one car and donor: base linked file by file (hard links, copied where the file system refuses), the donor's turbo files added as
data/kit_turbo_<n>.turbo (turbos_to_load of the engine points at them, written like the donor's entries with the car's own id), and every
top-level engine field whose name has "turbo", "boost" or "bov" in it copied from the donor's engine file, the same fields of the inline
engine block of the .car when the donor's .car has one and the car's too. A patched file is always written as a new file, never into a
link, so base stays as it is. kit.json in the kit root names what was added and copied and the size and time of every file the kit depends
on; a kit whose inputs changed is built again on the next use (a failed build leaves no kit). root_for(work, car, tune) is the kit root of a
tune whose state has "_turbo" and base otherwise; resolve_defaults reads it for a tune, set, show and apply use it, the turbo settings of
the catalogue then resolve against the donor's values, and apply builds from it and adds the notes "note: turbo kit: ...".
turbo-kit:    builds or refreshes the kit root of the tune (or draft) and prints it with the kind of kit, the files and the engine and .car fields.
Sound picker (module tools/sounds.py, library functions sound_options, sound_own, sound_choices, set_sound, reset_sounds): a modded car can take the
turbo sound and the backfire sound of any installed car. The slots are turbo (audio entry type TurboEvent) and backfire (type Backfire) in the
car's <id>.actor file; entries are found by their type, never by position (the order differs from car to car). A sound is an option named by its
key: the event text (event:/parts/turbos/turbo_rx7), with #<optionalParam> appended when the entry has an optionalParam other than 0. The choice is
the object "_sounds" = {"turbo": <option key>, "backfire": <option key>} in the state file (tune_state.json, draft_state.json); a missing slot or
no "_sounds" entry = the car keeps its own sound. Like "_tyres" and "_turbo" it is not a setting: never reported as unknown, shown in show or
counted as an applied setting, and duplicate and Create copy it with the rest of the state; Reset all drops it. apply writes the choice into the
<new id>.actor of the built car after all other steps (library functions sound_plan, write_sounds): only the entry of the slot changes (event, bank,
optionalParam; a car without an entry of the slot gets a copy of the entry of the first installed car that offers the sound), a slot equal to the
car's own sound changes nothing, and each changed slot adds the note "note: sound <slot>: <old key> -> <new key>" ("- added <key>" for an appended
entry) and an item {slot, from, to, added} to the "sounds" list of the apply result. A saved sound that is not offered any more, or a slot that does
not exist, refuses the apply before anything is built. The options are read from the .actor file of every car with an extracted base; a car whose
file is missing or cannot be decoded is skipped and reported. The TurboEvent and Backfire entries in the car_audio_events of the logic parts of the
presets/parts/**/*.carpart files of a car (e.g. event:/parts/turbos/turbo_supra_tuned of the Supra MKIV's tuned engine) are options too, listed with
that car and chosen like any other (sound_events; a .carpart that cannot be decoded skips the car); the cache of a car's sounds is keyed by the file
stamps of its actor and its car parts. sound-set and sound-reset take --version ID: the choice of that version of the tune (see Versions).
sounds:       lists per slot "<slot> (own: <key or none>, selected: <key or ->)" and one line per option: a mark (* selected, = the car's own
          sound, else blank), the key and the cars that use it (at most 4, then +N more); the none sound comes first, then by event name. A saved
          sound that is not offered any more is a warning.
sound-set:    chooses the option with the given key for a slot (turbo or backfire); the car's own sound removes the choice of the slot.
sound-reset:  removes the choice of one slot, or of every slot without an argument.
ranges:       the soft borders for the settings page (library functions compute_ranges, write_ranges, load_ranges): reads the
          defaults of every car with an extracted base in the work folder (every <work>/<car>/base) and writes the lowest and
          highest default of every numeric setting (kind value, type int or float; a field a car does not store does not
          count) to <work>/ranges.json = {setting id: {"low", "high"}}, never reading the game package. A value outside the
          range is allowed. Prints how many cars were read, how many were skipped and how many settings got a range; each
          skipped car (its defaults cannot be resolved) is listed on stderr and does not change the exit code. Without any
          readable car it fails and writes nothing. load_ranges gives {} for a missing or damaged file.
<work> defaults to %USERPROFILE%\\ace_modded_cars_work. --game is accepted by cars and init only; the other commands use the default Steam path of the game package for what they extract on first need. Writes nothing outside <work> and the mods folder. File
operations on car trees use extended-length paths (kspkg.long_path), so deep Windows paths work.

Catalogue settings: id, group, label, kind (value, curve_scale, meta, flag), type (int, float, string, enum, bool), unit, description and verified are required. shared (optional, only true) marks a setting that all versions of a modded car share: it is edited on the base only (shared_ids). min/max are a suggested range (a value outside it only gives a warning). Kind value writes the value into all its targets; the default is read from the first required target. Kind curve_scale has a default factor and curve_from (file role and path of a curve file name); apply multiplies the value of every point of that curve by the factor. Kind meta needs a handler (variant_name, name_suffix) and a default or a default_template (text with {stock_display_name} and {stock_variant_name}, replaced by the stock display name and the stock variant text). An enum lists its choices.

Catalogue field paths (inside the JSON that car_json decodes): dot-separated names, name[3] = list element by index,
name[key=VALUE] = the list element whose field key equals VALUE, name[*] = every element of the list (all existing
elements; the default and the consistency check read all of them and require them equal, like several targets; an
empty or absent list resolves to nothing, so a required target makes the setting not applicable), e.g. gears[1].ratio,
car_specs.items[key=CarSpecs_KeyEnum_POWER].value or performance_modes[*].electronics_settings.tc1. A missing last
field reads as the proto3 default (flagged absent) and is created on write; missing objects on the way are created on
write; a missing list element is an error. A setting with "create_missing": true also counts missing objects on the
way as resolved-absent (value = default 0) and creates them on write; without it they make the setting not applicable.

Catalogue target files ("file" of a target and of curve_from) are roles, resolved per car and case-insensitively from
its .car manifest: @engine, @drivetrain, @gearbox, @clutch, @brakes (engine_path ... brakes_path), @setup
(stock_setup), @limits (setupLimits), @coilover_front, @coilover_rear (suspensions.coilover_front_path and
suspensions.coilover_rear_path, the standalone .coilover files), @car (the .car file in data; with several, the one
that decodes as CarData and has engine_path), @mech_preset (first presets/*.mechanicalcarpreset in sorted order),
@turbo[N] (the file named by turbos_to_load[N] of the engine file), @tyre_front, @tyre_rear (the .tyre file named by
frontTyreCompounds[0] / rearTyreCompounds[0] of the .car; a shared game file in <base>/content/cars/common_phsx, reached
as "../common_phsx/..." relative to the car folder; apply never writes to it, see apply). A target with
"optional": true is written when it resolves and skipped otherwise; every other target is required. A setting is applicable to a car when all its required
targets resolve (an absent last field counts as resolved, a missing object or list element on the way does not).
"needs" is a list of further targets that must resolve for the setting to be applicable but are never written and not
compared. "hide_if_absent": true hides the setting when the last field of all its required targets is absent in the
stock data. Settings of kind "flag" have type bool, the default false and a fixed "value" (a number, 0 for the driver
aids switch): when a flag is true, apply writes that value into all its resolved targets (wildcards allowed, targets may
be optional) and nothing when it is false; a target whose field is absent in the data is skipped when the value is 0
(absent already reads as 0). The targets of a flag are neither compared nor give a default. Flags are applied after all
other settings, so a flag wins over a value on the same field. set accepts true/false, yes/no, 1/0, on/off for bool
(case-insensitive). An enum setting with "choice_values" (choice -> text) stores text in its field: the default is the
choice whose text equals the field (case-insensitive, slash and backslash alike; any other text makes the setting not
applicable), apply writes the text of the chosen choice. meta settings: variant_name, applicable only when the stock car has a variant name, and name_suffix (default MY, trimmed, runs of inner spaces
collapsed to one, then 1 to 30 characters without control characters): apply names the tuned car "<stock display name>
<name_suffix>" (stock display name from stock_info.json, else the car's mechanical preset, one space, the suffix), so the
default lists it next to the stock car. A suffix saved by the old version (MY or MY and a number, behind an
underscore) reads as MY, MY 2, ... (legacy_suffix); any other saved value is kept as it is. "ui": "header" on a setting is only a hint
for the web page (it shows the setting in its header, not in the table), "ui": "hidden" a hint to show it nowhere in the table (variant_name: the base gets its name through version-rename base; the 24 tyre settings of the old Tyres section). "advanced": true is a hint for the web page too:
it hides the setting unless the user ticks "show advanced settings" or the setting is changed; it has no effect on apply.

Stdlib only. Needs schemas/acevo.desc (see tools/extract_protos.py).
"""
import contextlib
import copy
import datetime
import difflib
import filecmp
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import threading
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import car_json  # noqa: E402
import clone_car  # noqa: E402
import kspkg  # noqa: E402
import sounds  # noqa: E402
import tyre_sets  # noqa: E402
from kspkg import parse_args  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
CATALOGUE = REPO / "tuner" / "catalogue.json"
CARS_JSON = REPO / "tuner" / "cars.json"
DEFAULT_WORK = "%USERPROFILE%\\ace_modded_cars_work"
DEFAULT_GAME = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Assetto Corsa EVO\\content.kspkg"
GAME_MISSING = ("game package not found: %s (is Assetto Corsa EVO installed? if it is in another Steam library, "
                "pass --game <path of content.kspkg>; start_tuner.bat has a GAME line for it)")
GAME_EXE = "AssettoCorsaEVO.exe"
OLD_LAYOUT = ("base", "build", "tune_state.json", "stock_info.json", "defaults.json")
TUNES = "tunes"
DRAFT = "draft"
VERSIONS = "versions"
VERSION_ID = re.compile(r"v(?:0[1-9]|[1-9]\d)")
VERSION_NAME_MAX = 40
BASE_NAME = "Base"
CALCULATED_SETTINGS = {"display_power_ps": 0, "display_torque_nm": 1}
CALCULATED_MIN_RPM = 500
CARS_TABLE = "system\\cars.table"
STOCK_LOC = "\\".join(clone_car.LOC_PATH)
STOCK_PROPERTIES = ("property_1", "property_2", "property_3")
# apply fallback for the default car when stock_info.json is missing and the game is not reachable: the values of the BMW M3 E46 CSL
CLONE_YEAR, CLONE_BRAND = clone_car.DEFAULT_YEAR, clone_car.DEFAULT_BRAND
NAME_SUFFIX_MAX = 30
LEGACY_SUFFIX = re.compile(r"_MY(\d*)")
PATH_STEP = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)((?:\[[^\]]*\])*)")
PATH_SELECTOR = re.compile(r"\[([^\]]*)\]")
GROUP_DESCRIPTION_MAX = 360
KINDS = ("value", "curve_scale", "meta", "flag")
VALUE_TYPES = ("int", "float", "string", "enum", "bool")
HANDLERS = ("variant_name", "name_suffix")
BOOL_WORDS = {"true": True, "yes": True, "1": True, "on": True, "false": False, "no": False, "0": False, "off": False}
REQUIRED = ("id", "group", "label", "kind", "type", "unit", "description", "verified")
MANIFEST_ROLES = {"engine": "engine_path", "drivetrain": "drivetrain_path", "gearbox": "gearbox_path",
                  "clutch": "clutch_path", "brakes": "brakes_path", "setup": "stock_setup", "limits": "setupLimits",
                  "coilover_front": "suspensions.coilover_front_path",
                  "coilover_rear": "suspensions.coilover_rear_path"}
VARIANT_PATHS = {"engine": "@engine", "gearbox": "@gearbox", "drivetrain": "@drivetrain", "clutch": "@clutch",
                 "setup": "@setup", "setup_limits": "@limits"}
VARIANT_COILOVERS = {"coilover_path_front": "@coilover_front", "coilover_path_rear": "@coilover_rear"}
TUNING_MEMBERS = ("engine_tune", "engine", "gearbox", "drivetrain", "clutch", "brakes", "brake_system", "electronics",
                  "suspensions", "suspensions_geometry", "wing", "aero_package", "setup", "setup_limits",
                  "performance_modes_tuning")
TYRE_ROLES = {"tyre_front": "frontTyreCompounds", "tyre_rear": "rearTyreCompounds"}
ROLE = re.compile(r"@(car|mech_preset|%s|turbo\[\d+\])" % "|".join(list(MANIFEST_ROLES) + list(TYRE_ROLES)))
SHARED_DIR = "common_phsx"
SHARED = "../%s/" % SHARED_DIR
GAME_SHARED = "content\\cars\\%s\\" % SHARED_DIR
TYRE_UNAVAILABLE = "shared tyre files not extracted"
TYRES_DIR = "tyres"
TYRE_KEY = "_tyres"
TURBO_KEY = "_turbo"
SOUND_KEY = "_sounds"
SOUND_PART_TYPE = "CarPartType_Mechanics_Engine"
VERSION_PARTS = (("sound", SOUND_PART_TYPE, ("engine",)),
                 ("drivetrain", "CarPartType_Mechanics_Differential", ("drivetrain", "gearbox", "clutch")),
                 ("suspension", "CarPartType_Mechanics_SuspensionGeometry_Front", ("geometry", "coilovers", "brakes", "setuplimits", "setup")))
TUNING_SPECS = (("engine", "", ("engine_path",), "engine", ("path",), SOUND_PART_TYPE),
                ("drivetrain", "", ("drivetrain_path",), "drivetrain", ("path",), "CarPartType_Mechanics_Drivetrain"),
                ("gearbox", "", ("gearbox_path",), "gearbox", ("path",), "CarPartType_Mechanics_Gearbox"),
                ("clutch", "", ("clutch_path",), "clutch", ("path",), "CarPartType_Mechanics_Clutch"),
                ("geometry", "suspensions", ("front_suspension_path", "rear_suspension_path"), "suspensions_geometry",
                 ("geometry_path_front", "geometry_path_rear"), "CarPartType_Mechanics_SuspensionGeometry_Front"),
                ("coilovers", "suspensions", ("coilover_front_path", "coilover_rear_path"), "suspensions",
                 ("coilover_path_front", "coilover_path_rear"), "CarPartType_Mechanics_SuspensionCoilover_Front"),
                ("brakes", "", ("brakes_path",), "brake_system", ("path",), None),
                ("setuplimits", "", ("setupLimits",), "setup_limits", ("path",), None),
                ("setup", "", ("stock_setup",), "setup", ("path",), None))
KIT_DIR = "kit"
SNAPSHOT_DIR = "snapshots"
SNAPSHOT_VERSION = 1
KIT_JSON = "kit.json"
KIT_WORDS = ("turbo", "boost", "bov")
TYRE_ID_MAX = 24
TYRE_ID = re.compile(r"[a-z0-9_]{1,%d}" % TYRE_ID_MAX)
TYRE_NAME_MAX = 40
TYRE_VERSION = 2
TYRE_SHORT = re.compile(r"[A-Z0-9]{1,3}")
TYRE_FILES = tuple("@" + r for r in TYRE_ROLES)
OWN_KEY = "own:"
GAME_KEY = "game:"
STOCK_KEY = "stock:"
OWN_TYRE_REL = "data/tyres/own_%s.tyre"
CHOICE_FIELDS = ("sets", "split", "fronts", "rears", "start_front", "start_rear")
DAMAGED_CHOICE = "damaged tyre choice in the saved state"
OLD_CHOICE = "the saved tyre choice was made before the tyre rebuild: choose the tyres again"
TYRE_VALUES_REFUSED = "tyre values are edited in the Tyre Creator: choose or create a tyre there"
CONVERT_CHOICE = "this car has a tyre choice already: reset the tyre values or the choice first"
CONVERT_NONE = "no saved tyre values to convert"
RANGES_FILE = "ranges.json"
TYRE_RANGES_FILE = "tyre_ranges.json"
TYRE_RANGES_VERSION = 3
CAR_FILE = "data/CarData.car"
VERSION_SKIP_FOLDERS = ("uiresources/", "generated/")
VERSION_SKIP_TYPES = (".actor", ".moddedcarcontent")

_index_error = []
_tyre_lock = threading.Lock()
_resolve_lock = threading.Lock()
_resolved = {}
_donor_listings = {}
_actor_options = {}
_engine_inputs = {}
_ranges_lock = threading.Lock()
_ranges_loaded = {}
_tyre_ranges_lock = threading.Lock()
_tyre_ranges_loaded = {}
_catalogue_lock = threading.Lock()
_catalogue_loaded = {}
_stdout_lock = threading.Lock()
_kit_lock = threading.Lock()


def quietly(func, *args):
    """Run func(*args) with stdout swallowed: kspkg and clone_car print their progress, which must not reach this command's output."""
    with _stdout_lock, contextlib.redirect_stdout(io.StringIO()):
        return func(*args)


def work_dir(arg=None):
    return clone_car.expand_dir(arg, DEFAULT_WORK, "work directory", "--work")


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + GAME_EXE, "/NH", "/FO", "CSV"],
                             capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and GAME_EXE.lower() in out.stdout.decode("ascii", "replace").lower()


def resolve_inside(root, path):
    root, path = os.path.realpath(root), os.path.realpath(path)
    if os.path.commonpath([root, path]) != root:
        raise ValueError("%s is not inside %s" % (path, root))
    return path


def remove_tree(work, path):
    if resolve_inside(work, path) == os.path.realpath(work):
        raise ValueError("refusing to remove the work directory itself")
    shutil.rmtree(kspkg.long_path(path))


def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except ValueError as e:
        raise ValueError("%s: %s" % (path, e)) from None


def load_cars(path=CARS_JSON):
    data = read_json(path)
    cars = data.get("cars") if isinstance(data, dict) else None
    if not isinstance(cars, list) or not cars or not isinstance(data.get("default"), str):
        raise ValueError("%s: needs default and a list of cars" % path)
    ids = []
    for c in cars:
        if not (isinstance(c, dict) and isinstance(c.get("id"), str) and re.fullmatch(r"[a-z0-9_]+", c["id"])
                and isinstance(c.get("label"), str) and c["label"]):
            raise ValueError("%s: every car needs an id (a-z, 0-9, _) and a label" % path)
        ids.append(c["id"])
    if len(set(ids)) != len(ids) or data["default"] not in ids:
        raise ValueError("%s: car ids must be unique and include the default" % path)
    return data


def pick_car(cars, car_id=None, index=None):
    car_id = car_id or cars["default"]
    if index is None:
        known = [c["id"] for c in cars["cars"]]
        if car_id not in known:
            raise ValueError("unknown car %r, the car list of the game is not available%s, the tested cars "
                             "(tuner/cars.json) are: %s" % (car_id, " (reason: %s)" % _index_error[0] if _index_error else "",
                                                            ", ".join(known)))
    else:
        known = [c["id"] for c in index]
        if car_id not in known:
            close = difflib.get_close_matches(car_id, known, n=5, cutoff=0.6)
            raise ValueError("unknown car %r, %s" % (car_id, "close matches: " + ", ".join(close) if close else
                                                     "the game has %d cars, tune.py cars lists them" % len(known)))
    return car_id


def new_id_for(car_id):
    return "ax_" + car_id[3:] if car_id.startswith("ks_") else "ax" + car_id[2:]


def car_work(work, car_id):
    return os.path.join(work, car_id)


def base_dir(work, car_id):
    return os.path.join(car_work(work, car_id), "base")


def build_dir(work, car_id):
    return os.path.join(car_work(work, car_id), "build")


def stock_loc_path(work):
    return os.path.join(work, "stock_loc", "en.cars.loc")


def migrate_old_layout(work, default_car):
    """Move the single-car layout of the first version into <work>/<default car>; returns the moved names."""
    dst = car_work(work, default_car)
    if not os.path.isdir(kspkg.long_path(os.path.join(work, "base"))) or os.path.exists(kspkg.long_path(dst)):
        return []
    os.makedirs(kspkg.long_path(dst))
    moved = []
    for name in OLD_LAYOUT:
        src = os.path.join(work, name)
        if os.path.exists(kspkg.long_path(src)):
            os.rename(kspkg.long_path(src), kspkg.long_path(os.path.join(dst, name)))
            moved.append(name)
    return moved


def save_json(path, data):
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".tmp"
    try:
        with open(part, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(part, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(part)
        raise


def check_groups(cat, path, key="groups"):
    """The group names of the catalogue list key (groups, or tyre_groups) in order; ValueError for a damaged or missing group list."""
    names = []
    for g in cat.get(key) if isinstance(cat.get(key), list) else []:
        if not (isinstance(g, dict) and isinstance(g.get("name"), str) and g["name"]
                and isinstance(g.get("description"), str) and 0 < len(g["description"]) <= GROUP_DESCRIPTION_MAX):
            raise ValueError("%s: every %s needs a name and a description (text of 1 to %d characters)"
                             % (path, "group" if key == "groups" else "tyre group", GROUP_DESCRIPTION_MAX))
        if any(ord(c) < 32 or ord(c) == 127 for c in g["name"] + g["description"]):
            raise ValueError("%s: group %r has a tab, a newline or another control character in its name or description"
                             % (path, g["name"]))
        if g["name"] in names:
            raise ValueError("%s: duplicate group name %r" % (path, g["name"]))
        names.append(g["name"])
    if not names:
        raise ValueError("%s: needs %s, a list of name and description" % (path, key))
    return names


def check_setting_kind(s, path):
    if s["kind"] not in KINDS or s["type"] not in VALUE_TYPES:
        raise ValueError("%s: setting %r has an unknown kind or type" % (path, s["id"]))
    if (s["kind"] == "flag") != (s["type"] == "bool"):
        raise ValueError("%s: setting %r: kind flag and type bool belong together" % (path, s["id"]))
    if s["kind"] in ("value", "flag") and not (s.get("targets") and all("file" in t and "path" in t
                                                                          for t in s["targets"])):
        raise ValueError("%s: setting %r needs targets with file and path" % (path, s["id"]))
    if s["kind"] == "flag" and type(s.get("value")) not in (int, float):
        raise ValueError("%s: setting %r needs a numeric value to write" % (path, s["id"]))
    if type(s.get("create_missing", False)) is not bool:
        raise ValueError("%s: setting %r has a create_missing that is not true or false" % (path, s["id"]))


def check_setting_options(s, path):
    cv = s.get("choice_values")
    if cv is not None and not (s["type"] == "enum" and isinstance(cv, dict) and set(cv) == set(s.get("choices", []))
                               and all(isinstance(x, str) and x for x in cv.values())):
        raise ValueError("%s: setting %r needs choice_values to be an enum's text for every choice"
                         % (path, s["id"]))
    if s["kind"] == "curve_scale" and not ("default" in s and {"file", "path"} <= set(s.get("curve_from", {}))):
        raise ValueError("%s: setting %r needs default and curve_from with file and path" % (path, s["id"]))
    needs = s.get("needs", [])
    if not (isinstance(needs, list)
            and all(isinstance(t, dict) and isinstance(t.get("file"), str) and isinstance(t.get("path"), str)
                    for t in needs)):
        raise ValueError("%s: setting %r has needs that is not a list of targets with file and path"
                         % (path, s["id"]))
    if type(s.get("hide_if_absent", False)) is not bool:
        raise ValueError("%s: setting %r has a hide_if_absent that is not true or false" % (path, s["id"]))
    if type(s.get("advanced", False)) is not bool:
        raise ValueError("%s: setting %r has an advanced that is not true or false" % (path, s["id"]))
    if "shared" in s and s["shared"] is not True:
        raise ValueError("%s: setting %r has a shared that is not true" % (path, s["id"]))


def check_setting_files(s, path):
    files = ([t["file"] for t in s.get("targets", [])] + [t["file"] for t in s.get("needs", [])]
             + ([s["curve_from"]["file"]] if s["kind"] == "curve_scale" else []))
    for f in files:
        if f.startswith("@") and not ROLE.fullmatch(f):
            raise ValueError("%s: setting %r has an unknown file role %r" % (path, s["id"], f))
    if not all(type(t.get("optional", False)) is bool for t in s.get("targets", [])):
        raise ValueError("%s: setting %r has a target whose optional is not true or false" % (path, s["id"]))
    if s["kind"] == "meta" and not (s.get("handler") in HANDLERS
                                    and (isinstance(s.get("default"), str) or isinstance(s.get("default_template"), str))):
        raise ValueError("%s: setting %r needs a handler (%s) and a string default or default_template"
                         % (path, s["id"], "/".join(HANDLERS)))


def check_setting(s, seen, names, path):
    missing = [k for k in REQUIRED if k not in s]
    if missing:
        raise ValueError("%s: setting %r misses %s" % (path, s.get("id"), ", ".join(missing)))
    if s["id"] in seen:
        raise ValueError("%s: duplicate setting id %r" % (path, s["id"]))
    seen.add(s["id"])
    check_setting_kind(s, path)
    check_setting_options(s, path)
    check_setting_files(s, path)
    if s["group"] not in names:
        raise ValueError("%s: setting %r has the group %r, which is not listed in groups" % (path, s["id"], s["group"]))


def derived_tyre_ids(cat):
    """The ids of the fields tyre_fields derives from the settings (the group Tyres, id ending _front, without _front)."""
    return [s["id"][:-len("_front")] for s in cat["settings"] if s.get("group") == "Tyres" and s["id"].endswith("_front")]


def check_tyre_setting(s, seen, names, path):
    missing = [k for k in REQUIRED if k not in s]
    if missing:
        raise ValueError("%s: tyre setting %r misses %s" % (path, s.get("id"), ", ".join(missing)))
    if s["id"] in seen:
        raise ValueError("%s: duplicate tyre setting id %r" % (path, s["id"]))
    seen.add(s["id"])
    if s["kind"] not in ("value", "flag") or s["type"] not in ("float", "bool", "enum") or (s["kind"] == "flag") != (s["type"] == "bool"):
        raise ValueError("%s: tyre setting %r needs kind value with type float or enum, or kind flag with type bool" % (path, s["id"]))
    targets = s.get("targets")
    if not (isinstance(targets, list) and targets and all(isinstance(t, dict) and t.get("file") == "@tyre" and isinstance(t.get("path"), str)
                                                          for t in targets)):
        raise ValueError("%s: tyre setting %r needs targets with the file @tyre and a path" % (path, s["id"]))
    for t in targets:
        try:
            parse_path(t["path"])
        except ValueError as e:
            raise ValueError("%s: tyre setting %r: %s" % (path, s["id"], e)) from None
    if s["type"] == "enum" and not (isinstance(s.get("choices"), list) and s["choices"] and isinstance(s.get("choice_values"), dict)):
        raise ValueError("%s: tyre setting %r needs choices and choice_values" % (path, s["id"]))
    if "absent" in s and not ((s["type"] == "float" and type(s["absent"]) in (int, float) and s["absent"] == 0)
                              or (s["type"] == "bool" and s["absent"] is False)):
        raise ValueError("%s: tyre setting %r has an absent that is not 0 for a float or false for a bool" % (path, s["id"]))
    check_setting_options(dict(s, kind="value"), path)
    if s["group"] not in names:
        raise ValueError("%s: tyre setting %r has the group %r, which is not listed in tyre_groups" % (path, s["id"], s["group"]))


def check_tyre_catalogue(cat, seen, path):
    """Validate tyre_groups, tyre_settings and the tyre_group of the settings (all optional; seen: the ids of the settings)."""
    grouped = [s["id"] for s in cat["settings"] if "tyre_group" in s]
    if "tyre_groups" not in cat and "tyre_settings" not in cat:
        if grouped:
            raise ValueError("%s: setting %r has a tyre_group, but the catalogue has no tyre_groups" % (path, grouped[0]))
        return
    if not isinstance(cat.get("tyre_settings"), list):
        raise ValueError("%s: needs tyre_settings, a list, together with tyre_groups" % path)
    names = check_groups(cat, path, "tyre_groups")
    taken = set(seen) | set(derived_tyre_ids(cat))
    used = set()
    for s in cat["settings"]:
        if s.get("group") == "Tyres" and s["id"].endswith("_front") and "tyre_group" not in s:
            raise ValueError("%s: setting %r needs a tyre_group, the catalogue has tyre_groups" % (path, s["id"]))
        if "tyre_group" in s:
            if s["tyre_group"] not in names:
                raise ValueError("%s: setting %r has the tyre_group %r, which is not listed in tyre_groups" % (path, s["id"], s["tyre_group"]))
            used.add(s["tyre_group"])
    own = set()
    for s in cat["tyre_settings"]:
        if not isinstance(s, dict) or "id" not in s:
            raise ValueError("%s: every tyre setting needs an id" % path)
        if s["id"] in taken:
            raise ValueError("%s: duplicate tyre setting id %r (a setting or a tyre field has it already)" % (path, s["id"]))
        check_tyre_setting(s, own, names, path)
        used.add(s["group"])
    unused = [n for n in names if n not in used]
    if unused:
        raise ValueError("%s: group %r is listed in tyre_groups but no tyre field uses it" % (path, unused[0]))


def load_catalogue(path=CATALOGUE):
    """The validated catalogue at path, parsed again only when the file's (mtime_ns, size) changed. The caller gets the shared
    object and must not change it; a catalogue that fails the validation is never kept."""
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return read_catalogue(path)
    stamp = (st.st_mtime_ns, st.st_size)
    with _catalogue_lock:
        hit = _catalogue_loaded.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    cat = read_catalogue(path)
    with _catalogue_lock:
        _catalogue_loaded[key] = (stamp, cat)
    return cat


def read_catalogue(path):
    cat = read_json(path)
    if not isinstance(cat.get("settings"), list):
        raise ValueError("%s: needs settings" % path)
    names = check_groups(cat, path)
    seen = set()
    for s in cat["settings"]:
        check_setting(s, seen, names, path)
    used = {s["group"] for s in cat["settings"]}
    unused = [n for n in names if n not in used]
    if unused:
        raise ValueError("%s: group %r is listed in groups but no setting uses it" % (path, unused[0]))
    check_tyre_catalogue(cat, seen, path)
    return cat


def group_list(catalogue=None):
    """The setting groups of the catalogue in display order, as copies of {"name", "description"}."""
    return [{"name": g["name"], "description": g["description"]} for g in (catalogue or load_catalogue())["groups"]]


def find_setting(cat, setting_id):
    for s in cat["settings"]:
        if s["id"] == setting_id:
            return s
    raise ValueError("unknown setting %r" % setting_id)


def check_tune_id(work, car_id, tune):
    if not isinstance(tune, str):
        raise ValueError("tune id must be text, got %r" % (tune,))
    clone_car.check_id(car_id, tune)


def is_default_tune(car_id, tune):
    return tune is None or tune == new_id_for(car_id)


def is_extra_tune(car_id, tune):
    """A modded car other than the default tune and the draft: its files live in <car>/tunes/<id>."""
    return not (is_default_tune(car_id, tune) or tune == DRAFT)


def tune_dir(work, car_id, tune):
    """Folder of the state file of a tune: the car folder for the default tune (None or new_id_for) and for the draft,
    <car>/tunes/<id> for any other tuned-car id (which must be valid for the car)."""
    if not is_extra_tune(car_id, tune):
        return car_work(work, car_id)
    check_tune_id(work, car_id, tune)
    return os.path.join(car_work(work, car_id), TUNES, tune)


def state_path(work, car_id, tune=None):
    return os.path.join(tune_dir(work, car_id, tune), "draft_state.json" if tune == DRAFT else "tune_state.json")


def load_state(work, car_id, tune=None):
    path = state_path(work, car_id, tune)
    if not os.path.exists(path):
        return {}
    state = read_json(path)
    if not isinstance(state, dict):
        raise ValueError("%s: expected an object" % path)
    return state


def save_state(work, car_id, state, tune=None):
    path = state_path(work, car_id, tune)
    save_json(path, state)
    meta = os.path.join(os.path.dirname(path), "meta.json")
    if is_extra_tune(car_id, tune) and not os.path.exists(meta):
        save_json(meta, {"stock": car_id})


def unknown_state_ids(work, car_id, catalogue=None, tune=None, version=None):
    known = {s["id"] for s in (catalogue or load_catalogue())["settings"]}
    state = load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)
    return [sid for sid in state if sid not in known and sid not in (TYRE_KEY, TURBO_KEY, SOUND_KEY)]


def version_dir(work, car_id, tune=None, version=None):
    """Folder of the versions of a tune (<tune folder>/versions), or of one version of it (version v01 .. v99). The draft has none."""
    if tune == DRAFT:
        raise ValueError("the draft has no versions")
    folder = os.path.join(tune_dir(work, car_id, tune), VERSIONS)
    if version is None:
        return folder
    if not isinstance(version, str) or not VERSION_ID.fullmatch(version):
        raise ValueError("version id must be v01 .. v99, got %r" % (version,))
    return os.path.join(folder, version)


def version_state_path(work, car_id, version, tune=None):
    if version is None:
        raise ValueError("version id must be v01 .. v99, got None")
    return os.path.join(version_dir(work, car_id, tune, version), "tune_state.json")


def read_version_state(work, car_id, version, tune=None):
    """The saved state of a version as the file holds it (meta settings included); an unknown version is an error."""
    path = version_state_path(work, car_id, version, tune)
    if not os.path.isfile(kspkg.long_path(path)):
        raise ValueError("%s has no version %s of %s" % (car_id, version, tune or new_id_for(car_id)))
    state = read_json(path)
    if not isinstance(state, dict):
        raise ValueError("%s: expected an object" % path)
    return state


def meta_ids(catalogue):
    return {s["id"] for s in catalogue["settings"] if s["kind"] == "meta"}


def shared_ids(catalogue):
    """The ids a version takes from its base: the meta settings and the settings with "shared": true (kept in the .car file, which the game takes from the base)."""
    return meta_ids(catalogue) | {s["id"] for s in catalogue["settings"] if s.get("shared") is True}


def load_version_state(work, car_id, version, tune=None, catalogue=None):
    """The state of a version with the shared settings (shared_ids) of the base state of the tune instead of its own; a shared setting the base has no value for is left out, so its stock default applies."""
    ids = shared_ids(catalogue or load_catalogue())
    state = {k: v for k, v in read_version_state(work, car_id, version, tune).items() if k not in ids}
    state.update({k: v for k, v in load_state(work, car_id, tune).items() if k in ids})
    return state


def version_meta(path):
    """The meta.json of a version as an object; {} when it is missing, damaged or no object."""
    try:
        meta = read_json(path)
    except (ValueError, OSError):
        return {}
    return meta if isinstance(meta, dict) else {}


def version_meta_path(work, car_id, version, tune=None):
    return os.path.join(version_dir(work, car_id, tune, version), "meta.json")


def is_locked(meta):
    return meta.get("locked") is True


def check_unlocked(work, car_id, version, tune=None):
    """A ValueError when the version is locked (its meta.json holds "locked": true)."""
    meta = version_meta(version_meta_path(work, car_id, version, tune))
    if is_locked(meta):
        raise ValueError("version %s (%s) is locked; unlock it to change it" % (version, meta["name"] if isinstance(meta.get("name"), str) else version))


def save_version_state(work, car_id, state, version, tune=None):
    check_unlocked(work, car_id, version, tune)
    save_json(version_state_path(work, car_id, version, tune), state)


def save_tune_state(work, car_id, state, tune=None, version=None):
    """Save the state of the tune, or of its version when given."""
    if version is None:
        save_state(work, car_id, state, tune)
    else:
        save_version_state(work, car_id, state, version, tune)


def kept_build(work, car_id, version, tune=None):
    """The parsed build.json of the kept build of a version (see store_version_build) when it is valid for the tune (None: the default
    tune): an object with "tune" the id of the tune, "preset" a text, "parts" a list of texts (the game paths of the compatible parts of the version, may be empty), "files" a list of texts (paths
    relative to the car folder, none empty, "." or ".." in it) that all exist below build/files, "time" a text and "state" an object;
    else None."""
    folder = os.path.join(version_dir(work, car_id, tune, version), "build")
    try:
        record = read_json(kspkg.long_path(os.path.join(folder, "build.json")))
    except (ValueError, OSError):
        return None
    if not isinstance(record, dict):
        return None
    files = record.get("files")
    if not (record.get("tune") == (tune or new_id_for(car_id)) and isinstance(record.get("preset"), str) and record["preset"]
            and isinstance(record.get("parts"), list) and all(isinstance(p, str) and p for p in record["parts"])
            and isinstance(files, list) and files and all(isinstance(f, str) and not {"", ".", ".."} & set(f.split("/")) for f in files)
            and isinstance(record.get("time"), str) and isinstance(record.get("state"), dict)):
        return None
    if not all(os.path.isfile(kspkg.long_path(os.path.join(folder, "files", *f.split("/")))) for f in files):
        return None
    return record


def list_versions(work, car_id, tune=None):
    """The versions of a tune (None: the default tune) as [{"id", "name", "locked", "built"}] sorted by id; a version is a folder v01 .. v99
    below <tune folder>/versions that holds a tune_state.json. Empty when there are none. A version whose meta.json is missing or
    damaged is named by its id; locked is true only when its meta.json holds "locked": true, built is the time of its kept build
    (kept_build) or None."""
    folder = version_dir(work, car_id, tune)
    found = []
    for name in sorted(os.listdir(kspkg.long_path(folder))) if os.path.isdir(kspkg.long_path(folder)) else []:
        if VERSION_ID.fullmatch(name) and os.path.isfile(kspkg.long_path(version_state_path(work, car_id, name, tune))):
            meta = version_meta(os.path.join(folder, name, "meta.json"))
            kept = kept_build(work, car_id, name, tune)
            found.append({"id": name, "name": meta["name"] if isinstance(meta.get("name"), str) else name, "locked": is_locked(meta),
                          "built": kept["time"] if kept else None})
    return found


def clean_version_name(name):
    """The trimmed name when it is 1 to 40 characters without control characters."""
    if isinstance(name, str):
        name = name.strip()
    if not isinstance(name, str) or not 1 <= len(name) <= VERSION_NAME_MAX or re.search(r"[\x00-\x1f\x7f]", name):
        raise ValueError("a version name must be 1 to %d characters without control characters" % VERSION_NAME_MAX)
    return name


def variant_name_setting(catalogue=None):
    for s in (catalogue or load_catalogue())["settings"]:
        if s.get("handler") == "variant_name":
            return s
    raise ValueError("the catalogue has no variant_name setting")


def base_name(work, car_id, tune=None, versions=None):
    """The name of the base of a modded car in the game's menu (the text of its _preset_base line): the saved variant_name of the state of the
    tune, else "Base" when the tune has a version (versions True or False says so without looking), else the stock text of that line. None
    when the stock car has no single _preset_base line (stock_info.json holds no variant_name: the setting is not applicable) and for the draft."""
    if tune == DRAFT:
        return None
    try:
        s, info = variant_name_setting(), load_stock_info(work, car_id)
    except ValueError:
        return None
    if not (info or {}).get("variant_name"):
        return None
    state = load_state(work, car_id, tune)
    if s["id"] in state:
        return saved_value(s, state[s["id"]])
    if versions is None:
        versions = bool(list_versions(work, car_id, tune))
    return BASE_NAME if versions else info["variant_name"]


def check_version_name(work, car_id, name, tune=None, exclude=None):
    """The trimmed name when it is 1 to 40 characters without control characters, no other version of the tune (not exclude) has it ignoring case and it is not the name of the base (the saved one, else "Base", as a tune with a version has it)."""
    name = clean_version_name(name)
    for v in list_versions(work, car_id, tune):
        if v["id"] != exclude and v["name"].lower() == name.lower():
            raise ValueError("version name %s is already used by %s" % (name, v["id"]))
    base = base_name(work, car_id, tune, versions=True)
    if base is not None and base.lower() == name.lower():
        raise ValueError("version name %s is already used by the base" % name)
    return name


def add_version(work, car_id, name, tune=None, source=None):
    """Add a version to a tune (None: the default tune): a copy of the base state, or of the state of the version source, without
    its shared settings (shared_ids), under the first free id v01 .. v99; returns the id. The name must pass check_version_name. Nothing is
    written on an error."""
    folder = version_dir(work, car_id, tune)
    if is_extra_tune(car_id, tune) and not os.path.isfile(kspkg.long_path(state_path(work, car_id, tune))):
        raise ValueError("%s has no tune %s" % (car_id, tune))
    name = check_version_name(work, car_id, name, tune)
    ids = shared_ids(load_catalogue())
    state = load_state(work, car_id, tune) if source is None else read_version_state(work, car_id, source, tune)
    taken = set(os.listdir(kspkg.long_path(folder))) if os.path.isdir(kspkg.long_path(folder)) else set()
    free = next((v for v in ("v%02d" % n for n in range(1, 100)) if v not in taken), None)
    if free is None:
        raise ValueError("no free version id left for %s (v01 .. v99 are taken)" % (tune or new_id_for(car_id)))
    save_json(os.path.join(folder, free, "meta.json"), {"name": name})
    save_version_state(work, car_id, {k: v for k, v in state.items() if k not in ids}, free, tune)
    return free


def rename_base(work, car_id, name, tune=None):
    """Give the base of a tune another name: the saved variant_name of its state. The rules of a version name (clean_version_name), and no version
    of the tune has it ignoring case; the base has no lock. An error for a stock car without a variant name; returns the trimmed name."""
    version_dir(work, car_id, tune)
    if is_extra_tune(car_id, tune) and not os.path.isfile(kspkg.long_path(state_path(work, car_id, tune))):
        raise ValueError("%s has no tune %s" % (car_id, tune))
    name = clean_version_name(name)
    if base_name(work, car_id, tune) is None:
        raise ValueError("the base of this car has no name in the game's menu")
    for v in list_versions(work, car_id, tune):
        if v["name"].lower() == name.lower():
            raise ValueError("base name %s is already used by version %s" % (name, v["id"]))
    state = load_state(work, car_id, tune)
    state[variant_name_setting()["id"]] = name
    save_state(work, car_id, state, tune)
    return name


def rename_version(work, car_id, version, name, tune=None):
    """Give a version of a tune another name (the rules of check_version_name; its own old name does not count as taken); returns the trimmed name.
    The reserved id "base" renames the base of the tune (rename_base)."""
    if version == "base":
        return rename_base(work, car_id, name, tune)
    read_version_state(work, car_id, version, tune)
    check_unlocked(work, car_id, version, tune)
    name = check_version_name(work, car_id, name, tune, exclude=version)
    path = version_meta_path(work, car_id, version, tune)
    save_json(path, dict(version_meta(path), name=name))
    return name


def lock_version(work, car_id, version, tune=None):
    """Lock a version of a tune: apply keeps its kept build (kept_build) in the package instead of building it, and it cannot be edited
    (save_version_state, rename_version) until unlock_version. Only possible when the kept build was made from the state the version
    has now. Locking a locked version is fine. Returns the name of the version."""
    state = read_version_state(work, car_id, version, tune)
    path = version_meta_path(work, car_id, version, tune)
    meta = version_meta(path)
    name = meta["name"] if isinstance(meta.get("name"), str) else version
    kept = kept_build(work, car_id, version, tune)
    if kept is None:
        raise ValueError("version %s (%s) has no kept build: Apply first, then lock it" % (version, name))
    if kept["state"] != state:
        raise ValueError("version %s (%s) has changes that are not built yet: Apply first, then lock it" % (version, name))
    save_json(path, dict(meta, locked=True))
    return name


def unlock_version(work, car_id, version, tune=None):
    """Remove the lock of a version of a tune (an unlocked version stays as it is). Returns the name of the version."""
    read_version_state(work, car_id, version, tune)
    path = version_meta_path(work, car_id, version, tune)
    meta = version_meta(path)
    if "locked" in meta:
        save_json(path, {k: v for k, v in meta.items() if k != "locked"})
    return meta["name"] if isinstance(meta.get("name"), str) else version


def to_f32(x):
    try:
        y = struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        raise ValueError("float out of range: %r" % (x,)) from None
    v = car_json.F32(y)
    v.text = car_json.f32_text(y)
    return v


# the float32's shortest decimal as a double (0.1, not 0.10000000149011612), for display and for comparing with the typed value
def plain(v):
    return float(v.text) if isinstance(v, car_json.F32) else v


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "true" if v else "false"
    return v if isinstance(v, str) else repr(v) if isinstance(v, float) else str(v)


def zero(s):
    if s["type"] == "enum" and s.get("choices"):
        return s["choices"][0]
    return {"int": 0, "float": 0.0, "bool": False}.get(s["type"], "")


def int_from_text(setting_id, text):
    try:
        if not re.fullmatch(r"[+-]?\d+", text.strip()):
            raise ValueError
        return int(text)
    except ValueError:
        raise ValueError("%s expects an integer, got %r" % (setting_id, text[:40])) from None


def coerce(s, v):
    """The value v of setting s as its type (bool, int, float, text, enum choice, name suffix); ValueError with the setting id in the text when it does not fit."""
    t = s["type"]
    if t == "bool":
        if type(v) is bool:
            return v
        word = str(v).strip().lower() if type(v) in (int, str) else None
        if word not in BOOL_WORDS:
            raise ValueError("%s expects true or false (also yes/no, 1/0, on/off), got %r" % (s["id"], v))
        return BOOL_WORDS[word]
    if t == "int":
        if isinstance(v, str):
            v = int_from_text(s["id"], v)
        if type(v) is not int:
            raise ValueError("%s expects an integer, got %r" % (s["id"], v))
    elif t == "float":
        try:
            if type(v) is bool or not isinstance(v, (str, int, float)):
                raise ValueError
            v = float(v)
        except (ValueError, OverflowError):
            raise ValueError("%s expects a number, got %r" % (s["id"], v)) from None
        if not math.isfinite(v):
            raise ValueError("%s expects a finite number, got %r" % (s["id"], v))
        try:
            to_f32(v)
        except ValueError:
            raise ValueError("%s is out of the float range the game stores (about +-3.4e38), got %r" % (s["id"], v)) from None
    elif s.get("handler") == "name_suffix":
        if isinstance(v, str):
            v = re.sub(" {2,}", " ", v.strip())
        if not isinstance(v, str) or not 1 <= len(v) <= NAME_SUFFIX_MAX or re.search(r"[\x00-\x1f\x7f]", v):
            raise ValueError("%s expects 1 to %d characters without control characters" % (s["id"], NAME_SUFFIX_MAX))
    else:
        if not isinstance(v, str) or not v or re.search(r"[\x00-\x1f\x7f]", v):
            raise ValueError("%s expects non-empty text without control characters" % s["id"])
        if t == "enum" and v not in s.get("choices", [v]):
            raise ValueError("%s must be one of: %s" % (s["id"], ", ".join(s["choices"])))
    return v


def range_warning(s, v):
    if s["type"] in ("int", "float") and (v < s.get("min", v) or v > s.get("max", v)):
        return "%s=%s is outside the suggested range %s..%s" % (
            s["id"], fmt(v), fmt(s.get("min", "-")), fmt(s.get("max", "-")))
    return None


# float copies from different files may differ in the last float32 digit; 1e-5 relative is well above float32 resolution (about 1.2e-7)
def same(s, a, b):
    if s["type"] == "float" and a is not None and b is not None:
        a, b = to_f32(a), to_f32(b)
        return abs(a - b) <= 1e-5 * max(1, abs(a), abs(b))
    return a == b


def set_value(work, car_id, setting_id, value, catalogue=None, tune=None, version=None):
    """Check one value, save it in the state of the tune (of its version when given) and return {id, value, warnings}; the setting must be applicable to the car and, for a version, no shared setting (shared_ids). A tyre setting of the car (tyre_settings, the old Tyres section) is refused: its values are edited in the Tyre Creator (a value saved earlier is still applied, unset_value removes it, convert_tyres turns them into library tyres)."""
    cat = catalogue or load_catalogue()
    s = find_setting(cat, setting_id)
    if any(t["id"] == setting_id for t in tyre_settings(cat)):
        raise ValueError(TYRE_VALUES_REFUSED)
    if version is not None and setting_id in shared_ids(cat):
        check_unlocked(work, car_id, version, tune)
        raise ValueError("%s is shared by all versions, set it on the base" % setting_id)
    coerced = coerce(s, value)
    row = resolve_defaults(work, car_id, dict(cat, settings=[s]), hidden=True, tune=new_id_for(car_id) if tune is None else tune, version=version)[0]
    if not row["applicable"]:
        raise ValueError("%s is not applicable to %s: %s" % (setting_id, car_id, row["reason"]))
    if version is None:
        state = load_state(work, car_id, tune)
        state[setting_id] = coerced
        save_state(work, car_id, state, tune)
    else:
        state = read_version_state(work, car_id, version, tune)
        state[setting_id] = coerced
        save_version_state(work, car_id, state, version, tune)
    warning = range_warning(s, coerced)
    return {"id": setting_id, "value": coerced, "warnings": [warning] if warning else []}


def unset_value(work, car_id, setting_id, catalogue=None, tune=None, version=None):
    """Remove one setting from the state of the tune (of its version when given, never a shared setting); returns {id, removed}."""
    if version is not None and setting_id in shared_ids(catalogue or load_catalogue()):
        check_unlocked(work, car_id, version, tune)
        raise ValueError("%s is shared by all versions, set it on the base" % setting_id)
    state = load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)
    # a name that is not in the state must be a catalogue setting; _tyres, _turbo and _sounds are no settings, so they are refused as unknown here (their own commands remove them)
    if setting_id not in state or setting_id in (TYRE_KEY, TURBO_KEY, SOUND_KEY):
        find_setting(catalogue or load_catalogue(), setting_id)
    removed = state.pop(setting_id, None) is not None
    if removed and version is None:
        save_state(work, car_id, state, tune)
    elif removed:
        save_version_state(work, car_id, state, version, tune)
    return {"id": setting_id, "removed": removed}


def parse_path(path):
    moves, pos = [], 0
    while True:
        m = PATH_STEP.match(path, pos)
        if not m:
            raise ValueError("bad field path %r" % path)
        moves.append(("key", m.group(1)))
        for sel in PATH_SELECTOR.findall(m.group(2)):
            if sel.isdigit():
                moves.append(("idx", int(sel)))
            elif sel == "*":
                moves.append(("all",))
            elif "=" in sel:
                moves.append(("find",) + tuple(sel.split("=", 1)))
            else:
                raise ValueError("bad selector [%s] in field path %r" % (sel, path))
        pos = m.end()
        if pos == len(path):
            return moves
        if path[pos] != ".":
            raise ValueError("bad field path %r" % path)
        pos += 1


def text_of(v):
    if isinstance(v, car_json.F32):
        return v.text
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def list_index(cur, move, path):
    if move[0] == "all":
        raise ValueError("%s: [*] must be expanded before use" % path)
    if not isinstance(cur, list):
        raise ValueError("%s: expected a list before [%s]" % (path, "=".join(map(str, move[1:]))))
    if move[0] == "idx":
        if move[1] >= len(cur):
            raise ValueError("%s: list has no element %d" % (path, move[1]))
        return move[1]
    for i, el in enumerate(cur):
        if isinstance(el, dict) and move[1] in el and text_of(el[move[1]]) == move[2]:
            return i
    raise ValueError("%s: no list element with %s=%s" % (path, move[1], move[2]))


def add_key(d, key, value):
    d[key] = value
    if "_order" in d:
        d["_order"].append(key)


def locate(obj, path, create=False, missing_ok=False):
    """Return (container, key) of the field named by path; create adds missing objects on the way, missing_ok
    returns (None, None) for a missing object on the way."""
    moves = parse_path(path)
    cur = obj
    for i, move in enumerate(moves):
        last = i == len(moves) - 1
        if move[0] == "key":
            if not isinstance(cur, dict):
                raise ValueError("%s: %r is not inside an object" % (path, move[1]))
            if last:
                return cur, move[1]
            if move[1] not in cur:
                if missing_ok:
                    return None, None
                if not create:
                    raise ValueError("%s: missing field %r" % (path, move[1]))
                add_key(cur, move[1], {})
            cur = cur[move[1]]
        else:
            idx = list_index(cur, move, path)
            if last:
                return cur, idx
            cur = cur[idx]


def get_value(obj, path, missing_ok=False):
    """(value, absent) of the field path in obj; absent is True (value None) when the last field is missing, or with missing_ok an object on the way."""
    container, key = locate(obj, path, missing_ok=missing_ok)
    if container is None or (isinstance(container, dict) and key not in container):
        return None, True
    return container[key], False


def expand_path(obj, path, missing_ok=False):
    """The concrete paths a path with [*] stands for (one per existing list element), [path] without one. An absent or
    empty list gives no paths."""
    if "[*]" not in path:
        return [path]
    prefix, _, rest = path.partition("[*]")
    items, absent = get_value(obj, prefix, missing_ok)
    if absent:
        return []
    if not isinstance(items, list):
        raise ValueError("%s: [*] needs a list at %s" % (path, prefix))
    return [p for i in range(len(items)) for p in expand_path(obj, "%s[%d]%s" % (prefix, i, rest), missing_ok)]


def put_value(obj, path, value):
    container, key = locate(obj, path, create=True)
    if isinstance(container, dict) and key not in container:
        add_key(container, key, value)
    else:
        container[key] = value


def load_msg(path):
    name = car_json.message_for(path)
    try:
        with open(kspkg.long_path(path), "rb") as f:
            data = f.read()
    except OSError as e:
        raise ValueError("%s: %s" % (path, e.strerror or e)) from None
    obj, err = car_json.roundtrip(car_json.load_schema(), name, data, text=False)
    if err:
        raise ValueError("%s: %s" % (path, err))
    return obj, name


def save_msg(path, name, obj):
    try:
        data = car_json.encode_msg(car_json.load_schema(), name, obj)
    except ValueError as e:
        raise ValueError("%s: %s" % (path, e)) from None
    with open(kspkg.long_path(path), "wb") as f:
        f.write(data)


def car_root_of(root, car_id):
    return os.path.join(root, "content", "cars", car_id)


def car_path(car_root, rel):
    if rel.startswith(SHARED):
        shared = os.path.join(os.path.dirname(car_root), SHARED_DIR)
        return resolve_inside(shared, os.path.join(shared, *rel[len(SHARED):].split("/")))
    return resolve_inside(car_root, os.path.join(car_root, *rel.split("/")))


def renamed(rel, old_id, new_id):
    return re.sub(re.escape(old_id), new_id, rel, flags=re.IGNORECASE)


def curve_path(root, text):
    return resolve_inside(root, os.path.join(root, *text.replace("\\", "/").split("/")))


def count_tree(path):
    files = dirs = size = 0
    for dp, dn, fn in os.walk(kspkg.long_path(path)):
        dirs += len(dn)
        files += len(fn)
        size += sum(os.path.getsize(os.path.join(dp, n)) for n in fn)
    return {"files": files, "dirs": dirs, "bytes": size}


def stock_info_path(work, car_id):
    return os.path.join(car_work(work, car_id), "stock_info.json")


def valid_stock_info(info, car_id):
    return (isinstance(info, dict) and info.get("car_id") == car_id
            and all(isinstance(info.get(k), str) and info[k] for k in ("display_name", "brand"))
            and type(info.get("year")) is int)


def complete_stock_info(info):
    return info is not None and all(isinstance(info.get(k), str) for k in STOCK_PROPERTIES + ("variant_name",))


def load_stock_info(work, car_id):
    path = stock_info_path(work, car_id)
    if not os.path.exists(path):
        return None
    info = read_json(path)
    if not valid_stock_info(info, car_id):
        raise ValueError("%s: expected car_id %s with display_name, brand and year" % (path, car_id))
    return info


def read_game_file(work, game, rel):
    """Bytes of one file of the game package, extracted through <work>/stock_tmp."""
    if not os.path.isfile(game):
        raise ValueError(GAME_MISSING % game)
    tmp = os.path.join(work, "stock_tmp")
    os.makedirs(work, exist_ok=True)
    if os.path.exists(tmp):
        remove_tree(work, tmp)
    try:
        quietly(kspkg.cmd_extract, game, tmp, rel)
        extracted = os.path.join(tmp, *rel.split("\\"))
        if not os.path.isfile(extracted):
            raise ValueError("%s not found in %s" % (rel, game))
        with open(extracted, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp):
            remove_tree(work, tmp)


def ensure_stock_loc(work, game=DEFAULT_GAME):
    """Make sure the game's stock en.cars.loc is in <work>/stock_loc; returns "present" or "written"."""
    path = stock_loc_path(work)
    if os.path.isfile(path):
        return "present"
    data = read_game_file(work, game, STOCK_LOC)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return "written"


def read_game_package_table(work, game):
    try:
        return read_game_file(work, game, CARS_TABLE)
    except (ValueError, OSError) as e:
        raise ValueError("%s; if this is the wrong file, pass --game <path of content.kspkg>" % e) from None


def cars_table_lines(data):
    return car_json.decode_msg(car_json.load_schema(), "TableData", data).get("preset", {}).get("lines", [])


def write_stock_info(work, car_id, game=DEFAULT_GAME):
    """Make sure <work>/<car>/stock_info.json is complete, read from the game's cars.table and en.cars.loc;
    returns "present" or "written"."""
    if complete_stock_info(load_stock_info(work, car_id)):
        return "present"
    data = read_game_file(work, game, CARS_TABLE)
    ensure_stock_loc(work, game)
    lines = cars_table_lines(data)
    rows = [line["car_content"] for line in lines if line.get("car_content", {}).get("name") == car_id]
    if len(rows) != 1:
        raise ValueError("%s has %d rows for %s, expected 1" % (CARS_TABLE, len(rows), car_id))
    info = {"car_id": car_id, "display_name": rows[0].get("display_name"), "brand": rows[0].get("brand"),
            "year": rows[0].get("year")}
    if not valid_stock_info(info, car_id):
        raise ValueError("%s: the row of %s lacks display_name, brand or year" % (CARS_TABLE, car_id))
    # proto3 leaves an enum at value 0 off the wire: absent property = the enum's value 0 name
    for i, key in enumerate(STOCK_PROPERTIES, 1):
        info[key] = rows[0].get(key) or car_json.load_schema()["enums"]["CarContentData.Property%d" % i][1][0]
    info["variant_name"] = clone_car.stock_variant(stock_loc_path(work), car_id)
    save_json(stock_info_path(work, car_id), info)
    return "written"


# best effort: when the game or the schemas are unavailable the car keeps whatever stock_info.json it has (or none) and callers fall back to the preset name (a damaged stock_info.json still raises ValueError)
def stock_info_or_none(work, car_id, game=DEFAULT_GAME):
    info = load_stock_info(work, car_id)
    if not complete_stock_info(info):
        try:
            write_stock_info(work, car_id, game)
            info = load_stock_info(work, car_id)
        except (ValueError, OSError):
            return info
    return info


def cars_index_path(work):
    return os.path.join(work, "cars_index.json")


def valid_cars_index(index):
    return (isinstance(index, list) and bool(index)
            and all(isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("display_name"), str)
                    for c in index))


def load_cars_index(work, game=DEFAULT_GAME):
    """[{id, display_name, brand, year}] of every car of the game sorted by display name, from the cache
    <work>/cars_index.json; created from the game's cars.table when missing. None when there is no cache and the
    game package cannot be read or decoded."""
    path = cars_index_path(work)
    _index_error.clear()
    if os.path.isfile(path):
        try:
            index = read_json(path)
        except (ValueError, OSError):
            index = None
        if valid_cars_index(index):
            return index
    if not os.path.isfile(game):
        _index_error[:] = [GAME_MISSING % game]
        return None
    try:
        lines = cars_table_lines(read_game_package_table(work, game))
    except (ValueError, OSError) as e:
        _index_error[:] = [str(e)]
        return None
    rows = {}
    for line in lines:
        c = line.get("car_content", {})
        if isinstance(c.get("name"), str) and c["name"]:
            rows[c["name"]] = {"id": c["name"], "display_name": c.get("display_name") or c["name"],
                               "brand": c.get("brand", ""), "year": c.get("year")}
    index = sorted(rows.values(), key=lambda c: (c["display_name"].lower(), c["id"]))
    if not valid_cars_index(index):
        _index_error[:] = ["%s lists no cars, pass --game <path of content.kspkg> of Assetto Corsa EVO" % CARS_TABLE]
        return None
    save_json(path, index)
    return index


def mech_preset_path(car_root, tail=""):
    folder = find_ci(car_root, "presets")
    names = sorted(n for n in os.listdir(kspkg.long_path(folder)) if n.lower().endswith(".mechanicalcarpreset"))
    if not names:
        raise ValueError("no mechanical preset in %s%s" % (folder, tail))
    return os.path.join(folder, names[0])


def preset_display_name(car_root):
    preset = load_msg(mech_preset_path(car_root, " to derive the stock car name from"))[0]
    text = ("%s %s" % (preset.get("brand", ""), preset.get("description", ""))).strip()
    return re.sub(r" Preset Base$", "", text)


def init(work, car_id, game=DEFAULT_GAME):
    """Extract the stock car into <work>/<car>/base (skipped when present), then ensure stock_loc, stock_info and the shared tyre files; returns the tree counts plus present, dir, stock_loc, stock_info, tyre_files."""
    base = base_dir(work, car_id)
    car_root = car_root_of(base, car_id)
    present = count_tree(car_root) if os.path.isdir(kspkg.long_path(car_root)) else None
    if present and present["files"]:
        res = dict(present, present=True, dir=car_root)
    else:
        if not os.path.isfile(game):
            raise ValueError(GAME_MISSING % game)
        # extract next to base and rename, so an interrupted extraction never leaves a half-filled base that count_tree would accept
        part = base + ".partial"
        os.makedirs(kspkg.long_path(car_work(work, car_id)), exist_ok=True)
        if os.path.exists(kspkg.long_path(part)):
            remove_tree(work, part)
        quietly(kspkg.cmd_extract, game, part, "content\\cars\\" + car_id)
        part_car = car_root_of(part, car_id)
        if not os.path.isdir(kspkg.long_path(part_car)) or not count_tree(part_car)["files"]:
            remove_tree(work, part)
            raise ValueError("%s not found in %s" % (car_id, game))
        if os.path.exists(kspkg.long_path(base)):
            remove_tree(work, base)
        os.rename(kspkg.long_path(part), kspkg.long_path(base))
        forget_resolved(work, car_id)
        res = dict(count_tree(car_root), present=False, dir=car_root)
    res["stock_loc"] = ensure_stock_loc(work, game)
    res["stock_info"] = write_stock_info(work, car_id, game)
    try:
        res["tyre_files"] = ensure_tyre_files(work, car_id, game)
    except (ValueError, OSError) as e:
        res["tyre_files"] = "not extracted (%s)" % e
    forget_resolved(work, car_id)
    return res


def read_file(car_root, rel, cache):
    """Decoded file below car_root (rel as returned by resolve_file), cached by rel; the same dict also holds the ("role", file) entries of resolve_file."""
    if rel not in cache:
        try:
            cache[rel] = load_msg(car_path(car_root, rel))[0]
        except ValueError as e:
            cache[rel] = e
    if isinstance(cache[rel], ValueError):
        raise cache[rel]
    return cache[rel]


def find_ci(base, rel):
    """Actual path of rel below base, every part matched case-insensitively."""
    cur = base
    for part in filter(None, re.split(r"[\\/]+", rel)):
        try:
            names = {n.lower(): n for n in os.listdir(kspkg.long_path(cur))}
        except OSError as e:
            raise ValueError("%s: %s" % (cur, e.strerror or e)) from None
        if part.lower() not in names:
            raise ValueError("%s not found in %s" % (part, cur))
        cur = os.path.join(cur, names[part.lower()])
    return cur


def rel_of(root, car_id, found):
    rel = os.path.relpath(found, car_root_of(root, car_id))
    if rel.split(os.sep)[0] == "..":
        raise ValueError("%s is outside the car folder" % found)
    return rel.replace(os.sep, "/")


def manifest_file(root, car_id, text, what):
    if not isinstance(text, str) or not text:
        raise ValueError("no %s" % what)
    return rel_of(root, car_id, find_ci(root, text))


def car_manifest(root, car_id, cache):
    car_root = car_root_of(root, car_id)
    data = find_ci(car_root, "data")
    names = sorted(n for n in os.listdir(kspkg.long_path(data))
                   if n.lower().endswith(".car") and os.path.isfile(kspkg.long_path(os.path.join(data, n))))
    if len(names) > 1:
        valid = []
        for n in names:
            rel = rel_of(root, car_id, os.path.join(data, n))
            try:
                if read_file(car_root, rel, cache).get("engine_path"):
                    valid.append(n)
            except ValueError:
                pass
        if len(valid) != 1:
            raise ValueError("ambiguous: %d .car files in %s (%s), %d of them with an engine_path"
                             % (len(names), data, ", ".join(names), len(valid)))
        names = valid
    if not names:
        raise ValueError("no .car file in %s" % data)
    return rel_of(root, car_id, os.path.join(data, names[0]))


def resolve_file(file, root, car_id, cache):
    """Path of a target file relative to the car folder: a role (@engine, ..., @turbo[N]) is resolved for the car,
    anything else is taken as it is."""
    if not file.startswith("@"):
        return file
    key = ("role", file)
    if isinstance(cache.get(key), ValueError):
        raise cache[key]
    if key not in cache:
        try:
            car_root = car_root_of(root, car_id)
            name, _, index = file[1:].rstrip("]").partition("[")
            if name == "car":
                cache[key] = car_manifest(root, car_id, cache)
            elif name == "mech_preset":
                cache[key] = rel_of(root, car_id, mech_preset_path(car_root))
            elif name == "turbo":
                engine = read_file(car_root, resolve_file("@engine", root, car_id, cache), cache)
                paths = engine.get("turbos_to_load", [])
                if int(index) >= len(paths):
                    raise ValueError("the engine file lists %d turbo file(s), no turbos_to_load[%s]" % (len(paths), index))
                cache[key] = manifest_file(root, car_id, paths[int(index)], "turbos_to_load[%s]" % index)
            elif name in TYRE_ROLES:
                cache[key] = tyre_file(root, car_id, name, cache)
            else:
                field = MANIFEST_ROLES[name]
                car = read_file(car_root, resolve_file("@car", root, car_id, cache), cache)
                cache[key] = manifest_file(root, car_id, get_value(car, field)[0], "%s in the car file" % field)
        except ValueError as e:
            cache[key] = e
            raise
    return cache[key]


def game_path_key(text):
    return text.replace("/", "\\").lower()


def tyre_text(root, car_id, name, cache):
    """The path text of frontTyreCompounds[0] / rearTyreCompounds[0] (name tyre_front / tyre_rear) in the .car file."""
    car = read_file(car_root_of(root, car_id), resolve_file("@car", root, car_id, cache), cache)
    paths = car.get(TYRE_ROLES[name])
    if not paths or not isinstance(paths[0], str) or not paths[0]:
        raise ValueError("no %s in the car file" % TYRE_ROLES[name])
    return paths[0]


def tyre_file(root, car_id, name, cache):
    """Path relative to the car folder of the tyre file of a role: inside the car folder, or SHARED + the path below
    common_phsx for a shared game file."""
    found = tyre_found(root, tyre_text(root, car_id, name, cache))
    rel = os.path.relpath(found, car_root_of(root, car_id)).replace(os.sep, "/")
    if rel.split("/")[0] != "..":
        return rel
    shared = os.path.relpath(found, os.path.join(root, "content", "cars", SHARED_DIR)).replace(os.sep, "/")
    if shared.split("/")[0] == "..":
        raise ValueError("%s is neither in the car folder nor in the shared folder" % found)
    return SHARED + shared


def tyre_found(root, text):
    try:
        return find_ci(root, text)
    except ValueError:
        raise ValueError(TYRE_UNAVAILABLE) from None


def referenced_tyres(root, car_id, cache):
    """The shared tyre files (game paths below content\\cars\\common_phsx, lower case) that the car's .car
    (frontTyreCompounds, rearTyreCompounds) and presets/*.compatibletyres name, each once."""
    car_root = car_root_of(root, car_id)
    car = read_file(car_root, resolve_file("@car", root, car_id, cache), cache)
    texts = list(car.get("frontTyreCompounds", [])) + list(car.get("rearTyreCompounds", []))
    try:
        folder = find_ci(car_root, "presets")
    except ValueError:
        folder = None
    for n in sorted(os.listdir(kspkg.long_path(folder))) if folder else []:
        if n.lower().endswith(".compatibletyres"):
            for pc in load_msg(os.path.join(folder, n))[0].get("physic_compounds", []):
                rear = pc.get("rear_tyre_data_paths")
                texts += [pc.get("front_tyre_data_path")] + (rear if isinstance(rear, list) else [rear])
    keys = [game_path_key(t) for t in texts if isinstance(t, str)]
    return list(dict.fromkeys(k for k in keys if k.startswith(GAME_SHARED)))


def tyre_present(root, text):
    try:
        find_ci(root, text)
        return True
    except ValueError:
        return False


def ensure_tyre_files(work, car_id, game=DEFAULT_GAME, cache=None):
    """Make sure the shared tyre files the car names are in <work>/<car>/base next to the car folder (extracted from
    the game package, nothing else); returns "present" or "extracted N file(s)"."""
    root = base_dir(work, car_id)
    with _tyre_lock:
        missing = [p for p in referenced_tyres(root, car_id, {} if cache is None else cache)
                   if not tyre_present(root, p)]
        if not missing:
            return "present"
        if not os.path.isfile(game):
            raise ValueError(GAME_MISSING % game)
        for p in missing:
            quietly(kspkg.cmd_extract, game, root, p)
        forget_resolved(work, car_id)
        gone = [p for p in missing if not tyre_present(root, p)]
        if gone:
            raise ValueError("%s not found in %s" % (gone[0], game))
    return "extracted %d file(s)" % len(missing)


def choice_of(s, text):
    for name, written in s["choice_values"].items():
        if game_path_key(written) == game_path_key(text):
            return name
    raise ValueError("%s is not one of the choices of %s" % (text, s["id"]))


def resolve_curve(s, root, car_id, cache):
    cf = s["curve_from"]
    out = {"file": cf["file"], "path": cf["path"], "resolved": False}
    try:
        out["rel"] = resolve_file(cf["file"], root, car_id, cache)
        text, absent = get_value(read_file(car_root_of(root, car_id), out["rel"], cache), cf["path"])
        if absent or not isinstance(text, str):
            raise ValueError("%s holds no curve file name" % cf["path"])
        curve, _ = load_msg(curve_path(root, text))
        values = [p["value"] for p in curve.get("points", []) if "value" in p]
        if not values:
            raise ValueError("curve %s has no points with a value" % text)
    except (ValueError, OSError) as e:
        out["error"] = str(e)
        return out
    out.update(resolved=True, absent=False, curve=text, value=s["default"],
               info="%d points, peak %s" % (len(curve["points"]), fmt(plain(max(values)))))
    return out


def resolve_target(s, t, root, car_id, cache):
    """The resolved copies of one catalogue target: one entry, or one per list element when the path has [*] (the
    path of each entry is the concrete one). A target that does not resolve gives one entry with the error."""
    entry = {"file": t["file"], "path": t["path"], "resolved": False}
    if t.get("optional"):
        entry["optional"] = True
    missing_ok = bool(s.get("create_missing"))
    try:
        entry["rel"] = resolve_file(t["file"], root, car_id, cache)
        obj = read_file(car_root_of(root, car_id), entry["rel"], cache)
        paths = expand_path(obj, t["path"], missing_ok)
        if not paths:
            raise ValueError("%s: the list has no elements" % t["path"])
        out = []
        for path in paths:
            value, absent = get_value(obj, path, missing_ok)
            value = plain(zero(s) if absent else value)
            if s["type"] == "int" and isinstance(value, float) and value.is_integer():
                value = int(value)
            if s.get("choice_values") and not absent:
                value = choice_of(s, value)
            out.append(dict(entry, path=path, resolved=True, absent=absent, value=value))
    except (ValueError, OSError) as e:
        return [dict(entry, error=str(e))]
    return out


def forget_resolved(work, car_id):
    """Drop the cached rows of resolve_defaults, the cached turbo listing and the cached sound options of a car (its base or its shared tyre files changed)."""
    with _resolve_lock:
        for key in [k for k in _resolved if k[:2] == (work, car_id)]:
            del _resolved[key]
        _donor_listings.pop((work, car_id), None)
        _actor_options.pop((work, car_id), None)
        for key in [k for k in _engine_inputs if k[:2] == (work, car_id)]:
            del _engine_inputs[key]


def resolve_stamp(work, car_id, root=None):
    """The (mtime_ns, size) of every .car file of the car and of its stock_info.json (plus the kit stamp of a kit root), None when unreadable. init rewrites every .car file when it extracts, so the stamp changes whenever what resolve_defaults reads can have changed."""
    root = root or base_dir(work, car_id)
    try:
        data = find_ci(car_root_of(root, car_id), "data")
        paths = [os.path.join(data, n) for n in sorted(os.listdir(kspkg.long_path(data))) if n.lower().endswith(".car")]
        paths.append(stock_info_path(work, car_id))
        stamp = [(st.st_mtime_ns, st.st_size) if st else None for st in map(stat_or_none, paths)]
    except (ValueError, OSError):
        return None
    info = kit_info(root) if root != base_dir(work, car_id) else None
    return stamp if info is None else stamp + [info["stamp"]]


def stat_or_none(path):
    try:
        return os.stat(kspkg.long_path(path))
    except FileNotFoundError:
        return None


def preset_names(car_root):
    folder = find_ci(car_root, "presets")
    return folder, sorted(n for n in os.listdir(kspkg.long_path(folder)) if n.lower().endswith(".mechanicalcarpreset"))


def tuning_overrides(root, car_id, tuning, roles, not_shown):
    """Add the role overrides of one decoded .tuningpart to roles ({role: rel}) and its other members to not_shown."""
    for member in TUNING_MEMBERS:
        if member not in tuning:
            continue
        data = tuning[member] if isinstance(tuning[member], dict) else {}
        found = {}
        if member in VARIANT_PATHS and data.get("path"):
            found[VARIANT_PATHS[member]] = data["path"]
        elif member == "suspensions":
            found = {role: data[field] for field, role in VARIANT_COILOVERS.items() if data.get(field)}
        if not found:
            if member not in VARIANT_PATHS and member not in not_shown:
                not_shown.append(member)
            continue
        for role, text in found.items():
            rel = manifest_file(root, car_id, text, "%s path in the tuning part" % member)
            if roles.setdefault(role, rel) != rel:
                raise ValueError("two tuning parts override %s with different files (%s, %s)" % (role, roles[role], rel))


def variant_of(root, car_id, folder, name):
    """The variant entry of one mechanical preset file, or None when the preset changes no role file (visual only)."""
    vid = name.rsplit(".", 1)[0].lower()
    entry = {"id": vid, "label": vid, "preset": rel_of(root, car_id, os.path.join(folder, name)), "roles": {},
             "not_shown": [], "error": None}
    try:
        preset = load_msg(os.path.join(folder, name))[0]
        entry["label"] = preset.get("note") or preset.get("description") or vid
        for key in ("forced_compatible_part_paths", "compatible_part_paths"):
            for part in preset.get(key, []):
                compatible = load_msg(find_ci(root, part))[0]
                if not compatible.get("car_part_path"):
                    raise ValueError("no car_part_path in %s" % part)
                car_part = load_msg(find_ci(root, compatible["car_part_path"]))[0]
                for logic in car_part.get("logic_parts", []):
                    if logic.get("tuning_part_path"):
                        tuning = load_msg(find_ci(root, logic["tuning_part_path"]))[0]
                        tuning_overrides(root, car_id, tuning, entry["roles"], entry["not_shown"])
    except (ValueError, OSError) as e:
        entry["error"] = str(e)
    return entry if entry["roles"] or entry["error"] else None


def list_variants(work, car_id):
    """The mechanical presets of the extracted stock car other than the base preset (@mech_preset) that replace role files
    (engine, gearbox, ...) through their tuning parts, in sorted order of the preset files, each as {"id", "label", "preset",
    "roles": {role: path relative to the car folder}, "not_shown": [tuning members that are not shown], "error": text or None}.
    A preset whose chain of files is broken carries the error; a preset without any role override is not listed."""
    root = base_dir(work, car_id)
    car_root = car_root_of(root, car_id)
    if not os.path.isdir(kspkg.long_path(car_root)):
        raise ValueError("no base car in %s, run init first" % root)
    base = os.path.basename(mech_preset_path(car_root))
    folder, names = preset_names(car_root)
    found = [variant_of(root, car_id, folder, n) for n in names if n != base]
    return [v for v in found if v]


def variant_seed(work, car_id, variant):
    """The resolve cache entries of a variant: its role files and its preset as @mech_preset."""
    for v in list_variants(work, car_id):
        if v["id"] == variant:
            if v["error"]:
                raise ValueError("variant %s of %s cannot be read: %s" % (variant, car_id, v["error"]))
            seed = {("role", role): rel for role, rel in v["roles"].items()}
            seed[("role", "@mech_preset")] = v["preset"]
            return seed
    raise ValueError("%s has no variant %s" % (car_id, variant))


def resolve_defaults(work, car_id, catalogue=None, game=DEFAULT_GAME, hidden=False, tune=None, variant=None, version=None):
    """Every setting with its default; hidden=False keeps only the settings applicable to the car, hidden=True
    returns all of them, each with applicable and reason (None when applicable). The resolved rows are cached per
    (work, car, root, catalogue) while resolve_stamp is unchanged (not when the tyre files or the stock info could not be
    read); the caller gets its own copy. tune None reads the stock car (base); a tune id or DRAFT reads root_for of
    that tune, the kit root when its state has a turbo kit. variant (an id of list_variants, only with tune None) reads the
    stock car with the role files of that variant (its engine, setup, ... and its preset as @mech_preset); an unknown
    variant is a ValueError. version (an id of list_versions, with tune None the default tune; not with a variant) reads the
    tune as before except that the kit root follows the turbo kit of the version's own state."""
    if variant is not None and tune is not None:
        raise ValueError("a variant cannot be combined with a tune")
    if version is not None and variant is not None:
        raise ValueError("a version cannot be combined with a variant")
    cat = catalogue or load_catalogue()
    if version is not None and tune is None:
        tune = new_id_for(car_id)
    root = base_dir(work, car_id) if tune is None else root_for(work, car_id, tune, version)
    if not os.path.isdir(kspkg.long_path(car_root_of(root, car_id))):
        raise ValueError("no base car in %s, run init first" % root)
    seed = variant_seed(work, car_id, variant) if variant is not None else None
    digest = hashlib.sha1(json.dumps(cat, sort_keys=True).encode()).hexdigest()
    key, stamp = (work, car_id, root, digest) + ((variant,) if variant is not None else ()), resolve_stamp(work, car_id, root)
    with _resolve_lock:
        hit = _resolved.get(key)
    if hit and stamp is not None and hit[0] == stamp:
        rows = copy.deepcopy(hit[1])
    else:
        rows, cacheable = resolve_rows(work, car_id, cat, game, root, seed)
        if cacheable and stamp is not None and resolve_stamp(work, car_id, root) == stamp:
            with _resolve_lock:
                _resolved[key] = (stamp, copy.deepcopy(rows))
    return rows if hidden else [r for r in rows if r["applicable"]]


def resolve_rows(work, car_id, cat, game, root=None, seed=None):
    """All rows of resolve_defaults and whether they may be cached; root is base unless a kit root is given, seed the resolve cache entries a variant starts with."""
    root = root or base_dir(work, car_id)
    car_root = car_root_of(root, car_id)
    info = stock_name = stock_variant = None
    if any("default_template" in s for s in cat["settings"]):
        info = stock_info_or_none(work, car_id, game)
        stock_name = info["display_name"] if info else preset_display_name(car_root)
        stock_variant = (info or {}).get("variant_name") or stock_name
    cache, rows, tyre_error = dict(seed or {}), [], None
    if any(t["file"].startswith("@tyre_") for s in cat["settings"] for t in s.get("targets", [])):
        try:
            ensure_tyre_files(work, car_id, game, cache if root == base_dir(work, car_id) else None)
        except (ValueError, OSError) as e:
            tyre_error = str(e)
    for s in cat["settings"]:
        row = {k: s[k] for k in REQUIRED if k != "description"}
        row.update({k: s[k] for k in ("min", "max", "description") if k in s})
        if s["kind"] == "meta":
            targets = []
        elif s["kind"] == "curve_scale":
            targets = [resolve_curve(s, root, car_id, cache)]
        else:
            targets = [c for t in s["targets"] for c in resolve_target(s, t, root, car_id, cache)]
        needs = [c for t in s.get("needs", []) for c in resolve_target(s, t, root, car_id, cache)]
        values = [t["value"] for t in targets if t["resolved"]] if s["kind"] != "flag" else []
        row["targets"] = targets
        row["resolved"] = all(t["resolved"] or t.get("optional") for t in targets)
        row["consistent"] = all(same(s, v, values[0]) for v in values)
        row["copies_differ"] = not row["consistent"]
        if row["copies_differ"]:
            row["copy_values"] = [{"target": "%s %s" % (t["file"], t["path"]), "value": t["value"]}
                                  for t in targets if t["resolved"]]
        row["default"] = (False if s["kind"] == "flag" else s["default"] if "default" in s
                          else s["default_template"].replace("{stock_display_name}", stock_name)
                                                    .replace("{stock_variant_name}", stock_variant)
                          if "default_template" in s else values[0] if values else None)
        row["absent"] = s["kind"] != "flag" and any(t.get("absent") for t in targets)
        row["ok"] = row["resolved"] and row["consistent"]
        missing = [t for t in targets + needs if not t["resolved"] and not t.get("optional")]
        required = [t for t in targets if not t.get("optional")]
        if s.get("handler") == "variant_name" and not (info or {}).get("variant_name"):
            row["reason"] = "the stock car has no variant name"
        elif missing:
            m = missing[0]
            row["reason"] = "%s %s: %s" % (m["file"], m["path"], m.get("error", "unresolved").removeprefix(m["path"] + ": "))
            if tyre_error and m["file"].startswith("@tyre_"):
                row["reason"] += " (%s)" % tyre_error
        elif s.get("hide_if_absent") and required and all(t["absent"] for t in required):
            row["reason"] = "field absent in the stock data"
        else:
            row["reason"] = None
        row["applicable"] = row["reason"] is None
        rows.append(row)
    return rows, tyre_error is None and (stock_name is None or complete_stock_info(info))


def engine_figures(points, limiter, boost):
    """(peak power in HP, peak torque in Nm) of an engine: points are the (rpm, Nm) pairs of its torque curve sorted by rpm (linear between them,
    0 outside), evaluated at every whole rpm from 500 to int(limiter), power = torque x rpm x 2 pi / 60 / 745.699872, each peak times
    (1 + boost) with boost the summed boost of its turbos in bar. None for fewer than 2 points, a limiter below 500 and a peak torque of 0 or less."""
    if len(points) < 2 or int(limiter) < CALCULATED_MIN_RPM:
        return None
    power = torque = 0.0
    i = 0
    for rpm in range(CALCULATED_MIN_RPM, int(limiter) + 1):
        while i + 1 < len(points) and points[i + 1][0] <= rpm:
            i += 1
        r0, v0 = points[i]
        if rpm < r0:
            continue
        if i + 1 < len(points):
            r1, v1 = points[i + 1]
            nm = v0 + (v1 - v0) * (rpm - r0) / (r1 - r0)
        elif rpm == r0:
            nm = v0
        else:
            continue
        torque = max(torque, nm)
        power = max(power, nm * rpm * 2 * math.pi / 60 / 745.699872)
    if torque <= 0:
        return None
    return power * (1 + boost), torque * (1 + boost)


def engine_inputs(work, car_id, root):
    """What the calculated display values read from the car at root: {"points" (the (rpm, Nm) of the engine's powerCurve sorted by rpm, a point
    without t at rpm 0), "limiter", "turbos" ([[max_boost, wastegate]] of its turbo files in turbos_to_load order, else of the engine's inline
    turbos; a wastegate that is missing is 0)}; None when the engine, its curve, its limiter or a turbo file cannot be read. Cached like
    resolve_defaults (per root, while resolve_stamp is unchanged, dropped by forget_resolved); the caller gets its own copy."""
    key, stamp = (work, car_id, root), resolve_stamp(work, car_id, root)
    with _resolve_lock:
        hit = _engine_inputs.get(key)
    if hit and stamp is not None and hit[0] == stamp:
        return copy.deepcopy(hit[1])
    try:
        found = read_engine_inputs(root, car_id)
    except (ValueError, OSError):
        return None
    if stamp is not None and resolve_stamp(work, car_id, root) == stamp:
        with _resolve_lock:
            _engine_inputs[key] = (stamp, copy.deepcopy(found))
    return found


def read_engine_inputs(root, car_id):
    """The uncached read of engine_inputs; a ValueError when something cannot be read."""
    cache, car_root = {}, car_root_of(root, car_id)
    engine = read_file(car_root, resolve_file("@engine", root, car_id, cache), cache)
    limiter = plain(engine.get("limiter"))
    text = engine.get("powerCurve")
    if not finite_number(limiter) or not isinstance(text, str) or not text:
        raise ValueError("no limiter or power curve")
    curve, _ = load_msg(curve_path(root, text))
    points = sorted((float(plain(p.get("t", 0))), float(plain(p.get("value", 0)))) for p in curve.get("points", []))
    turbos = [read_file(car_root, resolve_file("@turbo[%d]" % i, root, car_id, cache), cache) for i in range(len(engine.get("turbos_to_load", [])))]
    if not turbos:
        turbos = [t for t in engine.get("turbos", []) if isinstance(t, dict)]
    return {"points": points, "limiter": float(limiter),
            "turbos": [[float(plain(t.get("max_boost", 0))), float(plain(t.get("wastegate", 0)))] for t in turbos]}


def summed_boost(turbos):
    """The boost of a car in bar: every turbo gives min(max_boost, wastegate), max_boost alone when it has no wastegate (0)."""
    return sum(min(b, w) if w > 0 else b for b, w in turbos)


def state_number(state, setting_id):
    """The saved number of a setting, None when the state has none; a saved value that is no finite number is a ValueError."""
    if setting_id not in state:
        return None
    v = plain(state[setting_id])
    if not finite_number(v):
        raise ValueError("%s: no number" % setting_id)
    return float(v)


def calculated_display(work, car_id, tune, version, state, rows):
    """The calculated values of the displayed power and torque ({setting id: whole number as a float}; only the ones offered, an empty dict when
    the figures cannot be calculated). stock = the base car at power scale 1; now = root_for of the tune (or version) with the saved power_scale,
    limiter, turbo_boost_<n> and turbo_wastegate_<n> of its state (n = 1, 2: in place of the n-th turbo's max_boost and wastegate, a turbo that
    does not exist ignores them; no saved value: the file's). The value is the row's default x the peak of now / the peak of stock, rounded half
    up, offered when it differs from the default by at least 1; rows are the effective rows (the default of each setting)."""
    try:
        stock = engine_inputs(work, car_id, base_dir(work, car_id))
        now = engine_inputs(work, car_id, root_for(work, car_id, tune, version))
        if stock is None or now is None:
            return {}
        scale = state_number(state, "power_scale")
        limiter = state_number(state, "limiter")
        for n, turbo in enumerate(now["turbos"][:2], 1):
            for j, name in enumerate(("turbo_boost_%d", "turbo_wastegate_%d")):
                saved = state_number(state, name % n)
                if saved is not None:
                    turbo[j] = saved
        figures = (engine_figures(stock["points"], stock["limiter"], summed_boost(stock["turbos"])),
                   engine_figures(now["points"], now["limiter"] if limiter is None else limiter, summed_boost(now["turbos"])))
    except (ValueError, OSError):
        return {}
    if None in figures:
        return {}
    out = {}
    for row in rows:
        i = CALCULATED_SETTINGS.get(row["id"])
        if i is not None and finite_number(plain(row["default"])):
            default = float(plain(row["default"]))
            value = float(math.floor(default * (1 if scale is None else scale) * figures[1][i] / figures[0][i] + 0.5))
            if abs(value - default) >= 1:
                out[row["id"]] = value
    return out


def effective_rows(work, car_id, catalogue=None, hidden=False, tune=None, version=None):
    """The rows of resolve_defaults with the saved value of the state of tune (None: the default tune) as value and whether it differs from the default as changed; with version the state of that version (load_version_state). An applicable variant_name without a saved value reads "Base" when the tune has a version."""
    cat = catalogue or load_catalogue()
    state = load_state(work, car_id, tune) if version is None else load_version_state(work, car_id, version, tune, cat)
    rows = resolve_defaults(work, car_id, cat, hidden=hidden, tune=new_id_for(car_id) if tune is None else tune, version=version)
    calculated = None
    for row in rows:
        s = find_setting(cat, row["id"])
        row["value"] = saved_value(s, state[s["id"]]) if s["id"] in state else row["default"]
        row["changed"] = s["id"] in state and not same(s, row["value"], row["default"])
        if s.get("handler") == "variant_name" and row["applicable"] and s["id"] not in state and tune != DRAFT and list_versions(work, car_id, tune):
            row["value"] = BASE_NAME
            row["changed"] = not same(s, row["value"], row["default"])
        if s["id"] in CALCULATED_SETTINGS and row["applicable"] and s["id"] not in state:
            if calculated is None:
                calculated = calculated_display(work, car_id, new_id_for(car_id) if tune is None else tune, version, state, rows)
            if s["id"] in calculated:
                row.update(value=calculated[s["id"]], changed=True, calculated=True)
    return rows


def effective_row(work, car_id, setting_id, catalogue=None, tune=None, version=None):
    """The row of one setting as effective_rows(hidden=True) gives it, resolving only that setting."""
    cat = catalogue or load_catalogue()
    return effective_rows(work, car_id, dict(cat, settings=[find_setting(cat, setting_id)]), hidden=True, tune=tune, version=version)[0]


def scale_curve(curve, factor):
    for p in curve.get("points", []):
        if "value" in p:
            p["value"] = to_f32(p["value"] * factor)


def repoint(obj, field, old_text, new_text):
    """Replace, in the text (or list of texts) field of obj, every value equal to old_text; returns how many."""
    hits = 0
    values = obj.get(field)
    for i, v in enumerate(values if isinstance(values, list) else [values]):
        if isinstance(v, str) and game_path_key(v) == game_path_key(old_text):
            if isinstance(values, list):
                values[i] = new_text
            else:
                obj[field] = new_text
            hits += 1
    return hits


def build_tyre(root, car_id, new_id, car_root, role, edits, cache, counts=None):
    """Give the tuned car its own copy of the stock tyre file of an axle (role tyre_front / tyre_rear): copy it from
    base to data/tyres/<new_id>_<axle>.tyre, write the changed values (edits: (item, field, value)) and point the
    references of the stock file at the copy. Returns a note for the build log; counts, when given, gets the number of
    references that were pointed at the copy (.car entries and compatibletyres entries together)."""
    axle = role[len("tyre_"):]
    stock_text = tyre_text(root, car_id, role, cache)
    rel = "data/tyres/%s_%s.tyre" % (new_id, axle)
    new_text = "content\\cars\\%s\\%s" % (new_id, rel.replace("/", "\\"))
    path = car_path(car_root, rel)
    obj, name = load_msg(car_path(car_root_of(root, car_id), resolve_file("@" + role, root, car_id, cache)))
    for item, field, v in edits:
        put_value(obj, field, v)
        if rel not in item["files"]:
            item["files"].append(rel)
    os.makedirs(kspkg.long_path(os.path.dirname(path)), exist_ok=True)
    save_msg(path, name, obj)
    car_rel = renamed(resolve_file("@car", root, car_id, cache), car_id, new_id)
    car_file = car_path(car_root, car_rel)
    car, car_name = load_msg(car_file)
    in_car = repoint(car, TYRE_ROLES[role], stock_text, new_text)
    if in_car:
        save_msg(car_file, car_name, car)
    in_presets = 0
    folder = os.path.join(car_root, "presets")
    for n in preset_files(folder):
        preset, preset_name = load_msg(os.path.join(folder, n))
        hits = sum(repoint(pc, "front_tyre_data_path" if axle == "front" else "rear_tyre_data_paths",
                           stock_text, new_text) for pc in preset.get("physic_compounds", []))
        if hits:
            save_msg(os.path.join(folder, n), preset_name, preset)
            in_presets += hits
    if counts is not None:
        counts.append(in_car + in_presets)
    return "note: tyre %s: own file %s replaces %s in %d .car entry(ies) and %d compatibletyres entry(ies)" % (
        axle, new_text, stock_text, in_car, in_presets)


def plan_target(work, car_id, new_id, install, mods_dir, version=None):
    """Checks that need no catalogue: base car, ids and tune. Returns (root_for of the tune or of its version, mods folder or None); a turbo
    kit is built or refreshed here, before anything else is written."""
    root = base_dir(work, car_id)
    if not os.path.isdir(kspkg.long_path(car_root_of(root, car_id))):
        raise ValueError("no base car in %s, run init first" % root)
    mods = clone_car.expand_dir(mods_dir, clone_car.DEFAULT_MODS, "mods directory", "--mods") if install else None
    # ids only: the "unused" folder never exists, an old build of the same id is replaced below
    clone_car.validate(car_id, new_id, os.path.join(build_dir(work, car_id), "unused"))
    if (not is_default_tune(car_id, new_id) and not os.path.isdir(kspkg.long_path(tune_dir(work, car_id, new_id)))
            and list_tunes(work, car_id)):
        raise ValueError("%s is not a modded car of %s, create it with duplicate first" % (new_id, car_id))
    return root_for(work, car_id, new_id, version), mods


def changed_settings(work, car_id, new_id, cat, version=None):
    """Returns (rows, changed): every row and the (setting, row) pairs that differ from the default; refuses unusable changes."""
    rows = effective_rows(work, car_id, cat, hidden=True, tune=new_id, version=version)
    changed = [(s, r) for s, r in zip(cat["settings"], rows) if r["changed"]]
    bad = ["%s (%s)" % (s["id"], r["reason"]) for s, r in changed if not r["applicable"]]
    if bad:
        raise ValueError("cannot apply the changed setting(s), not applicable to %s: %s" % (car_id, ", ".join(bad)))
    for s, r in changed:
        for t in r["targets"] if s["kind"] == "value" else []:
            if t["resolved"] and t["file"] in TYRE_FILES and not t["rel"].startswith(SHARED):
                raise ValueError("%s: the tyre file is inside the car folder, not supported yet" % t["file"])
    return rows, changed


def apply_plan(work, car_id, new_id, install, mods_dir, cat, version=None, game=DEFAULT_GAME):
    """Everything apply needs, checked before anything is built: root (base, or the kit root of a tune with a turbo kit), mods, rows,
    changed, info, garage (the tyre_plan of the state's tyre choice or None), kit (the kit.json of the kit root or None) and sounds (sound_plan, [] without a saved choice).
    With version the plan of that version of the tune: its state decides, the meta settings and the name suffix check are the base's; game
    is the game package the tyres of a tyre choice are checked against."""
    root, mods = plan_target(work, car_id, new_id, install, mods_dir, version)
    state = load_state(work, car_id, new_id) if version is None else load_version_state(work, car_id, version, new_id, cat)
    garage = tyre_plan(work, car_id, new_id, root, state, cat, game) if TYRE_KEY in state else None
    rows, changed = changed_settings(work, car_id, new_id, cat, version)
    info = load_stock_info(work, car_id)
    if info is None and car_id != load_cars()["default"]:
        raise ValueError("stock info missing, run init with the game installed")
    info = info or {}
    suffix_id = name_suffix_setting(cat)["id"]
    name_suffix = next(r["value"] for r in rows if r["id"] == suffix_id)
    owner = suffix_owner(work, car_id, name_suffix, exclude=new_id) if version is None else None
    if owner:
        raise ValueError("car name %s is already used by %s" % (name_suffix, owner))
    kit = kit_info(root) if TURBO_KEY in state else None
    sound_steps = sound_plan(work, car_id, state) if SOUND_KEY in state else []
    return {"root": root, "mods": mods, "rows": rows, "changed": changed, "info": info, "garage": garage, "kit": kit, "sounds": sound_steps}


def plan_name(car_id, plan, suffix):
    """The game name of the car a plan builds: car_name of the stock display name (stock_info.json, else the preset) and the suffix."""
    return car_name(plan["info"].get("display_name") or preset_display_name(car_root_of(plan["root"], car_id)), suffix)


def build_partial(work, car_id, new_id, out_dir, plan, cat, game):
    """Clone the car under the new id into <out_dir>.partial (an old one is removed first). Returns (folder, meta values, notes)."""
    root, rows, info = plan["root"], plan["rows"], plan["info"]
    # the build always starts from the pristine base, in <new_id>.partial: the previous build of this id stays until the new one is complete
    part = out_dir + ".partial"
    if os.path.exists(kspkg.long_path(part)):
        remove_tree(work, part)
    meta = {s["handler"]: r["value"] for s, r in zip(cat["settings"], rows) if s["kind"] == "meta"}
    with contextlib.suppress(ValueError, OSError):
        ensure_stock_loc(work, game)
    stock_loc = stock_loc_path(work) if os.path.isfile(stock_loc_path(work)) else None
    name = plan_name(car_id, plan, meta["name_suffix"])
    log = io.StringIO()
    try:
        # kspkg and clone_car print their progress: keep it out of this command's output
        with _stdout_lock, contextlib.redirect_stdout(log):
            notes = clone_car.build(car_root_of(root, car_id), new_id, part, name,
                                    info.get("year", CLONE_YEAR), info.get("brand", CLONE_BRAND),
                                    meta["variant_name"], stock_loc, {k: info.get(k) for k in STOCK_PROPERTIES},
                                    pack=False)
    except ValueError as e:
        if not str(e).startswith("self-check failed"):
            raise
        raise ValueError("clone self-check failed:\n" + log.getvalue().rstrip()) from None
    return part, meta, notes


def scale_curve_file(s, r, car_id, new_id, part, car_root):
    """Write the scaled curve of a curve_scale setting into the build; returns its path below the car folder."""
    text, _ = get_value(load_msg(car_path(car_root, renamed(r["targets"][0]["rel"], car_id, new_id)))[0],
                        s["curve_from"]["path"])
    path = curve_path(part, text)
    curve, name = load_msg(path)
    scale_curve(curve, r["value"])
    save_msg(path, name, curve)
    return os.path.relpath(path, car_root).replace(os.sep, "/")


def flag_edits(s, r, car_id, new_id, item, edits):
    for t in r["targets"]:
        if t["resolved"] and not (t["absent"] and s["value"] == 0):
            edits.setdefault(renamed(t["rel"], car_id, new_id), []).append((item, t["path"], s["value"]))


def value_edits(s, r, car_id, new_id, item, edits, tyre_edits):
    v = to_f32(r["value"]) if s["type"] == "float" else r["value"]
    if s.get("choice_values"):
        v = s["choice_values"][v]
    for t in r["targets"]:
        if t["resolved"] and t["file"] in TYRE_FILES:
            tyre_edits.setdefault(t["file"][1:], []).append((item, t["path"], v))
        elif t["resolved"]:
            edits.setdefault(renamed(t["rel"], car_id, new_id), []).append((item, t["path"], v))


def collect_edits(car_id, new_id, changed, part, car_root):
    """Returns (edits by file, tyre edits by role, applied list) of the changed settings; writes the scaled curve files."""
    edits, tyre_edits, applied = {}, {}, []
    # flags last: a flag wins over a value on the same field
    for s, r in sorted(changed, key=lambda sr: sr[0]["kind"] == "flag"):
        item = {"id": s["id"], "old": r["default"], "new": r["value"], "files": []}
        applied.append(item)
        if s["kind"] == "meta":
            item["files"].append(new_id + "." + clone_car.MODDED_TYPE if s["handler"] == "name_suffix"
                                 else "/".join(clone_car.LOC_PATH))
        elif s["kind"] == "curve_scale":
            item["files"].append(scale_curve_file(s, r, car_id, new_id, part, car_root))
        elif s["kind"] == "flag":
            flag_edits(s, r, car_id, new_id, item, edits)
        else:
            value_edits(s, r, car_id, new_id, item, edits, tyre_edits)
    return edits, tyre_edits, applied


def write_edits(car_root, edits):
    """Write the value edits into the files of the build."""
    for rel, items in edits.items():
        path = car_path(car_root, rel)
        obj, name = load_msg(path)
        for item, field, v in items:
            put_value(obj, field, v)
            if rel not in item["files"]:
                item["files"].append(rel)
        save_msg(path, name, obj)


def write_tyres(root, car_id, new_id, car_root, garage, tyre_edits):
    """The tyre choice step and the per-car tyre step of the build. Returns their notes for the build log."""
    notes = []
    cache = {}
    if garage:
        notes += write_tyre_choice(car_root, garage)
    for role, items in tyre_edits.items():
        notes.append(build_tyre(root, car_id, new_id, car_root, role, items, cache))
    return notes


def game_path_of(car_id, rel):
    return "content\\cars\\%s\\%s" % (car_id, rel.replace("/", "\\"))


def retarget(obj, targets):
    """Replace, in every text of the decoded message obj (any depth), a game path that is a key of targets (game_path_key) by its
    value, with the slashes of the text kept. Returns how many texts changed."""
    hits = 0
    for k, v in list(obj.items() if isinstance(obj, dict) else enumerate(obj)):
        if isinstance(v, str):
            new = targets.get(game_path_key(v))
            if new is not None:
                obj[k] = new.replace("\\", "/") if "/" in v and "\\" not in v else new
                hits += 1
        elif isinstance(v, (dict, list)):
            hits += retarget(v, targets)
    return hits


def rename_files(car_root, mapping):
    """Give files of a build's car folder new names and point every reference at them. mapping = {old path: new path}, both relative
    to car_root (with /, the old one matched case-insensitively). Every decodable file of the folder has each text that is the game
    path (content\\cars\\<id>\\<path>, either slash, case-insensitive) of a renamed file replaced by the new one and is written back
    only when one changed; a file that holds an old path as text but cannot be rewritten (not decodable, or the path is not a text
    field of it) is an error, nothing is written then. Returns {"renamed": [(old, new)], "rewritten": {path after the renames:
    number of texts changed}}, both sorted."""
    car_id = os.path.basename(os.path.normpath(car_root))

    def ident(path):
        return os.path.realpath(kspkg.plain_path(path)).lower()

    moves, targets, texts = [], {}, []
    for old, new in mapping.items():
        src = find_ci(car_root, old)
        if not os.path.isfile(kspkg.long_path(src)):
            raise ValueError("%s is not a file" % old)
        new_rel = "/".join(filter(None, re.split(r"[\\/]+", new)))
        dst = car_path(car_root, new_rel)
        dst = os.path.join(os.path.dirname(dst), new_rel.rsplit("/", 1)[-1])
        try:
            taken = find_ci(car_root, new)
        except ValueError:
            taken = None
        if taken and ident(taken) != ident(src):
            raise ValueError("cannot rename %s to %s: the name is taken" % (old, new))
        if any(ident(src) == ident(m[0]) or ident(dst) == ident(m[1]) for m in moves):
            raise ValueError("%s -> %s: a file is listed twice in the renames" % (old, new))
        old_rel = os.path.relpath(src, car_root).replace(os.sep, "/")
        moves.append((src, dst, old_rel, new_rel))
        targets[game_path_key(game_path_of(car_id, old_rel))] = game_path_of(car_id, new_rel)
        texts.append(re.escape(game_path_of(car_id, old_rel)).replace("\\\\", "[\\\\/]").encode())
    if any(ident(m[1]) == ident(o[0]) for m in moves for o in moves if m is not o):
        raise ValueError("a file cannot be renamed to the name another renamed file has now")
    refers = re.compile(b"|".join(texts), re.IGNORECASE)
    base = kspkg.long_path(car_root)
    rewrites = []
    for dp, _, names in os.walk(base):
        for n in sorted(names):
            path = os.path.join(dp, n)
            rel = os.path.relpath(path, base).replace(os.sep, "/")
            obj, err = None, None
            try:
                obj, name = load_msg(path)
            except ValueError as e:
                err = e
            hits = retarget(obj, targets) if obj is not None else 0
            if hits:
                rewrites.append((path, rel, name, obj, hits))
                continue
            with open(path, "rb") as f:
                found = refers.search(f.read())
            if found:
                raise ValueError("%s refers to %s, which is renamed, but %s; its bytes are not patched"
                                 % (rel, found.group().decode("ascii", "replace"),
                                    "cannot be decoded (%s)" % err if err else "not in a text field of it"))
    for path, _, name, obj, _ in rewrites:
        save_msg(path, name, obj)
    for src, dst, _, _ in moves:
        os.makedirs(kspkg.long_path(os.path.dirname(dst)), exist_ok=True)
        os.rename(kspkg.long_path(src), kspkg.long_path(dst))
    after = {ident(src): new_rel for src, _, _, new_rel in moves}
    return {"renamed": sorted((old_rel, new_rel) for _, _, old_rel, new_rel in moves),
            "rewritten": dict(sorted((after.get(ident(path), rel), hits) for path, rel, _, _, hits in rewrites))}


def rename_car_file(part, new_id, applied):
    """The car file of the build gets the name the paint shop of a mod car expects (data/CarData.car) unless it has it already
    (case-insensitive), and every reference to it is rewritten; the file lists of applied are brought along. Returns the notes."""
    rel = resolve_file("@car", part, new_id, {})
    if rel.rsplit("/", 1)[-1].lower() == CAR_FILE.rsplit("/", 1)[-1].lower():
        return []
    res = rename_files(car_root_of(part, new_id), {rel: CAR_FILE})
    for item in applied:
        item["files"] = [CAR_FILE if f.lower() == rel.lower() else f for f in item["files"]]
    return ["note: car file: %s renamed to %s (the paint shop of a mod car expects that name)" % (rel, CAR_FILE)]


def tree_files(car_root):
    """The files below a car folder as paths relative to it (with /), sorted."""
    base = kspkg.long_path(car_root)
    return sorted(os.path.relpath(os.path.join(dp, n), base).replace(os.sep, "/") for dp, _, names in os.walk(base) for n in names)


def tree_path(car_root, rel):
    return os.path.join(car_root, *rel.split("/"))


def same_file(a, b):
    """Whether two files have the same bytes."""
    return filecmp.cmp(kspkg.long_path(a), kspkg.long_path(b), shallow=False)


def text_values(obj):
    """Every text of a decoded message, at any depth."""
    for v in obj.values() if isinstance(obj, dict) else obj:
        if isinstance(v, str):
            yield v
        elif isinstance(v, (dict, list)):
            yield from text_values(v)


def path_pattern(car_id, rels):
    """A byte pattern for the game paths (either slash, case-insensitive) of the files rels of the car folder."""
    return re.compile(b"|".join(re.escape(game_path_of(car_id, r)).replace("\\\\", "[\\\\/]").encode() for r in rels), re.IGNORECASE)


def version_excluded(rel):
    """Files of a version build that never become files of the version: the actor, the moddedcarcontent, the user interface and
    localization files and everything generated (thumbnails ...)."""
    low = rel.lower()
    return low.startswith(VERSION_SKIP_FOLDERS) or low.endswith(VERSION_SKIP_TYPES)


def version_files(car_root, rels, seed):
    """The files of a version: seed plus, until nothing new is added, every other file of the car folder that refers to one of them by
    game path (the matching of rename_files: a text of a decoded file, or the bytes of any file); the files of version_excluded are
    never added. Returns the set of paths relative to the car folder."""
    car_id = os.path.basename(os.path.normpath(car_root))
    members, fresh, texts = set(seed), sorted(seed), {}
    while fresh:
        keys = {game_path_key(game_path_of(car_id, r)) for r in fresh}
        refers = path_pattern(car_id, fresh)
        fresh = []
        for rel in rels:
            if rel in members or version_excluded(rel):
                continue
            path = tree_path(car_root, rel)
            if rel not in texts:
                try:
                    texts[rel] = {game_path_key(t) for t in text_values(load_msg(path)[0])}
                except ValueError:
                    texts[rel] = set()
            found = bool(texts[rel] & keys)
            if not found:
                with open(kspkg.long_path(path), "rb") as f:
                    found = bool(refers.search(f.read()))
            if found:
                members.add(rel)
                fresh.append(rel)
    return members


def version_rel(rel, version):
    """The path of a version's copy of a file: the same folder, the name with _<version> before the extension."""
    folder, _, name = rel.rpartition("/")
    stem, ext = os.path.splitext(name)
    return "%s%s_%s%s" % (folder + "/" if folder else "", stem, version, ext)


def version_description(description, name):
    """The description of a version's preset: the base description with a trailing word Base replaced by the name, else followed by it."""
    if re.search(r"(?:^|\s)Base$", description):
        return description[:-4] + name
    return ("%s %s" % (description, name)).strip()


def description_slug(description):
    """The key part the game derives from the description of a mechanical preset (JavaScript description.toLowerCase().replace(/[\\W_]+/g, "_"))."""
    return re.sub(r"[\W_]+", "_", description.lower(), flags=re.ASCII)


def version_finals(vroot, rels, car_id, preset, version, copied=()):
    """The carfinalstate files of the car folder vroot whose body.path is the base mechanical preset (path preset), as
    {path: (path of the version's copy, name of the base's visual preset, name of the visual preset the version uses)}: the copy is named
    <car id>_<preset of the version>_<visual preset the version uses>; that is <visual preset>_<version> when presets/<visual preset>.visualcarpreset
    is among the paths copied (the version has its own copy of it), else the base's <visual preset>."""
    stem = os.path.splitext(preset.rsplit("/", 1)[-1])[0]
    prefix = "%s_%s_" % (car_id, stem)
    copied = {c.lower() for c in copied}
    finals = {}
    for rel in rels:
        if not rel.lower().endswith(".carfinalstate"):
            continue
        if game_path_key((load_msg(tree_path(vroot, rel))[0].get("body") or {}).get("path", "")) != game_path_key(game_path_of(car_id, preset)):
            continue
        folder, _, name = rel.rpartition("/")
        stem_of, ext = os.path.splitext(name)
        if not stem_of.lower().startswith(prefix.lower()):
            raise ValueError("%s: a carfinalstate is named <car id>_<preset>_<visual preset>.carfinalstate, cannot name the one of version %s"
                             % (rel, version))
        visual = stem_of[len(prefix):]
        used = "%s_%s" % (visual, version) if "presets/%s.visualcarpreset" % visual.lower() in copied else visual
        finals[rel] = ("%s%s_%s_%s%s" % (folder + "/" if folder else "", car_id, "%s_%s" % (stem, version), used, ext), visual, used)
    return finals


def copy_version_files(vroot, root, car_id, names, edit):
    """Copy files of the version build vroot into the build root under new names (names = {path: new path}, relative to the car
    folders) and rewrite in the copies every reference to a renamed file; edit(old path, decoded message) may change a copy further.
    A file that holds an old path but cannot be rewritten is an error (like rename_files), found before anything is written."""
    targets = {game_path_key(game_path_of(car_id, old)): game_path_of(car_id, new) for old, new in names.items()}
    refers = path_pattern(car_id, names)
    copies = []
    for old, new in sorted(names.items()):
        src, dst = tree_path(vroot, old), tree_path(root, new)
        if os.path.exists(kspkg.long_path(dst)):
            raise ValueError("cannot copy %s to %s: the name is taken" % (old, new))
        obj, err, name = None, None, None
        try:
            obj, name = load_msg(src)
        except ValueError as e:
            err = e
        if obj is None or not retarget(obj, targets):
            with open(kspkg.long_path(src), "rb") as f:
                found = refers.search(f.read())
            if found:
                raise ValueError("%s refers to %s, which is copied under a new name, but %s; its bytes are not patched"
                                 % (old, found.group().decode("ascii", "replace"),
                                    "cannot be decoded (%s)" % err if err else "not in a text field of it"))
        if obj is not None:
            edit(old, obj)
        copies.append((src, dst, name, obj))
    for src, dst, name, obj in copies:
        os.makedirs(kspkg.long_path(os.path.dirname(dst)), exist_ok=True)
        if obj is None:
            shutil.copyfile(kspkg.long_path(src), kspkg.long_path(dst))
        else:
            save_msg(dst, name, obj)


def merge_version(part, vpart, new_id, version, name, taken=()):
    """Merge the build vpart of a version of a tune (the same tune id, built from the state of the version) into the build part of the
    base. The version's own files are the files whose bytes differ from the base build or are missing there, the base
    mechanical preset and its carfinalstate(s), every file of the version build below data/ (any depth) and every presets/*.compatibletyres
    directly in presets/ (the files the tuner writes, so the version shares none of them with the base), and every file that refers to
    one of them (version_files), but never the car file: the game saves a painted version with the base's data/CarData.car, so the
    version's carfinalstate(s) keep pointing at it and the version's physics reach the car through forced car parts (add_version_physics).
    They are copied under the
    name with _<version> before the extension (the carfinalstate: <car id>_<version preset>_<visual preset the version uses>.carfinalstate,
    where that is <visual preset>_<version> when the version has its own copy of presets/<visual preset>.visualcarpreset, else the base's
    visual preset) and point at each other; the preset gets the name of the version as note, its description (version_description, followed by
    " <version>" when the description_slug of it is one of taken: the slugs of the base preset and of the other versions of the build) and
    is_oem false; the thumbnails <car id>-<base preset>-<visual preset> of the base's carfinalstate(s) are copied as
    <car id>-<version preset>-<visual preset the version uses>. The actor, the moddedcarcontent, uiresources
    and generated files are never copied. Returns (number of own files, game path of the version's preset, notes, the paths written into
    the car folder of the build part (the copies and the thumbnail copies, relative to it), {game_path_key of a copied file: game path of
    its copy}, the paths of the carfinalstate copies relative to the car folder); the list of presets in the actor is the caller's."""
    root, vroot = car_root_of(part, new_id), car_root_of(vpart, new_id)
    rels = tree_files(vroot)
    own = {r for r in rels if not version_excluded(r) and (not os.path.isfile(kspkg.long_path(tree_path(root, r)))
                                                          or not same_file(tree_path(root, r), tree_path(vroot, r)))}
    preset = resolve_file("@mech_preset", vpart, new_id, {})
    finals = version_finals(vroot, rels, new_id, preset, version)
    tuner_files = {r for r in rels if not version_excluded(r) and (r.lower().startswith("data/") or (
        r.lower().startswith("presets/") and "/" not in r[len("presets/"):] and r.lower().endswith(".compatibletyres")))}
    car = resolve_file("@car", vpart, new_id, {})
    files = version_files(vroot, rels, own | tuner_files | {car, preset} | set(finals)) - {car}
    finals = version_finals(vroot, rels, new_id, preset, version, files)
    names = {r: finals[r][0] if r in finals else version_rel(r, version) for r in files}

    def edit(old, obj):
        if old == preset:
            put_value(obj, "note", name)
            put_value(obj, "is_oem", False)
            description = version_description(obj.get("description", ""), name)
            if description_slug(description) in taken:
                description = "%s %s" % (description, version)
            put_value(obj, "description", description)

    copy_version_files(vroot, root, new_id, names, edit)
    notes, written = [], set(names.values())
    stem = os.path.splitext(preset.rsplit("/", 1)[-1])[0]
    for _, visual, used in finals.values():
        for ext in (".texture", ".texturemips"):
            src, dst = ("generated/thumbnails/%s-%s-%s%s" % (new_id, s, v, ext) for s, v in ((stem, visual), ("%s_%s" % (stem, version), used)))
            if os.path.isfile(kspkg.long_path(tree_path(root, src))):
                shutil.copyfile(kspkg.long_path(tree_path(root, src)), kspkg.long_path(tree_path(root, dst)))
                written.add(dst)
            else:
                notes.append("note: version %s: no thumbnail %s to copy" % (version, src))
    copies = {game_path_key(game_path_of(new_id, old)): game_path_of(new_id, new) for old, new in names.items()}
    return len(files), game_path_of(new_id, names[preset]), notes, sorted(written), copies, sorted(finals[r][0] for r in finals)


def add_version_presets(part, new_id, presets):
    """Append the game paths of the version presets to the mechanical presets of the actor of the build."""
    path = find_ci(car_root_of(part, new_id), new_id + ".actor")
    actor, name = load_msg(path)
    field = "car.customization.mechanical_car_presets"
    current, absent = get_value(actor, field, missing_ok=True)
    if absent or not isinstance(current, list):
        raise ValueError("%s has no %s to list the versions in" % (os.path.basename(path), field))
    put_value(actor, field, current + presets)
    save_msg(path, name, actor)


def preset_of_game_path(root, game_path):
    """The decoded mechanical preset with the game path game_path ("content\\cars\\<id>\\<path>") in the car folder root."""
    return load_msg(tree_path(root, game_path.split("\\", 3)[3].replace("\\", "/")))[0]


def add_version_visuals(part, new_id, presets):
    """Make the visual presets of the version presets (game paths presets, read from the build part) known to the game: every path of
    their visual_preset_paths that the actor of the build does not list yet (game_path_key) is appended to
    car.customization.visual_car_presets, then the car_design_path of each of those visual presets that car.customization.car_designs does
    not list yet. The base's entries stay first; compatible_rims is not touched (the rims of the versions are add_version_rims')."""
    root = car_root_of(part, new_id)
    path = find_ci(root, new_id + ".actor")
    actor, name = load_msg(path)
    lists = {}
    for field in ("car.customization.visual_car_presets", "car.customization.car_designs"):
        current, absent = get_value(actor, field, missing_ok=True)
        lists[field] = [] if absent else list(current)
    visuals, designs = lists["car.customization.visual_car_presets"], lists["car.customization.car_designs"]
    new_visuals, new_designs = [], []
    for preset in presets:
        for visual in preset_of_game_path(root, preset).get("visual_preset_paths") or []:
            if game_path_key(visual) not in {game_path_key(v) for v in visuals + new_visuals}:
                new_visuals.append(visual)
    for visual in new_visuals:
        file = tree_path(root, visual.split("\\", 3)[3].replace("\\", "/"))
        design = load_msg(file)[0].get("car_design_path") if os.path.isfile(kspkg.long_path(file)) else None
        if design and game_path_key(design) not in {game_path_key(d) for d in designs + new_designs}:
            new_designs.append(design)
    if new_visuals:
        append_paths(actor, "car.customization.visual_car_presets", new_visuals)
    if new_designs:
        append_paths(actor, "car.customization.car_designs", new_designs)
    if new_visuals or new_designs:
        save_msg(path, name, actor)


def add_version_rims(part, new_id, base_preset, presets, locked):
    """Make the rims of the version presets (game paths presets, in the order of the versions; locked = whether each is a locked
    version) known to the game, which crashes in the paint shop ("map key not found") on a rim the actor does not list: every
    compatible_rim of those presets that neither car.customization.compatible_rims nor car.customization.aftermarket_rims of the
    actor lists (game_path_key) is appended to car.customization.aftermarket_rims (the Supra MKIV lists its drift rim there), compatible_rims
    is not touched. When one was appended, the base mechanical preset (base_preset: its path relative to the car folder, resolved before
    the merges) and the preset of every unlocked version get every rim of its compatible_rim followed by those appended, except its own,
    that its not_compatible_rim_paths does not list yet; the preset of a locked version is never changed (its files stay as kept).
    Nothing is rewritten when no rim was appended."""
    root = car_root_of(part, new_id)
    path = find_ci(root, new_id + ".actor")
    actor, name = load_msg(path)
    customization = (actor.get("car") or {}).get("customization") or {}
    listed = {game_path_key(r) for field in ("compatible_rims", "aftermarket_rims") for r in customization.get(field) or []}
    new = []
    for preset in presets:
        rim = preset_of_game_path(root, preset).get("compatible_rim")
        if rim and game_path_key(rim) not in listed:
            listed.add(game_path_key(rim))
            new.append(rim)
    if not new:
        return
    append_paths(actor, "car.customization.aftermarket_rims", new)
    save_msg(path, name, actor)
    base_rim = load_msg(tree_path(root, base_preset))[0].get("compatible_rim")
    every = ([base_rim] if base_rim else []) + new
    targets = [base_preset] + [preset.split("\\", 3)[3].replace("\\", "/") for preset, is_locked in zip(presets, locked) if not is_locked]
    for target in targets:
        file = tree_path(root, target)
        obj, kind = load_msg(file)
        own = game_path_key(obj.get("compatible_rim") or "")
        known = {game_path_key(r) for r in obj.get("not_compatible_rim_paths") or []} | {own}
        forbidden = []
        for rim in every:
            if game_path_key(rim) not in known:
                known.add(game_path_key(rim))
                forbidden.append(rim)
        if forbidden:
            append_paths(obj, "not_compatible_rim_paths", forbidden)
            save_msg(file, kind, obj)


def add_version_names(part, new_id, versions):
    """Give each version its menu text: the line "<tune id>_<description_slug of the description of its preset in the build part>=<version
    name>" appended to uiresources/localization/en.cars.loc of the build (UTF-8 without BOM, CRLF lines like clone_car.write_localization;
    the file is created when the build has none; an existing line is never changed). versions = [(version name, game path of its preset)]
    in the order of the versions."""
    root = car_root_of(part, new_id)
    path = tree_path(root, "/".join(clone_car.LOC_PATH))
    data = b""
    if os.path.isfile(kspkg.long_path(path)):
        with open(kspkg.long_path(path), "rb") as f:
            data = f.read()
    if data and not data.endswith(b"\n"):
        data += b"\r\n"
    lines = ["%s_%s=%s" % (new_id, description_slug(preset_of_game_path(root, preset).get("description", "")), name) for name, preset in versions]
    os.makedirs(kspkg.long_path(os.path.dirname(path)), exist_ok=True)
    with open(kspkg.long_path(path), "wb") as f:
        f.write(data + "".join(line + "\r\n" for line in lines).encode("utf-8"))


def check_versions(part, new_id, versions, presets):
    """Refuse a build in which the game would not show a version (the build part is packed only after this). For the mechanical preset of
    each version (game paths presets, in the order of versions = [{id, name}]) every path of its visual_preset_paths must be listed in
    car.customization.visual_car_presets of the actor and exist in the build, presets/<new id>_<preset>_<visual preset>.carfinalstate must
    exist and name the preset as its body.path, and the localization line of the version must exist. Then (version_faults) its compatible_rim
    (when it has one) and the rims.path of each of its carfinalstates (when present) must be listed in car.customization.compatible_rims or
    aftermarket_rims of the actor, the compatible_rim must exist in the build (the game crashes in the paint shop on a rim the actor does not
    list), the body.design of each carfinalstate (when present) must be one of the visual_preset_paths of the preset and the car_design_path
    of each visual preset must be in car.customization.car_designs, the car_data of each carfinalstate must exist in the build and every
    forced_compatible_part_paths entry of the preset that lies in the car folder must be listed in car.customization.aftermarket_parts, be in
    the parts of each carfinalstate and exist with its car part, the tuning parts of it and the files of the car folder those name.
    Raises ValueError "version <id> (<name>) would not show in the game:
    <what is missing>" for the first fault found, "version <id> (<name>) would crash the game: <what>" for a rim or part fault. Thumbnails are not
    checked."""
    if not versions:
        return
    root = car_root_of(part, new_id)
    actor = load_msg(find_ci(root, new_id + ".actor"))[0]
    listed = {game_path_key(v) for v in get_value(actor, "car.customization.visual_car_presets", missing_ok=True)[0] or []}
    rims = {game_path_key(r) for field in ("compatible_rims", "aftermarket_rims") for r in get_value(actor, "car.customization." + field, missing_ok=True)[0] or []}
    designs = {game_path_key(d) for d in get_value(actor, "car.customization.car_designs", missing_ok=True)[0] or []}
    listed_parts = {game_path_key(p) for p in get_value(actor, "car.customization.aftermarket_parts", missing_ok=True)[0] or []}
    loc_path = tree_path(root, "/".join(clone_car.LOC_PATH))
    keys = set()
    if os.path.isfile(kspkg.long_path(loc_path)):
        with open(kspkg.long_path(loc_path), "rb") as f:
            keys = {line.split("=", 1)[0] for line in f.read().decode("utf-8").splitlines()}
    for v, preset in zip(versions, presets):
        stem = os.path.splitext(preset.rsplit("\\", 1)[-1])[0]
        missing = None
        for visual in preset_of_game_path(root, preset).get("visual_preset_paths") or []:
            final = "presets/%s_%s_%s.carfinalstate" % (new_id, stem, os.path.splitext(visual.rsplit("\\", 1)[-1])[0])
            if game_path_key(visual) not in listed:
                missing = "%s is not in car.customization.visual_car_presets of the actor" % visual
            elif not os.path.isfile(kspkg.long_path(tree_path(root, visual.split("\\", 3)[3].replace("\\", "/")))):
                missing = "%s is not in the build" % visual
            else:
                try:
                    found = find_ci(root, final)
                except ValueError:
                    missing = "%s is missing" % final
                else:
                    if game_path_key((load_msg(found)[0].get("body") or {}).get("path", "")) != game_path_key(preset):
                        missing = "%s does not name %s as body.path" % (final, preset)
            if missing:
                break
        key = "%s_%s" % (new_id, description_slug(preset_of_game_path(root, preset).get("description", "")))
        if not missing and key not in keys:
            missing = "the localization line %s is missing in %s" % (key, "/".join(clone_car.LOC_PATH))
        crash = None
        if not missing:
            crash, missing = version_faults(root, new_id, preset, stem, rims, designs, listed_parts)
        if missing:
            raise ValueError("version %s (%s) would %s: %s" % (v["id"], v["name"], "crash the game" if crash else "not show in the game", missing))


def version_faults(root, new_id, preset, stem, rims, designs, listed_parts):
    """The first fault of a version preset (game path preset, its stem stem) beyond those of check_versions' visual presets and
    localization: (True, text) for a rim, a car file or a forced part that would crash the game, (False, text) for a design that would not
    show, (None, None) for none; the part faults come last. rims, designs and listed_parts are the game_path_keys that the actor lists in
    compatible_rims and aftermarket_rims, in car_designs and in aftermarket_parts."""
    obj = preset_of_game_path(root, preset)
    rim = obj.get("compatible_rim")
    if rim and game_path_key(rim) not in rims:
        return True, "compatible_rim %s is not in car.customization.compatible_rims or aftermarket_rims of the actor" % rim
    if rim and not os.path.isfile(kspkg.long_path(tree_path(root, rim.split("\\", 3)[3].replace("\\", "/")))):
        return True, "compatible_rim %s is not in the build" % rim
    visuals = obj.get("visual_preset_paths") or []
    finals = ["presets/%s_%s_%s.carfinalstate" % (new_id, stem, os.path.splitext(visual.rsplit("\\", 1)[-1])[0]) for visual in visuals]
    states = [(final, load_msg(find_ci(root, final))[0]) for final in finals]
    for final, state in states:
        path = (state.get("rims") or {}).get("path")
        if path and game_path_key(path) not in rims:
            return True, "%s: rims.path %s is not in car.customization.compatible_rims or aftermarket_rims of the actor" % (final, path)
    for final, state in states:
        design = (state.get("body") or {}).get("design")
        if design and game_path_key(design) not in {game_path_key(visual) for visual in visuals}:
            return False, "%s: body.design %s is not one of the visual_preset_paths of %s" % (final, design, preset)
    for visual in visuals:
        design = load_msg(tree_path(root, visual.split("\\", 3)[3].replace("\\", "/")))[0].get("car_design_path")
        if design and game_path_key(design) not in designs:
            return False, "%s: car_design_path %s is not in car.customization.car_designs of the actor" % (visual, design)
    folder = game_path_key(game_path_of(new_id, ""))

    def missing(path):
        return game_path_key(path).startswith(folder) and not os.path.isfile(kspkg.long_path(tree_path(root, path.split("\\", 3)[3].replace("\\", "/"))))

    for final, state in states:
        data = state.get("car_data")
        if data and missing(data):
            return True, "%s: car_data %s is not in the build" % (final, data)
    for forced in obj.get("forced_compatible_part_paths") or []:
        if not game_path_key(forced).startswith(folder):
            continue
        if game_path_key(forced) not in listed_parts:
            return True, "%s is not in car.customization.aftermarket_parts of the actor" % forced
        for final, state in states:
            if game_path_key(forced) not in {game_path_key(p.get("path", "")) for p in state.get("parts") or []}:
                return True, "%s: %s is not in its parts" % (final, forced)
        if missing(forced):
            return True, "%s is not in the build" % forced
        car_part = load_msg(tree_path(root, forced.split("\\", 3)[3].replace("\\", "/")))[0].get("car_part_path")
        if not car_part or not game_path_key(car_part).startswith(folder):
            continue
        if missing(car_part):
            return True, "%s (car_part_path of %s) is not in the build" % (car_part, forced)
        for logic in load_msg(tree_path(root, car_part.split("\\", 3)[3].replace("\\", "/")))[0].get("logic_parts") or []:
            tuning = logic.get("tuning_part_path")
            if not tuning or not game_path_key(tuning).startswith(folder):
                continue
            if missing(tuning):
                return True, "%s (tuning_part_path of %s) is not in the build" % (tuning, car_part)
            for text in text_values(load_msg(tree_path(root, tuning.split("\\", 3)[3].replace("\\", "/")))[0]):
                if missing(text):
                    return True, "%s (named by %s) is not in the build" % (text, tuning)
    return None, None


def append_paths(obj, field, paths):
    """Append game paths to a repeated text field of a decoded message (the field is created when the message has none)."""
    container, key = locate(obj, field, create=True)
    set_list(container, key, (container[key] if isinstance(container.get(key), list) else []) + paths)


def compatible_part(part_path):
    """The CompatiblePartData of a car part that sits on the engine bone without any offset (the structure of the Supra MKIV's
    physics parts)."""
    wheel = {"offset": {}, "rotation": {}}
    return {"car_part_path": part_path, "attachment_bone": "ENGINE",
            "attachment_relative_transform": {"position": {}, "rotation": {}, "scale": {"x": 1.0, "y": 1.0, "z": 1.0}},
            "showroom_data": {"offset": {}, "rotation": {}, "wheel_lf": dict(wheel), "wheel_rf": dict(wheel), "wheel_lr": dict(wheel),
                              "wheel_rr": dict(wheel), "animations": {}}}


def forbid_version_parts(root, base_preset, presets, locked, parts):
    """Forbid the compatible parts of the versions in the other mechanical presets: the base mechanical preset (base_preset: its path
    relative to the car folder root) and the preset of every unlocked version (game paths presets in the order of the versions; locked =
    whether each is a locked version; the preset of a locked version is never changed) get every compatible part of the other versions
    (parts = for each version its game paths in the order sound, drivetrain, suspension) that their not_compatible_part_paths does not list
    yet (game_path_key) appended, the versions in order."""
    targets = [(base_preset, None)] + [(preset.split("\\", 3)[3].replace("\\", "/"), i) for i, (preset, is_locked) in enumerate(zip(presets, locked))
                                      if not is_locked]
    for rel, own in targets:
        file = tree_path(root, rel)
        obj, kind = load_msg(file)
        known = {game_path_key(p) for p in obj.get("not_compatible_part_paths") or []}
        forbidden = []
        for i, paths in enumerate(parts):
            for path in paths if i != own else ():
                if game_path_key(path) not in known:
                    known.add(game_path_key(path))
                    forbidden.append(path)
        if forbidden:
            append_paths(obj, "not_compatible_part_paths", forbidden)
            save_msg(file, kind, obj)


def check_forced_parts(root, base_preset, version):
    """Refuse a version when the base mechanical preset (base_preset: its path relative to the car folder root) already forces a compatible
    part whose car part has one of the part types of the version's own car parts (VERSION_PARTS): the game takes one forced part per type."""
    types = {part_type for _, part_type, _ in VERSION_PARTS}
    for forced in load_msg(tree_path(root, base_preset))[0].get("forced_compatible_part_paths") or []:
        compatible = tree_path(root, forced.split("\\", 3)[3].replace("\\", "/"))
        if not os.path.isfile(kspkg.long_path(compatible)):
            continue
        car_part = load_msg(compatible)[0].get("car_part_path")
        car_part = tree_path(root, car_part.split("\\", 3)[3].replace("\\", "/")) if car_part else None
        if car_part and os.path.isfile(kspkg.long_path(car_part)):
            part_type = load_msg(car_part)[0].get("part_type")
            if part_type in types:
                raise ValueError("version %s: the preset of the car already forces a %s part (%s)" % (version, part_type, forced))


def version_tunings(car, copies):
    """The tuning parts of a version (TUNING_SPECS) as {key: decoded TuningPart}: the decoded car file car names the files in its fields; a
    tuning is there when all its fields are non-empty texts and all the files they name are among the copies ({game_path_key of a file: game
    path of its copy}); it names the copies."""
    tunings = {}
    for key, folder, fields, member, names, part_type in TUNING_SPECS:
        source = car.get(folder) if folder else car
        values = [source.get(f) if isinstance(source, dict) else None for f in fields]
        if all(isinstance(v, str) and v and game_path_key(v) in copies for v in values):
            tuning = {member: {n: copies[game_path_key(v)] for n, v in zip(names, values)}}
            if part_type:
                tuning["car_part_type"] = part_type
            tunings[key] = tuning
    return tunings


def part_guid(link, rel):
    """The guid text of a carfinalstate's livery_linker (a message with the 64-bit fields a and b; a missing field is 0): the UUID with
    the number b. An a other than 0 or a b that is no 64-bit number cannot be derived (ValueError naming the file rel)."""
    a, b = link.get("a", 0), link.get("b", 0)
    if a != 0 or type(b) is not int or not 0 <= b < 1 << 64:
        raise ValueError("%s: cannot derive the part guid" % rel)
    return str(uuid.UUID(int=b))


def add_version_physics(part, vpart, new_id, version, name, preset, copies, finals):
    """Give the version its physics and sounds as car parts, which the game takes from the base's car file otherwise (it saves a painted
    version with the base's data/CarData.car plus the parts of the version's carfinalstate, like the Supra MKIV Drift). From the car file of
    the version build vpart the tuning parts data/parts/<new id>_<version>_<key>.tuningpart (version_tunings: engine, drivetrain, gearbox,
    clutch, geometry, coilovers, brakes, setuplimits, setup; copies = {game_path_key: game path of the copy} of the files the merge
    copied) go into the car parts presets/parts/physics/<new id>_<version>_<kind>.carpart (VERSION_PARTS: sound, drivetrain, suspension; each
    written when it has a tuning; description and note "<version name> <kind>", brand of the base mechanical preset), each with its
    .compatiblepart (bone ENGINE for the sound part only). The audio entries of the actor of the version build that differ from those of the
    base build part (same slot and place, or no such entry there) become the car_audio_events of the sound part's logic part; a version with
    such entries but no engine tuning is an error. The compatible parts are appended in the order sound, drivetrain, suspension to the
    forced_compatible_part_paths of the version's preset (game path preset), and to the parts of each carfinalstate copy of the version
    (finals: their paths relative to the car folder) as {path, guid, pguid, type} entries in the order drivetrain, suspension, sound after
    its existing ones (guid and pguid from the livery_linker of that carfinalstate, part_guid). Returns (game paths of the compatible parts
    in the order sound, drivetrain, suspension, number of files written, notes, their paths relative to the car folder); listing them in
    the aftermarket_parts of the actor and forbidding them in the other presets is the caller's (add_version_parts, forbid_version_parts)."""
    root, vroot = car_root_of(part, new_id), car_root_of(vpart, new_id)
    actor = new_id + ".actor"
    base_actor, version_actor = load_msg(find_ci(root, actor))[0], load_msg(find_ci(vroot, actor))[0]
    events, changed = [], []
    for slot in sounds.SLOTS:
        own = [e for _, e in sounds.slot_entries(base_actor, slot)]
        found = [e for i, (_, e) in enumerate(sounds.slot_entries(version_actor, slot)) if i >= len(own) or e != own[i]]
        events += [copy.deepcopy(e) for e in found]
        changed += ["%s=%s" % (slot, short_event(sounds.option_of(e)["key"])) for e in found[:1]]
    base_preset = resolve_file("@mech_preset", vpart, new_id, {})
    version_preset = preset.split("\\", 3)[3].replace("\\", "/")
    brand = load_msg(tree_path(root, base_preset))[0].get("brand")
    car = load_msg(tree_path(vroot, resolve_file("@car", vpart, new_id, {})))[0]
    tunings = version_tunings(car, copies)
    if events and "engine" not in tunings:
        raise ValueError("the car file of version %s has no engine_path to name the tuning part after" % version)
    stem = "%s_%s" % (new_id, version)
    tuning_rels = {key: "data/parts/%s_%s.tuningpart" % (stem, key) for key in tunings}
    written = [(kind, part_type, [k for k in keys if k in tunings]) for kind, part_type, keys in VERSION_PARTS if any(k in tunings for k in keys)]
    rels = {kind: ("presets/parts/physics/%s_%s.carpart" % (stem, kind), "presets/parts/physics/%s_%s.compatiblepart" % (stem, kind))
            for kind, _, _ in written}
    paths = {kind: game_path_of(new_id, rel[1]) for kind, rel in rels.items()}
    edits = []
    for rel in finals if written else ():
        state, kind = load_msg(tree_path(root, rel))
        link = state.get("livery_linker") or {}
        guid = part_guid(link, rel)
        order = [w for w in written if w[0] != "sound"] + [w for w in written if w[0] == "sound"]
        edits.append((rel, state, kind, [{"path": paths[k], "guid": guid, "pguid": copy.deepcopy(link), "type": t} for k, t, _ in order]))
    files = list(tuning_rels.values()) + [r for pair in rels.values() for r in pair]
    for rel in files:
        if os.path.exists(kspkg.long_path(tree_path(root, rel))):
            raise ValueError("cannot write %s: the name is taken" % rel)
    for rel in files:
        os.makedirs(kspkg.long_path(os.path.dirname(tree_path(root, rel))), exist_ok=True)
    for key, rel in tuning_rels.items():
        save_msg(tree_path(root, rel), "TuningPart", tunings[key])
    for kind, part_type, keys in written:
        car_part = {"description": "%s %s" % (name, kind), "part_type": part_type, "note": "%s %s" % (name, kind)}
        if brand:
            car_part["brand"] = brand
        logic = [{"tuning_part_path": game_path_of(new_id, tuning_rels[k])} for k in keys]
        if kind == "sound" and events:
            logic[0]["car_audio_events"] = events
        car_part.update({"no_specialization": {}, "logic_parts": logic})
        save_msg(tree_path(root, rels[kind][0]), "CarPartData", car_part)
        compatible = compatible_part(game_path_of(new_id, rels[kind][0]))
        if kind != "sound":
            del compatible["attachment_bone"]
        save_msg(tree_path(root, rels[kind][1]), "CompatiblePartData", compatible)
    for rel, state, kind, entries in edits:
        set_list(state, "parts", list(state.get("parts") or []) + entries)
        save_msg(tree_path(root, rel), kind, state)
    compatibles = [paths[kind] for kind, _, _ in written]
    if compatibles:
        path = tree_path(root, version_preset)
        obj, kind = load_msg(path)
        append_paths(obj, "forced_compatible_part_paths", compatibles)
        save_msg(path, kind, obj)
    return compatibles, len(files), ["note: version %s (%s): own sounds %s" % (version, name, ", ".join(changed))] if events else [], sorted(files)


def add_version_parts(part, new_id, parts):
    """Append the game paths of the compatible parts of the versions to the aftermarket parts of the actor of the build."""
    path = find_ci(car_root_of(part, new_id), new_id + ".actor")
    actor, name = load_msg(path)
    append_paths(actor, "car.customization.aftermarket_parts", parts)
    save_msg(path, name, actor)


def pack_build(work, new_id, part, out_dir):
    """Pack the .partial folder and put it in place of the previous build. Returns the path of the package."""
    quietly(kspkg.cmd_pack, part, os.path.join(part, new_id + ".kspkg"))
    if os.path.exists(kspkg.long_path(out_dir)):
        remove_tree(work, out_dir)
    os.rename(kspkg.long_path(part), kspkg.long_path(out_dir))
    return os.path.join(out_dir, new_id + ".kspkg")


def install_package(work, pkg, mods):
    """Install the package into the mods folder with a backup of the previous one. Returns (backup, installed path)."""
    backup = quietly(clone_car.install, pkg, mods, os.path.join(work, "backups"))
    return backup, os.path.join(mods, os.path.basename(pkg))


def snapshot_path(work, car_id, new_id):
    return os.path.join(car_work(work, car_id), SNAPSHOT_DIR, new_id + ".json")


def tyre_record(garage):
    """The tyre choice of a tyre_plan as the build record keeps it: {fronts, rears (tyre keys), start_front, start_rear, labels}."""
    return {"fronts": list(garage["fronts"]), "rears": list(garage["rears"]), "start_front": garage["start_front"],
            "start_rear": garage["start_rear"], "labels": dict(garage["labels"])}


def make_snapshot(work, plan, applied, name):
    """The record of a build that the next build of the same modded car is compared with: the changed settings (id -> value), the
    turbo kit (donor, its label, kind and boost), the tyre choice (garage: fronts, rears, start_front, start_rear and labels, see tyre_record), the sound slots that
    differ from the car's own and the game name; kit_info and the plan carry no label or boost, so the donor's come from turbo_donor."""
    kit, garage = plan["kit"], plan["garage"]
    donor = turbo_donor(work, kit["donor"], index_names(work)) if kit else None
    return {"version": SNAPSHOT_VERSION,
            "settings": {a["id"]: plain(a["new"]) for a in applied},
            "kit": {"donor": kit["donor"], "label": donor["label"] if donor else kit["donor"], "kind": kit["kind"],
                    "boost": donor["boost"] if donor else []} if kit else None,
            "garage": tyre_record(garage) if garage else None,
            "sounds": {step["slot"]: step["option"]["key"] for step in plan["sounds"]},
            "name": name, "time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def valid_snapshot(data):
    if not (isinstance(data, dict) and type(data.get("version")) is int and data["version"] == SNAPSHOT_VERSION
            and "kit" in data and "garage" in data and isinstance(data.get("settings"), dict)
            and all(isinstance(k, str) and (isinstance(v, (bool, int, str)) or finite_number(v)) for k, v in data["settings"].items())
            and isinstance(data.get("name"), str) and isinstance(data.get("time"), str)):
        return False
    kit, garage, slots = data.get("kit"), data.get("garage"), data.get("sounds")
    return ((kit is None or (isinstance(kit, dict) and all(isinstance(kit.get(k), str) for k in ("donor", "label", "kind"))
                             and isinstance(kit.get("boost"), list) and all(finite_number(b) for b in kit["boost"])))
            and (garage is None or valid_tyre_record(garage))
            and isinstance(slots, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in slots.items()))


def valid_tyre_record(record):
    """Whether record has the form of tyre_record (a record of the old form, {keys, start}, has not)."""
    return (isinstance(record, dict) and set(record) == {"fronts", "rears", "start_front", "start_rear", "labels"}
            and all(isinstance(record[k], list) and record[k] and all(isinstance(t, str) for t in record[k]) for k in ("fronts", "rears"))
            and isinstance(record["labels"], dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in record["labels"].items())
            and all(isinstance(record[k], str) and record[k] in record[axle] and all(t in record["labels"] for t in record[axle])
                    for k, axle in (("start_front", "fronts"), ("start_rear", "rears"))))


def read_snapshot(path):
    """The record in the file path, None when it is missing, unreadable, damaged or of another version."""
    try:
        data = read_json(kspkg.long_path(path))
    except (ValueError, OSError):
        return None
    return data if valid_snapshot(data) else None


def load_snapshot(work, car_id, new_id):
    """The record of the last build of the modded car new_id, None when it is missing, unreadable, damaged or of another version."""
    return read_snapshot(snapshot_path(work, car_id, new_id))


def save_snapshot(work, car_id, new_id, snapshot):
    save_json(kspkg.long_path(snapshot_path(work, car_id, new_id)), snapshot)


def version_snapshot_path(work, car_id, new_id, version):
    return os.path.join(version_dir(work, car_id, new_id, version), "snapshot.json")


def store_version_build(work, car_id, new_id, version, out_dir, built, snapshot):
    """Keep the build of a version: the record <version folder>/snapshot.json, and in <version folder>/build the files the merge put
    into the packed build out_dir for the version (files/<path relative to the car folder>, byte copies) with build.json = {tune,
    preset, parts, files, time, state}. The new folder is written as build.partial first and then replaces build."""
    folder = version_dir(work, car_id, new_id, version)
    part, final = os.path.join(folder, "build.partial"), os.path.join(folder, "build")
    root = car_root_of(out_dir, new_id)
    if os.path.exists(kspkg.long_path(part)):
        remove_tree(work, part)
    for rel in built["files"]:
        dst = os.path.join(part, "files", *rel.split("/"))
        os.makedirs(kspkg.long_path(os.path.dirname(dst)), exist_ok=True)
        shutil.copyfile(kspkg.long_path(tree_path(root, rel)), kspkg.long_path(dst))
    save_json(kspkg.long_path(os.path.join(part, "build.json")),
              {"tune": new_id, "preset": built["preset"], "parts": built["parts"], "files": built["files"],
               "time": snapshot["time"], "state": built["state"]})
    if os.path.exists(kspkg.long_path(final)):
        remove_tree(work, final)
    os.rename(kspkg.long_path(part), kspkg.long_path(final))
    save_json(kspkg.long_path(version_snapshot_path(work, car_id, new_id, version)), snapshot)


def same_setting(s, a, b):
    """same() for values read from a snapshot: a float setting whose value is not a finite number there is only equal to itself."""
    if s["type"] == "float" and not (finite_number(a) and finite_number(b)):
        return a == b
    return same(s, a, b)


def ignored_shared_notes(versions, version_states, cat, rows):
    """One note per unlocked version (version_states: its own state, None for a locked one) and shared setting (not meta) whose own saved value differs from the effective value of the base (rows: the base's effective_rows): the version ignores it."""
    notes = []
    for v, state in zip(versions, version_states):
        for s, row in zip(cat["settings"], rows):
            if state is not None and s.get("shared") is True and s["kind"] != "meta" and s["id"] in state:
                own = saved_value(s, state[s["id"]])
                if not same_setting(s, own, row["value"]):
                    notes.append("note: version %s (%s): its own %s %s is ignored (shared by all versions, %s)" % (v["id"], v["name"], s["id"], fmt(own), fmt(row["value"])))
    return notes


def kit_text(kit):
    """A turbo kit as the people read it: <label> (<kind>, <boost> bar), None for no kit."""
    if kit is None:
        return None
    return "%s (%s%s)" % (kit["label"], kit["kind"], ", %s bar" % "/".join(fmt(b) for b in kit["boost"]) if kit["boost"] else "")


def short_event(key):
    """The last part of the event path of a sound option key, "own sound" for the car's own sound."""
    return "own sound" if key is None else key.replace("\\", "/").rsplit("/", 1)[-1]


def garage_text(before, after):
    """The sentence of a changed tyre choice: the tyres of the front and the rear and the tyres the car starts on."""
    if after is None:
        return "Tyres: the car's own tyres again (were %s)" % choice_text(before)
    return "Tyres: " + choice_text(after)


def build_extras(previous, current):
    """The changes of the turbo kit, the garage selection and the sound slots between two records (previous None: nothing before)."""
    before = previous or {"kit": None, "garage": None, "sounds": {}}
    extras = []
    if (before["kit"] or {}).get("donor") != (current["kit"] or {}).get("donor"):
        old, new = kit_text(before["kit"]), kit_text(current["kit"])
        extras.append({"kind": "turbo_kit", "from": old, "to": new, "text": "Turbo kit: %s -> %s" % (old or "none", new or "none")})
    if before["garage"] != current["garage"]:
        old, new = [choice_text(g) if g else None for g in (before["garage"], current["garage"])]
        extras.append({"kind": "garage", "from": old, "to": new, "text": garage_text(before["garage"], current["garage"])})
    for slot in sounds.SLOTS:
        old, new = before["sounds"].get(slot), current["sounds"].get(slot)
        if old != new:
            extras.append({"kind": "sound", "slot": slot, "from": old, "to": new,
                           "text": "Sound %s: %s -> %s" % (slot, short_event(old), short_event(new))})
    return extras


def build_changes(previous, current, cat, rows):
    """What a build changed compared with the previous build of the same modded car: {since ("last build", None without a previous
    record), settings ([{id, from, to}] in catalogue order: every setting whose value differs from the previous record, a setting
    that is not changed any more goes back to its stock default; without a previous record every changed setting from its stock
    default), extras (build_extras), total (the settings that differ from the stock car)}. previous and current are records (see
    make_snapshot), rows the rows of the build (the stock default of each setting). Reads nothing."""
    defaults = {r["id"]: plain(r["default"]) for r in rows}
    old_values = previous["settings"] if previous else {}
    new_values = current["settings"]
    settings = []
    for s in cat["settings"]:
        i = s["id"]
        if i in old_values or i in new_values:
            was, now = old_values.get(i, defaults[i]), new_values.get(i, defaults[i])
            if not same_setting(s, was, now):
                settings.append({"id": i, "from": was, "to": now})
    return {"since": "last build" if previous else None, "settings": settings, "extras": build_extras(previous, current),
            "total": len(new_values)}


def changes_lines(changes, subject, last, indent):
    """The lines of one build's changes: the count line (first build of <subject>, or since <last> build), then one line per changed
    setting and one per extra, each starting with indent."""
    count = len(changes["settings"]) + len(changes["extras"])
    total = "%d changed settings compared to the stock car" % changes["total"]
    if changes["since"] is None:
        lines = ["first build of %s: %s" % (subject, total)]
    elif count:
        lines = ["%d change(s) since %s build (%s in total)" % (count, last, total)]
    else:
        lines = ["no change since %s build (%s in total)" % (last, total)]
    lines += ["%s%s: %s -> %s" % (indent, c["id"], fmt(c["from"]), fmt(c["to"])) for c in changes["settings"]]
    lines += [indent + e["text"] for e in changes["extras"]]
    return lines


def change_lines(res):
    """The lines that tell what an apply result changed (res["changes"]), then those of each version with a record of its changes, then
    its notes: the count, one line per changed setting and one per extra (turbo kit, garage tyres, sound); a version's block starts
    with "version <id> (<name>): " before its count line and indents the other lines."""
    lines = changes_lines(res["changes"], "this car", "the last", "  ")
    for v in res.get("versions", []):
        if v.get("locked"):
            lines.append("version %s (%s): locked, not rebuilt (kept from its build of %s)" % (v["id"], v["name"], v["built"]))
        elif "changes" in v:
            block = changes_lines(v["changes"], "this version", "its last", "    ")
            lines += ["version %s (%s): %s" % (v["id"], v["name"], block[0])] + block[1:]
    return lines + res["notes"]


def build_state(work, car_id, new_id, out_dir, plan, cat, game):
    """The build steps of one state, the base of a tune or one of its versions (the plan decides which): clone, edits, tyres, sounds and the
    car file name, into <out_dir>.partial. Returns (folder, meta values, notes, applied list, changed sound slots)."""
    part, meta, notes = build_partial(work, car_id, new_id, out_dir, plan, cat, game)
    if plan["kit"]:
        notes += kit_notes(plan["kit"])
    car_root = car_root_of(part, new_id)
    edits, tyre_edits, applied = collect_edits(car_id, new_id, plan["changed"], part, car_root)
    if plan["garage"]:
        start_tyre_edits(plan["garage"], car_id, new_id, edits)
    write_edits(car_root, edits)
    notes += write_tyres(plan["root"], car_id, new_id, car_root, plan["garage"], tyre_edits)
    changed_sounds = write_sounds(car_root, new_id, plan["sounds"])
    notes += sound_notes(changed_sounds)
    notes += rename_car_file(part, new_id, applied)
    return part, meta, notes, applied, changed_sounds


def put_locked_version(work, car_id, new_id, root, version, kept):
    """Put the kept build of a locked version (kept_build) into the car folder root of the build: every file of its build/files under
    the same path (a file of that name that exists is an error, found before anything is copied). Returns the number of files."""
    source = os.path.join(version_dir(work, car_id, new_id, version), "build", "files")
    for rel in kept["files"]:
        if os.path.exists(kspkg.long_path(tree_path(root, rel))):
            raise ValueError("cannot copy %s of version %s: the name is taken" % (rel, version))
    for rel in kept["files"]:
        dst = tree_path(root, rel)
        os.makedirs(kspkg.long_path(os.path.dirname(dst)), exist_ok=True)
        shutil.copyfile(kspkg.long_path(os.path.join(source, *rel.split("/"))), kspkg.long_path(dst))
    return len(kept["files"])


def build_versions(work, car_id, new_id, part, versions, plans, kept, cat, game):
    """Build each unlocked version of the tune (plans from apply_plan, None for a locked version) into its own temporary folder next to
    the build, merge it into the base build in part (merge_version), then put in the kept build (kept, from kept_build, None for an
    unlocked version) of each locked version (put_locked_version), and list the version presets in the actor in the order of the
    versions. A version gets its physics and sounds as car parts of its own (add_version_physics), listed in the aftermarket parts of the
    actor (so do the parts of a locked version, in the order of the versions) and forbidden in the base preset and the presets of the
    unlocked versions (forbid_version_parts); a base preset that forces a part of the same types is refused (check_forced_parts). The visual presets and car designs of the version presets are
    added to the actor's lists (add_version_visuals), the rims of the version presets that the actor does not list are added to its
    car.customization.aftermarket_rims and forbidden in the other mechanical presets (add_version_rims: the base preset, resolved before the
    merges, and the unlocked versions' presets; a locked version's preset stays as kept) and each version gets its line in en.cars.loc
    (add_version_names); the description of an
    unlocked version's preset is made unique by its slug (merge_version) against the base's and the other versions' (the slugs of the locked
    ones are read from their kept presets). Returns ([{id, name, files, locked, built}], notes
    (by version), [{files (the paths written into the car folder for the version, sorted), preset (game path), parts (the game paths
    of its compatible parts: sound, drivetrain, suspension), applied (None for a locked version)}] in the order of the versions)."""
    root = car_root_of(part, new_id)
    base_preset = resolve_file("@mech_preset", part, new_id, {}) if versions else None
    merged, notes, built = [None] * len(versions), [None] * len(versions), [None] * len(versions)
    taken = {description_slug(preset_of_game_path(root, game_path_of(new_id, resolve_file("@mech_preset", part, new_id, {}))).get("description", ""))
             } if versions else set()
    for v, k in zip(versions, kept):
        if k is not None:
            kept_preset = os.path.join(version_dir(work, car_id, new_id, v["id"]), "build", "files", *k["preset"].split("\\", 3)[3].split("\\"))
            taken.add(description_slug(load_msg(kept_preset)[0].get("description", "")))
    for i, (v, plan) in enumerate(zip(versions, plans)):
        if plan is None:
            continue
        check_forced_parts(root, base_preset, v["id"])
        vout = os.path.join(build_dir(work, car_id), "%s_%s" % (new_id, v["id"]))
        try:
            vpart, applied = build_state(work, car_id, new_id, vout, plan, cat, game)[::3]
            count, preset, more, files, copies, finals = merge_version(part, vpart, new_id, v["id"], v["name"], taken)
            taken.add(description_slug(preset_of_game_path(root, preset).get("description", "")))
            compatibles, written, own_notes, part_files = add_version_physics(part, vpart, new_id, v["id"], v["name"], preset, copies, finals)
            count += written
            files = files + part_files
        finally:
            if os.path.exists(kspkg.long_path(vout + ".partial")):
                remove_tree(work, vout + ".partial")
        merged[i] = {"id": v["id"], "name": v["name"], "files": count, "locked": False}
        built[i] = {"files": sorted(files), "preset": preset, "parts": compatibles, "applied": applied}
        notes[i] = ["note: version %s (%s): %d files of its own" % (v["id"], v["name"], count)] + more + own_notes
    for i, (v, k) in enumerate(zip(versions, kept)):
        if k is None:
            continue
        count = put_locked_version(work, car_id, new_id, root, v["id"], k)
        merged[i] = {"id": v["id"], "name": v["name"], "files": count, "locked": True, "built": k["time"]}
        built[i] = {"files": k["files"], "preset": k["preset"], "parts": k["parts"], "applied": None}
        notes[i] = ["note: version %s (%s): locked, %d files kept from its build of %s" % (v["id"], v["name"], count, k["time"])]
    if built:
        add_version_presets(part, new_id, [b["preset"] for b in built])
        add_version_visuals(part, new_id, [b["preset"] for b in built])
        add_version_rims(part, new_id, base_preset, [b["preset"] for b in built], [k is not None for k in kept])
        add_version_names(part, new_id, [(v["name"], b["preset"]) for v, b in zip(versions, built)])
        forbid_version_parts(root, base_preset, [b["preset"] for b in built], [k is not None for k in kept], [b["parts"] for b in built])
    parts = [p for b in built for p in b["parts"]]
    if parts:
        add_version_parts(part, new_id, parts)
    return merged, [n for each in notes for n in each], built


def apply(work, car_id, new_id=None, install=True, mods_dir=None, catalogue=None, game=DEFAULT_GAME):
    """Build the modded car new_id (default: the default tune) of a stock car from its saved state and, with install, install the package. Each unlocked version of the tune is built too and merged into the package as a further mechanical preset (see build_versions); a locked version (lock_version) is not built: the files of its kept build (kept_build) are copied into the package byte for byte, its preset and parts listed as for a built one, and its build/ and snapshot.json stay as they are; a locked version whose kept build is missing or damaged is an error before anything is written. The snapshot is the base's. A version that the game would not show (check_versions) stops the apply before the pack. Returns {new_id, tune, name_suffix, build_dir, package, size, applied, notes, sounds, changes, versions, installed, backup}. A state (the base, or an unlocked version with its name in front) that holds saved values of the old Tyres section and no tyre choice adds the note "this car still has saved tyre values of the old Tyres section (N): convert them with tyres-convert" once; they are built as before. Raises ValueError before anything is written when the state cannot be applied (see apply_plan); a failed build keeps the previous one."""
    cat = catalogue or load_catalogue()
    new_id = new_id or new_id_for(car_id)
    plan = apply_plan(work, car_id, new_id, install, mods_dir, cat, game=game)
    versions = list_versions(work, car_id, new_id)
    kept = [kept_build(work, car_id, v["id"], new_id) if v["locked"] else None for v in versions]
    for v, k in zip(versions, kept):
        if v["locked"] and k is None:
            raise ValueError("version %s (%s) is locked but its kept build is missing or damaged; unlock it" % (v["id"], v["name"]))
    version_plans = [None if v["locked"] else apply_plan(work, car_id, new_id, False, None, cat, v["id"], game) for v in versions]
    version_states = [None if v["locked"] else read_version_state(work, car_id, v["id"], new_id) for v in versions]
    out_dir = os.path.join(build_dir(work, car_id), new_id)
    part, meta, notes, applied, changed_sounds = build_state(work, car_id, new_id, out_dir, plan, cat, game)
    merged, more, built = build_versions(work, car_id, new_id, part, versions, version_plans, kept, cat, game)
    notes += old_tyre_notes(load_state(work, car_id, new_id), cat) + more + ignored_shared_notes(versions, version_states, cat, plan["rows"])
    notes += [n for v, st in zip(versions, version_states) if st is not None for n in old_tyre_notes(st, cat, "version %s (%s): " % (v["id"], v["name"]))]
    check_versions(part, new_id, versions, [b["preset"] for b in built])
    pkg = pack_build(work, new_id, part, out_dir)
    records = []
    for v, vplan, vstate, b, entry in zip(versions, version_plans, version_states, built, merged):
        if vplan is None:
            continue
        record = make_snapshot(work, vplan, b["applied"], plan_name(car_id, vplan, meta["name_suffix"]))
        entry["changes"] = record["changes"] = build_changes(read_snapshot(version_snapshot_path(work, car_id, new_id, v["id"])), record, cat, vplan["rows"])
        records.append((v["id"], dict(b, state=vstate), record))
    snapshot = make_snapshot(work, plan, applied, plan_name(car_id, plan, meta["name_suffix"]))
    changes = build_changes(load_snapshot(work, car_id, new_id), snapshot, cat, plan["rows"])
    snapshot["changes"] = changes
    save_snapshot(work, car_id, new_id, snapshot)
    for version, b, record in records:
        store_version_build(work, car_id, new_id, version, out_dir, b, record)
    result = {"new_id": new_id, "tune": new_id, "name_suffix": meta["name_suffix"], "build_dir": out_dir, "package": pkg, "size": os.path.getsize(pkg),
              "applied": applied, "notes": notes, "sounds": changed_sounds, "changes": changes, "versions": merged, "installed": None, "backup": None}
    if install:
        result["backup"], result["installed"] = install_package(work, pkg, plan["mods"])
    return result


def index_names(work, game=""):
    """{car id: display name} of the cached car index (empty without it); game "" never reads the game package."""
    return {c["id"]: c["display_name"] for c in load_cars_index(work, game) or []}


def stock_car_name(work, car_id, names, labels=None):
    """Name of a stock car: stock_info.json, else the car index, else the tested label, else the id."""
    try:
        info = load_stock_info(work, car_id)
    except (ValueError, OSError):
        info = None
    return info["display_name"] if info else names.get(car_id) or (labels or {}).get(car_id) or car_id


def list_cars(work, mods_dir=None, tested_only=False, game=DEFAULT_GAME, sizes=True):
    """Every car of the game (the tested cars only when the car index is not available or tested_only), sorted by
    display name. sizes=False leaves bytes None without walking the car folders."""
    cars = load_cars()
    mods = clone_car.expand_dir(mods_dir, clone_car.DEFAULT_MODS, "mods directory", "--mods")
    labels = {c["id"]: c["label"] for c in cars["cars"]}
    names = index_names(work, game)
    rows = []
    for car_id in labels if tested_only else list(dict.fromkeys(list(labels) + list(names))):
        car_root = car_root_of(base_dir(work, car_id), car_id)
        extracted = os.path.isdir(kspkg.long_path(car_root)) and bool(os.listdir(kspkg.long_path(car_root)))
        try:
            info = load_stock_info(work, car_id) if extracted else None
        except ValueError:
            info = None
        display_name = info["display_name"] if info else names.get(car_id) or labels.get(car_id) or car_id
        new_id = new_id_for(car_id)
        rows.append({"id": car_id, "default": car_id == cars["default"], "label": labels.get(car_id, display_name),
                     "display_name": display_name, "extracted": extracted, "tested": car_id in labels,
                     "new_id": new_id, "installed": os.path.isfile(os.path.join(mods, new_id + ".kspkg")),
                     "bytes": count_tree(car_root)["bytes"] if extracted and sizes else None})
    return sorted(rows, key=lambda r: (r["display_name"].lower(), r["id"]))


def name_suffix_setting(catalogue=None):
    for s in (catalogue or load_catalogue())["settings"]:
        if s.get("handler") == "name_suffix":
            return s
    raise ValueError("the catalogue has no name_suffix setting")


def car_name(stock_name, suffix):
    """The name of a modded car in the game: the stock display name, one space, the (already trimmed) name suffix."""
    return stock_name + " " + suffix


def legacy_suffix(v):
    """A name suffix saved by the old version (underscore, MY, optional number) as it reads now: MY, MY <n>. Any other value is returned as it is."""
    m = LEGACY_SUFFIX.fullmatch(v) if isinstance(v, str) else None
    return v if m is None else "MY" + (" " + m.group(1) if m.group(1) else "")


def saved_value(s, v):
    """The value of setting s as the saved state v reads: legacy name suffixes converted, then checked and normalised by coerce."""
    return coerce(s, legacy_suffix(v) if s.get("handler") == "name_suffix" else v)


def state_suffix(state, s):
    return saved_value(s, state[s["id"]]) if s["id"] in state else s["default"]


def is_tune_id(work, car_id, name):
    try:
        check_tune_id(work, car_id, name)
    except ValueError:
        return False
    return name != DRAFT


def tunes_of(work, car_id, s):
    """The tunes of a stock car for the name suffix setting s, default tune first, then by id. The default tune is
    listed when its state file or its build folder exists, every other tune when tunes/<id>/tune_state.json exists."""
    default = new_id_for(car_id)
    found = []
    has_state = os.path.isfile(kspkg.long_path(state_path(work, car_id)))
    if has_state or os.path.isdir(kspkg.long_path(os.path.join(build_dir(work, car_id), default))):
        found.append((default, has_state))
    folder = os.path.join(car_work(work, car_id), TUNES)
    for name in sorted(os.listdir(kspkg.long_path(folder))) if os.path.isdir(kspkg.long_path(folder)) else []:
        if name != default and is_tune_id(work, car_id, name) and os.path.isfile(kspkg.long_path(state_path(work, car_id, name))):
            found.append((name, True))
    return sorted(({"id": i, "stock": car_id, "default": i == default, "name_suffix": state_suffix(load_state(work, car_id, i), s),
                    "has_state": h} for i, h in found), key=lambda t: (not t["default"], t["id"]))


def list_tunes(work, car_id):
    """The modded cars (tuned copies) of a stock car: {id, stock, default, name_suffix, has_state}, default tune first,
    then by id. name_suffix is the suffix in the saved state, the catalogue default when the state has none."""
    return tunes_of(work, car_id, name_suffix_setting())


def car_folders(work):
    """Ids of the stock cars that have a folder in the work folder (a base, a build, a state, a draft or tunes), sorted."""
    if not os.path.isdir(kspkg.long_path(work)):
        return []
    return sorted(n for n in os.listdir(kspkg.long_path(work)) if re.fullmatch(r"[a-z0-9_]+", n)
                  and any(os.path.exists(kspkg.long_path(os.path.join(work, n, x)))
                          for x in ("base", "build", "tune_state.json", "draft_state.json", TUNES)))


def known_tune_ids(work, mods_dir=None):
    """Every tuned-car id that must not be reused: the default tune id of each tested car, each car of the cached car
    index and each car folder of the work folder, every tune folder below <work>/*/tunes and, when mods_dir is given,
    every <id>.kspkg in it. Offline: the car index is read from its cache only."""
    # "" is never a file, so load_cars_index never reads the game package
    cars = {c["id"] for c in load_cars()["cars"]} | {c["id"] for c in load_cars_index(work, "") or []} | set(car_folders(work))
    known = {new_id_for(c) for c in cars}
    for car_id in car_folders(work):
        folder = os.path.join(car_work(work, car_id), TUNES)
        if os.path.isdir(kspkg.long_path(folder)):
            known.update(n for n in os.listdir(kspkg.long_path(folder)) if os.path.isdir(kspkg.long_path(os.path.join(folder, n))))
    if mods_dir is not None:
        mods = clone_car.expand(mods_dir)
        if os.path.isdir(kspkg.long_path(mods)):
            known.update(n[:-len(".kspkg")].lower() for n in os.listdir(kspkg.long_path(mods)) if n.lower().endswith(".kspkg"))
    return known


def free_tune_id(work, car_id, mods_dir=None):
    """The first unused tuned-car id of a stock car: the default id with its last two characters replaced by 01, 02, ...
    99 (same length as the stock id)."""
    base, known = new_id_for(car_id), known_tune_ids(work, mods_dir)
    for n in range(1, 100):
        candidate = base[:-2] + "%02d" % n
        if candidate in known:
            continue
        try:
            check_tune_id(work, car_id, candidate)
        except ValueError:
            continue
        return candidate
    raise ValueError("no free tuned car id left for %s (%s01 .. %s99 are taken or invalid)" % (car_id, base[:-2], base[:-2]))


def suffix_owner(work, car_id, suffix, exclude=None):
    """Id of a tune of the stock car (other than exclude) that uses the name suffix, else None."""
    for t in list_tunes(work, car_id):
        if t["id"] != exclude and t["name_suffix"] == suffix:
            return t["id"]
    return None


def free_suffix(work, car_id, wanted, exclude=None):
    """wanted when no other tune of the stock car uses it, else the number after a space at its end counted up (MY -> MY 2 ->
    MY 3, T 1 -> T 2; leading zeros keep their width; a number without a space is part of the text), the stem cut to stay
    within the length limit of the setting."""
    s = name_suffix_setting()
    wanted = coerce(s, wanted)
    stem, digits = re.fullmatch(r"(.*?)(?: (\d+))?", wanted).groups()
    taken = {t["name_suffix"] for t in tunes_of(work, car_id, s) if t["id"] != exclude}
    candidate, n = wanted, int(digits or 1)
    while candidate in taken:
        n += 1
        number = str(n).zfill(len(digits or ""))
        if len(number) + 2 > NAME_SUFFIX_MAX:
            raise ValueError("no free car name left for %s" % wanted)
        candidate = stem[:NAME_SUFFIX_MAX - len(number) - 1].rstrip() + " " + number
    return candidate


def duplicate_tune(work, car_id, src, new_id=None, suffix=None, mods_dir=None):
    """Copy the saved values of a tune (src: a tune id, None for the default tune, or DRAFT) to a new tune of the stock
    car; returns {id, stock, name_suffix}. new_id None picks free_tune_id; an explicit id must be valid, unused
    (the default id only while the default tune does not exist) and not DRAFT. suffix None keeps the suffix of src
    made unique with free_suffix; an explicit one must not be used by another tune. Nothing is written on an error."""
    s = name_suffix_setting()
    default = new_id_for(car_id)
    if is_extra_tune(car_id, src) and not os.path.isfile(kspkg.long_path(state_path(work, car_id, src))):
        raise ValueError("%s has no tune %s" % (car_id, src))
    state = load_state(work, car_id, src)
    if new_id is None:
        new_id = free_tune_id(work, car_id, mods_dir)
    else:
        check_tune_id(work, car_id, new_id)
        known = known_tune_ids(work, mods_dir)
        if new_id == default:
            if any(t["default"] for t in list_tunes(work, car_id)):
                raise ValueError("%s is already a tune of %s" % (new_id, car_id))
            known.discard(default)
        if new_id == DRAFT or new_id in known:
            raise ValueError("tuned car id %s is already used or reserved" % new_id)
    if suffix is None:
        suffix = free_suffix(work, car_id, state_suffix(state, s))
    else:
        suffix = coerce(s, suffix)
        owner = suffix_owner(work, car_id, suffix)
        if owner:
            raise ValueError("car name already used by %s" % owner)
    state[s["id"]] = suffix
    save_state(work, car_id, state, new_id)
    return {"id": new_id, "stock": car_id, "name_suffix": suffix}


def new_tune_from_draft(work, car_id, suffix=None, new_id=None, mods_dir=None):
    """duplicate_tune(DRAFT) for the Apply of a stock car: new_id None takes the default id while the default tune does
    not exist yet (no state, no build), else free_tune_id."""
    if new_id is None and not any(t["default"] for t in list_tunes(work, car_id)):
        new_id = new_id_for(car_id)
    return duplicate_tune(work, car_id, DRAFT, new_id, suffix, mods_dir)


def list_modded(work, mods_dir=None):
    """Every modded car of every stock car with a work folder: {id, stock, label (car_name: stock display name, space, suffix), name_suffix,
    default, installed (<id>.kspkg in the mods folder), built (build/<id>/<id>.kspkg)}, sorted by label. Stock cars without
    tunes give nothing; a damaged stock_info.json falls back to the cached car index, the tested label or the car id."""
    s = name_suffix_setting()
    mods = clone_car.expand_dir(mods_dir, clone_car.DEFAULT_MODS, "mods directory", "--mods")
    labels = {c["id"]: c["label"] for c in load_cars()["cars"]}
    names = index_names(work)
    rows = []
    for car_id in car_folders(work):
        tunes = tunes_of(work, car_id, s)
        stock_name = stock_car_name(work, car_id, names, labels) if tunes else None
        for t in tunes:
            rows.append({"id": t["id"], "stock": car_id, "label": car_name(stock_name, t["name_suffix"]), "name_suffix": t["name_suffix"],
                         "default": t["default"], "installed": os.path.isfile(os.path.join(mods, t["id"] + ".kspkg")),
                         "built": os.path.isfile(kspkg.long_path(os.path.join(build_dir(work, car_id), t["id"], t["id"] + ".kspkg")))})
    return sorted(rows, key=lambda r: (r["label"].lower(), r["id"]))


def tyres_dir(work):
    return os.path.join(work, TYRES_DIR)


def check_tyre_id(tyre_id):
    if not isinstance(tyre_id, str) or not TYRE_ID.fullmatch(tyre_id):
        raise ValueError("bad tyre id %r: use 1 to %d characters a-z, 0-9 and _" % (tyre_id, TYRE_ID_MAX))


def tyre_path(work, tyre_id):
    check_tyre_id(tyre_id)
    return os.path.join(tyres_dir(work), tyre_id + ".json")


def tyre_exists(work, tyre_id):
    return os.path.isfile(kspkg.long_path(tyre_path(work, tyre_id)))


def free_tyre_id(work, name):
    """An unused library id made from a name: lower case, every run of other characters one _, at most 24 characters,
    "tyre" for an empty result; a taken id gets 2, 3, ... appended (the base cut to keep the id within 24 characters)."""
    base = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:TYRE_ID_MAX] or "tyre"
    candidate, n = base, 1
    while tyre_exists(work, candidate):
        n += 1
        candidate = base[:TYRE_ID_MAX - len(str(n))] + str(n)
    return candidate


def check_tyre_name(work, name, own_id=None):
    """The stripped name when it is 1 to 40 characters without control characters and no other library tyre has it
    (ignoring case)."""
    if not isinstance(name, str):
        raise ValueError("a tyre name must be text, got %r" % (name,))
    name = name.strip()
    if not 1 <= len(name) <= TYRE_NAME_MAX or re.search(r"[\x00-\x1f\x7f]", name):
        raise ValueError("a tyre name needs 1 to %d characters without control characters" % TYRE_NAME_MAX)
    for t in list_tyres(work):
        if t["id"] != own_id and t.get("name", "").lower() == name.lower():
            raise ValueError("a tyre named %r exists already (%s)" % (t["name"], t["id"]))
    return name


def check_tyre_short(short):
    if not isinstance(short, str) or not TYRE_SHORT.fullmatch(short):
        raise ValueError("a tyre short name needs 1 to 3 characters A-Z and 0-9 (upper case, no spaces), got %r" % (short,))
    return short


def default_short(name):
    """The short name made from a tyre name: the first letters of its last two words (one word: its first two letters), upper case,
    only A-Z and 0-9, at most 3 characters, "X" when nothing is left."""
    words = str(name).split()
    text = words[-2][:1] + words[-1][:1] if len(words) > 1 else (words[0][:2] if words else "")
    return re.sub(r"[^A-Z0-9]", "", text.upper())[:3] or "X"


def tyre_settings(catalogue=None):
    """The catalogue settings that write a tyre file (a target with the role @tyre_front or @tyre_rear)."""
    return [s for s in (catalogue or load_catalogue())["settings"] if any(t["file"] in TYRE_FILES for t in s.get("targets", []))]


def tyre_group_list(catalogue=None):
    """The tyre groups of the catalogue in display order, as copies of {"name", "description"}; [] when it has none."""
    return [{"name": g["name"], "description": g["description"]} for g in (catalogue or load_catalogue()).get("tyre_groups", [])]


def tyre_fields(catalogue=None):
    """The fields of a library tyre. First the derived ones: one per setting of the group Tyres whose id ends _front, as a copy of that
    setting with the id without _front, the label without the word front and the targets of @tyre_front as {file "@tyre", path}; front_id
    is the id of the setting; the description says "the tyre" and "its axle" where the setting says "the front tyre" and "the front axle";
    the group is the setting's tyre_group (else its group). The _rear settings are not used. Then the fields of the catalogue's
    tyre_settings (copies; an "absent" field also gets create_missing, so a tyre that does not store it still resolves). With tyre_groups
    all fields are in the order of the groups, the derived ones first in each (stable otherwise)."""
    cat = catalogue or load_catalogue()
    fields = []
    for s in cat["settings"]:
        if s.get("group") != "Tyres" or not s["id"].endswith("_front"):
            continue
        label = re.sub(r"\s+", " ", re.sub(r"(?i)\bfront\b", "", s["label"])).strip()
        description = s["description"].replace("the front tyre", "the tyre").replace("the front axle", "its axle")
        fields.append(dict(s, id=s["id"][:-len("_front")], front_id=s["id"], label=label[:1].upper() + label[1:], description=description,
                           group=s.get("tyre_group", s["group"]), targets=[dict(t, file="@tyre") for t in s["targets"] if t["file"] == "@tyre_front"]))
    for s in cat.get("tyre_settings", []):
        fields.append(dict(s, targets=[dict(t) for t in s["targets"]], **({"create_missing": True} if "absent" in s else {})))
    order = [g["name"] for g in cat.get("tyre_groups", [])]
    return sorted(fields, key=lambda f: order.index(f["group"]) if f["group"] in order else len(order)) if order else fields


def tyre_field(cat, field_id):
    for s in tyre_fields(cat):
        if s["id"] == field_id:
            return s
    find_setting(cat, field_id)
    raise ValueError("%s is not a tyre setting" % field_id)


def compound_texts(pc):
    """The (front, rear) game paths (backslashes) of a physic compound: the rear is the first of rear_tyre_data_paths; None when the
    compound has no text front or rear."""
    front = pc.get("front_tyre_data_path") if isinstance(pc, dict) else None
    rear = pc.get("rear_tyre_data_paths") if isinstance(pc, dict) else None
    if isinstance(rear, list):
        rear = rear[0] if rear else None
    if not (isinstance(front, str) and isinstance(rear, str)):
        return None
    return front.replace("/", "\\"), rear.replace("/", "\\")


def compound_pair(pc):
    """compound_texts as game_path_key; None when the compound has no text front or rear."""
    texts = compound_texts(pc)
    return None if texts is None else (game_path_key(texts[0]), game_path_key(texts[1]))


def preset_tyre_pairs(root, car_id):
    """The (front, rear) game paths (backslashes, as written) of the physic compounds in presets/*.compatibletyres of a car in root,
    each pair once (case ignored): the rear is the first of rear_tyre_data_paths; both must be shared game files present below root."""
    folder = find_ci(car_root_of(root, car_id), "presets")
    pairs, seen = [], set()
    for n in sorted(os.listdir(kspkg.long_path(folder))):
        if not n.lower().endswith(".compatibletyres"):
            continue
        try:
            compounds = load_msg(os.path.join(folder, n))[0].get("physic_compounds", [])
        except (ValueError, OSError):
            continue
        for pc in compounds if isinstance(compounds, list) else []:
            texts = compound_texts(pc)
            if texts is None or compound_pair(pc) in seen:
                continue
            seen.add(compound_pair(pc))
            front, rear = map(game_path_key, texts)
            if (front.startswith(GAME_SHARED) and rear.startswith(GAME_SHARED) and tyre_present(root, front)
                    and tyre_present(root, rear)):
                pairs.append(texts)
    return pairs


def extracted_tyres(work):
    """The tyre entries (tyre_sets.game_index) of the shared tyre files that are extracted: in the base of an extracted car and in
    <work>/tyre_files."""
    found = []
    for root in [base_dir(work, c) for c in car_folders(work)] + [os.path.join(work, "tyre_files")]:
        top = os.path.join(root, "content", "cars", SHARED_DIR, "tyres")
        for dp, _, names in os.walk(kspkg.long_path(top)):
            rel = os.path.relpath(dp, kspkg.long_path(top))
            parts = [] if rel == "." else rel.split(os.sep)
            found += [tyre_sets.SHARED + "\\".join(parts + [n]) for n in names if n.lower().endswith(".tyre")]
    return tyre_sets.game_index(found)


def available_tyres(work, game=DEFAULT_GAME):
    """The tyres a library tyre or a car can use: tyre_sets.read_index of the game package; when the package is not there only the
    extracted tyre files (extracted_tyres)."""
    if os.path.isfile(game):
        return tyre_sets.read_index(game, work)
    return extracted_tyres(work)


def tyre_ranges_path(work):
    return os.path.join(work, TYRE_RANGES_FILE)


def tyre_type_order(types):
    """The tyre types (folders) in the order of tyre_sets.TYPE_ORDER, unknown ones last (otherwise as given)."""
    order = tyre_sets.TYPE_ORDER
    return sorted(types, key=lambda k: order.index(k.lower()) if k.lower() in order else len(order))


def tyre_ranges_key(work, tyres, fields, game):
    """What the cached tyre ranges depend on: the package's [size, mtime_ns] (without a package: the paths of the tyres), the id and
    first target path of every field (an enum also its choices with their texts) and the types of the tyres with their labels."""
    st = os.stat(game) if os.path.isfile(game) else None
    stamp = [st.st_size, st.st_mtime_ns] if st else [t["path"] for t in tyres]
    labels = {t["type"]: t["type_label"] for t in tyres}
    return {"stamp": stamp,
            "fields": [[s["id"], s["targets"][0]["path"]] + ([[[c, s.get("choice_values", {}).get(c)] for c in s["choices"]]] if s["type"] == "enum" else [])
                       for s in fields],
            "type_list": [[k, labels[k]] for k in tyre_type_order(labels)]}


def valid_type_entry(e):
    if not isinstance(e, dict):
        return False
    if "values" in e:
        v = e["values"]
        return (isinstance(v, list) and len(v) > 0 and (all(type(x) is bool for x in v) or all(isinstance(x, str) for x in v))
                and type(e.get("count")) is int and e["count"] >= 0)
    return (finite_number(e.get("low")) and finite_number(e.get("high")) and e["low"] <= e["high"] and type(e.get("count")) is int
            and e["count"] >= 1)


def valid_tyre_ranges(data, key):
    if not (isinstance(data, dict) and data.get("version") == TYRE_RANGES_VERSION and data.get("stamp") == key["stamp"]
            and data.get("fields") == key["fields"] and data.get("type_list") == key["type_list"] and type(data.get("total")) is int):
        return False
    types, by_type = data.get("types"), data.get("by_type")
    if not (isinstance(types, list) and isinstance(by_type, dict)
            and all(isinstance(t, dict) and isinstance(t.get("type"), str) and isinstance(t.get("label"), str) and type(t.get("total")) is int
                    and t["total"] >= 1 for t in types)
            and sum(t["total"] for t in types) == data["total"]):
        return False
    listed, field_ids = {t["type"] for t in types}, {f[0] for f in key["fields"]}
    return all(f in field_ids and isinstance(per, dict) and all(k in listed and valid_type_entry(e) for k, e in per.items())
               for f, per in by_type.items())


def tyre_choice_name(s, text):
    """The choice of the enum field s whose text is text; for a path that is no choice the file stem."""
    try:
        return choice_of(s, text)
    except (ValueError, KeyError):
        return os.path.splitext(re.split(r"[\\/]", text)[-1])[0]


def widen(r, value):
    return ({"low": value, "high": value, "count": 1} if r is None
            else {"low": min(r["low"], value), "high": max(r["high"], value), "count": r["count"] + 1})


def read_tyre_ranges(work, tyres, fields, game):
    """{"total", "types", "by_type"} read from every tyre of the list: the values of the fields (the first target, as the default of
    tyre_rows reads it) of the tyres that store the field. "types" is [{"type", "label", "total"}] (tyre_type_order) and "by_type"
    {field id: {type: entry}} with {"low", "high", "count"} for a float field and {"values", "count"} for a bool or an enum field (see
    the docstring of this file). A tyre that cannot be read is skipped."""
    local = tyre_sets.find_files(work, [t["path"] for t in tyres], game)
    per_type, kinds, total = {}, {}, 0
    for t in tyres:
        path = local.get(tyre_sets.norm(t["path"]))
        try:
            obj = load_msg(path)[0] if path else None
        except (ValueError, OSError):
            obj = None
        if obj is None:
            continue
        total += 1
        kinds.setdefault(t["type"], {"type": t["type"], "label": t["type_label"], "total": 0})["total"] += 1
        mine = per_type.setdefault(t["type"], {})
        for s in fields:
            try:
                value, absent = get_value(obj, s["targets"][0]["path"], True)
            except ValueError:
                continue
            value = plain(value)
            if s["type"] == "float":
                if absent or not finite_number(value):
                    continue
                mine[s["id"]] = widen(mine.get(s["id"]), value)
                continue
            if s["type"] == "bool":
                if absent and "absent" not in s:
                    continue
                if not absent and type(value) is not bool:
                    continue
                name, stored = (False, False) if absent else (value, True)
            else:
                if absent or not isinstance(value, str):
                    continue
                name, stored = tyre_choice_name(s, value), True
            r = mine.setdefault(s["id"], {"values": set(), "count": 0})
            r["values"].add(name)
            r["count"] += int(stored)
    by_type = {}
    for s in fields:
        for kind, mine in per_type.items():
            e = mine.get(s["id"])
            if e is None:
                continue
            if "values" in e:
                choices = s.get("choices", [])
                e = {"values": sorted(e["values"]) if s["type"] == "bool" else
                     sorted(e["values"], key=lambda n: (choices.index(n) if n in choices else len(choices), n)), "count": e["count"]}
            by_type.setdefault(s["id"], {})[kind] = e
    return {"total": total, "types": [kinds[k] for k in tyre_type_order(kinds)], "by_type": by_type}


def tyre_ranges(work, catalogue=None, game=DEFAULT_GAME):
    """What the available_tyres store in every tyre field, by tyre type: {"total": the number of tyres read, "types": [{"type", "label",
    "total"}], "by_type": {field id: {type: entry}}} (read_tyre_ranges describes the entries). Cached in
    <work>/tyre_ranges.json while the package (size, mtime; without a package the list of tyres), the list of field ids, paths and
    enum choices and the types stay the same; a damaged or outdated file is read again, a failed write is no error."""
    tyres = available_tyres(work, game)
    fields = [s for s in tyre_fields(catalogue) if s["type"] in ("float", "bool", "enum")]
    key = tyre_ranges_key(work, tyres, fields, game)
    path = tyre_ranges_path(work)
    try:
        st = stat_or_none(path)
    except OSError:
        st = None
    stamp = (st.st_mtime_ns, st.st_size) if st else None
    with _tyre_ranges_lock:
        hit = _tyre_ranges_loaded.get(path)
    if hit and hit[0] == stamp and hit[1] == key:
        return copy.deepcopy(hit[2])
    try:
        data = read_json(path) if st else None
    except (ValueError, OSError):
        data = None
    if valid_tyre_ranges(data, key):
        found = {k: data[k] for k in ("total", "types", "by_type")}
    else:
        found = read_tyre_ranges(work, tyres, fields, game)
        try:
            if os.path.isdir(work):
                save_json(path, dict(key, version=TYRE_RANGES_VERSION, **found))
        except OSError:
            pass
        try:
            st = stat_or_none(path)
        except OSError:
            st = None
        stamp = (st.st_mtime_ns, st.st_size) if st else None
    with _tyre_ranges_lock:
        _tyre_ranges_loaded[path] = (stamp, key, copy.deepcopy(found))
    return found


def tyre_type_list(work, catalogue=None, game=DEFAULT_GAME):
    """The "types" of tyre_ranges ([{type, label, total}]); [] when they cannot be computed."""
    try:
        return tyre_ranges(work, catalogue, game)["types"]
    except (ValueError, OSError):
        return []


def find_tyre(work, text, game=DEFAULT_GAME):
    """The tyre entry named by text: a game path below content\\cars\\common_phsx (with or without .tyre, any slashes and case) or the
    file name without its folder and .tyre (road_235_35_19); ValueError when it is none of the available_tyres or the stem is not
    unique."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a tyre source must be a game path or a file name, got %r" % (text,))
    text = text.strip()
    index = available_tyres(work, game)
    stem = text[:-len(".tyre")] if text.lower().endswith(".tyre") else text
    if re.search(r"[\\/]", text):
        hits = [t for t in index if tyre_sets.norm(t["path"]) == tyre_sets.norm(stem + ".tyre")]
    else:
        hits = [t for t in index if t["file"].lower() == stem.lower()]
    if not hits:
        raise ValueError("unknown tyre %r, tyre-index lists the tyres" % text)
    if len(hits) > 1:
        raise ValueError("%r names %d tyres (%s), give the game path" % (text, len(hits), ", ".join(t["path"] for t in hits)))
    return hits[0]


def load_tyre(work, tyre_id):
    """The library tyre {version, name, short, source (game path), values} of <work>/tyres/<id>.json, checked for its shape; a tyre
    saved in the old front/rear form (version 1) is an error."""
    path = tyre_path(work, tyre_id)
    if not os.path.isfile(kspkg.long_path(path)):
        raise ValueError("no tyre %r in the library" % tyre_id)
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("%s: expected an object" % path)
    if type(data.get("version")) is int and data["version"] == 1:
        raise ValueError("%s: the tyre was saved in the old front/rear form and must be created again" % path)
    if type(data.get("version")) is not int or data["version"] != TYRE_VERSION:
        raise ValueError("%s: version %r is not supported (expected %d)" % (path, data.get("version"), TYRE_VERSION))
    if not isinstance(data.get("name"), str) or not data["name"]:
        raise ValueError("%s: name must be text" % path)
    if not isinstance(data.get("short"), str) or not TYRE_SHORT.fullmatch(data["short"]):
        raise ValueError("%s: short must be 1 to 3 characters A-Z and 0-9" % path)
    if not isinstance(data.get("source"), str) or not data["source"]:
        raise ValueError("%s: source needs a tyre game path" % path)
    if not isinstance(data.get("values"), dict):
        raise ValueError("%s: values must be an object" % path)
    return data


def save_tyre(work, tyre_id, name, short, source, values):
    save_json(tyre_path(work, tyre_id), {"version": TYRE_VERSION, "name": name, "short": short, "source": source, "values": values})


def list_tyres(work):
    """The library, sorted by name (ignoring case), then id: {id, name, short, source, changed}; a file that cannot be read or has
    a wrong shape (an old front/rear tyre too) is {id, error} and comes last."""
    folder = tyres_dir(work)
    good, bad = [], []
    for n in sorted(os.listdir(kspkg.long_path(folder))) if os.path.isdir(kspkg.long_path(folder)) else []:
        tyre_id = n[:-len(".json")]
        if not n.endswith(".json") or not TYRE_ID.fullmatch(tyre_id):
            continue
        try:
            t = load_tyre(work, tyre_id)
        except (ValueError, OSError) as e:
            bad.append({"id": tyre_id, "error": str(e)})
        else:
            good.append({"id": tyre_id, "name": t["name"], "short": t["short"], "source": t["source"], "changed": len(t["values"])})
    return sorted(good, key=lambda t: (t["name"].lower(), t["id"])) + bad


def create_tyre(work, name, source, short=None, game=DEFAULT_GAME):
    """A new library tyre named name from a source (find_tyre: a game path or file name of an available tyre; game is the game
    package), without changed values; short is 1 to 3 characters A-Z 0-9 (default default_short of the name); returns {id, name,
    short, source}."""
    name = check_tyre_name(work, name)
    short = default_short(name) if short is None else check_tyre_short(short)
    source = find_tyre(work, source, game)["path"]
    tyre_id = free_tyre_id(work, name)
    save_tyre(work, tyre_id, name, short, source, {})
    return {"id": tyre_id, "name": name, "short": short, "source": source}


def rename_tyre(work, tyre_id, name, short=None):
    """Change the name of a library tyre, and its short name when short is given."""
    tyre = load_tyre(work, tyre_id)
    tyre["name"] = check_tyre_name(work, name, tyre_id)
    if short is not None:
        tyre["short"] = check_tyre_short(short)
    save_tyre(work, tyre_id, tyre["name"], tyre["short"], tyre["source"], tyre["values"])
    return {"id": tyre_id, "name": tyre["name"], "short": tyre["short"]}


def set_tyre_source(work, tyre_id, source, game=DEFAULT_GAME):
    """Point a library tyre at another source (see create_tyre); the values are kept."""
    tyre = load_tyre(work, tyre_id)
    source = find_tyre(work, source, game)["path"]
    save_tyre(work, tyre_id, tyre["name"], tyre["short"], source, tyre["values"])
    return {"id": tyre_id, "source": source}


def set_tyre_value(work, tyre_id, field_id, text, catalogue=None):
    """Like set_value for a library tyre: the id of a field of tyre_fields and the value, and the range warnings."""
    tyre = load_tyre(work, tyre_id)
    s = tyre_field(catalogue or load_catalogue(), field_id)
    v = coerce(s, text)
    tyre["values"][field_id] = v
    save_tyre(work, tyre_id, tyre["name"], tyre["short"], tyre["source"], tyre["values"])
    warning = range_warning(s, v)
    return {"id": field_id, "value": v, "warnings": [warning] if warning else []}


def unset_tyre_value(work, tyre_id, field_id, catalogue=None):
    tyre = load_tyre(work, tyre_id)
    if field_id not in tyre["values"]:
        tyre_field(catalogue or load_catalogue(), field_id)
    removed = tyre["values"].pop(field_id, None) is not None
    if removed:
        save_tyre(work, tyre_id, tyre["name"], tyre["short"], tyre["source"], tyre["values"])
    return {"id": field_id, "removed": removed}


def reset_tyre(work, tyre_id):
    """Drop every changed value of a library tyre; returns {id, cleared} (the number of values dropped)."""
    tyre = load_tyre(work, tyre_id)
    cleared = len(tyre["values"])
    if cleared:
        save_tyre(work, tyre_id, tyre["name"], tyre["short"], tyre["source"], {})
    return {"id": tyre_id, "cleared": cleared}


def source_object(work, tyre, tyre_id, game):
    """(decoded source file, message name) of a library tyre; ValueError naming the tyre when the file cannot be had or read."""
    try:
        return load_msg(tyre_sets.find_file(work, tyre["source"], game))
    except (ValueError, OSError) as e:
        raise ValueError("tyre %s: the source %s cannot be read: %s" % (tyre_id, tyre["source"], e)) from None


def tyre_rows(work, tyre_id, catalogue=None, game=DEFAULT_GAME):
    """One row per field of tyre_fields for the tyre editor: the field's keys, default (read from the source tyre file), value (the
    override or the default) and changed. A field whose default cannot be read from the file gets applicable False and a reason
    (default None); the others applicable True and reason None."""
    tyre = load_tyre(work, tyre_id)
    obj = source_object(work, tyre, tyre_id, game)[0]
    rows = []
    try:
        ranges = tyre_ranges(work, catalogue, game)
    except (ValueError, OSError):
        ranges = {"total": 0, "types": [], "by_type": {}}
    for s in tyre_fields(catalogue):
        row = {k: s[k] for k in ("id", "label", "group", "unit", "type", "kind", "description", "verified")}
        row.update({k: s[k] for k in ("min", "max") if k in s})
        row["type_ranges"] = {k: dict(e, **({"values": list(e["values"])} if "values" in e else {})) for k, e in ranges["by_type"].get(s["id"], {}).items()}
        if s["type"] == "enum":
            row["choices"] = list(s["choices"])
        targets = [c for t in s["targets"] for c in resolve_target(s, dict(t, file="tyre"), "", "tyre", {"tyre": obj})]
        missing = [t for t in targets if not t["resolved"] and not t.get("optional")]
        reason = ("%s: %s" % (missing[0]["path"], missing[0].get("error", "unresolved").removeprefix(missing[0]["path"] + ": "))
                  if missing else None)
        values = [t["value"] for t in targets if t["resolved"]]
        if reason is None and not values:
            reason = "no value in the source file"
        default = values[0] if reason is None else None
        try:
            value = coerce(s, tyre["values"][s["id"]]) if s["id"] in tyre["values"] else default
        except ValueError as e:
            raise ValueError("tyre %s: %s" % (tyre_id, e)) from None
        row.update(default=default, value=value, changed=s["id"] in tyre["values"] and not same(s, value, default),
                   applicable=reason is None, reason=reason)
        rows.append(row)
    return rows


def tyre_key(text):
    """("game", game path) or ("own", tyre id) for a tyre key ("game:<path>", "own:<id>"), None for anything else."""
    if isinstance(text, str):
        for kind, prefix in (("game", GAME_KEY), ("own", OWN_KEY)):
            if text.startswith(prefix) and len(text) > len(prefix):
                return kind, text[len(prefix):]
    return None


def key_texts(value):
    """Every text that looks like a tyre key in a saved "_tyres" value of any form (for finding the users of a library tyre)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [t for v in value for t in key_texts(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in key_texts(v)]
    return []


def tyre_in_state(state, tyre_id):
    return (OWN_KEY + tyre_id) in key_texts(state.get(TYRE_KEY)) if TYRE_KEY in state else False


def tyre_users(work, tyre_id):
    """The saved states that use the library tyre in their "_tyres": {car (stock car id), tune (tune id, or DRAFT)} and for a version
    of a tune also version, per stock car the default tune (its versions after it), the other tunes by id, then the draft.
    Unreadable state files are ignored."""
    check_tyre_id(tyre_id)
    users = []

    def uses(path):
        try:
            return tyre_in_state(read_json(path), tyre_id)
        except (ValueError, OSError, AttributeError):
            return False

    for car_id in car_folders(work):
        default = new_id_for(car_id)
        folder = os.path.join(car_work(work, car_id), TUNES)
        names = sorted(os.listdir(kspkg.long_path(folder))) if os.path.isdir(kspkg.long_path(folder)) else []
        others = [n for n in names if n != default and is_tune_id(work, car_id, n)]
        for label, tune in [(default, None)] + [(n, n) for n in others] + [(DRAFT, DRAFT)]:
            if uses(state_path(work, car_id, tune)):
                users.append({"car": car_id, "tune": label})
            for v in [] if tune == DRAFT else list_versions(work, car_id, tune):
                if uses(version_state_path(work, car_id, v["id"], tune)):
                    users.append({"car": car_id, "tune": label, "version": v["id"]})
    return users


def delete_tyre(work, tyre_id):
    """Remove a library tyre; refused while a saved state (a version and the draft included) of a modded car uses it."""
    if not tyre_exists(work, tyre_id):
        raise ValueError("no tyre %r in the library" % tyre_id)
    users = tyre_users(work, tyre_id)
    if users:
        raise ValueError("tyre %s is used by %s" % (tyre_id, ", ".join(
            "%s (draft)" % u["car"] if u["tune"] == DRAFT else "%s / %s%s" % (u["car"], u["tune"], " / " + u["version"] if "version" in u else "")
            for u in users)))
    os.remove(kspkg.long_path(tyre_path(work, tyre_id)))
    return {"id": tyre_id, "deleted": True}


def key_label(work, key):
    """The name a tyre key has in lists: the label of tyre_sets.tyre_entry for a game tyre, the name of a library tyre."""
    kind, rest = tyre_key(key)
    if kind == "own":
        try:
            return load_tyre(work, rest)["name"]
        except (ValueError, OSError):
            return "%s (not in the library)" % rest
    try:
        return tyre_sets.tyre_entry(rest)["label"]
    except ValueError:
        return rest


def stock_sets(work, car_id):
    """The stock tyre sets of a car: the physic compounds of the presets/*.compatibletyres of its own base (preset_tyre_pairs: shared
    game files present in the base) in order, each pair once, as [{front, rear (keys "game:<path>"), label ("<front label> / <rear
    label>")}]. A car without a base or without presets has none."""
    try:
        pairs = preset_tyre_pairs(base_dir(work, car_id), car_id)
    except (ValueError, OSError):
        return []
    return [{"front": GAME_KEY + f, "rear": GAME_KEY + r, "label": "%s / %s" % (key_label(work, GAME_KEY + f), key_label(work, GAME_KEY + r))}
            for f, r in pairs]


def key_list(value, name):
    if not isinstance(value, list) or not value:
        raise ValueError("%s must be a list of tyre keys with at least one key" % name)
    for k in value:
        if tyre_key(k) is None:
            raise ValueError("bad tyre key %r in %s: use game:<game path> or own:<tyre id>" % (k, name))
    if len(tyre_sets.unique_paths(value)) != len(value):
        raise ValueError("%s lists a tyre twice" % name)
    return list(value)


def choice_lists(choice):
    """(fronts, rears): the front and the rear tyre keys of a tyre choice in order, each once."""
    if choice["split"]:
        return list(choice["fronts"]), list(choice["rears"])
    return (tyre_sets.unique_paths([s["front"] for s in choice["sets"]]), tyre_sets.unique_paths([s["rear"] for s in choice["sets"]]))


def parse_choice(value):
    """The tyre choice in its saved form: {sets: [{front, rear}], split: False, start_front, start_rear}, or {split: True, fronts,
    rears, start_front, start_rear}; the start keys (default: the first of the list) must be in the lists. ValueError with the fault
    when value is no tyre choice; the keys are only checked for their form."""
    if not isinstance(value, dict):
        raise ValueError("the tyre choice must be an object")
    unknown = sorted(set(value) - set(CHOICE_FIELDS))
    if unknown:
        raise ValueError("unknown field %r in the tyre choice" % unknown[0])
    split = value.get("split", False)
    if type(split) is not bool:
        raise ValueError("split must be true or false")
    if split:
        out = {"split": True, "fronts": key_list(value.get("fronts"), "fronts"), "rears": key_list(value.get("rears"), "rears")}
    else:
        sets = value.get("sets")
        if not isinstance(sets, list) or not sets:
            raise ValueError("sets must be a list with at least one set")
        for s in sets:
            if not (isinstance(s, dict) and set(s) == {"front", "rear"}):
                raise ValueError("a set is {front, rear}, got %r" % (s,))
            key_list([s["front"]], "a set")
            key_list([s["rear"]], "a set")
        out = {"sets": [{"front": s["front"], "rear": s["rear"]} for s in sets], "split": False}
    fronts, rears = choice_lists(out)
    for field, keys in (("start_front", fronts), ("start_rear", rears)):
        key = value.get(field, keys[0])
        if tyre_key(key) is None or tyre_sets.norm(key) not in [tyre_sets.norm(k) for k in keys]:
            raise ValueError("%s %r is not one of the %s tyres" % (field, key, "front" if field == "start_front" else "rear"))
        out[field] = next(k for k in keys if tyre_sets.norm(k) == tyre_sets.norm(key))
    return out


def old_choice(value):
    """The tyre choice of a saved "_tyres" list of the old form (entries "stock:<front>|<rear>"): every entry a set, the start the first
    entry's pair. An "own:" entry is an error (the choice was made before the tyre rebuild)."""
    if not value or not all(isinstance(k, str) for k in value):
        raise ValueError(DAMAGED_CHOICE)
    if any(k.startswith(OWN_KEY) for k in value):
        raise ValueError(OLD_CHOICE)
    sets = []
    for k in value:
        front, bar, rear = k[len(STOCK_KEY):].partition("|") if k.startswith(STOCK_KEY) else ("", "", "")
        if not (front and bar and rear):
            raise ValueError(DAMAGED_CHOICE)
        sets.append({"front": GAME_KEY + front, "rear": GAME_KEY + rear})
    try:
        return parse_choice({"sets": sets, "split": False})
    except ValueError:
        raise ValueError(DAMAGED_CHOICE) from None


def saved_tyres(state):
    """The tyre choice of the "_tyres" entry of a state (parse_choice form), None when it has none; the old list form is converted
    (old_choice). ValueError for a damaged entry and for an old entry with own tyres."""
    if TYRE_KEY not in state:
        return None
    value = state[TYRE_KEY]
    if isinstance(value, list):
        return old_choice(value)
    try:
        return parse_choice(value)
    except ValueError:
        raise ValueError(DAMAGED_CHOICE) from None


def stock_choice(stock):
    """The tyre choice that leaves a car with the stock sets (parse_choice form), None for a car without stock sets."""
    return parse_choice({"sets": [{"front": s["front"], "rear": s["rear"]} for s in stock], "split": False}) if stock else None


def same_choice(a, b):
    """Whether two tyre choices (parse_choice form) give the same sets or lists and the same start tyres (case and slashes ignored)."""
    def norms(c):
        if c["split"]:
            return [[tyre_sets.norm(k) for k in c[f]] for f in ("fronts", "rears")] + [tyre_sets.norm(c["start_front"]), tyre_sets.norm(c["start_rear"])]
        return [[tyre_sets.norm(s["front"]), tyre_sets.norm(s["rear"])] for s in c["sets"]] + [tyre_sets.norm(c["start_front"]), tyre_sets.norm(c["start_rear"])]
    return a["split"] == b["split"] and norms(a) == norms(b)


def choice_keys(choice):
    """Every tyre key a tyre choice (parse_choice form) names, each text once."""
    keys = choice["fronts"] + choice["rears"] if choice["split"] else [k for s in choice["sets"] for k in (s["front"], s["rear"])]
    return list(dict.fromkeys(keys))


def tyre_state(work, car_id, tune=None, version=None):
    return load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)


def tyre_choices(work, car_id, tune=None, version=None):
    """The tyre choice of a car in a state: {default (no saved choice: the car keeps its stock sets), stock_sets ([{front, rear, label}]
    of stock_sets), sets ([{front, rear}] of the choice, empty when split), split, fronts, rears (tyre keys), start_front, start_rear,
    labels ({key: label}), car, tune}; a car without a saved choice and without stock sets has empty lists and no start. The saved
    choice must be readable (saved_tyres)."""
    saved = saved_tyres(tyre_state(work, car_id, tune, version))
    stock = stock_sets(work, car_id)
    choice = saved or stock_choice(stock)
    fronts, rears = choice_lists(choice) if choice else ([], [])
    keys = tyre_sets.unique_paths(fronts + rears + [k for s in stock for k in (s["front"], s["rear"])])
    return {"default": saved is None, "stock_sets": stock, "sets": [] if choice is None or choice["split"] else list(choice["sets"]),
            "split": bool(choice and choice["split"]), "fronts": fronts, "rears": rears,
            "start_front": choice["start_front"] if choice else None, "start_rear": choice["start_rear"] if choice else None,
            "labels": {k: key_label(work, k) for k in keys}, "car": car_id, "tune": tune}


def check_choice_keys(work, choice, game):
    """The tyre choice with every key checked and written the way the library or the game index has it: an own key is a library tyre
    that can be read, a game key a tyre of the available tyres (the game package, else the extracted files)."""
    index = {}

    def checked(key):
        kind, rest = tyre_key(key)
        if kind == "own":
            load_tyre(work, rest)
            return key
        if not index:
            index.update({tyre_sets.norm(t["path"]): t for t in available_tyres(work, game)})
        tyre_sets.tyre_entry(rest)
        t = index.get(tyre_sets.norm(rest))
        if t is None:
            raise ValueError("unknown tyre %s, tyre-index lists the tyres" % rest)
        return GAME_KEY + t["path"]

    mapped = {k: checked(k) for k in choice_keys(choice)}
    fixed = {"split": choice["split"], "start_front": mapped[choice["start_front"]], "start_rear": mapped[choice["start_rear"]]}
    if choice["split"]:
        fixed.update(fronts=[mapped[k] for k in choice["fronts"]], rears=[mapped[k] for k in choice["rears"]])
    else:
        fixed["sets"] = [{"front": mapped[s["front"]], "rear": mapped[s["rear"]]} for s in choice["sets"]]
    return parse_choice(fixed)


def set_tyres(work, car_id, choice, tune=None, version=None, game=DEFAULT_GAME):
    """Save the tyre choice of a state (choice: {sets, split, fronts, rears, start_front, start_rear} as in the "_tyres" entry, see
    parse_choice; game is the game package the tyres are checked against). Every key must be a game tyre of the available tyres or a
    library tyre. The stock choice of the car (its stock_sets, not split, starting on the first) removes the entry. Returns {default,
    sets, split, fronts, rears, start_front, start_rear}."""
    parsed = check_choice_keys(work, parse_choice(choice), game)
    state = tyre_state(work, car_id, tune, version)
    stock = stock_choice(stock_sets(work, car_id))
    default = stock is not None and same_choice(parsed, stock)
    if default:
        if state.pop(TYRE_KEY, None) is not None:
            save_tune_state(work, car_id, state, tune, version)
    else:
        state[TYRE_KEY] = parsed
        save_tune_state(work, car_id, state, tune, version)
    fronts, rears = choice_lists(parsed)
    return {"default": default, "sets": [] if parsed["split"] else parsed["sets"], "split": parsed["split"], "fronts": fronts, "rears": rears,
            "start_front": parsed["start_front"], "start_rear": parsed["start_rear"]}


def reset_tyres(work, car_id, tune=None, version=None):
    """Remove the tyre choice of a state: the car is not touched any more. Returns {removed}."""
    state = tyre_state(work, car_id, tune, version)
    removed = state.pop(TYRE_KEY, None) is not None
    if removed:
        save_tune_state(work, car_id, state, tune, version)
    return {"removed": removed}


def old_tyre_ids(state, cat):
    """The ids of the tyre settings of the car (tyre_settings, the old Tyres section) that a saved state holds a value for."""
    return [s["id"] for s in tyre_settings(cat) if s["id"] in state]


def old_tyre_notes(state, cat, label=""):
    """The note of apply for a state that holds values of the old Tyres section and no tyre choice (once per state; label names a version),
    else none."""
    ids = old_tyre_ids(state, cat)
    if not ids or TYRE_KEY in state:
        return []
    return ["note: %sthis car still has saved tyre values of the old Tyres section (%d): convert them with tyres-convert" % (label, len(ids))]


def old_tyre_values(cat, state):
    """({axle: {field id: coerced value}}, ids) of the saved values of the old Tyres section in a state: the values of each axle under
    the generic ids of tyre_fields (the front setting's id without _front, the rear setting's id without _rear) and the setting ids
    they came from; ValueError for a saved value that is no tyre field or does not fit its field."""
    values, used = {"front": {}, "rear": {}}, []
    for f in tyre_fields(cat):
        if "front_id" not in f:
            continue
        for axle, setting_id in (("front", f["front_id"]), ("rear", f["id"] + "_rear")):
            if setting_id in state:
                values[axle][f["id"]] = coerce(f, state[setting_id])
                used.append(setting_id)
    stray = [i for i in old_tyre_ids(state, cat) if i not in used]
    if stray:
        raise ValueError("%s has no field in the Tyre Creator, it cannot be converted" % stray[0])
    return values, used


def own_tyre_like(work, source, values):
    """The id of the first library tyre (by name) with this source (game path, case and slashes ignored) and exactly these values, None
    when there is none."""
    for t in list_tyres(work):
        if "error" not in t and tyre_sets.norm(t["source"]) == tyre_sets.norm(source) and load_tyre(work, t["id"])["values"] == values:
            return t["id"]
    return None


def free_tyre_name(work, base):
    """base, or base with " 2", " 3" ... appended when a library tyre has that name already (case ignored)."""
    taken = {t["name"].lower() for t in list_tyres(work) if "error" not in t}
    name, n = base, 1
    while name.lower() in taken:
        n += 1
        name = "%s %d" % (base, n)
    return name


def convert_tyres(work, car_id, name, tune=None, version=None, game=DEFAULT_GAME):
    """Turn the saved values of the old Tyres section (the 24 tyre settings of the car, see tyre_settings) of a state (the tune's base,
    its draft or one of its versions) into library tyres and a tyre choice. Per axle: the values saved for it go into an own tyre made
    from the file the settings act on (the .car file's first front / rear tyre in the base of the car), named "<name> front" /
    "<name> rear" (" 2", " 3" ... appended while the name is taken), with the values under the generic ids (tyre_fields); an own tyre
    with exactly that source and those values (also one made by an earlier call) is used instead of a new one. An axle without saved
    values keeps that file as its game tyre. The choice (as set_tyres writes it) has the converted pair as its first set and as the start
    tyres, then the stock sets of the car that differ from it, not split; the saved tyre values are removed from the state. Refused
    (nothing changes): a state with a tyre choice, without saved tyre values, a locked version, a source file that is not available or
    cannot be read, a saved value that does not fit its field. Own tyres made during the call are deleted again when the state cannot
    be written. Returns {front, rear: {key, name, created}, sets (the number of sets of the choice)}."""
    cat = load_catalogue()
    state = tyre_state(work, car_id, tune, version)
    if version is not None:
        check_unlocked(work, car_id, version, tune)
    if not old_tyre_ids(state, cat):
        raise ValueError(CONVERT_NONE)
    if TYRE_KEY in state:
        raise ValueError(CONVERT_CHOICE)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("a tyre name needs 1 to %d characters without control characters" % TYRE_NAME_MAX)
    name = name.strip()
    values, used = old_tyre_values(cat, state)
    root, cache = base_dir(work, car_id), {}
    texts = {axle: tyre_text(root, car_id, "tyre_" + axle, cache) for axle in values}
    entries = {}
    for axle in values:
        if values[axle]:
            entries[axle] = find_tyre(work, texts[axle], game)
            source_object(work, {"source": entries[axle]["path"]}, "%s %s" % (name, axle), game)
    keys, fresh, created = {}, {}, []
    try:
        for axle in values:
            keys[axle] = GAME_KEY + texts[axle]
            if values[axle]:
                source = entries[axle]["path"]
                tyre_id = own_tyre_like(work, source, values[axle])
                fresh[axle] = tyre_id is None
                if tyre_id is None:
                    made = create_tyre(work, free_tyre_name(work, "%s %s" % (name, axle)), source, None, game)
                    tyre_id = made["id"]
                    created.append(tyre_id)
                    save_tyre(work, tyre_id, made["name"], made["short"], made["source"], values[axle])
                keys[axle] = OWN_KEY + tyre_id
        pair = {"front": keys["front"], "rear": keys["rear"]}
        same_pair = [tyre_sets.norm(pair["front"]), tyre_sets.norm(pair["rear"])]
        others = [{"front": s["front"], "rear": s["rear"]} for s in stock_sets(work, car_id)
                  if [tyre_sets.norm(s["front"]), tyre_sets.norm(s["rear"])] != same_pair]
        parsed = check_choice_keys(work, parse_choice({"sets": [pair] + others, "split": False,
                                                       "start_front": pair["front"], "start_rear": pair["rear"]}), game)
        for setting_id in used:
            del state[setting_id]
        state[TYRE_KEY] = parsed
        save_tune_state(work, car_id, state, tune, version)
    except Exception:
        for tyre_id in created:
            with contextlib.suppress(OSError):
                os.remove(kspkg.long_path(tyre_path(work, tyre_id)))
        raise
    first = parsed["sets"][0]
    out = {axle: {"key": first[axle], "name": key_label(work, first[axle]), "created": fresh.get(axle, False)} for axle in ("front", "rear")}
    return dict(out, sets=len(parsed["sets"]))


def turbo_rel(root, car_id, text):
    """The path below the car folder that the text of a turbos_to_load entry names, whether the file exists or not."""
    parts = [p for p in re.split(r"[\\/]+", text) if p]
    return os.path.relpath(os.path.join(root, *parts), car_root_of(root, car_id)).replace(os.sep, "/")


def turbo_listing(root, car_id, cache=None):
    """What the engine file (@engine) of a car lists: {files (path below the car folder of each turbos_to_load entry, in
    order; as @turbo[N] resolves it, else the path the entry names), boost (the max_boost of each turbo file, in file order;
    when a file gives none, the max_boost of the engine's turbos instead if that list has a number for every file, else
    empty), boost_ref (max_turbo_boost of the engine, a reference value, when it is above 0 and boost is empty, else None),
    count (len(files)), missing (the files that are not on disk)}. An engine that cannot be read, or whose turbos_to_load is
    not a list of texts, lists nothing."""
    cache = {} if cache is None else cache
    nothing = {"files": [], "boost": [], "boost_ref": None, "count": 0, "missing": []}
    try:
        engine = read_file(car_root_of(root, car_id), resolve_file("@engine", root, car_id, cache), cache)
    except (ValueError, OSError):
        return nothing
    texts = engine.get("turbos_to_load", [])
    if not (isinstance(texts, list) and all(isinstance(t, str) and t for t in texts)):
        return nothing
    files, missing = [], []
    for i, text in enumerate(texts):
        try:
            files.append(resolve_file("@turbo[%d]" % i, root, car_id, cache))
        except ValueError:
            files.append(turbo_rel(root, car_id, text))
            missing.append(files[-1])
    boost = []
    for rel in files:
        try:
            value = plain(read_file(car_root_of(root, car_id), rel, cache).get("max_boost"))
        except (ValueError, OSError):
            continue
        if finite_number(value):
            boost.append(float(value))
    if len(boost) != len(files):
        turbos = engine.get("turbos", [])
        listed = [plain(t.get("max_boost")) if isinstance(t, dict) else None for t in turbos] if isinstance(turbos, list) else []
        boost = [float(b) for b in listed] if len(listed) == len(files) and all(finite_number(b) for b in listed) else []
    reference = plain(engine.get("max_turbo_boost"))
    boost_ref = float(reference) if not boost and finite_number(reference) and reference > 0 else None
    return {"files": files, "boost": boost, "boost_ref": boost_ref, "count": len(files), "missing": missing}


def has_turbo(root, car_id, cache=None):
    """Whether the engine of the car in root (a base folder, as resolve_file takes it) lists at least one turbo file; an
    engine that cannot be read lists none."""
    return turbo_listing(root, car_id, cache)["count"] >= 1


def files_stamp(root, car_id, rels):
    """The (mtime_ns, size) of each file below the car folder, None for a missing one."""
    car_root = car_root_of(root, car_id)
    return [(st.st_mtime_ns, st.st_size) if st else None for st in (stat_or_none(car_path(car_root, r)) for r in rels)]


def donor_listing(work, car_id):
    """turbo_listing of the base of a car, cached per (work, car) while resolve_stamp and the stamp of every file the listing
    read are unchanged (forget_resolved drops it); the caller gets its own copy. A listing is not cached when a file it read
    cannot be decoded, when the engine cannot be read or when a turbo file is missing."""
    root, key, cache = base_dir(work, car_id), (work, car_id), {}
    stamp = resolve_stamp(work, car_id)
    with _resolve_lock:
        hit = _donor_listings.get(key)
    if hit and stamp is not None and hit[0] == stamp:
        try:
            if files_stamp(root, car_id, hit[1]) == hit[2]:
                return copy.deepcopy(hit[3])
        except (ValueError, OSError):
            pass
    found = turbo_listing(root, car_id, cache)
    rels = [k for k in cache if isinstance(k, str)]
    if (stamp is not None and isinstance(cache.get(("role", "@engine")), str) and not found["missing"]
            and not any(isinstance(cache[r], ValueError) for r in rels)):
        try:
            files = files_stamp(root, car_id, rels)
        except (ValueError, OSError):
            return found
        if resolve_stamp(work, car_id) == stamp:
            with _resolve_lock:
                _donor_listings[key] = (stamp, rels, files, copy.deepcopy(found))
    return found


def turbo_kind(count):
    return "no turbo" if count == 0 else "single turbo" if count == 1 else "twin turbo" if count == 2 else "%d turbos" % count


def turbo_donor(work, car_id, names):
    """The list_turbo_donors entry of one car, None when the id is no car folder id, its base is missing or its engine lists no
    turbo file or lacks one on disk; names is index_names."""
    if not (re.fullmatch(r"[a-z0-9_]+", car_id) and os.path.isdir(kspkg.long_path(car_root_of(base_dir(work, car_id), car_id)))):
        return None
    found = donor_listing(work, car_id)
    if found["count"] < 1 or found["missing"]:
        return None
    return {"car": car_id, "label": stock_car_name(work, car_id, names),
            "count": found["count"], "kind": turbo_kind(found["count"]), "boost": found["boost"],
            "boost_ref": found["boost_ref"]}


def list_turbo_donors(work):
    """The cars that can give their turbo setup: every extracted car (base folder present; a car that cannot be read counts
    as having no turbo) whose engine lists at least one turbo file and has all of them in its base, sorted by display name,
    then id: {car, label (stock_info.json, else the cached car index, else the id), count, kind, boost, boost_ref (as
    turbo_listing gives them)}. Nothing is extracted, the game package is not needed."""
    names = index_names(work)
    donors = [d for d in (turbo_donor(work, car_id, names) for car_id in car_folders(work)) if d]
    return sorted(donors, key=lambda d: (d["label"].lower(), d["car"]))


def saved_turbo(state):
    """The donor id of the "_turbo" entry of a state, None when it has none."""
    if TURBO_KEY not in state:
        return None
    saved = state[TURBO_KEY]
    if not (isinstance(saved, dict) and isinstance(saved.get("donor"), str)):
        raise ValueError("damaged turbo kit in the saved state")
    return saved["donor"]


def turbo_choice(work, car_id, tune=None, version=None):
    """The turbo kit of a car: {donor (saved donor id or None), available (False when the car has a turbo itself or no
    donor exists), reason (why not, else ""), donors (list_turbo_donors without the car), picked (the entry of the saved
    donor in donors, None when it has none or is no donor any more), has_turbo (whether the car has a turbo itself)}."""
    donor = saved_turbo(load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune))
    donors = [d for d in list_turbo_donors(work) if d["car"] != car_id]
    own = has_turbo(base_dir(work, car_id), car_id)
    reason = "the car has a turbo already" if own else "" if donors else "no installed car has a turbo"
    return {"donor": donor, "available": not reason, "reason": reason, "donors": donors,
            "picked": next((d for d in donors if d["car"] == donor), None), "has_turbo": own}


def set_turbo(work, car_id, donor, tune=None, version=None):
    """Choose the donor of a car's turbo kit and store {"donor": donor} in the state (written only when it changes); the car
    must be extracted and have no turbo itself, the donor must be one of list_turbo_donors and not the car. Returns
    {donor, count, kind, boost, boost_ref} of the donor."""
    root = base_dir(work, car_id)
    if has_turbo(root, car_id):
        raise ValueError("%s has a turbo already" % car_id)
    if not os.path.isdir(kspkg.long_path(car_root_of(root, car_id))):
        raise ValueError("no base car in %s, run init first" % root)
    if not isinstance(donor, str):
        raise ValueError("the turbo donor must be a car id, got %r" % (donor,))
    if donor == car_id:
        raise ValueError("%s cannot be its own turbo donor" % car_id)
    picked = turbo_donor(work, donor, {})
    if picked is None:
        raise ValueError("%s is not an installed car with a turbo" % donor)
    state = load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)
    if state.get(TURBO_KEY) != {"donor": donor}:
        state[TURBO_KEY] = {"donor": donor}
        save_tune_state(work, car_id, state, tune, version)
    return {"donor": donor, "count": picked["count"], "kind": picked["kind"], "boost": picked["boost"],
            "boost_ref": picked["boost_ref"]}


def reset_turbo(work, car_id, tune=None, version=None):
    """Remove the turbo kit choice of a state: the car is not touched any more. Returns {removed}."""
    state = load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)
    removed = state.pop(TURBO_KEY, None) is not None
    if removed:
        save_tune_state(work, car_id, state, tune, version)
    return {"removed": removed}


def kit_path(work, car_id, donor):
    return os.path.join(car_work(work, car_id), KIT_DIR, donor)


def kit_info(root):
    """The kit.json of a kit root, None when it is missing, damaged or of another shape than kit_root writes."""
    try:
        info = read_json(os.path.join(root, KIT_JSON))
    except (ValueError, OSError):
        return None
    ok = (isinstance(info, dict) and isinstance(info.get("donor"), str) and isinstance(info.get("kind"), str)
          and all(isinstance(info.get(k), list) and all(isinstance(x, str) for x in info[k]) for k in ("files", "fields", "inline_fields"))
          and isinstance(info.get("stamp"), list) and all(isinstance(x, list) and len(x) == 4 and isinstance(x[1], str) for x in info["stamp"]))
    return info if ok else None


def car_file_rels(root, car_id):
    """The paths below the car folder of the .car files in its data folder, sorted."""
    data = find_ci(car_root_of(root, car_id), "data")
    return [rel_of(root, car_id, os.path.join(data, n)) for n in sorted(os.listdir(kspkg.long_path(data))) if n.lower().endswith(".car")]


def kit_stamp(work, car_id, donor, extra_files):
    """[side, path below the car folder, size, mtime_ns] (size and time null for a missing file) of what a kit depends on: the
    .car files of the car (side "car") and of the donor (side "donor") in their base folders, and the (side, path) pairs of
    extra_files (the engine files of both and the turbo files of the donor)."""
    stamp = []
    for side, cid in (("car", car_id), ("donor", donor)):
        root = base_dir(work, cid)
        for rel in car_file_rels(root, cid) + [r for s, r in extra_files if s == side]:
            st = stat_or_none(os.path.join(car_root_of(root, cid), *rel.split("/")))
            stamp.append([side, rel, st.st_size if st else None, st.st_mtime_ns if st else None])
    return stamp


def kit_current(work, car_id, donor, root):
    """Whether root holds a complete kit of the donor whose inputs have not changed since it was built."""
    info = kit_info(root)
    if info is None or info["donor"] != donor:
        return False
    try:
        now = kit_stamp(work, car_id, donor, [(x[0], x[1]) for x in info["stamp"] if not x[1].lower().endswith(".car")])
    except (ValueError, OSError):
        return False
    return (now == info["stamp"] and os.path.isdir(kspkg.long_path(car_root_of(root, car_id)))
            and all(os.path.isfile(kspkg.long_path(os.path.join(root, *f.split("/")))) for f in info["files"]))


def check_kit(work, car_id, donor):
    """The checks of set_turbo at the time a kit is used: the car has no turbo itself and is extracted, the donor is another car
    that list_turbo_donors would list. Raises ValueError("turbo kit: ...")."""
    root = base_dir(work, car_id)
    if has_turbo(root, car_id):
        raise ValueError("turbo kit: %s has a turbo already" % car_id)
    if not os.path.isdir(kspkg.long_path(car_root_of(root, car_id))):
        raise ValueError("turbo kit: no base car in %s, run init first" % root)
    if donor == car_id:
        raise ValueError("turbo kit: %s cannot be its own turbo donor" % car_id)
    if turbo_donor(work, donor, {}) is None:
        raise ValueError("turbo kit: %s is not an installed car with a turbo" % donor)


def link_tree(src, dst):
    """Copy the tree src to dst, every file as a hard link to its source where the file system allows it, else as a copy. A file of
    dst must be replaced, never written in place: that would change the file in src."""
    src, dst = kspkg.long_path(src), kspkg.long_path(dst)
    for root, _, names in os.walk(src):
        rel = root[len(src):].strip(os.sep)
        out = os.path.join(dst, rel) if rel else dst
        os.makedirs(out, exist_ok=True)
        for n in names:
            try:
                os.link(os.path.join(root, n), os.path.join(out, n))
            except OSError:
                shutil.copy2(os.path.join(root, n), os.path.join(out, n))


def save_fresh(path, name, obj):
    """save_msg into a new file: an existing one (maybe a hard link to a file of base) is removed first, never written in place."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(kspkg.long_path(path))
    save_msg(path, name, obj)


def set_field(obj, key, value, packed=False):
    """Put value into the top-level field key of a decoded message and keep its wire bookkeeping valid: the names in _order follow
    the number of occurrences (every element of a list, but one for a packed list or a single value) and _packed names the packed
    lists."""
    if packed:
        set_list(obj, key, [None])
        obj[key] = value
    elif isinstance(value, list):
        set_list(obj, key, value)
    elif key in obj:
        obj[key] = value
    else:
        add_key(obj, key, value)
    marked = [k for k in obj.get("_packed", []) if k != key] + ([key] if packed else [])
    if marked:
        obj["_packed"] = marked
    else:
        obj.pop("_packed", None)


def copy_turbo_fields(dst, src, turbo_entries):
    """Copy every top-level field of src whose name has "turbo", "boost" or "bov" in it into dst (deep copies, replacing or adding
    the field); the list turbo_entries takes the place of turbos_to_load. Returns the names of the fields copied."""
    names = []
    for key, value in src.items():
        if key.startswith("_") or not any(w in key.lower() for w in KIT_WORDS):
            continue
        set_field(dst, key, list(turbo_entries) if key == "turbos_to_load" else copy.deepcopy(value), key in src.get("_packed", []))
        names.append(key)
    return names


def kit_entry(text, donor, car_id, name):
    """The turbos_to_load entry for the file data/<name> of the car, written like the entry text of the donor: its separators, the
    id of the car in capitals when the donor's id is in capitals."""
    m = re.fullmatch(r"(content[\\/]+cars[\\/]+)(%s)([\\/]+)(.+)" % re.escape(donor), text, re.IGNORECASE)
    if not m or re.match(r"[\\/]", m.group(4)):
        raise ValueError("turbo kit: cannot read the style of the turbos_to_load entry %r of %s, expected content\\cars\\%s\\... or with /"
                         % (text, donor, donor))
    sep = re.search(r"[\\/]+", m.group(4))
    return m.group(1) + (car_id.upper() if m.group(2).isupper() else car_id) + m.group(3) + "data" + (sep.group(0) if sep else m.group(3)) + name


def inline_listing(donor, inline, texts, new_texts):
    """turbos_to_load of the inline engine block of the donor's .car as new entries: the entry of the engine file that names the same file."""
    keys = [game_path_key(t) for t in texts]
    entries = inline["turbos_to_load"]
    if not (isinstance(entries, list) and all(isinstance(t, str) and game_path_key(t) in keys for t in entries)):
        raise ValueError("turbo kit: the .car file of %s lists turbo files that its engine file does not list" % donor)
    return [new_texts[keys.index(game_path_key(t))] for t in entries]


def kit_inline(path, donor, donor_inline, texts, new_texts):
    """Patch the inline engine block of the .car file at path (when it and the donor's have one); returns the fields copied."""
    if not isinstance(donor_inline, dict):
        return []
    car, name = load_msg(path)
    inline = car.get("engine")
    if not isinstance(inline, dict):
        return []
    entries = inline_listing(donor, donor_inline, texts, new_texts) if "turbos_to_load" in donor_inline else None
    fields = copy_turbo_fields(inline, donor_inline, entries)
    if fields:
        save_fresh(path, name, car)
    return fields


def kit_turbo_files(work, car_id, donor, part, listing):
    """Copy the turbo files of the donor (listing: turbo_listing of its base plus texts = the turbos_to_load entries of its engine file, as patch_kit adds it) into the data folder of the car in part as
    kit_turbo_<n>.turbo; returns (paths below the car folder, the turbos_to_load entries that name them)."""
    droot = base_dir(work, donor)
    car_root = car_root_of(part, car_id)
    data = find_ci(car_root, "data")
    taken = {n.lower() for n in os.listdir(kspkg.long_path(data))}
    rels, texts = [], []
    for n, (rel, text) in enumerate(zip(listing["files"], listing["texts"])):
        name = "kit_turbo_%d.turbo" % n
        if name in taken:
            raise ValueError("turbo kit: %s has a data/%s already" % (car_id, name))
        texts.append(kit_entry(text, donor, car_id, name))
        dst = os.path.join(data, name)
        shutil.copy2(kspkg.long_path(car_path(car_root_of(droot, donor), rel)), kspkg.long_path(dst))
        rels.append(rel_of(part, car_id, dst))
    return rels, texts


def patch_kit(work, car_id, donor, part):
    """Add the turbo files of the donor to the copy of base in part and copy the turbo fields into its engine file and the inline
    engine block of its .car file; returns the content of the kit.json."""
    droot, dcache, cache = base_dir(work, donor), {}, {}
    donor_car, car_root = car_root_of(droot, donor), car_root_of(part, car_id)
    donor_engine_rel = resolve_file("@engine", droot, donor, dcache)
    donor_engine = read_file(donor_car, donor_engine_rel, dcache)
    listing = dict(turbo_listing(droot, donor, dcache), texts=donor_engine["turbos_to_load"])
    rels, new_texts = kit_turbo_files(work, car_id, donor, part, listing)
    engine_rel = resolve_file("@engine", part, car_id, cache)
    path = car_path(car_root, engine_rel)
    engine, name = load_msg(path)
    fields = copy_turbo_fields(engine, donor_engine, new_texts)
    save_fresh(path, name, engine)
    donor_inline = read_file(donor_car, resolve_file("@car", droot, donor, dcache), dcache).get("engine")
    inline = kit_inline(car_path(car_root, resolve_file("@car", part, car_id, cache)), donor, donor_inline, listing["texts"], new_texts)
    extra_files = [("car", engine_rel), ("donor", donor_engine_rel)] + [("donor", f) for f in listing["files"]]
    return {"donor": donor, "kind": turbo_kind(len(rels)), "count": len(rels), "files": ["content/cars/%s/%s" % (car_id, r) for r in rels],
            "fields": fields, "inline_fields": inline, "stamp": kit_stamp(work, car_id, donor, extra_files)}


def kit_root(work, car_id, donor):
    """The folder <work>/<car>/kit/<donor>: a tree like base for the car with the turbo kit of the donor built in (see the module
    docstring). Built when it is missing or damaged or when a file it depends on has changed (kit.json holds their size and time),
    else used as it is. Raises ValueError("turbo kit: ...") when the car has a turbo itself or the donor is no donor (any more); a
    failed build removes its .partial folder."""
    if not (isinstance(donor, str) and re.fullmatch(r"[a-z0-9_]+", donor)):
        raise ValueError("turbo kit: %r is not an installed car with a turbo" % (donor,))
    root = kit_path(work, car_id, donor)
    with _kit_lock:
        if kit_current(work, car_id, donor, root):
            return root
        check_kit(work, car_id, donor)
        part = root + ".partial"
        if os.path.exists(kspkg.long_path(part)):
            remove_tree(work, part)
        try:
            link_tree(base_dir(work, car_id), part)
            save_json(os.path.join(part, KIT_JSON), patch_kit(work, car_id, donor, part))
            if os.path.exists(kspkg.long_path(root)):
                remove_tree(work, root)
            os.rename(kspkg.long_path(part), kspkg.long_path(root))
        except BaseException:
            if os.path.exists(kspkg.long_path(part)):
                with contextlib.suppress(OSError):
                    remove_tree(work, part)
            raise
    return root


def root_for(work, car_id, tune=None, version=None):
    """The folder the tune of a car is read and built from: the kit root (kit_root) when its state has a turbo kit, else base; with
    version the state of that version of the tune decides."""
    donor = saved_turbo(load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune))
    return base_dir(work, car_id) if donor is None else kit_root(work, car_id, donor)


def kit_notes(info):
    """The notes of apply for a build from a kit root with this kit.json."""
    notes = ["note: turbo kit: donor %s (%s): files %s, engine fields %s" % (
        info["donor"], info["kind"], ", ".join(f.split("/", 3)[3] for f in info["files"]), ", ".join(info["fields"]))]
    if info["inline_fields"]:
        notes.append("note: turbo kit: .car engine fields %s" % ", ".join(info["inline_fields"]))
    return notes


def tyre_target_paths(obj, s, t, tyre_id):
    """The paths of a target t of the field s in the source file obj; None for an optional target the file cannot take."""
    try:
        paths = expand_path(obj, t["path"], bool(s.get("create_missing")))
        if not paths:
            raise ValueError("%s: the list has no elements" % t["path"])
        for path in paths:
            get_value(obj, path, bool(s.get("create_missing")))
    except ValueError as e:
        if t.get("optional"):
            return None
        raise ValueError("tyres: tyre %s: %s cannot be written into the source file: %s" % (tyre_id, s["id"], e)) from None
    return paths


def own_tyre_file(work, tyre_id, game, cat):
    """The file of a library tyre in a build: (path below the car folder, message name, decoded file, the library tyre): the source tyre
    file with the changed values (the same value handling as the car's tyre values: float32, choice text) and "name" = "<name>
    (<short>)", "shortName" = <short>."""
    try:
        tyre = load_tyre(work, tyre_id)
        obj, name = source_object(work, tyre, tyre_id, game)
    except ValueError as e:
        raise ValueError("tyres: %s" % e) from None
    for s in tyre_fields(cat):
        if s["id"] not in tyre["values"]:
            continue
        try:
            v = coerce(s, tyre["values"][s["id"]])
        except ValueError as e:
            raise ValueError("tyres: tyre %s: %s" % (tyre_id, e)) from None
        v = to_f32(v) if s["type"] == "float" else v
        if s.get("choice_values"):
            v = s["choice_values"][v]
        for t in s["targets"]:
            for path in tyre_target_paths(obj, s, t, tyre_id) or []:
                if "absent" in s and v == s["absent"] and get_value(obj, path, True)[1]:
                    continue
                put_value(obj, path, v)
    put_value(obj, "name", "%s (%s)" % (tyre["name"], tyre["short"]))
    put_value(obj, "shortName", tyre["short"])
    return OWN_TYRE_REL % tyre_id, name, obj, tyre


def start_tyre_files(root, car_id):
    """The setup and the setup limits file of the car in root (@setup, @limits) as paths below the car folder, checked for the
    alignments of the four wheels; ValueError "cannot set the start tyre: ..." when a file or its structure is missing."""
    cache, rels = {}, []
    try:
        for role in ("@setup", "@limits"):
            rel = resolve_file(role, root, car_id, cache)
            alignments = read_file(car_root_of(root, car_id), rel, cache).get("alignments")
            if not (isinstance(alignments, list) and len(alignments) >= 4 and all(isinstance(a, dict) for a in alignments[:4])):
                raise ValueError("%s has no alignments for the four wheels" % rel)
            if role == "@limits" and not all(isinstance(a.get("compound", {}), dict) for a in alignments[:4]):
                raise ValueError("%s: alignments[].compound is no object" % rel)
            rels.append(rel)
    except ValueError as e:
        raise ValueError("cannot set the start tyre: %s" % e) from None
    return rels


def choice_text(record):
    """A tyre choice as the people read it: front <labels>; rear <labels>; starts on <label> / <label> (record: fronts, rears, start_front,
    start_rear, labels)."""
    labels = record["labels"]
    return "front %s; rear %s; starts on %s / %s" % (", ".join(labels[k] for k in record["fronts"]), ", ".join(labels[k] for k in record["rears"]),
                                                     labels[record["start_front"]], labels[record["start_rear"]])


def tyre_plan(work, car_id, new_id, root, state, cat, game):
    """Everything apply needs for the tyre choice of a state, checked before anything is built: the lists (fronts, rears, start_front,
    start_rear: keys), labels ({key: label}), front_paths and rear_paths (game paths as the compatibletyres get them, an own tyre's
    file in the build of new_id), types ({path: type folder} of the own tyres), files ([(path below the car folder, message name,
    object)] of the own tyres), start (index of the start tyre of each axle) and setup, limits (the files of start_tyre_files).
    Raises ValueError for a choice that cannot be read, a tyre that is gone, a source file that cannot be read, a state that also
    holds values of the car's tyre settings and a car without setup files for the start tyre. None for a state without a choice."""
    choice = saved_tyres(state)
    if choice is None:
        return None
    if any(s["id"] in state for s in tyre_settings(cat)):
        raise ValueError("this car has saved tyre values of the old Tyres section and a tyre choice: convert them first")
    fronts, rears = choice_lists(choice)
    files, names, types, paths, known = [], {}, {}, {}, None
    for key in tyre_sets.unique_paths(fronts + rears):
        kind, rest = tyre_key(key)
        if kind == "own":
            rel, name, obj, tyre = own_tyre_file(work, rest, game, cat)
            files.append((rel, name, obj))
            paths[tyre_sets.norm(key)] = game_path_of(new_id, rel)
            types[paths[tyre_sets.norm(key)]] = tyre_sets.tyre_entry(tyre["source"])["type"]
            names[tyre_sets.norm(key)] = tyre["name"]
            continue
        if known is None:
            known = {tyre_sets.norm(t["path"]) for t in available_tyres(work, game)}
        if tyre_sets.norm(rest) not in known:
            raise ValueError("tyres: unknown tyre %s, tyre-index lists the tyres" % rest)
        paths[tyre_sets.norm(key)] = rest
        names[tyre_sets.norm(key)] = key_label(work, key)
    front_paths, rear_paths = [paths[tyre_sets.norm(k)] for k in fronts], [paths[tyre_sets.norm(k)] for k in rears]
    setup, limits = start_tyre_files(root, car_id)
    start = (tyre_sets.compound_index(front_paths, paths[tyre_sets.norm(choice["start_front"])]),
             tyre_sets.compound_index(rear_paths, paths[tyre_sets.norm(choice["start_rear"])]))
    labels = {k: names[tyre_sets.norm(k)] for k in fronts + rears}
    return {"fronts": fronts, "rears": rears, "start_front": choice["start_front"], "start_rear": choice["start_rear"], "labels": labels,
            "front_paths": front_paths, "rear_paths": rear_paths, "types": types, "files": files, "start": start, "setup": setup,
            "limits": limits}


def start_tyre_edits(plan, car_id, new_id, edits):
    """Add the edits of the start tyre to edits (see collect_edits): the compound of the four alignments of the setup file (index of
    the start tyre, wheels 0 and 1 front, 2 and 3 rear) and, in the setup limits file, the highest index of the axle and is_modifiable."""
    item = {"files": []}
    setup, limits = renamed(plan["setup"], car_id, new_id), renamed(plan["limits"], car_id, new_id)
    for i in range(4):
        axle = 0 if i < 2 else 1
        count = len((plan["front_paths"], plan["rear_paths"])[axle])
        edits.setdefault(setup, []).append((item, "alignments[%d].compound" % i, to_f32(float(plan["start"][axle]))))
        edits.setdefault(limits, []).append((item, "alignments[%d].compound.max" % i, to_f32(float(count - 1))))
        edits.setdefault(limits, []).append((item, "alignments[%d].compound.is_modifiable" % i, True))


def set_list(obj, key, values):
    """Replace a repeated field of obj; the names of the field in the wire order (_order) follow the new length."""
    obj[key] = values
    order = obj.get("_order")
    if isinstance(order, list):
        at = order.index(key) if key in order else len(order)
        order[:] = [k for k in order if k != key]
        order[at:at] = [key] * len(values)


def compounds_of(preset):
    compounds = preset.get("physic_compounds", [])
    return compounds if isinstance(compounds, list) else []


def preset_files(folder):
    return [n for n in sorted(os.listdir(kspkg.long_path(folder))) if n.lower().endswith(".compatibletyres")] \
        if os.path.isdir(kspkg.long_path(folder)) else []


def tyre_compounds(preset, plan):
    """(physic_compounds, graphic_compounds) of one presets/*.compatibletyres for the tyre choice of a plan: tyre_sets.build_compounds
    of the file's own compounds; a compound that keeps its name (and so its pair of tyres) stays as the file has it, a new one gets
    the three fields only (the rear tyre as a list, unless the file's compounds have it as plain text)."""
    stock = compounds_of(preset)
    built = tyre_sets.build_compounds(stock, plan["front_paths"], plan["rear_paths"], plan["types"])
    old = {c["tyre_compound"]: c for c in stock if isinstance(c, dict) and isinstance(c.get("tyre_compound"), str)}
    old_graphic = {c["tyre_compound"]: c for c in preset.get("graphic_compounds", []) if isinstance(c, dict) and isinstance(c.get("tyre_compound"), str)}
    plain_text = any(isinstance(c.get("rear_tyre_data_paths"), str) for c in stock if isinstance(c, dict))
    physic = []
    for c in built["physic"]:
        kept = old.get(c["tyre_compound"])
        if kept is not None and compound_pair(kept) == (game_path_key(c["front_tyre_data_path"]), game_path_key(c["rear_tyre_data_paths"])):
            physic.append(copy.deepcopy(kept))
        else:
            physic.append(dict(c, rear_tyre_data_paths=c["rear_tyre_data_paths"] if plain_text else [c["rear_tyre_data_paths"]]))
    graphic = [copy.deepcopy(old_graphic.get(g["tyre_compound"], g)) for g in built["graphic"]]
    return physic, graphic


def write_tyre_choice(car_root, plan):
    """Write the tyre choice of a plan into the build of the tuned car: the files of the own tyres and the physic_compounds and
    graphic_compounds of every presets/*.compatibletyres (tyre_compounds). Returns the notes for the build log."""
    for rel, name, obj in plan["files"]:
        path = car_path(car_root, rel)
        os.makedirs(kspkg.long_path(os.path.dirname(path)), exist_ok=True)
        save_msg(path, name, obj)
    folder = os.path.join(car_root, "presets")
    for n in preset_files(folder):
        preset, name = load_msg(os.path.join(folder, n))
        physic, graphic = tyre_compounds(preset, plan)
        set_list(preset, "physic_compounds", physic)
        set_list(preset, "graphic_compounds", graphic)
        save_msg(os.path.join(folder, n), name, preset)
    return ["note: tyres: " + choice_text(plan)]


def actor_path(work, car_id):
    """The <car id>.actor file in the base car folder (matched case-insensitively); the car must be extracted."""
    root = base_dir(work, car_id)
    car_root = car_root_of(root, car_id)
    if not os.path.isdir(kspkg.long_path(car_root)):
        raise ValueError("no base car in %s, run init first" % root)
    return find_ci(car_root, car_id + ".actor")


def load_actor(work, car_id):
    return load_msg(actor_path(work, car_id))[0]


def carpart_rels(car_root):
    """The .carpart files below presets/parts of a car folder as paths relative to it (with /), sorted."""
    base = kspkg.long_path(car_root)
    return sorted(os.path.relpath(os.path.join(dp, n), base).replace(os.sep, "/")
                  for dp, _, names in os.walk(os.path.join(base, "presets", "parts")) for n in names if n.lower().endswith(".carpart"))


def sound_events(work, car_id):
    """The audio entries of the sound slots of a car: those of its .actor file, then those of the car_audio_events of the logic_parts of
    every .carpart below presets/parts (in file order). Raises like load_actor, or ValueError for a .carpart that cannot be decoded."""
    kinds = set(sounds.SLOTS.values())
    events = [e for e in sounds.audio_events(load_actor(work, car_id)) if isinstance(e, dict) and e.get("type") in kinds]
    car_root = car_root_of(base_dir(work, car_id), car_id)
    for rel in carpart_rels(car_root):
        for part in (load_msg(tree_path(car_root, rel))[0].get("logic_parts") or []):
            events += [e for e in (part.get("car_audio_events") or []) if isinstance(e, dict) and e.get("type") in kinds]
    return events


def actor_sounds(work, car_id):
    """The audio entries of the sound slots of a car (sound_events: its actor file and its car parts), as the object
    sounds.collect_options reads. Cached per (work, car) while the path, size and time of the actor file and of every .carpart file are
    unchanged (forget_resolved drops it); the caller gets its own copy. Raises like sound_events."""
    path, key = actor_path(work, car_id), (work, car_id)
    car_root = car_root_of(base_dir(work, car_id), car_id)

    def stamp_of():
        files = [path] + [tree_path(car_root, rel) for rel in carpart_rels(car_root)]
        stats = [stat_or_none(f) for f in files]
        return None if None in stats else tuple((f, st.st_mtime_ns, st.st_size) for f, st in zip(files, stats))

    stamp = stamp_of()
    with _resolve_lock:
        hit = _actor_options.get(key)
    if hit and stamp is not None and hit[0] == stamp:
        return copy.deepcopy(hit[1])
    found = {"car": {"audio_events": sound_events(work, car_id)}}
    if stamp is not None and stamp_of() == stamp:
        with _resolve_lock:
            _actor_options[key] = (stamp, copy.deepcopy(found))
    return found


def sound_options(work):
    """The sounds the installed cars offer, read from the .actor file of every car with an extracted base (installed_cars):
    ({slot: [{key, event, bank, optional, cars}]}, skipped); see sounds.collect_options. A car whose actor file is missing or cannot
    be decoded is skipped and listed in skipped as {car, reason}."""
    actors, skipped = {}, []
    for car_id in installed_cars(work):
        try:
            actors[car_id] = actor_sounds(work, car_id)
        except (ValueError, OSError) as e:
            skipped.append({"car": car_id, "reason": str(e)})
    return sounds.collect_options(actors), skipped


def sound_own(work, car_id):
    """The sound the stock car has in each slot: {slot: option key, None when the car has no entry of the slot's type}."""
    actor = load_actor(work, car_id)
    own = {}
    for slot in sounds.SLOTS:
        own[slot] = sounds.own_key(actor, slot)
    return own


def saved_sounds(state):
    """The {slot: option key} of the "_sounds" entry of a state, {} when it has none."""
    if SOUND_KEY not in state:
        return {}
    saved = state[SOUND_KEY]
    if not (isinstance(saved, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in saved.items())):
        raise ValueError("damaged sound choice in the saved state")
    return saved


def sound_view(options, skipped, own, saved):
    """{slots: {slot: {options, own, selected}}, skipped, missing}: selected is the saved key of the slot when it is one of the options;
    a saved key that is no option any more is not selected and is listed in missing as {slot, key}."""
    slots, missing = {}, []
    for slot in sounds.SLOTS:
        chosen = saved.get(slot)
        if chosen is not None and chosen not in {o["key"] for o in options[slot]}:
            missing.append({"slot": slot, "key": chosen})
            chosen = None
        slots[slot] = {"options": options[slot], "own": own[slot], "selected": chosen}
    return {"slots": slots, "skipped": skipped, "missing": missing}


def sound_choices(work, car_id, tune=None, version=None):
    """The sound picker of a car: {slots: {slot: {options, own (key of the stock car's sound or None), selected (the saved key
    or None)}}, skipped (cars sound_options could not read), missing (saved choices that are not offered any more)}."""
    saved = saved_sounds(load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune))
    options, skipped = sound_options(work)
    return sound_view(options, skipped, sound_own(work, car_id), saved)


def set_sound(work, car_id, slot, key, tune=None, version=None):
    """Choose the sound with the option key for a slot of a car and store it in the "_sounds" entry of the state (of its version when
    given; written only when it changes). key None or the car's own sound removes the slot's entry, an empty "_sounds" entry is removed from the state. The
    slot must exist and the key must be an option of sound_options. Returns sound_choices."""
    sounds.slot_type(slot)
    if key is not None and not isinstance(key, str):
        raise ValueError("the sound key must be text, got %r" % (key,))
    own = sound_own(work, car_id)
    options, skipped = sound_options(work)
    if key is not None and key not in {o["key"] for o in options[slot]}:
        raise ValueError("unknown %s sound %s, sounds lists the sounds of the game cars" % (slot, key))
    state = load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)
    saved = dict(saved_sounds(state))
    if key is None or key == own[slot]:
        saved.pop(slot, None)
    else:
        saved[slot] = key
    if (saved or None) != state.get(SOUND_KEY):
        if saved:
            state[SOUND_KEY] = saved
        else:
            del state[SOUND_KEY]
        if version is None:
            save_state(work, car_id, state, tune)
        else:
            save_version_state(work, car_id, state, version, tune)
    return sound_view(options, skipped, own, saved)


def reset_sounds(work, car_id, tune=None, slot=None, version=None):
    """Remove the sound choice of one slot, or of every slot (slot None), from a state (of a version when given): the car keeps its own
    sounds. Returns {removed}."""
    if slot is not None:
        sounds.slot_type(slot)
    state = load_state(work, car_id, tune) if version is None else read_version_state(work, car_id, version, tune)
    if slot is None:
        removed = state.pop(SOUND_KEY, None) is not None
    else:
        saved = dict(saved_sounds(state))
        removed = saved.pop(slot, None) is not None
        if removed:
            if saved:
                state[SOUND_KEY] = saved
            else:
                del state[SOUND_KEY]
    if removed and version is None:
        save_state(work, car_id, state, tune)
    elif removed:
        save_version_state(work, car_id, state, version, tune)
    return {"removed": removed}


def sound_template(work, slot, option):
    """The audio entry of the option in the .actor or the car parts of the first installed car that offers it (option["cars"][0], see
    sound_options)."""
    for _, entry in sounds.slot_entries({"car": {"audio_events": sound_events(work, option["cars"][0])}}, slot):
        if sounds.option_of(entry)["key"] == option["key"]:
            return entry
    raise ValueError("the %s sound %s is not in the actor of %s any more" % (slot, option["key"], option["cars"][0]))


def sound_plan(work, car_id, state):
    """Everything apply needs for the saved sounds of a state, checked before anything is built: [{slot, option, template}] in slot
    order, option from sound_options and template its entry (sound_template); a slot whose saved sound is the car's own is left out.
    An unknown slot or a saved sound that is no option any more is a ValueError. Writes nothing."""
    saved = saved_sounds(state)
    for slot in saved:
        sounds.slot_type(slot)
    if not saved:
        return []
    options, _ = sound_options(work)
    own = sound_own(work, car_id)
    plan = []
    for slot in sounds.SLOTS:
        if slot not in saved:
            continue
        option = next((o for o in options[slot] if o["key"] == saved[slot]), None)
        if option is None:
            raise ValueError("the saved %s sound %s is no longer available (the car that had it is not installed), change or reset it"
                             % (slot, saved[slot]))
        if option["key"] != own[slot]:
            plan.append({"slot": slot, "option": option, "template": sound_template(work, slot, option)})
    return plan


def write_sounds(car_root, new_id, plan):
    """The sound step of the build: give the .actor of the built car the sounds of a sound_plan. Returns [{slot, from (the option key the
    car had, None when it had no entry of the slot), to, added (the entry was appended)}] of the changed slots."""
    if not plan:
        return []
    path = find_ci(car_root, new_id + ".actor")
    actor, name = load_msg(path)
    changed = []
    for step in plan:
        before = sounds.own_key(actor, step["slot"])
        sounds.set_choice(actor, step["slot"], step["option"], step["template"], set_field)
        changed.append({"slot": step["slot"], "from": before, "to": step["option"]["key"], "added": before is None})
    save_msg(path, name, actor)
    return changed


def sound_notes(changed):
    """The notes of apply for the changed sound slots, one line each."""
    return ["note: sound %s: %s" % (c["slot"], "- added %s" % c["to"] if c["added"] else "%s -> %s" % (c["from"], c["to"])) for c in changed]


def ranges_path(work):
    return os.path.join(work, RANGES_FILE)


def finite_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def installed_cars(work):
    """Ids of the cars whose base car folder in the work folder is extracted (not empty), sorted."""
    found = []
    for car_id in car_folders(work):
        car_root = car_root_of(base_dir(work, car_id), car_id)
        if os.path.isdir(kspkg.long_path(car_root)) and os.listdir(kspkg.long_path(car_root)):
            found.append(car_id)
    return found


def compute_ranges(work, catalogue=None, game=DEFAULT_GAME):
    """The lowest and highest default of every numeric value setting (kind value, type int or float) over the cars with
    an extracted base in the work folder: {"ranges": {setting id: {"low", "high"}}, "cars": [ids read], "skipped":
    [{"car", "reason"}]}. A car whose defaults cannot be resolved is skipped; a field the car does not store does not count."""
    cat = catalogue or load_catalogue()
    ranges, cars, skipped = {}, [], []
    for car_id in installed_cars(work):
        try:
            rows = resolve_defaults(work, car_id, cat, game, hidden=True)
        except (ValueError, OSError, SystemExit) as e:
            skipped.append({"car": car_id, "reason": str(e)})
            continue
        cars.append(car_id)
        for r in rows:
            if (r["applicable"] and r["kind"] == "value" and r["type"] in ("float", "int") and not r["absent"]
                    and finite_number(r["default"])):
                low, high = ranges.get(r["id"], (r["default"], r["default"]))
                ranges[r["id"]] = (min(low, r["default"]), max(high, r["default"]))
    return {"ranges": {i: {"low": low, "high": high} for i, (low, high) in ranges.items()}, "cars": cars, "skipped": skipped}


def write_ranges(work, ranges):
    path = ranges_path(work)
    save_json(path, ranges)
    return path


def valid_ranges(data):
    return (isinstance(data, dict)
            and all(isinstance(r, dict) and finite_number(r.get("low")) and finite_number(r.get("high")) and r["low"] <= r["high"]
                    for r in data.values()))


def load_ranges(work):
    """{setting id: {"low", "high"}} from <work>/ranges.json; {} when the file is missing, unreadable or invalid. Read again
    only when its (mtime_ns, size) changed."""
    path = ranges_path(work)
    try:
        st = stat_or_none(path)
    except OSError:
        return {}
    if st is None:
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    with _ranges_lock:
        hit = _ranges_loaded.get(path)
    if hit and hit[0] == stamp:
        return copy.deepcopy(hit[1])
    try:
        data = read_json(path)
    except (ValueError, OSError):
        data = None
    found = {i: {"low": r["low"], "high": r["high"]} for i, r in data.items()} if valid_ranges(data) else {}
    with _ranges_lock:
        _ranges_loaded[path] = (stamp, copy.deepcopy(found))
    return found


def table(headers, rows):
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in [headers] + rows) for i in range(len(headers))]
    lines = [" | ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in [headers] + rows]
    return "\n".join([lines[0], "-+-".join("-" * w for w in widths)] + lines[1:])


def consistency_text(row):
    if row["consistent"]:
        return "yes"
    return "NO (%s)" % " / ".join(fmt(t["value"]) for t in row["targets"] if t["resolved"])


def print_defaults(rows):
    print(table(["id", "group", "default", "unit", "targets resolved", "consistent"],
                [[r["id"], r["group"], fmt(r["default"]) + (" (absent)" if r["absent"] else ""), r["unit"],
                  "%d/%d" % (sum(t["resolved"] for t in r["targets"]), len(r["targets"])) if r["targets"] else "-",
                  consistency_text(r)] for r in rows]))


def print_copy_differences(rows):
    differing = [r for r in rows if r["copies_differ"]]
    if not differing:
        return
    print("copies differ in the stock data (%d setting(s), the default shown is the first required target):"
          % len(differing))
    for r in differing:
        print("  " + r["id"])
        for c in r["copy_values"]:
            print("    %s = %s" % (c["target"], fmt(c["value"])))


def warn_unknown_state(work, car_id, catalogue=None, tune=None, version=None):
    for sid in unknown_state_ids(work, car_id, catalogue, tune, version):
        print("warning: ignoring unknown setting '%s' in the saved state" % sid, file=sys.stderr)


def note_untested(car_id):
    if car_id not in [c["id"] for c in load_cars()["cars"]]:
        print("note: %s is not in the tested list; results are unverified" % car_id)


def start(opts):
    """Work folder and chosen car of a command; moves the old single-car layout first and says so."""
    work = work_arg(opts)
    cars = load_cars()
    car_id = pick_car(cars, opts.get("car"), load_cars_index(work, game_arg(opts)))
    moved = migrate_old_layout(work, cars["default"])
    if moved:
        print("moved the old single-car layout of %s into %s: %s" % (work, car_work(work, cars["default"]),
                                                                    ", ".join(moved)))
    return work, car_id


def usage():
    print(__doc__.split("\n\n")[1])
    sys.exit(2)


def cli_args(flags, switches=()):
    try:
        pos, opts = parse_args(sys.argv[2:], flags, switches)
    except ValueError:
        usage()
    if "tune" in opts and "draft" in opts:
        usage()
    return pos, opts


def work_arg(opts):
    return work_dir(opts.get("work"))


def game_arg(opts):
    return os.path.expandvars(opts.get("game", DEFAULT_GAME))


def mods_arg(opts):
    return clone_car.expand(opts["mods"]) if "mods" in opts else None


def tune_arg(work, car_id, opts):
    """The tune chosen with --tune: DRAFT for --draft, None when not given, the default id as given, else the id of an existing modded car."""
    if "draft" in opts:
        return DRAFT
    tune_id = opts.get("tune")
    if tune_id is None or tune_id == new_id_for(car_id):
        return tune_id
    if tune_id == DRAFT or not os.path.isfile(kspkg.long_path(state_path(work, car_id, tune_id))):
        raise ValueError("%s has no tune %s" % (car_id, tune_id))
    return tune_id


def cmd_cars():
    pos, opts = cli_args(("game", "mods", "work"), ("tested", "modded"))
    if pos or ("tested" in opts and "modded" in opts):
        usage()
    work, _ = start(opts)
    game = game_arg(opts)
    if "modded" in opts:
        print(table(["id", "stock", "label", "suffix", "installed", "built"],
                    [[r["id"], r["stock"], r["label"], r["name_suffix"], "yes" if r["installed"] else "no",
                      "yes" if r["built"] else "no"] for r in list_modded(work, mods_arg(opts))]))
        return
    print(table(["id", "display name", "extracted", "tested", "new id", "installed", "size"],
                [[r["id"], r["display_name"], "yes" if r["extracted"] else "no", "yes" if r["tested"] else "no",
                  r["new_id"], "yes" if r["installed"] else "no",
                  "%.1f MB" % (r["bytes"] / (1 << 20)) if r["extracted"] else "-"]
                 for r in list_cars(work, mods_arg(opts), "tested" in opts, game)]))
    if "tested" not in opts and load_cars_index(work, game) is None:
        print("note: no car index, only the tested cars are listed: %s" % _index_error[0])


def cmd_init():
    pos, opts = cli_args(("car", "game", "work"))
    if pos:
        usage()
    work, car_id = start(opts)
    note_untested(car_id)
    res = init(work, car_id, game_arg(opts))
    print("base already present" if res["present"] else "extracted the stock car")
    print("%s: %d files, %d folders, %d bytes" % (res["dir"], res["files"], res["dirs"], res["bytes"]))
    print("stock localization %s" % res["stock_loc"])
    print("stock info %s" % res["stock_info"])
    print("shared tyre files %s" % res["tyre_files"])


def cmd_defaults():
    pos, opts = cli_args(("car", "tune", "variant", "version", "work"), ("hidden",))
    if pos or ("tune" in opts and "variant" in opts) or ("version" in opts and "variant" in opts):
        usage()
    work, car_id = start(opts)
    tune_id = tune_arg(work, car_id, opts)
    every = resolve_defaults(work, car_id, hidden=True, variant=opts.get("variant"), tune=tune_id if "version" in opts else None,
                             version=opts.get("version"))
    rows = [r for r in every if r["applicable"]]
    print_defaults(rows)
    print("%d hidden for this car (not applicable)" % (len(every) - len(rows)))
    if "hidden" in opts:
        for r in every:
            if not r["applicable"]:
                print("  %s: %s" % (r["id"], r["reason"]))
    print_copy_differences(rows)


def cmd_variants():
    pos, opts = cli_args(("car", "work"))
    if pos:
        usage()
    work, car_id = start(opts)
    variants = list_variants(work, car_id)
    if not variants:
        print("%s has no variants" % car_id)
    for v in variants:
        print("%s: %s" % (v["id"], v["label"]))
        print("  preset: %s" % v["preset"])
        for role, rel in v["roles"].items():
            print("  %s = %s" % (role, rel))
        if v["not_shown"]:
            print("  not shown: %s" % ", ".join(v["not_shown"]))
        if v["error"]:
            print("  error: %s" % v["error"])


def cmd_versions():
    pos, opts = cli_args(("car", "tune", "work"))
    if pos:
        usage()
    work, car_id = start(opts)
    tune_id = tune_arg(work, car_id, opts)
    name = base_name(work, car_id, tune_id)
    print("base" if name is None else "base: %s" % name)
    for v in list_versions(work, car_id, tune_id):
        print("%s: %s%s" % (v["id"], v["name"], " (locked)" if v["locked"] else ""))


def cmd_version_add():
    pos, opts = cli_args(("from", "car", "tune", "work"))
    if len(pos) != 1:
        usage()
    work, car_id = start(opts)
    print("car: %s, new version: %s" % (car_id, add_version(work, car_id, pos[0], tune_arg(work, car_id, opts), opts.get("from"))))


def cmd_version_lock():
    pos, opts = cli_args(("car", "tune", "work"))
    if len(pos) != 1:
        usage()
    work, car_id = start(opts)
    print("locked %s (%s)" % (pos[0], lock_version(work, car_id, pos[0], tune_arg(work, car_id, opts))))


def cmd_version_unlock():
    pos, opts = cli_args(("car", "tune", "work"))
    if len(pos) != 1:
        usage()
    work, car_id = start(opts)
    print("unlocked %s (%s)" % (pos[0], unlock_version(work, car_id, pos[0], tune_arg(work, car_id, opts))))


def cmd_version_rename():
    pos, opts = cli_args(("car", "tune", "work"))
    if len(pos) != 2:
        usage()
    work, car_id = start(opts)
    print("%s: %s" % (pos[0], rename_version(work, car_id, pos[0], pos[1], tune_arg(work, car_id, opts))))


def cmd_set():
    pos, opts = cli_args(("car", "tune", "version", "work"))
    if len(pos) != 2:
        usage()
    work, car_id = start(opts)
    res = set_value(work, car_id, pos[0], pos[1], tune=tune_arg(work, car_id, opts), version=opts.get("version"))
    for w in res["warnings"]:
        print("warning: " + w, file=sys.stderr)
    print("%s = %s" % (res["id"], fmt(res["value"])))


def cmd_unset():
    pos, opts = cli_args(("car", "tune", "version", "work"))
    if len(pos) != 1:
        usage()
    work, car_id = start(opts)
    res = unset_value(work, car_id, pos[0], tune=tune_arg(work, car_id, opts), version=opts.get("version"))
    print("%s %s" % (res["id"], "removed from the state" if res["removed"] else "was not set"))


def cmd_show():
    pos, opts = cli_args(("car", "tune", "version", "work"))
    if pos:
        usage()
    work, car_id = start(opts)
    tune_id = tune_arg(work, car_id, opts)
    cat = load_catalogue()
    warn_unknown_state(work, car_id, cat, tune_id, opts.get("version"))
    rows = effective_rows(work, car_id, cat, tune=tune_id, version=opts.get("version"))
    lines = table(["", "id", "value", "default", "unit"],
                  [["*" if r["changed"] else "", r["id"], fmt(r["value"]), fmt(r["default"]), r["unit"]] for r in rows]).splitlines()
    print("\n".join(lines[:2] + [line + " | calculated" if r.get("calculated") else line for line, r in zip(lines[2:], rows)]))


def cmd_apply():
    pos, opts = cli_args(("car", "tune", "new-id", "mods", "work"), ("no-install",))
    if pos:
        usage()
    if "tune" in opts and "new-id" in opts:
        raise ValueError("--tune and --new-id cannot be combined")
    if "no-install" not in opts and game_running():
        raise ValueError("the game is running, close it first")
    work, car_id = start(opts)
    note_untested(car_id)
    new_id = tune_arg(work, car_id, opts) or opts.get("new-id")
    cat = load_catalogue()
    warn_unknown_state(work, car_id, cat, new_id)
    res = apply(work, car_id, new_id, "no-install" not in opts, mods_arg(opts), cat)
    print("car: %s, new id: %s" % (car_id, res["new_id"]))
    for line in change_lines(res):
        print(line)
    print("package: %s (%d bytes)" % (res["package"], res["size"]))
    if res["installed"]:
        print("installed: %s" % res["installed"])
        print("backup: %s" % (res["backup"] or "no previous install"))


def cmd_duplicate():
    pos, opts = cli_args(("car", "tune", "new-id", "suffix", "mods", "work"), ("draft",))
    if pos:
        usage()
    work, car_id = start(opts)
    src = tune_arg(work, car_id, opts)
    res = duplicate_tune(work, car_id, src, opts.get("new-id"), opts.get("suffix"), mods_arg(opts))
    print("car: %s, new id: %s" % (car_id, res["id"]))
    print("name suffix: %s" % res["name_suffix"])


def cmd_tyres():
    pos, opts = cli_args(("work",))
    if pos:
        usage()
    tyres = list_tyres(work_arg(opts))
    if not tyres:
        print("no tyres in the library")
    else:
        print(table(["id", "name", "short", "source", "changed"],
                    [[t["id"], t["name"], t["short"], t["source"], t["changed"]]
                     if "error" not in t else [t["id"], "-", "-", "error: " + t["error"], "-"] for t in tyres]))


def cmd_tyre_index():
    pos, opts = cli_args(("type", "game", "work"))
    if pos:
        usage()
    index = available_tyres(work_arg(opts), game_arg(opts))
    if "type" in opts:
        index = [t for t in index if opts["type"].lower() in (t["type"].lower(), t["type_label"].lower())]
    if not index:
        print("note: no tyres to list (the game package was not found and no tyre file is extracted, or no tyre has this type)")
    else:
        print(table(["label", "file", "type"], [[t["label"], t["file"], t["type"]] for t in index]))


def cmd_tyre_new():
    pos, opts = cli_args(("name", "source", "short", "game", "work"))
    if pos or "name" not in opts or "source" not in opts:
        usage()
    res = create_tyre(work_arg(opts), opts["name"], opts["source"], opts.get("short"), game_arg(opts))
    print("created tyre %s: %s (%s, source %s)" % (res["id"], res["name"], res["short"], res["source"]))


def cmd_tyre_show():
    pos, opts = cli_args(("game", "work"))
    if len(pos) != 1:
        usage()
    work = work_arg(opts)
    tyre = load_tyre(work, pos[0])
    rows = tyre_rows(work, pos[0], game=game_arg(opts))
    print("tyre %s: %s (%s), source %s" % (pos[0], tyre["name"], tyre["short"], tyre["source"]))
    print(table(["", "id", "value", "default", "unit", "note"],
                [["*" if r["changed"] else "", r["id"], fmt(r["value"]), fmt(r["default"]), r["unit"], r["reason"] or ""]
                 for r in rows]))


def cmd_tyre_set():
    pos, opts = cli_args(("work",))
    if len(pos) != 3:
        usage()
    res = set_tyre_value(work_arg(opts), pos[0], pos[1], pos[2])
    for w in res["warnings"]:
        print("warning: " + w, file=sys.stderr)
    print("%s = %s" % (res["id"], fmt(res["value"])))


def cmd_tyre_unset():
    pos, opts = cli_args(("work",))
    if len(pos) != 2:
        usage()
    res = unset_tyre_value(work_arg(opts), pos[0], pos[1])
    print("%s %s" % (res["id"], "removed from the tyre" if res["removed"] else "was not set"))


def cmd_tyre_delete():
    pos, opts = cli_args(("work",))
    if len(pos) != 1:
        usage()
    res = delete_tyre(work_arg(opts), pos[0])
    print("deleted tyre %s" % res["id"])


def cmd_tyres_convert():
    pos, opts = cli_args(("car", "tune", "version", "name", "game", "work"), ("draft",))
    if pos or "name" not in opts:
        usage()
    work, car_id = start(opts)
    res = convert_tyres(work, car_id, opts["name"], tune_arg(work, car_id, opts), opts.get("version"), game_arg(opts))
    for axle in ("front", "rear"):
        r = res[axle]
        print("%s: %s" % (axle, ("created tyre %s (%s)" if r["created"] else "used tyre %s (%s)" if r["key"].startswith(OWN_KEY)
                                 else "no saved values, stays on %s (%s)") % (r["key"], r["name"])))
    print("tyres: %d set(s), starting on %s / %s" % (res["sets"], res["front"]["name"], res["rear"]["name"]))


def cmd_garage():
    pos, opts = cli_args(("car", "tune", "work"), ("draft",))
    if pos:
        usage()
    work, car_id = start(opts)
    res = tyre_choices(work, car_id, tune_arg(work, car_id, opts))
    print("tyres of %s: %s" % (car_id, "default (the car's own tyres, the car is not touched)" if res["default"] else "saved choice, %s"
                               % ("front and rear apart" if res["split"] else "%d set(s)" % len(res["sets"]))))
    labels = res["labels"]
    for s in res["sets"]:
        print("set: %s / %s" % (labels[s["front"]], labels[s["rear"]]))
    for title, keys, start_key in (("front", res["fronts"], res["start_front"]), ("rear", res["rears"], res["start_rear"])):
        if keys:
            print(table([title, "start", "key"], [[labels[k], "start" if k == start_key else "", k] for k in keys]))
    if not res["fronts"]:
        print("note: no tyres to show (the presets of the car offer no tyre set and no choice is saved)")


def cmd_garage_set():
    pos, opts = cli_args(("car", "tune", "game", "work"), ("draft",))
    if len(pos) != 1:
        usage()
    work, car_id = start(opts)
    res = set_tyres(work, car_id, read_json(pos[0]), tune_arg(work, car_id, opts), game=game_arg(opts))
    print("tyres: %d front, %d rear, starting on %s / %s%s" % (len(res["fronts"]), len(res["rears"]), res["start_front"], res["start_rear"],
                                                           " (the car's own tyres, nothing is stored)" if res["default"] else ""))


def cmd_garage_reset():
    pos, opts = cli_args(("car", "tune", "work"), ("draft",))
    if pos:
        usage()
    work, car_id = start(opts)
    res = reset_tyres(work, car_id, tune_arg(work, car_id, opts))
    print("tyre choice %s" % ("removed from the state" if res["removed"] else "was not set"))


def boost_text(boost):
    return " / ".join("%g" % b for b in boost) if boost else "unknown"


def cmd_turbo_donors():
    pos, opts = cli_args(("car", "work"))
    if pos:
        usage()
    work, car_id = start(opts) if "car" in opts else (work_arg(opts), None)
    donors = list_turbo_donors(work)
    if donors:
        print(table(["car", "name", "kind", "boost (bar)"],
                    [[d["car"], d["label"], d["kind"], boost_text(d["boost"])] for d in donors]))
    else:
        print("no installed car has a turbo")
    if car_id:
        res = turbo_choice(work, car_id)
        print("chosen: %s" % res["donor"] if res["donor"] else "no turbo kit chosen")
        if res["donor"] and not res["picked"]:
            print("warning: the saved turbo donor %s is not available any more" % res["donor"], file=sys.stderr)


def cmd_turbo_add():
    pos, opts = cli_args(("car", "tune", "work"), ("draft",))
    if len(pos) != 1:
        usage()
    work, car_id = start(opts)
    res = set_turbo(work, car_id, pos[0], tune_arg(work, car_id, opts))
    print("%s: %s, boost %s bar" % (res["donor"], res["kind"], boost_text(res["boost"])))


def cmd_turbo_remove():
    pos, opts = cli_args(("car", "tune", "work"), ("draft",))
    if pos:
        usage()
    work, car_id = start(opts)
    res = reset_turbo(work, car_id, tune_arg(work, car_id, opts))
    print("turbo kit %s" % ("removed from the state" if res["removed"] else "was not set"))


def cmd_turbo_kit():
    pos, opts = cli_args(("car", "tune", "work"), ("draft",))
    if pos:
        usage()
    work, car_id = start(opts)
    tune_id = tune_arg(work, car_id, opts)
    donor = saved_turbo(load_state(work, car_id, tune_id))
    if donor is None:
        raise ValueError("no turbo kit chosen for %s, turbo-add chooses one" % (tune_id or new_id_for(car_id)))
    root = kit_root(work, car_id, donor)
    info = kit_info(root)
    print("kit root: %s" % root)
    print("donor: %s (%s)" % (info["donor"], info["kind"]))
    print("files: %s" % ", ".join(info["files"]))
    print("engine fields: %s" % ", ".join(info["fields"]))
    print(".car fields: %s" % (", ".join(info["inline_fields"]) or "none"))


def cars_text(cars):
    return ", ".join(cars[:4]) + (" +%d more" % (len(cars) - 4) if len(cars) > 4 else "")


def cmd_sounds():
    pos, opts = cli_args(("car", "tune", "work"), ("draft",))
    if pos:
        usage()
    work, car_id = start(opts)
    res = sound_choices(work, car_id, tune_arg(work, car_id, opts))
    for s in res["skipped"]:
        print("skipped %s: %s" % (s["car"], s["reason"]), file=sys.stderr)
    for slot, info in res["slots"].items():
        print("%s (own: %s, selected: %s)" % (slot, info["own"] or "none", info["selected"] or "-"))
        for o in info["options"]:
            print("%s %s  %s" % ("*" if o["key"] == info["selected"] else "=" if o["key"] == info["own"] else " ", o["key"], cars_text(o["cars"])))
    for m in res["missing"]:
        print("warning: the saved %s sound %s is not available any more" % (m["slot"], m["key"]), file=sys.stderr)


def cmd_sound_set():
    pos, opts = cli_args(("car", "tune", "version", "work"), ("draft",))
    if len(pos) != 2:
        usage()
    work, car_id = start(opts)
    res = set_sound(work, car_id, pos[0], pos[1], tune_arg(work, car_id, opts), opts.get("version"))
    print("%s sound: %s%s" % (pos[0], pos[1], "" if res["slots"][pos[0]]["selected"] else " (the own sound of the car, nothing is stored)"))


def cmd_sound_reset():
    pos, opts = cli_args(("car", "tune", "version", "work"), ("draft",))
    if len(pos) > 1:
        usage()
    work, car_id = start(opts)
    res = reset_sounds(work, car_id, tune_arg(work, car_id, opts), pos[0] if pos else None, opts.get("version"))
    print("%ssound selection %s" % (pos[0] + " " if pos else "", "removed from the state" if res["removed"] else "was not set"))


def cmd_ranges():
    pos, opts = cli_args(("work",))
    if pos:
        usage()
    work = work_arg(opts)
    res = compute_ranges(work, game="")
    for s in res["skipped"]:
        print("skipped %s: %s" % (s["car"], s["reason"]), file=sys.stderr)
    if not res["cars"]:
        raise ValueError("no car could be read in %s" % work if res["skipped"] else "no installed car in %s, run init first" % work)
    write_ranges(work, res["ranges"])
    print("read %d cars, skipped %d, %d settings with a range" % (len(res["cars"]), len(res["skipped"]), len(res["ranges"])))


COMMANDS = {
    "cars": cmd_cars,
    "init": cmd_init,
    "defaults": cmd_defaults,
    "variants": cmd_variants,
    "versions": cmd_versions,
    "version-add": cmd_version_add,
    "version-rename": cmd_version_rename,
    "version-lock": cmd_version_lock,
    "version-unlock": cmd_version_unlock,
    "set": cmd_set,
    "unset": cmd_unset,
    "show": cmd_show,
    "apply": cmd_apply,
    "duplicate": cmd_duplicate,
    "tyres": cmd_tyres,
    "tyre-index": cmd_tyre_index,
    "tyre-new": cmd_tyre_new,
    "tyre-show": cmd_tyre_show,
    "tyre-set": cmd_tyre_set,
    "tyre-unset": cmd_tyre_unset,
    "tyre-delete": cmd_tyre_delete,
    "tyres-convert": cmd_tyres_convert,
    "garage": cmd_garage,
    "garage-set": cmd_garage_set,
    "garage-reset": cmd_garage_reset,
    "turbo-donors": cmd_turbo_donors,
    "turbo-add": cmd_turbo_add,
    "turbo-remove": cmd_turbo_remove,
    "turbo-kit": cmd_turbo_kit,
    "sounds": cmd_sounds,
    "sound-set": cmd_sound_set,
    "sound-reset": cmd_sound_reset,
    "ranges": cmd_ranges,
}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        COMMANDS.get(cmd, usage)()
    except (ValueError, OSError) as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
