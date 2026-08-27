# Sunshine Display Manager

*English | [简体中文](README.zh-CN.md)*

A 4K60 virtual display for Sunshine on this host: GNOME Wayland, NVIDIA RTX
3080, GDM 50.

## Hardware map

| Role | Kernel connector | GNOME connector | Mode |
| --- | --- | --- | --- |
| Physical display | `DP-1` | `DP-1` | `1920x1080@165.001`, SDR |
| Virtual display | `DP-3` | `DP-3` | `3840x2160@59.997`, SDR |

The virtual display is two independent mechanisms, and it needs both:

- **EDID injection.** The kernel argument
  `drm.edid_firmware=DP-3:edid/sunshine-4k60-hdr.bin` makes the port use a
  forged 4K60 EDID. This can only happen at boot, see [Boot entries](#boot-entries).
- **Connector forcing.** Writing `on` to `/sys/class/drm/card*-DP-3/status`
  makes the kernel report the port as connected; writing `detect` hands it
  back. This is purely a runtime switch.

So the virtual display does not exist until something asks for it.

`DP-3` is a port that never gets a cable on this machine, which leaves the HDMI
port free for a real display. The cost is HDR: a forced DisplayPort connector
cannot carry it. See [What a sink-less DisplayPort connector can and cannot
do](#what-a-sink-less-displayport-connector-can-and-cannot-do). The `hdmi-hdr`
branch trades the HDMI port for working HDR.

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
- Every topology change is confirmed against `/sys/class/drm/card*-*/enabled`,
  because `gdctl` reports what Mutter accepted, not what the driver committed.
  A rejected commit is an error, not a silent half-applied state.
- When Moonlight launches an app, Sunshine's `global_prep_cmd` records the
  current topology. With automation on, it attaches the virtual display,
  switches to virtual-only, and inhibits idle and suspend.
- When the Sunshine app session ends, the previous topology is restored, and
  the connector is handed back if nothing needs it any more.
- Switching manually during a stream sets a manual override: the old topology
  is not restored on disconnect.

"Connecting" here means Moonlight launching a Sunshine app and establishing a
stream, not a client merely browsing the host's app list.

## Install

```bash
./root/install-edid
./root/install-boot-entry
./install.sh
```

`install-edid` installs the EDID firmware and pulls it into the initramfs;
`install-boot-entry` generates the GRUB entry, installs the runtime helper and
a passwordless sudo rule for it; `install.sh` installs the user-level CLI, the
indicator and two user units. The EDID is injected on the next boot.

## Boot entries

The EDID argument is not written into the default command line. It gets its own
GRUB menu entry:

| Entry | Kernel argument | Result |
| --- | --- | --- |
| `Ubuntu (virtual display)` (default) | `drm.edid_firmware=DP-3:edid/sunshine-4k60-hdr.bin` | `DP-3` can be forced into a 4K60 virtual display at any time |
| `Ubuntu` | none | `DP-3` behaves like a normal port, no virtual display |

The virtual entry is the default: the connector it injects stays disconnected
until something forces it on, so booting it costs nothing. The stock entry
stays in the menu for when `DP-3` has to behave like a normal port.

`/etc/grub.d/11_linux_sunshine` re-runs `10_linux` with modified arguments and a
different title, so both sets of entries stay in sync across kernel upgrades and
no kernel path is hardcoded. Every generated menu identifier gets a `sunshine-`
prefix to keep it distinct from the stock ones.

Note that there is **no** `video=DP-3:e`. That argument would report the
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
a reboot. Only handing `DP-3` back to normal use does.

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
- Starting and stopping the Sunshine service
- Opening the Sunshine web UI
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
Status      status  boot-status  verify
Displays    physical-only  virtual-only  both
            physical-on  physical-off  virtual-on  virtual-off  recover
Connector   attach  detach
Boot mode   boot-virtual  boot-stock  boot-cancel
Sunshine    sunshine-on  sunshine-off  sunshine-restart
Automation  auto-on  auto-off  stream-start  stream-stop
```

With no argument it prints one line of JSON for the indicator and for scripts.
`stream-start` and `stream-stop` are Sunshine's session hooks, `attach` and
`detach` are the connector hooks; none of them are meant to be run by hand.

`recover` stops the streaming inhibitor, clears the runtime session state, hands
the virtual connector back and forces `DP-1` back to `1920x1080@165.001` SDR.

## What a sink-less DisplayPort connector can and cannot do

Measured on this host, with the state read back from DRM rather than from
`gdctl`'s exit code, which only reports whether Mutter accepted the request:

| Topology | Mode | Color mode | Result |
| --- | --- | --- | --- |
| dual | `800x600@60.317` | SDR | applied |
| dual | `1920x1080@60.000` | SDR | applied |
| dual | `3840x2160@29.970` | SDR | applied |
| dual | `3840x2160@59.997` | SDR | applied, 3/3 |
| dual | `3840x2160@59.997` | `sdr-native` | applied |
| virtual-only | `3840x2160@59.997` | SDR | applied, 2/2 |
| dual | `1920x1080@60.000` | `bt2100` | rejected |
| dual | `3840x2160@29.970` | `bt2100` | rejected |
| dual | `3840x2160@59.997` | `bt2100` | rejected, 3/3 |
| virtual-only | `3840x2160@59.997` | `bt2100` | rejected |

A rejected commit looks like this: `gdctl` exits 0, Mutter shows the new layout,
`/sys/class/drm/card1-DP-3/enabled` stays `disabled`, the connector never gets a
CRTC, and gnome-shell logs

```text
Page flip failed: drmModeAtomicCommit: Invalid argument
```

about thirty times a second until the layout is changed back.

So bandwidth is not the limit — `1920x1080@60` fails in HDR while
`3840x2160@60` succeeds in SDR. HDR over DisplayPort needs capability bits the
driver reads out of the sink's DPCD, and a forged EDID cannot produce a link to
read them from. HDMI is one-way TMDS: the HDR InfoFrame goes out with no
handshake, which is why the `hdmi-hdr` branch gets HDR at the price of the HDMI
port.

Sunshine captures the first live output it finds. It logged
`Found connector ID [825]` (`DP-1`) while the physical display was the only live
output, and `Found connector ID [833]` (`DP-3`) while the virtual display was.
That is why streaming switches to virtual-only rather than dual.

## Port limitation

Under the virtual entry, `DP-3` always uses the forged AOC EDID. A real display
plugged into it would not have its own EDID read: one that tolerates the 4K60
timings might still light up, but its modes, HDR and audio capabilities and its
hotplug state would all be wrong. Reboot into the stock entry to use the port
normally; nothing has to be uninstalled. `DP-1`, `DP-2` and HDMI are untouched.

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
- `/sys/kernel/debug/dri/*/DP-3/edid_override`, the only runtime injection
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
root/         EDID and GRUB boot entry install/remove tools,
              plus the runtime boot-entry and connector helper
edid/         the verified 4K60 EDID
config/       Sunshine configuration fragment
```

## Branches

- `main` — the virtual display on `DP-3`, 4K60 SDR, HDMI port left free.
- `hdmi-hdr` — the virtual display on `HDMI-A-1`, 4K60 HDR, HDMI port consumed
  by the forged EDID whenever the virtual entry is booted.
