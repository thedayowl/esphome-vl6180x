# VL6180X ESPHome Component — Development Session Summary

## Objective

Build a production-quality ESPHome external component for the ST VL6180X time-of-flight sensor (range + ALS) and its range-only sibling the VL6180, supporting multiple sensors on a single I2C bus on ESP32 with the esp-idf framework.

---

## Hardware context

- Adafruit VL6180X breakout boards
- XSHUT pin is active-LOW on the bare IC; Adafruit adds a pull-up so the sensor is enabled by default
- All sensors share factory default I2C address 0x29
- Target platform: ESP32-S2-SAOLA-1 with esp-idf framework
- Up to 4 sensors on one I2C bus

---

## Architecture evolution

### Phase 1 — Initial implementation (single sensor, XSHUT toggling)

The first working architecture toggled XSHUT on every `update()` cycle:

- `setup()` — configure GPIO direction only, hold XSHUT LOW
- `update()` — raise XSHUT, run full init on first call (deferred from setup so WiFi logger captures output), take measurements, lower XSHUT

This worked for a single sensor but had a fundamental flaw: every XSHUT LOW→HIGH transition causes the sensor to reload NVM factory defaults, wiping the operational configuration written by `configure_defaults_()`. This meant `configure_defaults_()` had to re-run on every update cycle, adding latency and complexity.

### Phase 2 — Multi-sensor via address assignment (final architecture)

Switched to the same approach used by the Adafruit Arduino library:

- Each sensor is assigned a unique permanent I2C address at boot via register 0x212
- XSHUT is only used during the one-time boot sequencing
- After setup all sensors stay permanently enabled and are read directly by address
- No XSHUT toggling during normal operation — much faster and cleaner

The sequencing requirement: every sensor boots at 0x29, so sensors must be initialised one at a time. The component uses `std::stable_sort` to ensure the sensor keeping address 0x29 is always initialised last, regardless of YAML declaration order.

---

## Key bugs encountered and fixed

### I2C and register issues

- **Deprecated I2C API** — `write(..., false)` replaced with `write_read()`
- **Wrong mandatory register addresses** — AN4545 addresses used verbatim from the ST application note
- **FRESH_OUT_OF_RESET guard** — was skipping mandatory init; removed guard, writes unconditionally
- **Wrong interrupt config register value** — 0x24 broke the polling mechanism; must be 0x00 at init, set per-measurement
- **Wrong completion polling register** — was polling RESULT__RANGE_STATUS bit 0 for completion; switched to RESULT__INTERRUPT_STATUS_GPIO (0x04F) per Adafruit library
- **RANGE_CHECK_ENABLES = 0xFF** — factory default enables early convergence abort, causing error 12 (raw underflow); fixed to 0x10 (SNR check only)
- **Range INT_CFG bits not set** — range new-sample-ready event never asserted; fixed by setting bits [2:0] = 4 before each measurement
- **ALS raw=0** — missing device-ready poll before ALS start; sensor not idle when measurement triggered
- **ALS integration period register** — confirmed 16-bit register at 0x040/0x041, value encodes ms directly
- **ALS gain formula** — lux = 0.32 × raw / gain_factor; gain is optical (already applied by hardware), must divide not multiply

### Architecture bugs

- **XSHUT double-toggle** — `init_sensor_()` was calling `enable_sensor_()`/`disable_sensor_()` internally, then `update()` called enable again — double reset wiped all registers
- **configure_defaults_() not repeating** — after switching to address-assignment architecture, `configure_defaults_()` only ran on first boot; subsequent XSHUT cycles in the old architecture wiped it
- **Coordinator pattern with RawExpression** — `cg.add(VL6180XComponent.register_instance(var))` generated C++ dot notation instead of `::` for static method; reverted to `RawExpression` with explicit namespace
- **setup() pointer comparison** — `all[0] != this` was unreliable; added `static bool sequence_done` fallback
- **Sensor A corrupted by Sensor B init** — Sensor B booting at 0x29 while Sensor A already on bus at 0x29 caused address collision and register corruption; fixed by `std::stable_sort` in `setup()` to ensure the 0x29 sensor is always sequenced last, and pulling ALL XSHUT pins low before sequencing begins
- **init at wrong address** — `setup()` was communicating at the target address (e.g. 0x30) during init, but sensor hadn't been assigned that address yet; fixed by temporarily switching to 0x29 for init, then assigning target address

