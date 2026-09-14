"""Auto-deploy dashboard and custom card for the Retro Gaming integration.

Creates a storage-mode Lovelace dashboard and registers the bundled
retro-controller-card as a frontend resource — all on first setup,
mirroring how _deploy_sentences() works for custom sentences.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_CONSOLE_TYPE, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN, LOGGER

DASHBOARD_URL_PATH = "retro"
DASHBOARD_ID = "dashboard_retro"
DASHBOARD_TITLE = "Retro Gaming"
DASHBOARD_ICON = "mdi:gamepad-variant"
CARD_JS_PATH = "/local/retro/retro-controller-card-v2.js"
CARD_URL_BASE = "/local/retro/retro-controller-card-v2.js"


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


async def async_update_dashboard_config(hass: HomeAssistant) -> None:
    """Rebuild the dashboard config from all configured retro entries.

    Called after each entry setup to add new devices to the dashboard.
    Uses the internal Lovelace storage API so the live in-memory state
    updates immediately (file writes alone only take effect on restart).
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return

    config = _build_dynamic_dashboard(entries)
    device_count = len(config["views"][0]["sections"]) - 1

    # Always write the file (ensures restart picks it up)
    await hass.async_add_executor_job(_write_dashboard_config, hass, config)

    # Also try to update the live in-memory state via lovelace internal API.
    # This matters when adding a device to a running system — without it,
    # the browser shows stale dashboard until next HA restart.
    try:
        dashboards = hass.data.get("lovelace_dashboards", {})
        dash = dashboards.get(DASHBOARD_URL_PATH)
        if dash is not None and hasattr(dash, "async_save"):
            await dash.async_save(config)
            LOGGER.info(
                "Updated Retro Gaming dashboard with %d device(s) (live)",
                device_count,
            )
            return
    except Exception as err:
        LOGGER.debug("Live dashboard update skipped: %s", err)


# ---------------------------------------------------------------------------
# File-based dashboard deploy (runs in executor)
# ---------------------------------------------------------------------------


