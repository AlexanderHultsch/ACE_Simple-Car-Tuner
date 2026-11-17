r"""Read the shared memory of Assetto Corsa EVO (Windows): the raw blocks, and named readings of them.

usage: python tools/ace_shm.py dump [--wait SECONDS]
  e.g. python tools/ace_shm.py dump --wait 30

dump waits up to SECONDS (default 5, retry every 0.5 s) for the blocks Local\acevo_pmf_physics, Local\acevo_pmf_graphics and
Local\acevo_pmf_static, reads them once and prints {"info": ..., "channels": ...} as indented JSON on stdout: "info" names the
session (status, car, track, session id, game and layout version, packet ids), "channels" holds the named readings of the
physics and graphics blocks (units as the game gives them, angles in degrees where the name says _deg, NaN and infinity as null).
The blocks are opened read-only with OpenFileMappingW: a game that is not running has no blocks, nothing is created.
Layouts follow Kunos' ACE_SharedFileOut_Documentation_v1 (changelog 2026-03-31). The physics page is the Assetto Corsa
Competizione layout, 800 bytes. Wheel order in every array: front left, front right, rear left, rear right.

Exit code 0 on success, 1 on a runtime error (error: ... on stderr: not on Windows, the game is not running (no shared memory), a block
that cannot be opened or read), 2 on bad usage (usage block on stdout).
"""
import ctypes
import json
import math
import pathlib
import sys
import time
from ctypes import Structure, c_bool, c_byte, c_char, c_float, c_int8, c_int16, c_int32, c_uint8, c_uint16, c_uint32, c_uint64, sizeof

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kspkg  # noqa: E402

PHYSICS_TAG = "Local\\acevo_pmf_physics"
GRAPHICS_TAG = "Local\\acevo_pmf_graphics"
STATIC_TAG = "Local\\acevo_pmf_static"
RETRY_S = 0.5
STATUS = {0: "off", 1: "replay", 2: "live", 3: "pause"}

FILE_MAP_READ = 0x0004
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_wchar_p]
    _kernel32.OpenFileMappingW.restype = ctypes.c_void_p
    _kernel32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
    _kernel32.MapViewOfFile.restype = ctypes.c_void_p
    _kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    class _MemoryInfo(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", ctypes.c_uint32), ("PartitionId", ctypes.c_uint16),
                    ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_uint32),
                    ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32)]

    _kernel32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MemoryInfo), ctypes.c_size_t]
    _kernel32.VirtualQuery.restype = ctypes.c_size_t


class SharedMemory:
    """Read-only view of a named Windows shared memory block. Python's mmap would create a missing block and read
    zeros; OpenFileMappingW fails instead (FileNotFoundError), which tells us the game is not running.
    size: the bytes read() returns (zero-padded if the block is smaller)."""

    def __init__(self, name: str, size: int):
        if sys.platform != "win32":
            raise FileNotFoundError("shared memory needs Windows")
        handle = _kernel32.OpenFileMappingW(FILE_MAP_READ, False, name)
        if not handle:
            code = ctypes.get_last_error()
            if code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
                raise FileNotFoundError(name)
            raise OSError(code, ctypes.FormatError(code), name)
        view = _kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)   # 0 = the whole block
        if not view:
            _kernel32.CloseHandle(handle)
            raise OSError(ctypes.get_last_error(), "MapViewOfFile failed", name)
        info = _MemoryInfo()
        _kernel32.VirtualQuery(view, ctypes.byref(info), ctypes.sizeof(info))
        self.handle, self.view = handle, view
        # Never read past the mapped pages (VirtualQuery gives the view size rounded up to 4096 bytes), so a smaller block is only padded when it ends on an earlier page.
        self.available = min(size, info.RegionSize or size)
        self.size = size

    def read(self) -> bytes:
        """`size` bytes; zero-padded when the mapped view is smaller (the view size is a whole number of pages)."""
        return ctypes.string_at(self.view, self.available).ljust(self.size, b"\0")

    def close(self) -> None:
        if self.view:
            _kernel32.UnmapViewOfFile(self.view)
            self.view = None
        if self.handle:
            _kernel32.CloseHandle(self.handle)
            self.handle = None


