"""Custom profile storage for Retro Gaming adapters.

Uses homeassistant.helpers.storage.Store for atomic async persistence.
Data is stored in /config/.storage/retro_custom_profiles.

Schema:
    {
        "devices": {
            "<entry_id>": {
                "profiles": {
                    "<name>": {
                        "description": "...",
                        "mappings": [...],
                        "created": "YYYYMMDD_HHMMSS",
                        "source": "auto" | "user",
                        "src_controller": "ps5" | "xbox" | "switch_pro"
                    }
                },
                "last_known_profile": "string | null"
            }
        }
    }
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, LOGGER

STORAGE_KEY = f"{DOMAIN}_custom_profiles"
STORAGE_VERSION = 1
MAX_CUSTOM_PROFILES_PER_DEVICE = 20

_EMPTY_STORE: dict[str, Any] = {"devices": {}}


def _get_store(hass: HomeAssistant) -> Store:
    """Get or create the Store instance (cached on hass.data)."""
    store_key = f"{DOMAIN}_profiles_store"
    if store_key not in hass.data:
        hass.data[store_key] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    return hass.data[store_key]


async def _async_load(hass: HomeAssistant) -> dict[str, Any]:
    """Load profile data, migrating from legacy file if needed."""
    store = _get_store(hass)
    data = await store.async_load()
    if data is not None:
        return data

    # One-time migration from legacy /config/retro_backups/custom_profiles.json
    legacy_path = Path(hass.config.config_dir) / "retro_backups" / "custom_profiles.json"
    if legacy_path.exists():
        try:
            legacy_data = json.loads(await hass.async_add_executor_job(legacy_path.read_text))
            await store.async_save(legacy_data)
            await hass.async_add_executor_job(legacy_path.unlink)
            LOGGER.info("Migrated custom profiles from %s to Store", legacy_path)
            return legacy_data
        except (json.JSONDecodeError, OSError) as err:
            LOGGER.error("Failed to migrate legacy custom profiles: %s", err)

    return _EMPTY_STORE.copy()


async def _async_save(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Save profile data atomically via Store."""
    store = _get_store(hass)
    await store.async_save(data)


async def async_save_custom_profile(
    hass: HomeAssistant,
    entry_id: str,
    name: str,
    mappings: list[dict[str, Any]],
    description: str = "",
    source: str = "auto",
    src_controller: str = "ps5",
) -> str:
    """Save a custom profile for a device. Returns the profile name."""
    data = await _async_load(hass)

    if "devices" not in data:
        data["devices"] = {}
    if entry_id not in data["devices"]:
        data["devices"][entry_id] = {"profiles": {}}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    data["devices"][entry_id]["profiles"][name] = {
        "description": description,
        "mappings": mappings,
        "created": timestamp,
        "source": source,
        "src_controller": src_controller,
    }

    # Trim oldest auto-saved profiles if over max
    profiles = data["devices"][entry_id]["profiles"]
    auto_profiles = {k: v for k, v in profiles.items() if v.get("source") == "auto"}
    if len(auto_profiles) > MAX_CUSTOM_PROFILES_PER_DEVICE:
        sorted_auto = sorted(auto_profiles.items(), key=lambda x: x[1].get("created", ""))
        to_remove = len(auto_profiles) - MAX_CUSTOM_PROFILES_PER_DEVICE
        for k, _ in sorted_auto[:to_remove]:
            del profiles[k]

    await _async_save(hass, data)
    LOGGER.info("Saved custom profile '%s' for entry %s", name, entry_id)
    return name


async def async_list_custom_profiles(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """List all custom profiles for a device (name -> metadata without full mappings)."""
    data = await _async_load(hass)
    profiles = data.get("devices", {}).get(entry_id, {}).get("profiles", {})
    return {
        name: {"description": p.get("description", ""), "created": p.get("created", ""), "source": p.get("source", "")}
        for name, p in profiles.items()
    }


async def async_get_custom_profile(hass: HomeAssistant, entry_id: str, name: str) -> dict[str, Any] | None:
    """Get a custom profile's full data (including mappings)."""
    data = await _async_load(hass)
    profiles = data.get("devices", {}).get(entry_id, {}).get("profiles", {})
    return profiles.get(name)


async def async_delete_custom_profile(hass: HomeAssistant, entry_id: str, name: str) -> bool:
    """Delete a custom profile. Returns True if deleted."""
    data = await _async_load(hass)
    profiles = data.get("devices", {}).get(entry_id, {}).get("profiles", {})
    if name in profiles:
        del profiles[name]
        await _async_save(hass, data)
        LOGGER.info("Deleted custom profile '%s' for entry %s", name, entry_id)
        return True
    return False


async def async_get_last_known_profile(hass: HomeAssistant, entry_id: str) -> str | None:
    """Get the last known active profile for a device (persists across restarts)."""
    data = await _async_load(hass)
    return data.get("devices", {}).get(entry_id, {}).get("last_known_profile")


async def async_set_last_known_profile(hass: HomeAssistant, entry_id: str, profile_name: str) -> None:
    """Persist the last known active profile for a device."""
    data = await _async_load(hass)
    if "devices" not in data:
        data["devices"] = {}
    if entry_id not in data["devices"]:
        data["devices"][entry_id] = {"profiles": {}}
    data["devices"][entry_id]["last_known_profile"] = profile_name
    await _async_save(hass, data)
