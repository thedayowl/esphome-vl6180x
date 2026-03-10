"""ESPHome external component configuration schema for VL6180X / VL6180."""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import i2c, sensor, text_sensor
from esphome import pins
from esphome.const import (
    CONF_ID,
    CONF_NUMBER,
    CONF_ADDRESS,
    CONF_UPDATE_INTERVAL,
    DEVICE_CLASS_DISTANCE,
    DEVICE_CLASS_ILLUMINANCE,
    STATE_CLASS_MEASUREMENT,
    UNIT_MILLIMETER,
    UNIT_LUX,
    ICON_RULER,
    ICON_BRIGHTNESS_5,
)

CODEOWNERS = ["@your-github-username"]
DEPENDENCIES = ["i2c"]
AUTO_LOAD = ["sensor", "text_sensor"]

vl6180x_ns = cg.esphome_ns.namespace("vl6180x")
VL6180XComponent = vl6180x_ns.class_(
    "VL6180XComponent", cg.PollingComponent, i2c.I2CDevice
)

CONF_ENABLE_PIN    = "enable_pin"
CONF_RANGE         = "range"
CONF_RANGE_STATUS  = "range_status"
CONF_LUX           = "lux"
CONF_RECOVERY      = "recovery"
CONF_FAILURE_THRESHOLD = "failure_threshold"
CONF_RETRY_INTERVAL    = "retry_interval"
CONF_MAX_RETRIES       = "max_retries"


def _coerce_pin(value):
    if isinstance(value, str):
        value = {CONF_NUMBER: value}
    return pins.gpio_output_pin_schema(value)


RANGE_SENSOR_SCHEMA = sensor.sensor_schema(
    unit_of_measurement=UNIT_MILLIMETER,
    icon=ICON_RULER,
    accuracy_decimals=0,
    device_class=DEVICE_CLASS_DISTANCE,
    state_class=STATE_CLASS_MEASUREMENT,
)

RANGE_STATUS_SCHEMA = text_sensor.text_sensor_schema(
    icon="mdi:map-marker-distance",
)

LUX_SENSOR_SCHEMA = sensor.sensor_schema(
    unit_of_measurement=UNIT_LUX,
    icon=ICON_BRIGHTNESS_5,
    accuracy_decimals=1,
    device_class=DEVICE_CLASS_ILLUMINANCE,
    state_class=STATE_CLASS_MEASUREMENT,
).extend({
    cv.Optional(CONF_UPDATE_INTERVAL): cv.positive_time_period_milliseconds,
})

RECOVERY_SCHEMA = cv.Schema({
    cv.Optional(CONF_FAILURE_THRESHOLD, default=3):
        cv.int_range(min=1, max=255),
    cv.Optional(CONF_RETRY_INTERVAL, default="30s"):
        cv.positive_time_period_milliseconds,
    cv.Optional(CONF_MAX_RETRIES, default=10):
        cv.int_range(min=1, max=255),
})

_ENTRY_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(VL6180XComponent),
            cv.Optional(CONF_ENABLE_PIN): _coerce_pin,
            cv.Optional(CONF_RANGE): RANGE_SENSOR_SCHEMA,
            cv.Optional(CONF_RANGE_STATUS): RANGE_STATUS_SCHEMA,
            cv.Optional(CONF_LUX): LUX_SENSOR_SCHEMA,
            cv.Optional(CONF_RECOVERY): RECOVERY_SCHEMA,
        }
    )
    .extend(cv.polling_component_schema("60s"))
    .extend(i2c.i2c_device_schema(0x29))
)


def _validate(configs):
    if len(configs) > 1:
        for i, entry in enumerate(configs):
            if CONF_ENABLE_PIN not in entry:
                raise cv.Invalid(
                    f"enable_pin is required on every vl6180x entry when more than one "
                    f"sensor is configured (missing on entry {i})",
                    path=[i, CONF_ENABLE_PIN],
                )

    addrs = [entry[CONF_ADDRESS] for entry in configs]
    if len(addrs) != len(set(addrs)):
        seen = set()
        for i, addr in enumerate(addrs):
            if addr in seen:
                raise cv.Invalid(
                    f"Duplicate I2C address 0x{addr:02X} on entry {i} — "
                    f"each vl6180x sensor must have a unique address",
                    path=[i, CONF_ADDRESS],
                )
            seen.add(addr)

    return configs


CONFIG_SCHEMA = cv.All(cv.ensure_list(_ENTRY_SCHEMA), _validate)


async def to_code(config):
    for entry in config:
        var = cg.new_Pvariable(entry[CONF_ID])
        await cg.register_component(var, entry)
        await i2c.register_i2c_device(var, entry)

        cg.add(var.set_name_str(entry[CONF_ID].id))

        cg.add(cg.RawExpression(
            f"esphome::vl6180x::VL6180XComponent::register_instance({entry[CONF_ID].id})"
        ))

        if CONF_ENABLE_PIN in entry:
            pin = await cg.gpio_pin_expression(entry[CONF_ENABLE_PIN])
            cg.add(var.set_enable_pin(pin))

        if CONF_RANGE in entry:
            sens = await sensor.new_sensor(entry[CONF_RANGE])
            cg.add(var.set_range_sensor(sens))

        if CONF_RANGE_STATUS in entry:
            sens = await text_sensor.new_text_sensor(entry[CONF_RANGE_STATUS])
            cg.add(var.set_range_status_sensor(sens))

        if CONF_LUX in entry:
            lux_conf = entry[CONF_LUX]
            sens = await sensor.new_sensor(lux_conf)
            cg.add(var.set_lux_sensor(sens))
            if CONF_UPDATE_INTERVAL in lux_conf:
                cg.add(var.set_lux_update_interval(lux_conf[CONF_UPDATE_INTERVAL]))

        if CONF_RECOVERY in entry:
            rec = entry[CONF_RECOVERY]
            cg.add(var.set_failure_threshold(rec[CONF_FAILURE_THRESHOLD]))
            cg.add(var.set_retry_interval(rec[CONF_RETRY_INTERVAL]))
            cg.add(var.set_max_retries(rec[CONF_MAX_RETRIES]))