class Physics(Structure):            # 800 bytes
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int32), ("gas", c_float), ("brake", c_float), ("fuel", c_float),
        ("gear", c_int32), ("rpms", c_int32), ("steerAngle", c_float), ("speedKmh", c_float),
        ("velocity", c_float * 3), ("accG", c_float * 3), ("wheelSlip", c_float * 4),
        ("wheelLoad", c_float * 4), ("wheelsPressure", c_float * 4), ("wheelAngularSpeed", c_float * 4),
        ("tyreWear", c_float * 4), ("tyreDirtyLevel", c_float * 4), ("tyreCoreTemperature", c_float * 4),
        ("camberRAD", c_float * 4), ("suspensionTravel", c_float * 4), ("drs", c_float), ("tc", c_float),
        ("heading", c_float), ("pitch", c_float), ("roll", c_float), ("cgHeight", c_float),
        ("carDamage", c_float * 5), ("numberOfTyresOut", c_int32), ("pitLimiterOn", c_int32), ("abs", c_float),
        ("kersCharge", c_float), ("kersInput", c_float), ("autoShifterOn", c_int32), ("rideHeight", c_float * 2),
        ("turboBoost", c_float), ("ballast", c_float), ("airDensity", c_float), ("airTemp", c_float),
        ("roadTemp", c_float), ("localAngularVel", c_float * 3), ("finalFF", c_float), ("performanceMeter", c_float),
        ("engineBrake", c_int32), ("ersRecoveryLevel", c_int32), ("ersPowerLevel", c_int32),
        ("ersHeatCharging", c_int32), ("ersIsCharging", c_int32), ("kersCurrentKJ", c_float),
        ("drsAvailable", c_int32), ("drsEnabled", c_int32), ("brakeTemp", c_float * 4), ("clutch", c_float),
        ("tyreTempI", c_float * 4), ("tyreTempM", c_float * 4), ("tyreTempO", c_float * 4),
        # ACE additions from offset 416
        ("isAIControlled", c_int32), ("tyreContactPoint", (c_float * 3) * 4),
        ("tyreContactNormal", (c_float * 3) * 4), ("tyreContactHeading", (c_float * 3) * 4),
        ("brakeBias", c_float), ("localVelocity", c_float * 3), ("P2PActivations", c_int32),
        ("P2PStatus", c_int32), ("currentMaxRpm", c_int32), ("mz", c_float * 4), ("fx", c_float * 4),
        ("fy", c_float * 4), ("slipRatio", c_float * 4), ("slipAngle", c_float * 4), ("tcInAction", c_int32),
        ("absInAction", c_int32), ("suspensionDamage", c_float * 4), ("tyreTemp", c_float * 4),
        ("waterTemp", c_float), ("brakeTorque", c_float * 4), ("frontBrakeCompound", c_int32),
        ("rearBrakeCompound", c_int32), ("padLife", c_float * 4), ("discLife", c_float * 4),
        ("ignitionOn", c_int32), ("starterEngineOn", c_int32), ("isEngineRunning", c_int32),
        ("kerbVibration", c_float), ("slipVibrations", c_float), ("roadVibrations", c_float), ("absVibrations", c_float),
    ]


class Static(Structure):
    _pack_ = 4
    _fields_ = [
        ("sm_version", c_char * 15), ("ac_evo_version", c_char * 15), ("session", c_int32),
        ("session_name", c_char * 33), ("event_id", c_uint8), ("session_id", c_uint8), ("starting_grip", c_int32),
        ("starting_ambient_temperature_c", c_float), ("starting_ground_temperature_c", c_float),
        ("is_static_weather", c_bool), ("is_timed_race", c_bool), ("is_online", c_bool),
        ("number_of_sessions", c_int32), ("nation", c_char * 33), ("longitude", c_float), ("latitude", c_float),
        ("track", c_char * 33), ("track_configuration", c_char * 33), ("track_length_m", c_float),
    ]


class TyreState(Structure):          # 256 bytes
    _pack_ = 4
    _fields_ = [
        ("slip", c_float), ("lock", c_bool), ("tyre_pressure", c_float), ("tyre_temperature_c", c_float),
        ("brake_temperature_c", c_float), ("brake_pressure", c_float), ("tyre_temperature_left", c_float),
        ("tyre_temperature_center", c_float), ("tyre_temperature_right", c_float),
        ("tyre_compound_front", c_char * 33), ("tyre_compound_rear", c_char * 33),
        ("tyre_normalized_pressure", c_float), ("tyre_normalized_temperature_left", c_float),
        ("tyre_normalized_temperature_center", c_float), ("tyre_normalized_temperature_right", c_float),
        ("brake_normalized_temperature", c_float), ("tyre_normalized_temperature_core", c_float),
        ("_reserved", c_byte * 128),
    ]


