"""Intent handlers for the Retro Gaming integration.

Registers SetRetroProfile intent with HA's intent system.
The handler resolves which adapter to target based on console slot,
validates the profile exists, applies it, and returns speech response.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import CONF_CONSOLE_TYPE, DOMAIN, LOGGER


class SetRetroProfileIntent(intent.IntentHandler):
    """Handle SetRetroProfile intents from voice assistants."""

    intent_type = "SetRetroProfile"
    description = "Set a retro gaming controller mapping profile"

    slot_schema = {
        vol.Required("profile"): str,
        vol.Optional("console", default="default"): str,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the SetRetroProfile intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)

        profile = slots["profile"]["value"]
        console = slots["console"]["value"]

        coordinator = await _resolve_coordinator(hass, console)

        if coordinator is None:
            response = intent_obj.create_response()
            if console == "default":
                response.async_set_speech(
                    "No retro gaming adapters are configured."
                )
            else:
                response.async_set_speech(
                    f"No {console} adapter is configured."
                )
            return response

        if profile not in coordinator.profile_names:
            available = ", ".join(coordinator.profile_names)
            response = intent_obj.create_response()
            response.async_set_speech(
                f"Unknown profile '{profile}' for {coordinator.console_type}. "
                f"Available: {available}."
            )
            return response

        try:
            await coordinator.async_apply_profile(profile)
        except Exception as err:
            LOGGER.error("Failed to apply profile '%s': %s", profile, err)
            response = intent_obj.create_response()
            response.async_set_speech(
                f"Failed to apply {profile} profile. "
                "Make sure no controller is connected to the adapter."
            )
            return response

        response = intent_obj.create_response()
        if console == "default":
            response.async_set_speech(
                f"Set controller to {profile} profile."
            )
        else:
            response.async_set_speech(
                f"Set {console} to {profile} profile."
            )
        return response


async def _resolve_coordinator(
    hass: HomeAssistant, console: str
) -> Any | None:
    """Find the RetroCoordinator matching the console type.

    If console is 'default', returns the first (or only) configured adapter.
    """
    from homeassistant.config_entries import ConfigEntry

    entries: list[ConfigEntry] = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None

    if console == "default":
        for entry in entries:
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                return entry.runtime_data
        return None

    for entry in entries:
        if (
            entry.data.get(CONF_CONSOLE_TYPE) == console
            and hasattr(entry, "runtime_data")
            and entry.runtime_data
        ):
            return entry.runtime_data

    return None
