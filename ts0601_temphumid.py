import datetime
from typing import Any, Dict, Optional, Union

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
    TUYA_MCU_COMMAND,
    TUYA_SET_TIME,
    TuyaLocalCluster,
    TuyaTimePayload,
)
from zhaquirks.tuya.mcu import (
    DPToAttributeMapping,
    TuyaClusterData,
    TuyaMCUCluster,
    TuyaOnOffNM,
)
from zigpy.profiles import zha
from zigpy.quirks import CustomDevice
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    AnalogOutput,
    Basic,
    Groups,
    Identify,
    OnOff,
    Ota,
    PowerConfiguration,
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


class TuyaTempSensivity(AnalogOutput, TuyaLocalCluster):
    """Analog output for temperature sensivity."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature sensivity"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 10)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0.5)
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.5)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    async def command(
        self,
        command_id: Union[foundation.GeneralCommand, int, t.uint8_t],
        *args,
        manufacturer: Optional[Union[int, t.uint16_t]] = None,
        expect_reply: bool = True,
        tsn: Optional[Union[int, t.uint8_t]] = None,
        **kwargs: Any,
    ):
        """Override the default Cluster command."""
        self.debug(
            "Sending Tuya Cluster Command. Cluster Command is %x, Arguments are %s, %s",
            command_id,
            args,
            kwargs,
        )

        if command_id in (0x0000, 0x0001, 0x0004):
            cluster_data = TuyaClusterData(
                endpoint_id=self.endpoint.endpoint_id,
                cluster_name=self.ep_attribute,
                cluster_attr="present_value",
                attr_value=7,
                expect_reply=expect_reply,
                manufacturer=manufacturer,
            )
            self.endpoint.device.command_bus.listener_event(
                TUYA_MCU_COMMAND,
                cluster_data,
            )
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        self.warning("Unsupported command_id: %s", command_id)
        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(command_id=command_id, status=foundation.Status.UNSUP_CLUSTER_COMMAND)


class TuyaManufCluster(TuyaMCUCluster):
    """Manufacturer Specific Cluster"""

    set_time_offset = 1970
    set_time_local_offset = 1970

    server_commands = TuyaMCUCluster.server_commands.copy()
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
            TuyaOnOffNM.ep_attribute,
            "on_off",
            converter=lambda x: bool(x),
            dp_converter=lambda x: TemperatureUnitConvert(x),
        ),
        # 19: DPToAttributeMapping(
        #     TuyaTemperatureMeasurement.ep_attribute,
        #     "temperature_sensitivity",
        #     converter=lambda x: x / 2,
        # ),
        19: DPToAttributeMapping(
            TuyaTempSensivity.ep_attribute,
            "present_value",
            converter=lambda x: x / 2,
        ),
    }

    data_point_handlers = {
        1: "_dp_2_attr_update",
        2: "_dp_2_attr_update",
        4: "_dp_2_attr_update",
        9: "_dp_2_attr_update",
        19: "_dp_2_attr_update",
    }


class TuyaDevice(CustomDevice):
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
                    TuyaManufCluster.cluster_id,
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
                    TuyaManufCluster,
                    TuyaTemperatureMeasurement,
                    TuyaRelativeHumidity,
                    TuyaPowerConfigurationCluster3AAA,
                    TuyaOnOffNM,
                    TuyaTempSensivity,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
        },
    }
