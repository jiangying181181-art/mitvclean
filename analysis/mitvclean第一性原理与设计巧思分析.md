# mitvclean 第一性原理与设计巧思分析

- **分析对象**：`mitvclean`
- **数据来源**：本地仓库源码直读（26 个文件、5 次提交）
- **分析日期**：2026-10-21
- **分析角度**：角度三（第一性原理）+ 角度四（设计巧思深挖）

## 结论

**根本问题**：让一个只有 2GB 内存、被厂商塞满后台的安卓电视，在**不卸载任何东西、不变砖、不失去还原能力**的前提下，恢复到可用的响应速度，并且把服务端动态下发的广告掐断。

拆成不可再分的基本事实只有三条：

| # | 基本事实 | 推翻了什么表面答案 |
|---|---|---|
| F1 | **电视没有 root，且厂商在持续对抗** —— adbd 是黑盒、固件锁死属性、组件级禁用被 SecurityException 拒绝 | "禁包"是万能答案 —— 实测贴片广告在 `com.mitv.tvhome` 里，禁整包=进不去桌面，禁组件=被固件拒绝 |
| F2 | **广告地址是服务端下发的，不是编译期常量** | "扒 APK 拿到域名清单" —— APK 里只有 `film_ad_online_server` 这个**键名**，值在服务端 |
| F3 | **用户要的是"可回退"，不是"干净"** | "去广告工具应该删干净" —— 删了就回不去了，用户不敢用 |

13 项设计巧思全部能回溯到这三条事实。其中最值得讲的三项是：

1. **状态快照先于动手**（`packages.py:122-144`）—— F3 的直接产物，把"可回退"从承诺变成机制
2. **两条腿取域名**（`ads.py:99-140`）—— F2 的直接产物，用"并集"代替"择一"
3. **包名白名单正则**（`packages.py:23`）—— F1 的衍生，因为清单是外部输入且会被拼进 shell 命令

**代价也是真金白银的**：手写 DER 解析 100 行（为了零依赖）、CLI 层 CC 17 的一坨函数（为了少写抽象）、以及最刺眼的——**`adswitch` 写操作不记录原值，破坏了 F3 自己建立的闭环**。

---

## 一、基本事实

### F1 · 电视没有 root，厂商在持续对抗

**不可再分的事实**：
1. shell 权限只到 `pm disable-user --user 0`，没有 root
2. 固件可以拒绝 shell 改组件状态
3. adbd 的协议行为是厂商自定义的，黑盒

**推翻了什么**：
"去广告 = 禁包"是表面答案。实测三路都被堵死：

```
$ adb shell pm disable --user 0 com.mitv.tvhome/.PreDetailsActivity
SecurityException: Shell cannot change component state for
  com.mitv.tvhome/com.mitv.tvhome.PreDetailsActivity to 2
```

```
$ adb shell getprop persist.bootvideo.bootanim     # 属性不存在
$ adb shell setprop service.bootvideo 0            # 只读，失败
```

而 `com.mitv.tvhome` 装在 `/data/app/` 而非 `/system/`——这台机器被第三方精简版刷过，桌面和广告组件纠缠在同一个包里，禁整包就是删桌面。

**必然的设计**：
- 只能做**可逆**操作（禁用而非卸载）
- 必须绕开组件层，走 DNS 层
- 协议层必须自研且经过实测校准

### F2 · 广告地址是服务端下发的

**不可再分的事实**：APK 里保存的是**配置键名**，值由服务端在运行时下发。

**推翻了什么**：
"静态扒 APK 就能拿到广告域名清单" —— 只静态扫出来的是**硬编码域名**，不是真实广告通道。

扒 APK 能看到的是键名和模块名：

```
com.mitv.tvhome.ads.filmad.FilmAdBean
com.mitv.tvhome.util.InternalFrontAdCtlManager   →  fetchMiFrontAdConfig
close_after_ad_video_interval_cnt                ← 广告时长计数器
film_ad_online_server                              ← 只有键名，值在服务端
```

