"""BlueRetro BLE GATT adapter protocol handler.

Implements BaseAdapter for BlueRetro ESP32-based retro controller adapters.
Communicates via BLE GATT characteristics through HA's bluetooth proxy.
"""

from __future__ import annotations

import struct
from typing import Any

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection
from bluetooth_data_tools import short_address
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
)
from homeassistant.core import HomeAssistant

from ..const import (
    BR_CFG_CMD_UUID,
    BR_GLOBAL_CFG_UUID,
    BR_IN_CFG_CTRL_UUID,
    BR_IN_CFG_DATA_UUID,
    BR_OUT_CFG_CTRL_UUID,
    BR_OUT_CFG_DATA_UUID,
    CFG_CMD_GET_FW_VER,
    LOGGER,
)
from . import BaseAdapter

# Scaling algorithms
ALGO_LINEAR = 0
ALGO_PASSTHROUGH = 5

# BlueRetro combo function base button ID
COMBO_BASE_1 = 118

# Button IDs (subset used for combo mappings)
PAD_LM = 24   # Z / L2 / LT
PAD_RM = 28   # R2 / RT
PAD_MM = 20   # Start
PAD_RB_UP = 19     # Triangle / X
PAD_RB_LEFT = 16   # Square / Y / B(N64)
PAD_RB_DOWN = 18   # Cross / A
PAD_RB_RIGHT = 17  # Circle / B

