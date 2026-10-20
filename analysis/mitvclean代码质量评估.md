# mitvclean 代码质量评估

- **分析对象**：`mitvclean`
- **数据来源**：本地仓库实测（radon 6.0.1 / ruff / coverage，均在隔离 venv 中执行）
- **分析日期**：2026-10-21
- **分析版本**：`b277c37`
- **分析角度**：角度五 · 代码质量

## 结论

**整体评级：良好偏上，工程化欠一档。**

| 维度 | 实测 | 判定 |
|---|---|---|
| 平均圈复杂度 | **3.76**（122 个块） | ✅ 优秀（< 5） |
| 复杂度热点 | CC 最高 17（`cmd_doctor`） | ⚠️ 1 处越界 |
| 源码规模 | 1626 LOC / 945 语句 | ✅ 规模合理 |
| 注释密度 | (C+M)%L = 15% | ✅ 优秀（注释是解释"为什么"） |
| 测试覆盖 | **34%**（离线测试口径） | ⚠️ 偏低 |
| 静态检查 | ruff **49 条**告警 | ❌ 未进 CI |
| 循环依赖 | **0**（4 模块 + 5 子模块，依赖图无环） | ✅ 优秀 |
| 第三方依赖 | **0** | ✅ 双刃剑 |

**唯一必须立刻处理的 P0**：`mitvclean/ads.py:217` `set_ad_settings` 不记录原值——这**违反了项目自己在 README 里声明的"只做可逆操作"**。不是质量问题，是承诺一致性问题。

**最值得做的一步**：把 `ruff check` 加进 CI。49 条告警里 10 条可自动修、其余大多集中在 18 处 `except Exception`（BLE001）——这些恰恰是"外部设备返回什么都有可能"的合理场景，但**必须逐条确认是不是该捕获**。CI 一接上，代码质量的回归就被自动卡住了。

---

## 一、指标总览

| 指标 | 实测值 | 阈值 | 判定 | 采集命令 |
|---|---|---|---|---|
| 平均圈复杂度 | 3.76 | < 5 优 / 5-10 中 / > 15 差 | ✅ 优 | `radon cc mitvclean tests -s -a` |
| 最高圈复杂度 | 17（`cmd_doctor`） | ≤ 15 | ⚠️ 越界 | 同上 |
| CC > 10 的函数数 | 4 | 0 | ⚠️ | 同上 |
| 源码 LOC | 1626 | — | ✅ | `radon raw mitvclean -s` |
| 逻辑行 SLOC | 1115 | — | — | 同上 |
| 注释率 (C+M)%L | 15% | > 8% | ✅ 优 | 同上 |
| 测试文件行数 | 525 | — | ✅ | `wc -l tests/*.py` |
| 语句覆盖率 | 34% | > 60% | ⚠️ 偏低 | `coverage run --source=mitvclean -m tests.test_offline` |
| ruff 告警 | 49 | 0 | ❌ | `ruff check mitvclean tests` |
| 可自动修复 | 10 | — | — | `ruff check --fix` |
| 循环依赖 | 0 | 0 | ✅ 优 | 手工核 import 图 |
| 直接依赖 | 0 | — | ✅/⚠️ | `pyproject.toml` |
| CI 覆盖的 Python 版本 | 3.9–3.13 × 3 OS | — | ✅ 优 | `.github/workflows/test.yml` |

**覆盖率口径说明**：34% 是**只跑 `test_offline.py`** 的结果。`test_adb_protocol.py` 用假 adbd 覆盖了 `adb.py` 的握手与流控路径，但因覆盖率工具未合并运行，此处未计入。合并两个测试文件后的实际覆盖率会更高（`adb.py` 的 19% 主要是被协议测试覆盖的握手段被离线测试完全跳过）。**此数字为保守值。**

---

## 二、复杂度热点 Top-10

按 radon 圈复杂度（CC）排序：

