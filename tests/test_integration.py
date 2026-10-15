import asyncio
import ast
from datetime import timedelta
import json
import re
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import probatio as vol

from bootstrap import COMPONENT, ROOT, Entry, Hass, HomeAssistantError, ConfigEntryAuthFailed, component
from test_protocol import catalog

c = component("coordinator")
d = component("catalog")
e = component("errors")
init = component("__init__")
cf = component("config_flow")
diagnostics = component("diagnostics")


class FakeSession:
    text = catalog()
    failure = None
    show_failure = False
    hold = None
    opened = closed = 0
    actions = []
    runtime = ("238", "12345")
    checks = 0
    connect_failure = None
    action_failure = None
    action_hold = None

    def __init__(self, *args):
        self.opened_preview = None
        self.owned_preview = args[-1]
        self.runtime_identity = self.runtime
        self.connected = False

    async def __aenter__(self):
        type(self).opened += 1
        self.connected = True
        if self.connect_failure:
            raise self.connect_failure("FAKE_SECRET_EXCEPTION")
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self.connected:
            type(self).closed += 1
        self.connected = False

    async def verify_runtime(self):
        type(self).checks += 1
        if not self.connected or self.runtime_identity != type(self).runtime:
            raise e.ConnectionFailure("FAKE_SECRET_EXCEPTION")

    def is_connected(self):
        return self.connected

    async def discover(self):
        if self.hold is not None:
            await self.hold.wait()
        if self.failure:
            raise self.failure("FAKE_SECRET_EXCEPTION")
        return d.parse_catalog(self.text)

    async def show_camera(self, camera, brightness):
        if self.show_failure:
            raise e.StationError("FAKE_SECRET_EXCEPTION")
        self.actions.append(("camera", camera.label, camera.sequence, brightness))
        if self.action_hold is not None:
            await self.action_hold.wait()
        self.opened_preview = ("", "0x9999")

    async def display(self, level):
        self.actions.append(("display", level))
        if self.action_failure:
            raise self.action_failure("FAKE_SECRET_EXCEPTION")

    async def home(self):
        self.actions.append(("home",))

    async def window(self):
        return ("Mydesktop", "0x1234")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass, self.entry = Hass(), Entry()
        FakeSession.text, FakeSession.failure, FakeSession.show_failure = catalog(), None, False
        FakeSession.hold = None
        FakeSession.opened = FakeSession.closed = 0
        FakeSession.actions = []
        FakeSession.runtime, FakeSession.checks = ("238", "12345"), 0
        FakeSession.connect_failure = FakeSession.action_failure = None
        FakeSession.action_hold = None
        self.session_patch = patch.object(c, "StationSession", FakeSession)
        self.seed_patch = patch.object(c, "load_seeds", return_value=[])
        self.session_patch.start()
        self.seed_patch.start()
        self.coordinator = c.DisplayCoordinator(self.hass, self.entry)

    async def asyncTearDown(self):
        await self.coordinator.async_shutdown()
        self.session_patch.stop()
        self.seed_patch.stop()

    async def refresh(self):
        await self.coordinator.async_config_entry_first_refresh()

    async def test_setup_owns_platforms_and_listener_cleanup(self):
        self.assertTrue(await init.async_setup_entry(self.hass, self.entry))
        self.assertEqual(self.hass.forwarded, ["select", "number", "button", "sensor"])
        self.assertEqual(len(self.entry.runtime_data.data), 3)
        self.assertEqual(len(self.entry.cleanup), 1)
        self.assertTrue(await init.async_unload_entry(self.hass, self.entry))
        self.assertTrue(self.entry.runtime_data.stopping)
        self.assertTrue(self.entry.runtime_data.shutdown_called)

    async def test_failed_setup_cleans_coordinator(self):
        FakeSession.failure = e.UnsupportedFirmware
        with patch.object(init, "DisplayCoordinator", return_value=self.coordinator):
            with self.assertRaises(c.UpdateFailed) as context:
                await init.async_setup_entry(self.hass, self.entry)
        self.assertTrue(self.coordinator.stopping)
        self.assertNotIn("FAKE_SECRET", str(context.exception))
        self.assertIsNone(self.hass.forwarded)

    async def test_failed_platform_unload_does_not_shutdown_still_loaded_entry(self):
        self.entry.runtime_data = self.coordinator
        self.hass.allow_unload = False
        self.assertFalse(await init.async_unload_entry(self.hass, self.entry))
        self.assertFalse(self.coordinator.stopping)

    async def test_shutdown_cancels_active_poll_and_closes_session(self):
        FakeSession.hold = asyncio.Event()
        task = asyncio.create_task(self.coordinator._async_update_data())
        await asyncio.sleep(0.01)
        await self.coordinator.async_shutdown()
        self.assertTrue(task.cancelled())
        self.assertEqual(FakeSession.opened, FakeSession.closed)
        self.assertFalse(self.coordinator.operation_lock.locked())

    async def test_second_station_has_independent_lifecycle_and_lock(self):
        other = c.DisplayCoordinator(self.hass, Entry("SHA256:SECOND"))
        await self.coordinator.operation_lock.acquire()
        self.assertFalse(other.operation_lock.locked())
        await self.coordinator.async_shutdown()
        self.assertFalse(other.stopping)
        self.coordinator.operation_lock.release()
        await other.async_shutdown()

    async def test_dynamic_options_add_remove_rename_without_recreating_entity(self):
        await self.refresh()
        entity = component("select").CameraSelect(self.coordinator)
        unique_id = entity._attr_unique_id
        FakeSession.text = catalog(("Door", "Renamed", "Added", "Extra"))
        await self.coordinator.async_request_refresh()
        self.assertEqual(entity.options, ["Door", "Renamed", "Added", "Extra"])
        FakeSession.text = catalog(("Door",))
        await self.coordinator.async_request_refresh()
        self.assertEqual(entity.options, ["Door"])
        self.assertEqual(entity._attr_unique_id, unique_id)

    async def test_selection_refreshes_before_actuation_and_rejects_old_name(self):
        await self.refresh()
        FakeSession.text = catalog(("Door", "Renamed"))
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.perform("camera", "Camera A")
        self.assertEqual(FakeSession.actions, [])
        await self.coordinator.perform("camera", "Renamed")
        self.assertEqual(FakeSession.actions[-1], ("camera", "Renamed", 1, 60))
        self.assertEqual(self.coordinator.owned_preview, ("", "0x9999"))

    async def test_failure_never_falls_back_to_stale_catalog(self):
        await self.refresh()
        FakeSession.failure = e.StationError
        with self.assertRaises(HomeAssistantError) as context:
            await self.coordinator.perform("camera", "Camera A")
        self.assertEqual(FakeSession.actions, [])
        self.assertNotIn("FAKE_SECRET", str(context.exception))

    async def test_brightness_on_off_home_and_requested_state(self):
        await self.refresh()
        await self.coordinator.perform("brightness", 77)
        await self.coordinator.perform("display_off")
        await self.coordinator.perform("display_on")
        await self.coordinator.perform("home")
        self.assertEqual(FakeSession.actions, [("display", 77), ("display", 0), ("display", 77), ("home",)])
        self.assertEqual(self.entry.options["brightness"], 77)
        self.assertIsNone(self.coordinator.selected_label)

    async def test_check_does_not_actuate_display(self):
        await self.refresh()
        await self.coordinator.perform("check")
        self.assertEqual(self.coordinator.last_result, "connection_verified")
        self.assertEqual(FakeSession.actions, [])

    async def test_poll_and_controls_reuse_verified_session(self):
        await self.refresh()
        first = self.coordinator._session
        await self.coordinator.perform("display_on")
        await self.coordinator.perform("camera", "Camera A")
        await self.coordinator.async_request_refresh()
        self.assertIs(self.coordinator._session, first)
        self.assertEqual(FakeSession.opened, 1)
        self.assertEqual(FakeSession.closed, 0)
        self.assertEqual(FakeSession.checks, 3)
        await self.coordinator.async_shutdown()
        self.assertEqual(FakeSession.closed, 1)
        self.assertIsNone(self.coordinator._idle_task)

    async def test_idle_expiry_closes_without_unloading_entities(self):
        with patch.object(c, "SESSION_IDLE_SECONDS", 0.001):
            await self.refresh()
        idle = self.coordinator._idle_task
        await asyncio.wait_for(idle, 1)
        self.assertIsNone(self.coordinator._session)
        self.assertIsNone(self.coordinator._idle_task)
        self.assertFalse(self.coordinator.stopping)
        self.assertEqual(FakeSession.closed, 1)
        await self.coordinator.perform("check")
        self.assertEqual(FakeSession.opened, 2)

    async def test_activity_replaces_idle_timer(self):
        await self.refresh()
        first_timer = self.coordinator._idle_task
        await self.coordinator.perform("check")
        self.assertTrue(first_timer.done())
        self.assertIsNot(first_timer, self.coordinator._idle_task)
        self.assertEqual(FakeSession.closed, 0)

    async def test_session_lifetime_forces_fresh_verification(self):
        await self.refresh()
        old = self.coordinator._session
        self.coordinator._session_started -= c.SESSION_MAX_SECONDS
        await self.coordinator.perform("check")
        self.assertIsNot(self.coordinator._session, old)
        self.assertEqual((FakeSession.opened, FakeSession.closed), (2, 1))

    async def test_changed_process_reconnects_and_invalidates_preview(self):
        await self.refresh()
        await self.coordinator.perform("camera", "Camera A")
        FakeSession.runtime = ("238", "98765")
        await self.coordinator.perform("check")
        self.assertEqual((FakeSession.opened, FakeSession.closed), (2, 1))
        self.assertIsNone(self.coordinator.owned_preview)
        self.assertIsNone(self.coordinator.selected_label)
        self.assertIsNone(self.coordinator._session.owned_preview)

    async def test_known_closed_connection_reconnects_before_action(self):
        await self.refresh()
        await self.coordinator._session.close()
        await self.coordinator.perform("display_on")
        self.assertEqual(FakeSession.opened, 2)
        self.assertEqual(FakeSession.actions, [("display", 60)])

    async def test_failure_after_actuation_is_never_replayed(self):
        await self.refresh()
        FakeSession.action_failure = e.ConnectionFailure
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.perform("display_on")
        self.assertEqual(FakeSession.actions, [("display", 60)])
        self.assertEqual((FakeSession.opened, FakeSession.closed), (1, 1))
        self.assertIsNone(self.coordinator._session)
        self.assertIsNone(self.coordinator._idle_task)
        FakeSession.action_failure = None
        await self.coordinator.perform("check")
        self.assertEqual(FakeSession.opened, 2)
        self.assertEqual(FakeSession.actions, [("display", 60)])

    async def test_partial_connect_failure_closes_and_does_not_retry(self):
        FakeSession.connect_failure = e.ConnectionFailure
        with self.assertRaises(c.UpdateFailed):
            await self.refresh()
        self.assertEqual((FakeSession.opened, FakeSession.closed), (1, 1))
        self.assertIsNone(self.coordinator._session)
        self.assertIsNone(self.coordinator._idle_task)

    async def test_process_restart_cannot_bypass_new_firmware_verification(self):
        await self.refresh()
        FakeSession.runtime = ("238", "98765")
        FakeSession.connect_failure = e.UnsupportedFirmware
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.perform("display_on")
        self.assertEqual(FakeSession.actions, [])
        self.assertEqual(FakeSession.opened, FakeSession.closed)

    async def test_shutdown_cancels_active_camera_and_idle_timer(self):
        await self.refresh()
        old_idle = self.coordinator._idle_task
        FakeSession.action_hold = asyncio.Event()
        task = asyncio.create_task(self.coordinator.perform("camera", "Camera A"))
        await asyncio.sleep(0.01)
        await self.coordinator.async_shutdown()
        self.assertTrue(task.cancelled())
        self.assertTrue(old_idle.done())
        self.assertIsNone(self.coordinator._idle_task)
        self.assertIsNone(self.coordinator._session)
        self.assertEqual(FakeSession.opened, FakeSession.closed)

    async def test_pending_reconfiguration_cannot_use_cached_connection(self):
        await self.refresh()
        self.entry.data = {**self.entry.data, "host": "192.0.2.20"}
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.perform("display_on")
        self.assertEqual(FakeSession.actions, [])
        self.assertEqual((FakeSession.opened, FakeSession.closed), (1, 1))

    async def test_two_cached_connections_have_independent_cleanup(self):
        await self.refresh()
        other = c.DisplayCoordinator(self.hass, Entry("SHA256:SECOND"))
        try:
            await other.async_config_entry_first_refresh()
            await self.coordinator.async_shutdown()
            self.assertIsNone(self.coordinator._session)
            self.assertTrue(other._session.is_connected())
            self.assertFalse(other._idle_task.done())
            await other.perform("check")
        finally:
            await other.async_shutdown()
        self.assertEqual(FakeSession.opened, FakeSession.closed)

    async def test_overlapping_and_invalid_commands_rejected(self):
        await self.refresh()
        await self.coordinator.operation_lock.acquire()
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.perform("display_on")
        self.coordinator.operation_lock.release()
        for action, value in [("unlock", None), ("brightness", True), ("brightness", 0), ("brightness", 101)]:
            with self.assertRaises(HomeAssistantError):
                await self.coordinator.perform(action, value)
        self.assertEqual(FakeSession.actions, [])

    async def test_auth_failure_starts_reauth_without_secret_exception(self):
        await self.refresh()
        FakeSession.failure = e.AuthenticationError
        with self.assertRaises(HomeAssistantError) as context:
            await self.coordinator.perform("camera", "Camera A")
        self.assertTrue(self.entry.reauth_started)
        self.assertNotIn("FAKE_SECRET", str(context.exception))
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.coordinator._async_update_data()

    async def test_empty_catalog_disables_select_but_keeps_refresh(self):
        FakeSession.text = catalog(())
        await self.refresh()
        self.assertFalse(component("select").CameraSelect(self.coordinator).available)
        refresh = component("button").DisplayButton(self.coordinator, "refresh", "Refresh", "mdi:refresh")
        self.assertTrue(refresh.available)

    async def test_failed_poll_marks_controls_unavailable_and_refresh_recovers(self):
        await self.refresh()
        entity = component("select").CameraSelect(self.coordinator)
        FakeSession.failure = e.StationError
        await self.coordinator.async_request_refresh()
        self.assertFalse(entity.available)
        FakeSession.failure = None
        refresh = component("button").DisplayButton(self.coordinator, "refresh", "Refresh", "mdi:refresh")
        await refresh.async_press()
        self.assertTrue(entity.available)

    async def test_nine_entities_have_unique_ids_owned_by_same_device(self):
        self.entry.runtime_data = self.coordinator
        entities = []
        for platform in ["select", "number", "button", "sensor"]:
            await component(platform).async_setup_entry(self.hass, self.entry, entities.extend)
        self.assertEqual(len(entities), 9)
        self.assertEqual(len({entity._attr_unique_id for entity in entities}), 9)
        for entity in entities:
            self.assertEqual(entity._attr_device_info["identifiers"], {("hikvision_display", self.entry.unique_id)})

    async def test_diagnostics_export_excludes_credentials_host_and_camera_names(self):
        await self.refresh()
        self.entry.runtime_data = self.coordinator
        serialized = json.dumps(await diagnostics.async_get_config_entry_diagnostics(self.hass, self.entry))
        for secret in ["FAKE_PASSWORD", "FAKE_KEY", "192.0.2.10", "Camera A", "FAKE_SECRET"]:
            self.assertNotIn(secret, serialized)

    async def test_options_update_interval_without_restart(self):
        self.entry.runtime_data = self.coordinator
        self.entry.options = {"scan_interval": 120, "brightness": 81}
        await init.async_options_updated(self.hass, self.entry)
        self.assertEqual(self.coordinator.update_interval, timedelta(seconds=120))
        self.assertEqual(self.coordinator.brightness, 81)

    async def test_connection_change_listener_schedules_reload_instead_of_polling_old_host(self):
        self.entry.runtime_data = self.coordinator
        self.entry.data = {**self.entry.data, "host": "192.0.2.20"}
        await init.async_options_updated(self.hass, self.entry)
        self.assertEqual(self.hass.reloads, [self.entry.entry_id])
        self.assertEqual(FakeSession.opened, 0)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.flow = cf.ConfigFlow()
        self.flow.hass = Hass()

    async def test_no_password_auth_before_explicit_fingerprint_verification(self):
        with patch.object(cf, "probe_host_key", AsyncMock(return_value=("PUBLIC_KEY", "SHA256:FINGERPRINT"))), \
                patch.object(cf, "validate_station", AsyncMock()) as authenticate:
            result = await self.flow.async_step_user({"host": "192.0.2.2", "port": 22, "name": "Hall"})
            self.assertEqual(result["step_id"], "trust")
            self.assertEqual(result["description_placeholders"]["fingerprint"], "SHA256:FINGERPRINT")
            self.assertEqual((await self.flow.async_step_trust({"verified": False}))["errors"]["base"], "verify_host_key")
            self.assertEqual((await self.flow.async_step_trust({"verified": True}))["step_id"], "credentials")
            authenticate.assert_not_awaited()
            result = await self.flow.async_step_credentials({"password": "FAKE_PASSWORD", "supported_device": True})
            self.assertEqual(result["type"], "create_entry")
            self.assertEqual(result["data"]["public_key"], "PUBLIC_KEY")
            authenticate.assert_awaited_once()

    async def test_duplicate_station_is_rejected_by_host_key_identity(self):
        self.flow.hass.existing_ids = {"SHA256:FINGERPRINT"}
        with patch.object(cf, "probe_host_key", AsyncMock(return_value=("KEY", "SHA256:FINGERPRINT"))):
            with self.assertRaisesRegex(RuntimeError, "already_configured"):
                await self.flow.async_step_user({"host": "192.0.2.2", "port": 22, "name": "Hall"})

    async def test_errors_are_fixed_messages_not_raw_diagnostic_content(self):
        data = {"password": "FAKE_PASSWORD"}
        for exception, code in [(e.AuthenticationError, "invalid_auth"),
                                (e.UnsupportedFirmware, "unsupported_firmware"),
                                (e.ConnectionFailure, "cannot_connect"),
                                (e.StationError, "discovery_failed")]:
            with patch.object(cf, "validate_station", AsyncMock(side_effect=exception("FAKE_SECRET"))):
                self.assertEqual(await self.flow._validate(data), {"base": code})

    async def test_admin_device_confirmation_is_required(self):
        self.assertEqual((await self.flow.async_step_credentials({"password": "x", "supported_device": False}))
                         ["errors"]["base"], "unsupported_device")

    async def test_empty_or_multiline_password_rejected(self):
        for password in ["", "x\ny", "x\ry", "x" * 257]:
            self.assertEqual(await self.flow._validate({"password": password}), {"base": "invalid_auth"})

    async def test_reauth_and_reconfigure_preserve_pinned_key(self):
        self.flow.test_entry = Entry()
        with patch.object(cf, "validate_station", AsyncMock()) as validate:
            result = await self.flow.async_step_reauth_confirm({"password": "NEW_PASSWORD"})
            self.assertEqual(result["updated"]["data_updates"]["public_key"], "FAKE_KEY")
            result = await self.flow.async_step_reconfigure({"host": "192.0.2.20", "port": 2222, "password": ""})
            data = result["updated"]["data_updates"]
            self.assertEqual(data["password"], "FAKE_PASSWORD")
            self.assertEqual(data["public_key"], "FAKE_KEY")
            self.assertEqual(data["port"], 2222)

    async def test_options_schema_bounds(self):
        flow = cf.OptionsFlow()
        flow.config_entry = Entry()
        schema = (await flow.async_step_init())["data_schema"]
        self.assertEqual(schema({"scan_interval": 60, "brightness": 1})["scan_interval"], 60)
        for value in [{"scan_interval": 0, "brightness": 50}, {"scan_interval": 300, "brightness": 101}]:
            with self.assertRaises(vol.Invalid):
                schema(value)

    async def test_reconfiguration_uses_existing_update_listener_without_deprecated_reload_helper(self):
        entry = Entry()
        entry.update_listeners.append(lambda: None)
        result = self.flow._update_entry(entry, {**entry.data, "host": "192.0.2.30"})
        self.assertTrue(result["listener_reload"])


class PackagingTests(unittest.TestCase):
    def test_source_has_no_personal_defaults_or_legacy_helpers(self):
        for path in COMPONENT.rglob("*.py"):
            text = path.read_text()
            ast.parse(text)
            self.assertIsNone(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text), path.name)
            for forbidden in ["input_select.set_options", "hassio.addon_stdin", "station_password"]:
                self.assertNotIn(forbidden, text, path.name)
        self.assertFalse((COMPONENT / "known_hosts").exists())

    def test_manifest_translations_and_seed_integrity(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["requirements"], ["asyncssh>=2.24.0,<3"])
        if "documentation" in manifest:
            self.assertTrue(manifest["documentation"].startswith("https://github.com/"))
            self.assertEqual(manifest["issue_tracker"], manifest["documentation"] + "/issues")
        self.assertEqual(json.loads((COMPONENT / "strings.json").read_text()),
                         json.loads((COMPONENT / "translations/en.json").read_text()))
        self.assertEqual(len(component("solver").load_seeds()), 1000000)


if __name__ == "__main__":
    unittest.main()
