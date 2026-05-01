"""Custom ZHA quirk for _TZE284_hodyryli TS0601.

Tuya Temperature/Humidity sensor with external probe and clock display.
Typical use: freezer/refrigerator monitoring with external probe.

Device info:
  Manufacturer: _TZE284_hodyryli
  Model:        TS0601 (Tuya generic model)
  Submodel:     hodyryli (Actual device identifier in Tuya world)
  DPs:
    1  = internal temperature (signed int, /10, °C)
    2  = humidity (%)
    3  = battery state (0=low/~10%, 1=medium/50%, 2=full/100%)
    17 = time format (0=24h, 1=12h)
    38 = external probe temperature (signed int32, /10, °C)  <-- critical for freezer use

Sources:
  https://github.com/zigpy/zha-device-handlers/pull/4520
  https://github.com/zigpy/zha-device-handlers/issues/4489
  https://github.com/Koenkk/zigbee2mqtt/issues/29627

Installation (HAOS):
  1. Copy this file to /config/custom_zha_quirks/tze284_hodyryli.py
  2. Add to /config/configuration.yaml:
       zha:
         custom_quirks_path: /config/custom_zha_quirks
  3. Restart Home Assistant
  4. Re-interview the device if entities don't appear
"""

import zigpy.types as t
from zigpy.quirks.v2.homeassistant import UnitOfTemperature
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass

from zhaquirks.tuya import TuyaPowerConfigurationCluster2AAA
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.tuya_sensor import NoManufTimeTuyaMCUCluster


(
    TuyaQuirkBuilder("_TZE284_hodyryli", "TS0601")
    # DP 1: internal temperature sensor, signed, divide by 10 for °C
    .tuya_temperature(dp_id=1, scale=10)
    # DP 2: relative humidity in %
    .tuya_humidity(dp_id=2)
    # DP 3: battery state → percentage mapping (device only reports 3 levels)
    .tuya_dp(
        dp_id=3,
        ep_attribute=TuyaPowerConfigurationCluster2AAA.ep_attribute,
        attribute_name="battery_percentage_remaining",
        converter=lambda x: {0: 20, 1: 50, 2: 100}.get(x, 0),
    )
    .adds(TuyaPowerConfigurationCluster2AAA)
    # DP 38: external probe temperature
    # MUST use t.int32s (signed) — negative values (freezer!) would otherwise
    # be reported as ~429 million degrees with the unsigned interpretation.
    .tuya_sensor(
        dp_id=38,
        attribute_name="temperature_external",
        type=t.int32s,
        converter=lambda x: x / 10,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="temperature_external",
        fallback_name="Temperature Probe",
    )
    .skip_configuration()
    .add_to_registry(replacement_cluster=NoManufTimeTuyaMCUCluster)
)