class DamageState(Structure):        # 128 bytes
    _pack_ = 4
    _fields_ = [
        ("damage_front", c_float), ("damage_rear", c_float), ("damage_left", c_float), ("damage_right", c_float),
        ("damage_center", c_float), ("damage_suspension_lf", c_float), ("damage_suspension_rf", c_float),
        ("damage_suspension_lr", c_float), ("damage_suspension_rr", c_float), ("_reserved", c_byte * 92),
    ]


class PitInfo(Structure):            # 64 bytes
    _pack_ = 4
    _fields_ = [
        ("damage", c_int8), ("fuel", c_int8), ("tyres_lf", c_int8), ("tyres_rf", c_int8), ("tyres_lr", c_int8),
        ("tyres_rr", c_int8), ("_reserved", c_byte * 58),
    ]


class Electronics(Structure):        # 128 bytes
    _pack_ = 4
    _fields_ = [
        ("tc_level", c_int8), ("tc_cut_level", c_int8), ("abs_level", c_int8), ("esc_level", c_int8),
        ("ebb_level", c_int8), ("brake_bias", c_float), ("engine_map_level", c_int8), ("turbo_level", c_float),
        ("ers_deployment_map", c_int8), ("ers_recharge_map", c_float), ("is_ers_heat_charging_on", c_bool),
        ("is_ers_overtake_mode_on", c_bool), ("is_drs_open", c_bool), ("diff_power_level", c_int8),
        ("diff_coast_level", c_int8), ("front_bump_damper_level", c_int8), ("front_rebound_damper_level", c_int8),
        ("rear_bump_damper_level", c_int8), ("rear_rebound_damper_level", c_int8), ("is_ignition_on", c_bool),
        ("is_pitlimiter_on", c_bool), ("active_performance_mode", c_int8), ("_reserved", c_byte * 88),
    ]


class Instrumentation(Structure):    # 128 bytes
    _pack_ = 4
    _fields_ = [
        ("main_light_stage", c_int8), ("special_light_stage", c_int8), ("cockpit_light_stage", c_int8),
        ("wiper_level", c_int8), ("rain_lights", c_bool), ("direction_light_left", c_bool),
        ("direction_light_right", c_bool), ("flashing_lights", c_bool), ("warning_lights", c_bool),
        ("selected_display_index", c_int8), ("display_current_page_index", c_int8 * 16),
        ("are_headlights_visible", c_bool), ("_reserved", c_byte * 101),
    ]


class SessionState(Structure):       # 256 bytes
    _pack_ = 4
    _fields_ = [
        ("phase_name", c_char * 33), ("time_left", c_char * 15), ("time_left_ms", c_int32),
        ("wait_time", c_char * 15), ("total_lap", c_int32), ("current_lap", c_int32), ("lights_on", c_int32),
        ("lights_mode", c_int32), ("lap_length_km", c_float), ("end_session_flag", c_int32),
        ("time_to_next_session", c_char * 15), ("disconnected_from_server", c_bool),
        ("restart_season_enabled", c_bool), ("ui_enable_drive", c_bool), ("ui_enable_setup", c_bool),
        ("is_ready_to_next_blinking", c_bool), ("show_waiting_for_players", c_bool), ("_reserved", c_byte * 140),
    ]


class TimingState(Structure):        # 256 bytes
    _pack_ = 4
    _fields_ = [
        ("current_laptime", c_char * 15), ("delta_current", c_char * 15), ("delta_current_p", c_int32),
        ("last_laptime", c_char * 15), ("delta_last", c_char * 15), ("delta_last_p", c_int32),
        ("best_laptime", c_char * 15), ("ideal_laptime", c_char * 15), ("total_time", c_char * 15),
        ("is_invalid", c_bool), ("_reserved", c_byte * 138),
    ]


class AssistsState(Structure):       # 64 bytes
    _pack_ = 4
    _fields_ = [
        ("auto_gear", c_uint8), ("auto_blip", c_uint8), ("auto_clutch", c_uint8), ("auto_clutch_on_start", c_uint8),
        ("manual_ignition_e_start", c_uint8), ("auto_pit_limiter", c_uint8), ("standing_start_assist", c_uint8),
        ("auto_steer", c_float), ("arcade_stability_control", c_float), ("_reserved", c_byte * 48),
    ]


