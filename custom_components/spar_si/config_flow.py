"""Config flow for SPAR Online Slovenija."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SparApiClient, SparAuthError, SparConnectionError
from .const import CONF_STORE_ID, DEFAULT_STORE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_STORE_ID, default=DEFAULT_STORE_ID): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class SparSiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SPAR Online Slovenija."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — user enters credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries for the same email
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = SparApiClient(
                session=session,
                email=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                store_id=user_input.get(CONF_STORE_ID, DEFAULT_STORE_ID),
            )

            try:
                customer = await client.async_authenticate()
            except SparAuthError:
                errors["base"] = "invalid_auth"
            except SparConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during authentication")
                errors["base"] = "unknown"
            else:
                title = customer.name or customer.email
                return self.async_create_entry(
                    title=f"SPAR Online ({title})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when token expires."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-auth confirmation step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            session = async_get_clientsession(self.hass)
            client = SparApiClient(
                session=session,
                email=reauth_entry.data[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                store_id=reauth_entry.data.get(CONF_STORE_ID, DEFAULT_STORE_ID),
            )

            try:
                await client.async_authenticate()
            except SparAuthError:
                errors["base"] = "invalid_auth"
            except SparConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "unknown"
            else:
                new_data = {**reauth_entry.data, **user_input}
                return self.async_update_reload_and_abort(
                    reauth_entry, data=new_data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )
