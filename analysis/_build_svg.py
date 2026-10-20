"""生成 analysis/svg/ 下的矢量图（单文件、样式全内联、零外链）。"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "svg"
OUT.mkdir(parents=True, exist_ok=True)

FONT = "-apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

INK = "#17201c"
MUTED = "#68736d"
LINE = "#dfe4e1"
GREEN = "#156b4a"
GREEN_D = "#0e5238"
GREEN_S = "#e7f2ec"
BLUE = "#356a91"
BLUE_S = "#e7eff5"
AMBER = "#9a6418"
AMBER_S = "#f8eedc"
RED = "#b83b35"
RED_S = "#f8e9e7"
SURFACE = "#ffffff"
BG = "#f3f5f4"


def head(w, h, title):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="{FONT}">
<rect width="{w}" height="{h}" fill="{BG}"/>
<text x="24" y="34" font-size="17" font-weight="700" fill="{INK}">mitvclean · {title}</text>
<line x1="24" y1="46" x2="{w-24}" y2="46" stroke="{LINE}" stroke-width="1"/>
"""


def foot(w, h, note=""):
    n = f'<text x="24" y="{h-16}" font-size="11.5" fill="{MUTED}">{note}</text>' if note else ""
    return n + "</svg>"


def box(x, y, w, h, fill, stroke=LINE, rx=10):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1"/>')


def txt(x, y, s, size=13, fill=INK, weight="400", anchor="start", ff=None):
    f = f' font-family="{ff}"' if ff else ""
    s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}"'
            f' text-anchor="{anchor}"{f}>{s}</text>')


# ---------------------------------------------------------------- 架构图
def arch():
    W, H = 900, 620
    p = [head(W, H, "架构实现 · 四层单向依赖")]
    layers = [
        (GREEN_S, GREEN, "应用层", "cli.py", "9 个子命令 · 唯一知道用户意图的一层",
         ["cli.py", "argparse 全局参数前后皆可", "异常 → 退出码 2/3/130"]),
        (SURFACE, AMBER, "领域层", "packages.py · ads.py · profiles.py", "可离线测试 · 不依赖网络",
         ["packages.py  可逆包管理 CC14", "ads.py  广告域提取 CC≤10", "profiles.py  机型数据层"]),
        (BLUE_S, BLUE, "协议层", "adb.py", "唯一碰网络的一层 · 513 行 CC≤8",
         ["CNXN/AUTH/OPEN/OKAY/WRTE/CLSE", "shell v2 + sync 子协议", "设备怪癖下沉为通用契约"]),
        (SURFACE, MUTED, "数据层", "profiles/ + work/", "加机型不改代码",
         ["profiles/<slug>/profile.json", "debloat.txt · hosts.txt（73 域名 3 组）", "work/ 状态快照（原子写）"]),
    ]
    y = 66
    for i, (fill, accent, name, files, desc, chips) in enumerate(layers):
        h = 108
        p.append(box(24, y, W - 48, h, fill, LINE))
        p.append(f'<rect x="24" y="{y}" width="5" height="{h}" rx="2.5" fill="{accent}"/>')
        p.append(txt(46, y + 28, name, 15, accent, "700"))
        p.append(txt(120, y + 28, files, 13, INK, "600", ff=MONO))
        p.append(txt(46, y + 50, desc, 12.5, MUTED))
        cx = 46
        for c in chips:
            w = 8.0 + len(c) * 7.0
            p.append(box(cx, y + 62, w, 26, "#ffffff", LINE, 7))
            p.append(txt(cx + 10, y + 79, c, 11.5, "#33453c", "400", ff=MONO))
            cx += w + 10
        if i < 3:
            p.append(txt(W / 2, y + h + 20, "▼", 13, GREEN, "700", "middle"))
        y += h + 30
    p.append(txt(24, y + 16, "依赖方向严格向下 · 领域层从不反向引用应用层 · 循环依赖 0",
                 12, GREEN_D, "600"))
    p.append(foot(W, H, "数据来源：mitvclean 源码直读（b277c37）"))
    return "".join(p)


