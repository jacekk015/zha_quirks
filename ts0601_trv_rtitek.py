"""RtiTek TRV devices support."""
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
    TuyaManufCluster,
    TuyaManufClusterAttributes,
    TuyaPowerConfigurationCluster,
    TuyaThermostat,
    TuyaThermostatCluster,
    TuyaTimePayload,
    TuyaUserInterfaceCluster,
)
from zigpy.profiles import zha
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    AnalogOutput,
    Basic,
    BinaryInput,
    Groups,
    OnOff,
    Ota,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.hvac import Thermostat

_LOGGER = logging.getLogger(__name__)

RTI_TARGET_TEMP_ATTR = 0x0202  # target room temp (decidegree)
RTI_TEMPERATURE_ATTR = 0x0203  # current room temp (decidegree)
RTI_MODE_ATTR = 0x0401  # [0] schedule [1] manual [2] off [3] on
RTI_CHILD_LOCK_ATTR = 0x010C  # [0] unlocked [1] locked
RTI_TEMP_CALIBRATION_ATTR = 0x0265  # temperature calibration (degree)
RTI_MIN_TEMPERATURE_ATTR = 0x020F  # minimum limit of temperature setting (decidegree)
RTI_MAX_TEMPERATURE_ATTR = 0x0210  # maximum limit of temperature setting (decidegree)
RTI_WINDOW_DETECT_ATTR = 0x0108  # [0] alarm not active [1] alarm active
RTI_BOOST_ATTR = 0x0104  # [0] off [1] on
RTI_BOOST_COUNTDOWN_ATTR = 0x0205  # (seconds)
RTI_VALVE_POSITION_ATTR = 0x0266  # opening percentage /10
RTI_VALVE_STATE_ATTR = 0x0406  # [0] closed [1] opened
RTI_BATTERY_ATTR = 0x020D  # battery percentage remaining 0-100%
RTI_SOFT_VER_ATTR = 0x0296  # 109 means 1.0.9
RtiManufClusterSelf = {}


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

        await RtiManufClusterSelf[
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


class RtiManufCluster(TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of thermostatic valves."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        global RtiManufClusterSelf
        RtiManufClusterSelf[self.endpoint.device.ieee] = self

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
            RTI_TEMPERATURE_ATTR: ("temperature", t.uint32_t),
            RTI_TARGET_TEMP_ATTR: ("target_temperature", t.uint32_t),
            RTI_MODE_ATTR: ("mode", t.uint8_t),
            RTI_CHILD_LOCK_ATTR: ("child_lock", t.uint8_t),
            RTI_TEMP_CALIBRATION_ATTR: ("temperature_calibration", t.int32s),
            RTI_MIN_TEMPERATURE_ATTR: ("min_temperature", t.uint32_t),
            RTI_MAX_TEMPERATURE_ATTR: ("max_temperature", t.uint32_t),
            RTI_WINDOW_DETECT_ATTR: ("window_detection", t.uint8_t),
            RTI_BOOST_ATTR: ("boost_enabled", t.uint8_t),
            RTI_BOOST_COUNTDOWN_ATTR: ("boost_duration_seconds", t.uint32_t),
            RTI_VALVE_POSITION_ATTR: ("valve_position", t.uint32_t),
            RTI_VALVE_STATE_ATTR: ("valve_state", t.uint8_t),
            RTI_BATTERY_ATTR: ("battery", t.uint32_t),
            RTI_SOFT_VER_ATTR: ("software_version", t.uint32_t),
        }
    )

    DIRECT_MAPPED_ATTRS = {
        RTI_TEMPERATURE_ATTR: ("local_temperature", lambda value: value * 10),
        RTI_TARGET_TEMP_ATTR: ("occupied_heating_setpoint", lambda value: value * 10),
        RTI_TEMP_CALIBRATION_ATTR: (
            "local_temperature_calibration",
            lambda value: value * 10,
        ),
        RTI_MIN_TEMPERATURE_ATTR: (
            "min_heat_setpoint_limit",
            lambda value: value * 10,
        ),
        RTI_MAX_TEMPERATURE_ATTR: (
            "max_heat_setpoint_limit",
            lambda value: value * 10,
        ),
        RTI_VALVE_POSITION_ATTR: (
            "valve_position",
            lambda value: value * 10,
        ),
    }

    def _update_attribute(self, attrid, value):
        """Override default _update_attribute."""
        super()._update_attribute(attrid, value)
        if attrid in self.DIRECT_MAPPED_ATTRS and value < 60000:
            self.endpoint.device.thermostat_bus.listener_event(
                "temperature_change",
                self.DIRECT_MAPPED_ATTRS[attrid][0],
                value
                if self.DIRECT_MAPPED_ATTRS[attrid][1] is None
                else self.DIRECT_MAPPED_ATTRS[attrid][1](value),
            )

        if attrid == RTI_WINDOW_DETECT_ATTR:
            self.endpoint.device.RtiWindowDetection_bus.listener_event(
                "set_value", value
            )
        elif attrid == RTI_CHILD_LOCK_ATTR:
            self.endpoint.device.ui_bus.listener_event("child_lock_change", value)
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "child_lock_change", value
            )
        elif attrid in (RTI_MODE_ATTR, RTI_BOOST_ATTR):
            if attrid == RTI_BOOST_ATTR and value == 1:
                self.endpoint.device.thermostat_bus.listener_event("mode_change", 5)
            elif attrid == RTI_MODE_ATTR:
                self.endpoint.device.thermostat_bus.listener_event("mode_change", value)
        elif attrid == RTI_VALVE_POSITION_ATTR:
            self.endpoint.device.RtiValvePosition_bus.listener_event(
                "set_value", value / 10
            )
        elif attrid == RTI_VALVE_STATE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("state_change", value)
        elif attrid == RTI_TEMP_CALIBRATION_ATTR:
            self.endpoint.device.RtiTempCalibration_bus.listener_event(
                "set_value", value / 10
            )
        elif attrid == RTI_BOOST_COUNTDOWN_ATTR:
            self.endpoint.device.RtiBoostCountdown_bus.listener_event(
                "set_value", value
            )
        elif attrid == RTI_BATTERY_ATTR:
            self.endpoint.device.battery_bus.listener_event("battery_change", value)
        elif attrid == RTI_MIN_TEMPERATURE_ATTR:
            self.endpoint.device.RtiMinTemp_bus.listener_event("set_value", value / 10)
        elif attrid == RTI_MAX_TEMPERATURE_ATTR:
            self.endpoint.device.RtiMaxTemp_bus.listener_event("set_value", value / 10)
        elif attrid == RTI_SOFT_VER_ATTR:
            self.endpoint.device.RtiSoftwareVersion_bus.listener_event(
                "set_value", value
            )
