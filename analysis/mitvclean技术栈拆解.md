# mitvclean 技术栈拆解

- **分析对象**：`mitvclean`
- **数据来源**：本地仓库直读（`pyproject.toml` / `.github/workflows/test.yml` / `requirements` 清单 / 源码 import 分析）
- **分析日期**：2026-10-21
- **分析版本**：`b277c37`
- **分析角度**：角度六 · 技术栈

## 结论

这是一套**刻意极简**的技术栈：**Python 3.9+ 标准库，零第三方依赖**。

| 维度 | 结论 |
|---|---|
| 语言构成 | Python 100%（2 265 行），另有 829 行 Markdown / 配置 / 清单 |
| 运行时 | CPython ≥ 3.9（CI 实测 3.9–3.13 × 3 OS 全绿） |
| 框架与核心库 | **0 个第三方库**。stdlib 覆盖 socket / struct / json / zipfile / re / argparse / hashlib |
| 数据与存储 | 无数据库。文件系统（`profiles/` 版本化 + `work/` 运行时） |
| 基础设施 | 无。单机 CLI，无服务、无容器、无编排 |
| 构建与交付 | `pyproject.toml` + setuptools，`pip install -e .`，`mitvclean.bat` 双击即用 |
| 质量与工程化 | unittest（自写 runner）+ 2 个 CI 矩阵 + fake adbd 集成测试；**但无 lint / 无类型检查 / 无覆盖率门禁** |
| 许可证 | MIT（项目与唯一可选依赖 `cryptography` 均为 MIT/Apache-2.0 双许可兼容） |
| 依赖健康度 | 间接依赖 **0**，漏洞面 **0** |

**零依赖是本项目最正确的一个技术决策**，理由不只是"轻"：

1. 用户是普通人，不会为去广告去配 Python 环境。`dependencies = []` 让 `pip install` 永不失败。
2. 供应链攻击面归零。没有 `requirements.txt` 就没有 CVE 传导路径，这对一个要装在别人家用电器上的工具是决定性的。
3. 交叉编译与打包（若将来做 GUI）不受第三方库的 Python 版本约束。

**代价**：手写了 RSA DER 解析（`adb.py:151-184`，100 行，零测试覆盖）；没有 `httpx`/`requests` 级别的 HTTP 能力（不需要）；没有 `pydantic` 级别的数据校验（`profile.json` 因此静默容错，见质量评估 P1-8）。

**唯一实质风险**：`cryptography` 作为可选依赖，其最低版本 `>=3.4` 是 **2019 年**的版本。`cryptography` 从 3.4 起才支持 Rust 后端，且 2024 年后官方推荐 ≥ 41.0。这个下限设得太松，会让用户装到含已知 CVE 的旧版本。

---

## 一、七维度技术栈矩阵

| 维度 | 实测内容 | 评价 |
|---|---|---|
| **语言构成** | Python 2 265 行（`mitvclean/` 1 626 + `tests/` 525 + 其他）；Markdown / TOML / YAML / TXT / JSON / BAT 共 829 行 | ✅ 单一语言，无 FFI、无跨语言构建 |
| **运行时与版本** | `requires-python = ">=3.9"`；CI 矩阵 3.9 / 3.10 / 3.11 / 3.12 / 3.13 × ubuntu / windows / macos = 15 组 | ✅✅ 优秀。最低 3.9 是刻意的（Windows 预装 Python 常年落后），且真在 15 个组合上跑 |
| **框架与核心库** | 无框架。核心依赖全在 stdlib：`socket`（传输）、`struct`（二进制协议）、`hashlib`/`base64`（认证）、`zipfile`（APK 扫描）、`re`（域名提取）、`argparse`（CLI）、`json`/`csv`（数据）、`subprocess`（仅 `list_devices`） | ✅ 依赖风险为零。⚠️ 但 `subprocess` 唯一用处在 `list_devices()`（`adb.py:501`），是全项目唯一需要外部 adb 的功能 |
| **数据与存储** | 无数据库、无 ORM。版本化数据：`profiles/<slug>/{profile.json,debloat.txt,hosts.txt}`；运行时数据：`work/state-*.json`（原子写）、`work/hosts-*.txt`、`work/domains.json`、`work/logcat.txt` | ✅ 对单机 CLI 是正确选择。⚠️ `work/` 无清理机制，快照会无限堆积 |
| **基础设施** | 无。云无关、无容器、无 CI 服务依赖（只用了 GitHub Actions）、无网络出口（本工具只连电视的 5555 端口） | ✅✅ 优秀。**零外部网络依赖**是这类工具的重要属性 |
| **构建与交付** | `pyproject.toml`（setuptools ≥ 61，PEP 621 元数据）；`pip install -e .` → `mitvclean` 命令；`mitvclean.bat`（Windows 双击，自动找 Python、自动装依赖、进入交互菜单）；未打包成 wheel/PyPI | ✅ 交付路径极简。⚠️ 未发 PyPI 是对的（受众是电视用户不是 Python 用户），但也没有 exe 化路径 |
| **质量与工程化** | 自写 unittest runner（`tests/test_*.py` 各自 `_run_all()`，无 pytest 依赖）；CI 15 组矩阵 + CLI 冒烟；`FakeAdbd` 假设备做协议集成测试；**无 ruff、无 mypy、无覆盖率门禁、无 pre-commit** | ⚠️ 测试有骨架但**门禁不全**。CI 跑了测试但没跑 lint（实测 49 条 ruff 告警从未被卡住） |