---

## Features implemented

- Range measurement (mm) with full error code decoding
- ALS / lux measurement with configurable gain
- Independent polling intervals for range and lux on the same sensor
- Multi-sensor support via per-sensor XSHUT GPIO and unique address assignment
- Automatic `stable_sort` in `setup()` ensures the 0x29-addressed sensor is always initialised last — YAML declaration order is irrelevant
- Compile-time validation: `enable_pin` required when >1 sensor; duplicate addresses rejected with descriptive error
- VL6180 (range-only) compatible — identical register map, just omit `lux:` entry
- Single-sensor mode with no `enable_pin` — XSHUT sequencing skipped entirely

---

## Files

```
components/vl6180x/
├── __init__.py     ESPHome Python config schema and code generation
├── vl6180x.h      C++ class declaration, static instance registry
└── vl6180x.cpp    C++ implementation
example_config.yaml
README.md
DEVELOPMENT_SUMMARY.md  (this file)
```

---

## Known limitations and future work

- **ALS lux calibration** — the 0.32 lux/count constant and 20× gain setting are reasonable defaults but the Adafruit breakout cover glass attenuates readings significantly. A configurable `lux_multiplier` YAML parameter would allow field calibration.
- **Configurable ALS gain** — currently hardcoded to 20×. A YAML parameter would allow tuning for different light environments.

## Phase 3 — Non-blocking state machine

### Problem
`update()` contained blocking `while(true)/delay(1)` loops waiting for hardware completion. Range blocked for ~50 ms; ALS blocked for ~130–150 ms (100 ms integration period). ESPHome's main loop is single-threaded — any block beyond ~30 ms degrades WiFi keepalives, OTA updates, and the API connection.

### Solution
Replaced all blocking loops with a state machine driven from `loop()`. `update()` now only kicks off a measurement; `loop()` advances the machine by one step per call, doing minimal I2C work each time and returning immediately.

### States
```
IDLE → RANGE_START → RANGE_WAIT → [ALS_START → ALS_WAIT] → IDLE
```

- **RANGE_START** — configures INT_CFG, checks device-ready bit, fires SYSRANGE_START, transitions to RANGE_WAIT
- **RANGE_WAIT** — polls INTERRUPT_STATUS_GPIO bit 2; when set, reads result and publishes; advances to ALS_START or IDLE
- **ALS_START** — configures INT_CFG, checks device-ready, fires SYSALS_START, transitions to ALS_WAIT
- **ALS_WAIT** — polls INTERRUPT_STATUS_GPIO bits [5:3]; when == 4, reads result and publishes; returns to IDLE

### Timeout handling
Each wait state has a `state_deadline_` (millis-based). If the deadline expires the state returns to IDLE and publishes NAN / "Timeout". No blocking at all — the deadline check is a single comparison per `loop()` call.

### Independent lux timer
The `lux_start_()` method replaces `do_lux_measurement_()`. If the state machine is IDLE it transitions directly to ALS_START. If a range measurement is in progress it sets `lux_pending_ = true`; RANGE_WAIT checks this flag and chains to ALS_START automatically after the range result is published.

### update() guard
If `update()` fires while the state machine is still active (state != IDLE), the new cycle is skipped and a WARNING is logged suggesting the user increase `update_interval`. At any normal polling rate (≥500 ms) this should never fire — the full range+ALS cycle completes in ~180 ms.
