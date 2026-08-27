# Sunshine Display Manager

*[English](README.md) | 简体中文*

为当前主机提供给 Sunshine 用的 4K60 虚拟显示器：GNOME Wayland、NVIDIA RTX
3080、GDM 50。

## 硬件映射

| 用途 | 内核连接器 | GNOME 连接器 | 模式 |
| --- | --- | --- | --- |
| 物理显示器 | `DP-1` | `DP-1` | `1920x1080@165.001`、SDR |
| 虚拟显示器 | `DP-3` | `DP-3` | `3840x2160@59.997`、SDR |

虚拟显示器由两套互相独立的机制构成，缺一不可：

- **EDID 注入**：内核参数
  `drm.edid_firmware=DP-3:edid/sunshine-4k60-hdr.bin` 让该端口使用伪造的 4K60
  EDID。这件事只能在启动时完成，见[启动条目](#启动条目)。
- **连接器强制**：往 `/sys/class/drm/card*-DP-3/status` 写 `on` 让内核报告该端口
  已连接，写 `detect` 交还。这一步是纯运行时的。

所以虚拟显示器在被要求之前根本不存在。

`DP-3` 是这台机器上永远不会插线的端口，用它可以把 HDMI 口留给真实显示器。代价是
HDR：被强制连接的 DisplayPort 端口带不动 HDR，见[无 sink 的 DisplayPort
连接器能做什么、不能做什么](#无-sink-的-displayport-连接器能做什么不能做什么)。
`hdmi-hdr` 分支用 HDMI 口换 HDR。

## 控制逻辑

- 打开虚拟显示器：物理屏已开则进入双屏，否则进入仅虚拟屏。
- 关闭虚拟显示器：先确保物理屏开启，进入仅物理屏，并交还连接器。
- 打开物理显示器：虚拟屏已开则进入双屏，否则进入仅物理屏。
- 关闭物理显示器：先确保虚拟屏开启，再进入仅虚拟屏。
- 任何需要虚拟屏的操作都会先强制连接器，并等待内核和 mutter 两边都认账。
- 每次拓扑切换都用 `/sys/class/drm/card*-*/enabled` 复核，因为 `gdctl` 报告的是
  mutter 接受了什么，不是驱动提交了什么。被驳回的提交视为错误，不会留下"一半
  生效"的状态。
- Moonlight 启动应用时，Sunshine 的 `global_prep_cmd` 记录当前拓扑。自动控制开启
  时接入虚拟屏、切换为仅虚拟屏，并抑制空闲与挂起。
- Sunshine 应用会话结束时恢复此前拓扑；如果不再需要虚拟屏，连接器一并交还。
- 串流期间手动切换会设置"人工覆盖"，断开时不再恢复旧拓扑。

这里的"连接"指 Moonlight 启动 Sunshine 应用并建立串流会话，不是客户端仅仅浏览
主机应用列表。

## 安装

```bash
./root/install-edid
./root/install-boot-entry
./install.sh
```

`install-edid` 安装 EDID 固件并写进 initramfs；`install-boot-entry` 生成 GRUB
条目、安装运行时 helper 和只针对它的免密 sudo 规则；`install.sh` 安装用户级
CLI、状态栏和两个用户 unit。EDID 在下一次启动时注入。

## 启动条目

EDID 参数不写进默认命令行，而是单独生成一个 GRUB 菜单项：

| 菜单项 | 内核参数 | 结果 |
| --- | --- | --- |
| `Ubuntu (virtual display)`（默认） | `drm.edid_firmware=DP-3:edid/sunshine-4k60-hdr.bin` | `DP-3` 可随时被强制成 4K60 虚拟显示器 |
| `Ubuntu` | 无 | `DP-3` 恢复普通端口行为，没有虚拟显示器 |

默认是虚拟条目：它注入的连接器在被要求之前始终断开，所以开机常驻没有代价；原版
条目留在菜单里，供 `DP-3` 真的要当普通端口用时使用。

`/etc/grub.d/11_linux_sunshine` 用改过的参数和标题重新执行 `10_linux`，因此内核
升级后两套条目自动同步，不存在写死的内核路径；生成的菜单标识符统一加 `sunshine-`
前缀，与原版条目区分。

注意参数里**没有** `video=DP-3:e`。那个参数会让连接器开机即被报告为已连接，登录
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

由于虚拟屏是运行时开关，日常串流不需要重启——只有真的要把 `DP-3` 交还给普通用途
时才需要。

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
状态    status  boot-status  verify
显示    physical-only  virtual-only  both
        physical-on  physical-off  virtual-on  virtual-off  recover
连接器  attach  detach
启动    boot-virtual  boot-stock  boot-cancel
服务    sunshine-on  sunshine-off  sunshine-restart
自动化  auto-on  auto-off  stream-start  stream-stop
```

不带参数时输出一行 JSON，供状态栏和脚本使用。`stream-start` 和 `stream-stop` 是
Sunshine 的会话钩子，`attach` 和 `detach` 是连接器钩子，都不需要手动执行。

`recover` 会停止串流抑制器、清除运行时会话状态、交还虚拟连接器，并强制把 `DP-1`
恢复到 `1920x1080@165.001` SDR。

## 无 sink 的 DisplayPort 连接器能做什么、不能做什么

在这台机器上实测，状态从 DRM 读回，而不是看 `gdctl` 的退出码——后者只说明 mutter
是否接受了请求：

| 拓扑 | 模式 | 色彩模式 | 结果 |
| --- | --- | --- | --- |
| 双屏 | `800x600@60.317` | SDR | 生效 |
| 双屏 | `1920x1080@60.000` | SDR | 生效 |
| 双屏 | `3840x2160@29.970` | SDR | 生效 |
| 双屏 | `3840x2160@59.997` | SDR | 生效，3/3 |
| 双屏 | `3840x2160@59.997` | `sdr-native` | 生效 |
| 仅虚拟 | `3840x2160@59.997` | SDR | 生效，2/2 |
| 双屏 | `1920x1080@60.000` | `bt2100` | 被驳回 |
| 双屏 | `3840x2160@29.970` | `bt2100` | 被驳回 |
| 双屏 | `3840x2160@59.997` | `bt2100` | 被驳回，3/3 |
| 仅虚拟 | `3840x2160@59.997` | `bt2100` | 被驳回 |

被驳回长这样：`gdctl` 退出码 0，mutter 显示新布局，
`/sys/class/drm/card1-DP-3/enabled` 停在 `disabled`，连接器一个 CRTC 都拿不到，
gnome-shell 以每秒约三十次的频率刷

```text
Page flip failed: drmModeAtomicCommit: Invalid argument
```

直到布局被改回去。

所以瓶颈不是带宽——`1920x1080@60` 开 HDR 会失败，而 `3840x2160@60` 走 SDR 能成。
DisplayPort 上的 HDR 需要驱动从 sink 的 DPCD 里读能力位，伪造的 EDID 造不出可读
的链路。HDMI 是单向 TMDS，HDR InfoFrame 不需要握手直接发出去，所以 `hdmi-hdr`
分支能拿到 HDR，代价是 HDMI 口。

Sunshine 抓的是它找到的第一块处于活动状态的输出。物理屏是唯一活动输出时它记录
`Found connector ID [825]`（`DP-1`），虚拟屏是唯一活动输出时记录
`Found connector ID [833]`（`DP-3`）。这就是串流时要切到仅虚拟屏而不是双屏的原因。

## 端口限制

在虚拟条目下，`DP-3` 始终使用伪造的 AOC EDID。把真实显示器插进这个口，系统不会
读它自己的 EDID：能容忍 4K60 时序的显示器也许还能亮，但模式、HDR、音频能力和热
插拔状态都是错的。要正常使用这个口，重启选原版条目即可，不必卸载任何东西。
`DP-1`、`DP-2` 和 HDMI 完全不受影响。

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
- DRM 唯一的运行时注入接口 `/sys/kernel/debug/dri/*/DP-3/edid_override`，在
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
root/         EDID 和 GRUB 启动项的安装/移除工具，
              以及运行时的启动条目与连接器 helper
edid/         校验过的 4K60 EDID
config/       Sunshine 配置片段
```

## 分支

- `main`——虚拟显示器在 `DP-3`，4K60 SDR，HDMI 口保持空闲。
- `hdmi-hdr`——虚拟显示器在 `HDMI-A-1`，4K60 HDR，代价是只要启动虚拟条目，HDMI 口
  就一直挂着伪造的 EDID。
