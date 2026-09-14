"""The Retro Gaming integration."""

from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN, LOGGER, PLATFORMS
from .coordinator import RetroCoordinator
from .dashboard import async_deploy_dashboard
from .intents import SetRetroProfileIntent

type RetroConfigEntry = ConfigEntry[RetroCoordinator]

_INTENT_REGISTERED = f"{DOMAIN}_intent_registered"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Retro Gaming integration (YAML — registers intent handler)."""
    # Register the intent handler once (shared across all config entries)
    if _INTENT_REGISTERED not in hass.data:
        intent.async_register(hass, SetRetroProfileIntent())
        hass.data[_INTENT_REGISTERED] = True
        LOGGER.info("Registered SetRetroProfile intent handler")

    # Auto-deploy custom sentences to /config/custom_sentences/en/
    await hass.async_add_executor_job(_deploy_sentences, hass)

    # Auto-deploy dashboard, custom card, and lovelace resource
    await async_deploy_dashboard(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: RetroConfigEntry) -> bool:
    """Set up a Retro Gaming adapter from a config entry."""
    coordinator = RetroCoordinator(hass, dict(entry.data))

    # Load profiles (async file I/O)
    await coordinator.async_setup()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Schedule a non-blocking initial refresh — BLE devices may be
    # unreachable at boot (rebooting, powered off, controller connected).
    # Don't block HA startup waiting for a BLE timeout.
    entry.async_create_background_task(
        hass, coordinator.async_request_refresh(), "retro_initial_refresh"
    )

    LOGGER.info("Retro adapter '%s' set up", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RetroConfigEntry) -> bool:
    """Unload a Retro Gaming adapter config entry."""
    if coordinator := entry.runtime_data:
        if coordinator.adapter.is_connected:
            await coordinator.adapter.async_disconnect()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _deploy_sentences(hass: HomeAssistant) -> None:
    """Deploy bundled custom_sentences to HA config dir if not present.

    Copies sentences/en/retro.yaml → /config/custom_sentences/en/retro.yaml.
    This enables the default conversation agent to recognize our intents
    without requiring manual user file deployment.
    """
    source_dir = Path(__file__).parent / "sentences" / "en"
    target_dir = Path(hass.config.config_dir) / "custom_sentences" / "en"

    if not source_dir.exists():
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    for src_file in source_dir.glob("*.yaml"):
        dst_file = target_dir / src_file.name
        if not dst_file.exists():
            shutil.copy2(src_file, dst_file)
            LOGGER.info("Deployed sentence file: %s", dst_file)
        else:
            # Update if bundled version is newer (check mtime)
            if src_file.stat().st_mtime > dst_file.stat().st_mtime:
                shutil.copy2(src_file, dst_file)
                LOGGER.info("Updated sentence file: %s", dst_file)
