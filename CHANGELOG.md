# Changelog

## 1.0.0

- Home Assistant config-flow setup with independently confirmed SSH host-key pinning.
- Camera selector populated from the station's current camera configuration.
- Automatic refresh for added, removed and renamed cameras.
- Requested brightness, display on/off, Home, refresh and connection-check controls.
- Per-station command serialization and conservative GUI-window checks.
- Verified SSH session reuse with idle/lifetime limits and process-identity checks.
- No automatic replay of display commands after connection failures.
- Config-entry-owned entities and transport cleanup on unload.
- Sanitized diagnostics and architecture-independent station transport.

Compatibility is limited to the model, firmware, language and layout in the README.
