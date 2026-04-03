"""The SPAR Online Slovenija integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SparApiClient, SparAuthError, SparConnectionError
from .const import CONF_STORE_ID, DEFAULT_STORE_ID, DOMAIN
from .coordinator import SparConfigEntry, SparCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TODO]


async def async_setup_entry(
    hass: HomeAssistant, entry: SparConfigEntry
) -> bool:
    """Set up SPAR Online from a config entry."""
    session = async_get_clientsession(hass)
    client = SparApiClient(
        session=session,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        store_id=entry.data.get(CONF_STORE_ID, DEFAULT_STORE_ID),
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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SparConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    if hass.services.has_service(DOMAIN, "search_products"):
        return  # Already registered

    async def handle_search_products(call: ServiceCall) -> dict:
        """Handle the search_products service call."""
        query = call.data["query"]
        max_results = call.data.get("max_results", 10)

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return {"products": []}

        coordinator: SparCoordinator = entries[0].runtime_data
        products = await coordinator.client.async_search_products(
            query=query, page_size=max_results
        )

        return {
            "products": [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "price": p.price,
                    "unit": p.unit,
                    "brand": p.brand,
                    "is_available": p.is_available,
                    "image_url": p.image_url,
                }
                for p in products
            ]
        }

    hass.services.async_register(
        DOMAIN,
        "search_products",
        handle_search_products,
        schema=vol.Schema(
            {
                vol.Required("query"): str,
                vol.Optional("max_results", default=10): vol.All(
                    int, vol.Range(min=1, max=50)
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
