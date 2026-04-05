"""The SPAR Online Slovenija integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SparApiClient, SparApiError, SparAuthError, SparConnectionError
from .const import CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE, DOMAIN
from .coordinator import SparConfigEntry, SparCoordinator
from .store import SparPreferenceStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TODO]

# Key for storing preference store in hass.data
PREF_STORE_KEY = f"{DOMAIN}_preferences"


async def async_setup_entry(
    hass: HomeAssistant, entry: SparConfigEntry
) -> bool:
    """Set up SPAR Online from a config entry."""
    session = async_get_clientsession(hass)
    client = SparApiClient(
        session=session,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        store_reference=entry.data.get(CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE),
    )

    try:
        await client.async_authenticate()
    except SparAuthError as err:
        raise ConfigEntryAuthFailed(
            "Invalid credentials for SPAR Online"
        ) from err
    except SparConnectionError as err:
        raise ConfigEntryNotReady(
            "Cannot connect to SPAR Online"
        ) from err

    coordinator = SparCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Load preference store
    pref_store = SparPreferenceStore(hass, entry.entry_id)
    await pref_store.async_load()
    hass.data.setdefault(DOMAIN, {})[PREF_STORE_KEY] = pref_store

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)
    _register_auto_sync_listener(hass, entry, coordinator)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SparConfigEntry
) -> bool:
    """Unload a config entry."""
    hass.data.get(DOMAIN, {}).pop(PREF_STORE_KEY, None)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_coordinator(hass: HomeAssistant) -> SparCoordinator | None:
    """Get the first available coordinator."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    return entries[0].runtime_data


def _get_pref_store(hass: HomeAssistant) -> SparPreferenceStore | None:
    """Get the preference store."""
    return hass.data.get(DOMAIN, {}).get(PREF_STORE_KEY)


def _get_shopping_list(hass: HomeAssistant, entry_id: str):
    """Get the SparShoppingListEntity for the given entry."""
    return hass.data.get(DOMAIN, {}).get(f"{entry_id}_shopping_list")


async def _do_sync_list_to_cart(
    coordinator: SparCoordinator,
    pref_store: SparPreferenceStore | None,
    shopping_list,
) -> dict:
    """Sync all NEEDS_ACTION items from shopping list to SPAR cart.

    Returns: {added: [{name, matched}], not_found: [str], errors: [{name, error}]}
    """
    results: dict = {"added": [], "not_found": [], "errors": []}

    items = [
        item
        for item in (shopping_list.todo_items or [])
        if item.status == TodoItemStatus.NEEDS_ACTION
    ]

    if not items:
        return results

    # Fetch fresh cart state before syncing
    try:
        cart = await coordinator.client.async_get_cart()
        _LOGGER.debug(
            "Sync: cart_id=%s, status=%s, items=%d",
            cart.cart_id,
            cart.status,
            cart.item_count,
        )
    except (SparApiError, SparAuthError, SparConnectionError) as err:
        raise SparApiError(
            f"Ni mogoče pridobiti košarice: {err}"
        ) from err

    if not cart.is_modifiable:
        raise SparApiError(
            f"Košarica je v statusu '{cart.status}' in je ni mogoče spreminjati. "
            "Odpri online.spar.si in dodaj artikel, da se ustvari nova košarica."
        )

    for item in items:
        query = item.summary or ""
        if not query:
            continue
        try:
            products = await coordinator.client.async_search_products(
                query=query, page_size=5
            )
            if not products:
                results["not_found"].append(query)
                continue

            # Filter to available products only
            available = [p for p in products if p.is_available]
            if not available:
                results["not_found"].append(query)
                _LOGGER.info(
                    "Sync: '%s' found %d products but none available",
                    query,
                    len(products),
                )
                continue

            # Prefer previously chosen product if available
            product = available[0]
            if pref_store:
                pref = pref_store.get_preference(query)
                if pref:
                    preferred = next(
                        (p for p in available if p.sku == pref["sku"]), None
                    )
                    if preferred:
                        product = preferred

            _LOGGER.debug(
                "Sync: adding '%s' -> sku=%s, name=%s, unit=%s, "
                "stock=%d, cart_id=%s",
                query,
                product.sku,
                product.name,
                product.unit,
                product.stock,
                coordinator.client._cart_id,
            )
            await coordinator.client.async_add_to_cart(
                reference=product.sku,
                unit=product.unit,
                unit_quantity=1.0,
            )
            results["added"].append({
                "name": query,
                "matched": product.name,
                "sku": product.sku,
            })

            # Mark as completed on shopping list
            await shopping_list.async_update_todo_item(
                TodoItem(
                    uid=item.uid,
                    summary=item.summary,
                    status=TodoItemStatus.COMPLETED,
                )
            )
        except (SparApiError, SparAuthError, SparConnectionError) as err:
            _LOGGER.error(
                "Sync failed for '%s' (sku=%s, unit=%s): %s",
                query,
                product.sku,
                product.unit,
                err,
            )
            results["errors"].append({
                "name": query,
                "sku": product.sku,
                "matched": product.name,
                "error": str(err),
            })
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Unexpected error syncing '%s'", query)
            results["errors"].append({"name": query, "error": str(err)})

    await coordinator.async_request_refresh()
    results["cart_id"] = cart.cart_id
    results["cart_status"] = cart.status
    return results


