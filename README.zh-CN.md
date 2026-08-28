# Sunshine Display Manager

*[English](README.md) | 简体中文*

为当前主机提供给 Sunshine 用的 4K60 虚拟显示器：GNOME Wayland、NVIDIA RTX
3080、GDM 50。

## 硬件映射

| 用途 | 内核连接器 | GNOME 连接器 | 模式 |
| --- | --- | --- | --- |
| 物理显示器 | `DP-1` | `DP-1` | `1920x1080@165.001`、SDR |
| 虚拟显示器 | `DP-3` 或 `HDMI-A-1` | `DP-3` 或 `HDMI-1` | `3840x2160@59.997`、200% 缩放 |

虚拟显示器由两套互相独立的机制构成，缺一不可：

- **EDID 注入**：内核参数
  `drm.edid_firmware=<连接器>:edid/sunshine-4k60-hdr.bin` 让该端口使用伪造的 4K60
  EDID。这件事只能在启动时完成，见[启动条目](#启动条目)。
- **连接器强制**：往 `/sys/class/drm/card*-<连接器>/status` 写 `on` 让内核报告该端口
  已连接，写 `detect` 交还。这一步是纯运行时的。

所以虚拟显示器在被要求之前根本不存在。

## 虚拟显示器端口

虚拟显示器落在两个端口之一，任何时刻只有一个端口挂着伪造的 EDID。端口只决定色彩
空间，别的什么都不决定：

| 端口 | 内核 / GNOME 连接器 | 色彩模式 | Sunshine 输出 | 代价 |
| --- | --- | --- | --- | --- |
| `dp`（默认） | `DP-3` / `DP-3` | `default` | 4K60 10-bit SDR | 无，`DP-3` 在这台机器上永远不插线 |
| `hdmi` | `HDMI-A-1` / `HDMI-1` | `bt2100` | 4K60 HDR10 | 只要启动虚拟条目，HDMI 口就一直挂着伪 EDID |

其余部分——分辨率、200% 缩放、双屏布局、自动化、greeter 处理——两种端口完全一致。
为什么只有 HDMI 能出 HDR 见[下文](#hdr-只在-hdmi-上成立)。

切换端口要改写 GRUB 条目的内核参数，因此会通过 polkit 交互请求密码，然后重启：

```bash
sunshine-displayctl port-status   # 当前使用的端口和下次启动使用的端口
sunshine-displayctl port-dp       # 切到 DP-3、SDR，并立即重启
sunshine-displayctl port-hdmi     # 切到 HDMI-A-1、HDR，并立即重启
```

状态栏里同样有这组切换（一对单选项）。选中的端口存在
`/etc/default/sunshine-display-manager`，生成的 GRUB 条目每次 `update-grub` 时读取
它；运行中的内核只认自己启动时的那个端口，所以切换必须重启。

## 控制逻辑

- 打开虚拟显示器：物理屏已开则进入双屏，否则进入仅虚拟屏。
- 关闭虚拟显示器：先确保物理屏开启，进入仅物理屏，并交还连接器。
- 打开物理显示器：虚拟屏已开则进入双屏，否则进入仅物理屏。
- 关闭物理显示器：先确保虚拟屏开启，再进入仅虚拟屏。
- 任何需要虚拟屏的操作都会先强制连接器，并等待内核和 mutter 两边都认账。
- 虚拟屏固定应用 `3840x2160@59.997` 和 200% 缩放，色彩模式由所在端口决定；物理屏
  保持 SDR。
- 每次拓扑切换都用 `/sys/class/drm/card*-*/enabled` 复核，因为 `gdctl` 报告的是
  mutter 接受了什么，不是驱动提交了什么。被驳回的提交视为错误，不会留下"一半
  生效"的状态。
- Moonlight 启动应用时，Sunshine 的 `global_prep_cmd` 接入虚拟屏、切换为仅虚拟屏，
  并抑制空闲与挂起。
- Sunshine 应用会话结束时**一律**回到仅物理屏并交还连接器，即使串流是从双屏开始的
  也一样。恢复双屏会把虚拟屏留在 mutter 里，而强制连接器的全部意义就是它只在有人
  串流时存在。
- 手工打开虚拟屏的菜单项仍然保留（调试用），它们是虚拟屏在串流之外出现的唯一途径。

这里的"连接"指 Moonlight 启动 Sunshine 应用并建立串流会话，不是客户端仅仅浏览
主机应用列表。

## 安装

```bash
./root/install-edid
./root/install-boot-entry
./install.sh
```

`install-edid` 安装 EDID 固件并写进 initramfs；`install-boot-entry` 生成 GRUB
条目、安装两个运行时 helper、只针对启动条目 helper 的免密 sudo 规则，以及端口
helper 的 polkit action；`install.sh` 安装用户级 CLI、状态栏和两个用户 unit。
EDID 在下一次启动时注入。

## 启动条目

EDID 参数不写进默认命令行，而是单独生成一个 GRUB 菜单项：

| 菜单项 | 内核参数 | 结果 |
| --- | --- | --- |
| `Ubuntu (virtual display)`（默认） | `drm.edid_firmware=<端口>:edid/sunshine-4k60-hdr.bin` | 选中的端口可随时被强制成 4K60 虚拟显示器 |
| `Ubuntu` | 无 | 选中的端口恢复普通端口行为，没有虚拟显示器 |

默认是虚拟条目：它注入的连接器在被要求之前始终断开，所以开机常驻没有代价；原版
条目留在菜单里，供该端口真的要当普通端口用时使用。

`/etc/grub.d/11_linux_sunshine` 用改过的参数和标题重新执行 `10_linux`，因此内核
升级后两套条目自动同步，不存在写死的内核路径。端口不写死在里面，而是从
`/etc/default/sunshine-display-manager` 读取——这正是[切换端口](#虚拟显示器端口)
只需要改一行加一次重启的原因。生成的菜单标识符统一加 `sunshine-` 前缀，与原版条目
区分。

注意参数里**没有** `video=<端口>:e`。那个参数会让连接器开机即被报告为已连接，登录
界面就会跑到虚拟屏上。去掉之后连接器完全由运行时控制；固件 EDID 会在连接器首次
运行时探测时加载，什么都没损失。

### 无人值守切换

`root/install-boot-entry` 会把 `GRUB_DEFAULT` 改为 `saved`（`GRUB_SAVEDEFAULT`
保持关闭，所以一次性选择永远不会变成永久默认），并安装
`/usr/local/sbin/sunshine-boot-mode` 和一条只允许该命令的 sudo 规则。于是远程 SSH
也能在看不到 GRUB 菜单的情况下切换条目：

```bash
sunshine-displayctl boot-status    # 当前启动条目和已排队的下次启动
sunshine-displayctl boot-virtual   # 下次启动用虚拟条目并立即重启
sunshine-displayctl boot-stock     # 下次启动用原版条目并立即重启
sunshine-displayctl boot-cancel    # 只清除排队，不重启
```

排队只影响下一次启动。排队状态镜像在 `/run/sunshine-display-boot-pending`，状态栏
因此可以直接轮询而不需要 root。

由于虚拟屏是运行时开关，日常串流不需要重启——只有真的要把注入的端口交还给普通用途，
或者要把虚拟屏挪到另一个端口时才需要。

### 原版条目下的行为

没有注入 EDID 时，强制打开连接器只会得到一块没有模式信息的输出，因此 helper 直接
拒绝：

- 状态栏里虚拟显示器、双屏、仅虚拟三项置灰，标题显示"虚拟不可用"。
- `virtual-only`、`both`、`virtual-on`、`physical-off` 直接报错退出。
- Moonlight 连接时不再切换拓扑，串流照常进行，只是串的是物理屏；空闲和挂起抑制
  仍然生效。

## 登录界面

虚拟显示器只在登录之后存在，所以 GDM 的 greeter 永远只看到物理屏，不需要任何
greeter 配置。`sunshine-virtual-connector.service` 在图形会话启动和结束时各执行
一次 `detach`，保证注销回到登录界面时连接器已经交还。

GDM 50 起 greeter 以动态用户 `gdm-greeter` 运行，家目录是 tmpfs 上的
`/run/gdm3/home/gdm-greeter`，每次开机重建，`/var/lib/gdm3/.config/monitors.xml`
不再会被读取。在这个 GDM 上 greeter 配置是条死路，这也是改用运行时连接器开关的
原因之一。清理早期版本留下的文件：

```bash
./root/remove-greeter-config
```

## 状态栏

`sunshine-display-indicator.service` 随 GNOME 会话启动。菜单提供：

- 分别开关物理和虚拟显示器
- 直接选择仅物理、仅虚拟或双屏
- 开关"串流时自动关闭物理显示器"
- 显示当前启动条目，并重启切换到虚拟条目或原版条目（带确认对话框）
- 取消已排队但尚未生效的启动条目
- 在 `DP-3 (SDR)` 和 `HDMI (HDR)` 之间切换虚拟屏所在端口（带确认对话框和 polkit
  密码框）
- 启停 Sunshine 服务
- 打开 Sunshine Web 管理页面
- 强制恢复物理显示器

查看服务日志：

```bash
systemctl --user status sunshine-display-indicator.service
journalctl --user -u sunshine-display-indicator.service -b
```

## CLI

所有操作都在 `sunshine-displayctl` 一个命令里。它会自行设置 `XDG_RUNTIME_DIR` 和
GNOME 会话总线地址，因此以桌面用户身份 SSH 登录后可直接运行；除启动条目相关命令
外，GNOME 会话必须仍在运行。

```bash
sunshine-displayctl help
```

```text
状态    status  boot-status  port-status  verify
显示    physical-only  virtual-only  both
        physical-on  physical-off  virtual-on  virtual-off  recover
连接器  attach  detach
启动    boot-virtual  boot-stock  boot-cancel
端口    port-dp  port-hdmi
服务    sunshine-on  sunshine-off  sunshine-restart
自动化  auto-on  auto-off  stream-start  stream-stop
```

不带参数时输出一行 JSON，供状态栏和脚本使用。`stream-start` 和 `stream-stop` 是
Sunshine 的会话钩子，`attach` 和 `detach` 是连接器钩子，都不需要手动执行。

`recover` 会停止串流抑制器、清除运行时会话状态、交还虚拟连接器，并强制把 `DP-1`
恢复到 `1920x1080@165.001` SDR。

`port-dp` 和 `port-hdmi` 是唯二会要密码的命令：在终端里走 `sudo`，从状态栏调用时走
`pkexec`。其余命令要么不需要权限，要么走免密的
`/usr/local/sbin/sunshine-boot-mode`。

## HDR 只在 HDMI 上成立

`DP-3` 是这台机器上永远不会插线的端口，本来是伪造 EDID 最自然的落点，还能把 HDMI
口留给真实显示器。但它带不动 HDR。Mutter 接受它切到 `bt2100`，GNOME 里的 HDR 开关
也能打开，但 DRM 连接器的 `HDR_OUTPUT_METADATA` 和 `Colorspace` 属性仍然是 0，
Sunshine 的 KMS 捕获因此把这块输出判定为 SDR，编码出来的是 10-bit SDR 而不是 HDR10。
DisplayPort 上的 HDR 需要驱动从 sink 的 DPCD 里读能力位，伪造的 EDID 造不出可读的
链路。

HDMI 是单向 TMDS：HDR InfoFrame 不需要握手就直接发出去，所以强制的连接器在那边确实
能带 HDR——代价是这个口。完整探索过程、旧环境结果、Sunshine 源码判定和两种潜在实现
路线见 [DP-3 HDR 调查记录](docs/dp-hdr-investigation.zh-CN.md)。

Sunshine 抓的是它找到的第一块处于活动状态的输出。物理屏是唯一活动输出时它记录
`Found connector ID [825]`（`DP-1`），虚拟屏是唯一活动输出时记录
`Found connector ID [833]`（`DP-3`）。这就是串流时要切到仅虚拟屏而不是双屏的原因。

## 端口限制

在虚拟条目下，选中的端口始终使用伪造的 AOC EDID。把真实显示器插进这个口，系统不会
读它自己的 EDID：能容忍 4K60 时序的显示器也许还能亮，但模式、HDR、音频能力和热
插拔状态都是错的。要正常使用这个口，重启选原版条目、或者把虚拟屏挪到另一个端口即可，
不必卸载任何东西。除选中的那个口以外，其余端口完全不受影响。

只移除启动项和 sudo 规则、保留 EDID 固件：

```bash
./root/remove-boot-entry
```

连 EDID 固件一起移除：

```bash
./root/remove-edid
```

`remove-edid` 会先调用 `remove-boot-entry`。两者都只移除本项目添加的内容，不会
覆盖之后对 GRUB 做的其他修改。

## 为什么 EDID 必须在启动时注入

这台机器开着 Secure Boot，内核处于 `integrity` lockdown。实测结论：

- `/sys/module/drm/parameters/edid_firmware` 虽然可写，但 EDID 在连接器首次探测时
  就被装成连接器级 override 并保留到连接器生命周期结束，之后再改这个参数无效。
- DRM 唯一的运行时注入接口 `/sys/kernel/debug/dri/*/<连接器>/edid_override`，在
  lockdown 下任何写方式的打开都返回 `EPERM`。lockdown 只能升级不能降级，只有在
  固件里关掉 Secure Boot 才能解除。
- `nvidia`、`nvidia_modeset`、`nvidia_drm` 三个模块都没有 EDID 相关参数，
  `CustomEDID` 只存在于 X11。

连接器强制不受 lockdown 限制，所以最终形态是：EDID 启动时注入一次，连接器运行时
随用随开。

## 卸载

只移除状态栏、CLI 和 Sunshine 会话钩子：

```bash
./uninstall.sh
```

再加 `./root/remove-boot-entry` 可移除启动项，`./root/remove-edid` 连 EDID 固件
一起移除。早期版本装过的 greeter 配置用 `./root/remove-greeter-config` 清理。

## 文件结构

```text
bin/          显示状态控制器
indicator/    GNOME AppIndicator 状态栏进程
systemd/      用户服务单元
root/         EDID 和 GRUB 启动项的安装/移除工具，以及运行时的启动条目、
              连接器和虚拟屏端口 helper
polkit/       端口 helper 的 polkit action
edid/         校验过的 4K60 EDID
config/       Sunshine 配置片段
```