`film_ad_online_server` 的值只在 logcat 里出现过。实测抓到的 `cp-ppvideo.cdn.ptmi.gitv.tv` 这类 `cp-` 前缀的 CDN 域名，**静态扫 APK 根本找不到**。

**必然的设计**：
- 必须有动态腿（logcat）
- 动态腿要有触发条件——所以要"两条腿交叉"
- 提取器必须宽松（宁可多收），分类器再分流

### F3 · 用户要的是"可回退"，不是"干净"

**不可再分的事实**：这个工具的操作对象是别人的家用电器。用户不会读代码，但一定会看说明书。**一旦出事，责任在工具。**

**推翻了什么**：
"去广告工具应该删干净" —— 删了就回不去了，用户不敢用，工具就没人用。

**必然的设计**：
- 状态快照先于动手
- 还原只恢复"原本就是 enabled 的"，不动用户自己关掉的
- 桌面 / 系统设置 / 平台输入服务绝不碰
- 包名必须校验，防止清单被当 shell 执行

---

## 二、设计巧思全景

按层组织，共 13 项，覆盖 4 层。

### 层 1 · 协议层（`mitvclean/adb.py`）

#### 巧思 1 · AUTH 签名末尾放 token 本身，而非摘要

```python
# adb.py:121-125
digest_info = bytes.fromhex("3021300906052b0e03021a05000414")
pad_len = k - 3 - len(digest_info) - len(data)
if pad_len < 8:
    raise AdbError("token 太长，无法用 RSA 填充签名")
em = b"\x00\x01" + b"\xff" * pad_len + b"\x00" + digest_info + data
return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
```

**做什么**：用 PKCS#1 type 1 填充 + 15 字节 SHA-1 DigestInfo 前缀 + **原始 token**，而不是标准 PKCS#1 v1.5 签名。

**为什么必然**：adbd 用 `RSA_public_decrypt` 验签后，**把解出的明文和 token 逐字节比较**——它不验证摘要。所以末尾必须是 token 原文。这是 F1（黑盒协议）逼出来的：照文档写会无限循环 AUTH。

#### 巧思 2 · shell v2 长度字段按小端解析

```python
# adb.py:447
length = struct.unpack("<I", payload[i + 1:i + 5])[0]
```

**为什么必然**：shell v2 的帧是 `1 字节类型 + 4 字节长度 + 数据`，而长度是**小端**。按大端读会得到 83886080 这种荒谬值。docstring 里专门留了一行警告："按大端读会得到 83886080 这种荒谬的值"。

#### 巧思 3 · stderr 帧单独收集，不混进结果

```python
# adb.py:451-455
if kind == 0x01:      # stdout
    result += data
elif kind == 0x03:    # stderr
    err += data
# 0x02 (stdin EOF) / 0x04 (exit code) 忽略
```

**为什么必然**：`dev.run()` 的返回值被上层当成"命令的纯输出"用来解析（如 `pm list packages`、`getprop`）。stderr 混进去会让解析静默出错。而且 `pm disable-user` 失败时信息恰恰在 stderr——所以 `last_stderr` 必须留着但不能污染 stdout。

#### 巧思 4 · 设备 quirk 下沉为协议层通用契约

```python
# adb.py:392-404
def run(self, command: str, read_timeout: float = 60.0) -> str:
    try:
        return self.shell(command, read_timeout)
    except AdbError:
        self.close()
        self.connect()
        return self.shell(command, read_timeout)
```

**为什么必然**：小米 adbd 同一连接连续开第二个流会被 CLSE。这是 F1 的直接产物。关键在于**下沉**——`cli.py` 里 20 多处 `dev.run()` 调用一行都不用改。设备 quirk 被封装在协议层，领域层完全无感。

#### 巧思 5 · 主协议与 sync 子协议严格分离

