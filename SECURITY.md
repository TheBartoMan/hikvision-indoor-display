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
