# Sunshine Display Manager

为当前主机的 GNOME Wayland、NVIDIA RTX 3080 和 Sunshine 提供 4K60 HDR
虚拟显示器管理。

## 当前硬件映射

| 用途 | 内核连接器 | GNOME 连接器 | 模式 |
| --- | --- | --- | --- |
| 物理显示器 | `DP-1` | `DP-1` | `1920x1080@165.001`、SDR |
| 虚拟显示器 | `HDMI-A-1` | `HDMI-1` | `3840x2160@59.997`、BT.2100 HDR |

内核通过 EDID 固件强制注册 `HDMI-A-1`。GNOME 中的“关闭”只表示不再为该
输出分配活动 CRTC，内核连接器仍会显示为 `connected`。

## 控制逻辑

- 手动打开虚拟屏：如果物理屏已开启，则进入双屏；否则进入仅虚拟屏。
- 手动关闭虚拟屏：先确保物理屏开启，再进入仅物理屏。
- 手动打开物理屏：如果虚拟屏已开启，则进入双屏；否则进入仅物理屏。
- 手动关闭物理屏：先确保虚拟屏开启，再进入仅虚拟屏。
- Moonlight 启动应用时，Sunshine 的 `global_prep_cmd` 记录当前拓扑。自动控制
  开启时切换为仅虚拟屏，并启用 GNOME 空闲/挂起抑制。
- Sunshine 应用会话结束时恢复此前拓扑。
- 串流期间通过状态栏或 CLI 手动切换会设置“人工覆盖”；断开时保留人工选择，
  不再自动恢复旧拓扑。

这里的“连接”指 Moonlight 启动 Sunshine 应用并建立串流会话，不是客户端仅仅
浏览主机应用列表。

## 安装

EDID 已安装的当前主机只需执行用户级安装：

```bash
./install.sh
```

全新安装或重新建立内核 EDID：

```bash
./root/install-edid
systemctl reboot
```

重启后再执行 `./install.sh`。

让登录界面只使用物理显示器（只需执行一次，见下一节）：

```bash
./root/install-greeter-config
```

## 登录界面

内核参数把 `HDMI-A-1` 永久报告为已连接，因此 GDM 的 greeter 也会看到虚拟
显示器。greeter 以 `gdm` 用户运行，而它默认没有任何显示配置
（`/var/lib/gdm3/.config/monitors.xml` 不存在），于是 mutter 退回默认布局，
把两块屏全部点亮，登录框落在 4K 虚拟屏上，选择用户和输入密码只能盲打。

```bash
./root/install-greeter-config
```

该命令把 `config/gdm-monitors.xml` 安装为 `gdm` 用户的
`~/.config/monitors.xml`，内容与用户会话里的“仅物理屏”配置一致：`DP-1` 是
`1920x1080@165.001` 主屏，`HDMI-1` 放在 `<disabled>` 里。安装前会校验该 XML
与 `bin/sunshine-displayctl` 中的连接器和模式常量一致，并拒绝任何启用了虚拟
连接器的配置。文件属主是 root，greeter 只能读取，不会把布局改回去。

这是纯用户空间配置：不改内核参数、不需要重启、不影响用户会话和串流路径。
切换用户、注销或重启后进入登录界面即生效。用户会话仍然读取自己的
`~/.config/monitors.xml`。

两点范围限制：

- Plymouth 启动画面仍然会画在虚拟屏上。该阶段还没有任何显示管理器配置可
  用，且没有交互输入，不影响登录。
- 如果开机时物理显示器处于断电状态，`DP-1` 会被报告为断开，配置无法匹配，
  greeter 会退回默认布局。

恢复 GDM 的默认行为：

```bash
./root/remove-greeter-config
```

## 状态栏

`sunshine-display-indicator.service` 随 GNOME 图形会话启动。菜单提供：

- 分别开关物理和虚拟显示器
- 直接选择仅物理、仅虚拟或双屏
- 开关“串流时自动关闭物理显示器”
- 启停 Sunshine 服务
- 打开 Sunshine Web 管理页面
- 强制恢复物理显示器

查看服务日志：

```bash
systemctl --user status sunshine-display-indicator.service
journalctl --user -u sunshine-display-indicator.service -b
```

## CLI 与 SSH 救急

控制器会自动设置 `XDG_RUNTIME_DIR` 和 GNOME 会话 D-Bus 地址，因此从 SSH 登录
同一用户后可直接运行。GNOME 图形会话必须仍在运行。

```bash
sunshine-display-status
sunshine-display-recover
sunshine-display-physical-only
sunshine-display-virtual-only
sunshine-display-both
```

底层完整命令：

```bash
sunshine-displayctl status
sunshine-displayctl verify
sunshine-displayctl physical-only
sunshine-displayctl virtual-only
sunshine-displayctl both
sunshine-displayctl auto-on
sunshine-displayctl auto-off
sunshine-displayctl recover
```

`recover` 会停止串流显示抑制、清除运行时会话状态，并强制恢复
`DP-1` 的 `1920x1080@165.001` SDR 输出。

## HDMI 端口限制

当前内核参数为：

```text
drm.edid_firmware=HDMI-A-1:edid/sunshine-4k60-hdr.bin video=HDMI-A-1:e
```

这意味着该 HDMI 端口始终使用伪造的 AOC EDID，并始终被报告为已连接。把真实
显示器插入同一个 HDMI 端口后，系统不会读取真实显示器的 EDID。兼容 4K60
时序的显示器可能仍能显示，但模式、HDR、音频能力和热插拔状态都可能不正确，
不应把该端口当作普通物理 HDMI 使用。DisplayPort 端口不受影响。

恢复 HDMI 端口的正常物理用途：

```bash
./root/remove-edid
systemctl reboot
```

该命令只移除本项目添加的两个内核参数、dracut 配置和 EDID 文件，不会覆盖
之后对 GRUB 做的其他修改。

## 卸载

只移除状态栏、CLI 和 Sunshine 会话钩子：

```bash
./uninstall.sh
```

要同时恢复登录界面的默认行为：

```bash
./root/remove-greeter-config
```

要同时恢复物理 HDMI 行为，再运行 `./root/remove-edid` 并重启。

## 文件结构

```text
bin/          显示状态控制器
indicator/    GNOME AppIndicator 状态栏进程
systemd/      用户服务单元
ssh/          独立救急入口
root/         EDID 和登录界面配置的安装与移除工具
edid/         校验过的 4K60 HDR EDID
config/       Sunshine 配置片段和 GDM 登录界面显示配置
```
