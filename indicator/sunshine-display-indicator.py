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

        self.virtual_item = Gtk.CheckMenuItem(label="虚拟显示器 (DP-3, 4K60)")
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

        self.boot_stock_item = Gtk.MenuItem(label="重启到原版条目 (释放 DP-3)")
        self.boot_stock_item.connect("activate", self.on_boot_stock)
        menu.append(self.boot_stock_item)

        self.boot_cancel_item = Gtk.MenuItem(label="取消已排队的重启模式")
        self.boot_cancel_item.connect(
            "activate", lambda _item: self.run_controller("boot-cancel")
        )
        menu.append(self.boot_cancel_item)
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
        if confirm(
            "现在重启到虚拟显示器条目？",
            "这会立即重启主机。重启后 DP-3 会带着注入的 EDID，"
            "虚拟显示器可以随时打开。",
        ):
            self.run_controller("boot-virtual")

    def on_boot_stock(self, _item):
        if confirm(
            "现在重启到原版条目？",
            "这会立即重启主机。重启后 DP-3 恢复普通端口行为，"
            "在下一次重启回虚拟条目之前无法串流到虚拟显示器。",
        ):
            self.run_controller("boot-stock")

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
        boot_mode = state.get("boot_mode", "virtual")
        boot_pending = state.get("boot_pending", "none")
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
        pending = ""
        if boot_pending == "virtual":
            pending = " | 下次启动：虚拟显示器条目"
        elif boot_pending == "stock":
            pending = " | 下次启动：原版条目"
        self.status_item.set_label(f"{physical} | {virtual}{stream}{pending}")

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
