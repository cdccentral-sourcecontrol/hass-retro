"""Data update coordinator for Retro Gaming devices."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .adapters import BaseAdapter
from .adapters.blueretro import BlueRetroAdapter
from .const import (
    CONF_ADAPTER_TYPE,
    CONF_CONSOLE_TYPE,
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    DOMAIN,
    LOGGER,
    AdapterType,
)

SCAN_INTERVAL = timedelta(minutes=5)
PROFILES_DIR = Path(__file__).parent / "profiles"


class RetroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for a single retro adapter device.

    Manages BLE connection lifecycle, profile loading, and state updates.
    """

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any]) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{entry_data[CONF_DEVICE_NAME]}",
            update_interval=SCAN_INTERVAL,
        )
        self._entry_data = entry_data
        self._adapter: BaseAdapter = self._create_adapter()
        self._profiles: dict[str, Any] = {}
        self._active_profile: str | None = None
        self._firmware: str | None = None

    @property
    def adapter(self) -> BaseAdapter:
        """Return the protocol adapter."""
        return self._adapter

    @property
    def device_name(self) -> str:
        """Return the user-friendly device name."""
        return self._entry_data[CONF_DEVICE_NAME]

    @property
    def device_address(self) -> str:
        """Return the device BLE/USB address."""
        return self._entry_data[CONF_DEVICE_ADDRESS]

    @property
    def adapter_type(self) -> str:
        """Return the adapter type string."""
        return self._entry_data[CONF_ADAPTER_TYPE]

    @property
    def console_type(self) -> str:
        """Return the console type string."""
        return self._entry_data[CONF_CONSOLE_TYPE]

    @property
    def profiles(self) -> dict[str, Any]:
        """Return loaded profiles for this device's console type."""
        return self._profiles

    @property
    def profile_names(self) -> list[str]:
        """Return list of available profile names."""
        return list(self._profiles.keys())

    @property
    def active_profile(self) -> str | None:
        """Return the name of the currently active profile."""
        return self._active_profile

    @property
    def firmware(self) -> str | None:
        """Return cached firmware version."""
        return self._firmware

    def _create_adapter(self) -> BaseAdapter:
        """Create the appropriate adapter for the device type."""
        adapter_type = self._entry_data[CONF_ADAPTER_TYPE]
        if adapter_type == AdapterType.BLUERETRO:
            return BlueRetroAdapter(self.hass, self._entry_data[CONF_DEVICE_ADDRESS])
        raise ValueError(f"Unsupported adapter type: {adapter_type}")

    def _load_profiles(self) -> None:
        """Load profiles for this device's console type from JSON."""
        console = self._entry_data[CONF_CONSOLE_TYPE]
        profile_file = PROFILES_DIR / f"{console}.json"
        if not profile_file.exists():
            LOGGER.warning("No profiles found for console type: %s", console)
            return
        try:
            data = json.loads(profile_file.read_text())
            self._profiles = data.get("profiles", {})
            LOGGER.info(
                "Loaded %d profiles for %s", len(self._profiles), console
            )
        except (json.JSONDecodeError, OSError) as err:
            LOGGER.error("Failed to load profiles for %s: %s", console, err)

    async def async_setup(self) -> None:
        """Load profiles (must be called from async context)."""
        await self.hass.async_add_executor_job(self._load_profiles)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the adapter.

        This runs on the polling interval. BLE connection is ephemeral —
        connect, read, disconnect to free the GATT slot.
        """
        try:
            await self._adapter.async_connect()
            try:
                # Read firmware if not cached
                if self._firmware is None:
                    try:
                        self._firmware = await self._adapter.async_read_firmware()
                    except Exception:  # noqa: BLE001
                        self._firmware = "unknown"

                mapping = await self._adapter.async_read_mapping()
                return {
                    "firmware": self._firmware,
                    "mapping": mapping,
                    "connected": True,
                    "active_profile": self._active_profile,
                }
            finally:
                await self._adapter.async_disconnect()

        except Exception as err:
            LOGGER.debug("Update failed for %s: %s", self.device_name, err)
            return {
                "firmware": self._firmware,
                "mapping": None,
                "connected": False,
                "active_profile": self._active_profile,
            }

    @staticmethod
    def _normalize_mapping(m: dict[str, Any]) -> dict[str, Any]:
        """Normalize profile mapping keys to adapter format.

        Profile JSON uses short keys (src/dst) for readability.
        Adapter expects src_btn/dst_btn/dst_id/perc_max/etc.
        """
        return {
            "src_btn": m.get("src_btn", m.get("src", 0)),
            "dst_btn": m.get("dst_btn", m.get("dst", 0)),
            "dst_id": m.get("dst_id", 0),
            "perc_max": m.get("perc_max", 100),
            "perc_threshold": m.get("perc_threshold", 50),
            "perc_deadzone": m.get("perc_deadzone", 15),
            "turbo": m.get("turbo", 0),
            "algo": m.get("algo", 0),
        }

    async def async_apply_profile(self, profile_name: str) -> None:
        """Connect and write a mapping profile to the adapter."""
        if profile_name not in self._profiles:
            raise ValueError(
                f"Unknown profile '{profile_name}'. "
                f"Available: {self.profile_names}"
            )

        profile = self._profiles[profile_name]
        mappings = [self._normalize_mapping(m) for m in profile["mappings"]]

        try:
            await self._adapter.async_connect()
            try:
                await self._adapter.async_write_mapping(mappings)
                self._active_profile = profile_name
                LOGGER.info(
                    "Applied profile '%s' to %s",
                    profile_name,
                    self.device_name,
                )
            finally:
                await self._adapter.async_disconnect()
        except Exception as err:
            raise UpdateFailed(
                f"Failed to apply profile '{profile_name}': {err}"
            ) from err

        # Trigger an immediate refresh so entities update
        await self.async_request_refresh()

    async def async_backup(self) -> dict[str, Any]:
        """Connect, read full config, disconnect. Returns backup dict."""
        try:
            await self._adapter.async_connect()
            try:
                return await self._adapter.async_backup()
            finally:
                await self._adapter.async_disconnect()
        except Exception as err:
            raise UpdateFailed(f"Backup failed: {err}") from err

    async def async_restore(self, backup: dict[str, Any]) -> None:
        """Connect, write full config, disconnect."""
        try:
            await self._adapter.async_connect()
            try:
                await self._adapter.async_restore(backup)
            finally:
                await self._adapter.async_disconnect()
        except Exception as err:
            raise UpdateFailed(f"Restore failed: {err}") from err
