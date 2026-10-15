#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: bash install.sh USER@HA_HOST [SSH_PORT]\n' >&2
  exit 2
fi
target=$1
port=${2:-22}
if [[ ! "$target" =~ ^[A-Za-z0-9][A-Za-z0-9_.@:-]*$ || ! "$port" =~ ^[0-9]+$ ]] ||
   (( 10#$port < 1 || 10#$port > 65535 )); then
  printf 'Invalid SSH destination or port.\n' >&2
  exit 2
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
printf 'Installing custom integration source. This does not modify legacy packages or app settings.\n'
COPYFILE_DISABLE=1 tar -C "$root/custom_components" -cf - hikvision_display |
  ssh -p "$port" "$target" 'mkdir -p /config/custom_components && tar -C /config/custom_components -xf -'
printf 'Source installed. Restart HA, then add Hikvision Indoor Display under Devices & services.\n'
