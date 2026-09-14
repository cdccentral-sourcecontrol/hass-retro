"""Data update coordinator for Retro Gaming devices."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .adapters import BaseAdapter
from .adapters.blueretro import BlueRetroAdapter
from .backup import async_has_backup, async_migrate_if_needed, async_save_backup
from .custom_profiles import (
    async_get_custom_profile,
    async_get_last_known_profile,
    async_list_custom_profiles,
    async_save_custom_profile,
    async_set_last_known_profile,
)
from .const import (
    CONF_ADAPTER_TYPE,
    CONF_CONSOLE_TYPE,
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    LOGGER,
    OPT_AUTO_BACKUP,
    OPT_KEEP_ALIVE,
    OPT_POLL_INTERVAL,
    AdapterType,
)

PROFILES_DIR = Path(__file__).parent / "profiles"

REPO_URL = "https://github.com/cdccentral-sourcecontrol/hass-retro"


class RetroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for a single retro adapter device.

    Manages BLE connection lifecycle, profile loading, and state updates.
    """

    def __init__(
        self, hass: HomeAssistant, entry_id: str, entry_data: dict[str, Any], options: dict[str, Any]
    ) -> None:
        """Initialize the coordinator."""
        poll_minutes = options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{entry_data[CONF_DEVICE_NAME]}",
            update_interval=timedelta(minutes=poll_minutes),
        )
        self._entry_id = entry_id
        self._entry_data = entry_data
        self._options = options
        self._adapter: BaseAdapter = self._create_adapter()
        self._profiles: dict[str, Any] = {}
        self._active_profile: str | None = None
        self._last_known_profile: str | None = None
        self._firmware: str | None = None
        self._baseline_checked = False
        self._has_backup = False

    @property
    def entry_id(self) -> str:
        """Return the config entry ID (stable device key for storage)."""
        return self._entry_id

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
        """Return list of available profile names, sorted alphabetically."""
        return sorted(self._profiles.keys())

    @property
    def active_profile(self) -> str | None:
        """Return the name of the currently active profile.

        Falls back to _last_known_profile if current mapping doesn't match
        any profile (e.g., after custom edits).
        """
        return self._active_profile or self._last_known_profile

    @property
    def last_known_profile(self) -> str | None:
        """Return the last known base profile (persists across restarts)."""
        return self._last_known_profile

    @property
    def firmware(self) -> str | None:
        """Return cached firmware version."""
        return self._firmware

    @property
    def has_backup(self) -> bool:
        """Return whether a backup exists for this device."""
        return self._has_backup

    @property
    def keep_alive(self) -> bool:
        """Return whether keep-alive is enabled."""
        from .const import DEFAULT_KEEP_ALIVE  # noqa: PLC0415
        return self._options.get(OPT_KEEP_ALIVE, DEFAULT_KEEP_ALIVE)

    @property
    def auto_backup_on_profile_change(self) -> bool:
        """Return whether auto-backup on profile change is enabled."""
        from .const import DEFAULT_AUTO_BACKUP  # noqa: PLC0415
        return self._options.get(OPT_AUTO_BACKUP, DEFAULT_AUTO_BACKUP)

    def _create_adapter(self) -> BaseAdapter:
        """Create the appropriate adapter for the device type."""
        adapter_type = self._entry_data[CONF_ADAPTER_TYPE]
        if adapter_type == AdapterType.BLUERETRO:
            return BlueRetroAdapter(self.hass, self._entry_data[CONF_DEVICE_ADDRESS])
        raise ValueError(f"Unsupported adapter type: {adapter_type}")

    async def _async_load_profiles(self) -> None:
        """Load built-in + custom profiles for this device's console type."""
        console = self._entry_data[CONF_CONSOLE_TYPE]
        profile_file = PROFILES_DIR / f"{console}.json"
        if not profile_file.exists():
            LOGGER.warning("No profiles found for console type: %s", console)
            return
        try:
            raw = await self.hass.async_add_executor_job(profile_file.read_text)
            data = json.loads(raw)
            self._profiles = data.get("profiles", {})
        except (json.JSONDecodeError, OSError) as err:
            LOGGER.error("Failed to load profiles for %s: %s", console, err)
            return

        # Merge custom profiles with display-friendly names.
        # Storage keys are like "custom_default" → display as "default (custom)"
        custom = await async_list_custom_profiles(self.hass, self._entry_id)
        for name in custom:
            full = await async_get_custom_profile(self.hass, self._entry_id, name)
            if full and "mappings" in full:
                display_name = self._custom_display_name(name)
                self._profiles[display_name] = {
                    "description": full.get("description", "Custom profile"),
                    "mappings": full["mappings"],
                    "_storage_key": name,  # Track original key for lookups
                }

        LOGGER.info(
            "Loaded %d profiles for %s (%d custom)",
            len(self._profiles),
            console,
            len(custom),
        )

    async def async_setup(self) -> None:
        """Load profiles and run backup migration (must be called from async context)."""
        await self._async_load_profiles()
        # Restore persisted last-known profile from storage
        self._last_known_profile = await async_get_last_known_profile(
            self.hass, self._entry_id
        )
        # Migrate v1 MAC-keyed backups to v2 entry_id key (one-time, idempotent)
        await async_migrate_if_needed(
            self.hass, self._entry_id, self.device_address
        )

    async def _maybe_take_baseline(self) -> None:
        """Take an automatic baseline backup if none exists for this device.

        Called while adapter is already connected during poll.
        """
        exists = await async_has_backup(self.hass, self._entry_id)
        if exists:
            self._has_backup = True
            LOGGER.debug("Baseline exists for %s, skipping", self.device_name)
            return

        LOGGER.info(
            "No backup exists for %s — taking automatic baseline",
            self.device_name,
        )
        try:
            # Use adapter directly — we're already connected in _async_update_data
            backup_data = await self._adapter.async_backup()
            await async_save_backup(
                self.hass,
                self._entry_id,
                self.device_name,
                self.device_address,
                backup_data,
                "baseline",
            )
            self._has_backup = True
            LOGGER.info("Baseline backup saved for %s", self.device_name)
        except Exception as err:
            LOGGER.warning(
                "Failed to take baseline backup for %s: %s",
                self.device_name,
                err,
            )

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
                        LOGGER.info("Firmware: %s", self._firmware)
                    except Exception:  # noqa: BLE001
                        self._firmware = "unknown"

                mapping = await self._adapter.async_read_mapping()
                LOGGER.debug(
                    "Polled %s: %d mappings active",
                    self.device_name,
                    mapping.get("map_size", 0),
                )

                # Try to identify active profile from mapping data
                detected = self._match_profile(mapping)
                if detected:
                    if detected != self._active_profile:
                        LOGGER.info(
                            "Detected active profile '%s' on %s",
                            detected,
                            self.device_name,
                        )
                    self._active_profile = detected
                    # Persist last-known for survival across restarts
                    if detected != self._last_known_profile:
                        self._last_known_profile = detected
                        await async_set_last_known_profile(
                            self.hass, self._entry_id, detected
                        )

                # Auto-baseline: take a backup on first successful read
                # if no backup exists yet for this device.
                if not self._baseline_checked:
                    self._baseline_checked = True
                    await self._maybe_take_baseline()

                return {
                    "firmware": self._firmware,
                    "mapping": mapping,
                    "connected": True,
                    "active_profile": self._active_profile,
                }
            finally:
                await self._adapter.async_disconnect()

        except Exception as err:
            LOGGER.debug("Poll failed for %s: %s", self.device_name, err)

            # Keep-alive: retry once after a short delay
            if self.keep_alive:
                await asyncio.sleep(3)
                try:
                    await self._adapter.async_connect()
                    try:
                        mapping = await self._adapter.async_read_mapping()
                        detected = self._match_profile(mapping)
                        if detected:
                            self._active_profile = detected
                        LOGGER.info("Keep-alive retry succeeded for %s", self.device_name)
                        return {
                            "firmware": self._firmware,
                            "mapping": mapping,
                            "connected": True,
                            "active_profile": self._active_profile,
                        }
                    finally:
                        await self._adapter.async_disconnect()
                except Exception as retry_err:
                    LOGGER.debug("Keep-alive retry also failed: %s", retry_err)

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

    @staticmethod
    def _custom_display_name(storage_key: str) -> str:
        """Convert a custom profile storage key to a display name.

        'custom_default' → 'default (custom)'
        'custom_my_setup' → 'my_setup (custom)'
        """
        base = storage_key.removeprefix("custom_") if storage_key.startswith("custom_") else storage_key
        return f"{base} (custom)"

    @staticmethod
    def _custom_storage_key(display_name: str) -> str:
        """Convert a display name back to a storage key.

        'default (custom)' → 'custom_default'
        """
        if display_name.endswith(" (custom)"):
            base = display_name[: -len(" (custom)")]
            return f"custom_{base}"
        return display_name

    def _match_profile(self, mapping: dict[str, Any]) -> str | None:
        """Try to identify which profile matches the current device mapping.

        Compares the non-combo portion of the active mapping against each
        known profile's expected mappings. Returns profile name or None.
        """
        if not mapping or not mapping.get("mappings"):
            return None

        from .adapters.blueretro import COMBO_MAPPINGS

        # Strip combo mappings from the readback — they're appended
        # by write_mapping and are the same for every profile.
        n_combo = len(COMBO_MAPPINGS)
        device_maps = mapping["mappings"]
        if len(device_maps) > n_combo:
            profile_maps = device_maps[: len(device_maps) - n_combo]
        else:
            profile_maps = device_maps

        for name, profile in self._profiles.items():
            expected = [self._normalize_mapping(m) for m in profile["mappings"]]
            if len(expected) != len(profile_maps):
                continue
            match = all(
                pm.get("src_btn") == em["src_btn"]
                and pm.get("dst_btn") == em["dst_btn"]
                for pm, em in zip(profile_maps, expected)
            )
            if match:
                return name
        return None

    async def async_apply_profile(self, profile_name: str) -> None:
        """Connect and write a mapping profile to the adapter.

        After write, the device reboots. We poll every 2s for up to 1 minute
        until we can reconnect and verify the mapping was saved.
        """
        if profile_name not in self._profiles:
            raise ValueError(
                f"Unknown profile '{profile_name}'. "
                f"Available: {self.profile_names}"
            )

        profile = self._profiles[profile_name]
        mappings = [self._normalize_mapping(m) for m in profile["mappings"]]

        LOGGER.info(
            "Applying profile '%s' (%d mappings) to %s",
            profile_name,
            len(mappings),
            self.device_name,
        )

        # Phase 1: Connect and write
        try:
            await self._adapter.async_connect()
            LOGGER.info("Connected to %s for profile write", self.device_name)
        except Exception as err:
            LOGGER.error("Cannot connect to %s: %s", self.device_name, err)
            raise UpdateFailed(
                f"Failed to connect for profile '{profile_name}': {err}"
            ) from err

        # Auto-save current mapping as custom profile before overwriting
        if self.auto_backup_on_profile_change:
            try:
                current_mapping = await self._adapter.async_read_mapping()
                if current_mapping and current_mapping.get("mappings"):
                    from .adapters.blueretro import COMBO_MAPPINGS  # noqa: PLC0415
                    # Strip combo mappings — only save the game-specific part
                    n_combo = len(COMBO_MAPPINGS)
                    all_maps = current_mapping["mappings"]
                    if len(all_maps) > n_combo:
                        game_maps = all_maps[: len(all_maps) - n_combo]
                    else:
                        game_maps = all_maps

                    # Name it after the detected profile — stored as custom_<name>
                    current_name = self._active_profile or self._last_known_profile or "manual"
                    # If currently on a custom profile, use its storage key
                    if current_name.endswith(" (custom)"):
                        save_name = self._custom_storage_key(current_name)
                    else:
                        save_name = f"custom_{current_name}"
                    await async_save_custom_profile(
                        self.hass,
                        self._entry_id,
                        save_name,
                        game_maps,
                        f"Auto-saved before switching to {profile_name}",
                        "auto",
                    )
                    # Reload profiles so the new custom profile appears immediately
                    await self._async_load_profiles()
                    LOGGER.info(
                        "Auto-saved current mapping as '%s' before applying '%s'",
                        save_name,
                        profile_name,
                    )
            except Exception as err:
                LOGGER.warning("Auto-save profile failed (continuing): %s", err)

        try:
            await self._adapter.async_write_mapping(mappings)
            self._active_profile = profile_name
            # Persist so it survives restarts even if edits make it unmatchable
            self._last_known_profile = profile_name
            await async_set_last_known_profile(
                self.hass, self._entry_id, profile_name
            )
            LOGGER.info(
                "Write sent for profile '%s' — device rebooting",
                profile_name,
            )
        except Exception as err:
            LOGGER.error("Write failed for '%s': %s", profile_name, err)
            if self._adapter.is_connected:
                await self._adapter.async_disconnect()
            raise UpdateFailed(
                f"Failed to write profile '{profile_name}': {err}"
            ) from err

        # Phase 2: Post-write verification poll — check every 2s for 1 min
        # The write_mapping may have already reconnected and verified.
        # If adapter is still connected, verify immediately.
        if self._adapter.is_connected:
            LOGGER.info("Still connected after write — verifying immediately")
            try:
                readback = await self._adapter.async_read_mapping()
                detected = self._match_profile(readback)
                LOGGER.info(
                    "Immediate verify: %d mappings, detected profile='%s'",
                    readback.get("map_size", 0),
                    detected,
                )
                await self._adapter.async_disconnect()
                self.async_set_updated_data({
                    "firmware": self._firmware,
                    "mapping": readback,
                    "connected": True,
                    "active_profile": self._active_profile,
                })
                return
            except Exception as err:
                LOGGER.debug("Immediate verify failed: %s", err)
                try:
                    await self._adapter.async_disconnect()
                except Exception:
                    pass

        # Device rebooted — poll until it comes back
        LOGGER.info(
            "Polling for %s reboot (every 2s, up to 60s)...",
            self.device_name,
        )
        verified = False
        for attempt in range(30):
            await asyncio.sleep(2)
            try:
                await self._adapter.async_connect()
                LOGGER.info(
                    "Reconnected on attempt %d/%d — verifying",
                    attempt + 1,
                    30,
                )
                readback = await self._adapter.async_read_mapping()
                detected = self._match_profile(readback)
                LOGGER.info(
                    "Verified: %d mappings, profile='%s' (expected '%s')",
                    readback.get("map_size", 0),
                    detected,
                    profile_name,
                )
                await self._adapter.async_disconnect()
                self.async_set_updated_data({
                    "firmware": self._firmware,
                    "mapping": readback,
                    "connected": True,
                    "active_profile": self._active_profile,
                })
                verified = True
                break
            except Exception as err:
                LOGGER.debug(
                    "Poll attempt %d/%d: %s", attempt + 1, 30, err
                )
                try:
                    await self._adapter.async_disconnect()
                except Exception:
                    pass

        if not verified:
            LOGGER.warning(
                "Could not verify profile '%s' after 60s — "
                "device may still be rebooting or unreachable",
                profile_name,
            )
            self.async_set_updated_data({
                "firmware": self._firmware,
                "mapping": None,
                "connected": False,
                "active_profile": self._active_profile,
            })

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
        await self.async_request_refresh()

    async def async_factory_reset(self) -> None:
        """Write factory default identity mappings (all src==dst).

        This resets the adapter to the same state as a hardware factory
        reset (BOOT button hold 10s). All 63 standard button slots mapped
        1:1 with deadzone=135, max=100, threshold=50.
        """
        # Build 63 identity mappings matching BlueRetro factory defaults
        factory_mappings = [
            {
                "src_btn": i,
                "dst_btn": i,
                "dst_id": 0,
                "perc_max": 100,
                "perc_threshold": 50,
                "perc_deadzone": 135,
                "turbo": 0,
                "algo": 0,
            }
            for i in range(63)
        ]

        LOGGER.info(
            "Factory reset: writing %d identity mappings to %s",
            len(factory_mappings),
            self.device_name,
        )
        try:
            await self._adapter.async_connect()
            try:
                await self._adapter.async_write_mapping(factory_mappings)
                self._active_profile = None
            finally:
                if self._adapter.is_connected:
                    await self._adapter.async_disconnect()
        except Exception as err:
            raise UpdateFailed(f"Factory reset failed: {err}") from err
        await self.async_request_refresh()

    async def async_save_current_as_profile(
        self, name: str, description: str = "", src_controller: str = "ps5"
    ) -> str:
        """Read current mapping from adapter and save as a named custom profile.

        The name should be a storage key (e.g. 'custom_default').
        Returns the display name (e.g. 'default (custom)').
        """
        from .adapters.blueretro import COMBO_MAPPINGS  # noqa: PLC0415

        # Ensure storage key has custom_ prefix
        if not name.startswith("custom_"):
            name = f"custom_{name}"

        try:
            await self._adapter.async_connect()
            try:
                mapping = await self._adapter.async_read_mapping()
            finally:
                await self._adapter.async_disconnect()
        except Exception as err:
            raise UpdateFailed(f"Cannot read mapping: {err}") from err

        if not mapping or not mapping.get("mappings"):
            raise UpdateFailed("No mapping data read from adapter")

        # Strip combo mappings
        n_combo = len(COMBO_MAPPINGS)
        all_maps = mapping["mappings"]
        if len(all_maps) > n_combo:
            game_maps = all_maps[: len(all_maps) - n_combo]
        else:
            game_maps = all_maps

        saved_name = await async_save_custom_profile(
            self.hass,
            self._entry_id,
            name,
            game_maps,
            description or f"User-saved profile ({len(game_maps)} mappings)",
            "user",
            src_controller,
        )

        # Reload profiles so it appears in the select immediately
        await self._async_load_profiles()
        self.async_set_updated_data(self.data)

        return self._custom_display_name(saved_name)

    async def async_write_custom_mapping(self, mappings: list[dict[str, Any]]) -> None:
        """Write a full set of game mappings to the adapter.

        Combo mappings are appended automatically by the adapter layer.
        After write, device reboots and we poll for reconnection.
        """
        LOGGER.info(
            "Writing custom mapping (%d entries) to %s",
            len(mappings),
            self.device_name,
        )
        try:
            await self._adapter.async_connect()
            try:
                await self._adapter.async_write_mapping(mappings)
                self._active_profile = None  # No longer a known profile
            finally:
                if self._adapter.is_connected:
                    await self._adapter.async_disconnect()
        except Exception as err:
            raise UpdateFailed(f"Write mapping failed: {err}") from err
        await self.async_request_refresh()
