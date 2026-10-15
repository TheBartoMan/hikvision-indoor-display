"""A live camera selector, rather than a separately installed helper."""
from homeassistant.components.select import SelectEntity

from .entity import DisplayEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CameraSelect(entry.runtime_data)])


class CameraSelect(DisplayEntity, SelectEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "camera", "Camera", "mdi:cctv")

    @property
    def options(self):
        return [camera.label for camera in self.coordinator.data or ()]

    @property
    def current_option(self):
        label = self.coordinator.selected_label
        return label if label in self.options else None

    @property
    def available(self):
        return super().available and bool(self.coordinator.data)

    async def async_select_option(self, option):
        await self.coordinator.perform("camera", option)
