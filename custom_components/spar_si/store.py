"""Persistent storage for SPAR SI shopping list and preferences."""
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


class SparPreferenceStore:
    """Persistent store for product preferences.

    Maps search terms to preferred product SKUs, so the AI assistant
    can suggest previously chosen products first.
    Example: "kruh" -> {"sku": "371991", "name": "KRUH HRIBOVC BELI", "price": 1.29, "count": 5}
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.preferences"
        )
        self._preferences: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load preferences from disk."""
        data = await self._store.async_load()
        self._preferences = data.get("preferences", {}) if data else {}

    async def async_save(self) -> None:
        """Save preferences to disk."""
        await self._store.async_save({"preferences": self._preferences})

    async def async_record_choice(
        self, search_term: str, sku: str, name: str, price: float
    ) -> None:
        """Record a product choice for a search term."""
        key = search_term.lower().strip()
        existing = self._preferences.get(key, {})
        count = existing.get("count", 0) + 1 if existing.get("sku") == sku else 1
        self._preferences[key] = {
            "sku": sku,
            "name": name,
            "price": price,
            "count": count,
        }
        await self.async_save()

    def get_preference(self, search_term: str) -> dict[str, Any] | None:
        """Get the preferred product for a search term."""
        return self._preferences.get(search_term.lower().strip())

    def get_all_preferences(self) -> dict[str, dict[str, Any]]:
        """Return all saved preferences."""
        return dict(self._preferences)
