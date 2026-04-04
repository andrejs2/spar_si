"""Data update coordinator for SPAR SI."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import SparApiClient, SparAuthError, SparCart, SparConnectionError
from .const import CART_UPDATE_INTERVAL, DOMAIN

DEFAULT_UPDATE_INTERVAL_MIN = 5

_LOGGER = logging.getLogger(__name__)

type SparConfigEntry = ConfigEntry[SparCoordinator]


class SparCoordinator(DataUpdateCoordinator[SparCart]):
    """Coordinator to fetch SPAR Online cart data."""

    config_entry: SparConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SparConfigEntry,
        client: SparApiClient,
    ) -> None:
        """Initialize the coordinator."""
        interval_min = config_entry.options.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL_MIN
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(minutes=interval_min),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> SparCart:
        """Fetch cart data from SPAR Online."""
        try:
            return await self.client.async_get_cart()
        except SparAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed, please re-authenticate"
            ) from err
        except SparConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error fetching cart: {err}") from err
