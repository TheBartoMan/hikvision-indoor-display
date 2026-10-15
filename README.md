# Hikvision Indoor Display

A Home Assistant **custom integration**, not a Supervisor app. It connects directly
to your indoor station over SSH. Setup, entity ownership, polling and removal follow
Home Assistant's config-entry lifecycle. No YAML package or companion app is needed.

Version **1.0.0** controls camera selection, backlight and navigation on supported
Hikvision indoor stations. Camera options are discovered from the configured station;
no station addresses, credentials or camera configuration are supplied with the code.
This is an independent community integration, not an official Hikvision product.

## Supported Profile

- DS-KH6320-WTE1, V2.2.108 build 250718, English 1024x600 display layout.
- Running `hicore` binary must match the verified size and CRC profile. Other
  binaries fail closed before display control. The model/layout are also confirmed
  by the administrator during setup; CRC is a compatibility check, not attestation.
- Enabled SSH and the owner's administrator password/root Debug access are required.
- Home Assistant 2026.10 or later; HA installs AsyncSSH automatically. No x86-specific
  SDK or OpenSSH executable is used. The code is architecture-independent, but actual
  HA/CPU combinations still need deployment verification. Slower CPUs can hit the
  bounded challenge-solver timeout and are not automatically retried with guesses.

The SSH dependency accepts AsyncSSH 2.24.x and later 2.x releases so Home Assistant
can manage its shared version. Newer already-installed versions are not downgraded.
Older HA releases are not supported. Do not force upgrades of HA's dependencies to
install it. See `SECURITY.md` for dependency guidance. Setup forms use HA 2026.10's
Probatio API rather than an older Voluptuous-only implementation.

The firmware's public challenge-verification parameters and a generated seed table
are shared firmware data, not your device credentials. Unsupported future firmware
needs analysis and tests, not simply a new CRC added to the allowlist.

## Install

### HACS

