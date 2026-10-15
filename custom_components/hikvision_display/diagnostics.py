"""Diagnostic exports contain no addresses, credentials, names or host keys."""
from .coordinator import SESSION_IDLE_SECONDS, SESSION_MAX_SECONDS


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "supported_profile": "DS-KH6320-WTE1 V2.2.108 build 250718, English 1024x600",
        "last_update_success": coordinator.last_update_success,
        "last_result": coordinator.last_result,
        "poll_seconds": coordinator.update_interval.total_seconds(),
        "operation_running": coordinator.operation_lock.locked(),
        "camera_count": len(coordinator.data or ()),
        "camera_types": [camera.kind for camera in coordinator.data or ()],
        "session_connected": coordinator._session is not None and coordinator._session.is_connected(),
        "session_idle_timeout_seconds": SESSION_IDLE_SECONDS,
        "session_max_lifetime_seconds": SESSION_MAX_SECONDS,
    }
