"""The Retro Gaming integration."""

from __future__ import annotations

import shutil
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, intent

from .const import DOMAIN, LOGGER, PLATFORMS
from .coordinator import RetroCoordinator
from .custom_profiles import async_delete_custom_profile
from .dashboard import async_deploy_dashboard, async_update_dashboard_config
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

    # Register service calls
    _register_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: RetroConfigEntry) -> bool:
    """Set up a Retro Gaming adapter from a config entry."""
    coordinator = RetroCoordinator(hass, entry.entry_id, dict(entry.data), dict(entry.options))

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

    # Listen for options changes (poll interval, keep-alive, etc.)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    LOGGER.info("Retro adapter '%s' set up", entry.title)

    # Rebuild dashboard to include this device
    entry.async_create_background_task(
        hass, async_update_dashboard_config(hass), "retro_dashboard_update"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: RetroConfigEntry) -> bool:
    """Unload a Retro Gaming adapter config entry."""
    if coordinator := entry.runtime_data:
        if coordinator.adapter.is_connected:
            await coordinator.adapter.async_disconnect()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: RetroConfigEntry) -> None:
    """Handle options update — reload the entry to apply new settings."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Register retro.save_profile and retro.delete_profile services."""

    async def _handle_save_profile(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        name = call.data["name"]
        description = call.data.get("description", "")
        src_controller = call.data.get("src_controller", "ps5")

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ValueError(f"Config entry '{entry_id}' not found for {DOMAIN}")

        coordinator: RetroCoordinator = entry.runtime_data
        saved = await coordinator.async_save_current_as_profile(name, description, src_controller)
        LOGGER.info("Service save_profile: saved '%s' for %s", saved, coordinator.device_name)

    async def _handle_delete_profile(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        name = call.data["name"]

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ValueError(f"Config entry '{entry_id}' not found for {DOMAIN}")

        deleted = await async_delete_custom_profile(hass, entry_id, name)
        if deleted:
            coordinator: RetroCoordinator = entry.runtime_data
            await coordinator._async_load_profiles()
            coordinator.async_set_updated_data(coordinator.data)
            LOGGER.info("Service delete_profile: deleted '%s'", name)
        else:
            LOGGER.warning("Service delete_profile: '%s' not found", name)

    async def _handle_set_mapping(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        mappings = call.data["mappings"]

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ValueError(f"Config entry '{entry_id}' not found for {DOMAIN}")

        coordinator: RetroCoordinator = entry.runtime_data
        await coordinator.async_write_custom_mapping(mappings)
        LOGGER.info("Service set_mapping: wrote %d mappings to %s", len(mappings), coordinator.device_name)

    hass.services.async_register(
        DOMAIN,
        "save_profile",
        _handle_save_profile,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("description", default=""): cv.string,
                vol.Optional("src_controller", default="ps5"): vol.In(
                    ["ps5", "xbox", "switch_pro"]
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "delete_profile",
        _handle_delete_profile,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("name"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_mapping",
        _handle_set_mapping,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("mappings"): vol.All(
                    cv.ensure_list,
                    [
                        vol.Schema(
                            {
                                vol.Required("src_btn"): vol.Coerce(int),
                                vol.Required("dst_btn"): vol.Coerce(int),
                                vol.Optional("dst_id", default=0): vol.Coerce(int),
                                vol.Optional("perc_max", default=100): vol.Coerce(int),
                                vol.Optional("perc_threshold", default=50): vol.Coerce(int),
                                vol.Optional("perc_deadzone", default=15): vol.Coerce(int),
                                vol.Optional("turbo", default=0): vol.Coerce(int),
                                vol.Optional("algo", default=0): vol.Coerce(int),
                            }
                        )
                    ],
                ),
            }
        ),
    )

    LOGGER.info("Registered retro.save_profile, retro.delete_profile, and retro.set_mapping services")


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
