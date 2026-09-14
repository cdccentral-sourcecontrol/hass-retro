"""Button entities for Retro Gaming adapters."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up button entities for this adapter."""
    coordinator: RetroCoordinator = entry.runtime_data
    async_add_entities(
        [
            RetroBackupButton(coordinator, entry),
            RetroRefreshButton(coordinator, entry),
        ]
    )


class _RetroButtonBase(CoordinatorEntity[RetroCoordinator], ButtonEntity):
    """Base button for retro adapter devices."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_DEVICE_ADDRESS])},
            "name": entry.data[CONF_DEVICE_NAME],
            "manufacturer": "BlueRetro" if "blueretro" in entry.data.get("adapter_type", "") else "Unknown",
            "model": entry.data.get(CONF_CONSOLE_TYPE, "unknown").upper(),
        }


class RetroBackupButton(_RetroButtonBase):
    """Button to trigger a config backup from the adapter."""

    _attr_translation_key = "backup"
    _attr_icon = "mdi:content-save"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the backup button."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_backup"

    async def async_press(self) -> None:
        """Trigger a backup of the adapter config."""
        LOGGER.info("Backing up config for %s", self.coordinator.device_name)
        try:
            backup = await self.coordinator.async_backup()
            # Fire an event with the backup data so automations can persist it
            self.hass.bus.async_fire(
                f"{DOMAIN}_backup_complete",
                {
                    "device_name": self.coordinator.device_name,
                    "device_address": self.coordinator.device_address,
                    "backup": backup,
                },
            )
            LOGGER.info("Backup complete for %s", self.coordinator.device_name)
        except Exception as err:
            LOGGER.error("Backup failed for %s: %s", self.coordinator.device_name, err)
            raise


class RetroRefreshButton(_RetroButtonBase):
    """Button to force a status refresh from the adapter."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_refresh"

    async def async_press(self) -> None:
        """Force an immediate data refresh."""
        LOGGER.info("Refreshing %s", self.coordinator.device_name)
        await self.coordinator.async_request_refresh()
