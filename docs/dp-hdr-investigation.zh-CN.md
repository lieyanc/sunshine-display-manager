# DP-3 HDR 调查记录

本文记录在无真实 sink 的强制 `DP-3` 上探索 HDR 的过程、观测证据、Sunshine 的判定
机制、尝试过的实现方向，以及最终回退到 SDR 的原因。

## 最终结论

当前软件栈允许 GNOME/Mutter 把 `DP-3` 的 `color-mode` 设置成 `bt2100`，但这不等同于
一条可供 Sunshine 使用的端到端 HDR10 链路。DP-3 的 DRM connector 没有非零的
`HDR_OUTPUT_METADATA`，`Colorspace` 也仍为默认值。Sunshine 的 Linux KMS 捕获因此
将显示器判断为 SDR，最终生成的是 **10-bit SDR**，不是 HDR10。

项目据此继续把强制 `DP-3` 定义为不支持 HDR：

- `DP-3`：`3840x2160@59.997`、SDR、200% 缩放；
- `DP-1`：`1920x1080@165.001`、SDR；
- 需要 HDR 时切到 `hdmi` 端口模式（`sunshine-displayctl port-hdmi`），或以后重新
  验证本文列出的替代方案。

## 测试环境

调查日期：2026-08-28。

| 组件 | 版本 |
| --- | --- |
| 内核 | `7.0.0-30-generic` |
| GNOME Shell | `50.1` |
| Mutter | `50.1-0ubuntu2.2` |
| GPU | NVIDIA GeForce RTX 3080 |
| NVIDIA 驱动 | `610.43.02` |
| Sunshine | `2026.516.143833` |
| Sunshine commit | `14ffa6fdaa53f7b51512be2b3d24f3939695403c` |
| 捕获/编码 | KMS / NVENC |

虚拟显示器使用启动参数：

```text
drm.edid_firmware=DP-3:edid/sunshine-4k60-hdr.bin
```

登录后再向 `/sys/class/drm/card*-DP-3/status` 写 `on`，使连接器在运行时出现。

## 探索过程

### 1. 较早软件栈：BT.2100 atomic commit 被拒绝

早期测试中，`gdctl` 返回成功、Mutter 也显示新布局，但 NVIDIA DRM 没有实际启用
DP-3。`/sys/class/drm/card1-DP-3/enabled` 保持 `disabled`，gnome-shell 持续记录：

```text
Page flip failed: drmModeAtomicCommit: Invalid argument
```

当时的矩阵如下：

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

这也是控制器一直通过 `/sys/class/drm/card*-*/enabled` 复核拓扑，而不只相信
`gdctl` 退出码的原因。

### 2. 当前软件栈：Mutter 可以设置 BT.2100

升级后的环境中，以下配置能通过 Mutter 验证并实际保持 DP-3 enabled：

```bash
gdctl set --layout-mode logical \
  --logical-monitor --primary --scale 2 --x 0 --y 0 \
  --monitor DP-3 --mode 3840x2160@59.997 \
  --color-mode bt2100 --rgb-range auto
```

`gdctl show --properties` 随后报告：

```text
DP-3 current mode = 3840x2160@59.997
DP-3 color-mode   = bt2100
logical scale     = 2.0
```

这说明 Mutter 的显示配置层已经接受 HDR 模式，也解释了 GNOME 设置中的 HDR 开关
为何可以打开。但它只证明 compositor 状态，不证明 DRM connector 已带 HDR10 元数据。

### 3. Moonlight 已请求 HDR，Sunshine 仍选择 SDR

Moonlight 建立会话后，Sunshine 找到的唯一活动输出和编码器均正确：

```text
Monitor 0 is DP-3: AOC 32"
Found connector ID [833]
Creating encoder [hevc_nvenc]
Color coding: SDR (Rec. 601)
Color depth: 10-bit
Color range: MPEG
```

`Color depth: 10-bit` 很关键。Sunshine 从 Moonlight 的 RTSP 参数
`x-nv-video[0].dynamicRangeMode` 读取客户端动态范围；值为 1 时选择 10-bit。因此客户端
已经请求了 HDR/Main10，问题不在 Moonlight HDR 开关或 NVENC 能力。

同时出现“10-bit”和“SDR”说明 Sunshine 收到了客户端 HDR 请求，但捕获端的
`display.is_hdr()` 返回了 false。

### 4. DRM connector 缺少 HDR 元数据

通过 libdrm 直接读取 Sunshine 记录的 connector 833，得到：

```text
connector_id=833
connection=connected
link-status=0
Colorspace=0
HDR_OUTPUT_METADATA=0
Broadcast RGB=<missing>
max bpc=<missing>
```

因此 GNOME/Mutter 的 `bt2100` 状态并未转化为 Sunshine 所依赖的 DRM HDR metadata
blob。这是当前无法形成 HDR 串流的直接原因。

## Sunshine 为什么降级成 SDR