```python
# adb.py:219-224
if cmd == A_SYNC:
    if magic != 0xFFFFFFFF:
        raise AdbError(f"sync 包 magic 不对：{magic:#x}")
elif magic != (cmd ^ 0xFFFFFFFF):
    raise AdbError(f"adb 包校验失败：cmd={cmd:#x} magic={magic:#x}")
```

**为什么必然**：主协议 24 字节小端二进制头、magic 随 command 变化；sync 子协议 8 字节 ASCII 头、magic 固定 0xFFFFFFFF。初版把两者混用，症状是"shell 能通但 pull 超时"——因为恰好错在数据流的另一端。

#### 巧思 6 · 手写 DER 解析，放弃 100 行代码换零依赖

```python
# adb.py:151-184
def _parse_pem_rsa(text: str):
    """从 PEM 文本解析 RSA 的 n/d/e。"""
    ...
    if der[0] != 0x30:
        raise ValueError("期望 SEQUENCE")
```

**为什么必然**：签名需要 RSA 私钥的 (n, d, e)。标准做法是 `pip install cryptography`——但那会打破"零第三方依赖"这条 F1 派生出的核心承诺。所以选择手写 100 行 DER 解析，代价是这块代码没有第三方库的测试覆盖（覆盖率报告里 `adb.py:153-184` 全红）。

**妥协点**：`cryptography` 仍作为**可选依赖**存在（`pyproject.toml` `[project.optional-dependencies] crypto`），有则用它、无则手写。

### 层 2 · 领域层 · 包管理（`mitvclean/packages.py`）

#### 巧思 7 · 包名白名单正则——把清单当不可信输入

```python
# packages.py:23
PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")

# packages.py:60-65
def validate_package(name: str) -> str:
    """校验包名合法性。非法直接抛错——这是防止清单注入的关键一道闸。"""
    name = name.strip()
    if not PACKAGE_RE.fullmatch(name):
        raise PackageError(f"不是合法的包名，拒绝执行：{name!r}")
    return name
```

**为什么必然**：包名最终被拼进 `pm disable-user --user 0 {n}`。清单文件来自仓库、来自用户提交、来自未来的 PR——**是不可信输入**。正则要求至少两段、只允许字母数字下划线和点，`:`、`;`、`$`、空格全部拒绝。这是 F1 + F3 的共同产物。

#### 巧思 8 · 状态快照先于动手

```python
# packages.py:184-185
# 先落盘，再动手
result.record_path = save_record(dev, valid, state, record_dir, tag)
```

**为什么必然**：F3 的字面实现。如果先禁用再记录，中途断电就永远不知道原来哪些包是开着的。顺序不可交换。

#### 巧思 9 · 还原只恢复"原本 enabled"的

```python
# packages.py:213
to_enable = [n for n, s in states.items() if s == STATE_ENABLED]
```

**为什么必然**：用户自己关掉的包（可能是为了省电、可能是不喜欢），工具不该替他打开。快照里记录的是**三态**（`enabled` / `disabled` / `absent`）而不是布尔值，正是为了区分"用户关的"和"工具关的"。

**验证**：`tests/test_offline.py::test_restore_only_reenables_what_was_enabled` 专门测这一条。

#### 巧思 10 · 原子写：先 `.tmp` 再 `replace()`

```python
# packages.py:141-143
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
tmp.replace(path)  # 原子替换，避免半截文件
```

**为什么必然**：快照文件是"可回退"的唯一凭据。写一半的 JSON 会让 `load_record` 直接抛 `PackageError`，用户就再也回不去了。`Path.replace()` 在同一文件系统内是原子的。

#### 巧思 11 · 逐条下发命令，不用分号链式

```python
# packages.py:187-190
for n in targets:
    try:
        out = dev.run(f"pm disable-user --user 0 {n}").strip()
```

