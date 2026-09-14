"""Persistent backup storage for Retro Gaming adapter configs.

Uses homeassistant.helpers.storage.Store for atomic async persistence.
Data is stored in /config/.storage/retro_backups.

Storage schema (v2):
    {
        "devices": {
            "<entry_id>": {
                "device_name": "...",
                "device_address": "AA:BB:CC:DD:EE:FF",
                "backups": [ { "timestamp": "...", "label": "...", "data": {...} } ]
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

STORAGE_KEY = f"{DOMAIN}_backups"
STORAGE_VERSION = 2
MAX_BACKUPS_PER_DEVICE = 10

_EMPTY_STORE: dict[str, Any] = {"devices": {}}


def _get_store(hass: HomeAssistant) -> Store:
    """Get or create the Store instance (cached on hass.data)."""
    store_key = f"{DOMAIN}_backup_store"
    if store_key not in hass.data:
        hass.data[store_key] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    return hass.data[store_key]


async def _async_load(hass: HomeAssistant) -> dict[str, Any]:
    """Load backup data, migrating from legacy file if needed."""
    store = _get_store(hass)
    data = await store.async_load()
    if data is not None:
        return data

    # One-time migration from legacy /config/retro_backups/backups.json
    legacy_path = Path(hass.config.config_dir) / "retro_backups" / "backups.json"
    if legacy_path.exists():
        try:
            legacy_data = json.loads(await hass.async_add_executor_job(legacy_path.read_text))
            await store.async_save(legacy_data)
            await hass.async_add_executor_job(legacy_path.unlink)
            LOGGER.info("Migrated backup data from %s to Store", legacy_path)
            return legacy_data
        except (json.JSONDecodeError, OSError) as err:
            LOGGER.error("Failed to migrate legacy backups: %s", err)

    return _EMPTY_STORE.copy()


async def _async_save(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Save backup data atomically via Store."""
    store = _get_store(hass)
    await store.async_save(data)


async def async_migrate_if_needed(
    hass: HomeAssistant, entry_id: str, device_address: str
) -> None:
    """Migrate v1 MAC-keyed data to v2 entry_id key (one-time, idempotent)."""
    data = await _async_load(hass)
    devices = data.get("devices", {})

    if entry_id in devices:
        return

    old_key = device_address.replace(":", "").lower()
    if old_key in devices:
        LOGGER.info(
            "Migrating backup data from MAC key '%s' -> entry_id '%s'",
            old_key,
            entry_id,
        )
        devices[entry_id] = devices.pop(old_key)
        await _async_save(hass, data)


async def async_has_backup(hass: HomeAssistant, entry_id: str) -> bool:
    """Check if any backup exists for a device."""
    data = await _async_load(hass)
    backups = data.get("devices", {}).get(entry_id, {}).get("backups", [])
    return len(backups) > 0


async def async_save_backup(
    hass: HomeAssistant,
    entry_id: str,
    device_name: str,
    device_address: str,
    backup_data: dict[str, Any],
    label: str = "manual",
) -> str:
    """Save a backup for a device. Returns the timestamp label."""
    data = await _async_load(hass)

    if "devices" not in data:
        data["devices"] = {}
    if entry_id not in data["devices"]:
        data["devices"][entry_id] = {
            "device_name": device_name,
            "device_address": device_address,
            "backups": [],
        }
    else:
        data["devices"][entry_id]["device_name"] = device_name
        data["devices"][entry_id]["device_address"] = device_address

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    entry = {
        "timestamp": timestamp,
        "label": label,
        "data": backup_data,
    }

    data["devices"][entry_id]["backups"].append(entry)

    # Trim to max - keep most recent
    if len(data["devices"][entry_id]["backups"]) > MAX_BACKUPS_PER_DEVICE:
        data["devices"][entry_id]["backups"] = data["devices"][entry_id]["backups"][
            -MAX_BACKUPS_PER_DEVICE:
        ]

    await _async_save(hass, data)
    LOGGER.info(
        "Saved backup '%s' (%s) for %s [entry=%s]",
        label,
        timestamp,
        device_name,
        entry_id,
    )
    return timestamp


async def async_get_latest_backup(hass: HomeAssistant, entry_id: str) -> dict[str, Any] | None:
    """Get the most recent backup for a device."""
    data = await _async_load(hass)
    backups = data.get("devices", {}).get(entry_id, {}).get("backups", [])
    if not backups:
        return None
    return backups[-1]


async def async_list_backups(hass: HomeAssistant, entry_id: str) -> list[dict[str, Any]]:
    """List all backups for a device (without full data, just metadata)."""
    data = await _async_load(hass)
    backups = data.get("devices", {}).get(entry_id, {}).get("backups", [])
    return [
        {"timestamp": b["timestamp"], "label": b["label"]}
        for b in backups
    ]


async def async_get_backup_by_timestamp(
    hass: HomeAssistant, entry_id: str, timestamp: str
) -> dict[str, Any] | None:
    """Get a specific backup by timestamp."""
    data = await _async_load(hass)
    backups = data.get("devices", {}).get(entry_id, {}).get("backups", [])
    for b in backups:
        if b["timestamp"] == timestamp:
            return b
    return None


async def async_delete_backup(
    hass: HomeAssistant, entry_id: str, timestamp: str
) -> bool:
    """Delete a backup by timestamp. Returns True if deleted."""
    data = await _async_load(hass)
    backups = data.get("devices", {}).get(entry_id, {}).get("backups", [])
    original_len = len(backups)
    data["devices"][entry_id]["backups"] = [
        b for b in backups if b["timestamp"] != timestamp
    ]
    if len(data["devices"][entry_id]["backups"]) < original_len:
        await _async_save(hass, data)
        LOGGER.info("Deleted backup '%s' for entry %s", timestamp, entry_id)
        return True
    return False
