"""Tuya temperature and humidity sensor."""
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
    TuyaEnchantableCluster,
    TuyaManufCluster,
    TuyaManufClusterAttributes,
    TuyaPowerConfigurationCluster,
    TuyaThermostatCluster,
    TuyaTimePayload,
)
from zhaquirks.tuya.mcu import EnchantedDevice
from zigpy.profiles import zha
from zigpy.quirks import CustomCluster, CustomDevice
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
from zigpy.zcl.clusters.measurement import RelativeHumidity, TemperatureMeasurement

_LOGGER = logging.getLogger(__name__)

TUYA_TEMPERATURE_ATTR = 0x0201  # [0, 0, 0, 202] / 10
TUYA_HUMIDITY_ATTR = 0x0202  # [0, 0, 0, 65]
TUYA_BATTERY_ATTR = 0x0204  # [0, 0, 0, 40]
TUYA_MAX_TEMP = 0x020A  # [0, 0, 0, 254] / 10
TUYA_MIN_TEMP = 0x020B  # [0, 0, 0, 154] / 10
TUYA_ALARM_TEMP = 0x040E  # 0 = underride , 1 = override , 2 = all is fine
TUYA_MAX_HUMIDITY = 0x020C  # [0, 0, 0, 61]
TUYA_MIN_HUMIDITY = 0x020D  # [0, 0, 0, 21]
TUYA_ALARM_HUMIDITY = 0x040F  # 0 = underride , 1 = override , 2 = all is fine
TUYA_TEMP_SENSIVITY = 0x0213  # [0, 0, 0, 6] / 2
TUYA_HUMIDITY_SENSIVITY = 0x0214  # [0, 0, 0, 3]
TUYA_TEMP_REPORTING = 0x0211  # [0, 0, 0, 120] [minutes]
TUYA_HUMIDITY_REPORTING = 0x0212  # [0, 0, 0, 120] [minutes]
TUYA_TEMP_UNIT = 0x0409  # 0 = Celsius 1 = Fahrenheit
TuyaManufClusterSelf = {}


