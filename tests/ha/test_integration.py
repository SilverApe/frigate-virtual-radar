"""End-to-end tests in a real Home Assistant: config flow over HTTP, MQTT in, sensors out."""
import json

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.frigate_virtual_radar.const import DOMAIN

# Calibration: image pixels map linearly onto a 9.6 x 5.4 m floor (1 px = 0.5 cm).
CAL = json.dumps({
    "camera": "camera_01",
    "image_size": [1920, 1080],
    "points": [
        {"img": [0, 0], "plan": [0, 0]},
        {"img": [1920, 0], "plan": [9.6, 0]},
        {"img": [1920, 1080], "plan": [9.6, 5.4]},
        {"img": [0, 1080], "plan": [0, 5.4]},
    ],
    "origin": [4.8, 5.4],
})

BASE = {
    "camera": "camera_01", "radar_name": "cam01", "max_targets": 3, "person_labels": "person",
    "dog_label": "dog", "max_dogs": 1, "min_move": 5, "stale_timeout": 1800,
    "topic": "frigate/events", "calibration": CAL,
}


async def test_flow_over_http(hass: HomeAssistant, hass_client, mqtt_mock) -> None:
    """The UI path that returned 400 before: POST the flow, get a form, submit it."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await client.post("/api/config/config_entries/flow", json={"handler": DOMAIN})
    assert resp.status == 200, await resp.text()
    form = await resp.json()
    assert form["type"] == "form" and form["step_id"] == "user"
    keys = {f["name"] for f in form["data_schema"]}
    assert {"camera", "radar_name", "calibration"} <= keys

    resp = await client.post(f"/api/config/config_entries/flow/{form['flow_id']}", json=BASE)
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["type"] == "create_entry"


async def test_bad_calibration_rejected(hass: HomeAssistant, mqtt_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**BASE, "calibration": "{nope"})
    assert result["type"] == "form"
    assert result["errors"] == {"calibration": "invalid_calibration"}


async def test_bad_name_rejected(hass: HomeAssistant, mqtt_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**BASE, "radar_name": "Cam 01"})
    assert result["errors"] == {"radar_name": "invalid_name"}


def event(kind, fid, box, label="person", **extra):
    return json.dumps({"type": kind, "after": {"id": fid, "camera": "camera_01", "label": label, "box": box, **extra}})


async def test_mqtt_to_sensors(hass: HomeAssistant, mqtt_mock) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=BASE, unique_id="cam01", title="camera_01 → cam01")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for eid in ("sensor.cam01_target_1_x", "sensor.cam01_target_3_y", "sensor.cam01_presence_target_count",
                "sensor.cam01_dog_1_x", "sensor.cam01_dog_count"):
        assert hass.states.get(eid) is not None, eid
    assert hass.states.get("sensor.cam01_target_1_x").state == "unknown"

    # Foot point at pixel (960, 540) -> plan (4.8, 2.7) m -> radar frame (0, +270) cm.
    async_fire_mqtt_message(hass, "frigate/events", event("new", "a", [900, 100, 1020, 540], sub_label=["Aaron", 0.92]))
    await hass.async_block_till_done()
    x = hass.states.get("sensor.cam01_target_1_x")
    assert float(x.state) == 0.0
    assert float(hass.states.get("sensor.cam01_target_1_y").state) == 270.0
    assert x.attributes["unit_of_measurement"] == "cm"
    assert x.attributes["sub_label"] == "Aaron"
    assert hass.states.get("sensor.cam01_presence_target_count").state == "1"

    # A dog never lands in a person slot.
    async_fire_mqtt_message(hass, "frigate/events", event("new", "d", [100, 900, 200, 1080], label="dog"))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.cam01_presence_target_count").state == "1"
    assert hass.states.get("sensor.cam01_dog_count").state == "1"

    # Another camera is ignored.
    other = json.dumps({"type": "new", "after": {"id": "z", "camera": "garage", "label": "person", "box": [0, 0, 10, 10]}})
    async_fire_mqtt_message(hass, "frigate/events", other)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.cam01_presence_target_count").state == "1"

    # End frees the slot.
    async_fire_mqtt_message(hass, "frigate/events", event("end", "a", [900, 100, 1020, 540]))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.cam01_target_1_x").state == "unknown"
    assert hass.states.get("sensor.cam01_presence_target_count").state == "0"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_updates_calibration(hass: HomeAssistant, mqtt_mock) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={**BASE, "calibration": ""}, unique_id="cam01")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    opts = {k: v for k, v in BASE.items() if k not in ("camera", "radar_name")}
    result = await hass.config_entries.options.async_configure(result["flow_id"], opts)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["calibration"] == CAL
