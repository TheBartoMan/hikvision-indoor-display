"""Requested brightness, applied immediately and never presented as measured state."""
from homeassistant.components.number import NumberEntity, NumberMode

from .entity import DisplayEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BrightnessNumber(entry.runtime_data)])


class BrightnessNumber(DisplayEntity, NumberEntity):
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator):
        super().__init__(coordinator, "brightness", "Requested brightness", "mdi:brightness-6")

    @property
    def native_value(self):
        return self.coordinator.brightness

    async def async_set_native_value(self, value):
        if not float(value).is_integer():
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError("Brightness must be a whole number")
        await self.coordinator.perform("brightness", int(value))
