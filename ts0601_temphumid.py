import datetime
from typing import Dict

import zigpy.types as t
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
    SKIP_CONFIGURATION,
)
from zhaquirks.tuya import (
    TUYA_SET_TIME,
    NoManufacturerCluster,
    TuyaCommand,
    TuyaEnchantableCluster,
    TuyaLocalCluster,
    TuyaNewManufCluster,
    TuyaPowerConfigurationCluster,
    TuyaTimePayload,
)
from zhaquirks.tuya.mcu import DPToAttributeMapping, EnchantedDevice, TuyaMCUCluster
from zigpy.profiles import zha
from zigpy.quirks import CustomDevice
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    Basic,
    Groups,
    Identify,
    OnOff,
    Ota,
    PowerConfiguration,
    PowerSource,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.measurement import RelativeHumidity, TemperatureMeasurement


class TemperatureUnitConvert(t.enum8):
    """Tuya Temp unit convert enum."""

    Celsius = 0x00
    Fahrenheit = 0x01


class TuyaRelativeHumidity(RelativeHumidity, TuyaLocalCluster):
    """Tuya local RelativeHumidity cluster."""


class TuyaTemperatureMeasurement(TemperatureMeasurement, TuyaLocalCluster):
    """Tuya local TemperatureMeasurement cluster."""

    attributes = TemperatureMeasurement.attributes.copy()
    attributes.update(
        {
            0xEF01: ("temp_unit_convert", t.enum8),
            0xEF02: ("alarm_max_temperature", t.Single),
            0xEF03: ("alarm_min_temperature", t.Single),
            0xEF04: ("temperature_sensitivity", t.Single),
        }
    )


class TuyaPowerConfigurationCluster3AAA(PowerConfiguration, TuyaLocalCluster):
    """PowerConfiguration cluster for battery-operated TRVs with 3 AAA."""

    BATTERY_SIZE = 0x0031
    BATTERY_RATED_VOLTAGE = 0x0034
    BATTERY_QUANTITY = 0x0033

    _CONSTANT_ATTRIBUTES = {
        BATTERY_SIZE: 0x04,
        BATTERY_RATED_VOLTAGE: 15,
        BATTERY_QUANTITY: 3,
    }


# class TuyaSensorManufCluster(TuyaEnchantableCluster, TuyaMCUCluster):
class TuyaSensorManufCluster(TuyaMCUCluster):
    """Manufacturer Specific Cluster"""

    set_time_offset = 1970
    set_time_local_offset = 1970

    server_commands = TuyaNewManufCluster.server_commands.copy()
    server_commands.update(
        {
            TUYA_SET_TIME: foundation.ZCLCommandDef(
                "set_time",
                {"time": TuyaTimePayload},
                False,
                is_manufacturer_specific=False,
            ),
        }
    )

    dp_to_attribute: Dict[int, DPToAttributeMapping] = {
        1: DPToAttributeMapping(
            TuyaTemperatureMeasurement.ep_attribute,
            "measured_value",
            converter=lambda x: x * 10,  # Zigbee to HA
            # dp_converter=lambda x: x / 10, # HA to Zigbee
            # endpoint_id=2, #
        ),
        2: DPToAttributeMapping(
            TuyaRelativeHumidity.ep_attribute,
            "measured_value",
            converter=lambda x: x * 100,  # 0.01 to 1.0
        ),
        4: DPToAttributeMapping(
            TuyaPowerConfigurationCluster3AAA.ep_attribute,
            "battery_percentage_remaining",
            converter=lambda x: x * 2,
        ),
        9: DPToAttributeMapping(
            TuyaTemperatureMeasurement.ep_attribute,
            "temp_unit_convert",
            converter=lambda x: TemperatureUnitConvert(x),
        ),
    }

    data_point_handlers = {
        1: "_dp_2_attr_update",
        2: "_dp_2_attr_update",
        9: "_dp_2_attr_update",
    }


# class TuyaSensor(EnchantedDevice, CustomDevice):
class TuyaSensor(CustomDevice):
    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=0 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_bq5c8xfe", "TS0601"),
            ("_TZE200_locansqn", "TS0601"),
        ],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    TuyaSensorManufCluster.cluster_id,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            }
        },
    }

    replacement = {
        SKIP_CONFIGURATION: True,
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.TEMPERATURE_SENSOR,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    TuyaSensorManufCluster,
                    TuyaTemperatureMeasurement,
                    TuyaRelativeHumidity,
                    TuyaPowerConfigurationCluster3AAA,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
        },
    }
