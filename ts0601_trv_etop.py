"""Etop TRV devices support."""
import logging
import math
from typing import Optional, Union

import zigpy.types as t
from zhaquirks import Bus, LocalDataCluster
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.tuya import (
    TuyaManufClusterAttributes,
    TuyaPowerConfigurationCluster,
    TuyaThermostat,
    TuyaThermostatCluster,
    TuyaUserInterfaceCluster,
)
from zhaquirks.tuya.mcu import EnchantedDevice
from zigpy.profiles import zha
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    AnalogOutput,
    Basic,
    BinaryInput,
    Groups,
    Identify,
    OnOff,
    Ota,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.hvac import Thermostat

_LOGGER = logging.getLogger(__name__)


ETOP_TARGET_TEMP_ATTR = 0x0210  # target temp, degrees/10
ETOP_TEMPERATURE_ATTR = 0x0218  # current room temp, degrees/10
ETOP_PRESET_ATTR = 0x0402  # [0] manual [1] away [2] scheduled
ETOP_SYSTEM_MODE_ATTR = 0x0101  # [0] off [1] heat
ETOP_BATTERY_STATE_ATTR = 0x0523  # [0] OK [1] Empty
ETOP_WINDOW_DETECT_FUNC_ATTR = 0x0108  # [0] off [1] on
ETOP_MIN_TEMPERATURE_VAL = 5
ETOP_MAX_TEMPERATURE_VAL = 30
EtopManufClusterSelf = {}

# TUYA_DP_TYPE_RAW = 0x0000
# TUYA_DP_TYPE_BOOL = 0x0100
# TUYA_DP_TYPE_VALUE = 0x0200
# TUYA_DP_TYPE_STRING = 0x0300
# TUYA_DP_TYPE_ENUM = 0x0400
# TUYA_DP_TYPE_FAULT = 0x0500


