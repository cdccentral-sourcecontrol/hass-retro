"""Auto-deploy dashboard and custom card for the Retro Gaming integration.

Creates a storage-mode Lovelace dashboard and registers the bundled
retro-controller-card as a frontend resource — all on first setup,
mirroring how _deploy_sentences() works for custom sentences.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER

DASHBOARD_URL_PATH = "retro"
DASHBOARD_TITLE = "Retro Gaming"
DASHBOARD_ICON = "mdi:gamepad-variant"
CARD_JS_PATH = "/local/retro/retro-controller-card.js"
CARD_URL = "/local/retro/retro-controller-card.js"


# ---------------------------------------------------------------------------
# Public helpers called from __init__.py
# ---------------------------------------------------------------------------


async def async_deploy_dashboard(hass: HomeAssistant) -> None:
    """Create the Retro Gaming dashboard if it doesn't already exist.

    Writes two .storage files:
      - lovelace_dashboards  (registry — adds our entry)
      - lovelace.dashboard_retro  (actual dashboard config)

    Also copies the card JS to www/retro/ so HA can serve it, and
    registers it as a Lovelace resource.
    """
    await hass.async_add_executor_job(_deploy_dashboard_files, hass)
    await hass.async_add_executor_job(_deploy_card_resource, hass)
    await hass.async_add_executor_job(_deploy_card_www, hass)


# ---------------------------------------------------------------------------
# File-based dashboard deploy (runs in executor)
# ---------------------------------------------------------------------------


def _deploy_dashboard_files(hass: HomeAssistant) -> None:
    """Write dashboard .storage files if not present."""
    storage_dir = Path(hass.config.config_dir) / ".storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    # --- Dashboard config file ---
    dashboard_file = storage_dir / "lovelace.dashboard_retro"
    if not dashboard_file.exists():
        payload = {
            "version": 1,
            "minor_version": 1,
            "key": "lovelace.dashboard_retro",
            "data": {"config": _build_dashboard_config()},
        }
        dashboard_file.write_text(json.dumps(payload, indent=2))
        LOGGER.info("Deployed Retro Gaming dashboard config")
    else:
        LOGGER.debug("Retro dashboard config already exists, skipping")

    # --- Dashboard registry entry ---
    dashboards_file = storage_dir / "lovelace_dashboards"
    if dashboards_file.exists():
        dashboards = json.loads(dashboards_file.read_text())
    else:
        dashboards = {
            "version": 1,
            "minor_version": 1,
            "key": "lovelace_dashboards",
            "data": {"items": []},
        }

    existing = {item.get("url_path") for item in dashboards["data"]["items"]}
    if DASHBOARD_URL_PATH not in existing:
        dashboards["data"]["items"].append(
            {
                "id": str(uuid.uuid4().hex[:12]),
                "url_path": DASHBOARD_URL_PATH,
                "mode": "storage",
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "require_admin": False,
                "show_in_sidebar": True,
            }
        )
        dashboards_file.write_text(json.dumps(dashboards, indent=2))
        LOGGER.info("Registered Retro Gaming dashboard in sidebar")


# ---------------------------------------------------------------------------
# Card JS deploy — copy to www/retro/ so HA serves it at /local/retro/
# ---------------------------------------------------------------------------


def _deploy_card_www(hass: HomeAssistant) -> None:
    """Copy retro-controller-card.js to config/www/retro/."""
    source = Path(__file__).parent / "www" / "retro-controller-card.js"
    if not source.exists():
        LOGGER.debug("Card JS source not found: %s", source)
        return

    target_dir = Path(hass.config.config_dir) / "www" / "retro"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "retro-controller-card.js"

    if not target.exists() or source.stat().st_mtime > target.stat().st_mtime:
        import shutil

        shutil.copy2(source, target)
        LOGGER.info("Deployed retro-controller-card.js to %s", target)


# ---------------------------------------------------------------------------
# Lovelace resource registration
# ---------------------------------------------------------------------------


def _deploy_card_resource(hass: HomeAssistant) -> None:
    """Register retro-controller-card.js as a Lovelace resource in .storage."""
    storage_dir = Path(hass.config.config_dir) / ".storage"
    resource_file = storage_dir / "lovelace_resources"

    if resource_file.exists():
        resources = json.loads(resource_file.read_text())
    else:
        resources = {
            "version": 1,
            "minor_version": 1,
            "key": "lovelace_resources",
            "data": {"items": []},
        }

    # Check if already registered
    existing_urls = {item.get("url") for item in resources["data"]["items"]}
    if CARD_URL in existing_urls:
        LOGGER.debug("retro-controller-card already registered as resource")
        return

    resources["data"]["items"].append(
        {
            "id": str(uuid.uuid4().hex[:12]),
            "type": "module",
            "url": CARD_URL,
        }
    )
    resource_file.write_text(json.dumps(resources, indent=2))
    LOGGER.info("Registered retro-controller-card.js as Lovelace resource")


# ---------------------------------------------------------------------------
# Dashboard config builder — generates the full Lovelace YAML-equivalent
# ---------------------------------------------------------------------------


def _build_dashboard_config() -> dict[str, Any]:
    """Return the default Retro Gaming dashboard config.

    Uses a combination of the custom retro-controller-card and standard
    HA cards. Entity IDs use {name} placeholders that work dynamically
    when the user has configured adapters.
    """
    return {
        "views": [
            {
                "type": "sections",
                "title": "Retro Gaming",
                "path": "retro",
                "icon": "mdi:gamepad-variant",
                "badges": [],
                "sections": [
                    # --- Custom Card Section ---
                    {
                        "type": "grid",
                        "title": "",
                        "cards": [
                            {
                                "type": "heading",
                                "heading": "Controller Adapters",
                                "heading_style": "title",
                                "icon": "mdi:gamepad-variant",
                            },
                            {
                                "type": "custom:retro-controller-card",
                                "entity": "select.retro_n64_profile",
                                "title": "N64 Adapter",
                            },
                            {
                                "type": "markdown",
                                "content": (
                                    "### Setup\n\n"
                                    "1. **Disconnect** BT controller (press adapter BOOT 3\u20136s)\n"
                                    "2. Select a profile above or say *\"set retro profile to goldeneye\"*\n"
                                    "3. Wait for reboot (~5s) then re-pair controller\n\n"
                                    "Add more adapters via **Settings \u2192 Devices \u2192 Add Integration \u2192 Retro Gaming**"
                                ),
                            },
                        ],
                    },
                    # --- Quick Switch Section ---
                    {
                        "type": "grid",
                        "title": "",
                        "cards": [
                            {
                                "type": "heading",
                                "heading": "Quick Switch",
                                "heading_style": "title",
                                "icon": "mdi:lightning-bolt",
                            },
                            {
                                "type": "horizontal-stack",
                                "cards": [
                                    _profile_button("Default", "mdi:gamepad", "default"),
                                    _profile_button("GoldenEye", "mdi:pistol", "goldeneye"),
                                    _profile_button("Mario Kart", "mdi:go-kart", "mario_kart"),
                                ],
                            },
                            {
                                "type": "horizontal-stack",
                                "cards": [
                                    _profile_button("Smash Bros", "mdi:boxing-glove", "smash_bros"),
                                    _profile_button("Zelda", "mdi:sword", "zelda"),
                                    _profile_button("Perfect Dark", "mdi:pistol", "perfect_dark"),
                                ],
                            },
                        ],
                    },
                    # --- Device Info Section ---
                    {
                        "type": "grid",
                        "title": "",
                        "cards": [
                            {
                                "type": "heading",
                                "heading": "Device Info",
                                "heading_style": "title",
                                "icon": "mdi:chip",
                            },
                            {
                                "type": "horizontal-stack",
                                "cards": [
                                    {
                                        "type": "tile",
                                        "entity": "sensor.retro_n64_status",
                                        "name": "Status",
                                        "icon": "mdi:bluetooth-connect",
                                    },
                                    {
                                        "type": "tile",
                                        "entity": "sensor.retro_n64_firmware",
                                        "name": "Firmware",
                                        "icon": "mdi:chip",
                                    },
                                ],
                            },
                            {
                                "type": "horizontal-stack",
                                "cards": [
                                    {
                                        "type": "button",
                                        "entity": "button.retro_n64_backup",
                                        "name": "Backup",
                                        "icon": "mdi:content-save",
                                        "show_state": False,
                                        "tap_action": {
                                            "action": "perform-action",
                                            "perform_action": "button.press",
                                            "target": {
                                                "entity_id": "button.retro_n64_backup"
                                            },
                                        },
                                    },
                                    {
                                        "type": "button",
                                        "entity": "button.retro_n64_refresh",
                                        "name": "Refresh",
                                        "icon": "mdi:refresh",
                                        "show_state": False,
                                        "tap_action": {
                                            "action": "perform-action",
                                            "perform_action": "button.press",
                                            "target": {
                                                "entity_id": "button.retro_n64_refresh"
                                            },
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
    }


def _profile_button(name: str, icon: str, profile: str) -> dict[str, Any]:
    """Build a quick-switch button card for a single profile."""
    return {
        "type": "button",
        "name": name,
        "icon": icon,
        "show_state": False,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "select.select_option",
            "target": {"entity_id": "select.retro_n64_profile"},
            "data": {"option": profile},
        },
    }
