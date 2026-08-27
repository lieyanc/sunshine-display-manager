# Sunshine Display Manager

为当前主机的 GNOME Wayland、NVIDIA RTX 3080 和 Sunshine 提供 4K60 HDR
虚拟显示器管理。

## 当前硬件映射

| 用途 | 内核连接器 | GNOME 连接器 | 模式 |
| --- | --- | --- | --- |
| 物理显示器 | `DP-1` | `DP-1` | `1920x1080@165.001`、SDR |
| 虚拟显示器 | `HDMI-A-1` | `HDMI-1` | `3840x2160@59.997`、BT.2100 HDR |

内核通过 EDID 固件强制注册 `HDMI-A-1`，但只在选择了“虚拟显示器”启动项时
才注册（见“启动模式”）。GNOME 中的“关闭”只表示不再为该输出分配活动 CRTC，
内核连接器仍会显示为 `connected`。

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

用户级安装：

```bash
./install.sh
```

全新安装或重新建立内核 EDID 与启动项：

```bash
./root/install-edid
./root/install-boot-entry
```

`install-boot-entry` 不需要立即重启，当前会话保持原样。

让登录界面只使用物理显示器（只需执行一次，见下一节）：

```bash
./root/install-greeter-config
```

## 启动模式

虚拟显示器所需的内核参数不写进默认命令行，而是单独生成一个 GRUB 菜单项：

| 菜单项 | 内核参数 | 结果 |
| --- | --- | --- |
| `Ubuntu` | 无 | HDMI 端口恢复普通物理用途，没有虚拟显示器 |
| `Ubuntu (virtual display)` | `drm.edid_firmware=HDMI-A-1:edid/sunshine-4k60-hdr.bin video=HDMI-A-1:e` | 注册 4K60 HDR 虚拟显示器 |

默认启动的是不带虚拟显示器的普通条目。`/etc/grub.d/11_linux_sunshine` 用改过
的参数和标题重新执行 `10_linux`，因此内核升级后两套条目自动同步，不存在写死
的内核路径；生成的菜单标识符统一加上 `sunshine-` 前缀，与原版条目区分。

### 无人值守切换

`root/install-boot-entry` 会把 `GRUB_DEFAULT` 改为 `saved`（`GRUB_SAVEDEFAULT`
保持关闭，所以一次性选择永远不会变成永久默认），并安装
`/usr/local/sbin/sunshine-boot-mode` 和一条只允许该命令的免密 sudo 规则。于是
远程 SSH 也能在看不到 GRUB 菜单的情况下切换启动模式：

```bash
sunshine-displayctl boot-status    # 当前启动模式和已排队的下次启动
sunshine-displayctl boot-virtual   # 排队一次虚拟显示器启动并立即重启
sunshine-displayctl boot-default   # 清除排队并立即重启回普通模式
sunshine-displayctl boot-cancel    # 只清除排队，不重启
```

“排队”只影响下一次启动，之后自动回到普通模式。排队状态镜像在
`/run/sunshine-display-boot-pending`，状态栏因此可以直接轮询而不需要 root。

### 普通模式下的行为

普通模式下 `HDMI-1` 不存在，因此：

- 状态栏中虚拟显示器、双屏、仅虚拟三项置灰，标题显示“虚拟不可用”。
- `virtual-only`、`both`、`virtual-on`、`physical-off` 会直接报错退出。
- Moonlight 连接时不再自动切换拓扑，串流照常进行，只是串的是物理屏；空闲和
  挂起抑制仍然启用。

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
- 显示当前启动模式，并重启切换到虚拟显示器模式或普通模式（有确认对话框）
- 取消已排队但尚未生效的启动模式
- 启停 Sunshine 服务
- 打开 Sunshine Web 管理页面
- 强制恢复物理显示器

查看服务日志：

```bash
systemctl --user status sunshine-display-indicator.service
journalctl --user -u sunshine-display-indicator.service -b
```

## CLI 与 SSH 救急

所有操作都在 `sunshine-displayctl` 一个命令里。它会自动设置 `XDG_RUNTIME_DIR`
和 GNOME 会话 D-Bus 地址，因此从 SSH 登录同一用户后可直接运行；除启动模式相关
命令外，GNOME 图形会话必须仍在运行。

```bash
sunshine-displayctl help
```

```text
状态    status  boot-status  verify
显示    physical-only  virtual-only  both
        physical-on  physical-off  virtual-on  virtual-off  recover
启动    boot-virtual  boot-default  boot-cancel
服务    sunshine-on  sunshine-off  sunshine-restart
自动化  auto-on  auto-off  stream-start  stream-stop
```

不带参数等同于 `status`，输出一行 JSON，供状态栏和脚本使用。`stream-start` 和
`stream-stop` 是 Sunshine 的会话钩子，不需要手动执行。

`recover` 会停止串流显示抑制、清除运行时会话状态，并强制恢复
`DP-1` 的 `1920x1080@165.001` SDR 输出。

## HDMI 端口限制

只在“虚拟显示器”启动项下，该 HDMI 端口才使用伪造的 AOC EDID 并始终被报告为
已连接。此时把真实显示器插入同一个 HDMI 端口，系统不会读取它的 EDID：兼容
4K60 时序的显示器可能仍能显示，但模式、HDR、音频能力和热插拔状态都可能不
正确，不应把该端口当作普通物理 HDMI 使用。DisplayPort 端口不受影响。

普通启动项没有这些参数，HDMI 端口行为完全正常，所以日常使用不需要卸载任何
东西——重启选普通条目即可。

彻底移除启动项和免密 sudo 规则（保留 EDID 固件）：

```bash
./root/remove-boot-entry
```

连 EDID 固件一起移除：

```bash
./root/remove-edid
```

`remove-edid` 会先调用 `remove-boot-entry`，只移除本项目添加的内容，不会覆盖
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

要同时移除启动项，运行 `./root/remove-boot-entry`；连 EDID 固件一起移除则运行
`./root/remove-edid`。

## 文件结构

```text
bin/          显示状态控制器
indicator/    GNOME AppIndicator 状态栏进程
systemd/      用户服务单元
root/         EDID、GRUB 启动项和登录界面配置的安装与移除工具，
              以及运行时的启动模式 helper
edid/         校验过的 4K60 HDR EDID
config/       Sunshine 配置片段和 GDM 登录界面显示配置
```
