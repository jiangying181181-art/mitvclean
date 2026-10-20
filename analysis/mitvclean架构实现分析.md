# mitvclean 架构实现分析

- **分析对象**：`mitvclean`（https://github.com/jiangying181181-art/mitvclean）
- **数据来源**：本地路径直读（`D:/外部项目咨询调研/github项目调研/mitv-clean`），含完整 `.git` 历史，共 5 次提交、26 个受版本控制的文件
- **分析日期**：2026-10-21
- **分析角度**：角度一 · 架构实现

## 结论

这是一个**四层单向依赖**的极小工具型项目：协议层（`adb.py`）→ 领域层（`packages.py` / `ads.py` / `profiles.py`）→ 应用层（`cli.py`）→ 数据层（`profiles/` 目录 + `work/` 运行时产物）。

它的架构判断力体现在三处，而不是文件数量：

1. **依赖方向严格单向，零反向引用。** 领域层只 `from .adb import AdbDevice` 拿一个连接对象，从不反向引用 CLI；CLI 是唯一知道"用户想干什么"的地方。这让 `packages.py` / `ads.py` 可以在完全离线的条件下被测试（`tests/test_offline.py` 里的 `FakeDevice` 就是这么替身掉 `AdbDevice` 的）。
2. **数据与代码分离是硬约束，不是口号。** 机型画像放在仓库根的 `profiles/<slug>/`，`profiles.py` 里没有一行针对具体机型的 `if`。加新机型 = 复制目录改内容，零代码改动。
3. **"可逆"这个领域概念只在一处定义，贯穿到底。** 状态快照（`save_record`）→ 按快照还原（`enable_packages`）→ 测试对称性验证（`test_restore_only_reenables_what_was_enabled`）。这是整个项目最核心的业务不变量。

代价也很明确：应用层 `cli.py` 的 `cmd_doctor` 圈复杂度 **17**（radon 实测，C 级），是唯一越过"命令层只做编排"边界的函数；`cli.py` 覆盖率仅 **18%**，是全项目最薄的测试防线。

---

## 一、分层与职责

| 层 | 文件 | 职责 | 关键点 |
|---|---|---|---|
| 协议层 | `mitvclean/adb.py` | 自研 ADB-over-TCP 客户端 | 24 字节包头编解码、AUTH 签名、shell v2 流、sync 子协议；纯标准库 |
| 领域层 | `mitvclean/packages.py` | 包状态管理（可逆禁用/还原） | 包名校验白名单、状态快照落盘、原子写、还原对称性 |
| 领域层 | `mitvclean/ads.py` | 广告域提取与缓存清理 | APK 静态扫描、logcat 动态提取、域名分类、settings 开关探测 |
| 领域层 | `mitvclean/profiles.py` | 机型画像数据层 | 目录约定 + `profile.json` 解析，无机型特判 |
| 应用层 | `mitvclean/cli.py` | 命令行编排 | 9 个子命令，全局参数前后皆可 |
| 数据层 | `profiles/mitv-ansp0/*` | 机型适配数据 | `profile.json` / `debloat.txt` / `hosts.txt` |
| 数据层 | `work/`（运行时） | 状态快照、hosts 产物、日志 | 运行时生成，不入版本库 |
| 验证层 | `tests/test_offline.py` | 离线条目测试 | 17 项，用 `FakeDevice` 替身设备 |
| 验证层 | `tests/test_adb_protocol.py` | 协议实现测试 | 5 项，用假 adbd 验证握手/开流/读写/认证 |

### 分层图

```
┌──────────────────────────────────────────────────────────┐
│ 应用层   cli.py                                          │  ← 唯一知道"用户意图"的一层
│          info doctor scan hosts debloat adswitch         │
│          cache restore profiles                          │
├──────────────────────────────────────────────────────────┤
│ 领域层   packages.py   ads.py   profiles.py              │  ← 可离线测试，不依赖网络
│          包状态/可逆   广告域提取   机型数据              │
├──────────────────────────────────────────────────────────┤
│ 协议层   adb.py                                          │  ← 唯一碰网络的一层
│          CNXN/AUTH/OPEN/OKAY/WRTE/CLSE + sync 子协议      │
├──────────────────────────────────────────────────────────┤
│ 数据层   profiles/<slug>/  +  work/（运行时）            │  ← 加机型不改代码
└──────────────────────────────────────────────────────────┘
              依赖方向严格向下，无反向引用
```