| # | 函数 | 文件:行 | CC | 等级 | 说明 |
|---|---|---|---|---|---|
| 1 | `cmd_doctor` | `cli.py:131` | **17** | C | 体检报告，混合三种关注点 |
| 2 | `disable_packages` | `packages.py:158` | **14** | C | 禁用主流程（状态判定 + 落盘 + 逐条执行） |
| 3 | `FakeAdbd._session` | `test_adb_protocol.py:57` | 11 | C | 假 adbd 主循环（测试代码，可接受） |
| 4 | `cmd_debloat` | `cli.py:292` | **11** | C | 禁用命令的 CLI 编排 |
| 5 | `cmd_info` | `cli.py:90` | 10 | B | 设备信息 |
| 6 | `cmd_scan` | `cli.py:181` | 10 | B | 域名提取编排 |
| 7 | `clean_ad_cache` | `ads.py:240` | 10 | B | 缓存清理 |
| 8 | `find_ad_settings` | `ads.py:191` | 9 | B | 广告键探测 |
| 9 | `enable_packages` | `packages.py:201` | 8 | B | 还原 |
| 10 | `extract_from_apk` | `ads.py:99` | 8 | B | APK 扫描 |

### 逐个诊断

**`cmd_doctor`（CC 17，`cli.py:131-178`）—— 唯一的 C 级生产函数**

它同时在做四件事：
1. 读设备型号与系统版本
2. 探测 settings 里的广告开关
3. 遍历**所有画像**的 debloat 清单，逐个查包状态
4. 列 sdcard 缓存目录

第 3 步尤其糟糕：它在内层循环里**反复调用 `list_packages(dev)`**（`cli.py:152-153`）——每遍历一个画像就发两次 `pm list packages`。当前只有一个画像所以看不出来，加到 5 个画像就是 10 次全量包列举。

**建议拆分**：
```python
def cmd_doctor(args) -> int:
    ...
    _doctor_ad_settings(dev)      # 拆出，CC ~4
    _doctor_ad_packages(dev)      # 拆出，并把 list_packages 提到循环外
    _doctor_cache(dev)            # 拆出
```
同时把 `packages.list_packages` 的两次调用**提到画像循环之外**，只查一次。

**`disable_packages`（CC 14，`packages.py:158-198`）—— 业务核心，可接受但可读性差**

三个阶段（判定目标 / 落盘 / 执行）串在一个函数里。业务逻辑本身是正确的、顺序也是对的，但 40 行里混了 3 个关注点。

**建议**：拆成 `_select_targets(state)` / `_execute_disable(dev, targets)`，主函数降到 CC 8 以下。注意**顺序不可变**（判定→落盘→执行），拆分时要保持。

**协议层与测试代码的复杂度都在健康范围**：`adb.py` 最高 CC 8（`pull`），且是"长而浅"——513 行但每个函数都在 20 行以内。测试里的 `FakeAdbd._session`（CC 11）是要模拟的状态机，复杂度天然高，可接受。

---

## 三、覆盖率与未覆盖的关键模块

```
Name                    Stmts   Miss  Cover   Missing
----------------------------------------------------
mitvclean\__init__.py       2      0   100%
mitvclean\adb.py          271    219    19%
mitvclean\ads.py          136     96    29%
mitvclean\cli.py          305    250    18%
mitvclean\packages.py     155     31    80%
mitvclean\profiles.py      76     30    61%
----------------------------------------------------
TOTAL                     945    626    34%
```

| 模块 | 覆盖率 | 判断 |
|---|---|---|
| `packages.py` | **80%** | ✅ 好。核心业务有测试 |
| `profiles.py` | 61% | ⚠️ 可接受。缺 `host_groups()` 的边界测试（本次已补） |
| `ads.py` | 29% | ⚠️ 偏低。`extract_from_apk` / `pull_apks` / `find_ad_settings` 未覆盖 |
| `adb.py` | 19% | ⚠️ 保守值。协议测试实际覆盖了握手段，但未合并统计 |
| `cli.py` | **18%** | ❌ **最薄弱环节** |

### 未覆盖的关键位置（按风险排序）

