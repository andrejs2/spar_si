"""Todo platform for SPAR Online Slovenija."""
from __future__ import annotations

import logging
import uuid

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SparApiError, SparAuthError, SparCartItem, SparConnectionError
from .const import DOMAIN
from .coordinator import SparConfigEntry, SparCoordinator
from .store import SparShoppingListStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SparConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SPAR todo entities."""
    coordinator: SparCoordinator = entry.runtime_data

    store = SparShoppingListStore(hass, entry.entry_id)
    saved_items = await store.async_load()

    async_add_entities(
        [
            SparShoppingListEntity(coordinator, entry, store, saved_items),
            SparCartEntity(coordinator, entry),
        ]
    )


class SparShoppingListEntity(TodoListEntity):
    """Local shopping list for items to find in SPAR.

    This is a local-only list where users add items by name
    (e.g., via voice assistant). Items can then be matched to
    SPAR products and moved to the cart. Persists across restarts.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_icon = "mdi:clipboard-list-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self,
        coordinator: SparCoordinator,
        entry: SparConfigEntry,
        store: SparShoppingListStore,
        saved_items: list[dict],
    ) -> None:
        """Initialize the shopping list."""
        self._entry = entry
        self._coordinator = coordinator
        self._store = store
        self._attr_unique_id = f"{entry.entry_id}_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SPAR Online",
            manufacturer="SPAR Slovenija",
            entry_type=None,
        )
        # Restore items from storage
        self._items: list[TodoItem] = [
            TodoItem(
                uid=item["uid"],
                summary=item["summary"],
                status=TodoItemStatus(item.get("status", "needs_action")),
                description=item.get("description"),
            )
            for item in saved_items
        ]

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the shopping list items."""
        return self._items

    async def _async_save(self) -> None:
        """Persist items to storage."""
        await self._store.async_save(
            [
                {
                    "uid": item.uid,
                    "summary": item.summary,
                    "status": item.status.value if item.status else "needs_action",
                    "description": item.description,
                }
                for item in self._items
            ]
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the shopping list."""
        new_item = TodoItem(
            uid=str(uuid.uuid4()),
            summary=item.summary,
            status=TodoItemStatus.NEEDS_ACTION,
            description=item.description,
        )
        self._items.append(new_item)
        self.async_write_ha_state()
        await self._async_save()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a shopping list item."""
        for idx, existing in enumerate(self._items):
            if existing.uid == item.uid:
                self._items[idx] = TodoItem(
                    uid=existing.uid,
                    summary=item.summary or existing.summary,
                    status=item.status or existing.status,
                    description=item.description
                    if item.description is not None
                    else existing.description,
                )
                break
        self.async_write_ha_state()
        await self._async_save()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the shopping list."""
        uid_set = set(uids)
        self._items = [i for i in self._items if i.uid not in uid_set]
        self.async_write_ha_state()
        await self._async_save()


class SparCartEntity(
    CoordinatorEntity[SparCoordinator], TodoListEntity
):
    """SPAR Online cart synchronized as a todo list.

    Each item represents a product in the SPAR Online cart.
    Adding/removing items here directly modifies the online cart.
    The summary format is "Product Name (Qty UNIT)".
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cart"
    _attr_icon = "mdi:cart"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self,
        coordinator: SparCoordinator,
        entry: SparConfigEntry,
    ) -> None:
        """Initialize the cart entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cart"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SPAR Online",
            manufacturer="SPAR Slovenija",
        )

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return cart items as todo items."""
        if self.coordinator.data is None:
            return None

        return [
            self._cart_item_to_todo(item)
            for item in self.coordinator.data.items
        ]

    def _cart_item_to_todo(self, item: SparCartItem) -> TodoItem:
        """Convert a SPAR cart item to a HA todo item."""
        qty_str = (
            f"{item.unit_quantity:g}"
            if item.unit_quantity != int(item.unit_quantity)
            else str(int(item.unit_quantity))
        )
        return TodoItem(
            uid=item.product_id,
            summary=f"{item.name} ({qty_str} {item.unit})",
            status=TodoItemStatus.NEEDS_ACTION,
            description=(
                f"REF: {item.reference} | "
                f"Cena: {item.price_total:.2f} EUR"
            ),
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a product to the SPAR cart.

        Accepts either:
        - Plain text like "mleko" -> searches and adds first result
        - "mleko 3" or "3x mleko" -> searches and adds with quantity
        """
        if not item.summary:
            return

        query, quantity = self._parse_item_input(item.summary)

        try:
            products = await self.coordinator.client.async_search_products(
                query=query, page_size=1
            )
        except (SparApiError, SparAuthError, SparConnectionError) as err:
            _LOGGER.error("Failed to search for '%s': %s", query, err)
            raise HomeAssistantError(
                f"Iskanje izdelka '{query}' ni uspelo: {err}"
            ) from err

        if not products:
            _LOGGER.warning("No product found for: %s", query)
            raise HomeAssistantError(
                f"Izdelek '{query}' ni bil najden v SPAR Online"
            )

        product = products[0]
        try:
            await self.coordinator.client.async_add_to_cart(
                reference=product.sku,
                unit=product.unit,
                unit_quantity=quantity,
            )
        except (SparApiError, SparAuthError, SparConnectionError) as err:
            _LOGGER.error("Failed to add '%s' to cart: %s", product.name, err)
            raise HomeAssistantError(
                f"Dodajanje '{product.name}' v košarico ni uspelo: {err}"
            ) from err

        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a cart item.

        - Mark as complete -> removes from cart
        - Change summary -> try to parse new quantity
        """
        if not item.uid:
            return

        try:
            if item.status == TodoItemStatus.COMPLETED:
                await self.coordinator.client.async_remove_from_cart(
                    product_id=item.uid
                )
                await self.coordinator.async_request_refresh()
                return

            if item.summary:
                _, quantity = self._parse_item_input(item.summary)
                if quantity != 1.0:
                    await self.coordinator.client.async_update_cart_item(
                        product_id=item.uid, unit_quantity=quantity
                    )
            await self.coordinator.async_request_refresh()
        except (SparApiError, SparAuthError, SparConnectionError) as err:
            _LOGGER.error("Failed to update cart item: %s", err)
            raise HomeAssistantError(
                f"Posodobitev košarice ni uspela: {err}"
            ) from err

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove products from the cart."""
        try:
            for product_id in uids:
                await self.coordinator.client.async_remove_from_cart(
                    product_id=product_id
                )
            await self.coordinator.async_request_refresh()
        except (SparApiError, SparAuthError, SparConnectionError) as err:
            _LOGGER.error("Failed to remove from cart: %s", err)
            raise HomeAssistantError(
                f"Odstranjevanje iz košarice ni uspelo: {err}"
            ) from err

    @staticmethod
    def _parse_item_input(text: str) -> tuple[str, float]:
        """Parse item input to extract product name and quantity.

        Supports formats:
        - "mleko" -> ("mleko", 1.0)
        - "mleko 3" -> ("mleko", 3.0)
        - "3x mleko" -> ("mleko", 3.0)
        - "3 x mleko" -> ("mleko", 3.0)
        """
        import re

        text = text.strip()

        # Match "3x mleko" or "3 x mleko"
        match = re.match(r"^(\d+(?:\.\d+)?)\s*x\s+(.+)$", text, re.IGNORECASE)
        if match:
            return match.group(2).strip(), float(match.group(1))

        # Match "mleko 3"
        match = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)$", text)
        if match:
            return match.group(1).strip(), float(match.group(2))

        return text, 1.0
