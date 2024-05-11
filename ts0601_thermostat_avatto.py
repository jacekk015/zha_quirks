"""Avatto TRV devices support."""

import logging
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
    NoManufacturerCluster,
    TuyaManufCluster,
    TuyaManufClusterAttributes,
    TuyaPowerConfigurationCluster,
    TuyaThermostat,
    TuyaThermostatCluster,
    TuyaTimePayload,
    TuyaUserInterfaceCluster,
)
from zhaquirks.tuya.mcu import EnchantedDevice
from zigpy.profiles import zha
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    AnalogOutput,
    Basic,
    GreenPowerProxy,
    Groups,
    OnOff,
    Ota,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.hvac import Thermostat

_LOGGER = logging.getLogger(__name__)

AVATTO_TARGET_TEMP_ATTR = 0x0210  # target room temp (degree)
AVATTO_TEMPERATURE_ATTR = 0x0218  # current room temp (degree)
AVATTO_MODE_ATTR = 0x0402  # [0] manual [1] schedule
AVATTO_SYSTEM_MODE_ATTR = 0x0101  # device [0] off [1] on
AVATTO_HEAT_STATE_ATTR = 0x0424  # [0] heating icon on [1] heating icon off
BEOK_HEAT_STATE_ATTR = 0x0403  # [1] heating icon on [0] heating icon off
AVATTO_CHILD_LOCK_ATTR = 0x0128  # [0] unlocked [1] locked
AVATTO_TEMP_CALIBRATION_ATTR = 0x021B  # temperature calibration (degree)
AVATTO_MIN_TEMPERATURE_VAL = 500  # minimum limit of temperature setting (degree/100)
AVATTO_MAX_TEMPERATURE_VAL = 3000  # maximum limit of temperature setting (degree/100)
AvattoManufClusterSelf = {}


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
            attr_name = self.attributes[record.attrid].name
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

        await AvattoManufClusterSelf[
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


class AvattoManufCluster(TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of thermostatic valves."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        global AvattoManufClusterSelf
        AvattoManufClusterSelf[self.endpoint.device.ieee] = self

    set_time_offset = 1970

    server_commands = {
        0x0000: foundation.ZCLCommandDef(
            "set_data",
            {"param": TuyaManufCluster.Command},
            False,
            is_manufacturer_specific=False,
        ),
        0x0010: foundation.ZCLCommandDef(
            "mcu_version_req",
            {"param": t.uint16_t},
            False,
            is_manufacturer_specific=True,
        ),
        0x0024: foundation.ZCLCommandDef(
            "set_time",
            {"param": TuyaTimePayload},
            False,
            is_manufacturer_specific=False,
        ),
    }

    attributes = TuyaManufClusterAttributes.attributes.copy()
    attributes.update(
        {
            AVATTO_TEMPERATURE_ATTR: ("temperature", t.uint32_t, True),
            AVATTO_TARGET_TEMP_ATTR: ("target_temperature", t.uint32_t, True),
            AVATTO_MODE_ATTR: ("mode", t.uint8_t, True),
            AVATTO_SYSTEM_MODE_ATTR: ("system_mode", t.uint8_t, True),
            AVATTO_HEAT_STATE_ATTR: ("heat_state", t.uint8_t, True),
            BEOK_HEAT_STATE_ATTR: ("beok_heat_state", t.uint8_t, True),
            AVATTO_CHILD_LOCK_ATTR: ("child_lock", t.uint8_t, True),
            AVATTO_TEMP_CALIBRATION_ATTR: ("temperature_calibration", t.int32s, True),
        }
    )

    DIRECT_MAPPED_ATTRS = {
        AVATTO_TEMPERATURE_ATTR: (
            "local_temperature",
            lambda value: value * 100,
            lambda value: value * 10,
        ),
        AVATTO_TARGET_TEMP_ATTR: (
            "occupied_heating_setpoint",
            lambda value: value * 100,
            lambda value: value * 10,
        ),
    }

    def _update_attribute(self, attrid, value):
        """Override default _update_attribute."""
        super()._update_attribute(attrid, value)
        if attrid in self.DIRECT_MAPPED_ATTRS and value < 500:
            if self.endpoint.device.manufacturer in (
                "_TZE200_2ekuz3dz",
                "_TZE200_g9a3awaj",
            ) or (
                attrid == AVATTO_TEMPERATURE_ATTR
                and self.endpoint.device.manufacturer
                in (
                    "_TZE204_u9bfwha0",
                    "_TZE200_u9bfwha0",
                    "_TZE200_aoclfnxz",
                    "_TZE204_aoclfnxz",
                )
            ):
                self.endpoint.device.thermostat_bus.listener_event(
                    "temperature_change",
                    self.DIRECT_MAPPED_ATTRS[attrid][0],
                    (
                        value
                        if self.DIRECT_MAPPED_ATTRS[attrid][2] is None
                        else self.DIRECT_MAPPED_ATTRS[attrid][2](value)
                    ),
                )
            else:
                self.endpoint.device.thermostat_bus.listener_event(
                    "temperature_change",
                    self.DIRECT_MAPPED_ATTRS[attrid][0],
                    (
                        value
                        if self.DIRECT_MAPPED_ATTRS[attrid][1] is None
                        else self.DIRECT_MAPPED_ATTRS[attrid][1](value)
                    ),
                )

        if attrid == AVATTO_TEMP_CALIBRATION_ATTR:
            if self.endpoint.device.manufacturer in (
                "_TZE200_2ekuz3dz",
                "_TZE200_g9a3awaj",
            ):
                self.endpoint.device.AvattoTempCalibration_bus.listener_event(
                    "set_value", value / 10
                )
            else:
                self.endpoint.device.AvattoTempCalibration_bus.listener_event(
                    "set_value", value
                )

        if attrid == AVATTO_CHILD_LOCK_ATTR:
            self.endpoint.device.ui_bus.listener_event("child_lock_change", value)
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "child_lock_change", value
            )
        elif attrid == AVATTO_MODE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("mode_change", value)
        elif attrid == AVATTO_HEAT_STATE_ATTR:
            if self.endpoint.device.manufacturer == "_TZE200_g9a3awaj":
                self.endpoint.device.thermostat_bus.listener_event(
                    "state_change", value
                )
            else:
                self.endpoint.device.thermostat_bus.listener_event(
                    "state_change", not value
                )
        elif attrid == BEOK_HEAT_STATE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("state_change", value)
        elif attrid == AVATTO_SYSTEM_MODE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event(
                "system_mode_change", value
            )


class AvattoThermostat(TuyaThermostatCluster):
    """Thermostat cluster for thermostatic valves."""

    class Preset(t.enum8):
        """Working modes of the thermostat."""

        Away = 0x00
        Schedule = 0x01
        Manual = 0x02
        Comfort = 0x03
        Eco = 0x04
        Boost = 0x05
        Complex = 0x06
        TempManual = 0x07

    class WorkDays(t.enum8):
        """Workday configuration for scheduler operation mode."""

        MonToFri = 0x00
        MonToSat = 0x01
        MonToSun = 0x02

    class ForceValveState(t.enum8):
        """Force valve state option."""

        Normal = 0x00
        Open = 0x01
        Close = 0x02

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
            AVATTO_TARGET_TEMP_ATTR,
            lambda value: round(value / 100),
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
            AVATTO_MIN_TEMPERATURE_VAL,
        )
        self.endpoint.device.thermostat_bus.listener_event(
            "temperature_change",
            "max_heat_setpoint_limit",
            AVATTO_MAX_TEMPERATURE_VAL,
        )

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute in self.DIRECT_MAPPING_ATTRS:
            if self.endpoint.device.manufacturer in (
                "_TZE200_2ekuz3dz",
                "_TZE200_g9a3awaj",
            ):
                return {
                    self.DIRECT_MAPPING_ATTRS[attribute][0]: (
                        value
                        if self.DIRECT_MAPPING_ATTRS[attribute][2] is None
                        else self.DIRECT_MAPPING_ATTRS[attribute][2](value)
                    )
                }
            else:
                return {
                    self.DIRECT_MAPPING_ATTRS[attribute][0]: (
                        value
                        if self.DIRECT_MAPPING_ATTRS[attribute][1] is None
                        else self.DIRECT_MAPPING_ATTRS[attribute][1](value)
                    )
                }

        if attribute == "operation_preset":
            if value == 1:
                return {AVATTO_MODE_ATTR: 1}
            if value == 2:
                return {AVATTO_MODE_ATTR: 0}

        if attribute in ("programing_oper_mode", "occupancy"):
            if attribute == "occupancy":
                occupancy = value
                oper_mode = self._attr_cache.get(
                    self.attributes_by_name["programing_oper_mode"].id,
                    self.ProgrammingOperationMode.Simple,
                )
            else:
                occupancy = self._attr_cache.get(
                    self.attributes_by_name["occupancy"].id, self.Occupancy.Occupied
                )
                oper_mode = value
            if occupancy == self.Occupancy.Occupied:
                if oper_mode == self.ProgrammingOperationMode.Schedule_programming_mode:
                    return {AVATTO_MODE_ATTR: 1}
                if oper_mode == self.ProgrammingOperationMode.Simple:
                    return {AVATTO_MODE_ATTR: 0}
                self.error("Unsupported value for ProgrammingOperationMode")
            else:
                self.error("Unsupported value for Occupancy")

        if attribute == "system_mode":
            if value == self.SystemMode.Off:
                mode = 0
            else:
                mode = 1
            return {AVATTO_SYSTEM_MODE_ATTR: mode}

    def mode_change(self, value):
        """Preset Mode change."""
        if value == 0:
            operation_preset = self.Preset.Manual
            prog_mode = self.ProgrammingOperationMode.Simple
            occupancy = self.Occupancy.Occupied
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


class AvattoUserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    _CHILD_LOCK_ATTR = AVATTO_CHILD_LOCK_ATTR


class AvattoChildLock(CustomTuyaOnOff):
    """On/Off cluster for the child lock function of the electric heating thermostats."""

    def child_lock_change(self, value):
        """Child lock change."""
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""
        if attribute == "on_off":
            return {AVATTO_CHILD_LOCK_ATTR: value}


class AvattoTempCalibration(LocalDataCluster, AnalogOutput):
    """Analog output for Temp Calibration."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.AvattoTempCalibration_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature Calibration"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 10)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, -10)
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)

    def get_value(self):
        """Get value."""
        return self._attr_cache.get(self.attributes_by_name["present_value"].id)

    async def write_attributes(self, attributes, manufacturer=None):
        """Override the default Cluster write_attributes."""
        for attrid, value in attributes.items():
            if isinstance(attrid, str):
                attrid = self.attributes_by_name[attrid].id
            if attrid not in self.attributes:
                self.error("%d is not a valid attribute id", attrid)
                continue
            self._update_attribute(attrid, value)

            if self.endpoint.device.manufacturer in (
                "_TZE200_2ekuz3dz",
                "_TZE200_g9a3awaj",
            ):
                await AvattoManufClusterSelf[
                    self.endpoint.device.ieee
                ].endpoint.tuya_manufacturer.write_attributes(
                    {AVATTO_TEMP_CALIBRATION_ATTR: value * 10},
                    manufacturer=None,
                )
            else:
                await AvattoManufClusterSelf[
                    self.endpoint.device.ieee
                ].endpoint.tuya_manufacturer.write_attributes(
                    {AVATTO_TEMP_CALIBRATION_ATTR: value},
                    manufacturer=None,
                )

        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class Avatto(EnchantedDevice, TuyaThermostat):
    """Avatto Thermostatic radiator valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.AvattoTempCalibration_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=1 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_ye5jkfsb", "TS0601"),
            ("_TZE200_aoclfnxz", "TS0601"),
            ("_TZE200_ztvwu4nk", "TS0601"),
            ("_TZE200_5toc8efa", "TS0601"),
            ("_TZE200_u9bfwha0", "TS0601"),
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
                    AvattoManufCluster,
                    AvattoThermostat,
                    AvattoUserInterface,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [AvattoChildLock],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [AvattoTempCalibration],
                OUTPUT_CLUSTERS: [],
            },
        }
    }


class Beok(EnchantedDevice, TuyaThermostat):
    """Beok Thermostatic radiator valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.AvattoTempCalibration_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=1 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_2ekuz3dz", "TS0601"),
            ("_TZE204_aoclfnxz", "TS0601"),
            ("_TZE204_u9bfwha0", "TS0601"),
            ("_TZE200_g9a3awaj", "TS0601"),
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
            },
            242: {
                PROFILE_ID: 41440,
                DEVICE_TYPE: 97,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
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
                    AvattoManufCluster,
                    AvattoThermostat,
                    AvattoUserInterface,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [AvattoChildLock],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [AvattoTempCalibration],
                OUTPUT_CLUSTERS: [],
            },
            242: {
                PROFILE_ID: 41440,
                DEVICE_TYPE: 97,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        }
    }


class Beok2(EnchantedDevice, TuyaThermostat):
    """Beok Thermostatic radiator valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.AvattoTempCalibration_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=1 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_g9a3awaj", "TS0601"),
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
            },
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
                    AvattoManufCluster,
                    AvattoThermostat,
                    AvattoUserInterface,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [AvattoChildLock],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [AvattoTempCalibration],
                OUTPUT_CLUSTERS: [],
            },
        }
    }