---

## 二、依赖清单

### 直接依赖

| 包 | 版本约束 | 用途 | 必需性 |
|---|---|---|---|
| （无） | — | — | — |
| `cryptography` | `>=3.4`（**可选**，extras `crypto`） | ADB 认证时加速 RSA 签名 / 生成密钥 | 可选。无它时走手写 DER 解析（`adb.py:139-143` 的 `except ImportError` 分支） |

`pyproject.toml` 原文：

```toml
dependencies = []

[project.optional-dependencies]
# 只有在 adb 认证需要自己签 RSA 密钥时才有必要装；有 cryptography 会快很多。
crypto = ["cryptography>=3.4"]
```

### 间接依赖

| 场景 | 间接依赖数 | 判定 |
|---|---|---|
| 默认安装（`pip install -e .`） | **0** | ✅✅ 无依赖膨胀 |
| 安装 `crypto` extra | `cryptography` → `cffi` → `pycparser` = **3** | ✅ 极小 |

**没有"依赖膨胀"问题**。这是本项目技术栈最大的优点——对于要被普通用户装在自己家里电视上的工具，任何间接依赖都是潜在的故障点。

---

## 三、依赖健康度与合规

### 3.1 漏洞与过时清单

| 项 | 状态 | 说明 |
|---|---|---|
| **项目本身漏洞** | **0 个第三方依赖 → 0 个已知 CVE** | 无依赖即无传导路径 |
| **`cryptography>=3.4`** | ⚠️ **版本下限过松** | 3.4 发布于 2019-10。它是 `cryptography` 第一个支持 Rust 后端的版本（3.4 是过渡期，实际稳定在 42+）。2024 年后官方仅维护 42+ 分支。装到 3.4/3.9 这类旧版本会带来已修复的 OpenSSL 绑定层 CVE |
| **Python 3.9** | ⚠️ **EOL 在 2025-10** | Python 3.9 已于 2025 年 10 月结束官方支持。本项目 `requires-python = ">=3.9"` 允许装到已 EOL 的解释器，且 CI 仍在测 3.9 |
| **stdlib 用法** | ✅ 无过时 API | `socket` / `struct` / `zipfile` / `argparse` 均为稳定 API |

**建议**：
- `cryptography>=3.4` → `cryptography>=41.0`（2023-03，LTS 分支起点）
- `requires-python` 保持 `>=3.9`（这是给终端用户装的，锁更高会挡住 Windows 预装的旧 Python），但**在 README 里标注 3.9 已 EOL、推荐 3.11+**
- CI 矩阵保留 3.9（验证兼容性），但可加一个"最低版本 3.9 不再是推荐版本"的说明

### 3.2 许可证合规

