"""Catalog count and sanitized results owned by the integration entry."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import DisplayEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CatalogSensor(entry.runtime_data), ResultSensor(entry.runtime_data)])


class CatalogSensor(DisplayEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "camera_count", "Camera count", "mdi:cctv")

    @property
    def native_value(self):
        return len(self.coordinator.data or ())

    @property
    def extra_state_attributes(self):
        return {"cameras": [{"name": c.name, "label": c.label, "type": c.kind,
                             "device_id": c.device_id, "slot": c.slot}
                            for c in self.coordinator.data or ()],
                "last_success": self.coordinator.last_success.isoformat()
                if self.coordinator.last_success else None}


class ResultSensor(DisplayEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "last_result", "Last result", "mdi:information-outline")

    @property
    def native_value(self):
        return self.coordinator.last_result