#        elif attrid in (RTI_TEMPERATURE_ATTR, RTI_TARGET_TEMP_ATTR):
#            self.endpoint.device.thermostat_bus.listener_event(
#                "hass_climate_state_change", attrid, value
#            )


class RtiThermostat(TuyaThermostatCluster):
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
        0x001C: Thermostat.SystemMode.Heat,
    }

    attributes = TuyaThermostatCluster.attributes.copy()
    attributes.update(
        {
            0x4002: ("operation_preset", Preset),
            0x4003: ("valve_position", t.uint32_t, True),
        }
    )

    DIRECT_MAPPING_ATTRS = {
        "min_heat_setpoint_limit": (
            RTI_MIN_TEMPERATURE_ATTR,
            lambda value: round(value / 10),
        ),
        "max_heat_setpoint_limit": (
            RTI_MAX_TEMPERATURE_ATTR,
            lambda value: round(value / 10),
        ),
        "local_temperature_calibration": (
            RTI_TEMP_CALIBRATION_ATTR,
            lambda value: value / 10,
        ),
        "occupied_heating_setpoint": (
            RTI_TARGET_TEMP_ATTR,
            lambda value: value / 10,
        ),
        "valve_position": (
            RTI_VALVE_POSITION_ATTR,
            lambda value: value / 10,
        ),
    }

    SCHEDULE_ATTRS = {
        "schedule_sunday_4_temperature": 20,
        "schedule_sunday_4_minute": 30,
        "schedule_sunday_4_hour": 18,
        "schedule_sunday_3_temperature": 21,
        "schedule_sunday_3_minute": 30,
        "schedule_sunday_3_hour": 14,
        "schedule_sunday_2_temperature": 20,
        "schedule_sunday_2_minute": 30,
        "schedule_sunday_2_hour": 12,
        "schedule_sunday_1_temperature": 19,
        "schedule_sunday_1_minute": 0,
        "schedule_sunday_1_hour": 6,
        "schedule_saturday_4_temperature": 21,
        "schedule_saturday_4_minute": 30,
        "schedule_saturday_4_hour": 17,
        "schedule_saturday_3_temperature": 22,
        "schedule_saturday_3_minute": 30,
        "schedule_saturday_3_hour": 14,
        "schedule_saturday_2_temperature": 23,
        "schedule_saturday_2_minute": 00,
        "schedule_saturday_2_hour": 12,
        "schedule_saturday_1_temperature": 24,
        "schedule_saturday_1_minute": 0,
        "schedule_saturday_1_hour": 6,
        "schedule_workday_4_temperature": 23,
        "schedule_workday_4_minute": 30,
        "schedule_workday_4_hour": 17,
        "schedule_workday_3_temperature": 22,
        "schedule_workday_3_minute": 30,
        "schedule_workday_3_hour": 13,
        "schedule_workday_2_temperature": 21,
        "schedule_workday_2_minute": 30,
        "schedule_workday_2_hour": 11,
        "schedule_workday_1_temperature": 20,
        "schedule_workday_1_minute": 0,
        "schedule_workday_1_hour": 6,
    }

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute in self.DIRECT_MAPPING_ATTRS:
            return {
                self.DIRECT_MAPPING_ATTRS[attribute][0]: value
                if self.DIRECT_MAPPING_ATTRS[attribute][1] is None
                else self.DIRECT_MAPPING_ATTRS[attribute][1](value)
            }

        if attribute == "operation_preset":
            if value == 1:
                return {RTI_MODE_ATTR: 0, RTI_BOOST_ATTR: 0}
            if value == 2:
                return {RTI_MODE_ATTR: 1, RTI_BOOST_ATTR: 0}
            if value == 5:
                return {RTI_BOOST_ATTR: 1}

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
                    return {RTI_MODE_ATTR: 0}
                if oper_mode == self.ProgrammingOperationMode.Simple:
                    return {RTI_MODE_ATTR: 1}
                self.error("Unsupported value for ProgrammingOperationMode")
            else:
                self.error("Unsupported value for Occupancy")

        if attribute == "system_mode":
            if value == self.SystemMode.Off:
                return {RTI_MODE_ATTR: 2}
            else:
                return {RTI_MODE_ATTR: 0}

    def hass_climate_state_change(self, attrid, value):
        """Update of the HASS Climate gui state according to temp difference."""
        if attrid == RTI_TEMPERATURE_ATTR:
            temp_current = value * 10
            temp_set = self._attr_cache.get(
                self.attributes_by_name["occupied_heating_setpoint"].id
            )
        else:
            temp_set = value * 10
            temp_current = self._attr_cache.get(
                self.attributes_by_name["local_temperature"].id
            )

        state = 0 if (int(temp_current) >= int(temp_set)) else 1
        self.endpoint.device.thermostat_bus.listener_event("state_change", state)

    def mode_change(self, value):
        """System Mode change."""
        if value in (1, 2, 3):
            operation_preset = self.Preset.Manual
            prog_mode = self.ProgrammingOperationMode.Simple
            occupancy = self.Occupancy.Occupied
        elif value == 5:
            operation_preset = self.Preset.Boost
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

        if value == 2:
            self._update_attribute(
                self.attributes_by_name["system_mode"].id, self.SystemMode.Off
            )
        else:
            self._update_attribute(
                self.attributes_by_name["system_mode"].id, self.SystemMode.Heat
            )


class RtiUserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    _CHILD_LOCK_ATTR = RTI_CHILD_LOCK_ATTR


class RtiWindowDetection(LocalDataCluster, BinaryInput):
    """Binary cluster for the window detection function."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiWindowDetection_bus.add_listener(self)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class RtiChildLock(CustomTuyaOnOff):
    """On/Off cluster for the child lock function of the electric heating thermostats."""

    def child_lock_change(self, value):
        """Child lock change."""
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""
        if attribute == "on_off":
            return {RTI_CHILD_LOCK_ATTR: value}


class RtiValvePosition(LocalDataCluster, AnalogOutput):
    """Analog output for Valve State."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiValvePosition_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Valve Position"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 100)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0)
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 4 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 98)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)

    async def write_attributes(self, attributes, manufacturer=None):
        """Override the default Cluster write_attributes."""
        for attrid, value in attributes.items():
            if isinstance(attrid, str):
                attrid = self.attributes_by_name[attrid].id
            if attrid not in self.attributes:
                self.error("%d is not a valid attribute id", attrid)
                continue
            self._update_attribute(attrid, value)
            await RtiManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {RTI_VALVE_POSITION_ATTR: value * 10}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class RtiTempCalibration(LocalDataCluster, AnalogOutput):
    """Analog output for Temp Calibration."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiTempCalibration_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature Calibration"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 2)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, -2)
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

            await RtiManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {RTI_TEMP_CALIBRATION_ATTR: value * 10},
                manufacturer=None,
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class RtiBoostCountdown(LocalDataCluster, AnalogOutput):
    """Analog output for Boost Countdown time."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiBoostCountdown_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Boost Countdown"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 9999)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 12 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 73)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class RtiMinTemp(LocalDataCluster, AnalogOutput):
    """Analog output for Min Temperature."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiMinTemp_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Min Temperature"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 15)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 5)
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

            await RtiManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {RTI_MIN_TEMPERATURE_ATTR: value * 10},
                manufacturer=None,
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class RtiMaxTemp(LocalDataCluster, AnalogOutput):
    """Analog output for Max Temperature."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiMaxTemp_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Max Temperature"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 35)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 15)
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

            await RtiManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {RTI_MAX_TEMPERATURE_ATTR: value * 10},
                manufacturer=None,
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class RtiSoftwareVersion(LocalDataCluster, AnalogOutput):
    """Analog output for TRV software version."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.RtiSoftwareVersion_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Software version"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 9999)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 95)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class Rti(TuyaThermostat):
    """Rti Thermostatic radiator valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.RtiWindowDetection_bus = Bus()
        self.RtiValvePosition_bus = Bus()
        self.RtiTempCalibration_bus = Bus()
        self.RtiBoostCountdown_bus = Bus()
        self.RtiMinTemp_bus = Bus()
        self.RtiMaxTemp_bus = Bus()
        self.RtiSoftwareVersion_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=0 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_a4bpgplm", "TS0601"),
            ("_TZE200_dv8abrrz", "TS0601"),
            ("_TZE200_z1tyspqw", "TS0601"),
            ("_TZE200_rtrmfadk", "TS0601"),
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
                    RtiManufCluster,
                    RtiThermostat,
                    RtiUserInterface,
                    RtiWindowDetection,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [RtiChildLock],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [RtiValvePosition],
                OUTPUT_CLUSTERS: [],
            },
            4: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [RtiTempCalibration],
                OUTPUT_CLUSTERS: [],
            },
            5: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [RtiBoostCountdown],
                OUTPUT_CLUSTERS: [],
            },
            6: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [RtiMinTemp],
                OUTPUT_CLUSTERS: [],
            },
            7: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [RtiMaxTemp],
                OUTPUT_CLUSTERS: [],
            },
        }
    }