class Graphics(Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int32), ("status", c_int32), ("focused_car_id_a", c_uint64), ("focused_car_id_b", c_uint64),
        ("player_car_id_a", c_uint64), ("player_car_id_b", c_uint64), ("rpm", c_uint16),
        ("is_rpm_limiter_on", c_bool), ("is_change_up_rpm", c_bool), ("is_change_down_rpm", c_bool),
        ("tc_active", c_bool), ("abs_active", c_bool), ("esc_active", c_bool), ("launch_active", c_bool),
        ("is_ignition_on", c_bool), ("is_engine_running", c_bool), ("kers_is_charging", c_bool),
        ("is_wrong_way", c_bool), ("is_drs_available", c_bool), ("battery_is_charging", c_bool),
        ("is_max_kj_per_lap_reached", c_bool), ("is_max_charge_kj_per_lap_reached", c_bool),
        ("display_speed_kmh", c_int16), ("display_speed_mph", c_int16), ("display_speed_ms", c_int16),
        ("pitspeeding_delta", c_float), ("gear_int", c_int16), ("rpm_percent", c_float), ("gas_percent", c_float),
        ("brake_percent", c_float), ("handbrake_percent", c_float), ("clutch_percent", c_float),
        ("steering_percent", c_float), ("ffb_strength", c_float), ("car_ffb_multiplier", c_float),
        ("water_temperature_percent", c_float), ("water_pressure_bar", c_float), ("fuel_pressure_bar", c_float),
        ("water_temperature_c", c_int8), ("air_temperature_c", c_int8), ("oil_temperature_c", c_float),
        ("oil_pressure_bar", c_float), ("exhaust_temperature_c", c_float), ("g_forces_x", c_float),
        ("g_forces_y", c_float), ("g_forces_z", c_float), ("turbo_boost", c_float), ("turbo_boost_level", c_float),
        ("turbo_boost_perc", c_float), ("steer_degrees", c_int32), ("current_km", c_float), ("total_km", c_uint32),
        ("total_driving_time_s", c_uint32), ("time_of_day_hours", c_int32), ("time_of_day_minutes", c_int32),
        ("time_of_day_seconds", c_int32), ("delta_time_ms", c_int32), ("current_lap_time_ms", c_int32),
        ("predicted_lap_time_ms", c_int32), ("fuel_liter_current_quantity", c_float),
        ("fuel_liter_current_quantity_percent", c_float), ("fuel_liter_per_km", c_float),
        ("km_per_fuel_liter", c_float), ("current_torque", c_float), ("current_bhp", c_int32),
        ("tyre_lf", TyreState), ("tyre_rf", TyreState), ("tyre_lr", TyreState), ("tyre_rr", TyreState),
        ("npos", c_float), ("kers_charge_perc", c_float), ("kers_current_perc", c_float),
        ("control_lock_time", c_float), ("car_damage", DamageState), ("car_location", c_int32),
        ("pit_info", PitInfo), ("fuel_liter_used", c_float), ("fuel_liter_per_lap", c_float),
        ("laps_possible_with_fuel", c_float), ("battery_temperature", c_float), ("battery_voltage", c_float),
        ("instantaneous_fuel_liter_per_km", c_float), ("instantaneous_km_per_fuel_liter", c_float),
        ("gear_rpm_window", c_float), ("instrumentation", Instrumentation),
        ("instrumentation_min_limit", Instrumentation), ("instrumentation_max_limit", Instrumentation),
        ("electronics", Electronics), ("electronics_min_limit", Electronics),
        ("electronics_max_limit", Electronics), ("electronics_is_modifiable", Electronics),
        ("total_lap_count", c_int32), ("current_pos", c_uint32), ("total_drivers", c_uint32),
        ("last_laptime_ms", c_int32), ("best_laptime_ms", c_int32), ("flag", c_int32), ("global_flag", c_int32),
        ("max_gears", c_uint32), ("engine_type", c_int32), ("has_kers", c_bool), ("is_last_lap", c_bool),
        ("performance_mode_name", c_char * 33), ("diff_coast_raw_value", c_float),
        ("diff_power_raw_value", c_float), ("race_cut_gained_time_ms", c_int32),
        ("distance_to_deadline", c_int32), ("race_cut_current_delta", c_float),
        ("session_state", SessionState), ("timing_state", TimingState), ("player_ping", c_int32),
        ("player_latency", c_int32), ("player_cpu_usage", c_int32), ("player_cpu_usage_avg", c_int32),
        ("player_qos", c_int32), ("player_qos_avg", c_int32), ("player_fps", c_int32),
        ("player_fps_avg", c_int32), ("driver_name", c_char * 33), ("driver_surname", c_char * 33),
        ("car_model", c_char * 33), ("is_in_pit_box", c_bool), ("is_in_pit_lane", c_bool),
        ("is_valid_lap", c_bool), ("car_coordinates", (c_float * 3) * 60), ("gap_ahead", c_float),
        ("gap_behind", c_float), ("active_cars", c_uint8), ("fuel_per_lap", c_float),
        ("fuel_estimated_laps", c_float), ("assists_state", AssistsState), ("max_fuel", c_float),
        ("max_turbo_boost", c_float), ("use_single_compound", c_bool),
        ("car_ids", (c_uint64 * 2) * 60),      # driver id per car_coordinates slot (lower, upper 64 bits)
    ]


