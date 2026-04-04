"""Persistent storage for SPAR SI shopping list."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1


class SparShoppingListStore:
    """Persistent store for the local shopping list."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.shopping_list"
        )

    async def async_load(self) -> list[dict[str, Any]]:
        """Load shopping list items from disk."""
        data = await self._store.async_load()
        if data is None:
            return []
        return data.get("items", [])

    async def async_save(self, items: list[dict[str, Any]]) -> None:
        """Save shopping list items to disk."""
        await self._store.async_save({"items": items})
