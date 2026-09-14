"""Constants for the Retro Gaming integration."""

from __future__ import annotations

import logging
from enum import StrEnum

LOGGER = logging.getLogger(__package__)
DOMAIN = "retro"

# ---------------------------------------------------------------------------
# Adapter types — each has its own protocol handler in adapters/
# ---------------------------------------------------------------------------

class AdapterType(StrEnum):
    """Supported retro adapter hardware types."""

    BLUERETRO = "blueretro"
    # Future:
    # EIGHTBITDO = "8bitdo"
    # RAPHNET = "raphnet"


# ---------------------------------------------------------------------------
# Console types — determines which profile set is available
# ---------------------------------------------------------------------------

class ConsoleType(StrEnum):
    """Console systems supported by retro adapters."""

    N64 = "n64"
    SNES = "snes"
    NES = "nes"
    GENESIS = "genesis"
    SATURN = "saturn"
    PSX = "psx"
    GAMECUBE = "gamecube"
    DREAMCAST = "dreamcast"
    JAGUAR = "jaguar"
    PCE = "pce"
    THREE_DO = "3do"
    CDI = "cdi"
    PCFX = "pcfx"
    VIRTUAL_BOY = "virtual_boy"
    WII_EXT = "wii_ext"
    JVS = "jvs"
    PARALLEL_1P = "parallel_1p"
    PARALLEL_2P = "parallel_2p"


CONSOLE_FRIENDLY_NAMES: dict[str, str] = {
    ConsoleType.N64: "Nintendo 64",
    ConsoleType.SNES: "Super Nintendo",
    ConsoleType.NES: "NES",
    ConsoleType.GENESIS: "Sega Genesis",
    ConsoleType.SATURN: "Sega Saturn",
    ConsoleType.PSX: "PlayStation",
    ConsoleType.GAMECUBE: "GameCube",
    ConsoleType.DREAMCAST: "Dreamcast",
    ConsoleType.JAGUAR: "Atari Jaguar",
    ConsoleType.PCE: "PC Engine / TG16",
    ConsoleType.THREE_DO: "3DO",
    ConsoleType.CDI: "CD-i",
    ConsoleType.PCFX: "PC-FX",
    ConsoleType.VIRTUAL_BOY: "Virtual Boy",
    ConsoleType.WII_EXT: "Wii Extension",
    ConsoleType.JVS: "JVS (Arcade)",
    ConsoleType.PARALLEL_1P: "Parallel 1P (NeoGeo)",
    ConsoleType.PARALLEL_2P: "Parallel 2P (Atari/SMS)",
}

# ---------------------------------------------------------------------------
# BlueRetro BLE GATT UUIDs
# Base UUID: 56830f56-5180-fab0-314b-2fa176799a00
# ---------------------------------------------------------------------------

BR_SERVICE_UUID = "56830f56-5180-fab0-314b-2fa176799a00"
BR_GLOBAL_CFG_UUID = "56830f56-5180-fab0-314b-2fa176799a01"
BR_OUT_CFG_CTRL_UUID = "56830f56-5180-fab0-314b-2fa176799a02"
BR_OUT_CFG_DATA_UUID = "56830f56-5180-fab0-314b-2fa176799a03"
BR_IN_CFG_CTRL_UUID = "56830f56-5180-fab0-314b-2fa176799a04"
BR_IN_CFG_DATA_UUID = "56830f56-5180-fab0-314b-2fa176799a05"
BR_CFG_CMD_UUID = "56830f56-5180-fab0-314b-2fa176799a07"

# Config commands
CFG_CMD_GET_FW_VER = 0x02

# ---------------------------------------------------------------------------
# Config entry data keys
# ---------------------------------------------------------------------------

CONF_ADAPTER_TYPE = "adapter_type"
CONF_CONSOLE_TYPE = "console_type"
CONF_DEVICE_ADDRESS = "device_address"
CONF_DEVICE_NAME = "device_name"

# ---------------------------------------------------------------------------
# Options (configurable per-device in Settings → Devices → Configure)
# ---------------------------------------------------------------------------

OPT_POLL_INTERVAL = "poll_interval"
OPT_KEEP_ALIVE = "keep_alive"
OPT_AUTO_BACKUP = "auto_backup_on_profile_change"
OPT_INQUIRY_MODE = "inquiry_mode"

# Defaults
DEFAULT_POLL_INTERVAL = 5  # minutes
DEFAULT_KEEP_ALIVE = True
DEFAULT_AUTO_BACKUP = True
DEFAULT_INQUIRY_MODE = "auto"  # "auto" or "manual"

# ---------------------------------------------------------------------------
# Entity platforms to set up per config entry
# ---------------------------------------------------------------------------

PLATFORMS: list[str] = ["select", "sensor", "button"]

# ---------------------------------------------------------------------------
# Button name lookup tables for human-readable mapping display.
# Keys are BlueRetro generic button IDs (0-based).
# Source = PS5 DualSense controller, Destination = per-console.
# ---------------------------------------------------------------------------

# Generic source names (PS5 DualSense / modern gamepad)
SRC_BUTTON_NAMES: dict[int, str] = {
    0: "Left Stick X",
    1: "Left Stick Y",
    2: "Right Stick X",
    3: "Right Stick Y",
    4: "L Stick X→Btn",
    5: "L Stick Y→Btn",
    6: "R Stick X→Btn",
    7: "R Stick Y→Btn",
    8: "D-pad Left",
    9: "D-pad Right",
    10: "D-pad Down",
    11: "D-pad Up",
    12: "L3 Left",
    13: "L3 Right",
    14: "L3 Down",
    15: "L3 Up",
    16: "Square",
    17: "Circle",
    18: "Cross",
    19: "Triangle",
    20: "Start",
    21: "Select",
    24: "L2",
    25: "L1",
    28: "R2",
    29: "R1",
}

# Per-console destination names
DST_BUTTON_NAMES: dict[str, dict[int, str]] = {
    "n64": {
        0: "Stick X",
        1: "Stick Y",
        2: "Stick X (alt)",
        3: "Stick Y (alt)",
        8: "D-pad Left",
        9: "D-pad Right",
        10: "D-pad Down",
        11: "D-pad Up",
        12: "C-Left",
        13: "C-Right",
        14: "C-Down",
        15: "C-Up",
        16: "B",
        17: "—",
        18: "A",
        19: "—",
        20: "Start",
        24: "Z",
        25: "L",
        29: "R",
    },
    # Future consoles can be added here
}
