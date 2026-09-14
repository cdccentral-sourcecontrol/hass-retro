"""Profile and backup select entities for Retro Gaming adapters."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backup import async_list_backups
from .const import CONF_CONSOLE_TYPE, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN, LOGGER
from .coordinator import REPO_URL, RetroCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities for this adapter."""
    coordinator: RetroCoordinator = entry.runtime_data
    async_add_entities([
        RetroProfileSelect(coordinator, entry),
        RetroBackupSelect(coordinator, entry),
    ])


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
            "configuration_url": REPO_URL,
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


class RetroBackupSelect(CoordinatorEntity[RetroCoordinator], SelectEntity):
    """Select entity for choosing a backup to restore."""

    _attr_has_entity_name = True
    _attr_translation_key = "backup_select"
    _attr_icon = "mdi:backup-restore"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the backup select entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_backup_select"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_DEVICE_ADDRESS])},
            "name": entry.data[CONF_DEVICE_NAME],
            "manufacturer": "BlueRetro" if "blueretro" in entry.data.get("adapter_type", "") else "Unknown",
            "model": entry.data.get(CONF_CONSOLE_TYPE, "unknown").upper(),
            "configuration_url": REPO_URL,
        }
        self._selected: str | None = None
        self._cached_options: list[str] = []

    async def _async_refresh_options(self) -> list[str]:
        """Build option list from backup store."""
        backups = await async_list_backups(self.hass, self._entry.entry_id)
        # Format: "label (timestamp)" — newest first
        return [f"{b['label']} ({b['timestamp']})" for b in reversed(backups)]

    async def async_added_to_hass(self) -> None:
        """Load options when entity is added."""
        await super().async_added_to_hass()
        self._cached_options = await self._async_refresh_options()
        # Default to latest (first in list, since newest-first)
        if self._cached_options and not self._selected:
            self._selected = self._cached_options[0]

    def _handle_coordinator_update(self) -> None:
        """Refresh options on every coordinator update."""
        self.hass.async_create_task(self._async_do_refresh())
        super()._handle_coordinator_update()

    async def _async_do_refresh(self) -> None:
        """Refresh options from store."""
        self._cached_options = await self._async_refresh_options()
        if self._selected and self._selected not in self._cached_options:
            self._selected = None
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        """Return list of available backups."""
        return self._cached_options

    @property
    def current_option(self) -> str | None:
        """Return the currently selected backup."""
        return self._selected

    async def async_select_option(self, option: str) -> None:
        """Select a backup (does not restore — just selects it)."""
        self._selected = option
        self.async_write_ha_state()

    @property
    def selected_timestamp(self) -> str | None:
        """Extract timestamp from selected option for restore use."""
        if not self._selected:
            return None
        # Format is "label (YYYYMMDD_HHMMSS)"
        try:
            return self._selected.rsplit("(", 1)[1].rstrip(")")
        except (IndexError, AttributeError):
            return None
