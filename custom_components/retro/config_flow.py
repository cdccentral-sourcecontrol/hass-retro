"""Config flow for Retro Gaming integration.

Multi-step flow:
1. Select adapter type (blueretro, future: 8bitdo, raphnet)
2. BLE scan or manual address entry
3. Select console type and enter friendly name

Options flow:
- Poll interval (minutes)
- Keep-alive (aggressive reconnect)
- Auto-backup on profile change
- Inquiry mode (auto/manual pairing)
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import (
    BR_SERVICE_UUID,
    CONF_ADAPTER_TYPE,
    CONF_CONSOLE_TYPE,
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    CONSOLE_FRIENDLY_NAMES,
    DEFAULT_AUTO_BACKUP,
    DEFAULT_INQUIRY_MODE,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    LOGGER,
    OPT_AUTO_BACKUP,
    OPT_INQUIRY_MODE,
    OPT_KEEP_ALIVE,
    OPT_POLL_INTERVAL,
    AdapterType,
    ConsoleType,
)


class RetroConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for adding a retro gaming adapter."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._adapter_type: str | None = None
        self._address: str | None = None
        self._discovered_devices: dict[str, str] = {}  # address -> name

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return RetroOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Select adapter type."""
        if user_input is not None:
            self._adapter_type = user_input[CONF_ADAPTER_TYPE]
            if self._adapter_type == AdapterType.BLUERETRO:
                return await self.async_step_bluetooth_scan()
            # Future adapter types may have different discovery methods
            return await self.async_step_manual_address()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADAPTER_TYPE, default=AdapterType.BLUERETRO): vol.In(
                        {t.value: t.value for t in AdapterType}
                    ),
                }
            ),
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle bluetooth discovery of a BlueRetro device."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._adapter_type = AdapterType.BLUERETRO
        self._address = discovery_info.address
        self._discovered_devices[discovery_info.address] = (
            discovery_info.name or f"BlueRetro ({discovery_info.address})"
        )

        self.context["title_placeholders"] = {
            "name": discovery_info.name or "BlueRetro"
        }
        return await self.async_step_configure()

    async def async_step_bluetooth_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 (BlueRetro): Scan for BLE devices or enter manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input.get(CONF_DEVICE_ADDRESS, "")
            if address == "__manual__":
                return await self.async_step_manual_address()
            if address:
                self._address = address
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return await self.async_step_configure()
            errors["base"] = "no_device_selected"

        # Scan for BlueRetro devices via HA bluetooth
        self._discovered_devices = {}
        for info in async_discovered_service_info(self.hass):
            if BR_SERVICE_UUID.lower() in [
                u.lower() for u in (info.service_uuids or [])
            ]:
                name = info.name or f"BlueRetro ({info.address})"
                self._discovered_devices[info.address] = name
            elif info.name and "blueretro" in info.name.lower():
                name = info.name
                self._discovered_devices[info.address] = name

        device_options = {
            addr: f"{name} ({addr})"
            for addr, name in self._discovered_devices.items()
        }
        device_options["__manual__"] = "Enter address manually..."

        if not self._discovered_devices:
            LOGGER.debug("No BlueRetro devices found in BLE scan")

        return self.async_show_form(
            step_id="bluetooth_scan",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ADDRESS): vol.In(device_options),
                }
            ),
            errors=errors,
        )

    async def async_step_manual_address(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manually enter a BLE address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input.get(CONF_DEVICE_ADDRESS, "").strip().upper()
            if address and ":" in address:
                self._address = address
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return await self.async_step_configure()
            errors[CONF_DEVICE_ADDRESS] = "invalid_address"

        return self.async_show_form(
            step_id="manual_address",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ADDRESS): str,
                }
            ),
            errors=errors,
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Select console type and set friendly name."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_DEVICE_NAME],
                data={
                    CONF_ADAPTER_TYPE: self._adapter_type,
                    CONF_DEVICE_ADDRESS: self._address,
                    CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                    CONF_CONSOLE_TYPE: user_input[CONF_CONSOLE_TYPE],
                },
            )

        # Default name from discovered device name or address
        default_name = self._discovered_devices.get(
            self._address, f"Retro {self._address}"
        )

        console_options = {c.value: CONSOLE_FRIENDLY_NAMES[c] for c in ConsoleType}

        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_NAME, default=default_name): str,
                    vol.Required(CONF_CONSOLE_TYPE, default=ConsoleType.N64): vol.In(
                        console_options
                    ),
                }
            ),
        )


class RetroOptionsFlow(OptionsFlow):
    """Options flow for configuring a retro gaming adapter."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage adapter options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPT_POLL_INTERVAL,
                        default=options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): vol.In({1: "1 min", 2: "2 min", 5: "5 min", 10: "10 min", 15: "15 min"}),
                    vol.Required(
                        OPT_KEEP_ALIVE,
                        default=options.get(OPT_KEEP_ALIVE, DEFAULT_KEEP_ALIVE),
                    ): bool,
                    vol.Required(
                        OPT_AUTO_BACKUP,
                        default=options.get(OPT_AUTO_BACKUP, DEFAULT_AUTO_BACKUP),
                    ): bool,
                    vol.Required(
                        OPT_INQUIRY_MODE,
                        default=options.get(OPT_INQUIRY_MODE, DEFAULT_INQUIRY_MODE),
                    ): vol.In({"auto": "Auto (always discoverable)", "manual": "Manual (button press)"}),
                }
            ),
        )