class CustomTuyaOnOff(LocalDataCluster, OnOff):
    """Custom Tuya OnOff cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.thermostat_onoff_bus.add_listener(self)

    # pylint: disable=R0201
    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""
        return {}

    async def write_attributes(self, attributes, manufacturer=None):
        """Implement writeable attributes."""

        records = self._write_attr_records(attributes)

        if not records:
            return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]

        manufacturer_attrs = {}
        for record in records:
            attr_name = self.attributes[record.attrid][0]
            new_attrs = self.map_attribute(attr_name, record.value.value)

            _LOGGER.debug(
                "[0x%04x:%s:0x%04x] Mapping standard %s (0x%04x) "
                "with value %s to custom %s",
                self.endpoint.device.nwk,
                self.endpoint.endpoint_id,
                self.cluster_id,
                attr_name,
                record.attrid,
                repr(record.value.value),
                repr(new_attrs),
            )

            manufacturer_attrs.update(new_attrs)

        if not manufacturer_attrs:
            return [
                [
                    foundation.WriteAttributesStatusRecord(
                        foundation.Status.FAILURE, r.attrid
                    )
                    for r in records
                ]
            ]

        await EtopManufClusterSelf[
            self.endpoint.device.ieee
        ].endpoint.tuya_manufacturer.write_attributes(
            manufacturer_attrs, manufacturer=manufacturer
        )

        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]

    async def command(
        self,
        command_id: Union[foundation.GeneralCommand, int, t.uint8_t],
        *args,
        manufacturer: Optional[Union[int, t.uint16_t]] = None,
        expect_reply: bool = True,
        tsn: Optional[Union[int, t.uint8_t]] = None,
    ):
        """Override the default Cluster command."""

        if command_id in (0x0000, 0x0001, 0x0002):

            if command_id == 0x0000:
                value = False
            elif command_id == 0x0001:
                value = True
            else:
                attrid = self.attributes_by_name["on_off"].id
                success, _ = await self.read_attributes(
                    (attrid,), manufacturer=manufacturer
                )
                try:
                    value = success[attrid]
                except KeyError:
                    return foundation.Status.FAILURE
                value = not value

            (res,) = await self.write_attributes(
                {"on_off": value},
                manufacturer=manufacturer,
            )
            return [command_id, res[0].status]

        return [command_id, foundation.Status.UNSUP_CLUSTER_COMMAND]


class EtopManufCluster(TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of some thermostatic valves."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.EtopManufCluster_bus.add_listener(self)
        global EtopManufClusterSelf
        EtopManufClusterSelf[self.endpoint.device.ieee] = self

    set_time_offset = 1970

    attributes = TuyaManufClusterAttributes.attributes.copy()
    attributes.update(
        {
            ETOP_TARGET_TEMP_ATTR: (
                "target_temperature",
                t.uint32_t,
                True,
            ),
            ETOP_TEMPERATURE_ATTR: ("temperature", t.uint32_t, True),
            ETOP_PRESET_ATTR: ("preset", t.uint8_t, True),
            ETOP_SYSTEM_MODE_ATTR: ("system_mode", t.uint8_t, True),
            ETOP_BATTERY_STATE_ATTR: ("battery_state", t.uint8_t, True),
            ETOP_WINDOW_DETECT_FUNC_ATTR: ("window_detection_func", t.uint8_t, True),
        }
    )

    DIRECT_MAPPED_ATTRS = {
        ETOP_TEMPERATURE_ATTR: (
            "local_temperature",
            lambda value: value * 10,
        ),
        ETOP_TARGET_TEMP_ATTR: (
            "occupied_heating_setpoint",
            lambda value: value * 10,
        ),
    }

    def _update_attribute(self, attrid, value):
        """Override default _update_attribute."""
        super()._update_attribute(attrid, value)

        if attrid in self.DIRECT_MAPPED_ATTRS:
            self.endpoint.device.thermostat_bus.listener_event(
                "temperature_change",
                self.DIRECT_MAPPED_ATTRS[attrid][0],
                value
                if self.DIRECT_MAPPED_ATTRS[attrid][1] is None
                else self.DIRECT_MAPPED_ATTRS[attrid][1](value),
            )

        if attrid == ETOP_PRESET_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("preset_change", value)
        elif attrid == ETOP_SYSTEM_MODE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event(
                "system_mode_change", value
            )
        elif attrid == ETOP_BATTERY_STATE_ATTR:
            self.endpoint.device.battery_bus.listener_event(
                "battery_change", 0 if value == 1 else 100
            )
        elif attrid == ETOP_WINDOW_DETECT_FUNC_ATTR:
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "window_detect_func_change", value
            )


class EtopThermostat(TuyaThermostatCluster):
    """Thermostat cluster for some thermostatic valves."""

    class Preset(t.enum8):
        """Working modes of the thermostat."""

        Away = 0x00
        Schedule = 0x01
        Manual = 0x02
        Comfort = 0x03
        Eco = 0x04
        Boost = 0x05
        Complex = 0x06

    _CONSTANT_ATTRIBUTES = {
        0x001B: Thermostat.ControlSequenceOfOperation.Heating_Only,
    }

    attributes = TuyaThermostatCluster.attributes.copy()
    attributes.update(
        {
            0x4002: ("operation_preset", Preset, True),
        }
    )

    DIRECT_MAPPING_ATTRS = {
        "occupied_heating_setpoint": (
            ETOP_TARGET_TEMP_ATTR,
            lambda value: round(value / 10),
        ),
    }

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.thermostat_bus.add_listener(self)
        self.endpoint.device.thermostat_bus.listener_event(
            "temperature_change",
            "min_heat_setpoint_limit",
            ETOP_MIN_TEMPERATURE_VAL * 100,
        )
        self.endpoint.device.thermostat_bus.listener_event(
            "temperature_change",
            "max_heat_setpoint_limit",
            ETOP_MAX_TEMPERATURE_VAL * 100,
        )

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute in self.DIRECT_MAPPING_ATTRS:
            return {
                self.DIRECT_MAPPING_ATTRS[attribute][0]: value
                if self.DIRECT_MAPPING_ATTRS[attribute][1] is None
                else self.DIRECT_MAPPING_ATTRS[attribute][1](value)
            }

        if attribute == "operation_preset":
            if value == self.Preset.Manual:
                return {ETOP_PRESET_ATTR: 0}
            if value == self.Preset.Away:
                return {ETOP_PRESET_ATTR: 1}
            if value == self.Preset.Schedule:
                return {ETOP_PRESET_ATTR: 2}

        if attribute == "system_mode":
            if value == self.SystemMode.Off:
                mode = 0
            else:
                mode = 1
            return {ETOP_SYSTEM_MODE_ATTR: mode}

    def preset_change(self, value):
        """Preset change."""
        if value == 0:
            operation_preset = self.Preset.Manual
            prog_mode = self.ProgrammingOperationMode.Simple
            occupancy = self.Occupancy.Occupied
        elif value == 1:
            operation_preset = self.Preset.Away
            prog_mode = self.ProgrammingOperationMode.Simple
            occupancy = self.Occupancy.Unoccupied
        else:
            operation_preset = self.Preset.Schedule
            prog_mode = self.ProgrammingOperationMode.Schedule_programming_mode
            occupancy = self.Occupancy.Occupied

        self._update_attribute(
            self.attributes_by_name["programing_oper_mode"].id, prog_mode
        )
        self._update_attribute(self.attributes_by_name["occupancy"].id, occupancy)
        self._update_attribute(
            self.attributes_by_name["operation_preset"].id, operation_preset
        )

    def system_mode_change(self, value):
        """System Mode change."""
        if value == 0:
            mode = self.SystemMode.Off
        else:
            mode = self.SystemMode.Heat
        self._update_attribute(self.attributes_by_name["system_mode"].id, mode)


class EtopUserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    # _CHILD_LOCK_ATTR = MAXSMART_CHILD_LOCK_ATTR


class EtopWindowDectection(CustomTuyaOnOff):
    """Open Window Detection function support"""

    def window_detect_func_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {ETOP_WINDOW_DETECT_FUNC_ATTR: value}


class Etop(EnchantedDevice, TuyaThermostat):
    """Etop Thermostatic radiator valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.EtopManufCluster_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=0 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_0hg58wyk", "TS0601"),
        ],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    TuyaManufClusterAttributes.cluster_id,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            }
        },
    }

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.THERMOSTAT,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    EtopManufCluster,
                    EtopThermostat,
                    EtopUserInterface,
                    EtopWindowDectection,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            }
        }
    }
