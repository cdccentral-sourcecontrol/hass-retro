"""Retro adapter protocol handlers.

Each adapter type implements the BaseAdapter interface.
The coordinator delegates GATT/USB operations to the appropriate adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAdapter(ABC):
    """Abstract base for retro adapter protocol handlers."""

    @abstractmethod
    async def async_connect(self) -> None:
        """Establish connection to the adapter."""

    @abstractmethod
    async def async_disconnect(self) -> None:
        """Disconnect from the adapter."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if currently connected."""

    @abstractmethod
    async def async_read_firmware(self) -> str:
        """Read firmware version string."""

    @abstractmethod
    async def async_read_mapping(self, device_id: int = 0) -> dict[str, Any]:
        """Read current button mapping from the adapter."""

    @abstractmethod
    async def async_write_mapping(
        self, mappings: list[dict[str, Any]], device_id: int = 0
    ) -> None:
        """Write a button mapping profile to the adapter."""

    @abstractmethod
    async def async_backup(self) -> dict[str, Any]:
        """Read full config for backup. Returns serializable dict."""

    @abstractmethod
    async def async_restore(self, backup: dict[str, Any]) -> None:
        """Restore config from a backup dict."""