当前 Sunshine 在
[`src/video_colorspace.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/video_colorspace.cpp)
中使用以下逻辑：

```cpp
if (config.dynamicRange > 0 && hdr_display) {
    colorspace.colorspace = colorspace_e::bt2020;
} else {
    // SDR
}
```

其中：

- `config.dynamicRange > 0` 来自 Moonlight，本次已经为真；
- `hdr_display` 来自 KMS capture 的 `disp.is_hdr()`。

Linux KMS 实现在
[`src/platform/linux/kmsgrab.cpp`](https://github.com/LizardByte/Sunshine/blob/14ffa6fdaa53f7b51512be2b3d24f3939695403c/src/platform/linux/kmsgrab.cpp)
中读取 connector 的 `HDR_OUTPUT_METADATA`。属性不存在或值为 0 时，`is_hdr()` 直接
返回 false。只有 metadata blob 中 EOTF 为 SMPTE ST 2084/PQ 等 HDR 类型时，Sunshine
才输出：

```text
Color coding: HDR (Rec. 2020 + SMPTE 2084 PQ)
```

所以仅把控制器的 `--color-mode` 改成 `bt2100` 不足以开启 Sunshine HDR。

## 伪造 EDID 中可用的 HDR 数据

当前 EDID 的 CTA HDR Static Metadata Data Block 声明：

- 支持传统 SDR、传统 HDR 和 SMPTE ST 2084/PQ；
- Static Metadata Type 1；
- 期望峰值亮度约 604 nit；
- 期望全屏亮度约 351 nit；
- 期望最低亮度约 0.0491 nit。

从 EDID 色度坐标换算到 Moonlight `SS_HDR_METADATA` 的 50000 归一化单位后为：

```text
R = (33984, 15674)
G = (13379, 34229)
B = ( 7568,  2734)
W = (15674, 16455)
maxDisplayLuminance = 604
minDisplayLuminance = 491  # 单位为 0.0001 nit
maxFullFrameLuminance = 351
```

这些数据可用于 Sunshine fallback 实验，但 EDID 能声明能力并不代表无 sink 的 DP
链路真的完成了 AUX/DPCD 协商或提交了 HDR metadata。

## 探索过的两条实现路线

### 路线 A：Sunshine KMS fallback

在 Sunshine 的 `kmsgrab.cpp` 中增加一个显式、仅针对 DP-3 的选项：

1. 原生 `HDR_OUTPUT_METADATA` 非零时继续使用现有逻辑；
2. 只有捕获输出是 DP-3、用户显式启用 fallback 且原生 metadata 为 0 时，
   `is_hdr()` 才回退为 true；
3. `get_hdr_metadata()` 使用上面的 EDID 数据填充 `SS_HDR_METADATA`；
4. 通过 systemd 环境变量或 Sunshine 配置开启，避免影响真实显示器。

这会让 Sunshine 选择 BT.2020/PQ 和 HEVC Main10，但存在重要风险：如果 Mutter 的扫描
缓冲区并不是真正的 PQ HDR 内容，强制按 HDR10 编码会产生灰雾、过曝或饱和度错误。
因此这是一种实验性绕过，不足以证明链路正确，没有采用。

### 路线 B：Mutter/NVIDIA 正确提交 DRM metadata

长期正确方案是在 Mutter 选择 `bt2100` 时，让 native KMS atomic update 同时提交：

```text
HDR_OUTPUT_METADATA = 非零 hdr_output_metadata blob
Colorspace          = BT2020_RGB（或驱动对应枚举）
输出位深             = 10 bpc
```

Mutter 可以从 EDID CTA block 构造 `struct hdr_output_metadata`。如果 Mutter 已提交而
NVIDIA 驱动仍把属性保持为 0，则需要 NVIDIA 修复；专有驱动无法由本项目直接修改。
由于 Mutter 持有 DRM master，`gdctl` 或普通 Bash 脚本也不能绕过 compositor 直接写
connector property。

无真实 DisplayPort sink 还意味着没有 AUX/DPCD 响应。驱动可能有意拒绝或丢弃 HDR
metadata。此时软件之外的方案是使用能模拟完整 AUX/DPCD 的 DisplayPort dummy/emulator，
而不只是注入 EDID。

## 回退决定

本次探索结束后，控制器恢复到「`DP-3` 用 SDR」：`dp` 端口模式的色彩模式是
`default`，缩放保持独立验证过的 200%。两个端口模式的差异因此只剩连接器和色彩空间：

| 端口模式 | 连接器 | `--color-mode` | 缩放 |
| --- | --- | --- | --- |
| `dp` | `DP-3` | `default` | 2 |
| `hdmi` | `HDMI-A-1` | `bt2100` | 2 |

文档继续明确 `DP-3` 不支持 Sunshine 端到端 HDR，避免把 GNOME 设置中的 HDR 开关
误认为串流已经进入 HDR10。

## 将来重新打开结论的条件

只有同时满足以下条件，才应把 `dp` 端口模式也改成 HDR：

1. `gdctl show --properties` 显示 DP-3 为 `bt2100`；
2. DP-3 的 `HDR_OUTPUT_METADATA` 为非零 metadata blob；
3. DRM `Colorspace` 为 BT.2020 对应值；
4. Sunshine 日志显示 `HDR (Rec. 2020 + SMPTE 2084 PQ)` 和 10-bit；
5. Moonlight 客户端报告 HDR，会话中的 HDR 测试图和实际内容没有灰雾、剪裁或错误
   tone mapping；
6. 串流开始、断开恢复、双屏和仅虚拟三种拓扑均经过 DRM 实际状态复核。
