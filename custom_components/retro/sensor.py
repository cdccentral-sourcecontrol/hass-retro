"""Sensor entities for Retro Gaming adapters."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONSOLE_TYPE, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN
from .coordinator import RetroCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for this adapter."""
    coordinator: RetroCoordinator = entry.runtime_data
    async_add_entities(
        [
            RetroStatusSensor(coordinator, entry),
            RetroFirmwareSensor(coordinator, entry),
        ]
    )


class _RetroSensorBase(CoordinatorEntity[RetroCoordinator], SensorEntity):
    """Base sensor for retro adapter devices."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_DEVICE_ADDRESS])},
            "name": entry.data[CONF_DEVICE_NAME],
            "manufacturer": "BlueRetro" if "blueretro" in entry.data.get("adapter_type", "") else "Unknown",
            "model": entry.data.get(CONF_CONSOLE_TYPE, "unknown").upper(),
        }


class RetroStatusSensor(_RetroSensorBase):
    """Sensor showing adapter connection status."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_status"

    @property
    def native_value(self) -> str:
        """Return the connection status."""
        if self.coordinator.data and self.coordinator.data.get("connected"):
            return "connected"
        return "disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return additional state attributes."""
        attrs: dict[str, str | int | None] = {
            "adapter_type": self.coordinator.adapter_type,
            "console_type": self.coordinator.console_type,
            "active_profile": self.coordinator.active_profile,
        }
        if self.coordinator.data and self.coordinator.data.get("mapping"):
            attrs["mapping_count"] = self.coordinator.data["mapping"].get("map_size", 0)
        return attrs


class RetroFirmwareSensor(_RetroSensorBase):
    """Sensor showing adapter firmware version."""

    _attr_translation_key = "firmware"
    _attr_icon = "mdi:chip"
    _attr_entity_registry_enabled_default = True

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the firmware sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_firmware"

    @property
    def native_value(self) -> str | None:
        """Return the firmware version."""
        return self.coordinator.firmware