### 分层成立的证据

| 检查项 | 结果 | 证据 |
|---|---|---|
| 领域层是否引用应用层 | ❌ 无 | `packages.py` / `ads.py` / `profiles.py` 的 import 只有 `from .adb import AdbDevice` 与标准库 |
| 协议层是否引用领域层 | ❌ 无 | `adb.py` 只 import 标准库（`base64/hashlib/os/socket/struct/subprocess/sys/pathlib`） |
| 协议层是否含业务判断 | ❌ 无 | `adb.py` 中唯一的"策略"是 `run()` 的换连接重试（`adb.py:392-404`），是传输层容错 |
| 应用层是否绕过领域层直接操作设备 | ⚠️ 部分 | `cli.py` 直接调 `dev.run(...)` 取系统属性（`cli.py:63-64, 93-98, 134-135`）——只读探测，可接受 |
| 领域层是否依赖具体机型 | ❌ 无 | `profiles.py` 全文无机型字符串；机型信息只从 `profile.json` 读 |

**唯一的越界点**：`ads.py:191-214` 的 `find_ad_settings` 内嵌了"哪些 settings 键算广告键"的关键词表（`("ad","splash","boot","front","skip","vip")`）与排除词表（`("bluetooth","keyboard","alarm",...)`）。这是业务知识被写死在协议无关的领域层里——但它只影响"哪些键被读出来给人看"，不影响任何写操作，风险可控。

---

## 二、层间结合机制

本项目没有框架，用的是三种朴素机制：

| 机制 | 实现 | 位置 |
|---|---|---|
| **数据驱动注册** | 目录即注册表：`profiles/` 下每个含 `profile.json` 的目录自动成为一个可用画像 | `profiles.py:97-104` `list_profiles()` 遍历 `PROFILES_DIR.iterdir()` |
| **装饰器式状态捕获** | `with _connect(args) as dev:` 打开连接、退出时关闭 | `cli.py:91, 133, 187, 294, 327, 349, 372` 全部走 `AdbDevice.__enter__/__exit__`（`adb.py:301-306`） |
| **异常 → 退出码映射** | `ProfileError → 2`、`AdbError → 3`、`KeyboardInterrupt → 130` | `cli.py:455-464` `main()` 的 except 链 |

**校验体系**（分四层，每层守不同东西）：

| 层 | 校验 | 守什么 | 位置 |
|---|---|---|---|
| 1. 输入格式 | 包名必须匹配 `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$` | 防清单注入（清单内容被当 shell 片段执行） | `packages.py:23, 60-65` |
| 2. 输入内容 | 清单为空直接抛错；非法行报"文件:行号" | 防空操作与静默错误 | `packages.py:96-103` |
| 3. 状态前置 | 只禁用 `STATE_ENABLED` 的包 | 不动用户自己关掉的东西 | `packages.py:173-175` |
| 4. 持久化完整性 | 先写 `.tmp` 再 `Path.replace()` 原子替换 | 断电/中断不留半截记录 | `packages.py:141-143` |

**四层校验的顺序不可交换**：第 1 层必须在第 3 层之前——如果先把未校验的包名拼进 `pm disable-user --user 0 {n}`，注入就已经发生了。

---

## 三、一次完整数据流

以「禁用后台包」为例（`mitvclean debloat`）：

```
① 用户意图           cli.py:292 cmd_debloat
      ↓ args.profile / --dry-run / --out
② 画像解析           profiles.py:76 load_profile(slug)
      ↓ 校验三个文件都存在，否则 ProfileError
③ 清单解析           packages.py:80 read_list(debloat.txt)
      ↓ 剥 BOM → 去注释 → 逐行 validate_package → 去重保序
④ 设备连接           cli.py:47 _connect → adb.py:241 connect
      ↓ socket → _handshake(CNXN) → AUTH 签名 → 设备回 CNXN
⑤ 状态快照           packages.py:107 query_state
      ↓ pm list packages + pm list packages -d（两次）
⑥ 落盘（先于动手）   packages.py:122 save_record
      ↓ work/state-20261021-045612-mitv-ansp0.json（原子写）
⑦ 逐条执行           packages.py:187-196
      ↓ 每个包一条命令：pm disable-user --user 0 <pkg>
      ↓ 逐条下发（不用分号链式）
⑧ 结果汇总           DebloatResult{disabled, failed, skipped_absent, skipped_already}
      ↓ CLI 打印 + 告知还原命令
```