**为什么必然**：注释写明"部分国产 ROM 的 shell 会吞掉分号后的语句"。链式 `a; b; c` 在某些 ROM 上只执行第一条且不报错——**静默的半执行**比报错更可怕。逐条下发还能精确定位哪个包失败了。

### 层 3 · 领域层 · 广告处理（`mitvclean/ads.py`）

#### 巧思 12 · 两条腿取域名，用并集不用择一

```python
# cli.py:222
for d in report.from_dex.keys() | log_doms:
    kind = ads.classify(d)
```

**为什么必然**：F2 的直接产物。静态腿能拿到硬编码域名但拿不到服务端下发的；动态腿能拿到真实通道但只在特定功能触发后才有。**任一单独使用都会漏**。用集合并集，并单独记录 `from_dex` / `from_logcat` 两个来源标记（`ads.py:68-69`），让使用者知道每条域名的出处。

#### 巧思 13 · 提取器宽松、分类器严格——两段式

```python
# ads.py:33-37  提取器：宁多勿漏
DOMAIN_RE = re.compile(
    rb"[a-z0-9][a-z0-9-]{1,40}(?:\.[a-z0-9-]{1,30}){1,5}"
    rb"\.(?:xiaomi|com|cn|net|tv|org|io|me)"
    rb"\.(?:com|cn|net|tv|org|io|me)"
)

# ads.py:89-96  分类器：按已知特征分流
def classify(domain: str) -> str:
    low = domain.lower()
    if any(h in low for h in AD_HINTS):
        return "ad"
    if any(h in low for h in SOURCE_HINTS):
        return "source"
    return "other"
```

**为什么必然**：域名在运行时才知道，事先无法穷举。提取阶段用"宽正则"尽量多收（甚至收进 `other`），分类阶段用已知特征表分流。**关键在于把"不确定"显式化**——`other` 这一档存在本身就是在说"这些我还没搞清"。生成 hosts 时只输出 `ad` + `source`（`ads.py:75-78`），`other` 不进清单。

**顺带一提**：`ads.py:99-125` 的 `extract_from_apk` 用 `zipfile` 逐条目解开再扫，因为 APK 是 zip 压缩包，压缩后的字节不可见——`strings` 对它无效。这是个容易踩的坑。

---

## 三、巧思 → 基本事实映射

| 巧思 | 位置 | 服务的基本事实 | 对应层次 |
|---|---|---|---|
| 1. AUTH 签名放 token 原文 | `adb.py:121-125` | F1 黑盒协议 | 协议层 |
| 2. shell v2 小端长度 | `adb.py:447` | F1 黑盒协议 | 协议层 |
| 3. stderr 单独收集 | `adb.py:451-455` | F1 + 输出纯净性 | 协议层 |
| 4. 设备 quirk 下沉为通用契约 | `adb.py:392-404` | F1 厂商对抗 | 协议层 |
| 5. 主协议/sync 严格分离 | `adb.py:219-224` | F1 黑盒协议 | 协议层 |
| 6. 手写 DER 换零依赖 | `adb.py:151-184` | F1 派生（零依赖承诺） | 协议层 |
| 7. 包名白名单正则 | `packages.py:23` | F1 + F3 不可信输入 | 领域层·包 |
| 8. 快照先于动手 | `packages.py:184-185` | **F3 可回退** | 领域层·包 |
| 9. 只恢复原本 enabled 的 | `packages.py:213` | **F3 可回退** | 领域层·包 |
| 10. 原子写快照 | `packages.py:141-143` | F3 凭据完整性 | 领域层·包 |
| 11. 逐条下发不用分号 | `packages.py:187-190` | F1 + F3 静默失败 | 领域层·包 |
| 12. 两条腿取并集 | `cli.py:222` | **F2 服务端下发** | 领域层·广告 |
| 13. 提取宽松/分类严格 | `ads.py:33-37, 89-96` | **F2 事先不可穷举** | 领域层·广告 |