| 位置 | 未覆盖内容 | 风险 |
|---|---|---|
| `adb.py:153-184` | `_parse_pem_rsa` 手写 DER 解析 | **高** — 唯一手写密码学代码，CI 从不执行（CI 未装 cryptography） |
| `cli.py:91-384` | 几乎所有子命令的完整流程 | **高** — CLI 是用户唯一入口，出错直接影响使用 |
| `ads.py:105-125` | `extract_from_apk` 的 zipfile 遍历 | 中 — 逻辑简单但依赖真实 APK 结构 |
| `ads.py:153-179` | `pull_apks` 的路径解析与临时文件清理 | 中 — 临时文件 `/data/local/tmp/{pkg}.apk` 清理失败会留垃圾 |
| `ads.py:251-267` | `clean_ad_cache` 的 `rm -rf {d}/*` 分支 | **高** — 唯一的递归删除操作，且 `{d}` 来自命令行参数 |

**特别提示**：`ads.py:263` 的 `dev.run(f"rm -rf {d}/*")` 中 `{d}` **来自 `args.dir` 用户输入，未做路径校验**。虽然 `clean_ad_cache` 的调用方是 CLI 自己的默认列表（`cli.py:353-356`），但 `--dir` 参数允许用户传任意路径。与包名白名单（`packages.py:23`）形成鲜明对比——**同一个项目里，一条输入做了严格校验，另一条没做**。

---

## 四、ruff 静态检查结果

`ruff check mitvclean tests` → **49 条**。

### 按规则分类

| 规则 | 条数 | 位置 | 判断 |
|---|---|---|---|
| `BLE001` 盲捕 `Exception` | **18** | 遍布 `ads.py`(8) `packages.py`(4) `cli.py`(3) `adb.py`(1) 测试(4) | ⚠️ 多数合理（设备返回不可控），但**必须逐条确认** |
| `F401` 未使用的 import | 3 | `test_adb_protocol.py:21, 152`、`test_offline.py:8` | ✅ 直接删 |
| `RUF059` 未使用的解包变量 | 5 | `test_adb_protocol.py:77, 164` | ✅ 测试代码风格问题 |
| `S110` / `S112` 静默吞异常 | 8 | `cli.py:173` 等 | ⚠️ 多数是"这条探测失败就跳过"的可接受场景 |
| `I001` import 排序 | 1 | `test_adb_protocol.py:19` | ✅ 直接修 |
| `F841` 未使用的局部变量 | 1 | `test_adb_protocol.py:150` | ✅ 直接修 |
| `PIE810` 可用元组 | 1 | `test_adb_protocol.py:83` | ✅ 直接修 |

**10 条可自动修复**（`ruff check --fix`），其余 39 条需要人工判断。

### 关于 18 条 BLE001

这些 `except Exception` 绝大多数出现在**设备交互边界**——`dev.run()` 可能因为网络超时、连接断开、权限拒绝而抛出任意异常。捕获它们并转成"这条探测失败，跳过"是合理的。

**但有两处不该捕获**：

1. `ads.py:255-256` `clean_ad_cache` 里的 `pm clear` —— 失败了应该让用户知道，而不是记成一行 `ERROR: {e}` 混进结果字典
2. `cli.py:199-201` `cmd_scan` 里的 logcat 抓取 —— 已经正确地 `print` 了警告，这处是**典范写法**

**建议**：不要全局 `except Exception` 放行，而是逐条加 `# noqa: BLE001` 并注明为什么，或在 `ads.py` 引入一个窄的 `DeviceError` 类型。**关键是让每个捕获点都留下理由。**

---

## 五、循环依赖与依赖方向

```
cli.py     → ads.py, packages.py, profiles.py, adb.py
packages.py → adb.py
ads.py     → adb.py
profiles.py → (无内部依赖)
adb.py     → (无内部依赖)
```

**无环。** 4 个顶层模块的依赖图是一棵有根树，深度 2。

唯一的轻微反模式：`cli.py:33` 同时导入了 `ProfileError` 和 `list_profiles/load_profile/profile_table` 三个符号——`list_profiles` 与 `load_profile` 只在 `cli.py` 用，`profile_table` 也是。这不算越界，但 `cli.py` 承担了"应用层该知道所有领域层 API"的正常职责。

---

## 六、P0 / P1 / P2 改造清单

### P0 · 正确性 / 承诺一致性（必须做）

