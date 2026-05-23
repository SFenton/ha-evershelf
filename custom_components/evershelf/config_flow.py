"""Config flow for EverShelf integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_TOKEN, CONF_URL, DOMAIN
from .coordinator import EverShelfCoordinator

_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Optional(CONF_TOKEN, default=""): str,
    }
)


class EverShelfConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the EverShelf UI setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            token = (user_input.get(CONF_TOKEN) or "").strip()

            coordinator = EverShelfCoordinator(
                self.hass,
                entry_id="test",
                url=url,
                token=token,
            )
            ok, info = await coordinator.async_test_connection()

            if ok:
                # Prevent duplicate entries for the same EverShelf URL
                await self.async_set_unique_id(url.lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"EverShelf ({url})",
                    data={CONF_URL: url, CONF_TOKEN: token},
                )

            errors["base"] = info  # "cannot_connect" or "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=_SCHEMA,
            errors=errors,
        )