# ---------------------------------------------------------------- 演化时间线
def evolution():
    W, H = 900, 520
    p = [head(W, H, "架构演化 · 3 小时 13 分钟 5 次提交")]
    stages = [
        ("A", "02:53", "1c9ad54", "功能骨架", GREEN,
         "一次性脚本 → 可安装包", "四个决策全部存活：零依赖 / 数据代码分离 / 可逆 / 防注入"),
        ("B", "03:08", "b46239c", "协议重写", BLUE,
         "主协议与 sync 子协议分帧混用 → 按 AOSP 重写", "诞生假 adbd 测试策略 · adb.py +365 行"),
        ("C", "03:56", "debe01a", "真机校准", AMBER,
         "抓包逐字节比对，4 处偏差全部修正", "AUTH 签名 / CNXN 版本 / banner / v2 小端长度"),
        ("D", "04:06", "d67e9e0", "知识沉淀", GREEN,
         "把抓包结论写成 129 行协议笔记", "明确纠正网上错误说法 · 标注来源"),
        ("E", "04:2x", "b277c37", "协作补齐", BLUE,
         "hosts 分组 + PR/Issue 模板 + 徽章", "领域需求反向驱动基础层 host_groups()"),
    ]
    y = 78
    px = 46
    p.append(f'<line x1="{px}" y1="{y}" x2="{px}" y2="{y + len(stages)*76}" stroke="{LINE}" stroke-width="3"/>')
    for i, (tag, time, sha, title, color, what, detail) in enumerate(stages):
        cy = y + i * 76
        p.append(f'<circle cx="{px}" cy="{cy+14}" r="8" fill="{BG}" stroke="{color}" stroke-width="3"/>')
        p.append(box(px + 26, cy, W - px - 50, 62, SURFACE, LINE))
        p.append(box(px + 26, cy, 6, 62, color, color, 3))
        p.append(txt(px + 46, cy + 24, f"阶段 {tag}", 13.5, color, "700"))
        p.append(txt(px + 118, cy + 24, time, 12, MUTED, "400", ff=MONO))
        p.append(txt(px + 196, cy + 24, sha, 12, MUTED, "400", ff=MONO))
        p.append(txt(px + 300, cy + 24, title, 14, INK, "700"))
        p.append(txt(px + 46, cy + 44, what, 12.5, "#3a4a42"))
        p.append(txt(px + 46, cy + 58, detail, 11.5, MUTED))
    p.append(foot(W, H, "决定性重构：b46239c（协议重写，诞生假 adbd）· debe01a（与参照实现逐字节对齐）"))
    return "".join(p)


