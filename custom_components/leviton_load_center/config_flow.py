"""Config flow for the Leviton integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from aioleviton import (
    LevitonAuthError,
    LevitonClient,
    LevitonConnectionError,
    LevitonInvalidCode,
    LevitonTwoFactorRequired,
)

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CALCULATED_CURRENT,
    CONF_HIDE_DUMMY,
    CONF_READ_ONLY,
    CONF_STAGGER_DELAY,
    CONF_TOKEN,
    CONF_USER_ID,
    CONF_VOLTAGE_208,
    DEFAULT_CALCULATED_CURRENT,
    DEFAULT_HIDE_DUMMY,
    DEFAULT_READ_ONLY,
    DEFAULT_STAGGER_DELAY,
    DEFAULT_VOLTAGE_208,
    DOMAIN,
    LOGGER,
)

CONF_CODE = "code"

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_VOLTAGE_208, default=DEFAULT_VOLTAGE_208): bool,
        vol.Optional(CONF_READ_ONLY, default=DEFAULT_READ_ONLY): bool,
        vol.Optional(
            CONF_CALCULATED_CURRENT, default=DEFAULT_CALCULATED_CURRENT
        ): bool,
        vol.Optional(CONF_HIDE_DUMMY, default=DEFAULT_HIDE_DUMMY): bool,
        vol.Optional(
            CONF_STAGGER_DELAY, default=DEFAULT_STAGGER_DELAY
        ): NumberSelector(
            NumberSelectorConfig(
                min=1, max=10, step=1, mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
    }
)


class LevitonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Leviton."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str = ""
        self._password: str = ""
        self._client: LevitonClient | None = None

    def _entry_data(self) -> dict[str, Any]:
        """Build config entry data including stored token."""
        data: dict[str, Any] = {
            CONF_EMAIL: self._email,
            CONF_PASSWORD: self._password,
        }
        if self._client and self._client.token and self._client.user_id:
            data[CONF_TOKEN] = self._client.token
            data[CONF_USER_ID] = self._client.user_id
        return data

    async def _async_try_2fa_login(self, code: str) -> dict[str, str]:
        """Attempt 2FA login using the existing client, return errors dict."""
        errors: dict[str, str] = {}
        if self._client is None:
            errors["base"] = "unknown"
            return errors
        try:
            await self._client.login(self._email, self._password, code=code)
        except LevitonInvalidCode as err:
            LOGGER.warning("Invalid 2FA code for %s: %s", self._email, err)
            errors["base"] = "invalid_code"
        except LevitonTwoFactorRequired:
            errors["base"] = "invalid_code"
        except LevitonConnectionError as err:
            LOGGER.warning("Connection failed during 2FA for %s: %s", self._email, err)
            errors["base"] = "cannot_connect"
        except LevitonAuthError as err:
            LOGGER.warning("Auth failed during 2FA for %s: %s", self._email, err)
            errors["base"] = "invalid_auth"
        except Exception:
            LOGGER.exception("Unexpected error during 2FA for %s", self._email)
            errors["base"] = "unknown"
        return errors

    def _show_2fa_form(
        self, step_id: str, errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Show the 2FA verification code form."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> LevitonOptionsFlow:
        """Get the options flow for this handler."""
        return LevitonOptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = LevitonClient(session)

            try:
                await client.login(self._email, self._password)
            except LevitonTwoFactorRequired:
                LOGGER.debug("2FA required for %s", self._email)
                self._client = client
                return await self.async_step_2fa()
            except LevitonConnectionError as err:
                LOGGER.warning("Connection failed during login: %s", err)
                errors["base"] = "cannot_connect"
            except LevitonAuthError as err:
                LOGGER.warning("Authentication failed for %s: %s", self._email, err)
                errors["base"] = "invalid_auth"
            except Exception:
                LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            else:
                self._client = client
                await self.async_set_unique_id(
                    self._email.lower().strip()
                )
                self._abort_if_unique_id_configured()
                return await self.async_step_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_2fa(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the 2FA step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_try_2fa_login(user_input[CONF_CODE])
            if not errors:
                await self.async_set_unique_id(
                    self._email.lower().strip()
                )
                self._abort_if_unique_id_configured()
                return await self.async_step_options()

        return self._show_2fa_form("2fa", errors)

    async def async_step_options(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the options step after login."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Leviton Load Center ({self._email})",
                data=self._entry_data(),
                options=user_input,
            )

        return self.async_show_form(
            step_id="options",
            data_schema=OPTIONS_SCHEMA,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle reauth when token expires."""
        self._email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reauth confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = LevitonClient(session)

            try:
                await client.login(self._email, self._password)
            except LevitonTwoFactorRequired:
                self._client = client
                return await self.async_step_2fa_reauth()
            except LevitonConnectionError as err:
                LOGGER.warning("Connection failed during reauth: %s", err)
                errors["base"] = "cannot_connect"
            except LevitonAuthError as err:
                LOGGER.warning("Authentication failed during reauth for %s: %s", self._email, err)
                errors["base"] = "invalid_auth"
            except Exception:
                LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                self._client = client
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data=self._entry_data(),
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_2fa_reauth(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle 2FA during reauth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_try_2fa_login(user_input[CONF_CODE])
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data=self._entry_data(),
                )

        return self._show_2fa_form("2fa_reauth", errors)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = LevitonClient(session)

            try:
                await client.login(email, password)
            except LevitonTwoFactorRequired:
                self._email = email
                self._password = password
                self._client = client
                return await self.async_step_2fa_reconfigure()
            except LevitonConnectionError as err:
                LOGGER.warning("Connection failed during reconfigure: %s", err)
                errors["base"] = "cannot_connect"
            except LevitonAuthError as err:
                LOGGER.warning("Authentication failed during reconfigure for %s: %s", email, err)
                errors["base"] = "invalid_auth"
            except Exception:
                LOGGER.exception("Unexpected error during reconfigure")
                errors["base"] = "unknown"
            else:
                self._email = email
                self._password = password
                self._client = client
                await self.async_set_unique_id(email.lower().strip())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data=self._entry_data(),
                )

        reconfigure_entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EMAIL,
                        default=reconfigure_entry.data.get(CONF_EMAIL, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_2fa_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle 2FA during reconfigure."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._async_try_2fa_login(user_input[CONF_CODE])
            if not errors:
                await self.async_set_unique_id(self._email.lower().strip())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data=self._entry_data(),
                )

        return self._show_2fa_form("2fa_reconfigure", errors)


class LevitonOptionsFlow(OptionsFlow):
    """Handle Leviton options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage Leviton options."""
        if user_input is not None:
            LOGGER.debug("Options updated: %s", user_input)
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
