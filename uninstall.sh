#!/usr/bin/env bash
set -euo pipefail

readonly BIN_DIR="${HOME}/.local/bin"
readonly USER_UNIT_DIR="${HOME}/.config/systemd/user"
readonly SUNSHINE_CONFIG="${HOME}/.config/sunshine/sunshine.conf"

systemctl --user disable --now sunshine-display-indicator.service >/dev/null 2>&1 || true
systemctl --user stop sunshine-display-inhibit.service >/dev/null 2>&1 || true
rm -f "$USER_UNIT_DIR/sunshine-display-indicator.service"
rm -f "$BIN_DIR/sunshine-displayctl" \
  "$BIN_DIR/sunshine-display-indicator" \
  "$BIN_DIR/sunshine-display-status" \
  "$BIN_DIR/sunshine-display-recover" \
  "$BIN_DIR/sunshine-display-physical-only" \
  "$BIN_DIR/sunshine-display-virtual-only" \
  "$BIN_DIR/sunshine-display-both"

if [[ -f "$SUNSHINE_CONFIG" ]]; then
  perl -0pi -e \
    's/^global_prep_cmd\s*=.*sunshine-displayctl stream-start.*\n?//m' \
    "$SUNSHINE_CONFIG"
fi
systemctl --user daemon-reload

printf 'Removed user-level display controls. The kernel EDID override was not removed.\n'
printf 'Use root/remove-edid separately if the physical HDMI port must be restored.\n'
