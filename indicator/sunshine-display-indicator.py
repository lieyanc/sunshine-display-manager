#!/usr/bin/env python3
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import AppIndicator3, GLib, Gtk


CONTROLLER = os.path.expanduser("~/.local/bin/sunshine-displayctl")
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
LOCK_FILE = os.path.join(RUNTIME_DIR, "sunshine-display-indicator.lock")

# The virtual display is the same 4K60 output on either port; only the connector
# and the colour space differ. HDR needs DRM metadata the driver emits over HDMI
# but not over a forced DisplayPort connector.
PORTS = {
    "dp": {"label": "DP-3 (SDR)", "short": "DP-3", "command": "port-dp"},
    "hdmi": {"label": "HDMI (HDR)", "short": "HDMI", "command": "port-hdmi"},
}

# Mutter models the HDR reference luminance as a backlight, so the top bar's
# brightness slider changes how SDR content lands in the PQ signal the client
# decodes. 100% is the only value the stream is colour correct at, and a stray
# brightness key during a session is the one way to leave it.
REFERENCE_LUMINANCE = 100


def confirm(question, detail):
    dialog = Gtk.MessageDialog(
        transient_for=None,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.OK_CANCEL,
        text=question,
    )
    dialog.format_secondary_text(detail)
    dialog.set_keep_above(True)
    answer = dialog.run()
    dialog.destroy()
    return answer == Gtk.ResponseType.OK


