"""UI setup with explicit host-key trust, compatibility checks and reauthentication."""
import asyncssh
import probatio as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULT_BRIGHTNESS, DEFAULT_INTERVAL, DOMAIN
from .errors import AuthenticationError, ConnectionFailure, StationError, UnsupportedFirmware
from .protocol import StationSession, probe_host_key, validate_host
from .solver import load_seeds

PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


async def validate_station(hass, data):
    seeds = await hass.async_add_executor_job(load_seeds)
    async with StationSession(data["host"], data["port"], data["password"], data["public_key"],
                              seeds, hass.async_add_executor_job) as station:
        return await station.discover()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.connection_data = {}
        self.public_key = self.fingerprint = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                host = validate_host(user_input["host"])
                port = user_input["port"]
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError
                self.public_key, self.fingerprint = await probe_host_key(host, port)
                self.connection_data = {"host": host, "port": port, "name": user_input["name"]}
                await self.async_set_unique_id(self.fingerprint)
                self._abort_if_unique_id_configured()
                return await self.async_step_trust()
            except ValueError:
                errors["base"] = "invalid_host"
            except ConnectionFailure:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("host"): str,
            vol.Required("port", default=22): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required("name", default="Indoor display"): vol.All(str, vol.Length(min=1, max=80))}))

    async def async_step_trust(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get("verified") is True:
                return await self.async_step_credentials()
            errors["base"] = "verify_host_key"
        return self.async_show_form(step_id="trust", errors=errors,
            description_placeholders={"fingerprint": self.fingerprint, "host": self.connection_data["host"]},
            data_schema=vol.Schema({vol.Required("verified", default=False): bool}))

    async def async_step_credentials(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not user_input.get("supported_device"):
                errors["base"] = "unsupported_device"
            else:
                data = {"host": self.connection_data["host"], "port": self.connection_data["port"],
                        "public_key": self.public_key, "password": user_input["password"]}
                errors = await self._validate(data)
                if not errors:
                    return self.async_create_entry(title=self.connection_data["name"], data=data)
        return self.async_show_form(step_id="credentials", errors=errors, data_schema=vol.Schema({
            vol.Required("password"): PASSWORD,
            vol.Required("supported_device", default=False): bool}))

    async def _validate(self, data):
        if (not data["password"] or "\n" in data["password"] or "\r" in data["password"]
                or len(data["password"]) > 256):
            return {"base": "invalid_auth"}
        try:
            await validate_station(self.hass, data)
        except AuthenticationError:
            return {"base": "invalid_auth"}
        except UnsupportedFirmware:
            return {"base": "unsupported_firmware"}
        except (ConnectionFailure, OSError, asyncssh.Error):
            return {"base": "cannot_connect"}
        except (StationError, ValueError):
            return {"base": "discovery_failed"}
        return {}

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            data = {**entry.data, "password": user_input["password"]}
            errors = await self._validate(data)
            if not errors:
                return self._update_entry(entry, data)
        return self.async_show_form(step_id="reauth_confirm", errors=errors,
                                   data_schema=vol.Schema({vol.Required("password"): PASSWORD}))

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                data = {**entry.data, "host": validate_host(user_input["host"]), "port": user_input["port"]}
                if user_input.get("password"):
                    data["password"] = user_input["password"]
                errors = await self._validate(data)
                if not errors:
                    return self._update_entry(entry, data)
            except ValueError:
                errors["base"] = "invalid_host"
        return self.async_show_form(step_id="reconfigure", errors=errors, data_schema=vol.Schema({
            vol.Required("host", default=entry.data["host"]): str,
            vol.Required("port", default=entry.data["port"]): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional("password"): PASSWORD}))

    def _update_entry(self, entry, data):
        if entry.update_listeners:
            return self.async_update_and_abort(entry, data_updates=data)
        return self.async_update_reload_and_abort(entry, data_updates=data)


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("scan_interval", default=self.config_entry.options.get(
                "scan_interval", DEFAULT_INTERVAL)): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
            vol.Required("brightness", default=self.config_entry.options.get(
                "brightness", DEFAULT_BRIGHTNESS)): vol.All(vol.Coerce(int), vol.Range(min=1, max=100))}))
