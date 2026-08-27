#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BIN_DIR="${HOME}/.local/bin"
readonly USER_UNIT_DIR="${HOME}/.config/systemd/user"
readonly SETTINGS_DIR="${HOME}/.config/sunshine-display-manager"
readonly SUNSHINE_CONFIG="${HOME}/.config/sunshine/sunshine.conf"
readonly SUNSHINE_APPS="${HOME}/.config/sunshine/apps.json"
readonly SUNSHINE_HOOK="[{\"do\":\"${BIN_DIR}/sunshine-displayctl stream-start\",\"undo\":\"${BIN_DIR}/sunshine-displayctl stream-stop\"}]"

set_sunshine_option() {
  local key=$1 value=$2
  KEY="$key" VALUE="$value" perl -0777pi -e '
    $key = quotemeta($ENV{"KEY"});
    if (!s/^\s*$key\s*=.*$/$ENV{"KEY"} . " = " . $ENV{"VALUE"}/me) {
      $_ .= "\n" if length($_) && $_ !~ /\n\z/;
      $_ .= "$ENV{KEY} = $ENV{VALUE}\n";
    }
  ' "$SUNSHINE_CONFIG"
}

install -d --mode=0755 "$BIN_DIR" "$USER_UNIT_DIR" "$SETTINGS_DIR" \
  "$(dirname "$SUNSHINE_CONFIG")"
install --mode=0755 "$REPO_DIR/bin/sunshine-displayctl" \
  "$BIN_DIR/sunshine-displayctl"
install --mode=0755 "$REPO_DIR/indicator/sunshine-display-indicator.py" \
  "$BIN_DIR/sunshine-display-indicator"
install --mode=0755 "$REPO_DIR/ssh/display-status" \
  "$BIN_DIR/sunshine-display-status"
install --mode=0755 "$REPO_DIR/ssh/recover-physical" \
  "$BIN_DIR/sunshine-display-recover"
install --mode=0755 "$REPO_DIR/ssh/physical-only" \
  "$BIN_DIR/sunshine-display-physical-only"
install --mode=0755 "$REPO_DIR/ssh/virtual-only" \
  "$BIN_DIR/sunshine-display-virtual-only"
install --mode=0755 "$REPO_DIR/ssh/both-displays" \
  "$BIN_DIR/sunshine-display-both"
install --mode=0644 "$REPO_DIR/systemd/sunshine-display-indicator.service" \
  "$USER_UNIT_DIR/sunshine-display-indicator.service"

if [[ ! -e "$SETTINGS_DIR/settings" ]]; then
  printf 'auto_hide_physical=1\n' >"$SETTINGS_DIR/settings"
  chmod 0600 "$SETTINGS_DIR/settings"
fi

touch "$SUNSHINE_CONFIG"
cp --archive --update=none "$SUNSHINE_CONFIG" \
  "${SUNSHINE_CONFIG}.before-display-manager"
set_sunshine_option capture kms
set_sunshine_option encoder nvenc
set_sunshine_option global_prep_cmd "$SUNSHINE_HOOK"
python3 "$REPO_DIR/migrations/clean-sunshine-apps.py" "$SUNSHINE_APPS"

rm -f "$USER_UNIT_DIR/app-dev.lizardbyte.app.Sunshine.service.d/display.conf"
rm -f "$BIN_DIR/sunshine-display"

systemctl --user daemon-reload
systemctl --user enable sunshine-display-indicator.service
systemctl --user restart sunshine-display-indicator.service

printf 'Installed Sunshine Display Manager.\n'
printf 'Run %s status to inspect the current topology.\n' "$BIN_DIR/sunshine-displayctl"

gdm_home=$(getent passwd gdm | cut -d: -f6) || gdm_home=""
if [[ -n "$gdm_home" && ! -e "${gdm_home}/.config/monitors.xml" ]]; then
  printf '\nThe login screen has no display configuration, so the greeter lights up\n'
  printf 'the virtual display too. Run %s/root/install-greeter-config to fix it.\n' \
    "$REPO_DIR"
fi
