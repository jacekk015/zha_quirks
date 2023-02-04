"""Map from manufacturer to standard clusters for thermostatic valves."""

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
from zigpy.profiles import zha
from zigpy.zcl.clusters.general import Basic, Groups, Ota, Scenes, Time

ZONNSMART_CHILD_LOCK_ATTR = 0x0128  # [0] unlocked [1] child-locked
ZONNSMART_WINDOW_DETECT_ATTR = 0x0108  # [0] inactive [1] active
ZONNSMART_TARGET_TEMP_ATTR = 0x0210  # [0,0,0,210] target room temp (decidegree)
ZONNSMART_TEMPERATURE_ATTR = 0x0218  # [0,0,0,200] current room temp (decidegree)
ZONNSMART_BATTERY_ATTR = 0x0223  # [0,0,0,98] battery charge
ZONNSMART_MODE_ATTR = (
    0x0402  # [0] Scheduled/auto [1] manual [2] Holiday [3] HolidayReady
)
ZONNSMART_HEATING_STOPPING = 0x016B  # [0] inactive [1] active
ZONNSMART_BOOST_TIME_ATTR = 0x0265  # BOOST mode operating time in (sec)
ZONNSMART_UPTIME_TIME_ATTR = (
    0x0024  # Seems to be the uptime attribute (sent hourly, increases) [0,200]
)
ZONNSMARTManufClusterSelf = {}