def _register_auto_sync_listener(
    hass: HomeAssistant,
    entry: SparConfigEntry,
    coordinator: SparCoordinator,
) -> None:
    """Register a coordinator listener that auto-syncs when a new cart is detected."""

    @callback
    def _on_coordinator_update() -> None:
        if not coordinator.new_cart_detected:
            return
        if not entry.options.get("auto_sync", False):
            return
        shopping_list = _get_shopping_list(hass, entry.entry_id)
        if not shopping_list:
            return
        pending = [
            i
            for i in (shopping_list.todo_items or [])
            if i.status == TodoItemStatus.NEEDS_ACTION
        ]
        if not pending:
            return
        _LOGGER.info(
            "New cart detected — auto-syncing %d items from shopping list",
            len(pending),
        )
        pref_store = _get_pref_store(hass)
        hass.async_create_task(
            _do_sync_list_to_cart(coordinator, pref_store, shopping_list),
            name="spar_si_auto_sync",
        )

    entry.async_on_unload(coordinator.async_add_listener(_on_coordinator_update))


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services for AI voice assistant."""
    if hass.services.has_service(DOMAIN, "search_products"):
        return

    # ─── search_products ───────────────────────────────────────
    async def handle_search_products(call: ServiceCall) -> dict:
        """Search for products in SPAR Online store.

        Use this to find products by name. Returns a list of matching
        products with SKU, name, price, and availability.
        The preference field shows if the user has previously chosen
        this product for the given search term.
        """
        query = call.data["query"]
        max_results = call.data.get("max_results", 5)

        coordinator = _get_coordinator(hass)
        if not coordinator:
            return {"products": [], "preference": None}

        products = await coordinator.client.async_search_products(
            query=query, page_size=max_results
        )

        # Check for saved preference
        pref_store = _get_pref_store(hass)
        preference = None
        if pref_store:
            pref = pref_store.get_preference(query)
            if pref:
                preference = {
                    "sku": pref["sku"],
                    "name": pref["name"],
                    "price": pref["price"],
                    "times_chosen": pref["count"],
                }

        return {
            "products": [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "price": p.price,
                    "unit": p.unit,
                    "brand": p.brand,
                    "is_available": p.is_available,
                }
                for p in products
            ],
            "preference": preference,
        }

    hass.services.async_register(
        DOMAIN,
        "search_products",
        handle_search_products,
        schema=vol.Schema(
            {
                vol.Required("query"): str,
                vol.Optional("max_results", default=5): vol.All(
                    int, vol.Range(min=1, max=50)
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # ─── add_to_cart ───────────────────────────────────────────
    async def handle_add_to_cart(call: ServiceCall) -> dict:
        """Add a product to the SPAR Online cart by SKU.

        Use this after the user has chosen a specific product from
        search results. Provide the SKU (reference) from search_products.
        Also records the user's preference for future suggestions.
        """
        sku = call.data["sku"]
        quantity = call.data.get("quantity", 1.0)
        unit = call.data.get("unit", "KOS")
        search_term = call.data.get("search_term")

        coordinator = _get_coordinator(hass)
        if not coordinator:
            return {"success": False, "error": "Integration not configured"}

        cart = await coordinator.client.async_add_to_cart(
            reference=sku, unit=unit, unit_quantity=quantity
        )

        # Save preference if search_term provided
        if search_term:
            pref_store = _get_pref_store(hass)
            if pref_store:
                # Find the product name from cart
                product_name = sku
                price = 0.0
                for item in cart.items:
                    if item.reference == sku:
                        product_name = item.name
                        price = item.price_total
                        break
                await pref_store.async_record_choice(
                    search_term, sku, product_name, price
                )

        await coordinator.async_request_refresh()

        return {
            "success": True,
            "cart_items": cart.item_count,
            "added": sku,
        }

    hass.services.async_register(
        DOMAIN,
        "add_to_cart",
        handle_add_to_cart,
        schema=vol.Schema(
            {
                vol.Required("sku"): str,
                vol.Optional("quantity", default=1.0): vol.Coerce(float),
                vol.Optional("unit", default="KOS"): str,
                vol.Optional("search_term"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # ─── remove_from_cart ──────────────────────────────────────
    async def handle_remove_from_cart(call: ServiceCall) -> dict:
        """Remove a product from the SPAR Online cart.

        Provide the product_id (uid) from the cart items.
        """
        product_id = call.data["product_id"]

        coordinator = _get_coordinator(hass)
        if not coordinator:
            return {"success": False, "error": "Integration not configured"}

        cart = await coordinator.client.async_remove_from_cart(
            product_id=product_id
        )
        await coordinator.async_request_refresh()

        return {"success": True, "cart_items": cart.item_count}

    hass.services.async_register(
        DOMAIN,
        "remove_from_cart",
        handle_remove_from_cart,
        schema=vol.Schema(
            {
                vol.Required("product_id"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # ─── get_cart ──────────────────────────────────────────────
    async def handle_get_cart(call: ServiceCall) -> dict:
        """Get the current contents of the SPAR Online cart.

        Returns all items in the cart with names, quantities, and prices.
        """
        coordinator = _get_coordinator(hass)
        if not coordinator:
            return {"items": [], "item_count": 0}

        cart = await coordinator.client.async_get_cart()

        return {
            "items": [
                {
                    "product_id": item.product_id,
                    "name": item.name,
                    "reference": item.reference,
                    "quantity": item.unit_quantity,
                    "unit": item.unit,
                    "price": item.price_total,
                }
                for item in cart.items
            ],
            "item_count": cart.item_count,
        }

    hass.services.async_register(
        DOMAIN,
        "get_cart",
        handle_get_cart,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    # ─── get_preferences ───────────────────────────────────────
    async def handle_get_preferences(call: ServiceCall) -> dict:
        """Get saved product preferences.

        Returns a map of search terms to preferred products.
        Use this to know what the user typically buys.
        """
        pref_store = _get_pref_store(hass)
        if not pref_store:
            return {"preferences": {}}

        return {"preferences": pref_store.get_all_preferences()}

    hass.services.async_register(
        DOMAIN,
        "get_preferences",
        handle_get_preferences,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )

    # ─── sync_list_to_cart ─────────────────────────────────────
    async def handle_sync_list_to_cart(call: ServiceCall) -> dict:
        """Sync all pending shopping list items to the SPAR cart.

        Searches for each item on the shopping list, adds found products
        to the SPAR cart, and marks them as completed on the list.
        Items that cannot be found are left unchanged on the list.
        """
        coordinator = _get_coordinator(hass)
        if not coordinator:
            return {"added": [], "not_found": [], "errors": [], "total": 0}

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return {"added": [], "not_found": [], "errors": [], "total": 0}

        shopping_list = _get_shopping_list(hass, entries[0].entry_id)
        if not shopping_list:
            return {"added": [], "not_found": [], "errors": [], "total": 0}

        pref_store = _get_pref_store(hass)
        results = await _do_sync_list_to_cart(coordinator, pref_store, shopping_list)
        results["total"] = len(results["added"]) + len(results["not_found"]) + len(results["errors"])
        return results

    hass.services.async_register(
        DOMAIN,
        "sync_list_to_cart",
        handle_sync_list_to_cart,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