class Indicator:
    def __init__(self):
        self.updating = False
        self.busy = False
        self.virtual_injected = True
        self.virtual_port = "dp"
        self.virtual_port_configured = "dp"
        self.indicator = AppIndicator3.Indicator.new(
            "sunshine-display-manager",
            "preferences-desktop-display-symbolic",
            AppIndicator3.IndicatorCategory.SYSTEM_SERVICES,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Sunshine Display Manager")

        menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label="正在读取显示状态...")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.virtual_item = Gtk.CheckMenuItem(label="虚拟显示器 (4K60)")
        self.virtual_item.connect("toggled", self.on_virtual_toggled)
        menu.append(self.virtual_item)

        self.physical_item = Gtk.CheckMenuItem(label="物理显示器 (1080p165)")
        self.physical_item.connect("toggled", self.on_physical_toggled)
        menu.append(self.physical_item)

        self.auto_item = Gtk.CheckMenuItem(label="串流时自动关闭物理显示器")
        self.auto_item.connect("toggled", self.on_auto_toggled)
        menu.append(self.auto_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.both_item = Gtk.MenuItem(label="启用双屏")
        self.both_item.connect("activate", lambda _item: self.run_controller("both"))
        menu.append(self.both_item)

        self.virtual_only_item = Gtk.MenuItem(label="仅虚拟显示器")
        self.virtual_only_item.connect(
            "activate", lambda _item: self.run_controller("virtual-only")
        )
        menu.append(self.virtual_only_item)

        self.physical_only_item = Gtk.MenuItem(label="仅物理显示器")
        self.physical_only_item.connect(
            "activate", lambda _item: self.run_controller("physical-only")
        )
        menu.append(self.physical_only_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.boot_item = Gtk.MenuItem(label="启动模式")
        self.boot_item.set_sensitive(False)
        menu.append(self.boot_item)

        self.boot_virtual_item = Gtk.MenuItem(label="重启到虚拟显示器条目")
        self.boot_virtual_item.connect("activate", self.on_boot_virtual)
        menu.append(self.boot_virtual_item)

        self.boot_stock_item = Gtk.MenuItem(label="重启到原版条目")
        self.boot_stock_item.connect("activate", self.on_boot_stock)
        menu.append(self.boot_stock_item)

        self.boot_cancel_item = Gtk.MenuItem(label="取消已排队的重启模式")
        self.boot_cancel_item.connect(
            "activate", lambda _item: self.run_controller("boot-cancel")
        )
        menu.append(self.boot_cancel_item)

        self.port_items = {}
        first = None
        for port, spec in PORTS.items():
            item = Gtk.RadioMenuItem(label=f"虚拟屏端口：{spec['label']}")
            if first is None:
                first = item
            else:
                item.join_group(first)
            item.connect("toggled", self.on_port_toggled, port)
            menu.append(item)
            self.port_items[port] = item
        menu.append(Gtk.SeparatorMenuItem())

        self.sunshine_item = Gtk.CheckMenuItem(label="Sunshine 服务")
        self.sunshine_item.connect("toggled", self.on_sunshine_toggled)
        menu.append(self.sunshine_item)

        web_item = Gtk.MenuItem(label="打开 Sunshine 管理页面")
        web_item.connect(
            "activate",
            lambda _item: subprocess.Popen(
                ["xdg-open", "https://localhost:47990"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        )
        menu.append(web_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.luminance_item = Gtk.MenuItem(label="复位 HDR 亮度")
        self.luminance_item.connect(
            "activate", lambda _item: self.run_controller("luminance-reset")
        )
        menu.append(self.luminance_item)

        recover_item = Gtk.MenuItem(label="救急：恢复物理显示器")
        recover_item.connect("activate", lambda _item: self.run_controller("recover"))
        menu.append(recover_item)

        quit_item = Gtk.MenuItem(label="退出状态栏图标")

        quit_item.connect("activate", Gtk.main_quit)
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)
        self.refresh()
        GLib.timeout_add_seconds(5, self.refresh)

    def on_boot_virtual(self, _item):
        port = PORTS[self.virtual_port]["short"]
        if confirm(
            "现在重启到虚拟显示器条目？",
            f"这会立即重启主机。重启后 {port} 会带着注入的 EDID，"
            "虚拟显示器可以随时打开。",
        ):
            self.run_controller("boot-virtual")

    def on_boot_stock(self, _item):
        port = PORTS[self.virtual_port]["short"]
        if confirm(
            "现在重启到原版条目？",
            f"这会立即重启主机。重启后 {port} 恢复普通端口行为，"
            "在下一次重启回虚拟条目之前无法串流到虚拟显示器。",
        ):
            self.run_controller("boot-stock")

    # Moving the virtual display to the other port rewrites a boot entry, so it
    # asks for a password and only takes effect after the reboot it triggers.
    def on_port_toggled(self, item, port):
        if self.updating or not item.get_active() or port == self.virtual_port_configured:
            return
        spec = PORTS[port]
        if confirm(
            f"把虚拟显示器切到 {spec['short']}？",
            f"这会改写启动条目并立即重启主机，需要输入管理员密码。"
            f"重启后虚拟显示器在 {spec['label']} 上。",
        ):
            self.run_controller(spec["command"])
        else:
            self.refresh()

    def on_virtual_toggled(self, item):
        if not self.updating:
            self.run_controller("virtual-on" if item.get_active() else "virtual-off")

    def on_physical_toggled(self, item):
        if not self.updating:
            self.run_controller("physical-on" if item.get_active() else "physical-off")

    def on_auto_toggled(self, item):
        if not self.updating:
            self.run_controller("auto-on" if item.get_active() else "auto-off")

    def on_sunshine_toggled(self, item):
        if self.updating:
            return
        self.run_controller("sunshine-on" if item.get_active() else "sunshine-off")

    def run_controller(self, command):
        self.run_background(
            lambda: subprocess.run(
                [CONTROLLER, command], capture_output=True, text=True
            )
        )

    def run_background(self, operation):
        if self.busy:
            return
        self.busy = True
        self.status_item.set_label("正在应用显示配置...")

        def worker():
            result = operation()
            GLib.idle_add(self.command_finished, result)

        threading.Thread(target=worker, daemon=True).start()

    def command_finished(self, result):
        self.busy = False
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "操作失败").strip().splitlines()[-1]
            self.status_item.set_label(f"错误：{message}")
        else:
            self.refresh()
        return False

    def refresh(self):
        if self.busy:
            return True
        result = subprocess.run([CONTROLLER, "status"], capture_output=True, text=True)
        if result.returncode != 0:
            self.indicator.set_icon_full("dialog-error-symbolic", "显示状态读取失败")
            message = (result.stderr or "显示状态读取失败").strip().splitlines()[-1]
            self.status_item.set_label(f"错误：{message}")
            return True

        try:
            state = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.status_item.set_label("错误：控制器返回了无效状态")
            return True

        self.updating = True
        self.virtual_injected = state.get("virtual_injected", True)
        self.virtual_port = state.get("virtual_port", "dp")
        self.virtual_port_configured = state.get("virtual_port_configured", "dp")
        boot_mode = state.get("boot_mode", "virtual")
        boot_pending = state.get("boot_pending", "none")
        port = PORTS.get(self.virtual_port, PORTS["dp"])
        self.virtual_item.set_label(
            "虚拟显示器 ({}, 4K60 {})".format(
                port["short"], "HDR" if state.get("virtual_port_hdr") else "SDR"
            )
        )
        self.boot_stock_item.set_label(f"重启到原版条目 (释放 {port['short']})")
        for name, item in self.port_items.items():
            item.set_active(name == self.virtual_port_configured)
        self.virtual_item.set_sensitive(self.virtual_injected)
        self.both_item.set_sensitive(self.virtual_injected)
        self.virtual_only_item.set_sensitive(self.virtual_injected)
        self.physical_item.set_sensitive(self.virtual_injected or not state["physical"])
        self.boot_item.set_label(
            "启动条目：虚拟显示器" if boot_mode == "virtual" else "启动条目：原版"
        )
        self.boot_virtual_item.set_sensitive(boot_mode != "virtual")
        self.boot_stock_item.set_sensitive(boot_mode == "virtual")
        self.boot_cancel_item.set_sensitive(boot_pending != "none")
        # Only a streaming HDR virtual display has a reference to be off, and the
        # control disappears with the connector, so the item is dead weight for
        # every other topology.
        luminance = state.get("virtual_luminance")
        reference = state.get("luminance_reference", REFERENCE_LUMINANCE)
        if luminance is None:
            self.luminance_item.set_label("复位 HDR 亮度")
        else:
            self.luminance_item.set_label(f"复位 HDR 亮度 (当前 {luminance}%)")
        self.luminance_item.set_sensitive(
            bool(state["stream_active"])
            and bool(state["virtual_hdr"])
            and luminance is not None
            and luminance != reference
        )
        self.virtual_item.set_active(state["virtual"])
        self.physical_item.set_active(state["physical"])
        self.auto_item.set_active(state["auto_hide_physical"])
        self.sunshine_item.set_active(state["sunshine"])
        self.updating = False

        physical = "物理开" if state["physical"] else "物理关"
        if not self.virtual_injected:
            virtual = "虚拟不可用"
        elif state["virtual_hdr"]:
            virtual = "虚拟开 HDR"
        elif state["virtual"]:
            virtual = "虚拟开"
        else:
            virtual = "虚拟关"
        stream = " | 串流中" if state["stream_active"] else ""
        # Worth a word only when it is off the reference: the point is to notice a
        # stray brightness change during a session, when the colours are wrong but
        # nothing else in the menu says why.
        drift = ""
        if luminance is not None and luminance != reference:
            drift = f" | 亮度 {luminance}%"
        pending = ""
        if boot_pending == "virtual":
            pending = " | 下次启动：虚拟显示器条目"
        elif boot_pending == "stock":
            pending = " | 下次启动：原版条目"
        if self.virtual_port_configured != self.virtual_port:
            queued = PORTS.get(self.virtual_port_configured, PORTS["dp"])["short"]
            pending += f" | 下次启动：虚拟屏切到 {queued}"
        self.status_item.set_label(f"{physical} | {virtual}{stream}{drift}{pending}")

        if state["stream_active"]:
            icon = "network-transmit-receive-symbolic"
        elif state["topology"] == "both":
            icon = "preferences-desktop-display-symbolic"
        elif state["topology"] == "virtual-only":
            icon = "video-display-symbolic"
        else:
            icon = "computer-symbolic"
        self.indicator.set_icon_full(icon, self.status_item.get_label())
        return True


def main():
    lock = open(LOCK_FILE, "w", encoding="ascii")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = Indicator()
    Gtk.main()
    del app, lock
    return 0


if __name__ == "__main__":
    sys.exit(main())