def decode_text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").strip()


class SharedSource:
    """The game's three blocks, opened read-only. Anything with read() and close() is a source."""

    def __init__(self):
        self.blocks = []
        try:
            for tag, struct in ((PHYSICS_TAG, Physics), (GRAPHICS_TAG, Graphics), (STATIC_TAG, Static)):
                self.blocks.append(SharedMemory(tag, sizeof(struct)))
        except OSError:
            self.close()
            raise

    def read(self) -> tuple:
        """(physics_bytes, graphics_bytes, static_bytes)."""
        physics, graphics, static = (block.read() for block in self.blocks)
        return physics, graphics, static

    def close(self) -> None:
        for block in self.blocks:
            block.close()
        self.blocks = []


def open_source() -> SharedSource:
    """FileNotFoundError when the game's blocks do not exist (the game is not running)."""
    return SharedSource()


def padded(raw: bytes, struct) -> bytes:
    return bytes(raw)[:sizeof(struct)].ljust(sizeof(struct), b"\0")


def clean(value):
    """NaN and infinity become None, so every value is JSON-serialisable."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    return value


def to_degrees(values) -> list:
    return [math.degrees(v) for v in values]


def electronics_table(block) -> dict:
    table = {}
    for name, _ in Electronics._fields_:
        if not name.startswith("_"):
            value = getattr(block, name)
            table[name] = int(value) if isinstance(value, bool) else value
    return table


def channels(physics_bytes: bytes, graphics_bytes: bytes) -> dict:
    """Named readings, flat. Arrays are lists, front left, front right, rear left, rear right unless stated. Blocks shorter
    than their struct are zero-padded."""
    ph = Physics.from_buffer_copy(padded(physics_bytes, Physics))
    gr = Graphics.from_buffer_copy(padded(graphics_bytes, Graphics))
    el = gr.electronics
    tyres = (gr.tyre_lf, gr.tyre_rf, gr.tyre_lr, gr.tyre_rr)
    return clean({
        "rpm": ph.rpms,
        "rpm_max": ph.currentMaxRpm,
        "gas": ph.gas,
        "brake": ph.brake,
        "clutch": ph.clutch,
        "gear": ph.gear - 1,                    # ACE: 0 = R, 1 = N, 2 = 1st
        "speed_kmh": ph.speedKmh,
        "steer": ph.steerAngle,
        "steer_deg": gr.steer_degrees,
        "acc_g": list(ph.accG),
        "g_forces": [gr.g_forces_x, gr.g_forces_y, gr.g_forces_z],
        "angular_vel": list(ph.localAngularVel),
        "pitch_deg": math.degrees(ph.pitch),
        "roll_deg": math.degrees(ph.roll),
        "heading_deg": math.degrees(ph.heading),
        "wheel_load": list(ph.wheelLoad),
        "wheel_speed": list(ph.wheelAngularSpeed),
        "slip_ratio": list(ph.slipRatio),
        "slip_angle_deg": to_degrees(ph.slipAngle),
        "camber_deg": to_degrees(ph.camberRAD),
        "susp_travel": list(ph.suspensionTravel),
        "ride_height": list(ph.rideHeight),
        "tyre_pressure_psi": [t.tyre_pressure for t in tyres],
        "tyre_temp_core": [t.tyre_temperature_c for t in tyres],
        "tyre_temp_in": list(ph.tyreTempI),
        "tyre_temp_mid": list(ph.tyreTempM),
        "tyre_temp_out": list(ph.tyreTempO),
        "brake_temp": list(ph.brakeTemp),
        "brake_torque": list(ph.brakeTorque),
        "brake_bias": ph.brakeBias,
        "boost": gr.turbo_boost,
        "boost_max": gr.max_turbo_boost,
        "bhp": gr.current_bhp,
        "torque": gr.current_torque,
        "fuel_l": gr.fuel_liter_current_quantity,
        "fuel_max_l": gr.max_fuel,
        "max_gears": gr.max_gears,
        "tc_level": el.tc_level,
        "tc_cut_level": el.tc_cut_level,
        "abs_level": el.abs_level,
        "esc_level": el.esc_level,
        "ebb_level": el.ebb_level,
        "engine_map": el.engine_map_level,
        "diff_power_level": el.diff_power_level,
        "diff_coast_level": el.diff_coast_level,
        "turbo_level": el.turbo_level,
        "performance_mode": el.active_performance_mode,
        "performance_mode_name": decode_text(gr.performance_mode_name),
        "diff_power_pct": gr.diff_power_raw_value,
        "diff_coast_pct": gr.diff_coast_raw_value,
        "damper_levels": [el.front_bump_damper_level, el.front_rebound_damper_level,
                          el.rear_bump_damper_level, el.rear_rebound_damper_level],
        "tc_active": bool(gr.tc_active),
        "abs_active": bool(gr.abs_active),
        "esc_active": bool(gr.esc_active),
        "tc_in_action": int(ph.tcInAction),
        "abs_in_action": int(ph.absInAction),
        "engine_brake": ph.engineBrake,
        "tyre_compound_front": decode_text(gr.tyre_lf.tyre_compound_front),
        "tyre_compound_rear": decode_text(gr.tyre_lf.tyre_compound_rear),
        "cg_height": ph.cgHeight,
        "ballast": ph.ballast,
        "pad_life": list(ph.padLife),
        "disc_life": list(ph.discLife),
        "front_brake_compound": ph.frontBrakeCompound,
        "rear_brake_compound": ph.rearBrakeCompound,
        "electronics_min": electronics_table(gr.electronics_min_limit),
        "electronics_max": electronics_table(gr.electronics_max_limit),
        "electronics_modifiable": electronics_table(gr.electronics_is_modifiable),
    })


def session_info(graphics_bytes: bytes, static_bytes: bytes) -> dict:
    gr = Graphics.from_buffer_copy(padded(graphics_bytes, Graphics))
    st = Static.from_buffer_copy(padded(static_bytes, Static))
    return {
        "status": gr.status,
        "status_name": STATUS.get(gr.status, "unknown"),
        "car": decode_text(gr.car_model),
        "track": decode_text(st.track),
        "session_id": f"{st.event_id}-{st.session_id}-{st.session}-{decode_text(st.session_name)}",
        "game_version": decode_text(st.ac_evo_version),
        "layout_version": decode_text(st.sm_version),
        "packet": [gr.packetId],
    }


def packet_ids(physics_bytes: bytes, graphics_bytes: bytes) -> tuple:
    """(physics packetId, graphics packetId)."""
    ph = Physics.from_buffer_copy(padded(physics_bytes, Physics))
    gr = Graphics.from_buffer_copy(padded(graphics_bytes, Graphics))
    return ph.packetId, gr.packetId


def cmd_dump(wait: float) -> None:
    deadline = time.monotonic() + wait
    while True:
        try:
            source = open_source()
            break
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                sys.exit("error: the game is not running (no shared memory)")
            time.sleep(RETRY_S)
    try:
        physics, graphics, static = source.read()
    finally:
        source.close()
    print(json.dumps({"info": session_info(graphics, static), "channels": channels(physics, graphics)}, indent=2))


def usage():
    print(__doc__.split("\n\n")[1])
    sys.exit(2)


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        pos, opts = kspkg.parse_args(args, ("wait",))
        wait = float(opts.get("wait", 5))
    except ValueError:
        usage()
    if pos != ["dump"] or not wait >= 0:
        usage()
    if sys.platform != "win32":
        sys.exit("error: the session logger needs Windows (it reads the shared memory of Assetto Corsa EVO)")
    try:
        cmd_dump(wait)
    except OSError as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
