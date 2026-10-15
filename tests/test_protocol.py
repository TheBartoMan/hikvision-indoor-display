import asyncio
import base64
import struct
import socket
import re
import unittest
from unittest.mock import AsyncMock, Mock, patch

import asyncssh

from bootstrap import Entry, Hass, component

p = component("protocol")
d = component("catalog")
s = component("solver")
e = component("errors")
SEEDS = s.load_seeds()


def catalog(names=("Door", "Camera A", "Camera B"), ids=None):
    ids = list(range(len(names))) if ids is None else ids
    lines = ["token: FAKE_SECRET_TOKEN", "master key: FAKE_SECRET_KEY", f"devNum:{len(names)}"]
    for index, (name, device_id) in enumerate(zip(names, ids)):
        kind = 3 if index == 0 else 2
        lines.append(f"[{index}]devName:{name}, ip:192.0.2.1, devType:{kind}, devId:{device_id}, videoEncType:0-0")
    return "\n".join(lines)


class Server(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == "root" and password == "FAKE_ADMIN"


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.commands = []
        self.crc = p.FIRMWARE_CRC
        self.names = ("Door", "Camera A", "Camera B")
        self.destination = "/dev/console"
        self.preview = "Mydesktop"
        self.protected = False
        self.bad_challenge = False
        self.restore_ok = True
        self.runtime_start = "12345"
        self.bad_runtime = False
        self.change_runtime_on_crc = False
        self.key = asyncssh.generate_private_key("ecdsa-sha2-nistp256")
        self.port = 2200
        self.server_tasks = []
        self.real_connect = asyncssh.connect
        self.real_probe = asyncssh.get_server_host_key
        self.connect_patch = patch.object(asyncssh, "connect", self.connect_pair)
        self.probe_patch = patch.object(asyncssh, "get_server_host_key", self.probe_pair)
        self.connect_patch.start()
        self.probe_patch.start()

    async def asyncTearDown(self):
        self.connect_patch.stop()
        self.probe_patch.stop()
        for task in self.server_tasks:
            if task.done() and not task.cancelled() and task.exception() is None:
                task.result().close()
            else:
                task.cancel()
        await asyncio.gather(*self.server_tasks, return_exceptions=True)

    def socket_pair(self):
        client, server = socket.socketpair()
        self.server_tasks.append(asyncio.ensure_future(asyncssh.run_server(
            server, server_factory=Server, server_host_keys=[self.key], process_factory=self.shell)))
        return client

    async def connect_pair(self, host, **kwargs):
        return await self.real_connect(host, sock=self.socket_pair(), **kwargs)

    async def probe_pair(self, host, port, **kwargs):
        return await self.real_probe(host, port, sock=self.socket_pair(), **kwargs)

    def session(self, password="FAKE_ADMIN", key=None):
        public_key = (key or self.key).export_public_key().decode().strip()
        return p.StationSession("127.0.0.1", self.port, password, public_key, SEEDS, asyncio.to_thread)

    async def shell(self, process):
        unlocked = not self.protected
        process.stdout.write("[root@dvrdvs ~] # " if unlocked else "# ")
        try:
            async for line in process.stdin:
                command = line.strip()
                self.commands.append(command)
                if not unlocked and command == "Debug":
                    if self.bad_challenge:
                        process.stdout.write("qrcode:\nunknown\nPassword: ")
                    else:
                        seed1, seed2, seed3 = 123456, 123457, 123458
                        rng = s.Rng(seed3)
                        first3 = rng.next()
                        padding = bytearray()
                        while len(padding) < 245:
                            value = rng.next() & 255
                            if value:
                                padding.append(value)
                        response = base64.b64encode(struct.pack("<I", s.Rng(seed2).next()) + struct.pack("<I", first3)[:2])
                        self.expected_response = response.decode()
                        block = b"\0\2" + padding + b"\0" + response
                        long_value = b"\x0c\0\0\0" + pow(int.from_bytes(block, "big"), 65537, s.MODULUS).to_bytes(256, "big")
                        short_value = b"\x0c\0\0\0" + b"\0" * 6 + struct.pack("<I", s.Rng(seed1).next())
                        process.stdout.write("qrcode:\n" + base64.b64encode(long_value).decode() + "\n" +
                                             base64.b64encode(short_value).decode() + "\nPassword: ")
                    continue
                if not unlocked:
                    unlocked = command == getattr(self, "expected_response", None)
                    process.stdout.write("[root@dvrdvs ~] # " if unlocked else "# ")
                    continue
                if command == "id":
                    process.stdout.write("uid=0(root) gid=0(root)\n")
                elif command == "/bin/cat /proc/$(/bin/pidof hicore)/stat":
                    process.stdout.write("invalid stat\n" if self.bad_runtime else
                                         "238 (hicore) S " + "0 " * 18 + self.runtime_start + " 0\n")
                elif command.startswith("P=$("):
                    process.stdout.write(p.FIRMWARE_SIZE + f"\n{self.crc} /proc/238/exe\n")
                    if self.change_runtime_on_crc:
                        self.runtime_start = "99999"
                elif "getEzvizinfo" in command:
                    restored = "/dev/console" if self.restore_ok else "/dev/pts/1"
                    process.stdout.write("redirectionOutput success.\n" + catalog(self.names) +
                                         "\n__CAMERA_OUTPUT__" + restored + "\n")
                elif command.startswith("/bin/busybox readlink"):
                    process.stdout.write(self.destination + "\n")
                elif command == "guiStatus 40":
                    process.stdout.write(f"Current active window:{self.preview}(0x1234), focus ctrl:...\n")
                elif command == "guiDebug hiklinux 90 0":
                    self.preview = "Mydesktop"
                elif command == "guiDebug hiklinux 110 6100420":
                    self.preview = "Door Station"
                elif command == "guiDebug hiklinux 110 9700170":
                    self.preview = "Network Camera"
                elif command.startswith("kb mo"):
                    self.preview = ""
                process.stdout.write("[root@dvrdvs ~] # ")
        except (asyncssh.Error, OSError):
            pass
        finally:
            process.exit(0)

    async def test_real_ssh_discovery_returns_only_allowlisted_fields(self):
        async with self.session() as session:
            cameras = await session.discover()
            self.assertEqual([camera.name for camera in cameras], ["Door", "Camera A", "Camera B"])
            self.assertNotIn("FAKE_SECRET", repr(cameras))
            self.assertEqual(session.buffer, "")
        self.assertIsNone(session.connection)
        self.assertEqual(session.password, "")

    async def test_host_key_probe_does_not_authenticate(self):
        key, fingerprint = await p.probe_host_key("127.0.0.1", self.port)
        self.assertEqual(fingerprint, self.key.get_fingerprint("sha256"))
        self.assertEqual(key, self.key.export_public_key().decode().strip())
        self.assertEqual(self.commands, [])

    async def test_reuse_checks_process_start_time_without_repeating_crc(self):
        async with self.session() as session:
            self.assertTrue(session.is_connected())
            self.assertEqual(session.runtime_identity, ("238", "12345"))
            self.assertEqual(session.password, "")
            await session.verify_runtime()
            await session.verify_runtime()
            self.assertEqual(sum(command.startswith("P=$(") for command in self.commands), 1)
            self.runtime_start = "99999"
            with self.assertRaises(e.ConnectionFailure):
                await session.verify_runtime()
        self.assertFalse(session.is_connected())

    async def test_unreadable_process_identity_refuses_setup(self):
        self.bad_runtime = True
        with self.assertRaises(e.ConnectionFailure):
            async with self.session():
                pass
        self.assertFalse(any(command.startswith(("guiDebug", "kb ")) for command in self.commands))

    async def test_process_change_during_crc_refuses_setup(self):
        self.change_runtime_on_crc = True
        with self.assertRaises(e.ConnectionFailure):
            async with self.session():
                pass
        self.assertFalse(any(command.startswith(("guiDebug", "kb ")) for command in self.commands))

    async def test_coordinator_reuses_real_encrypted_session_and_closes_on_shutdown(self):
        c = component("coordinator")
        self.protected = True
        entry = Entry()
        entry.data = {"host": "127.0.0.1", "port": self.port, "password": "FAKE_ADMIN",
                      "public_key": self.key.export_public_key().decode().strip()}
        coordinator = c.DisplayCoordinator(Hass(), entry)
        try:
            await coordinator.async_config_entry_first_refresh()
            first = coordinator._session
            await coordinator.perform("check")
            await coordinator.perform("display_on")
            await coordinator.perform("display_off")
            self.assertIs(first, coordinator._session)
            self.assertEqual(self.commands.count("Debug"), 1)
            self.assertEqual(sum(command.startswith("P=$(") for command in self.commands), 1)
            self.assertIn("guiDebug hiklinux 150 60", self.commands)
            self.assertIn("guiDebug hiklinux 150 0", self.commands)
        finally:
            await coordinator.async_shutdown()
        self.assertFalse(first.is_connected())
        self.assertIsNone(coordinator._idle_task)

    async def test_wrong_password_fails_before_shell(self):
        with self.assertRaises(e.AuthenticationError):
            async with self.session(password="WRONG"):
                pass
        self.assertEqual(self.commands, [])

    async def test_changed_host_key_fails_closed(self):
        other = asyncssh.generate_private_key("ecdsa-sha2-nistp256")
        with self.assertRaises(e.ConnectionFailure):
            async with self.session(key=other):
                pass
        self.assertEqual(self.commands, [])

    async def test_unsupported_firmware_sends_no_display_controls(self):
        self.crc = "deadbeef"
        with self.assertRaises(e.UnsupportedFirmware):
            async with self.session():
                pass
        self.assertFalse(any(command.startswith(("guiDebug", "kb ")) for command in self.commands))

    async def test_protected_shell_verifies_fresh_debug_challenge(self):
        self.protected = True
        async with self.session() as session:
            self.assertEqual(len(await session.discover()), 3)
        self.assertIn("Debug", self.commands)
        self.assertIn(self.expected_response, self.commands)

    async def test_unknown_challenge_never_gets_an_unlock_guess(self):
        self.protected = self.bad_challenge = True
        with self.assertRaises(e.StationError):
            async with self.session():
                pass
        self.assertEqual(self.commands, ["Debug"])

    async def test_already_redirected_stdout_refuses_discovery(self):
        self.destination = "/dev/pts/1"
        async with self.session() as session:
            with self.assertRaises(e.BusyStation):
                await session.discover()
        self.assertFalse(any("getEzvizinfo" in command for command in self.commands))

    async def test_camera_navigation_and_owned_preview(self):
        async with self.session() as session:
            camera = (await session.discover())[2]
            original_sleep = asyncio.sleep
            async def immediate_sleep(seconds):
                await original_sleep(0)
            with patch.object(p.asyncio, "sleep", immediate_sleep):
                await session.show_camera(camera, 60)
            self.assertEqual(session.opened_preview, ("", "0x1234"))
        self.assertIn("kb mo2", self.commands)
        self.assertFalse(any("wt" in command for command in self.commands))

    async def test_incoming_call_window_blocks_backlight(self):
        self.preview = "Incoming Call"
        async with self.session() as session:
            with self.assertRaises(e.BusyStation):
                await session.display(0)
        self.assertNotIn("guiDebug hiklinux 150 0", self.commands)

    async def test_navigation_retains_firmware_settle_delays(self):
        settled_commands = []

        async def settle(seconds):
            settled_commands.append(self.commands[-1])

        async with self.session() as session:
            camera = (await session.discover())[1]
            with patch.object(p.asyncio, "sleep", new_callable=AsyncMock, side_effect=settle) as sleep:
                await session.show_camera(camera, 60)
                self.assertEqual(sleep.await_count, 5)
                self.assertTrue(all(args.args == (1,) for args in sleep.await_args_list))
        self.assertIn("guiDebug hiklinux 90 0", self.commands)
        self.assertEqual(settled_commands, [
            "guiDebug hiklinux 150 60", "guiDebug hiklinux 90 0",
            "guiDebug hiklinux 110 6100420", "guiDebug hiklinux 110 9700170", "kb mo1",
        ])

    async def test_navigation_waits_for_page_readiness(self):
        session = self.session()
        session.page = AsyncMock(side_effect=["Mydesktop", "Door Station"])
        with patch.object(p.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await session.wait_for_page("Door Station")
            sleep.assert_awaited_once_with(0.1)

    async def test_navigation_wait_is_bounded(self):
        session = self.session()
        session.page = AsyncMock(return_value="Mydesktop")
        loop = Mock()
        loop.time.side_effect = [0, 4]
        with patch.object(p.asyncio, "get_running_loop", return_value=loop):
            with self.assertRaises(e.StationError):
                await session.wait_for_page("Door Station")

    async def test_navigation_does_not_retry_busy_windows(self):
        session = self.session()
        session.window = AsyncMock(return_value=("Incoming Call", "0x4321"))
        with patch.object(p.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(e.BusyStation):
                await session.wait_for_page("Door Station")
            sleep.assert_not_awaited()

    async def test_preview_waits_for_transition_but_rejects_errors(self):
        session = self.session()
        session.window = AsyncMock(side_effect=[("Network Camera", "0x1"), ("", "0x2")])
        with patch.object(p.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await session.confirm_preview()
            sleep.assert_awaited_once_with(0.1)
        self.assertEqual(session.opened_preview, ("", "0x2"))
        session.opened_preview = None
        session.window = AsyncMock(return_value=("Talk Error", "0x3"))
        with self.assertRaises(e.StationError):
            await session.confirm_preview()
        self.assertIsNone(session.opened_preview)

    async def test_bad_console_restoration_fails_and_discards_transcript(self):
        self.restore_ok = False
        async with self.session() as session:
            with self.assertRaises(e.StationError) as context:
                await session.discover()
            self.assertEqual(session.buffer, "")
            self.assertNotIn("FAKE_SECRET", str(context.exception))

    async def test_bounded_wait_timeout_is_fixed_error_and_context_closes_connection(self):
        session = self.session()
        with self.assertRaises(e.ConnectionFailure) as context:
            async with session:
                await session.wait([re.compile("NEVER_MATCH")], 0.01)
        self.assertIsNone(session.connection)
        self.assertEqual(session.buffer, "")
        self.assertNotIn("FAKE_ADMIN", str(context.exception))

    async def test_zero_camera_discovery_over_real_ssh(self):
        self.names = ()
        async with self.session() as session:
            self.assertEqual(await session.discover(), ())


class CatalogTests(unittest.TestCase):
    def test_add_remove_rename_and_duplicate_names(self):
        first = d.parse_catalog(catalog())
        second = d.parse_catalog(catalog(("Door", "Renamed", "Added", "Extra")))
        self.assertEqual(len(second), 4)
        self.assertEqual(second[1].name, "Renamed")
        self.assertEqual(len(d.parse_catalog(catalog(("Door",)))), 1)
        self.assertNotEqual(first, second)
        duplicates = d.parse_catalog(catalog(("Door", "Same", "Same")))
        self.assertEqual(duplicates[2].label, "Same [ipc:2]")
        with self.assertRaises(e.StationError):
            d.resolve_camera("Same", duplicates)

    def test_gapped_ids_use_page_order(self):
        cameras = d.parse_catalog(catalog(ids=[0, 4, 12]))
        self.assertEqual(cameras[2].sequence, 2)

    def test_zero_cameras_and_unicode_commas(self):
        self.assertEqual(d.parse_catalog(catalog(())), ())
        cameras = d.parse_catalog(catalog(("Door", "Entr\u00e9e, East")))
        self.assertEqual(cameras[1].name, "Entr\u00e9e, East")

    def test_partial_unknown_duplicate_and_inconsistent_rows_fail(self):
        values = ["", "devNum:1", "devNum:51", catalog() + "\ndevNum:3",
                  catalog().replace("[1]", "[9]"), catalog().replace("devType:2", "devType:9"),
                  catalog(ids=[0, 1, 1]), catalog().replace("devId:1", "devId:bad"),
                  catalog(tuple(str(i) for i in range(18)))]
        for text in values:
            with self.subTest(text=text[:15]), self.assertRaises(e.StationError):
                d.parse_catalog(text)

    def test_removed_or_renamed_label_is_not_retargeted(self):
        cameras = d.parse_catalog(catalog(("Door", "Renamed")))
        with self.assertRaises(e.StationError):
            d.resolve_camera("Camera A", cameras)

    def test_host_input_validation(self):
        for host in ["192.0.2.1", "station.example", "::1"]:
            self.assertEqual(p.validate_host(host), host)
        for host in ["x; reboot", "x\n", "", "../station", None]:
            with self.assertRaises(ValueError):
                p.validate_host(host)


if __name__ == "__main__":
    unittest.main()