# ---------------------------------------------------------------- 质量热力
def quality():
    W, H = 900, 560
    p = [head(W, H, "代码质量 · 复杂度热点与改造分级")]
    rows = [
        ("cmd_doctor", "cli.py:131", 17, "C", RED, "混合三种关注点 · 内层循环重复调 list_packages", "P1"),
        ("disable_packages", "packages.py:158", 14, "C", RED, "判定/落盘/执行三阶段混在一个函数", "P1"),
        ("cmd_debloat", "cli.py:292", 11, "C", RED, "CLI 编排层复杂度过界", "P1"),
        ("cmd_info", "cli.py:90", 10, "B", AMBER, "多项只读探测聚合", "P2"),
        ("cmd_scan", "cli.py:181", 10, "B", AMBER, "两条腿的编排逻辑", "P2"),
        ("clean_ad_cache", "ads.py:240", 10, "B", AMBER, "含唯一递归删除 rm -rf {d}/*", "P0"),
        ("find_ad_settings", "ads.py:191", 9, "B", AMBER, "关键词表硬编码在领域层", "P2"),
        ("enable_packages", "packages.py:201", 8, "B", AMBER, "还原对称性 · 顺序正确", "—"),
        ("extract_from_apk", "ads.py:99", 8, "B", AMBER, "zipfile 逐条目扫描", "—"),
        ("AdbDevice.pull", "adb.py:458", 8, "B", AMBER, "sync 子协议 · 协议层最高", "—"),
    ]
    p.append(txt(24, 76, "函数", 12, MUTED, "700"))
    p.append(txt(250, 76, "位置", 12, MUTED, "700"))
    p.append(txt(390, 76, "CC", 12, MUTED, "700", "middle"))
    p.append(txt(450, 76, "等级", 12, MUTED, "700", "middle"))
    p.append(txt(500, 76, "说明", 12, MUTED, "700"))
    p.append(txt(840, 76, "分级", 12, MUTED, "700", "middle"))
    y = 88
    for name, loc, cc, lvl, color, desc, grade in rows:
        p.append(box(24, y, W - 48, 36, SURFACE, LINE, 8))
        p.append(txt(36, y + 23, name, 12.5, INK, "600", ff=MONO))
        p.append(txt(250, y + 23, loc, 12, MUTED, "400", ff=MONO))
        bw = cc * 11
        p.append(f'<rect x="440" y="{y+11}" width="{bw}" height="14" rx="4" fill="{color}" opacity="0.82"/>')
        p.append(txt(432, y + 23, str(cc), 12, color, "700", "end"))
        p.append(txt(478, y + 23, lvl, 12, color, "700", "middle"))
        p.append(txt(500, y + 23, desc, 12, "#3a4a42"))
        gc = {"P0": RED, "P1": AMBER, "P2": BLUE, "—": MUTED}[grade]
        p.append(txt(840, y + 23, grade, 12, gc, "700", "middle"))
        y += 40
    p.append(box(24, y + 8, W - 48, 84, GREEN_S, "#c4e0d1"))
    p.append(txt(40, y + 32, "总览", 13, GREEN_D, "700"))
    p.append(txt(40, y + 54, "平均 CC 3.76（优）· 覆盖率 34%（保守口径）· ruff 49 条（未进 CI）· 循环依赖 0 · 第三方依赖 0",
                 12.5, "#173b2d"))
    p.append(txt(40, y + 74, "P0 三项：adswitch 不记原值（承诺破口）· rm -rf 缺路径校验 · 手写 DER 解析零测试覆盖",
                 12.5, "#173b2d"))
    p.append(foot(W, H, "工具：radon 6.0.1 / ruff / coverage · 采集于 2026-10-21 · 隔离 venv"))
    return "".join(p)


# ---------------------------------------------------------------- 技术栈矩阵
def stack():
    W, H = 900, 480
    p = [head(W, H, "技术栈 · 七维度矩阵")]
    dims = [
        ("语言", "Python 2 265 行（100%）", GREEN),
        ("运行时", "CPython ≥3.9 · CI 3.9–3.13 × 3 OS = 15 组", GREEN),
        ("框架/库", "0 个第三方库 · socket/struct/zipfile/re 全 stdlib", GREEN),
        ("数据存储", "无数据库 · 文件系统（profiles/ 版本化 + work/ 运行时）", GREEN),
        ("基础设施", "无 · 单机 CLI · 零外部网络出口", GREEN),
        ("构建交付", "pyproject + setuptools · pip install -e . · mitvclean.bat", GREEN),
        ("质量工程化", "自写 runner + 2 个测试 + CI 矩阵 · 无 lint / 无类型检查 / 无覆盖率门禁", AMBER),
    ]
    y = 68
    for name, val, color in dims:
        p.append(box(24, y, W - 48, 46, SURFACE, LINE))
        p.append(f'<rect x="24" y="{y}" width="5" height="46" rx="2.5" fill="{color}"/>')
        p.append(txt(46, y + 28, name, 14, INK, "700"))
        p.append(txt(170, y + 28, val, 12.8, "#3a4a42"))
        y += 52
    p.append(box(24, y + 6, W - 48, 74, BLUE_S, "#c9dbe8"))
    p.append(txt(40, y + 30, "依赖健康度", 13, BLUE, "700"))
    p.append(txt(40, y + 52, "直接依赖 0 · 间接依赖 0（装 crypto extra 时 3 个）· 已知 CVE 传导路径 0 条",
                 12.5, "#234a66"))
    p.append(txt(40, y + 70, "唯一敞口：cryptography>=3.4 版本下限过松（2019 年版本）→ 建议提到 >=41.0",
                 12.5, RED))
    p.append(foot(W, H, "许可证：MIT（项目）· Apache-2.0/BSD 双许可（唯一可选依赖）· 零风险"))
    return "".join(p)


