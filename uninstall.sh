#!/usr/bin/env bash
set -euo pipefail

readonly BIN_DIR="${HOME}/.local/bin"
readonly USER_UNIT_DIR="${HOME}/.config/systemd/user"
readonly SUNSHINE_CONFIG="${HOME}/.config/sunshine/sunshine.conf"

systemctl --user disable --now sunshine-display-indicator.service >/dev/null 2>&1 || true
systemctl --user stop sunshine-display-inhibit.service >/dev/null 2>&1 || true
rm -f "$USER_UNIT_DIR/sunshine-display-indicator.service"
rm -f "$BIN_DIR/sunshine-displayctl" "$BIN_DIR/sunshine-display-indicator"
# Shims from installations that predate the single entry point.
rm -f "$BIN_DIR/sunshine-display-status" \
  "$BIN_DIR/sunshine-display-recover" \
  "$BIN_DIR/sunshine-display-physical-only" \
  "$BIN_DIR/sunshine-display-virtual-only" \
  "$BIN_DIR/sunshine-display-both" \
  "$BIN_DIR/sunshine-display-boot-status" \
  "$BIN_DIR/sunshine-display-boot-virtual" \
  "$BIN_DIR/sunshine-display-boot-default" \
  "$BIN_DIR/sunshine-display-boot-cancel" \
  "$BIN_DIR/sunshine-display-sunshine-on" \
  "$BIN_DIR/sunshine-display-sunshine-off"

if [[ -f "$SUNSHINE_CONFIG" ]]; then
  perl -0pi -e \
    's/^global_prep_cmd\s*=.*sunshine-displayctl stream-start.*\n?//m' \
    "$SUNSHINE_CONFIG"
fi
systemctl --user daemon-reload

printf 'Removed user-level display controls. The boot entry and the kernel EDID\n'
printf 'override were not removed. Use root/remove-boot-entry or root/remove-edid\n'
printf 'separately if they must go as well.\n'