**闭环校验**：三条基本事实全部被至少 3 项巧思服务，没有哪条事实是"提了但没落地"的。

---

## 四、代价与边界

第一性原理分析必须直面缺陷。本项目有三处代价是设计选择的直接结果：

### 代价 1 · `adswitch` 破坏了 F3 自己建立的闭环

```python
# ads.py:217-228
def set_ad_settings(dev: AdbDevice, values: dict[str, str]) -> dict[str, str]:
    """按 {ns.key: value} 写 settings，返回实际写入结果。"""
    out: dict[str, str] = {}
    for full, val in values.items():
        ns, _, key = full.partition(".")
        try:
            res = dev.run(f"settings put {ns} {key} {val}").strip()
            check = dev.run(f"settings get {ns} {key}").strip()
            out[full] = check if check else res
```

**问题**：写之前不读原值、不落盘。用户在 `adswitch --set` 里改了 4 个开关后，**没有任何办法一键还原**。

**为什么这严重**：README 写着"只做**可逆**操作"，项目级承诺是 F3。但 `adswitch` 是唯一破坏该承诺的命令。而 `ads.py` 里已经有现成的 `save_record` 模式可以照抄（`packages.py:122`）。

**修复成本**：低。读原值 → 复用 `save_record` 的原子写 → `restore` 时一并还原。大约 30 行。

### 代价 2 · 手写 DER 解析的测试覆盖为零

`adb.py:153-184`（`_parse_pem_rsa`）在覆盖率报告中整段缺失。它只在"没有 cryptography"这条路径上被走到，而 CI 里**没有安装 cryptography**（`test.yml` 只 `pip install -e .`），所以这段代码在 CI 里从没被执行过。

**为什么严重**：这是唯一一段**手写密码学**的代码。格式解析错了会静默产生错误的签名 → 表现为"AUTH 无限循环"，用户看不出是哪里错。

**修复成本**：低。加一个用已知测试密钥 PEM 的解析单测即可。

### 代价 3 · `other` 分类是无声的盲区

`classify()` 把无法归类的域名全部塞进 `other`，而 `other` **不进 hosts 清单**。这意味着：

- 用户看不到"还有多少域名没搞清楚"
- `scan` 的输出 `domains.json` 里 `other` 是一大坨未标注的域名
- 分类特征表 `AD_HINTS` / `SOURCE_HINTS` 是硬编码的 30 个字符串，覆盖不了的域名就沉默

**为什么这不是 bug 而是边界**：作者在 `ads.py:32` 注释了"从 APK 里提域名：宽松一点，宁可多收"。但**宽松的代价没有在用户可见的地方体现**。

**修复成本**：低。`DomainReport.summary()`（`ads.py:80-86`）加一句"另有 N 个未分类域名未加入清单"即可。

---

## 五、综合结论

这个项目的设计密度高于同规模工具的通常水平。**13 项巧思中，有 9 项直接来自三条基本事实的推导，而不是"我觉得这样好"**。最典型的是巧思 4（设备 quirk 下沉）——它体现的是架构判断力：把脏东西关在正确的层里。

最需要修的是**代价 1**。不是因为它复杂，而是因为它是**项目自己声明的核心承诺的唯一破口**。`adswitch` 加原值快照，是这个项目投入产出比最高的一处改动（约 30 行）。

其次是**演化速度与验证沉淀的失衡**（详见演化分析）：3 小时 13 分钟 5 次提交，其中 4 处协议偏差只在 1 台电视 1 个固件上验证过，且那些"抓包结论"目前只在文档里，没有固化成测试。`ruff check` 实测 49 条告警、CI 里没有 ruff——说明**静态检查从未进入过这个项目的开发闭环**。

**一句话总结**：这是一个**架构判断力远高于工程沉淀速度**的项目。骨架是对的，方向是对的，边界是清楚的；缺的是把"抓包结论"和"静态检查"这两件事从一次性调试变成常规流程。
