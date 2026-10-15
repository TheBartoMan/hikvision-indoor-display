"""Integration-owned entities; no app, YAML package, scripts or global listeners."""
from datetime import timedelta

from .const import DEFAULT_BRIGHTNESS, DEFAULT_INTERVAL, PLATFORMS
from .coordinator import DisplayCoordinator


async def async_setup_entry(hass, entry):
    coordinator = DisplayCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(async_options_updated))
    except BaseException:
        await coordinator.async_shutdown()
        raise
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
        return True
    return False


async def async_options_updated(hass, entry):
    coordinator = entry.runtime_data
    if dict(entry.data) != coordinator.connection_data:
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    coordinator.brightness = entry.options.get("brightness", DEFAULT_BRIGHTNESS)
    coordinator.update_interval = timedelta(seconds=entry.options.get("scan_interval", DEFAULT_INTERVAL))
    coordinator.async_update_listeners()
    if not coordinator.stopping and not coordinator.operation_lock.locked():
        await coordinator.async_request_refresh()
