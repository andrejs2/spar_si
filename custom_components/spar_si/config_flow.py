"""Config flow for SPAR Online Slovenija."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SparApiClient, SparAuthError, SparConnectionError
from .const import CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(
            CONF_STORE_REFERENCE, default=DEFAULT_STORE_REFERENCE
        ): str,
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SparSiOptionsFlow:
        """Get the options flow handler."""
        return SparSiOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the integration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = SparApiClient(
                session=session,
                email=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                store_reference=user_input.get(
                    CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE
                ),
            )

            try:
                customer = await client.async_authenticate()
            except SparAuthError:
                errors["base"] = "invalid_auth"
            except SparConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reconfiguration")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                title = customer.name or customer.email
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=f"SPAR Online ({title})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                {
                    CONF_EMAIL: reconfigure_entry.data.get(CONF_EMAIL, ""),
                    CONF_STORE_REFERENCE: reconfigure_entry.data.get(
                        CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE
                    ),
                },
            ),
            errors=errors,
        )

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
                store_reference=user_input.get(CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE),
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
                store_reference=reauth_entry.data.get(CONF_STORE_REFERENCE, DEFAULT_STORE_REFERENCE),
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


CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 5  # minutes

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
        ): vol.All(int, vol.Range(min=1, max=60)),
    }
)


class SparSiOptionsFlow(OptionsFlow):
    """Handle options for SPAR Online Slovenija."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
