"""Platform for sensor integration."""

from datetime import datetime
import logging

from pyemvue.device import VueDevice, VueDeviceChannel, ChargerDevice
from pyemvue.enums import Scale

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)


# def setup_platform(hass, config, add_entities, discovery_info=None):
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator_1min = hass.data[DOMAIN][config_entry.entry_id]["coordinator_1min"]
    coordinator_realtime_mains = hass.data[DOMAIN][config_entry.entry_id].get(
        "coordinator_realtime_mains"
    )
    coordinator_1mon = hass.data[DOMAIN][config_entry.entry_id]["coordinator_1mon"]
    coordinator_day_sensor = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator_day_sensor"
    ]

    _LOGGER.info(hass.data[DOMAIN][config_entry.entry_id])

    if coordinator_1min:
        async_add_entities(
            CurrentVuePowerSensor(coordinator_1min, identifier)
            for _, identifier in enumerate(coordinator_1min.data)
        )

    if coordinator_realtime_mains:
        async_add_entities(
            CurrentVuePowerSensor(coordinator_realtime_mains, identifier)
            for _, identifier in enumerate(coordinator_realtime_mains.data)
        )
        async_add_entities(
            RealtimeVueEnergySampleSensor(coordinator_realtime_mains, identifier)
            for _, identifier in enumerate(coordinator_realtime_mains.data)
        )
        async_add_entities(
            RealtimeVueHourEnergySensor(coordinator_realtime_mains, identifier)
            for _, identifier in enumerate(coordinator_realtime_mains.data)
        )
        async_add_entities(
            RealtimeVueHourAverageDemandSensor(coordinator_realtime_mains, identifier)
            for _, identifier in enumerate(coordinator_realtime_mains.data)
        )
        async_add_entities(
            RealtimeVueLastCompletedHourEnergySensor(coordinator_realtime_mains, identifier)
            for _, identifier in enumerate(coordinator_realtime_mains.data)
        )
        async_add_entities(
            RealtimeVuePeakDemandTodaySensor(coordinator_realtime_mains, identifier)
            for _, identifier in enumerate(coordinator_realtime_mains.data)
        )

    if coordinator_1mon:
        async_add_entities(
            CurrentVuePowerSensor(coordinator_1mon, identifier)
            for _, identifier in enumerate(coordinator_1mon.data)
        )

    if coordinator_day_sensor:
        async_add_entities(
            CurrentVuePowerSensor(coordinator_day_sensor, identifier)
            for _, identifier in enumerate(coordinator_day_sensor.data)
        )

    # Add charger status sensors
    coordinator_device_status = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator_device_status"
    ]
    device_information: dict[int, VueDevice] = hass.data[DOMAIN][config_entry.entry_id][
        "device_information"
    ]
    if coordinator_device_status and coordinator_device_status.data:
        async_add_entities(
            EmporiaChargerStatusSensor(coordinator_device_status, device_information[int(gid)])
            for gid in coordinator_device_status.data
            if int(gid) in device_information and device_information[int(gid)].ev_charger
        )


class CurrentVuePowerSensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Representation of a Vue Sensor's current power."""

    def __init__(self, coordinator, identifier) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self._id = identifier
        self._scale: str = coordinator.data[identifier]["scale"]
        device_gid: int = coordinator.data[identifier]["device_gid"]
        channel_num: str = coordinator.data[identifier]["channel_num"]
        self._device: VueDevice = coordinator.data[identifier]["info"]
        final_channel: VueDeviceChannel | None = None
        if self._device is not None:
            for channel in self._device.channels:
                if channel.channel_num == channel_num:
                    final_channel = channel
                    break
        if final_channel is None:
            _LOGGER.warning(
                "No channel found for device_gid %s and channel_num %s",
                device_gid,
                channel_num,
            )
            raise RuntimeError(
                f"No channel found for device_gid {device_gid} and channel_num {channel_num}"
            )
        self._channel: VueDeviceChannel = final_channel
        self._iskwh = self.scale_is_energy()

        self._attr_has_entity_name = True
        if self._iskwh:
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_state_class = SensorStateClass.TOTAL
            self._attr_suggested_display_precision = 3
            self._attr_name = f"Energy {self.scale_readable()}"
        else:
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 1
            self._attr_name = f"Power {self.scale_readable()}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        device_name = self._channel.name or self._device.device_name
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self._device.device_gid}-{self._channel.channel_num}")
            },
            name=device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

    @property
    def last_reset(self) -> datetime | None:
        """Reset time of the daily/monthly sensor. Midnight local time."""
        if self._id in self.coordinator.data:
            return self.coordinator.data[self._id]["reset"]
        return None

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self._id in self.coordinator.data:
            usage = self.coordinator.data[self._id]["usage"]
            return self.scale_usage(usage) if usage is not None else None
        return None

    @property
    def unique_id(self) -> str:
        """Return the Unique ID for the sensor."""
        if self._scale == Scale.MINUTE.value:
            return (
                "sensor.emporia_vue.instant."
                f"{self._channel.device_gid}-{self._channel.channel_num}"
            )
        return (
            f"sensor.emporia_vue.{self._scale}."
            f"{self._channel.device_gid}-{self._channel.channel_num}"
        )

    def scale_usage(self, usage):
        """Scales the usage to the correct timescale and magnitude."""
        if self._scale == Scale.MINUTE.value:
            usage = 60 * 1000 * usage  # convert from kwh to w rate
        elif self._scale == Scale.SECOND.value:
            usage = 3600 * 1000 * usage  # convert to rate
        elif self._scale == Scale.MINUTES_15.value:
            usage = (
                4 * 1000 * usage
            )  # this might never be used but for safety, convert to rate
        return usage

    def scale_is_energy(self):
        """Return True if the scale is an energy unit instead of power."""
        return self._scale not in (
            Scale.MINUTE.value,
            Scale.SECOND.value,
            Scale.MINUTES_15.value,
        )

    def scale_readable(self):
        """Return a human readable scale."""
        if self._scale == Scale.MINUTE.value:
            return "Minute Average"
        if self._scale == Scale.SECOND.value:
            return "Realtime"
        if self._scale == Scale.DAY.value:
            return "Today"
        if self._scale == Scale.MONTH.value:
            return "This Month"
        return self._scale


class RealtimeVueEnergySampleSensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Latest raw one-second Mains energy sample returned by Emporia."""

    def __init__(self, coordinator, identifier) -> None:
        """Initialize the raw realtime energy sample sensor."""
        super().__init__(coordinator)
        self._id = identifier
        device_gid: int = coordinator.data[identifier]["device_gid"]
        channel_num: str = coordinator.data[identifier]["channel_num"]
        self._device: VueDevice = coordinator.data[identifier]["info"]
        final_channel = next(
            (
                channel
                for channel in self._device.channels
                if channel.channel_num == channel_num
            ),
            None,
        )
        if final_channel is None:
            raise RuntimeError(
                f"No channel found for device_gid {device_gid} and channel_num {channel_num}"
            )
        self._channel: VueDeviceChannel = final_channel

        self._attr_has_entity_name = True
        self._attr_name = "Energy Realtime 1s Sample"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        # This is an interval/delta sample, not a cumulative meter reading.
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 6

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        device_name = self._channel.name or self._device.device_name
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self._device.device_gid}-{self._channel.channel_num}")
            },
            name=device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

    @property
    def native_value(self) -> float | None:
        """Return the raw kWh used in the latest one-second bucket."""
        if self._id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._id]["usage"]

    @property
    def unique_id(self) -> str:
        """Return a unique ID distinct from the realtime power sensor."""
        return (
            "sensor.emporia_vue.realtime_energy_sample."
            f"{self._channel.device_gid}-{self._channel.channel_num}"
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose the timestamp of the one-second bucket."""
        if self._id not in self.coordinator.data:
            return None
        timestamp = self.coordinator.data[self._id].get("timestamp")
        if timestamp is None:
            return None
        return {"sample_timestamp": timestamp.isoformat()}


class RealtimeVueHourEnergySensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Energy accumulated from unique 1-second Mains buckets this clock hour."""

    def __init__(self, coordinator, identifier) -> None:
        super().__init__(coordinator)
        self._id = identifier
        self._device: VueDevice = coordinator.data[identifier]["info"]
        channel_num = coordinator.data[identifier]["channel_num"]
        self._channel = next(
            channel for channel in self._device.channels if channel.channel_num == channel_num
        )
        self._attr_has_entity_name = True
        self._attr_name = "APS Current Hour Energy"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_suggested_display_precision = 4

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device.device_gid}-{self._channel.channel_num}")},
            name=self._channel.name or self._device.device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

    @property
    def native_value(self) -> float | None:
        if self._id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._id].get("hour_energy")

    @property
    def unique_id(self) -> str:
        return (
            "sensor.emporia_vue.aps_current_hour_energy."
            f"{self._channel.device_gid}-{self._channel.channel_num}"
        )

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        if self._id not in self.coordinator.data:
            return None
        data = self.coordinator.data[self._id]
        hour_start = data.get("hour_start")
        return {
            "hour_start": hour_start.isoformat() if hour_start else None,
            "sample_count": data.get("hour_sample_count", 0),
        }


class RealtimeVueHourAverageDemandSensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Average kW demand so far in the current clock hour."""

    def __init__(self, coordinator, identifier) -> None:
        super().__init__(coordinator)
        self._id = identifier
        self._device: VueDevice = coordinator.data[identifier]["info"]
        channel_num = coordinator.data[identifier]["channel_num"]
        self._channel = next(
            channel for channel in self._device.channels if channel.channel_num == channel_num
        )
        self._attr_has_entity_name = True
        self._attr_name = "APS Current Hour Average Demand"
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 3

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device.device_gid}-{self._channel.channel_num}")},
            name=self._channel.name or self._device.device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

    @property
    def native_value(self) -> float | None:
        if self._id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._id].get("hour_average_kw")

    @property
    def unique_id(self) -> str:
        return (
            "sensor.emporia_vue.aps_current_hour_average_demand."
            f"{self._channel.device_gid}-{self._channel.channel_num}"
        )


class RealtimeVueLastCompletedHourEnergySensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Energy used in the most recently completed realtime clock-hour block."""

    def __init__(self, coordinator, identifier) -> None:
        super().__init__(coordinator)
        self._id = identifier
        self._device: VueDevice = coordinator.data[identifier]["info"]
        channel_num = coordinator.data[identifier]["channel_num"]
        self._channel = next(
            channel for channel in self._device.channels if channel.channel_num == channel_num
        )
        self._attr_has_entity_name = True
        self._attr_name = "APS Last Completed Hour Energy"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 4

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device.device_gid}-{self._channel.channel_num}")},
            name=self._channel.name or self._device.device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

    @property
    def native_value(self) -> float | None:
        if self._id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._id].get("last_completed_hour_energy", 0.0)

    @property
    def unique_id(self) -> str:
        return (
            "sensor.emporia_vue.aps_last_completed_hour_energy."
            f"{self._channel.device_gid}-{self._channel.channel_num}"
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        start = self.coordinator.data[self._id].get("last_completed_hour_start")
        return {"hour_start": start.isoformat() if start else None}


class RealtimeVuePeakDemandTodaySensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Highest completed one-hour demand block observed today."""

    def __init__(self, coordinator, identifier) -> None:
        super().__init__(coordinator)
        self._id = identifier
        self._device: VueDevice = coordinator.data[identifier]["info"]
        channel_num = coordinator.data[identifier]["channel_num"]
        self._channel = next(
            channel for channel in self._device.channels if channel.channel_num == channel_num
        )
        self._attr_has_entity_name = True
        self._attr_name = "APS Peak Demand Today"
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 3

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device.device_gid}-{self._channel.channel_num}")},
            name=self._channel.name or self._device.device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

    @property
    def native_value(self) -> float | None:
        if self._id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._id].get("peak_demand_today_kw", 0.0)

    @property
    def unique_id(self) -> str:
        return (
            "sensor.emporia_vue.aps_peak_demand_today."
            f"{self._channel.device_gid}-{self._channel.channel_num}"
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        start = self.coordinator.data[self._id].get("peak_demand_hour_start")
        return {"peak_hour_start": start.isoformat() if start else None}


# Known Emporia charger API responses (from historical data):
#   Status: "Charging", "Standby", "DeviceNotConnected", ""
#   Messages: "Charging", "Ready", "Off", "Self Test", "Offline",
#             "EV is not accepting charge", "Connected to EV",
#             "Please Wait", "Charging Halted", ""

def _map_charger_state(status: str | None, message: str | None, fault_text: str | None) -> tuple[str, str]:
    """Map Emporia charger status/message to a human-friendly state and IEC 61851 code."""
    status_lower = (status or "").lower()
    message_lower = (message or "").lower()
    fault = (fault_text or "").strip()

    # F: Fault condition
    if fault or "error" in status_lower or "fault" in status_lower or "error" in message_lower or "fault" in message_lower:
        return "Error", "F"
    # C: Actively charging
    if status_lower == "charging":
        return "Charging", "C"
    # A: Disconnected -  no EV present or device offline
    if not status_lower:
        return "Disconnected", "A"
    if status_lower == "devicenotconnected":
        return "Disconnected", "A"
    if status_lower == "standby" and message_lower in ("ready", "off", "self test", "please wait"):
        return "Disconnected", "A"
    # B: Connected but not charging (default for unknown/unmapped states)
    if status_lower != "standby":
        _LOGGER.debug(
            "Unmapped charger state: status=%s, message=%s", status, message
        )
    return "Connected", "B"


CHARGER_STATUS_OPTIONS = ["Disconnected", "Connected", "Charging", "Error"]

class EmporiaChargerStatusSensor(CoordinatorEntity, SensorEntity):  # type: ignore
    """Representation of an Emporia Charger status sensor."""

    def __init__(self, coordinator, device: VueDevice) -> None:
        """Initialize the charger status sensor."""
        super().__init__(coordinator)
        self._device = device
        self._device_gid = str(device.device_gid)
        self._attr_has_entity_name = True
        self._attr_name = "Status"
        self._attr_translation_key = "charger_status"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = CHARGER_STATUS_OPTIONS
        self._attr_icon = "mdi:ev-station"

    @property
    def native_value(self) -> str:
        """Return the human-friendly charger status."""
        data: ChargerDevice | None = self.coordinator.data.get(self._device_gid)
        if data:
            state, _ = _map_charger_state(data.status, data.message, data.fault_text)
            return state
        return "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return IEC code and raw Emporia values as attributes."""
        data: ChargerDevice | None = self.coordinator.data.get(self._device_gid)
        if data:
            _, iec_code = _map_charger_state(data.status, data.message, data.fault_text)
            return {
                "iec_status": iec_code,
                "raw_status": data.status,
                "raw_message": data.message,
                "fault_text": data.fault_text,
            }
        return {}

    @property
    def unique_id(self) -> str:
        """Unique ID for the charger status sensor."""
        return f"emporia_vue.charger_status_{self._device_gid}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device_gid}-1,2,3")},
            name=self._device.device_name,
            model=self._device.model,
            sw_version=self._device.firmware,
            manufacturer="Emporia",
        )