class ZONNSMARTManufCluster(TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of some thermostatic valves."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.ZONNSMARTManufCluster_bus.add_listener(self)
        global ZONNSMARTManufClusterSelf
        ZONNSMARTManufClusterSelf[self.endpoint.device.ieee] = self

    attributes = TuyaManufClusterAttributes.attributes.copy()
    attributes.update(
        {
            ZONNSMART_CHILD_LOCK_ATTR: ("child_lock", t.uint8_t),
            ZONNSMART_WINDOW_DETECT_ATTR: ("window_detection", t.uint8_t),
            ZONNSMART_TARGET_TEMP_ATTR: ("target_temperature", t.uint32_t),
            ZONNSMART_TEMPERATURE_ATTR: ("temperature", t.uint32_t),
            ZONNSMART_BATTERY_ATTR: ("battery", t.uint32_t),
            ZONNSMART_MODE_ATTR: ("mode", t.uint8_t),
            ZONNSMART_BOOST_TIME_ATTR: ("boost_duration_seconds", t.uint32_t),
            ZONNSMART_UPTIME_TIME_ATTR: ("uptime", t.uint32_t),
            ZONNSMART_HEATING_STOPPING: ("heating_stop", t.uint8_t),
        }
    )

    DIRECT_MAPPED_ATTRS = {
        ZONNSMART_TEMPERATURE_ATTR: ("local_temperature", lambda value: value * 10),
        ZONNSMART_TARGET_TEMP_ATTR: (
            "occupied_heating_setpoint",
            lambda value: value * 10,
        ),
        ZONNSMART_BOOST_TIME_ATTR: ("boost_duration_seconds", None),
        ZONNSMART_UPTIME_TIME_ATTR: ("uptime_duration_hours", None),
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
        elif attrid == ZONNSMART_MODE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("mode_change", value)
        elif attrid == ZONNSMART_HEATING_STOPPING:
            self.endpoint.device.thermostat_bus.listener_event(
                "state_change", value == 0
            )
        elif attrid == ZONNSMART_CHILD_LOCK_ATTR:
            mode = 1 if value else 0
            self.endpoint.device.ui_bus.listener_event("child_lock_change", mode)
        elif attrid == ZONNSMART_BATTERY_ATTR:
            self.endpoint.device.battery_bus.listener_event("battery_change", value)


class ZONNSMARTThermostat(TuyaThermostatCluster):
    """Thermostat cluster for some thermostatic valves."""

    DIRECT_MAPPING_ATTRS = {
        "occupied_heating_setpoint": (
            ZONNSMART_TARGET_TEMP_ATTR,
            lambda value: round(value / 10),
        ),
        "operation_preset": (ZONNSMART_MODE_ATTR, None),
        "boost_duration_seconds": (ZONNSMART_BOOST_TIME_ATTR, None),
    }

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute in self.DIRECT_MAPPING_ATTRS:
            return {
                self.DIRECT_MAPPING_ATTRS[attribute][0]: value
                if self.DIRECT_MAPPING_ATTRS[attribute][1] is None
                else self.DIRECT_MAPPING_ATTRS[attribute][1](value)
            }
        if attribute in ("system_mode", "programing_oper_mode"):
            if attribute == "system_mode":
                system_mode = value
                oper_mode = self._attr_cache.get(
                    self.attributes_by_name["programing_oper_mode"].id,
                    self.ProgrammingOperationMode.Simple,
                )
            else:
                system_mode = self._attr_cache.get(
                    self.attributes_by_name["system_mode"].id, self.SystemMode.Heat
                )
                oper_mode = value
            if system_mode == self.SystemMode.Off:
                return {ZONNSMART_HEATING_STOPPING: 1}
            if system_mode == self.SystemMode.Heat:
                if oper_mode == self.ProgrammingOperationMode.Schedule_programming_mode:
                    return {ZONNSMART_MODE_ATTR: 0}
                if oper_mode == self.ProgrammingOperationMode.Simple:
                    return {ZONNSMART_MODE_ATTR: 1}
                self.error("Unsupported value for ProgrammingOperationMode")
            else:
                self.error("Unsupported value for SystemMode")

    def mode_change(self, value):
        """System Mode change."""
        if value == 0:
            prog_mode = self.ProgrammingOperationMode.Schedule_programming_mode
        elif value == 1:
            prog_mode = self.ProgrammingOperationMode.Simple
        else:
            prog_mode = self.ProgrammingOperationMode.Simple

        self._update_attribute(
            self.attributes_by_name["system_mode"].id, self.SystemMode.Heat
        )
        self._update_attribute(
            self.attributes_by_name["programing_oper_mode"].id, prog_mode
        )


class ZONNSMARTUserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    _CHILD_LOCK_ATTR = ZONNSMART_CHILD_LOCK_ATTR


class ZonnsmartTV01_ZG(TuyaThermostat):
    """ZONNSMART TV01-ZG Thermostatic radiator valve."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.ZONNSMARTManufCluster_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #  endpoint=1 profile=260 device_type=81 device_version=0 input_clusters=[0, 4, 5, 61184]
        #  output_clusters=[10, 25]>
        MODELS_INFO: [
            ("_TZE200_7yoranx2", "TS0601"),  # MOES TV01 ZTRV-ZX-TV01-MS
            ("_TZE200_e9ba97vf", "TS0601"),  # Zonnsmart TV01-ZG
            ("_TZE200_hue3yfsn", "TS0601"),  # Zonnsmart TV02-ZG
            ("_TZE200_husqqvux", "TS0601"),  # Tesla Smart TSL-TRV-TV01ZG
            ("_TZE200_kly8gjlz", "TS0601"),  # EARU TV05-ZG
            ("_TZE200_lnbfnyxd", "TS0601"),  # Tesla Smart TSL-TRV-TV01ZG
            ("_TZE200_mudxchsu", "TS0601"),  # Foluu TV05
            ("_TZE200_kds0pmmv", "TS0601"),  # MOES TV02
            ("_TZE200_sur6q7ko", "TS0601"),  # LSC Smart Connect 3012732
            ("_TZE200_lllliz3p", "TS0601"),  # tuya TV02-Zigbee
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
                    ZONNSMARTManufCluster,
                    ZONNSMARTThermostat,
                    ZONNSMARTUserInterface,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            }
        }
    }