| 对象 | 许可证 | 与 MIT 的兼容性 |
|---|---|---|
| 本项目 | MIT | — |
| `cryptography` | Apache-2.0 **或** BSD-3-Clause 双许可 | ✅ 完全兼容（Apache-2.0 与 MIT 兼容） |
| `cffi` | MIT | ✅ |
| `pycparser` | BSD-3-Clause | ✅ |
| Python stdlib | PSF License | ✅ 不进入分发物 |
| `docs/ADB协议实现笔记.md` 引用 AOSP 协议文档 | Apache-2.0 | ✅ 仅描述协议行为，未复制 AOSP 源码 |

**结论：许可证零风险。** 唯一可选依赖是双许可且与 MIT 兼容。

### 3.3 协议合规

本项目实现了 ADB 协议，**未复制 AOSP 任何源文件**——`adb.py` 是从协议文档 + 抓包实测独立实现的。这一点在 `docs/ADB协议实现笔记.md` 里明确写了来源方法（中间人代理抓包），且所有结论标注了"文档说的"vs"实测的"。

---

## 四、关键选型评价

### 选型 1 · 自研 ADB 客户端而非调用 adb.exe

**是否当前最佳实践**：**在这个场景下是**，在通用场景下不是。

**生命周期**：adb 协议自 Android 早期至今稳定（`CNXN`/`AUTH`/`OPEN`/`OKAY`/`WRTE`/`CLSE` 六命令二十年未变），自研实现的维护成本可控。

**替换 / 迁移成本**：
- 换成调用 `adb.exe`：成本极低（`adb.py` 的 `shell()` / `pull()` 换实现，`run()` 契约不变，上层零改动），但**会失去"零依赖 + 免安装"这两条核心承诺**
- 换成 `adb-shell`（PyPI）：引入 1 个直接依赖 + 若干间接依赖，破坏零依赖承诺

**判断**：这个场景（用户只有电视，没有 Android SDK，不会在电脑上装 platform-tools）下，自研是**唯一合理选择**。协议层 513 行、CC 最高 8、已被假 adbd 覆盖主要路径——投入产出比合理。

### 选型 2 · 零第三方依赖

**是否当前最佳实践**：**对受众是，对项目本身有代价**。

**生命周期**：零依赖永远不过时。

**替换成本**：零依赖是单向门——一旦引入就很难收回。所以 `cryptography` 只能是可选 extra，不能进 `dependencies`。

**判断**：正确。代价是 100 行手写 DER 解析（应补测试，见质量评估 P0-3）。

### 选型 3 · 纯文件系统数据层 + 目录即注册表

**是否当前最佳实践**：**是**。

**生命周期**：JSON / TXT 的可读性使它们在 10 年内不会过时。

**替换成本**：若要换 SQLite，只需重写 `profiles.py` 的 3 个函数（`list_profiles` / `load_profile` / `Profile.host_groups`）与 `packages.py` 的快照读写，**上层零改动**——因为边界划得清楚。

**判断**：对单机 CLI 是最优解，且迁移路径已经被架构保证。

### 选型 4 · 目录树作为注册表（无插件机制）

**是否当前最佳实践**：**是**。

`profiles.py:97-104` 的 `list_profiles()` 遍历目录自动发现画像。对比需要实现 `importlib.metadata` entry_points 的插件机制，目录树简单到没有 bug 面。

**代价**：无法打包成单文件分发（wheel 里不带 `profiles/`，`pyproject.toml` 的 `[tool.setuptools] packages = ["mitvclean"]` 只包含 Python 包）。**当前用 `pip install -e .`（editable）不暴露这个问题，但 `pip install mitvclean`（非 editable）会得到一个找不到画像的安装。**

这是一个**尚未暴露但已存在的发布缺陷**，见下方 P1。

---

## 五、二开成本评估

