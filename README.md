# Sunshine Display Manager

*English | [简体中文](README.zh-CN.md)*

A 4K60 virtual display for Sunshine on this host: GNOME Wayland, NVIDIA RTX
3080, GDM 50.

## Hardware map

| Role | Kernel connector | GNOME connector | Mode |
| --- | --- | --- | --- |
| Physical display | `DP-1` | `DP-1` | `1920x1080@165.001`, SDR |
| Virtual display | `DP-3` or `HDMI-A-1` | `DP-3` or `HDMI-1` | `3840x2160@59.997`, 200% scale |

The virtual display is two independent mechanisms, and it needs both:

- **EDID injection.** The kernel argument
  `drm.edid_firmware=<connector>:edid/sunshine-4k60-hdr.bin` makes the port use a
  forged 4K60 EDID. This can only happen at boot, see [Boot entries](#boot-entries).
- **Connector forcing.** Writing `on` to `/sys/class/drm/card*-<connector>/status`
  makes the kernel report the port as connected; writing `detect` hands it
  back. This is purely a runtime switch.

So the virtual display does not exist until something asks for it.

## Virtual display port

The virtual display lives on one of two ports, and only one port carries the
forged EDID at a time. The port decides the colour space and nothing else:

| Port | Kernel / GNOME connector | Colour mode | Sunshine output | Cost |
| --- | --- | --- | --- | --- |
| `dp` (default) | `DP-3` / `DP-3` | `default` | 4K60 10-bit SDR | none, `DP-3` never gets a cable on this machine |
| `hdmi` | `HDMI-A-1` / `HDMI-1` | `bt2100` | 4K60 HDR10 | the HDMI port carries the forged EDID whenever the virtual entry is booted |

Everything else — mode, 200% scale, dual-screen layout, automation, greeter
handling — is identical on both. Why only HDMI can do HDR is
[below](#hdr-only-works-on-hdmi).

Switching rewrites the kernel arguments of a GRUB entry, so it asks for a
password through polkit and then reboots:

```bash
sunshine-displayctl port-status   # the port in use now and after the next boot
sunshine-displayctl port-dp       # move to DP-3, SDR, reboot now
sunshine-displayctl port-hdmi     # move to HDMI-A-1, HDR, reboot now
```

The indicator has the same switch as a pair of radio items. The selected port is
stored in `/etc/default/sunshine-display-manager`, which the generated GRUB entry
reads on every `update-grub`; the running kernel keeps whatever port it booted
with, which is why the switch reboots.

## Control logic

- Turning the virtual display on: go dual if the physical display is on,
  otherwise go virtual-only.
- Turning the virtual display off: make sure the physical display is on, go
  physical-only, and hand the connector back.
- Turning the physical display on: go dual if the virtual display is on,
  otherwise go physical-only.
- Turning the physical display off: make sure the virtual display is on, then
  go virtual-only.
- Anything that needs the virtual display forces the connector on first and
  waits for both the kernel and Mutter to agree that it is there.
- The virtual display always uses `3840x2160@59.997` at 200% scale, in the colour
  mode its port allows; the physical display remains SDR.
- Every topology change is confirmed against `/sys/class/drm/card*-*/enabled`,
  because `gdctl` reports what Mutter accepted, not what the driver committed.
  A rejected commit is an error, not a silent half-applied state.
- When Moonlight launches an app, Sunshine's `global_prep_cmd` attaches the
  virtual display, switches to virtual-only, and inhibits idle and suspend.
  Turning off "hide the physical display while streaming" skips the switch, but
  not the inhibitor.
- When the Sunshine app session ends, the topology always returns to
  physical-only and the connector is handed back — including when the stream
  started from a dual layout, and including when the switch was skipped.
  Restoring a dual layout would leave the virtual display sitting in Mutter
  after the stream, and the point of the forced connector is that it exists only
  while something is streaming to it.
- The menu items that turn the virtual display on by hand are still there for
  testing; they are the only way it appears outside a stream.

"Connecting" here means Moonlight launching a Sunshine app and establishing a
stream, not a client merely browsing the host's app list.

## Install

```bash
./root/install-edid
./root/install-boot-entry
./install.sh
```

`install-edid` installs the EDID firmware and pulls it into the initramfs;
`install-boot-entry` generates the GRUB entry, installs the two runtime helpers,
a passwordless sudo rule for the boot-mode one and a polkit action for the port
one; `install.sh` installs the user-level CLI, the indicator and two user units.
The EDID is injected on the next boot.

## Boot entries

The EDID argument is not written into the default command line. It gets its own
GRUB menu entry:

| Entry | Kernel argument | Result |
| --- | --- | --- |
| `Ubuntu (virtual display)` (default) | `drm.edid_firmware=<port>:edid/sunshine-4k60-hdr.bin` | the selected port can be forced into a 4K60 virtual display at any time |
| `Ubuntu` | none | the selected port behaves like a normal one, no virtual display |

The virtual entry is the default: the connector it injects stays disconnected
until something forces it on, so booting it costs nothing. The stock entry
stays in the menu for when the port has to behave normally.

`/etc/grub.d/11_linux_sunshine` re-runs `10_linux` with modified arguments and a
different title, so both sets of entries stay in sync across kernel upgrades and
no kernel path is hardcoded. It reads the port out of
`/etc/default/sunshine-display-manager` rather than hardcoding it, which is what
makes [switching ports](#virtual-display-port) a one-line change plus a reboot.
Every generated menu identifier gets a `sunshine-` prefix to keep it distinct
from the stock ones.

Note that there is **no** `video=<port>:e`. That argument would report the
connector as connected from boot, and the greeter would land on the virtual
display. Without it the connector is entirely under runtime control; the
firmware EDID is loaded at the connector's first runtime probe, so nothing is
lost.

### Unattended switching

`root/install-boot-entry` sets `GRUB_DEFAULT=saved` (with `GRUB_SAVEDEFAULT`
off, so a one-shot choice never becomes permanent) and installs
`/usr/local/sbin/sunshine-boot-mode` plus a sudo rule that allows exactly that
command. Entries can then be switched over SSH, without seeing the GRUB menu:

```bash
sunshine-displayctl boot-status    # current entry and the armed next boot
sunshine-displayctl boot-virtual   # boot the virtual entry next, reboot now
sunshine-displayctl boot-stock     # boot the stock entry next, reboot now
sunshine-displayctl boot-cancel    # clear the armed boot without rebooting
```

Arming only affects the next boot. The armed state is mirrored in
`/run/sunshine-display-boot-pending` so the indicator can poll it without root.

Since the virtual display is a runtime switch, day-to-day streaming never needs
a reboot. Only handing the injected port back to normal use, or moving the
virtual display to the other port, does.

### Behaviour under the stock entry

Without the injected EDID, forcing the connector on would produce an output with
no modes, so the helper refuses:

- The virtual, dual and virtual-only items in the indicator are greyed out and
  the title reads "虚拟不可用".
- `virtual-only`, `both`, `virtual-on` and `physical-off` exit with an error.
- Moonlight connections no longer switch topology. Streaming still works, it
  just streams the physical display; idle and suspend inhibition still applies.

## Login screen

The virtual display only exists after login, so the GDM greeter only ever sees
the physical display and needs no configuration.
`sunshine-virtual-connector.service` runs `detach` when the graphical session
starts and when it stops, so logging out always hands the connector back.

Since GDM 50 the greeter runs as the dynamic user `gdm-greeter` with its home on
tmpfs at `/run/gdm3/home/gdm-greeter`, rebuilt on every boot, and
`/var/lib/gdm3/.config/monitors.xml` is never read again. Greeter configuration
is a dead end on this GDM, which is one reason the connector is a runtime
switch. To clean up what earlier versions left behind:

```bash
./root/remove-greeter-config
```

## Indicator

`sunshine-display-indicator.service` starts with the GNOME session. The menu
offers:

- Toggling the physical and the virtual display separately
- Picking physical-only, virtual-only or dual directly
- Toggling "hide the physical display while streaming"
- Showing the current boot entry, and rebooting into the virtual or stock entry
  behind a confirmation dialog
- Cancelling an armed but not yet consumed boot entry
- Moving the virtual display between `DP-3 (SDR)` and `HDMI (HDR)`, behind a
  confirmation dialog and a polkit password prompt
- Starting and stopping the Sunshine service
- Opening the Sunshine web UI
- Resetting the virtual display's HDR brightness to the 100% reference, enabled
  only while a stream is running on the HDR virtual display
- Forcing the physical display back

Service logs:

```bash
systemctl --user status sunshine-display-indicator.service
journalctl --user -u sunshine-display-indicator.service -b
```

## CLI

Everything lives in one command, `sunshine-displayctl`. It sets `XDG_RUNTIME_DIR`
and the GNOME session bus address itself, so it works over SSH as the desktop
user. Every command except the boot-entry ones needs the GNOME session to be
running.

```bash
sunshine-displayctl help
```

```text
Status      status  boot-status  port-status  verify
Displays    physical-only  virtual-only  both
            physical-on  physical-off  virtual-on  virtual-off  recover
            luminance-reset
Connector   attach  detach
Boot mode   boot-virtual  boot-stock  boot-cancel
Port        port-dp  port-hdmi
Sunshine    sunshine-on  sunshine-off  sunshine-restart
Automation  auto-on  auto-off  stream-start  stream-stop
```

With no argument it prints one line of JSON for the indicator and for scripts.
`stream-start` and `stream-stop` are Sunshine's session hooks, `attach` and
`detach` are the connector hooks; none of them are meant to be run by hand.

`recover` stops the streaming inhibitor, clears the runtime session state, hands
the virtual connector back and forces `DP-1` back to `1920x1080@165.001` SDR.

`luminance-reset` puts the virtual display's HDR brightness back to 100%. Mutter
models the reference luminance of an HDR output as a backlight, which is what the
top bar's brightness slider writes to; 100% is BT.2408 graphics white, the level
the desktop is encoded against, and any other value moves where SDR content lands
in the PQ signal the client decodes. The control appears and disappears with the
connector, so it only works while the virtual display is attached and in HDR, and
`stream-stop` has nothing left to reset by the time it runs.

`port-dp` and `port-hdmi` are the only commands that ask for a password: they use
`sudo` from a terminal and `pkexec` from the indicator. Everything else either
needs no privileges or goes through the passwordless
`/usr/local/sbin/sunshine-boot-mode`.

## HDR only works on HDMI

`DP-3` is a port that never gets a cable on this machine, so it is the natural
home for the forged EDID and leaves HDMI free for a real display. It cannot carry
HDR. Mutter accepts `bt2100` on it and GNOME's HDR switch turns on, but the DRM
connector's `HDR_OUTPUT_METADATA` and `Colorspace` properties stay zero, so
Sunshine's KMS capture reads the output as SDR and encodes 10-bit SDR rather than
HDR10. HDR over DisplayPort needs capability bits the driver reads out of the
sink's DPCD, and a forged EDID cannot produce a link to read them from.

HDMI is one-way TMDS: the HDR InfoFrame goes out with no handshake, so a forced
connector there does carry HDR — at the price of the port. See the
[DP-3 HDR investigation](docs/dp-hdr-investigation.zh-CN.md) for the full
exploration, older-stack results, Sunshine's source-level check, and two possible
implementation paths.

Sunshine captures the first live output it finds. It logged
`Found connector ID [825]` (`DP-1`) while the physical display was the only live
output, and `Found connector ID [833]` (`DP-3`) while the virtual display was.
That is why streaming switches to virtual-only rather than dual.

## Port limitation

Under the virtual entry, the selected port always uses the forged AOC EDID. A
real display plugged into it would not have its own EDID read: one that tolerates
the 4K60 timings might still light up, but its modes, HDR and audio capabilities
and its hotplug state would all be wrong. Reboot into the stock entry to use the
port normally, or move the virtual display to the other port; nothing has to be
uninstalled. Every port except the selected one is untouched.

To remove the boot entry and the sudo rule but keep the EDID firmware:

```bash
./root/remove-boot-entry
```

To remove the EDID firmware as well:

```bash
./root/remove-edid
```

`remove-edid` calls `remove-boot-entry` first. Both only remove what this
project added, and neither clobbers unrelated GRUB changes made afterwards.

## Why the EDID has to be injected at boot

Secure Boot is on and the kernel is in `integrity` lockdown. Measured on this
host:

- `/sys/module/drm/parameters/edid_firmware` is writable, but the EDID is
  installed as a connector-level override at the connector's first probe and
  kept for its lifetime, so writing the parameter afterwards does nothing.
- `/sys/kernel/debug/dri/*/<connector>/edid_override`, the only runtime injection
  interface DRM has, returns `EPERM` on any write-open under lockdown. Lockdown
  can be raised but never lowered, so only turning Secure Boot off in firmware
  would lift it.
- Neither `nvidia`, `nvidia_modeset` nor `nvidia_drm` has an EDID parameter.
  `CustomEDID` is X11-only.

Connector forcing is not restricted by lockdown, hence the split: the EDID goes
in once at boot, the connector is switched at runtime.

## Uninstall

To remove the indicator, the CLI and the Sunshine session hooks:

```bash
./uninstall.sh
```

Add `./root/remove-boot-entry` to drop the boot entry, or `./root/remove-edid`
to drop the EDID firmware as well. Greeter configuration installed by earlier
versions is cleaned up with `./root/remove-greeter-config`.

## Layout

```text
bin/          display state controller
indicator/    GNOME AppIndicator tray process
systemd/      user service units
root/         EDID and GRUB boot entry install/remove tools, plus the runtime
              boot-entry, connector and virtual display port helpers
polkit/       polkit action for the port helper
edid/         the verified 4K60 EDID
config/       Sunshine configuration fragment
```