| # | 事项 | 位置 | 影响面 | 成本 |
|---|---|---|---|---|
| 1 | **`set_ad_settings` 补原值快照** —— 写前读原值落盘，`restore` 时还原 | `ads.py:217-228` | 破坏项目"只做可逆操作"的核心承诺。用户在 `adswitch --set` 改 4 个开关后无法回退 | ~30 行 |
| 2 | **`rm -rf {d}/*` 的路径校验** —— 要求路径以 `/sdcard/` 开头且不含 `..` | `ads.py:263` | `--dir` 传错参数可能删掉非预期目录。这是全项目唯一的递归删除 | ~10 行 |
| 3 | **`_parse_pem_rsa` 加单测** —— 用已知测试密钥 PEM 验证 n/d/e 解析 | `adb.py:151-184` | 唯一手写密码学代码，CI 从不执行（CI 未装 cryptography）。解析错表现为"AUTH 无限循环" | ~20 行 |

### P1 · 可维护性阻塞（应该做）

| # | 事项 | 位置 | 影响面 | 成本 |
|---|---|---|---|---|
| 4 | **CI 接入 `ruff check`** | `.github/workflows/test.yml` | 49 条告警一次性暴露，10 条可自动修。成本几乎为零，收益是所有后续改动自动被卡住 | 5 行 |
| 5 | **拆分 `cmd_doctor`（CC 17）** | `cli.py:131-178` | 唯一 C 级函数。且内层循环重复调 `list_packages`（`cli.py:152-153`），多画像时性能线性劣化 | ~40 行 |
| 6 | **合并两个测试文件的覆盖率统计** | `tests/` | 真实覆盖率被低估（`adb.py` 19% 严重偏低），掩盖了协议层其实有测试的事实 | ~10 行 |
| 7 | **`cmd_debloat`（CC 11）与 `disable_packages`（CC 14）拆分** | `cli.py:292` `packages.py:158` | 两个 C 级函数。拆分时**必须保持"判定→落盘→执行"的顺序不变** | ~40 行 |
| 8 | **`profile.json` 加未知字段告警** | `profiles.py:41-57` | 画像写错字段名会静默取默认值（如把 `model` 写成 `models`），贡献者看不到任何提示 | ~15 行 |
| 9 | **`work/` 快照过期清理** | `cli.py:367-370` | `restore` 自动取"最新" `state-*.json`，多机型/多次操作会取错 | ~20 行 |

### P2 · 整洁度（有余力做）

| # | 事项 | 位置 | 影响面 |
|---|---|---|---|
| 10 | `ruff check --fix` 清掉 10 条可自动修的（未使用 import、import 排序等） | 测试代码为主 | 低 |
| 11 | `ads.py:80-86` `summary()` 补"另有 N 个未分类域名未加入清单" | `ads.py` | 让 `other` 盲区可见 |
| 12 | 18 处 `except Exception` 逐条加理由注释或 `# noqa` | 全项目 | 提升可读性，不改行为 |
| 13 | `ads.py` 的 `AD_HINTS` / `SOURCE_HINTS` 移到独立数据文件 | `ads.py:43-58` | 让贡献者能改分类规则而不动代码 |
| 14 | `mitvclean/__init__.py` 补 `__version__` | `mitvclean/__init__.py` | 目前版本号只在 `pyproject.toml`，`--version` 无法实现 |
| 15 | 协议结论补"适用固件范围"标注 | `docs/ADB协议实现笔记.md` | 4 处偏差只在 1 台电视 1 个固件验证过 |

---

## 七、复核命令

本次全部指标可用以下命令复现（需 `radon` / `ruff` / `coverage`）：

```bash
# 复杂度
radon cc mitvclean tests -s -a
radon raw mitvclean -s

# 静态检查
ruff check mitvclean tests --output-format concise
ruff check mitvclean tests --fix        # 10 条可自动修

# 覆盖率
coverage run --source=mitvclean -m tests.test_offline
coverage report -m

# 协议层覆盖率（补上）
coverage run --source=mitvclean -m tests.test_adb_protocol
coverage combine
coverage report -m

# 测试
python tests/test_offline.py
python tests/test_adb_protocol.py
```

**采集日期：2026-10-21。** 工具版本：radon 6.0.1、ruff（隔离 venv 最新版）、coverage（隔离 venv 最新版）。
工具运行于 `C:/Users/jiang/.workbuddy/binaries/python/envs/default/`，未污染用户全局环境。
