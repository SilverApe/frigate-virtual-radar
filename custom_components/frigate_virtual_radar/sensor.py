"""Sensors in the entity layout Radar Map Manager expects.

Persons:  sensor.<radar>_target_<n>_x / _y  and  sensor.<radar>_presence_target_count
Dogs:     sensor.<radar>_dog_<n>_x / _y     and  sensor.<radar>_dog_count   (RMM ignores these)
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import groups_from, settings
from .const import CONF_CAMERA, CONF_RADAR_NAME, DOMAIN, GROUP_DOG, GROUP_PERSON, SIGNAL_UPDATE
from .tracker import VirtualRadar

PREFIX = {GROUP_PERSON: "target", GROUP_DOG: "dog"}
NAME = {GROUP_PERSON: "Target", GROUP_DOG: "Dog"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    cfg = settings(entry)
    radar: VirtualRadar = entry.runtime_data
    name = cfg[CONF_RADAR_NAME]
    device = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Virtual radar {name}",
        manufacturer="Frigate Virtual Radar",
        model=f"Frigate camera {cfg[CONF_CAMERA]}",
    )
    entities: list[SensorEntity] = []
    for group, (_, size) in groups_from(cfg).items():
        for slot in range(size):
            for axis in ("x", "y"):
                entities.append(CoordSensor(entry, radar, device, name, group, slot, axis))
        entities.append(CountSensor(entry, radar, device, name, group))
    async_add_entities(entities)


class _Base(SensorEntity):
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, radar: VirtualRadar, device: DeviceInfo, group: str) -> None:
        self._entry = entry
        self._radar = radar
        self._group = group
        self._attr_device_info = device

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_UPDATE.format(self._entry.entry_id), self._on_update))

    @callback
    def _on_update(self, keys: set[tuple[str, int]]) -> None:
        if self._wants(keys):
            self.async_write_ha_state()

    def _wants(self, keys: set[tuple[str, int]]) -> bool:
        return any(g == self._group for g, _ in keys)


class CoordSensor(_Base):
    """One axis of one target slot, in cm relative to the camera position (RMM radar frame)."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_suggested_display_precision = 0
    _unrecorded_attributes = frozenset({"frigate_id", "plan_x_m", "plan_y_m", "zones", "score"})

    def __init__(self, entry, radar, device, name: str, group: str, slot: int, axis: str) -> None:
        super().__init__(entry, radar, device, group)
        self._slot = slot
        self._axis = axis
        key = f"{PREFIX[group]}_{slot + 1}_{axis}"
        self.entity_id = f"sensor.{name}_{key}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"{name} {NAME[group]} {slot + 1} {axis.upper()}"

    def _wants(self, keys) -> bool:
        return (self._group, self._slot) in keys

    @property
    def native_value(self) -> float | None:
        t = self._radar.target(self._group, self._slot)
        if t is None:
            return None
        return t.x_cm if self._axis == "x" else t.y_cm

    @property
    def extra_state_attributes(self) -> dict | None:
        t = self._radar.target(self._group, self._slot)
        if t is None or self._axis != "x":
            return None
        return {
            "label": t.label,
            "sub_label": t.sub_label,
            "score": t.score,
            "stationary": t.stationary,
            "zones": t.zones,
            "plan_x_m": t.plan_x,
            "plan_y_m": t.plan_y,
            "frigate_id": t.frigate_id,
        }


class CountSensor(_Base):
    """Number of occupied slots."""

    _attr_native_unit_of_measurement = None

    def __init__(self, entry, radar, device, name: str, group: str) -> None:
        super().__init__(entry, radar, device, group)
        key = "presence_target_count" if group == GROUP_PERSON else "dog_count"
        self.entity_id = f"sensor.{name}_{key}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"{name} {'Persons' if group == GROUP_PERSON else 'Dogs'}"
        self._attr_icon = "mdi:account-multiple" if group == GROUP_PERSON else "mdi:dog"

    @property
    def native_value(self) -> int:
        return self._radar.count(self._group)

    @property
    def extra_state_attributes(self) -> dict:
        names = [t.sub_label for t in self._radar.trackers[self._group].slots if t and t.sub_label]
        return {"names": names}
