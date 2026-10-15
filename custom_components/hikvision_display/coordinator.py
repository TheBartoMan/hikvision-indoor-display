"""Entry-owned polling and serialized display commands."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .catalog import resolve_camera
from .const import DEFAULT_BRIGHTNESS, DEFAULT_INTERVAL, DOMAIN
from .errors import AuthenticationError, BusyStation, ConnectionFailure, StationError, UnsupportedFirmware
from .protocol import StationSession
from .solver import load_seeds

LOGGER = logging.getLogger(__name__)
SESSION_IDLE_SECONDS = 60
SESSION_MAX_SECONDS = 600


class DisplayCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(seconds=entry.options.get("scan_interval", DEFAULT_INTERVAL)))
        self.entry = entry
        self.connection_data = dict(entry.data)
        self.seeds = None
        self.operation_lock = asyncio.Lock()
        self.active_task = None
        self.stopping = False
        self.owned_preview = None
        self.brightness = entry.options.get("brightness", DEFAULT_BRIGHTNESS)
        self.selected_label = None
        self.last_result = "not_connected"
        self.last_success = None
        self._session = None
        self._session_started = None
        self._runtime_identity = None
        self._idle_task = None

    def _new_session(self):
        data = self.entry.data
        return StationSession(data["host"], data["port"], data["password"], data["public_key"],
                              self.seeds, self.hass.async_add_executor_job, self.owned_preview)

    async def _cancel_idle_close(self):
        task, self._idle_task = self._idle_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _close_session(self, invalidate_preview=False):
        session, self._session = self._session, None
        self._session_started = None
        if invalidate_preview:
            self.owned_preview = None
            self.selected_label = None
        if session is not None:
            await session.close()

    async def _close_when_idle(self, session, seconds):
        try:
            await asyncio.sleep(seconds)
            async with self.operation_lock:
                if self._session is session:
                    await self._close_session()
        finally:
            if self._idle_task is asyncio.current_task():
                self._idle_task = None

    @asynccontextmanager
    async def session(self):
        # Callers hold the station lock; never retry an action after yielding.
        await self._cancel_idle_close()
        loop = asyncio.get_running_loop()
        try:
            if self.stopping or dict(self.entry.data) != self.connection_data:
                raise ConnectionFailure("Station configuration changed; integration reload required")
            if self._session is not None:
                if loop.time() - self._session_started >= SESSION_MAX_SECONDS:
                    await self._close_session()
                else:
                    try:
                        await self._session.verify_runtime()
                    except ConnectionFailure:
                        await self._close_session(invalidate_preview=True)
            if self._session is None:
                self._session = self._new_session()
                await self._session.__aenter__()
                self._session_started = loop.time()
                runtime = self._session.runtime_identity
                if self._runtime_identity is not None and runtime != self._runtime_identity:
                    self.owned_preview = None
                    self.selected_label = None
                self._runtime_identity = runtime
            self._session.owned_preview = self.owned_preview
            self._session.opened_preview = None
            yield self._session
        except BaseException:
            await self._close_session(invalidate_preview=True)
            raise
        finally:
            if self._session is not None and not self.stopping:
                remaining = SESSION_MAX_SECONDS - (loop.time() - self._session_started)
                if remaining <= 0:
                    await self._close_session()
                else:
                    self._idle_task = asyncio.create_task(self._close_when_idle(
                        self._session, min(SESSION_IDLE_SECONDS, remaining)))

    async def async_shutdown(self):
        self.stopping = True
        task = self.active_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._cancel_idle_close()
        await self._close_session(invalidate_preview=True)
        await super().async_shutdown()
        self.seeds = None

    async def _async_update_data(self):
        if self.stopping:
            raise UpdateFailed("Integration is unloading")
        if self.operation_lock.locked() and self.data is not None:
            return self.data
        async with self.operation_lock:
            self.active_task = asyncio.current_task()
            try:
                if self.seeds is None:
                    self.seeds = await self.hass.async_add_executor_job(load_seeds)
                async with self.session() as session:
                    cameras = await session.discover()
                self.last_success = dt_util.utcnow()
                self.last_result = "catalog_refreshed"
                return cameras
            except AuthenticationError:
                raise ConfigEntryAuthFailed("Station authentication failed; reconfigure credentials") from None
            except UnsupportedFirmware:
                raise UpdateFailed("Unsupported running firmware; controls were not sent") from None
            except (StationError, OSError, ValueError):
                raise UpdateFailed("Station discovery failed; existing catalog is stale") from None
            finally:
                self.active_task = None

    async def perform(self, action, value=None):
        if self.stopping or self.operation_lock.locked():
            raise HomeAssistantError("Another station operation is running; retry shortly")
        if action not in {"camera", "display_on", "display_off", "brightness", "home", "check"}:
            raise HomeAssistantError("Unsupported display action")
        if action == "brightness" and (type(value) is not int or not 1 <= value <= 100):
            raise HomeAssistantError("Brightness must be an integer from 1 to 100")
        async with self.operation_lock:
            self.active_task = asyncio.current_task()
            try:
                async with self.session() as session:
                    if action == "camera":
                        cameras = await session.discover()
                        self.last_success = dt_util.utcnow()
                        self.async_set_updated_data(cameras)
                        camera = resolve_camera(value, cameras)
                        self.owned_preview = None
                        await session.show_camera(camera, self.brightness)
                        self.owned_preview = session.opened_preview
                        self.selected_label = camera.label
                        self.last_result = "camera_command_sent"
                    elif action == "home":
                        await session.home()
                        self.owned_preview = None
                        self.selected_label = None
                        self.last_result = "home_navigation_confirmed"
                    elif action == "check":
                        current = await session.window()
                        self.last_result = "connection_verified" if current else "window_unrecognized"
                    else:
                        level = (0 if action == "display_off" else
                                 value if action == "brightness" else self.brightness)
                        await session.display(level)
                        if action == "brightness":
                            self.brightness = value
                            self.hass.config_entries.async_update_entry(
                                self.entry, options={**self.entry.options, "brightness": value})
                        self.last_result = "display_command_sent"
                self.async_update_listeners()
            except AuthenticationError:
                self.last_result = "authentication_failed"
                self.entry.async_start_reauth(self.hass)
                self.async_update_listeners()
                raise HomeAssistantError("Station rejected authentication; reauthenticate in Settings") from None
            except BusyStation:
                self.last_result = "busy"
                self.async_update_listeners()
                raise HomeAssistantError("Display is busy or in an unrecognized window") from None
            except (StationError, OSError, ValueError):
                self.last_result = "command_failed"
                self.async_update_listeners()
                raise HomeAssistantError("Station command failed; refresh cameras and check the station") from None
            finally:
                self.active_task = None
