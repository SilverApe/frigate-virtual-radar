"""Config and options flow: everything is set from the Home Assistant UI."""
from __future__ import annotations

import re
from typing import Any

try:  # Home Assistant 2026.10+ validates with probatio
    import probatio as vol
except ImportError:  # older releases still use voluptuous
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector, NumberSelectorConfig, NumberSelectorMode, SelectSelector, SelectSelectorConfig,
    SelectSelectorMode, TextSelector, TextSelectorConfig,
)

from .const import (
    CONF_CALIBRATION, CONF_CAMERA, CONF_DOG_LABEL, CONF_MAX_DOGS, CONF_MAX_TARGETS, CONF_MIN_MOVE,
    CONF_PERSON_LABELS, CONF_RADAR_NAME, CONF_STALE_TIMEOUT, CONF_TOPIC, DEFAULT_DOG_LABEL,
    DEFAULT_MAX_DOGS, DEFAULT_MAX_TARGETS, DEFAULT_MIN_MOVE, DEFAULT_PERSON_LABELS,
    DEFAULT_STALE_TIMEOUT, DEFAULT_TOPIC, DOMAIN, MAX_TARGETS_LIMIT,
)
from .geometry import CalibrationError, parse_calibration

SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


def _frigate_cameras(hass) -> list[str]:
    """Camera names exposed by the Frigate integration (camera.* with a camera_name attribute)."""
    names = {s.attributes.get("camera_name") for s in hass.states.async_all("camera")
             if s.attributes.get("client_id") == "frigate"}
    return sorted(n for n in names if n)


def _int(lo: int, hi: int, step: int = 1, unit: str | None = None) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=lo, max=hi, step=step, mode=NumberSelectorMode.BOX,
                                               unit_of_measurement=unit))


def _tuning_schema(d: dict) -> dict:
    return {
        vol.Required(CONF_MAX_TARGETS, default=d.get(CONF_MAX_TARGETS, DEFAULT_MAX_TARGETS)): _int(1, MAX_TARGETS_LIMIT),
        vol.Required(CONF_PERSON_LABELS, default=d.get(CONF_PERSON_LABELS, DEFAULT_PERSON_LABELS)): TextSelector(),
        vol.Optional(CONF_DOG_LABEL, default=d.get(CONF_DOG_LABEL, DEFAULT_DOG_LABEL)): TextSelector(),
        vol.Required(CONF_MAX_DOGS, default=d.get(CONF_MAX_DOGS, DEFAULT_MAX_DOGS)): _int(1, MAX_TARGETS_LIMIT),
        vol.Required(CONF_MIN_MOVE, default=d.get(CONF_MIN_MOVE, DEFAULT_MIN_MOVE)): _int(0, 50, unit="cm"),
        vol.Required(CONF_STALE_TIMEOUT, default=d.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT)): _int(30, 86400, unit="s"),
        vol.Required(CONF_TOPIC, default=d.get(CONF_TOPIC, DEFAULT_TOPIC)): TextSelector(),
        vol.Optional(CONF_CALIBRATION, default=d.get(CONF_CALIBRATION, "")): TextSelector(TextSelectorConfig(multiline=True)),
    }


def _check_calibration(user_input: dict, errors: dict) -> None:
    text = str(user_input.get(CONF_CALIBRATION) or "").strip()
    if not text:
        return  # allowed: the sensors stay empty until a calibration is pasted
    try:
        parse_calibration(text)
    except CalibrationError:
        errors[CONF_CALIBRATION] = "invalid_calibration"


class FrigateVirtualRadarConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_RADAR_NAME].strip().lower()
            user_input[CONF_RADAR_NAME] = name
            if not SLUG.match(name):
                errors[CONF_RADAR_NAME] = "invalid_name"
            _check_calibration(user_input, errors)
            if not errors:
                await self.async_set_unique_id(name)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"{user_input[CONF_CAMERA]} → {name}", data=user_input)

        cams = _frigate_cameras(self.hass)
        d = user_input or {}
        schema = {
            vol.Required(CONF_CAMERA, default=d.get(CONF_CAMERA, cams[0] if cams else "")): SelectSelector(
                SelectSelectorConfig(options=cams, custom_value=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required(CONF_RADAR_NAME, default=d.get(CONF_RADAR_NAME, "")): TextSelector(),
            **_tuning_schema(d),
        }
        return self.async_show_form(step_id="user", data_schema=vol.Schema(schema), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FrigateVirtualRadarOptionsFlow()


class FrigateVirtualRadarOptionsFlow(OptionsFlow):
    """Change everything except camera and radar name (those fix the entity IDs)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input.setdefault(CONF_DOG_LABEL, "")  # an emptied field means: no dog sensors
            user_input.setdefault(CONF_CALIBRATION, "")
            _check_calibration(user_input, errors)
            if not errors:
                return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}
        return self.async_show_form(step_id="init", data_schema=vol.Schema(_tuning_schema(current)), errors=errors)
