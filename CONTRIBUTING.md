# 贡献指南

## 加一个新机型画像

这是本项目最常见的贡献方式。**不需要改任何代码。**

### 1. 收集信息

```bash
mitvclean --host <电视IP> info
```

记下 `ro.product.model`（如 `MiTV-ANSP0`）、`ro.product.device`、系统版本、平台。

### 2. 建目录

```bash
mkdir -p profiles/mitv-xxxx
```

目录名（slug）用小写设备代号，短横线分隔：`mitv-ansp0`、`redmi-tv-a55`。

### 3. 写 profile.json

```json
{
  "title": "小米电视 A55 2023",
  "model": "L55A3",
  "device": "MiTV-XXXXX",
  "android": "Android 11 (SDK 30)",
  "firmware": "3.0.32.1",
  "platform": "Amlogic T962",
  "ram": "2GB",
  "verified": true,
  "verified_on": "2026-10-25",
  "notes": [
    "这台机器的 XXX 需要注意……"
  ]
}
```

`notes` 里写**你这台机器独有的坑**，比如：

- ADB 每次重启自动关闭
- 某个包禁了会导致桌面进不去
- 固件锁死了某个属性，改不了
- 广告是组件级的但被固件禁止禁用

### 4. 写 debloat.txt（去臃肿包清单）

一行一个包名，`#` 后面是注释。**只写你验证过能禁的。**

```bash
# ===== 默认禁用 =====
com.miui.tv.analytics        # 数据上报
com.xiaomi.mitv.tvmanager      # 电视管家，最吃内存

# ===== 不能禁（禁了会出问题）=====
# com.mitv.tvhome              # 桌面 —— 禁了进不去系统
# com.xiaomi.mitv.settings     # 系统设置
```

**几条硬规矩：**

- 桌面（通常是 `com.mitv.tvhome`）**绝对不能禁**
- 系统设置、平台输入服务（`com.droidlogic.*`、`com.mediatek.*`）不能禁
- 投屏相关包（`smartshare` / `miplay` / `wfdsinkhelperservice` / `upnp`）建议保留
- 拿不准的先别写进去

### 5. 写 hosts.txt（广告拦截域名）

一行一个域名。工具会自动补 `127.0.0.1 ` 前缀。

**优先用 `scan` 生成的，别手写：**

```bash
mitvclean --host <电视IP> scan --apk com.mitv.tvhome --apk com.mitv.videoplayer
```

从产物里挑出广告域和内容源域，整理成三组（看 `mitvclean/ads.py` 里的 `AD_HINTS` / `SOURCE_HINTS`
是怎么分的），并**在注释里写清每组的作用**。

### 6. 提交

```bash
python tests/test_offline.py     # 必须全过
```

## 改代码

- 保持零第三方依赖（`pyproject.toml` 里 `dependencies = []`）
- Python 3.9 兼容（不要用 3.10+ 的语法）
- 新逻辑补离线测试到 `tests/test_offline.py`
- 不要在代码里硬编码 IP、设备型号、路径

## 踩过的坑（提交前自查）

- [ ] 没有 uninstall，只有 `pm disable-user`
- [ ] 动手前落了盘状态记录
- [ ] 包名做了合法性校验
- [ ] 命令逐条下发，没有用分号链式
- [ ] 桌面 / 设置 / 平台服务没被禁
- [ ] 测试全过
- [ ] 提交里不含自己的 IP、MAC、SN、设备序列号
