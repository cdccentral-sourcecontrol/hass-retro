"""Button entities for Retro Gaming adapters."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backup import async_delete_backup, async_save_backup
from .const import CONF_CONSOLE_TYPE, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN, LOGGER
from .coordinator import REPO_URL, RetroCoordinator


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
            RetroRestoreButton(coordinator, entry),
            RetroSaveProfileButton(coordinator, entry),
            RetroDeleteBackupButton(coordinator, entry),
            RetroFactoryResetButton(coordinator, entry),
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
            "configuration_url": REPO_URL,
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
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_backup"

    async def async_press(self) -> None:
        """Backup adapter config to persistent storage."""
        LOGGER.info("Backing up config for %s", self.coordinator.device_name)
        try:
            backup_data = await self.coordinator.async_backup()
            # Save to persistent storage (keyed by entry_id)
            timestamp = await async_save_backup(
                self.hass,
                self._entry.entry_id,
                self.coordinator.device_name,
                self.coordinator.device_address,
                backup_data,
                "manual",
            )
            # Also fire event for automations
            self.hass.bus.async_fire(
                f"{DOMAIN}_backup_complete",
                {
                    "device_name": self.coordinator.device_name,
                    "device_address": self.coordinator.device_address,
                    "entry_id": self._entry.entry_id,
                    "timestamp": timestamp,
                    "label": "manual",
                },
            )
            LOGGER.info(
                "Backup saved for %s (timestamp: %s)",
                self.coordinator.device_name,
                timestamp,
            )
        except Exception as err:
            LOGGER.error("Backup failed for %s: %s", self.coordinator.device_name, err)
            raise


class RetroRestoreButton(_RetroButtonBase):
    """Button to restore adapter config from selected or latest backup."""

    _attr_translation_key = "restore"
    _attr_icon = "mdi:backup-restore"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the restore button."""
        super().__init__(coordinator, entry)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_restore"

    @property
    def available(self) -> bool:
        """Only available if coordinator reports a backup exists."""
        return self.coordinator.has_backup

    async def async_press(self) -> None:
        """Restore the selected backup (or latest if none selected)."""
        from .backup import async_get_backup_by_timestamp, async_get_latest_backup  # noqa: PLC0415

        # Check if backup_select entity has a selection
        select_entity_id = f"select.{self._entry.data[CONF_DEVICE_NAME].lower().replace(' ', '_')}_{self._entry.data[CONF_DEVICE_ADDRESS].replace(':', '').lower()}_backup_select"
        # Try to find the backup select entity in the entity registry
        backup = None
        state = self.hass.states.get(select_entity_id)
        if state and state.state not in ("unknown", "unavailable", "", None):
            # Parse timestamp from the selected option "label (YYYYMMDD_HHMMSS)"
            try:
                timestamp = state.state.rsplit("(", 1)[1].rstrip(")")
                backup = await async_get_backup_by_timestamp(
                    self.hass,
                    self._entry.entry_id,
                    timestamp,
                )
            except (IndexError, AttributeError):
                pass

        # Fallback to latest
        if backup is None:
            backup = await async_get_latest_backup(
                self.hass,
                self._entry.entry_id,
            )

        if backup is None:
            LOGGER.error("No backup found for %s", self.coordinator.device_name)
            return

        LOGGER.info(
            "Restoring backup '%s' (%s) to %s",
            backup["label"],
            backup["timestamp"],
            self.coordinator.device_name,
        )
        try:
            await self.coordinator.async_restore(backup["data"])
            LOGGER.info(
                "Restore complete for %s from %s",
                self.coordinator.device_name,
                backup["timestamp"],
            )
        except Exception as err:
            LOGGER.error("Restore failed for %s: %s", self.coordinator.device_name, err)
            raise


class RetroSaveProfileButton(_RetroButtonBase):
    """Button to save the current adapter mapping as a custom profile."""

    _attr_translation_key = "save_profile"
    _attr_icon = "mdi:content-save-plus"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the save profile button."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_save_profile"

    async def async_press(self) -> None:
        """Save current mapping as a custom profile.

        Uses the active profile name prefixed with 'custom_',
        or 'custom_manual' if no profile is detected.
        """
        active = self.coordinator.active_profile or "manual"
        # If already on a custom profile, reuse its storage key
        if active.endswith(" (custom)"):
            name = self.coordinator._custom_storage_key(active)
        else:
            name = f"custom_{active}"
        LOGGER.info("Saving current mapping as custom profile '%s'", name)
        try:
            saved = await self.coordinator.async_save_current_as_profile(name)
            self.hass.bus.async_fire(
                f"{DOMAIN}_profile_saved",
                {
                    "device_name": self.coordinator.device_name,
                    "profile_name": saved,
                    "entry_id": self.coordinator.entry_id,
                },
            )
            LOGGER.info("Custom profile '%s' saved", saved)
        except Exception as err:
            LOGGER.error("Save profile failed: %s", err)
            raise


class RetroDeleteBackupButton(_RetroButtonBase):
    """Button to delete the currently selected backup restore point."""

    _attr_translation_key = "delete_backup"
    _attr_icon = "mdi:delete"
    _attr_name = "Delete Backup"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the delete backup button."""
        super().__init__(coordinator, entry)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_delete_profile"

    async def async_press(self) -> None:
        """Delete the currently selected backup from the backup select entity.

        Reads the selected option from the backup select entity to find the
        timestamp, then removes that backup from storage.
        """
        # Find the backup select entity for this device
        prefix = self._entry.data[CONF_DEVICE_NAME].lower().replace(" ", "_")
        select_entity_id = f"select.{prefix}_backup_select"
        select_state = self.hass.states.get(select_entity_id)

        if not select_state or not select_state.state or select_state.state == "unknown":
            LOGGER.warning("No backup selected for deletion on %s", self.coordinator.device_name)
            return

        # Extract timestamp from option format "label (YYYYMMDD_HHMMSS)"
        selected = select_state.state
        ts_start = selected.rfind("(")
        ts_end = selected.rfind(")")
        if ts_start == -1 or ts_end == -1:
            LOGGER.warning("Cannot parse timestamp from backup option: %s", selected)
            return
        timestamp = selected[ts_start + 1 : ts_end]

        LOGGER.info("Deleting backup '%s' (timestamp: %s)", selected, timestamp)
        deleted = await async_delete_backup(
            self.hass, self._entry.entry_id, timestamp
        )
        if deleted:
            # Trigger coordinator update so the backup select refreshes its options
            self.coordinator.async_set_updated_data(self.coordinator.data)
            LOGGER.info("Deleted backup '%s'", selected)
        else:
            LOGGER.warning("Backup with timestamp '%s' not found", timestamp)


class RetroFactoryResetButton(_RetroButtonBase):
    """Button to reset the adapter to factory default (identity passthrough)."""

    _attr_translation_key = "factory_reset"
    _attr_icon = "mdi:restart"

    def __init__(
        self, coordinator: RetroCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the factory reset button."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ADDRESS]}_factory_reset"

    async def async_press(self) -> None:
        """Write factory default identity mappings to the adapter."""
        LOGGER.info("Factory reset for %s", self.coordinator.device_name)
        try:
            await self.coordinator.async_factory_reset()
            LOGGER.info("Factory reset complete for %s", self.coordinator.device_name)
        except Exception as err:
            LOGGER.error("Factory reset failed for %s: %s", self.coordinator.device_name, err)
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