class CustomTuyaOnOff(LocalDataCluster, OnOff):
    """Custom Tuya OnOff cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.tuya_onoff_bus.add_listener(self)

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

        await TuyaManufClusterSelf[
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


class TuyaSensorManufCluster(TuyaEnchantableCluster, TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of thermostatic valves."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        global TuyaManufClusterSelf
        TuyaManufClusterSelf[self.endpoint.device.ieee] = self

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

    attributes = TuyaThermostatCluster.attributes.copy()
    attributes.update(
        {
            TUYA_TEMPERATURE_ATTR: ("temperature", t.int16s),
            TUYA_HUMIDITY_ATTR: ("humidity", t.uint16_t),
            TUYA_BATTERY_ATTR: ("battery", t.uint8_t),
            TUYA_MAX_TEMP: ("max_temperature", t.int16s),
            TUYA_MIN_TEMP: ("min_temperature", t.int16s),
            TUYA_ALARM_TEMP: ("alarm_temp", t.uint8_t),
            TUYA_MAX_HUMIDITY: ("max_humidity", t.uint16_t),
            TUYA_MIN_HUMIDITY: ("min_humidity", t.uint16_t),
            TUYA_ALARM_HUMIDITY: ("alarm_humidity", t.uint8_t),
            TUYA_TEMP_SENSIVITY: ("temp_sensivity", t.uint16_t),
            TUYA_HUMIDITY_SENSIVITY: ("humidity_sensivity", t.uint16_t),
            TUYA_TEMP_REPORTING: ("temp_reporting", t.uint16_t),
            TUYA_HUMIDITY_REPORTING: ("humidity_reporting", t.uint16_t),
            TUYA_TEMP_UNIT: ("temp_unit", t.uint8_t),
        }
    )

    def _update_attribute(self, attrid, value):
        """Override default _update_attribute."""
        super()._update_attribute(attrid, value)
        if attrid == TUYA_TEMPERATURE_ATTR:
            self.endpoint.device.TuyaSensorTemperature_bus.listener_event(
                "set_value", value / 10
            )
        elif attrid == TUYA_HUMIDITY_ATTR:
            self.endpoint.device.TuyaSensorRelativeHumidity_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_BATTERY_ATTR:
            self.endpoint.device.battery_bus.listener_event("battery_change", value)
        elif attrid == TUYA_MAX_TEMP:
            self.endpoint.device.TuyaMaxTemperature_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_MIN_TEMP:
            self.endpoint.device.TuyaMinTemperature_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_ALARM_TEMP:
            if value == 0:
                self.endpoint.device.TuyaAlarmTempUnder_bus.listener_event(
                    "set_value", True
                )
                self.endpoint.device.TuyaAlarmTempOver_bus.listener_event(
                    "set_value", False
                )
            elif value == 1:
                self.endpoint.device.TuyaAlarmTempUnder_bus.listener_event(
                    "set_value", False
                )
                self.endpoint.device.TuyaAlarmTempOver_bus.listener_event(
                    "set_value", True
                )
            else:
                self.endpoint.device.TuyaAlarmTempUnder_bus.listener_event(
                    "set_value", False
                )
                self.endpoint.device.TuyaAlarmTempOver_bus.listener_event(
                    "set_value", False
                )
        elif attrid == TUYA_MAX_HUMIDITY:
            self.endpoint.device.TuyaMaxHumidity_bus.listener_event("set_value", value)
        elif attrid == TUYA_MIN_HUMIDITY:
            self.endpoint.device.TuyaMinHumidity_bus.listener_event("set_value", value)
        elif attrid == TUYA_ALARM_HUMIDITY:
            if value == 0:
                self.endpoint.device.TuyaAlarmHumidityUnder_bus.listener_event(
                    "set_value", True
                )
                self.endpoint.device.TuyaAlarmHumidityOver_bus.listener_event(
                    "set_value", False
                )
            elif value == 1:
                self.endpoint.device.TuyaAlarmHumidityUnder_bus.listener_event(
                    "set_value", False
                )
                self.endpoint.device.TuyaAlarmHumidityOver_bus.listener_event(
                    "set_value", True
                )
            else:
                self.endpoint.device.TuyaAlarmHumidityUnder_bus.listener_event(
                    "set_value", False
                )
                self.endpoint.device.TuyaAlarmHumidityOver_bus.listener_event(
                    "set_value", False
                )
        elif attrid == TUYA_TEMP_SENSIVITY:
            self.endpoint.device.TuyaTempSensivity_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_HUMIDITY_SENSIVITY:
            self.endpoint.device.TuyaHumiditySensivity_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_TEMP_REPORTING:
            self.endpoint.device.TuyaTemperatureReporting_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_HUMIDITY_REPORTING:
            self.endpoint.device.TuyaHumidityReporting_bus.listener_event(
                "set_value", value
            )
        elif attrid == TUYA_TEMP_UNIT:
            self.endpoint.device.tuya_onoff_bus.listener_event("unit_change", value)


class TuyaSensorTemperature(LocalDataCluster, AnalogOutput):
    """Temperature cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaSensorTemperature_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature Measurement"
        )
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class TuyaSensorRelativeHumidity(LocalDataCluster, AnalogOutput):
    """Humidity cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaSensorRelativeHumidity_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Relative Humidity Measurement"
        )
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 1 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 98)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class TuyaPowerConfigurationCluster2AAA(TuyaPowerConfigurationCluster):
    """PowerConfiguration cluster for battery-operated TRVs with 2 AAA."""

    BATTERY_SIZE = 0x0031
    BATTERY_RATED_VOLTAGE = 0x0034
    BATTERY_QUANTITY = 0x0033

    _CONSTANT_ATTRIBUTES = {
        BATTERY_SIZE: 3,
        BATTERY_RATED_VOLTAGE: 15,
        BATTERY_QUANTITY: 2,
    }


class TuyaMaxTemperature(LocalDataCluster, AnalogOutput):
    """Analog output for Max temperature."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaMaxTemperature_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Max Temperature"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 30)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, -20)
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value / 10)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_MAX_TEMP: value * 10}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaMinTemperature(LocalDataCluster, AnalogOutput):
    """Analog output for Min temperature."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaMinTemperature_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Min Temperature"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 30)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, -20)
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value / 10)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_MIN_TEMP: value * 10}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaAlarmTempUnder(LocalDataCluster, BinaryInput):
    """Binary cluster for the temp alarm under."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaAlarmTempUnder_bus.add_listener(self)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class TuyaAlarmTempOver(LocalDataCluster, BinaryInput):
    """Binary cluster for the temp alarm over."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaAlarmTempOver_bus.add_listener(self)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class TuyaMaxHumidity(LocalDataCluster, AnalogOutput):
    """Analog output for Max humidity."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaMaxHumidity_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Max Humidity"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 100)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 1 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 98)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_MAX_HUMIDITY: value}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaMinHumidity(LocalDataCluster, AnalogOutput):
    """Analog output for Min humidity."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaMinHumidity_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Min Humidity"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 100)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 1 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 98)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_MIN_HUMIDITY: value}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaAlarmHumidityUnder(LocalDataCluster, BinaryInput):
    """Binary cluster for the humidity alarm under."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaAlarmHumidityUnder_bus.add_listener(self)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class TuyaAlarmHumidityOver(LocalDataCluster, BinaryInput):
    """Binary cluster for the humidity alarm over."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaAlarmHumidityOver_bus.add_listener(self)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value)


class TuyaTempSensivity(LocalDataCluster, AnalogOutput):
    """Analog output for temperature sensivity."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaTempSensivity_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature sensivity"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 10)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 0.5)
        self._update_attribute(self.attributes_by_name["resolution"].id, 0.5)
        self._update_attribute(self.attributes_by_name["application_type"].id, 13 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 62)

    def set_value(self, value):
        """Set value."""
        self._update_attribute(self.attributes_by_name["present_value"].id, value / 2)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_TEMP_SENSIVITY: value * 2}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaHumiditySensivity(LocalDataCluster, AnalogOutput):
    """Analog output for humidity sensivity."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaHumiditySensivity_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Humidity sensivity"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 10)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 1)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 1 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 98)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_HUMIDITY_SENSIVITY: value}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaTemperatureReporting(LocalDataCluster, AnalogOutput):
    """Analog output for temperature reporting time."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaTemperatureReporting_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Temperature reporting time"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 300)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 1)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 14 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 72)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_TEMP_REPORTING: value}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaHumidityReporting(LocalDataCluster, AnalogOutput):
    """Analog output for humidity reporting time."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.TuyaHumidityReporting_bus.add_listener(self)
        self._update_attribute(
            self.attributes_by_name["description"].id, "Humidity reporting time"
        )
        self._update_attribute(self.attributes_by_name["max_present_value"].id, 300)
        self._update_attribute(self.attributes_by_name["min_present_value"].id, 1)
        self._update_attribute(self.attributes_by_name["resolution"].id, 1)
        self._update_attribute(self.attributes_by_name["application_type"].id, 14 << 16)
        self._update_attribute(self.attributes_by_name["engineering_units"].id, 72)

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

            await TuyaManufClusterSelf[
                self.endpoint.device.ieee
            ].endpoint.tuya_manufacturer.write_attributes(
                {TUYA_HUMIDITY_REPORTING: value}, manufacturer=None
            )
        return ([foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)],)


class TuyaTempUnit(CustomTuyaOnOff):
    """On/Off cluster for the temperature unit change."""

    def unit_change(self, value):
        """Unit change."""
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""
        if attribute == "on_off":
            return {TUYA_TEMP_UNIT: value}


class TuyaSensor(EnchantedDevice, CustomDevice):
    """Tuya temperature and humidity sensor."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.battery_bus = Bus()
        self.TuyaSensorTemperature_bus = Bus()
        self.TuyaSensorRelativeHumidity_bus = Bus()
        self.TuyaMaxTemperature_bus = Bus()
        self.TuyaMinTemperature_bus = Bus()
        self.TuyaAlarmTempUnder_bus = Bus()
        self.TuyaAlarmTempOver_bus = Bus()
        self.TuyaMaxHumidity_bus = Bus()
        self.TuyaMinHumidity_bus = Bus()
        self.TuyaAlarmHumidityUnder_bus = Bus()
        self.TuyaAlarmHumidityOver_bus = Bus()
        self.TuyaTempSensivity_bus = Bus()
        self.TuyaHumiditySensivity_bus = Bus()
        self.TuyaTemperatureReporting_bus = Bus()
        self.TuyaHumidityReporting_bus = Bus()
        self.tuya_onoff_bus = Bus()
        super().__init__(*args, **kwargs)

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
                DEVICE_TYPE: zha.DeviceType.TEMPERATURE_SENSOR,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    TuyaSensorManufCluster,
                    TuyaPowerConfigurationCluster2AAA,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaMaxTemperature],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaMinTemperature],
                OUTPUT_CLUSTERS: [],
            },
            4: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SIMPLE_SENSOR,
                INPUT_CLUSTERS: [TuyaAlarmTempUnder],
                OUTPUT_CLUSTERS: [],
            },
            5: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SIMPLE_SENSOR,
                INPUT_CLUSTERS: [TuyaAlarmTempOver],
                OUTPUT_CLUSTERS: [],
            },
            6: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaMaxHumidity],
                OUTPUT_CLUSTERS: [],
            },
            7: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaMinHumidity],
                OUTPUT_CLUSTERS: [],
            },
            8: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SIMPLE_SENSOR,
                INPUT_CLUSTERS: [TuyaAlarmHumidityUnder],
                OUTPUT_CLUSTERS: [],
            },
            9: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SIMPLE_SENSOR,
                INPUT_CLUSTERS: [TuyaAlarmHumidityOver],
                OUTPUT_CLUSTERS: [],
            },
            10: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaTempSensivity],
                OUTPUT_CLUSTERS: [],
            },
            11: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaHumiditySensivity],
                OUTPUT_CLUSTERS: [],
            },
            12: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaTemperatureReporting],
                OUTPUT_CLUSTERS: [],
            },
            13: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaHumidityReporting],
                OUTPUT_CLUSTERS: [],
            },
            14: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [TuyaTempUnit],
                OUTPUT_CLUSTERS: [],
            },
            15: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaSensorTemperature],
                OUTPUT_CLUSTERS: [],
            },
            16: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.CONSUMPTION_AWARENESS_DEVICE,
                INPUT_CLUSTERS: [TuyaSensorRelativeHumidity],
                OUTPUT_CLUSTERS: [],
            },
        }
    }