| 想做的事 | 难度 | 成本 | 说明 |
|---|---|---|---|
| 加一个新机型的去臃肿清单 | ⭐ 极低 | 复制目录改 `debloat.txt` | 零代码，`CONTRIBUTING.md` 已写清 |
| 加一个新机型的广告域名 | ⭐ 极低 | 跑 `scan` → 整理 `hosts.txt` | 零代码 |
| 改 hosts 分组策略 | ⭐⭐ 低 | 改 `profiles.py` 的 `GROUP_RE` 或直接改 `hosts.txt` 的标记 | 已有 `host_groups()` 抽象 |
| 支持别的品牌电视 | ⭐⭐ 低 | 加 `profiles/<slug>/` + 必要时扩 `ads.py` 的 HINTS | 分层清晰，主要工作在数据层 |
| 做一个 GUI | ⭐⭐⭐ 中 | 需要引入 GUI 框架（**破坏零依赖**）或做本地 Web UI | 建议做本地 Web UI + 保留 CLI core，这样零依赖仍成立 |
| 支持 `adb pair` / 无线调试（Android 11+） | ⭐⭐⭐ 中 | 需要实现 `host:pair:<code>` 服务与 TLS 传输 | 协议层是独立文件，不污染其他层 |
| 加 `scan` 的定时任务 | ⭐⭐ 低 | 加一个 `mitvclean watch` 子命令 + `apscheduler`（或用系统 cron） | `cli.py` 加子命令即可 |
| 打包成 Windows exe | ⭐⭐ 低 | PyInstaller | 但 `profiles/` 是运行时数据，需要 `--add-data` |
| 把 ADB 客户端换成 `adb-shell` | ⭐ 极低 | 重写 `adb.py` 的 `shell`/`pull` | `run()` 契约保持即可，上层零改动 |

**总体判断：二开成本极低。** 主要原因就是架构报告里说的那句——协议层是唯一不透明处，领域层与数据层都可独立替换。

---

## 六、按 P0 / P1 / P2 给技术栈升级建议

| 级别 | 事项 | 位置 | 说明 |
|---|---|---|---|
| **P0** | `cryptography>=3.4` → `>=41.0` | `pyproject.toml` | 避免用户装到含已知 CVE 的旧版本。1 行改动 |
| **P1** | 修 wheel 打包缺失 `profiles/` 的问题 | `pyproject.toml` | `pip install mitvclean`（非 editable）会找不到画像。改用 `package-data` + `MANIFEST.in`，或直接把 `profiles/` 移进 `mitvclean/` 包内 |
| **P1** | CI 接入 `ruff check` | `.github/workflows/test.yml` | 技术栈里唯一的"缺口"。49 条告警从未被卡住 |
| **P1** | CI 接入覆盖率门禁（`coverage report --fail-under=60`） | `.github/workflows/test.yml` | 当前覆盖率 34%（保守口径），无门禁则只会下降 |
| **P2** | 引入 `mypy` 或 `pyright` 做类型检查 | CI | 代码已有大量 `-> str` / `dict[str, str]` 标注，基础很好，补类型检查成本低 |
| **P2** | README 标注 Python 3.9 已 EOL，推荐 3.11+ | `README.md` | 用户机器上的 Python 版本由 OS 决定，主动引导比被动踩坑好 |
| **P2** | 增加 `mitvclean --version` | `mitvclean/__init__.py` | 版本号目前只在 `pyproject.toml`，需加 `__version__` 并在 CI 里校验与 `pyproject.toml` 一致 |
| **P2** | 考虑 `pre-commit` 钩子 | `.pre-commit-config.yaml` | 对单人项目收益有限，CI 门禁已足够 |

---

## 七、结论

技术栈是**这个项目最没有问题的部分**。

零依赖、纯标准库、Python 3.9+、MIT/Apache-2.0 双许可清白、15 组 CI 矩阵全绿、无数据库无容器无云依赖——每一条都指向同一个判断：**这个工具的价值在于它"装得上、用得起、不会连累用户"**，而不是技术含量。

两个必须处理的技术债：

1. **`cryptography>=3.4` 版本下限过松**（P0）——这是整个技术栈里唯一的安全敞口
2. **wheel 打包不含 `profiles/`**（P1）——一个尚未暴露但已存在的发布缺陷，`pip install -e .` 掩盖了它

而技术栈**缺的那一环**，恰好是质量评估里 P1-4 说的那个：**lint 与覆盖率从未进入 CI**。测试跑得很勤（17+5 项，15 组矩阵），但没有任何静态检查关卡——所以 49 条 ruff 告警在 5 次提交里安然无恙地躺到现在。对一个把"零第三方依赖"当成核心承诺的项目 ironically 缺了一环**工具链自检**：项目信任用户的网络，却不信任自己的代码风格。
