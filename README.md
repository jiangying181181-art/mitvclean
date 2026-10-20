# mitvclean

[![MIT License](https://img.shields.io/badge/许可-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![零依赖](https://img.shields.io/badge/依赖-0-brightgreen.svg)](pyproject.toml)
[![测试](https://img.shields.io/badge/测试-17%2B5%20通过-success.svg)](tests/)
[![实机验证](https://img.shields.io/badge/实机-MiTV--ANSP0%20已验证-brightgreen.svg)](profiles/mitv-ansp0/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**小米电视去臃肿与去广告工具** —— 纯 Python 3.9+，零第三方依赖，不装 adb 也能用。

只做**可逆**操作：所有改动都是 `pm disable-user`（禁用，不是卸载），动手前先落盘记录每个包的原始状态，一条命令就能还原。

```
mitvclean info      # 看这台电视的型号 / 系统 / 内存 / 包统计
mitvclean doctor    # 体检：现状 + 可优化点 + 广告开关值
mitvclean scan      # 从真机提取广告域名，生成 hosts 清单
mitvclean debloat   # 按机型画像禁用后台包
mitvclean restore   # 一键还原
```

---

## 为什么做这个

小米电视预装一堆常驻后台：数据上报、云端推送、PatchWall 网页内容、购物频道插件、"电视管家"清理器。
在 2GB 内存的机器上，这些后台吃掉的内存很可观，表现为**操作迟钝、画面不跟手**。

广告是另一回事，也更麻烦：

- **开机广告**有时是系统属性控制的，有时是独立包，有时是服务端下发
- **播放前贴片广告**（时长 30/36/120 秒不等）由**视频内容源**动态下发，域名会变

所以这个工具不是"一份黑名单脚本"，而是一套**分层处理 + 可验证**的方法：

| 层 | 手段 | 可逆性 |
|---|---|---|
| 1 | 系统设置里的广告开关 | 改回原值即可 |
| 2 | 禁用广告相关包 | `pm enable` 还原 |
| 3 | 路由器 hosts / DNS 拦截 | 删掉条目即可 |

---

## 安装

```bash
git clone https://github.com/<你的账号>/mitvclean.git
cd mitvclean
pip install -e .
```

不需要 Android SDK，不需要 platform-tools，不需要 adb 二进制。
（可选：装 `cryptography` 能让 ADB 认证快很多，`pip install -e ".[crypto]"`）

### Windows 用户：双击就行

```
mitvclean.bat
```

它会自动找 Python、装依赖、然后进入交互式菜单。不需要敲命令。

### 不想装东西？

直接用 `python -m mitvclean.cli` 也可以，只要 Python 3.9+ 在 PATH 上。

---

## 快速上手（三条命令）

```bash
mitvclean --host 192.168.1.50 info      # 看看认不认得这台电视
mitvclean --host 192.168.1.50 doctor    # 体检：有什么能优化的
mitvclean --host 192.168.1.50 debloat   # 瘦身（可逆）
```

---

## 使用

### 1. 电视上打开 ADB 调试

```
设置 → 账号与安全 → ADB 调试 → 允许
```

找不到这个选项？先在 `设置 → 关于本机 → 版本号` 连按 7 次开开发者模式。

首次连接电视会弹「允许 USB 调试吗？」，**点允许**。

> ⚠️ 国行小米电视每次重启后网络 ADB 会自动关闭，需要重新打开。
> 用完建议关掉（5555 端口是明文的）。

### 2. 找 IP 并连接

```bash
mitvclean --host 192.168.1.50 info
```

也可以用环境变量 `MITV_HOST`，或 `--host` 传参。

### 3. 体检

```bash
mitvclean --host 192.168.1.50 doctor
```

输出：设备信息、内存占用、settings 里的广告相关开关、当前启用的可优化包、sdcard 上的广告缓存。

### 4. 去臃肿

```bash
# 先看要动什么（不动手）
mitvclean --host 192.168.1.50 debloat --dry-run

# 确认后执行
mitvclean --host 192.168.1.50 debloat
```

执行时会：
1. 读取每个包的原始状态 → 落盘到 `work/state-<时间戳>.json`
2. 逐个 `pm disable-user`
3. 复查确认

### 5. 去广告

```bash
# 读/写系统里的广告开关
mitvclean --host 192.168.1.50 adswitch
mitvclean --host 192.168.1.50 adswitch --set system.boot_ad=0

# 清广告缓存（含 sdcard 上已下载的广告视频）
mitvclean --host 192.168.1.50 cache

# 提取广告域名，生成 hosts 清单
mitvclean --host 192.168.1.50 scan
```

`scan` 的产物：
- `work/hosts-scan.txt` —— 粘到路由器的「自定义 Hosts」
- `work/domains.json` —— 分类明细（广告域 / 内容源域 / 其他）

#### 往路由器贴 hosts：按组来，别一次全上

清单里 73 条域名分 3 组，**副作用从小到大**。建议分三步：

```bash
# ① 先出第 1 组（纯广告域，拦了没副作用）—— 开机广告、贴片广告就靠这一组
mitvclean hosts --profile mitv-ansp0 --group 1 --out work

# ② 断掉贴片广告后，再加第 2 组（内容源域）—— 有代价，见下
mitvclean hosts --profile mitv-ansp0 --group 2 --out work

# ③ 想要一份全量（不推荐直接用）
mitvclean hosts --profile mitv-ansp0 --group all --out work
```

**粘贴位置**：米家 App → 路由器 → 工具箱 → 自定义 Hosts（网页版没有这个功能）。
**格式是 IP 在前**（`127.0.0.1 域名`），和小米路由器要求一致，和标准 hosts 相反。

> ⚠️ 第 2 组是内容源域名，拦掉后**对应 App 会打不开**。
> 哪个 App 不出画了，就从清单里删掉那一条，不用整套回退。
> 每次只加几条、试一次，比一次贴 73 条省事得多。

### 6. 还原

```bash
mitvclean --host 192.168.1.50 restore
```

只恢复**记录里原本是启用状态**的包。你自己之前关掉的东西不会被误开。

---

## 提取广告域名：为什么要两条腿

这是本项目最值得说的一部分。

**只静态分析 APK 会漏。** 广告下发地址常是服务端配置——APK 里只有 `film_ad_online_server`
这样的**键名**，值是服务端给的。静态扫出来的是硬编码域名，不是真实广告通道。

**只抓 logcat 也不够。** 有些域名只在特定功能触发时才出现。

所以 `scan` 两条腿一起走：

| 腿 | 做法 | 能拿到什么 |
|---|---|---|
| 静态 | `adb pull` 出 `/data/app` 下的 APK → zipfile 逐条目扫 `.dex/.arsc/.xml/.so` | 硬编码的域名、模块名（`FilmAdBean`、`InternalFrontAdCtlManager`…）|
| 动态 | `adb shell logcat -d` → 正则提域名 | **服务端下发的真实域名**（配置接口返回的 JSON 里）|

实测过的例子：某台小米电视的贴片广告素材 CDN 是
`cp-ppvideo.cdn.ptmi.gitv.tv` 这类 `cp-` 前缀的域名，**只在 logcat 里出现过**，静态扫 APK 根本找不到。

> 拉 APK 只能拉 `/data/app` 下的（用户安装的应用）。系统应用在 `/system/app`，
> shell 读不到 base.apk —— 但系统应用通常也不是广告主，够用。

---

## 机型画像（profiles）

不同型号的电视，能禁的包和要拦的域名都不一样。所以数据与代码分离：

```
profiles/
  mitv-ansp0/
    profile.json    # 元信息：型号、代号、系统版本、实测注意事项
    debloat.txt     # 去臃肿包清单
    hosts.txt       # 广告拦截域名清单
```

**加新机型不用改代码**，复制一个目录改内容即可：

```bash
mitvclean --host <ip> info        # 记下 ro.product.model / ro.product.device
mkdir -p profiles/mitv-xxxx
# 写 profile.json / debloat.txt / hosts.txt
mitvclean --host <ip> profiles    # 确认被识别
```

`debloat.txt` 支持分组注释，被验证过"不能禁"的包（桌面、系统设置、平台输入服务等）
应该写在注释里说明原因，避免别人误加。

`hosts.txt` 一行一个域名，工具会补成 `127.0.0.1 <域名>`。

> **小米路由器的 hosts 格式是 IP 在前**（`127.0.0.1 域名`），和标准 hosts 相反。
> 入口在**米家 App → 路由器 → 工具箱 → 自定义 Hosts**（网页版没有这个功能）。

---

## 安全设计

| 风险 | 处理 |
|---|---|
| 误删应用 | 只用 `pm disable-user`，**永不 uninstall** |
| 还原时误开用户自己关的包 | 动手前落盘记录状态，还原只恢复原本 enabled 的 |
| 清单被当成 shell 片段执行 | 包名必须匹配 `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$`，否则整份清单拒绝执行 |
| 记录文件写一半 | 先写 `.tmp` 再原子替换 |
| 一条命令链式执行被静默中断 | 逐条下发命令（部分国产 ROM 的 shell 会吞掉分号后的语句）|
| 改到桌面进不去 | 工具本身不碰 `com.mitv.tvhome`；画像里明确列出不能禁的包 |

---

## 兼容性

| 项 | 情况 |
|---|---|
| 已实机验证 | `MiTV-ANSP0`（L65M5-ES，小米全面屏电视 Pro E65S，Android 9）|
| 原理通用 | 所有 Android TV（小米/红米/其他国产品牌）——画像不同而已 |
| 已知不适用 | Tizen（Samsung）、webOS（LG）、Fire OS（Amazon）—— 不是 Android |
| 需 root？ | 不需要 |

---

## 开发

```bash
python tests/test_offline.py        # 离线测试，不连设备
python tests/test_adb_protocol.py   # 协议测试，用假 adbd 验证协议实现
python -m mitvclean.cli --help
```

测试覆盖：清单解析（注释/BOM/去重）、包名校验（防注入）、状态查询与禁用、还原的对称性、
dry-run 不动手、域名分类、logcat 提取、画像加载，以及 ADB 协议实现
（握手/开流/读写/认证，用本地假 adbd 验证，不需要真电视）。

> 实现 ADB 客户端踩过的坑都记在 [docs/ADB协议实现笔记.md](docs/ADB协议实现笔记.md)，
> 里面的结论全部来自抓包实测（网上很多说法是错的）。

---

## 相关项目

- [cleanyourtv](https://github.com/Gathin23/cleanyourtv) —— 覆盖 93 台电视的清单与 launcher，
  本项目的思路（可逆禁用 + fail-safe）受其启发
- [MiTVNoAd](https://github.com/MiharaKinu/MiTVNoAd) —— 小米电视去广告工具

## 许可

MIT
