"""Frigate Virtual Radar: turns Frigate person boxes into X/Y radar targets on a floor plan."""
from __future__ import annotations

from datetime import timedelta
import json
import logging
import time

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_CALIBRATION, CONF_CAMERA, CONF_DOG_LABEL, CONF_MAX_DOGS, CONF_MAX_TARGETS, CONF_MIN_MOVE,
    CONF_PERSON_LABELS, CONF_STALE_TIMEOUT, CONF_TOPIC, DEFAULT_MAX_DOGS, DEFAULT_MAX_TARGETS,
    DEFAULT_MIN_MOVE, DEFAULT_PERSON_LABELS, DEFAULT_STALE_TIMEOUT, DEFAULT_TOPIC, GROUP_DOG,
    GROUP_PERSON, SIGNAL_UPDATE,
)
from .geometry import CalibrationError, parse_calibration
from .tracker import VirtualRadar

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


def settings(entry: ConfigEntry) -> dict:
    """Entry data with options on top (options win)."""
    return {**entry.data, **entry.options}


def groups_from(cfg: dict) -> dict[str, tuple[set[str], int]]:
    persons = {s.strip() for s in str(cfg.get(CONF_PERSON_LABELS, DEFAULT_PERSON_LABELS)).split(",") if s.strip()}
    groups = {GROUP_PERSON: (persons or {"person"}, int(cfg.get(CONF_MAX_TARGETS, DEFAULT_MAX_TARGETS)))}
    dog = str(cfg.get(CONF_DOG_LABEL) or "").strip()
    if dog:
        groups[GROUP_DOG] = ({dog}, int(cfg.get(CONF_MAX_DOGS, DEFAULT_MAX_DOGS)))
    return groups


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = settings(entry)
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available yet")

    calibration = None
    try:
        calibration = parse_calibration(cfg.get(CONF_CALIBRATION, ""))
    except CalibrationError as err:
        _LOGGER.warning("%s: no usable calibration yet (%s); targets stay empty until it is set",
                        entry.title, err)

    radar = VirtualRadar(cfg[CONF_CAMERA], calibration, groups_from(cfg),
                         min_move_cm=float(cfg.get(CONF_MIN_MOVE, DEFAULT_MIN_MOVE)))
    entry.runtime_data = radar
    signal = SIGNAL_UPDATE.format(entry.entry_id)

    @callback
    def publish(keys: set[tuple[str, int]]) -> None:
        if keys:
            async_dispatcher_send(hass, signal, keys)

    @callback
    def on_message(msg: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if isinstance(payload, dict):
            publish(radar.handle_event(payload, time.monotonic()))

    entry.async_on_unload(await mqtt.async_subscribe(hass, cfg.get(CONF_TOPIC, DEFAULT_TOPIC), on_message))

    timeout = float(cfg.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT))

    @callback
    def sweep(_now) -> None:
        publish(radar.expire(time.monotonic(), timeout))

    entry.async_on_unload(async_track_time_interval(hass, sweep, timedelta(seconds=30)))
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