# System combo mappings appended to every profile write
COMBO_MAPPINGS = [
    {"src_btn": PAD_LM, "dst_btn": COMBO_BASE_1, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
    {"src_btn": PAD_RM, "dst_btn": COMBO_BASE_1 + 1, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
    {"src_btn": PAD_MM, "dst_btn": COMBO_BASE_1 + 2, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
    {"src_btn": PAD_RB_UP, "dst_btn": COMBO_BASE_1 + 3, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
    {"src_btn": PAD_RB_LEFT, "dst_btn": COMBO_BASE_1 + 4, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
    {"src_btn": PAD_RB_DOWN, "dst_btn": COMBO_BASE_1 + 6, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
    {"src_btn": PAD_RB_RIGHT, "dst_btn": COMBO_BASE_1 + 5, "dst_id": 0,
     "perc_max": 100, "perc_threshold": 50, "perc_deadzone": 15, "turbo": 0, "algo": ALGO_PASSTHROUGH},
]


def _pack_map_entry(entry: dict[str, int]) -> bytes:
    """Pack a single map_cfg struct (8 bytes)."""
    return struct.pack(
        "BBBBBBBB",
        entry["src_btn"],
        entry["dst_btn"],
        entry.get("dst_id", 0),
        entry.get("perc_max", 100),
        entry.get("perc_threshold", 50),
        entry.get("perc_deadzone", 15),
        entry.get("turbo", 0),
        entry.get("algo", ALGO_LINEAR),
    )


def _unpack_map_entry(data: bytes) -> dict[str, int]:
    """Unpack 8 bytes into a map_cfg dict."""
    s, d, did, pm, pt, pd, t, a = struct.unpack("BBBBBBBB", data[:8])
    return {
        "src_btn": s, "dst_btn": d, "dst_id": did,
        "perc_max": pm, "perc_threshold": pt, "perc_deadzone": pd,
        "turbo": t, "algo": a,
    }


def _pack_in_cfg(bt_dev_id: int, bt_subdev_id: int, mappings: list[dict]) -> bytes:
    """Pack full in_cfg: 3-byte header + N*8-byte mappings."""
    header = struct.pack("BBB", bt_dev_id, bt_subdev_id, len(mappings))
    body = b"".join(_pack_map_entry(m) for m in mappings)
    return header + body


def _unpack_in_cfg(data: bytes) -> dict[str, Any]:
    """Unpack in_cfg binary data into structured dict."""
    bt_dev_id, bt_subdev_id, map_size = struct.unpack("BBB", data[:3])
    mappings = []
    for i in range(map_size):
        offset = 3 + i * 8
        if offset + 8 <= len(data):
            mappings.append(_unpack_map_entry(data[offset : offset + 8]))
    return {
        "bt_dev_id": bt_dev_id,
        "bt_subdev_id": bt_subdev_id,
        "map_size": map_size,
        "mappings": mappings,
    }


class BlueRetroAdapter(BaseAdapter):
    """BlueRetro BLE GATT protocol handler.

    Connects to a BlueRetro ESP32 adapter through HA's bluetooth proxy.
    Constraint: no BT controller can be connected during config writes.
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialize the adapter."""
        self._hass = hass
        self._address = address
        self._client = None
        self._firmware: str | None = None

    @property
    def is_connected(self) -> bool:
        """Return True if BLE client is connected."""
        return self._client is not None and self._client.is_connected

    @property
    def firmware(self) -> str | None:
        """Return cached firmware version."""
        return self._firmware

    async def async_connect(self) -> None:
        """Establish BLE GATT connection through HA bluetooth proxy."""
        ble_device = async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )
        if ble_device is None:
            raise BleakError(
                f"BlueRetro device {self._address} not found. "
                "Is it powered on with no controller connected?"
            )

        self._client = await establish_connection(
            BleakClient,
            ble_device,
            f"retro_{short_address(self._address)}",
            ble_device_callback=lambda: async_ble_device_from_address(
                self._hass, self._address, connectable=True
            ),
        )
        LOGGER.info("Connected to BlueRetro at %s", self._address)

    async def async_disconnect(self) -> None:
        """Disconnect BLE client."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None

    async def async_read_firmware(self) -> str:
        """Read firmware version via CFG_CMD characteristic."""
        if not self.is_connected:
            raise BleakError("Not connected")
        await self._client.write_gatt_char(
            BR_CFG_CMD_UUID, bytes([CFG_CMD_GET_FW_VER])
        )
        data = await self._client.read_gatt_char(BR_CFG_CMD_UUID)
        self._firmware = data.decode("utf-8", errors="replace").rstrip("\x00")
        return self._firmware

    async def async_read_mapping(self, device_id: int = 0) -> dict[str, Any]:
        """Read current input (mapping) config from the adapter."""
        if not self.is_connected:
            raise BleakError("Not connected")
        ctrl_data = struct.pack("<HH", device_id, 0)
        await self._client.write_gatt_char(BR_IN_CFG_CTRL_UUID, ctrl_data)
        data = await self._client.read_gatt_char(BR_IN_CFG_DATA_UUID)
        return _unpack_in_cfg(data)

    async def async_write_mapping(
        self, mappings: list[dict[str, Any]], device_id: int = 0
    ) -> None:
        """Write a mapping profile to the adapter.

        Appends system combo mappings automatically.
        BlueRetro reboots after saving — disconnect during write is expected.
        """
        if not self.is_connected:
            raise BleakError("Not connected")

        full_mappings = list(mappings) + COMBO_MAPPINGS

        ctrl_data = struct.pack("<HH", device_id, 0)
        await self._client.write_gatt_char(BR_IN_CFG_CTRL_UUID, ctrl_data)

        in_cfg_data = _pack_in_cfg(0, 0, full_mappings)
        LOGGER.info(
            "Writing %d mappings (%d bytes) to device %d",
            len(full_mappings),
            len(in_cfg_data),
            device_id,
        )

        # BlueRetro reboots immediately after saving config.
        # The device disconnects before sending a GATT write-response,
        # causing a BleakError. This is expected behaviour.
        try:
            await self._client.write_gatt_char(
                BR_IN_CFG_DATA_UUID, in_cfg_data, response=True
            )
            LOGGER.info("Write completed without disconnect")
        except BleakError as err:
            err_str = str(err).lower()
            if "changed connection status" in err_str or "disconnected" in err_str:
                LOGGER.info(
                    "Device rebooted after config write (expected): %s", err
                )
                self._client = None
            else:
                raise

    async def async_backup(self) -> dict[str, Any]:
        """Read full config for backup."""
        if not self.is_connected:
            raise BleakError("Not connected")

        # Global config
        global_data = await self._client.read_gatt_char(BR_GLOBAL_CFG_UUID)
        global_cfg = {
            "system_cfg": global_data[0] if len(global_data) > 0 else 0,
            "multitap_cfg": global_data[1] if len(global_data) > 1 else 0,
            "inquiry_mode": global_data[2] if len(global_data) > 2 else 0,
            "banksel": global_data[3] if len(global_data) > 3 else 0,
        }

        # Output config
        ctrl_data = struct.pack("<H", 0)
        await self._client.write_gatt_char(BR_OUT_CFG_CTRL_UUID, ctrl_data)
        out_data = await self._client.read_gatt_char(BR_OUT_CFG_DATA_UUID)
        out_cfg = {
            "dev_mode": out_data[0] if len(out_data) > 0 else 0,
            "acc_mode": out_data[1] if len(out_data) > 1 else 0,
        }

        # Input mapping
        in_cfg = await self.async_read_mapping(device_id=0)

        # Firmware
        fw = "unknown"
        try:
            fw = await self.async_read_firmware()
        except Exception:  # noqa: BLE001
            pass

        return {
            "address": self._address,
            "firmware": fw,
            "global_cfg": global_cfg,
            "out_cfg": out_cfg,
            "in_cfg": in_cfg,
        }

    async def async_restore(self, backup: dict[str, Any]) -> None:
        """Restore config from a backup dict."""
        if not self.is_connected:
            raise BleakError("Not connected")

        # Restore global config
        if "global_cfg" in backup:
            g = backup["global_cfg"]
            global_data = struct.pack(
                "BBBB",
                g["system_cfg"],
                g["multitap_cfg"],
                g["inquiry_mode"],
                g["banksel"],
            )
            await self._client.write_gatt_char(
                BR_GLOBAL_CFG_UUID, global_data, response=True
            )

        # Restore output config
        if "out_cfg" in backup:
            ctrl_data = struct.pack("<H", 0)
            await self._client.write_gatt_char(BR_OUT_CFG_CTRL_UUID, ctrl_data)
            o = backup["out_cfg"]
            out_data = struct.pack("BB", o["dev_mode"], o["acc_mode"])
            await self._client.write_gatt_char(
                BR_OUT_CFG_DATA_UUID, out_data, response=True
            )

        # Restore input mappings (without re-appending combos — backup has them)
        if "in_cfg" in backup:
            ic = backup["in_cfg"]
            ctrl_data = struct.pack("<HH", 0, 0)
            await self._client.write_gatt_char(BR_IN_CFG_CTRL_UUID, ctrl_data)
            in_cfg_data = _pack_in_cfg(
                ic.get("bt_dev_id", 0),
                ic.get("bt_subdev_id", 0),
                ic["mappings"],
            )
            await self._client.write_gatt_char(
                BR_IN_CFG_DATA_UUID, in_cfg_data, response=True
            )

        LOGGER.info("Config restored from backup")
