"""Async SSH transport, verified firmware and allowlisted display actions."""
import asyncio
import ipaddress
import re

import asyncssh

from .catalog import parse_catalog
from .errors import AuthenticationError, BusyStation, ConnectionFailure, StationError, UnsupportedFirmware
from .solver import parse_challenge, solve_challenge

ROOT_PROMPT = re.compile(r"(?m)^\[root@[^\r\n]{1,80}\]\s*#\s*$")
PSH_PROMPT = re.compile(r"(?m)^#\s*$")
PASSWORD_PROMPT = re.compile(r"(?i)password:\s*$")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SAFE_PAGES = {"Mydesktop", "Door Station", "Network Camera"}
FIRMWARE_CRC = "19a07ded"
FIRMWARE_SIZE = "12783368"


def validate_host(host):
    if not isinstance(host, str):
        raise ValueError("Invalid host")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
            return host.lower()
        raise ValueError("Invalid host") from None


async def probe_host_key(host, port):
    try:
        async with asyncio.timeout(12):
            key = await asyncssh.get_server_host_key(host, port, config=[])
        if key is None:
            raise ConnectionFailure("Station did not provide a host key")
        return key.export_public_key().decode().strip(), key.get_fingerprint("sha256")
    except (OSError, asyncssh.Error, TimeoutError):
        raise ConnectionFailure("Unable to read station host key") from None


