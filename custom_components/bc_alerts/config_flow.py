"""Config flow for BC Alerts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .const import (
    CONF_EAST,
    CONF_ISLAND_ONLY,
    CONF_NEARBY_KM,
    CONF_NORTH,
    CONF_SOUTH,
    CONF_WEST,
    DEFAULT_EAST,
    DEFAULT_ISLAND_ONLY,
    DEFAULT_NEARBY_KM,
    DEFAULT_NORTH,
    DEFAULT_SOUTH,
    DEFAULT_WEST,
    DOMAIN,
)
from .coordinator import BcAlertsConfigEntry

_DEGREES = NumberSelector(
    NumberSelectorConfig(
        min=-180, max=180, step="any", mode=NumberSelectorMode.BOX
    )
)
_KILOMETRES = NumberSelector(
    NumberSelectorConfig(
        min=1,
        max=500,
        step=1,
        mode=NumberSelectorMode.BOX,
        unit_of_measurement="km",
    )
)
_DEFAULTS = {
    CONF_SOUTH: DEFAULT_SOUTH,
    CONF_WEST: DEFAULT_WEST,
    CONF_NORTH: DEFAULT_NORTH,
    CONF_EAST: DEFAULT_EAST,
    CONF_ISLAND_ONLY: DEFAULT_ISLAND_ONLY,
    CONF_NEARBY_KM: DEFAULT_NEARBY_KM,
}
_SELECTORS = {
    CONF_SOUTH: _DEGREES,
    CONF_WEST: _DEGREES,
    CONF_NORTH: _DEGREES,
    CONF_EAST: _DEGREES,
    CONF_ISLAND_ONLY: BooleanSelector(),
    CONF_NEARBY_KM: _KILOMETRES,
}


def _schema(values: Mapping[str, Any]) -> vol.Schema:
    """Return the area form filled in with the given values."""
    return vol.Schema(
        {
            vol.Required(key, default=values.get(key, _DEFAULTS[key])): selector
            for key, selector in _SELECTORS.items()
        }
    )


def _validate(user_input: Mapping[str, Any]) -> dict[str, str]:
    """Return form errors for an area that makes no sense."""
    if (
        user_input[CONF_SOUTH] >= user_input[CONF_NORTH]
        or user_input[CONF_WEST] >= user_input[CONF_EAST]
    ):
        return {"base": "invalid_area"}
    return {}


class BcAlertsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the single BC Alerts entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(entry: BcAlertsConfigEntry) -> BcAlertsOptionsFlow:
        """Return the options flow."""
        return BcAlertsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the area to watch."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = _validate(user_input) if user_input else {}
        if user_input and not errors:
            return self.async_create_entry(title="BC Alerts", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or _DEFAULTS),
            errors=errors,
        )


class BcAlertsOptionsFlow(OptionsFlowWithReload):
    """Change the area to watch."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the area form."""
        errors = _validate(user_input) if user_input else {}
        if user_input and not errors:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(user_input or current), errors=errors
        )
