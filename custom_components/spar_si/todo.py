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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SparCartItem
from .const import DOMAIN
from .coordinator import SparConfigEntry, SparCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SparConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SPAR todo entities."""
    coordinator: SparCoordinator = entry.runtime_data

    async_add_entities(
        [
            SparShoppingListEntity(coordinator, entry),
            SparCartEntity(coordinator, entry),
        ]
    )


class SparShoppingListEntity(TodoListEntity):
    """Local shopping list for items to find in SPAR.

    This is a local-only list where users add items by name
    (e.g., via voice assistant). Items can then be matched to
    SPAR products and moved to the cart.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
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
        """Initialize the shopping list."""
        self._entry = entry
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SPAR Online",
            manufacturer="SPAR Slovenija",
            entry_type=None,
        )
        self._items: list[TodoItem] = []

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the shopping list items."""
        return self._items

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

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the shopping list."""
        uid_set = set(uids)
        self._items = [i for i in self._items if i.uid not in uid_set]
        self.async_write_ha_state()


class SparCartEntity(
    CoordinatorEntity[SparCoordinator], TodoListEntity
):
    """SPAR Online cart synchronized as a todo list.

    Each item represents a product in the SPAR Online cart.
    Adding/removing items here directly modifies the online cart.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cart"
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
        """Add a product to the SPAR cart by searching for it."""
        if not item.summary:
            return

        products = await self.coordinator.client.async_search_products(
            query=item.summary, page_size=1
        )
        if not products:
            _LOGGER.warning("No product found for: %s", item.summary)
            return

        product = products[0]
        await self.coordinator.client.async_add_to_cart(
            reference=product.sku, unit=product.unit, unit_quantity=1.0
        )
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a cart item (mark complete = remove from cart)."""
        if not item.uid:
            return

        if item.status == TodoItemStatus.COMPLETED:
            await self.coordinator.client.async_remove_from_cart(
                product_id=item.uid
            )
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove products from the cart."""
        for product_id in uids:
            await self.coordinator.client.async_remove_from_cart(
                product_id=product_id
            )
        await self.coordinator.async_request_refresh()