**一次完整数据流（广告域名）**：

```
① cmd_scan              cli.py:181
② 动态腿                ads.py:182 grab_logcat → logcat -d -v time（超时 120s）
                        ads.py:128 extract_from_logcat → 正则提域名
③ 静态腿                ads.py:143 pull_apks
                        → pm list packages -f 拿路径
                        → cp 到 /data/local/tmp/ → pull → rm -f
                        ads.py:99 extract_from_apk → zipfile 逐条目扫 .dex/.arsc/.so
④ 归类                  ads.py:89 classify → AD_HINTS / SOURCE_HINTS
⑤ 产物                  work/hosts-scan.txt（IP 在前）+ work/domains.json
```

**这里有一个重要的设计约束**：`ads.py:150-153` 明确写了"只有 `/data/app` 下的能 pull，系统应用 shell 读不到 base.apk"。这不是能力缺失，是被文档化的边界——分析器明确知道自己不知道什么。

---

## 四、架构优势

| # | 优势 | 证据 | 代价 |
|---|---|---|---|
| 1 | **零第三方依赖使领域层天然可测** | `pyproject.toml` `dependencies = []`；`tests/test_offline.py` 用 `FakeDevice` 在无网络下跑完 17 项 | 无依赖也意味着没有成熟的 RSA 库，ADBP 密钥解析得自己写（`adb.py:151-184`），是 100 行手写 DER 解析 |
| 2 | **数据与代码分离让适配成本趋零** | `profiles.py` 无机型特判；`CONTRIBUTING.md` 明确"不需要改任何代码" | 画像文件的 schema 无强校验（`profile.json` 写错字段名只会静默取默认值，见 `profiles.py:41-57`） |
| 3 | **"可逆"作为领域不变量只定义一次** | `save_record` / `enable_packages` / 对称性测试三处呼应 | 快照只记录包状态，**不记录 settings 开关原值**——`adswitch --set` 改了广告开关后无法自动还原 |
| 4 | **协议层是唯一不透明处** | `adb.py` 集中承载全部抓包结论，其他层完全不知道自己走的是 ADB | 协议层 513 行占全项目 31%，是最大的一块单体 |

## 五、架构代价

| # | 代价 | 具体位置 | 影响 |
|---|---|---|---|
| 1 | **CLI 层承担了本该属于领域层的编排判断** | `cli.py:131-178` `cmd_doctor` 圈复杂度 17（radon C 级），内部混合了"读广告设置 / 查包状态 / 列缓存目录"三种关注点 | 难以单测；`cli.py` 覆盖率仅 18%，出问题难定位 |
| 2 | **运行时状态与版本化数据混在同一 `work/` 目录** | 快照、hosts 产物、logcat 全落 `work/` | 快照文件没有过期清理机制，跑多了会堆积；`restore` 自动取"最新"的 `state-*.json`（`cli.py:367-370`），在多机型/多次操作场景下可能取错 |
| 3 | **`adswitch` 写操作无对称还原** | `ads.py:217-228` `set_ad_settings` 只写不存原值 | 用户设了 4 个开关后无法一键回退，与项目"只做可逆操作"的整体承诺不一致 |
| 4 | **协议层单文件过大** | `adb.py` 513 行 = 密钥管理 + 帧编解码 + 三种流协议 + 业务重试 | 任何协议改动都集中在这一个文件；但 CC 最高仅 8，说明是"长而浅"而非"深而复杂" |

---

## 六、结论

架构本身是健康的：**四层单向、零反向引用、协议隔离良好、数据驱动适配**。对一个 2 千行的工具来说，这个结构已经优于同类开源项目（`cleanyourtv` / `MiTVNoAd` 都是脚本形态，无领域/协议分层）。

真正需要动的是三处具体位置，而不是重构架构：

1. `cli.py:131` `cmd_doctor` 拆成三个小函数（CC 17 → 各 < 8）
2. `ads.py:217` `set_ad_settings` 加原值快照，补上"可逆"闭环
3. `profiles.py:41-57` `Profile` 的 meta 读取加未知字段告警，避免画像写错静默失效

详见《mitvclean 代码质量评估》中的 P0/P1 清单。
