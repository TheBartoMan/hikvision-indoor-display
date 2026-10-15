# Release Acceptance Checklist

Record results on real Home Assistant installations and the supported station
profile before publication. This checklist is not a claim that the checks passed.

## Confirmed Functional Checks

The installation tester confirmed camera selection, display on/off and Home on
the documented firmware profile. This confirms those controls only; it does not
establish the other platform, lifecycle or failure-path checks below.

## Remaining Validation

- Fresh manual installation and setup on HA OS and HA Container/Core.
- Minimum supported HA version and current HA version; dependency installation.
- Dependency resolution alongside HA's SFTP storage and other SSH integrations;
  their AsyncSSH pins may differ. Do not force conflicting package versions.
- Independently verified fingerprint, wrong password, changed key and wrong host.
- Unsupported firmware refusal before any display-control command.
- Zero, single and multiple cameras; duplicate names and Unicode/comma-containing names.
- Add, rename, delete and reorder cameras; verify each requested physical feed.
- Sleeping Home -> wake -> camera; brightness, backlight off/on and Home.
- Repeat navigation from sleeping Home and an existing preview; confirm slow
  transitions still complete and record end-to-end latency.
- Incoming call during each navigation stage; supervise physical safety and document
  the remaining non-atomic window-guard limitation.
- SSH timeout/disconnect during diagnostics; confirm stdout returns to `/dev/console`.
- Repeated controls within 60 seconds reuse the session; after idle expiry a fresh
  verified session is opened. Confirm the ten-minute lifetime rotates a busy session.
- Restart `hicore` or the station between operations; confirm full verification and
  invalidation of old preview ownership. Disconnect during a control; verify that
  the failed control is not replayed on reconnect.
- Compare cold and warm camera/display timings without changing GUI settling delays.
- HA restart, integration reload/disable, reauthentication and address change.
- Remove the integration during polling and during camera navigation; confirm no
  polling/SSH connection remains and owned entities are removed, without affecting
  a second independently configured station or unrelated entities.
- Inspect integration logs, diagnostics export and recorder attributes for secrets.
- Verify no competing controller or obsolete YAML package remains active.
- Test at least an amd64 and an aarch64 HA host; assess bounded solver CPU time.

Offline tests cannot establish these physical/HA deployment outcomes. Publish the
results and verified profiles before claiming broader compatibility.
