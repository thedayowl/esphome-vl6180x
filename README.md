# VL6180X / VL6180 ESPHome External Component

An ESPHome external component for the ST Microelectronics **VL6180X** (range + ambient light) and **VL6180** (range only) time-of-flight sensors. Supports multiple sensors on a single I2C bus using per-sensor XSHUT GPIO pins for unique address assignment at boot. The number of sensors is limited in practice by available GPIO pins and measurement timing — see [Practical limits](#practical-limits) below.

---

## Features

- Range measurement — 0–200 mm, 1 mm resolution, published in mm
- Range status — text sensor alongside each range sensor reporting `OK`, `No Target`, `Target Too Close`, `Out of Range`, `Hardware Fault`, `Sensor Error`, or `Timeout`
- Ambient light (ALS / lux) — VL6180X only, with independent polling interval
- Multi-sensor — any number of sensors on one I2C bus via per-sensor XSHUT GPIO pins (practical limit is GPIO count and timing budget — see below)
- Unique I2C address assignment — sensors are assigned permanent unique addresses at boot; no XSHUT toggling during normal operation
- Independent polling intervals — range and lux can be polled at different rates
- VL6180 compatible — range-only variant uses identical registers; just omit the `lux:` sub-entry
- Platforms — ESP32 (Arduino and IDF frameworks), ESP8266

---

## Theory of operation

### The address collision problem

All VL6180X/VL6180 sensors share the factory default I2C address **0x29** and the address register is volatile — it resets to 0x29 every time the sensor is powered up or released from hardware reset via the XSHUT pin. Connecting more than one sensor to the same I2C bus at the same address causes bus contention and corrupted readings.

### Address assignment at boot

The component solves this with a one-time sequenced initialisation at startup, mirroring the approach used by the Adafruit Arduino library:

1. **All XSHUT pins are driven LOW** — every sensor is held in hardware reset. The bus is clear.
2. **Sensors are sequenced** — the component automatically sorts sensors so any sensor keeping address 0x29 is initialised last, regardless of the order they appear in YAML. For each sensor in sequence:
   - XSHUT is driven HIGH — the sensor boots at 0x29
   - Mandatory private trim registers are written (ST application note AN4545)
   - Operational defaults are configured
   - The target I2C address is written to register 0x212
   - The sensor remains enabled (XSHUT stays HIGH) — it is now listening at its new address
3. **Normal operation** — all sensors are permanently enabled and polled independently by address. No XSHUT toggling occurs during normal operation, making reads fast and reliable.

### Why the 0x29 sensor is initialised last

Every sensor boots at 0x29. If a sensor whose target address *is* 0x29 were initialised first and left on the bus, the next sensor to be released from reset would also appear at 0x29 — causing an address collision before it can be moved. The component handles this automatically using `std::stable_sort` in `setup()`, so the order sensors appear in YAML does not matter.

### Single sensor

With only one sensor and no `enable_pin` configured, the XSHUT sequencing is skipped entirely. The sensor is initialised directly at 0x29 and stays there.

### Interrupt-based measurement

Rather than polling a status bit, the component configures the sensor's interrupt system for both range and ALS measurements. The `SYSTEM__INTERRUPT_CONFIG` register is set to assert a "new sample ready" event, and `RESULT__INTERRUPT_STATUS_GPIO` is polled for completion. This matches the Adafruit library's approach and avoids false completions from stale status bits.

---

## Hardware wiring

```
VL6180X breakout        ESP32
────────────────        ──────────────────────────
VIN / 3V3           →   3.3 V
GND                 →   GND
SDA                 →   GPIO33  (or any I2C SDA pin)
SCL                 →   GPIO35  (or any I2C SCL pin)
CE / XSHUT          →   GPIO3   (sensor A)
CE / XSHUT          →   GPIO5   (sensor B)
CE / XSHUT          →   GPIO6   (sensor C)  etc.
```

> **XSHUT polarity:** The bare VL6180X IC uses active-LOW XSHUT. Most breakout boards (including Adafruit) add a pull-up resistor so the sensor is enabled by default when XSHUT is unconnected. The component drives XSHUT HIGH to enable and LOW to reset, which is correct for these breakout boards. If your board uses an inverted signal, add `inverted: true` to the `enable_pin` definition.

---

## Installation

1. Copy the `components/vl6180x/` directory into your ESPHome project directory.
2. Add the `external_components` block shown below to your YAML.
3. Add one `vl6180x:` list entry per physical sensor.

--- OR ---

1. reference the github repository

---

## YAML configuration reference

### Minimal — single sensor, no enable pin required

```yaml
external_components:
  - source:
      type: local
      path: components        # folder containing vl6180x/

i2c:
  sda: GPIO33
  scl: GPIO35
  scan: true

vl6180x:
  - id: tof_a
    address: 0x29
    update_interval: 5s
    range:
      name: "Distance"
    range_status:
      name: "Range Status"
    lux:
      name: "Ambient Light"
```

### Multi-sensor — enable_pin required on every entry

```yaml
external_components:
  - source:
      type: local
      path: components

i2c:
  sda: GPIO33
  scl: GPIO35
  id: bus_a
  scan: true

vl6180x:
  - id: tof_a
    i2c_id: bus_a
    address: 0x2A             # unique address for this sensor
    enable_pin: GPIO3         # XSHUT GPIO for this sensor
    update_interval: 2s
    range:
      name: "Sensor A Distance"
    lux:
      name: "Sensor A Ambient Light"
      update_interval: 30s   # independent lux polling interval (optional)

  - id: tof_b
    i2c_id: bus_a
    address: 0x2B
    enable_pin: GPIO5
    update_interval: 2s
    range:
      name: "Sensor B Distance"

  - id: tof_c
    i2c_id: bus_a
    address: 0x29             # sensor keeping default address — must be last
    enable_pin: GPIO6         # (the component sorts this automatically)
    update_interval: 2s
    range:
      name: "Sensor C Distance"
```

### Configuration keys

| Key | Required | Default | Description |
|---|---|---|---|
| `id` | No | auto | ESPHome component ID / C++ variable name |
| `address` | No | `0x29` | Target I2C address for this sensor after boot assignment |
| `enable_pin` | **Yes** when >1 sensor | — | GPIO connected to CE / XSHUT |
| `update_interval` | No | `60s` | Range (and lux if no separate lux interval) polling rate |
| `range` | No | — | Distance sensor sub-entry (see below) |
| `range_status` | No | — | Text sensor reporting the range measurement status (see below) |
| `lux` | No | — | Ambient light sensor sub-entry — VL6180X only (see below) |
| `recovery` | No | — | Health monitoring sub-entry (see below) |

### `range:` sub-entry keys

Accepts all standard ESPHome [sensor schema](https://esphome.io/components/sensor/) keys:

```yaml
range:
  name: "Distance"
  id: my_range_sensor
  filters:
    - sliding_window_moving_average:
        window_size: 5
```

### `range_status:` sub-entry

Publishes the outcome of each range measurement as a human-readable string. Accepts all standard ESPHome [text sensor schema](https://esphome.io/components/text_sensor/) keys.

```yaml
range_status:
  name: "Range Status"
  id: my_range_status
```

**Possible states:**

| State | Meaning |
|---|---|
| `OK` | Valid measurement — distance value is reliable |
| `No Target` | Nothing detected within range (codes 7, 8, 11) |
| `Target Too Close` | Signal saturated — target closer than ~20 mm (codes 6, 12, 14) |
| `Out of Range` | Signal too weak — target likely beyond 200 mm (codes 13, 15) |
| `Hardware Fault` | VCSEL or PLL failure — sensor may need power-cycling (codes 1–5) |
| `Sensor Error` | I2C communication failure |
| `Timeout` | Sensor did not complete measurement within expected window |

The `range_status` sensor is independent of `range` — you can configure one without the other. If only `range_status` is configured (no `range`), measurements still run and the status is still published.

### `lux:` sub-entry keys

Accepts all standard ESPHome sensor schema keys plus one additional key:

| Key | Required | Default | Description |
|---|---|---|---|
| `update_interval` | No | same as top-level | Independent polling interval for lux only |

```yaml
lux:
  name: "Ambient Light"
  update_interval: 60s    # poll lux less frequently than range
```

### `enable_pin:` extended form

```yaml
enable_pin:
  number: GPIO3
  inverted: true          # use if your breakout board has active-LOW XSHUT
  mode:
    output: true
```

### Valid I2C addresses

The VL6180X address register accepts any 7-bit value in the range 0x08–0x77. There is no sensor-side limit on the number of sensors — each just needs a unique address and a dedicated XSHUT GPIO pin.

Suggested address assignments:

| Sensor | Address |
|---|---|
| A | `0x2A` |
| B | `0x2B` |
| C | `0x2C` |
| D | `0x2D` |
| … | … |
| Any | `0x29` ← component always initialises this last automatically |

If only one sensor is used, leave it at `0x29` and omit `enable_pin`.

---

## Practical limits

There is no hard limit in the component code. The realistic constraints are:

**GPIO pins** — each sensor requires one dedicated output-capable GPIO for its XSHUT pin. The number of sensors is therefore bounded by how many GPIOs your board exposes. An ESP32 or ESP32-S2 typically has 20+ usable output GPIOs; an ESP8266 has far fewer.

**Measurement timing** — the component uses a non-blocking state machine. `update()` starts a measurement; `loop()` advances it one step per main-loop iteration while the hardware integrates. The main loop is never blocked waiting for the sensor. Approximate hardware cycle times (for sizing `update_interval`):

| Measurement | Approximate hardware time |
|---|---|
| Range only | ~30–50 ms |
| ALS only | ~130–150 ms (100 ms integration) |
| Range + ALS | ~160–200 ms |

`update_interval` just needs to be longer than the hardware cycle — at any typical interval (500 ms+) there is comfortable headroom. If `update()` fires before the previous cycle has finished, the new cycle is skipped and a WARNING is logged.

As a rule of thumb for multi-sensor setups, note that sensors are polled **independently** at their own addresses — they do not block each other. The only constraint is that each sensor's `update_interval` should exceed its own measurement cycle time.


---

## Health monitoring

The component automatically detects when a sensor has stopped responding and attempts to reinitialise all sensors (Option 1 — full reinit). Healthy sensors that are mid-measurement are allowed to finish before the reinit sequence begins.

### How it works

1. Every I2C-level error and timeout increments a per-sensor `consecutive_failures_` counter. Valid measurement outcomes (`No Target`, `Target Too Close`, `Out of Range`) do **not** count as failures — the sensor is working correctly.
2. When `consecutive_failures_` reaches `failure_threshold_`, the sensor enters `RECOVERY_WAIT` and immediately publishes `Recovering` to the range status text sensor.
3. The instance at position 0 in the sensor list is the designated reinit initiator. It waits until:
   - The `retry_interval` has elapsed, **and**
   - All other sensors have finished any in-progress measurements
4. It then calls a full reinit of all sensors (all XSHUT lines low, then the full boot sequence).
5. If reinit succeeds, all sensors resume normal operation. If it fails, the initiator waits another `retry_interval` and tries again.
6. After `max_retries` failed reinit attempts the sensor is permanently marked failed — it will not recover until the ESP is restarted.

Non-initiator sensors in `RECOVERY_WAIT` simply wait for the initiator to complete reinit, then return to `IDLE`. A single reinit covers all failed sensors simultaneously.

Sensors that fail their very first boot at startup also enter `RECOVERY_WAIT` and are retried automatically — no manual intervention needed.

### `recovery:` sub-entry keys

```yaml
recovery:
  failure_threshold: 3    # consecutive failures before recovery triggers (default: 3)
  retry_interval: 30s     # wait between reinit attempts (default: 30s)
  max_retries: 10         # give up after this many failed reinits (default: 10)
```

| Key | Default | Description |
|---|---|---|
| `failure_threshold` | `3` | Consecutive bad reads (I2C errors, timeouts, hardware faults) before recovery |
| `retry_interval` | `30s` | How long to wait between reinit attempts |
| `max_retries` | `10` | Reinit attempts before the sensor is permanently marked failed |

The `recovery:` block is optional. If omitted, defaults are applied automatically.

### Range status during recovery

| Status | Meaning |
|---|---|
| `Recovering` | Failure threshold reached; reinit in progress or pending |

After successful reinit the status returns to `OK` (or the appropriate measurement state) on the next reading.

---

## Validation rules

The component enforces two rules at compile time:

- **`enable_pin` required when multiple sensors are configured.** Each sensor needs its own XSHUT GPIO so the boot sequencing can work correctly.
- **All `address` values must be unique.** Duplicate addresses produce a clear error message identifying the offending entry.

---

## ALS / lux notes

- The ALS sensor uses 20× analogue gain and 100 ms integration by default, giving a practical indoor range of roughly 0–500 lux.
- The lux formula is `lux = 0.32 × raw / 20.0`, per ST application note AN4545.
- The Adafruit VL6180X breakout has a cover glass over the ALS aperture which attenuates readings by roughly 10–50×. Values will read lower than a calibrated lux meter; this is expected behaviour.
- The VL6180 (no X) variant has no ALS hardware. Omit the `lux:` sub-entry for these sensors.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Failed to read model ID` at boot | Wiring fault or XSHUT not driven HIGH | Check SDA / SCL / XSHUT connections and 3.3 V supply |
| Only first sensor works, others fail | Missing `enable_pin` on some entries | Add `enable_pin` to every entry when using multiple sensors |
| Sensor B corrupts Sensor A | Duplicate addresses | Ensure each sensor has a unique `address` |
| Range always `nan` | Target out of range, or no target | VL6180X range is 0–200 mm; error code is logged at WARNING level |
| Range error 12 (raw underflow) | Target too close | Minimum reliable range is ~20 mm |
| Range error 11 (no target SNR) | No reflective target in range | Normal — sensor reports NaN |
| Lux always 0 | Genuine darkness or cover glass | Try pointing at a bright light source |
| I2C scan finds nothing | Missing pull-ups | Add 4.7 kΩ pull-ups on SDA and SCL to 3.3 V |

Enable DEBUG logging for detailed error codes and init diagnostics:

```yaml
logger:
  level: DEBUG
```

---

## Sensor specifications

| Parameter | Value |
|---|---|
| Range | 0–200 mm |
| Range resolution | 1 mm |
| Range accuracy | ±~3 mm typical (diffuse white target) |
| ALS range | 0–100 000 lux (gain dependent) |
| ALS accuracy | ±10 % typical (without cover glass correction) |
| I2C address (factory) | 0x29 |
| Supply voltage | 2.6–3.3 V (use 3.3 V breakout boards with ESP32) |
| Interface | I2C, 16-bit register addressing |

---

## License

MIT — free to use in personal and commercial ESPHome projects.
