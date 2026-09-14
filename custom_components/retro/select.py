"""Profile select entity for Retro Gaming adapters."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONSOLE_TYPE, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN, LOGGER
from .coordinator import RetroCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up profile select entity for this adapter."""
    coordinator: RetroCoordinator = entry.runtime_data
    async_add_entities([RetroProfileSelect(coordinator, entry)])


class RetroProfileSelect(CoordinatorEntity[RetroCoordinator], SelectEntity):
    """Select entity for choosing a controller mapping profile."""

    _attr_has_entity_name = True
    _attr_translation_key = "profile"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the profile select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_profile"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_DEVICE_ADDRESS])},
            "name": entry.data[CONF_DEVICE_NAME],
            "manufacturer": "BlueRetro" if "blueretro" in entry.data.get("adapter_type", "") else "Unknown",
            "model": entry.data.get(CONF_CONSOLE_TYPE, "unknown").upper(),
        }

    @property
    def options(self) -> list[str]:
        """Return list of available profiles."""
        return self.coordinator.profile_names

    @property
    def current_option(self) -> str | None:
        """Return the currently active profile."""
        return self.coordinator.active_profile

    async def async_select_option(self, option: str) -> None:
        """Apply the selected profile to the adapter."""
        LOGGER.info("Applying profile '%s' to %s", option, self.coordinator.device_name)
        await self.coordinator.async_apply_profile(option)
