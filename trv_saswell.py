"""Map from manufacturer to standard clusters for thermostatic valves."""
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
    Groups,
    Identify,
    OnOff,
    Ota,
    PowerConfiguration,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.hvac import Thermostat

# Setup logger
_LOGGER = logging.getLogger(__name__)


SASWELL_CHILD_LOCK_ATTR = 0x0128  # [0/1] on/off 296
SASWELL_ANTI_FREEZE_ATTR = 0x010A  # [0/1] on/off 266
SASWELL_WINDOW_DETECT_ATTR = 0x0108  # [0/1] on/off 264
SASWELL_LIMESCALE_PROTECT_ATTR = 0x0182  # [0/1] on/off 386
SASWELL_TEMP_CORRECTION_ATTR = 0x021B  # uint32 - temp correction 539
SASWELL_ROOM_TEMP_ATTR = 0x0266  # uint32 - current room temp 614
SASWELL_AWAY_MODE_ATTR = 0x016A  # [0/1] on/off 362
SASWELL_SCHEDULE_MODE_ATTR = 0x016C  # [0/1] on/off 364
SASWELL_ONOFF_ATTR = 0x0165  # [0/1] on/off 357
SASWELL_TARGET_TEMP_ATTR = 0x0267  # uint32 - target temp 615
SASWELL_BATTERY_ALARM_ATTR = 0x569  # [0/1] on/off - battery low 1385

# Global
SaswellManufClusterSelf = {}