Add [TheBartoMan/hikvision-indoor-display](https://github.com/TheBartoMan/hikvision-indoor-display)
in HACS under Custom repositories, choosing **Integration** as the category. Download **Hikvision Indoor
Display**, restart Home Assistant, and follow steps 3-7 below. A public repository
can be installed this way before acceptance into the default HACS catalog; default
catalog inclusion is a separate review, not automatic on publication.

### Manual

1. Copy `custom_components/hikvision_display` to your HA configuration directory:
   `/config/custom_components/hikvision_display` on HA OS. Existing files with this
   domain will be overwritten; back up HA and check for an unrelated integration first.
2. Restart Home Assistant. Installation needs internet access for the Python dependency.
3. Settings > Devices & services > Add integration > **Hikvision Indoor Display**.
4. Enter the station's IP/hostname and SSH port, and give the device a name.
5. Independently verify the displayed SSH fingerprint before accepting it. A trusted
   existing SSH known-hosts entry can be checked with `ssh-keygen -F STATION_HOST`
   and `ssh-keygen -lf KNOWN_HOSTS_FILE -E sha256`. A new unauthenticated network
   keyscan by itself is not independent verification.
6. Confirm the supported hardware/layout, enter the station administrator password,
   and let setup authenticate, validate the running firmware and discover cameras.
7. Open the integration's device to see its nine entities. No extra script/helper
   installation or dashboard YAML is required. Add entities to a dashboard normally.

For SSH transfer from a Mac/Linux machine, from this extracted directory:

```sh
bash install.sh root@YOUR_HA_HOST 22
```

The SSH destination/port are for your HA host, not the Hikvision station. This helper
only copies integration source; it does not restart HA, change credentials, stop other
apps or delete configuration. HA Container/Core users can copy the folder into their
configuration mount instead; Supervisor is not required.

This package is an integration, not an entry for the Home Assistant Apps store.
Repository publication and HACS listing status are tracked in `PUBLISHING.md`.

[Add this repository to HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheBartoMan&repository=hikvision-indoor-display&category=integration).

## Entities and Automations

Each configured station owns nine entities. With the default device name "Indoor
display", typical IDs are below; HA may suffix IDs for collisions or user renames.
Use the actual IDs shown on your device, especially with multiple stations.

| Typical entity | Behavior |
|---|---|
| `select.indoor_display_camera` | Live camera options. Selecting one refreshes discovery, wakes the display and requests that feed immediately. State is the last successful requested option, not measured live video. |
| `number.indoor_display_requested_brightness` | Brightness 1-100%. Changing it applies immediately and saves the requested value. It is not a brightness measurement. |
| `button.indoor_display_display_on` | Wakes the screen at requested brightness without choosing a feed. |
| `button.indoor_display_display_off` | Sets backlight to zero, not station power; does not explicitly stop preview. |
| `button.indoor_display_home` | Leaves the preview and returns Home when the window guard permits. |
| `button.indoor_display_refresh_cameras` | Discovers current camera configuration without waking or navigating the display. Remains usable after failed polling. |
| `button.indoor_display_check_connection` | Checks the verified session, running process identity and window metadata without changing the display. Opens and fully verifies a new session when needed. |
| `sensor.indoor_display_camera_count` | Discovered count with sanitized names/types/IDs/slots and last-success time. Becomes unavailable on polling failure. |
| `sensor.indoor_display_last_result` | Latest sanitized operation result, not authoritative physical screen state. |

Example automation action:

```yaml
action: select.select_option
target:
  entity_id: select.indoor_display_camera
data:
  option: Example camera
```

```yaml
action: button.press
target:
  entity_id: button.indoor_display_display_off
```

Names come from the configured station. Duplicate names receive labels such
as `Camera [ipc:3]`. Use an exact current label. Name literals in existing automations
must be changed manually after a rename; the integration cannot rewrite arbitrary
automations safely. Removed/renamed options fail, rather than select another feed.

## Automatic Discovery

Polls on setup and every five minutes by default, adjustable under the integration's
Configure options (60-3600 seconds). Every camera action also requires fresh discovery
before resolving the name. Added, removed or renamed cameras update options on the
same select entity without recreating its entity ID or making standalone helpers.

A complete catalog is required. Supported types are network cameras (2) and door
stations (3), limited to 16 network cameras/nine door stations by the current control
profile. Unknown types, duplicate type/device IDs, partial rows and inconsistent counts
are rejected. A valid empty list makes the selector unavailable. Failed polls mark
entities unavailable; no stale catalog is used for selection.

Selection follows catalog order within the active door/network page, not raw device
ID. Verify requested feeds after changing camera order or configuration.
Catalog edits between discovery and selection
can race the command. A preview-window change is not proof of decoded camera pixels.

Requests are serialized per station. A second user command during polling or another
operation is rejected as busy, not queued for later execution. Multiple stations have
independent coordinators, keys and locks. Do not run another controller or independent debug
captures against the same station concurrently.

The integration reuses a verified SSH session across operations. It closes after
60 seconds of inactivity and rotates after ten minutes (after any active command
finishes). Every new connection verifies the pinned host key, root access and full
firmware profile. Reuse first checks the `hicore` PID and process start time; a
restart requires a new fully verified connection and invalidates preview ownership.
Connections are also closed on command failure, cancellation or integration unload.
A stale session can be replaced before an action starts; an action that has started
is never automatically replayed after a failure. Diagnostics show connection status.

Fresh discovery is still required for each camera selection. One-second GUI settling
delays are followed by bounded page checks because captions do not prove that controls
have initialized. Session reuse avoids repeated authentication and firmware checks
for nearby actions; the first action after idle expiry needs fresh setup. Actual
latency depends on the station, network and Home Assistant host.

## Removal and Updates

Remove the configured integration from Settings > Devices & services. HA unloads
its entities, removes their config-entry ownership/registry entries and stops polling;
active transport operations are cancelled and their SSH connections closed. No
standalone scripts, helpers or package files are created. Historical recorder data
and user-created automations/dashboard references are not automatically erased.

Removing integration source from disk alone is not a clean uninstall: remove its
configured entry first, then delete the folder or use HACS removal.
Install updated source and restart HA for future code updates; there is no Supervisor
container or competing Installed/Latest app version state.

Use Reconfigure to change address/port/password without changing the pinned host key.
Authentication failure starts HA's reauthentication flow. A replacement device or
deliberately changed SSH key requires removal/re-addition and independent fingerprint
verification; keys are never silently accepted during routine operation.

## Security and Limitations

SSH is authenticated and host-key pinned. No inbound listener, cloud account, MQTT,
SDK, process-memory reads, permanent station files, firmware patches, door unlocking,
two-way audio or arbitrary command input. All shell commands are internal allowlisted
strings; camera names are never interpolated into shell commands.

Discovery uses the verified `getEzvizinfo` diagnostic. It briefly redirects stdout
to the SSH PTY and restores it with remote exit/signal traps, checking restoration.
Already-redirected stdout is refused. Diagnostic credentials briefly pass through
memory; only allowlisted camera fields are retained. Raw transcripts and exception
details are never logged by the integration or exported through diagnostics. This
is not a secure-memory-erasure guarantee. Avoid external terminal recordings and
verbose transport-level logging.

Passwords are stored in HA config-entry storage and may be included in backups.
Masking a field is not encryption. Protect HA administration, configuration storage
and backups. Keep station SSH on a trusted LAN, never forwarded to the internet.

The existing GUI-window guard refuses unknown/call/alarm/settings screens and only
leaves a preview if the integration owns its exact window handle. It is **not** an
authoritative call-state API; an incoming call between checks and commands can race
control. Validate supervised operation before unattended deployment. Screen sleep
timers remain active: Display on is a one-time wake, not a keep-awake loop.

## Test Status

The integration has automated transport and lifecycle tests with synthetic fixtures.
Automated tests do not establish physical camera rendering or Home Assistant UI
behavior. See `ACCEPTANCE.md` for the live-installation validation checklist. A version
number is not a certification of universal firmware or hardware compatibility.

76 automated tests pass: 18 use real encrypted AsyncSSH exchanges over in-process
socket pairs (no network listener), four cover adaptive navigation with transport doubles,
six cover catalog parsing, and 40 cover UI-flow,
coordinator, entity ownership, cleanup and packaging with explicit HA API doubles.
Eight additional tests cover release privacy checks, icon metadata, repository metadata
and reproducible source archives without filesystem owner metadata.
Those doubles do not establish real HA entity-registry removal or UI behavior.

Run tests in a separate Python 3.12+ environment, not inside a running HA process:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -v
```

Maintainers must complete repository metadata, run HA/HACS validation and record
live acceptance results before publication. See `PUBLISHING.md`. No Home Assistant
Core approval or default HACS listing is implied by this package.

Architecture follows HA's [config-entry lifecycle](https://developers.home-assistant.io/docs/config_entries_index/)
and [config-flow setup](https://developers.home-assistant.io/docs/core/integration/config_flow/).
Transport uses [AsyncSSH](https://asyncssh.readthedocs.io/en/latest/).
