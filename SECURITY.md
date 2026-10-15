# Security

Use only with devices you administer on a trusted network. Do not expose station
SSH to the internet. Verify its host-key fingerprint independently before setup.

Configuration stores the administrator password in Home Assistant storage and may
include it in backups. Protect both. Raw station diagnostics can contain cloud
credentials; never post them in issues or enable verbose SSH logging for a report.

For a suspected vulnerability, use GitHub's private vulnerability reporting if it
is enabled on the repository. If it is unavailable, open an issue requesting a
private contact channel without publishing exploit details, credentials or logs.

Only the current release and the documented station firmware profile are supported.

## Shared SSH Dependency

The manifest accepts AsyncSSH >=2.24.0,<3 to coexist with Home Assistant's dependency
management rather than forcing a conflicting exact pin. Both 2.24.0 and 2.24.1 are
included in the transport test matrix. Prefer the latest compatible patch release:
2.24.1 includes packet parsing, authentication, certificate and file-transfer
hardening. This integration uses a pinned-key SSH client, not an SSH/SFTP server,
SFTP, SCP, certificate authentication or user SSH configuration files. That narrower
usage is not a claim that older library versions have no security risk. Keep Home
Assistant updated and follow its dependency constraints; do not force a downgrade
or an incompatible upgrade. See the [AsyncSSH change log](https://asyncssh.readthedocs.io/en/latest/changes.html).