def _deploy_dashboard_files(hass: HomeAssistant) -> None:
    """Write dashboard .storage files if not present."""
    storage_dir = Path(hass.config.config_dir) / ".storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    # --- Dashboard config file ---
    dashboard_file = storage_dir / f"lovelace.{DASHBOARD_ID}"
    if not dashboard_file.exists():
        payload = {
            "version": 1,
            "minor_version": 1,
            "key": f"lovelace.{DASHBOARD_ID}",
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
                "id": DASHBOARD_ID,
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
    component_dir = Path(__file__).parent
    # homeassistant-config tracks the card at component root (www/ is gitignored on HAOS).
    source = component_dir / "www" / "retro-controller-card.js"
    if not source.exists():
        source = component_dir / "retro-controller-card.js"
    if not source.exists():
        LOGGER.debug("Card JS source not found in %s", component_dir)
        return

    target_dir = Path(hass.config.config_dir) / "www" / "retro"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "retro-controller-card-v2.js"

    if not target.exists() or source.stat().st_mtime > target.stat().st_mtime:
        import shutil

        shutil.copy2(source, target)
        LOGGER.info("Deployed retro-controller-card-v2.js to %s", target)


# ---------------------------------------------------------------------------
# Lovelace resource registration
# ---------------------------------------------------------------------------


def _deploy_card_resource(hass: HomeAssistant) -> None:
    """Register retro-controller-card.js as a Lovelace resource in .storage.

    Always updates the URL with a cache-busting timestamp from the deployed
    JS file's mtime so browsers pick up new versions.
    """
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

    # Cache-bust URL from deployed JS file mtime
    js_file = Path(hass.config.config_dir) / "www" / "retro" / "retro-controller-card-v2.js"
    if js_file.exists():
        cache_bust = int(js_file.stat().st_mtime)
    else:
        import time as _time
        cache_bust = int(_time.time())
    card_url = f"{CARD_URL_BASE}?v={cache_bust}"

    # Find existing entry
    items = resources["data"]["items"]
    existing_idx = None
    for idx, item in enumerate(items):
        url = item.get("url", "")
        if url == CARD_URL_BASE or url.startswith(f"{CARD_URL_BASE}?"):
            existing_idx = idx
            break

    entry = {
        "id": f"{DOMAIN}_controller_card",
        "type": "module",
        "url": card_url,
    }

    if existing_idx is not None:
        if items[existing_idx].get("url") == card_url:
            LOGGER.debug("retro-controller-card already registered with current version")
            return
        items[existing_idx] = entry
        LOGGER.info("Updated retro-controller-card resource URL to %s", card_url)
    else:
        items.append(entry)
        LOGGER.info("Registered retro-controller-card.js as Lovelace resource: %s", card_url)

    resource_file.write_text(json.dumps(resources, indent=2))


# ---------------------------------------------------------------------------
# Dynamic dashboard builder — generates config from all configured entries
# ---------------------------------------------------------------------------


def _write_dashboard_config(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Write dashboard config to .storage file."""
    storage_dir = Path(hass.config.config_dir) / ".storage"
    dashboard_file = storage_dir / f"lovelace.{DASHBOARD_ID}"
    payload = {
        "version": 1,
        "minor_version": 1,
        "key": f"lovelace.{DASHBOARD_ID}",
        "data": {"config": config},
    }
    dashboard_file.write_text(json.dumps(payload, indent=2))
    LOGGER.info("Updated Retro Gaming dashboard with %d device(s)", len(config["views"][0]["sections"]) - 1)


def _build_dynamic_dashboard(entries: list) -> dict[str, Any]:
    """Build dashboard config dynamically from all configured entries."""
    sections = []

    # Per-device sections
    for entry in entries:
        name = entry.data.get(CONF_DEVICE_NAME, "Unknown")
        addr = entry.data.get(CONF_DEVICE_ADDRESS, "")
        console = entry.data.get(CONF_CONSOLE_TYPE, "n64")
        # Entity ID prefix: HA generates from device name + address suffix
        # e.g. "BlueRetro_N64_XXXX" -> "blueretro_n64_xxxx"
        prefix = f"{name.lower().replace(' ', '_').replace('-', '_')}"

        sections.append(_device_section(prefix, name, console, entry))

    # Setup/info section at the end
    sections.append(_info_section())

    # Build Mappings tab — one custom card per device, uses masonry layout
    # (sections view type doesn't render custom elements properly)
    mapping_cards = []
    for entry in entries:
        name = entry.data.get(CONF_DEVICE_NAME, "Unknown")
        prefix = f"{name.lower().replace(' ', '_').replace('-', '_')}"
        mapping_cards.append({
            "type": "custom:retro-controller-card",
            "entity": f"select.{prefix}_profile",
            "title": f"{name} Mapping Editor",
            "entry_id": entry.entry_id,
        })

    return {
        "views": [
            {
                "type": "sections",
                "title": "Retro Gaming",
                "path": "retro",
                "icon": "mdi:gamepad-variant",
                "badges": [],
                "sections": sections,
            },
            {
                # panel view: full-width cards; masonry + hui-card wrapper is flaky on 2026.6
                "type": "panel",
                "title": "Mappings",
                "path": "mappings",
                "icon": "mdi:swap-horizontal",
                "badges": [],
                "cards": mapping_cards,
            },
        ]
    }


def _device_section(prefix: str, name: str, console: str, entry: Any) -> dict[str, Any]:
    """Build a dashboard section for one device."""
    profiles = _get_profiles_for_console(console)

    # Build quick-switch button rows (3 per row)
    profile_rows = []
    for i in range(0, len(profiles), 3):
        row = profiles[i:i+3]
        profile_rows.append({
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button",
                    "name": p["name"],
                    "icon": p["icon"],
                    "show_state": False,
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "select.select_option",
                        "target": {"entity_id": f"select.{prefix}_profile"},
                        "data": {"option": p["key"]},
                    },
                }
                for p in row
            ],
        })

    cards = [
        {
            "type": "heading",
            "heading": name,
            "heading_style": "title",
            "icon": "mdi:gamepad-variant",
        },
        # Status row
        {
            "type": "horizontal-stack",
            "cards": [
                {"type": "tile", "entity": f"sensor.{prefix}_status", "name": "Status", "icon": "mdi:bluetooth-connect"},
                {"type": "tile", "entity": f"sensor.{prefix}_firmware", "name": "Firmware", "icon": "mdi:chip"},
            ],
        },
        # Profile selector
        {
            "type": "entities",
            "entities": [
                {"entity": f"select.{prefix}_profile", "name": "Active Profile"},
            ],
        },
        # Quick switch buttons
        *profile_rows,
        # Backup selector
        {
            "type": "entities",
            "entities": [
                {"entity": f"select.{prefix}_backup_select", "name": "Restore Point"},
            ],
        },
        # Action buttons
        {
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button", "entity": f"button.{prefix}_backup_config",
                    "name": "Backup", "icon": "mdi:content-save", "show_state": False,
                    "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                   "target": {"entity_id": f"button.{prefix}_backup_config"}},
                },
                {
                    "type": "button", "entity": f"button.{prefix}_restore_config",
                    "name": "Restore", "icon": "mdi:backup-restore", "show_state": False,
                    "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                   "target": {"entity_id": f"button.{prefix}_restore_config"}},
                },
                {
                    "type": "button", "entity": f"button.{prefix}_save_profile",
                    "name": "Save Profile", "icon": "mdi:content-save-plus", "show_state": False,
                    "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                   "target": {"entity_id": f"button.{prefix}_save_profile"}},
                },
                {
                    "type": "button", "entity": f"button.{prefix}_delete_profile",
                    "name": "Delete Backup", "icon": "mdi:delete", "show_state": False,
                    "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                   "target": {"entity_id": f"button.{prefix}_delete_profile"}},
                },
            ],
        },
        {
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button", "entity": f"button.{prefix}_factory_reset",
                    "name": "Factory Reset", "icon": "mdi:restart", "show_state": False,
                    "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                   "target": {"entity_id": f"button.{prefix}_factory_reset"}},
                },
                {
                    "type": "button", "entity": f"button.{prefix}_refresh",
                    "name": "Refresh", "icon": "mdi:refresh", "show_state": False,
                    "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                   "target": {"entity_id": f"button.{prefix}_refresh"}},
                },
            ],
        },
    ]

    return {"type": "grid", "cards": cards}


def _info_section() -> dict[str, Any]:
    """Build the setup/info section."""
    return {
        "type": "grid",
        "cards": [
            {
                "type": "heading",
                "heading": "Info",
                "heading_style": "title",
                "icon": "mdi:information",
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
            {
                "type": "markdown",
                "content": (
                    "**Backups include:** Global config, output mode, input mappings, firmware version\n\n"
                    "**Per-device** \u2014 max 10 each, stored as JSON in `/config/retro_backups/`\n\n"
                    "\u270f\ufe0f [Browse in File Editor](/hassio/ingress/core_configurator) \u2192 `retro_backups/backups.json`\n\n"
                    "SMB: `smb://homeassistant.local/config/retro_backups/`"
                ),
            },
        ],
    }


def _get_profiles_for_console(console: str) -> list[dict[str, str]]:
    """Return profile metadata for dashboard quick-switch buttons."""
    if console == "n64":
        return [
            {"key": "default", "name": "Default", "icon": "mdi:gamepad"},
            {"key": "goldeneye", "name": "GoldenEye", "icon": "mdi:pistol"},
            {"key": "mario_kart", "name": "Mario Kart", "icon": "mdi:go-kart"},
            {"key": "smash_bros", "name": "Smash Bros", "icon": "mdi:boxing-glove"},
            {"key": "zelda", "name": "Zelda", "icon": "mdi:sword"},
            {"key": "perfect_dark", "name": "Perfect Dark", "icon": "mdi:pistol"},
        ]
    # Default fallback — just a default button
    return [{"key": "default", "name": "Default", "icon": "mdi:gamepad"}]


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
                                    "1. **Disconnect** BT controller (press adapter BOOT 3–6s)\n"
                                    "2. Select a profile above or say *\"set retro profile to goldeneye\"*\n"
                                    "3. Wait for reboot (~5s) then re-pair controller\n\n"
                                    "Add more adapters via **Settings → Devices → Add Integration → Retro Gaming**"
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
