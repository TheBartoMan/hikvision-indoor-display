"""Small HA API doubles, explicitly not a substitute for a live HA lifecycle test."""
import asyncio
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/hikvision_display"
package = types.ModuleType("test_hikvision")
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package


def module(name, **attributes):
    value = types.ModuleType(name)
    value.__dict__.update(attributes)
    sys.modules[name] = value
    return value


class HomeAssistantError(Exception):
    pass


class ConfigEntryAuthFailed(HomeAssistantError):
    pass


class UpdateFailed(HomeAssistantError):
    pass


class Coordinator:
    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.config_entry = kwargs["config_entry"]
        self.update_interval = kwargs["update_interval"]
        self.data = None
        self.last_update_success = True
        self.shutdown_called = False
        self.notifications = 0

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def async_request_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except UpdateFailed:
            self.last_update_success = False

    async def async_shutdown(self):
        self.shutdown_called = True

    def async_set_updated_data(self, data):
        self.data = data
        self.last_update_success = True
        self.async_update_listeners()

    def async_update_listeners(self):
        self.notifications += 1


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


class ConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    async def async_set_unique_id(self, value):
        self.unique_id = value

    def _abort_if_unique_id_configured(self):
        if self.unique_id in getattr(self.hass, "existing_ids", set()):
            raise RuntimeError("already_configured")

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def _get_reauth_entry(self):
        return self.test_entry

    def _get_reconfigure_entry(self):
        return self.test_entry

    def async_update_reload_and_abort(self, entry, **kwargs):
        return {"type": "abort", "updated": kwargs, "entry": entry}

    def async_update_and_abort(self, entry, **kwargs):
        return {"type": "abort", "updated": kwargs, "entry": entry, "listener_reload": True}


class OptionsFlow(ConfigFlow):
    pass


class Platform:
    SELECT, NUMBER, BUTTON, SENSOR = "select", "number", "button", "sensor"


class EntityCategory:
    DIAGNOSTIC = "diagnostic"


class NumberMode:
    SLIDER = "slider"


class TextSelector:
    def __init__(self, config):
        pass

    def __call__(self, value):
        return str(value)


ha = module("homeassistant")
ha.config_entries = module("homeassistant.config_entries", ConfigFlow=ConfigFlow, OptionsFlow=OptionsFlow)
module("homeassistant.const", Platform=Platform)
module("homeassistant.core", callback=lambda function: function)
module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError, ConfigEntryAuthFailed=ConfigEntryAuthFailed)
module("homeassistant.helpers")
module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=Coordinator,
       CoordinatorEntity=CoordinatorEntity, UpdateFailed=UpdateFailed)
module("homeassistant.helpers.device_registry", DeviceInfo=lambda **kwargs: kwargs)
module("homeassistant.helpers.entity", EntityCategory=EntityCategory)
module("homeassistant.helpers.selector", TextSelector=TextSelector, TextSelectorConfig=lambda **kwargs: kwargs,
       TextSelectorType=types.SimpleNamespace(PASSWORD="password"))
module("homeassistant.components")
for name, attribute in [("select", "SelectEntity"), ("number", "NumberEntity"),
                        ("button", "ButtonEntity"), ("sensor", "SensorEntity")]:
    extras = {"NumberMode": NumberMode} if name == "number" else {}
    module("homeassistant.components." + name, **{attribute: type(attribute, (), {}), **extras})
util = module("homeassistant.util")
util.dt = module("homeassistant.util.dt", utcnow=lambda: datetime.now(timezone.utc))


class Entry:
    def __init__(self, identifier="SHA256:FAKE_FINGERPRINT"):
        self.unique_id, self.entry_id, self.title = identifier, identifier, "Test station"
        self.data = {"host": "192.0.2.10", "port": 22, "password": "FAKE_PASSWORD", "public_key": "FAKE_KEY"}
        self.options = {}
        self.cleanup = []
        self.reauth_started = False
        self.update_listeners = []

    def async_on_unload(self, function):
        self.cleanup.append(function)

    def add_update_listener(self, callback):
        self.listener = callback
        self.update_listeners.append(callback)
        return lambda: None

    def async_start_reauth(self, hass):
        self.reauth_started = True


class Hass:
    def __init__(self):
        self.config_entries = self
        self.forwarded = self.unloaded = None
        self.allow_unload = True
        self.reloads = []

    async def async_add_executor_job(self, function, *args):
        return await asyncio.to_thread(function, *args)

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded = list(platforms)

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded = list(platforms)
        return self.allow_unload

    def async_update_entry(self, entry, **kwargs):
        for key, value in kwargs.items():
            setattr(entry, key, value)

    def async_schedule_reload(self, entry_id):
        self.reloads.append(entry_id)


def component(name):
    return importlib.import_module("test_hikvision." + name)
