"""Momentary commands with no invented screen-power switch state."""
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import DisplayEntity

ACTIONS = [("display_on", "Display on", "mdi:monitor"),
           ("display_off", "Display off", "mdi:monitor-off"),
           ("home", "Home", "mdi:home"),
           ("refresh", "Refresh cameras", "mdi:refresh"),
           ("check", "Check connection", "mdi:connection")]


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DisplayButton(entry.runtime_data, *action) for action in ACTIONS])


class DisplayButton(DisplayEntity, ButtonEntity):
    def __init__(self, coordinator, action, name, icon):
        super().__init__(coordinator, action, name, icon)
        self.action = action
        if action in {"check", "refresh"}:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        # Keep refresh available to recover a failed poll.
        return not self.coordinator.stopping if self.action == "refresh" else super().available

    async def async_press(self):
        if self.action == "refresh":
            from homeassistant.exceptions import HomeAssistantError
            if self.coordinator.operation_lock.locked():
                raise HomeAssistantError("Another operation is running; retry shortly")
            await self.coordinator.async_request_refresh()
            if not self.coordinator.last_update_success:
                raise HomeAssistantError("Camera discovery failed; check integration status")
        else:
            await self.coordinator.perform(self.action)