class CustomTuyaOnOff(LocalDataCluster, OnOff):
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

        await SaswellManufClusterSelf[
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


class SaswellManufCluster(TuyaManufClusterAttributes):
    """Manufacturer specific cluster for Tuya converting attributes <-> commands."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        global SaswellManufClusterSelf
        SaswellManufClusterSelf[self.endpoint.device.ieee] = self

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
            is_manufacturer_specific=True,
        ),
    }

    attributes = TuyaManufClusterAttributes.attributes.copy()
    attributes.update(
        {
            SASWELL_ONOFF_ATTR: ("on_off", t.uint8_t, True),
            SASWELL_TARGET_TEMP_ATTR: ("target_temperature", t.uint32_t, True),
            SASWELL_ROOM_TEMP_ATTR: ("current_room_temp", t.uint32_t, True),
            SASWELL_CHILD_LOCK_ATTR: ("child_lock", t.uint8_t, True),
            SASWELL_SCHEDULE_MODE_ATTR: ("schedule_mode", t.uint8_t, True),
            SASWELL_WINDOW_DETECT_ATTR: ("window_detection", t.uint8_t, True),
            SASWELL_ANTI_FREEZE_ATTR: ("anti_freeze_protection", t.uint8_t, True),
            SASWELL_LIMESCALE_PROTECT_ATTR: ("limescale_protection", t.uint8_t, True),
            SASWELL_AWAY_MODE_ATTR: ("away_mode", t.uint8_t, True),
            SASWELL_BATTERY_ALARM_ATTR: ("battery_low", t.uint8_t, True),
            SASWELL_TEMP_CORRECTION_ATTR: (
                "room_temperature_correction",
                t.int32s,
                True,
            ),
        }
    )

    DIRECT_MAPPED_ATTRS = {
        SASWELL_ROOM_TEMP_ATTR: ("local_temperature", lambda value: value * 10),
        SASWELL_TARGET_TEMP_ATTR: (
            "occupied_heating_setpoint",
            lambda value: value * 10,
        ),
        SASWELL_TEMP_CORRECTION_ATTR: ("local_temperature_calibration", None),
    }

    def _update_attribute(self, attrid, value):
        super()._update_attribute(attrid, value)
        if attrid in self.DIRECT_MAPPED_ATTRS:
            self.endpoint.device.thermostat_bus.listener_event(
                "temperature_change",
                self.DIRECT_MAPPED_ATTRS[attrid][0],
                value
                if self.DIRECT_MAPPED_ATTRS[attrid][1] is None
                else self.DIRECT_MAPPED_ATTRS[attrid][1](value),
            )

        if attrid == SASWELL_ONOFF_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("on_off_event", value)
        elif attrid == SASWELL_SCHEDULE_MODE_ATTR:
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "schedule_mode_change", value
            )
        elif attrid == SASWELL_AWAY_MODE_ATTR:
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "away_mode_change", value
            )
        elif attrid == SASWELL_CHILD_LOCK_ATTR:
            self.endpoint.device.ui_bus.listener_event("child_lock_change", value)
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "child_lock_change", value
            )
        elif attrid == SASWELL_WINDOW_DETECT_ATTR:
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "window_detect_change", value
            )
        elif attrid == SASWELL_ANTI_FREEZE_ATTR:
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "anti_freeze_change", value
            )
        elif attrid == SASWELL_LIMESCALE_PROTECT_ATTR:
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "limescale_protection_change", value
            )
        elif attrid == SASWELL_BATTERY_ALARM_ATTR:
            self.endpoint.device.battery_bus.listener_event(
                "battery_alarm_event", value
            )
        elif attrid == SASWELL_TEMP_CORRECTION_ATTR:
            self.endpoint.device.SaswellTempCalibration_bus.listener_event(
                "set_value", value
            )
        elif attrid in (SASWELL_ROOM_TEMP_ATTR, SASWELL_TARGET_TEMP_ATTR):
            self.endpoint.device.thermostat_bus.listener_event(
                "hass_climate_state_change", attrid, value
            )


class SaswellChildLock(CustomTuyaOnOff):
    """Child Lock setting support. Please remember that CL has to be set manually on the device. This only controls if locking is possible at all"""

    def child_lock_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {SASWELL_CHILD_LOCK_ATTR: value}


class SaswellWindowDectection(CustomTuyaOnOff):
    """Open Window Detection support"""

    def window_detect_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {SASWELL_WINDOW_DETECT_ATTR: value}


class SaswellAntiFreezeDectection(CustomTuyaOnOff):
    """Anti-Freeze support"""

    def anti_freeze_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {SASWELL_ANTI_FREEZE_ATTR: value}


class SaswellLimescaleProtectionDectection(CustomTuyaOnOff):
    """Limescale Protection support"""

    def limescale_protection_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {SASWELL_LIMESCALE_PROTECT_ATTR: value}


class SaswellScheduleModeDectection(CustomTuyaOnOff):
    """Schedule Mode On/Off support"""

    def schedule_mode_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {SASWELL_SCHEDULE_MODE_ATTR: value}


class SaswellAwayModeDectection(CustomTuyaOnOff):
    """Away Mode On/Off support"""

    def away_mode_change(self, value):
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        if attribute == "on_off":
            return {SASWELL_AWAY_MODE_ATTR: value}


class SaswellPowerConfigurationCluster(LocalDataCluster, PowerConfiguration):
    """Power configuration cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.battery_bus.add_listener(self)

    def battery_alarm_event(self, value):
        """Handle reported battery state."""
        _LOGGER.debug("reported battery alert: %d", value)
        if value == 1:  # alert
            self._update_attribute(
                self.attributes_by_name["battery_percentage_remaining"].id, 0
            )  # report 0% battery
        else:
            self._update_attribute(
                self.attributes_by_name["battery_percentage_remaining"].id, 200
            )  # report 100% battery


class SaswellTempCalibration(LocalDataCluster, AnalogOutput):
    """Analog output for Temp Calibration"""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.SaswellTempCalibration_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature Calibration"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 6)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, -6)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    def set_value(self, value):
        self._update_attribute(self.attributes_by_name["present_value"].id, value)

    def get_value(self):
        return self._attr_cache.get(self.attributes_by_name["present_value"].id)

    async def write_attributes(self, attributes, manufacturer=None):
        for attrid, value in attributes.items():
            if isinstance(attrid, str):
                attrid = self.attributes_by_name[attrid].id
            if attrid not in self.attributes:
                self.error("%d is not a valid attribute id", attrid)
                continue
            self._update_attribute(attrid, value)

            await SaswellManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {SASWELL_TEMP_CORRECTION_ATTR: value},
                manufacturer=None,
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class SaswellThermostatCluster(TuyaThermostatCluster):
    """Thermostat cluster for Tuya thermostats."""

    _CONSTANT_ATTRIBUTES = {
        0x001B: Thermostat.ControlSequenceOfOperation.Heating_Only,
    }

    DIRECT_MAPPING_ATTRS = {
        "local_temperature_calibration": (
            SASWELL_TEMP_CORRECTION_ATTR,
            lambda value: value,
        ),
        "occupied_heating_setpoint": (
            SASWELL_TARGET_TEMP_ATTR,
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
            500,
        )
        self.endpoint.device.thermostat_bus.listener_event(
            "temperature_change",
            "max_heat_setpoint_limit",
            3000,
        )

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute in self.DIRECT_MAPPING_ATTRS:
            return {
                self.DIRECT_MAPPING_ATTRS[attribute][0]: value
                if self.DIRECT_MAPPING_ATTRS[attribute][1] is None
                else self.DIRECT_MAPPING_ATTRS[attribute][1](value)
            }

        if attribute == "system_mode":
            if value == self.SystemMode.Off:
                return {SASWELL_ONOFF_ATTR: 0}
            if value == self.SystemMode.Heat:
                return {SASWELL_ONOFF_ATTR: 1}

    def on_off_event(self, value):
        """Handle on/off event"""
        if value == 1:
            self._update_attribute(
                self.attributes_by_name["system_mode"].id, Thermostat.SystemMode.Heat
            )
            self._update_attribute(
                self.attributes_by_name["running_mode"].id, Thermostat.RunningMode.Heat
            )
            self._update_attribute(
                self.attributes_by_name["running_state"].id,
                Thermostat.RunningState.Heat_State_On,
            )
            _LOGGER.debug("reported system_mode: heat")
        else:
            self._update_attribute(
                self.attributes_by_name["system_mode"].id, Thermostat.SystemMode.Off
            )
            self._update_attribute(
                self.attributes_by_name["running_mode"].id, Thermostat.RunningMode.Off
            )
            self._update_attribute(
                self.attributes_by_name["running_state"].id,
                Thermostat.RunningState.Idle,
            )
            _LOGGER.debug("reported system_mode: off")
        _LOGGER.debug("on/off event with value %d", value)

    def hass_climate_state_change(self, attrid, value):
        """Update of the HASS Climate gui state according to temp difference."""
        if (
            self._attr_cache.get(self.attributes_by_name["system_mode"].id)
            != Thermostat.SystemMode.Heat
        ):
            self.endpoint.device.thermostat_bus.listener_event("state_change", 0)
            return
        if attrid == SASWELL_ROOM_TEMP_ATTR:
            temp_current = value * 10
            temp_set = self._attr_cache.get(
                self.attributes_by_name["occupied_heating_setpoint"].id
            )
        else:
            temp_set = value * 10
            temp_current = self._attr_cache.get(
                self.attributes_by_name["local_temperature"].id
            )

        state = 0 if (int(temp_current) >= int(temp_set + 2)) else 1
        self.endpoint.device.thermostat_bus.listener_event("state_change", state)


class SaswellUserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    _CHILD_LOCK_ATTR = SASWELL_CHILD_LOCK_ATTR


class Saswell_Thermostat_TZE200(TuyaThermostat):
    """Saswell Thermostatic Radiator Valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.SaswellTempCalibration_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  (endpoint=1, profile=260, device_type=81, device_version=1, input_clusters=[0, 4, 5, 61184], output_clusters=[25, 10])
        #  <Endpoint id=1 in=[basic:0x0000, groups:0x0004, scenes:0x0005, None:0xEF00] out=[ota:0x0019, time:0x000A]
        MODELS_INFO: [
            ("_TZE200_yw7cahqs", "TS0601"),
            ("_TZE200_c88teujp", "TS0601"),
            ("_TZE200_azqp6ssj", "TS0601"),
            ("_TZE200_9gvruqf5", "TS0601"),
            ("_TZE200_zuhszj9s", "TS0601"),
            ("_TZE200_zr9c0day", "TS0601"),
            ("_TZE200_h4cgnbzg", "TS0601"),
            ("_TZE200_0dvm9mva", "TS0601"),
            ("_TZE200_exfrnlow", "TS0601"),
            ("_TZE200_9m4kmbfu", "TS0601"),
            ("_TZE200_3yp57tby", "TS0601"),
            ("_TZE200_mz5y07w2", "TS0601"),
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
                OUTPUT_CLUSTERS: [Ota.cluster_id, Time.cluster_id],
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
                    SaswellManufCluster,
                    SaswellThermostatCluster,
                    SaswellWindowDectection,
                    SaswellPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [
                    Ota.cluster_id,
                    Time.cluster_id,
                ],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellChildLock,
                ],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellAntiFreezeDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            4: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellLimescaleProtectionDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            5: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellScheduleModeDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            6: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellAwayModeDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            7: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [
                    SaswellTempCalibration,
                ],
                OUTPUT_CLUSTERS: [],
            },
        }
    }


class Saswell_Thermostat_TYST11(TuyaThermostat):
    """Saswell Thermostatic Radiator Valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.SaswellTempCalibration_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        # <SimpleDescriptor endpoint=1 profile=260 device_type=0
        # device_version=0
        # input_clusters=[0, 3]
        # output_clusters=[3, 25]>
        MODELS_INFO: [
            ("_TYST11_KGbxAXL2", "GbxAXL2"),
            ("_TYST11_c88teujp", "88teujp"),
            ("_TYST11_azqp6ssj", "zqp6ssj"),
            ("_TYST11_yw7cahqs", "w7cahqs"),
            ("_TYST11_9gvruqf5", "gvruqf5"),
            ("_TYST11_zuhszj9s", "uhszj9s"),
            ("_TYST11_caj4jz0i", "aj4jz0i"),
        ],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    Identify.cluster_id,
                    Ota.cluster_id,
                ],
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
                    Identify.cluster_id,
                    SaswellManufCluster,
                    SaswellThermostatCluster,
                    SaswellWindowDectection,
                    SaswellPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [
                    Ota.cluster_id,
                    Identify.cluster_id,
                ],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellChildLock,
                ],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellAntiFreezeDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            4: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellLimescaleProtectionDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            5: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellScheduleModeDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            6: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    SaswellAwayModeDectection,
                ],
                OUTPUT_CLUSTERS: [],
            },
            7: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [
                    SaswellTempCalibration,
                ],
                OUTPUT_CLUSTERS: [],
            },
        }
    }