# ---------------------------------------------------------------- 思维导图
def mindmap():
    W, H = 900, 700
    p = [head(W, H, "项目全景 · 三分钟讲清")]
    root_x, root_y = 450, 96
    p.append(f'<rect x="{root_x-76}" y="{root_y-22}" width="152" height="40" rx="10" fill="{GREEN_D}"/>')
    p.append(txt(root_x, root_y + 5, "mitvclean", 17, "#edf4f0", "700", "middle"))
    branches = [
        ("定位", 90, ["小米电视去臃肿去广告", "纯 Python 零依赖", "只做可逆操作", "CLI 单机工具"], GREEN),
        ("技术栈", 240, ["Python 3.9+ · MIT", "零第三方依赖", "CI 15 组矩阵", "stdlib 实现"], BLUE),
        ("分层架构", 390, ["应用层 cli.py", "领域层 packages/ads/profiles", "协议层 adb.py", "数据层 profiles/"], GREEN),
        ("核心链路", 540, ["debloat 判定→落盘→执行", "scan 两腿取并集", "hosts --group 分批", "restore 只恢复 enabled"], AMBER),
        ("关键设计", 690, ["状态快照先于动手", "原子写快照", "包名白名单正则", "设备怪癖下沉"], GREEN),
        ("质量与风险", 840, ["平均 CC 3.76（优）", "覆盖率 34%", "adswitch 不可逆 P0", "ruff 未进 CI"], RED),
    ]
    for name, bx, items, color in branches:
        p.append(f'<path d="M {root_x} {root_y+22} C {root_x} {root_y+70}, {bx} {root_y+40}, {bx} {root_y+52}" '
                 f'fill="none" stroke="{LINE}" stroke-width="2"/>')
        p.append(f'<rect x="{bx-58}" y="{root_y+52}" width="116" height="30" rx="8" fill="{color}"/>')
        p.append(txt(bx, root_y + 72, name, 13.5, "#ffffff", "700", "middle"))
        y = root_y + 100
        for it in items:
            p.append(f'<rect x="{bx-116}" y="{y}" width="232" height="30" rx="7" fill="{SURFACE}" stroke="{LINE}"/>')
            p.append(txt(bx - 104, y + 20, it, 12.3, "#33423b"))
            y += 36
    p.append(txt(24, H - 40, "演化脉络：骨架一次成型 → 协议重写 → 真机逐字节校准 → 知识沉淀 → 协作补齐",
                 12.5, GREEN_D, "600"))
    p.append(foot(W, H, "节点均可回溯到 analysis/ 下五份报告的对应章节"))
    return "".join(p)


for name, fn in [
    ("mitvclean-架构图.svg", arch),
    ("mitvclean-演化时间线.svg", evolution),
    ("mitvclean-质量热力图.svg", quality),
    ("mitvclean-技术栈矩阵.svg", stack),
    ("mitvclean-全景思维导图.svg", mindmap),
]:
    (OUT / name).write_text(fn(), encoding="utf-8")
    print("written:", name)