class StationSession:
    def __init__(self, host, port, password, public_key, seeds, executor, owned_preview=None):
        self.host, self.port, self.password = validate_host(host), port, password
        self.public_key, self.seeds, self.executor = public_key, seeds, executor
        self.owned_preview = owned_preview
        self.opened_preview = None
        self.connection = self.process = None
        self.buffer = ""
        self.runtime_identity = None

    async def __aenter__(self):
        try:
            await self.connect()
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        self.buffer = ""
        self.password = ""
        self.runtime_identity = None
        if self.connection is not None:
            self.connection.close()
            try:
                async with asyncio.timeout(5):
                    await self.connection.wait_closed()
            except (TimeoutError, OSError, asyncssh.Error):
                pass
            self.connection = None
        self.process = None

    def is_connected(self):
        return (self.connection is not None and not self.connection.is_closed()
                and self.process is not None and self.process.exit_status is None
                and not self.process.stdout.at_eof())

    async def read_runtime_identity(self):
        output = await self.command("/bin/cat /proc/$(/bin/pidof hicore)/stat")
        match = re.search(r"(?m)^([1-9][0-9]*) \(hicore\) (.+)$", output)
        if match:
            fields = match.group(2).split()
            if (len(fields) >= 20 and fields[0] in {"R", "S", "D", "I"}
                    and all(re.fullmatch(r"-?[0-9]+", value) for value in fields[1:20])
                    and fields[19].isdigit()):
                return match.group(1), fields[19]
        raise ConnectionFailure("Running station process could not be identified")

    async def verify_runtime(self):
        try:
            if not self.is_connected() or await self.read_runtime_identity() != self.runtime_identity:
                raise ConnectionFailure("Station session or running process changed")
        except (OSError, asyncssh.Error):
            raise ConnectionFailure("Station session is no longer usable") from None

    async def connect(self):
        pattern = self.host if self.port == 22 else f"[{self.host}]:{self.port}"
        known_hosts = asyncssh.import_known_hosts(f"{pattern} {self.public_key}\n")
        try:
            async with asyncio.timeout(15):
                self.connection = await asyncssh.connect(
                    self.host, port=self.port, username="root", password=self.password,
                    known_hosts=known_hosts, config=[], client_keys=[], agent_path=None,
                    preferred_auth="password", keepalive_interval=15, keepalive_count_max=2)
                self.process = await self.connection.create_process(
                    term_type="vt100", term_size=(200, 50), request_pty=True,
                    stderr=asyncssh.STDOUT, encoding="utf-8", errors="replace")
        except asyncssh.PermissionDenied:
            raise AuthenticationError("Station rejected the admin password") from None
        except (OSError, asyncssh.Error, TimeoutError):
            raise ConnectionFailure("SSH connection or pinned host-key verification failed") from None
        text, kind = await self.wait([ROOT_PROMPT, PSH_PROMPT], 15)
        if kind == 1:
            self.send("Debug")
            challenge, _ = await self.wait([PASSWORD_PROMPT], 15)
            long_value, short_value = parse_challenge(challenge.encode())
            response = await self.executor(solve_challenge, long_value, short_value, self.seeds)
            self.send(response)
            _, kind = await self.wait([ROOT_PROMPT, PSH_PROMPT, PASSWORD_PROMPT], 10)
            if kind != 0:
                raise AuthenticationError("Debug unlock was not confirmed")
        await self.command("unset TMOUT")
        if not re.search(r"\buid=0\(root\)", await self.command("id")):
            raise AuthenticationError("Root access was not confirmed")
        await self.command("export PATH=/usr/bin/dvrCmd:$PATH")
        runtime = await self.read_runtime_identity()
        identity = await self.command(
            "P=$(/bin/pidof hicore); /usr/bin/wc -c < /proc/$P/exe; /bin/busybox crc32 /proc/$P/exe")
        if (not re.search(rf"(?m)^\s*{FIRMWARE_SIZE}\s*$", identity)
                or not re.search(rf"(?m)^{FIRMWARE_CRC}\s+/proc/\d+/exe\s*$", identity)):
            raise UnsupportedFirmware("Running firmware does not match the verified profile")
        if await self.read_runtime_identity() != runtime:
            raise ConnectionFailure("Station process changed during firmware verification")
        self.runtime_identity = runtime
        self.password = ""
        text = ""

    def send(self, value):
        if "\n" in value or "\r" in value:
            raise StationError("Multiline command rejected")
        self.process.stdin.write(value + "\r")

    async def wait(self, patterns, seconds):
        try:
            async with asyncio.timeout(seconds):
                while True:
                    for index, pattern in enumerate(patterns):
                        match = pattern.search(self.buffer)
                        if match:
                            output, self.buffer = self.buffer[:match.end()], self.buffer[match.end():]
                            return output, index
                    if len(self.buffer) > 65536:
                        raise StationError("Station response exceeded size limit")
                    value = await self.process.stdout.read(4096)
                    if not value:
                        raise ConnectionFailure("Station closed the SSH session")
                    self.buffer += ANSI.sub("", value).replace("\r", "")
        except (TimeoutError, OSError, asyncssh.Error):
            raise ConnectionFailure("Station command timed out or disconnected") from None

    async def command(self, command):
        self.send(command)
        output, _ = await self.wait([ROOT_PROMPT], 15)
        return output

    async def discover(self):
        destination = await self.command("/bin/busybox readlink /proc/$(/bin/pidof hicore)/fd/1")
        if not re.search(r"(?m)^/dev/console\s*$", destination):
            raise BusyStation("Diagnostic output is already redirected")
        text = ""
        try:
            text = await self.command(
                "(trap 'outputClose >/dev/null' 0; trap 'exit' 1 2 15; "
                "outputOpen; getEzvizinfo; /bin/sleep 1); "
                "printf '__CAMERA_OUTPUT__'; /bin/busybox readlink /proc/$(/bin/pidof hicore)/fd/1")
            if ("redirectionOutput success." not in text or
                    not re.search(r"(?m)^__CAMERA_OUTPUT__/dev/console\s*$", text)):
                raise StationError("Diagnostic output capture or restoration failed")
            return parse_catalog(text)
        finally:
            text = self.buffer = ""

    async def window(self):
        output = await self.command("guiStatus 40")
        match = re.search(r"Current active window:(.*?)\((0x[0-9A-Fa-f]+)\)", output)
        return (match.group(1).strip(), match.group(2).lower()) if match else None

    async def page(self):
        current = await self.window()
        if current and (current[0] in SAFE_PAGES or current == self.owned_preview):
            return current[0]
        raise BusyStation("Display is busy or in an unrecognized window")

    async def display(self, level):
        if type(level) is not int or not 0 <= level <= 100:
            raise StationError("Invalid brightness")
        await self.page()
        await self.command(f"guiDebug hiklinux 150 {level}")

    async def home(self):
        await self.page()
        await self.command("guiDebug hiklinux 90 0")
        await asyncio.sleep(1)
        await self.wait_for_page("Mydesktop")

    async def wait_for_page(self, expected):
        deadline = asyncio.get_running_loop().time() + 3
        while True:
            if await self.page() == expected:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise StationError("Display navigation was not confirmed")
            await asyncio.sleep(0.1)

    async def confirm_preview(self):
        deadline = asyncio.get_running_loop().time() + 3
        while True:
            current = await self.window()
            if not current or re.search(r"call|alarm|error|talk|setting", current[0], re.I):
                raise StationError("Preview window was not confirmed")
            if current[0] not in SAFE_PAGES:
                self.opened_preview = current
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise StationError("Preview window was not confirmed")
            await asyncio.sleep(0.1)

    async def show_camera(self, camera, brightness):
        if (camera.kind not in {"ipc", "outdoor"} or type(camera.sequence) is not int
                or not 1 <= camera.sequence <= (16 if camera.kind == "ipc" else 9)):
            raise StationError("Unsupported camera route")
        await self.display(brightness)
        # Page captions can change before the firmware has initialized its controls.
        await asyncio.sleep(1)
        await self.home()
        await self.command("guiDebug hiklinux 110 6100420")
        await asyncio.sleep(1)
        await self.wait_for_page("Door Station")
        if camera.kind == "ipc":
            await self.command("guiDebug hiklinux 110 9700170")
            await asyncio.sleep(1)
            await self.wait_for_page("Network Camera")
        await self.command(f"kb mo{camera.sequence}")
        await asyncio.sleep(1)
        await self.confirm_preview()
