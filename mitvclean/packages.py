"""
mitvclean.packages — 包状态管理（可逆）

设计原则（来自 cleanyourtv 的 fail-safe 实践）：
  1. 只用 `pm disable-user` 禁用，**永不 uninstall** —— 禁用可逆，卸载不可逆
  2. 动手之前先把"每个包的原始状态"落盘，没有记录就不动手
  3. 还原时只恢复"记录里是 enabled"的包 —— 用户自己之前关掉的不会被误开
  4. 包名必须是合法的点分标识符，防止清单里的内容被当成 shell 片段执行
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .adb import AdbDevice

# 合法的 Android 包名：字母或下划线开头，段之间用点分隔
PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")

STATE_ENABLED = "enabled"
STATE_DISABLED = "disabled"
STATE_ABSENT = "absent"


class PackageError(RuntimeError):
    pass


@dataclass
class PackageState:
    """一个包在操作前后的状态。"""

    name: str
    state: str
    note: str = ""

    @property
    def exists(self) -> bool:
        return self.state != STATE_ABSENT


@dataclass
class DebloatResult:
    disabled: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_absent: list[str] = field(default_factory=list)
    skipped_already: list[str] = field(default_factory=list)
    record_path: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.failed


def validate_package(name: str) -> str:
    """校验包名合法性。非法直接抛错——这是防止清单注入的关键一道闸。"""
    name = name.strip()
    if not PACKAGE_RE.fullmatch(name):
        raise PackageError(f"不是合法的包名，拒绝执行：{name!r}")
    return name


def list_packages(dev: AdbDevice, disabled_only: bool = False) -> set[str]:
    """列出设备上的包。"""
    cmd = "pm list packages -d" if disabled_only else "pm list packages"
    out = dev.shell(cmd)
    result = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            result.add(line[len("package:"):].strip())
    return result


def read_list(path: str | Path) -> list[str]:
    """读去臃肿清单。

    格式：每行一个包名，`#` 之后是注释。
    会剥掉 UTF-8 BOM（Windows 编辑器可能加），并去重保序。
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    names: list[str] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = line.split()[0]
        try:
            name = validate_package(name)
        except PackageError as e:
            raise PackageError(f"{p}:{lineno}: {e}") from None
        if name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        raise PackageError(f"{p} 里没有解析出任何包名")
    return names


def query_state(dev: AdbDevice, names: list[str]) -> dict[str, str]:
    """查一批包当前的状态。"""
    installed = list_packages(dev)
    disabled = list_packages(dev, disabled_only=True)
    out: dict[str, str] = {}
    for n in names:
        if n not in installed:
            out[n] = STATE_ABSENT
        elif n in disabled:
            out[n] = STATE_DISABLED
        else:
            out[n] = STATE_ENABLED
    return out


def save_record(
    dev: AdbDevice,
    names: list[str],
    state: dict[str, str],
    record_dir: str | Path,
    tag: str = "",
) -> Path:
    """把操作前的状态落盘。**必须先落盘再动手。**"""
    d = Path(record_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"state-{stamp}{('-' + tag) if tag else ''}.json"
    path = d / name
    payload = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": dev.host,
        "port": dev.port,
        "packages": state,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # 原子替换，避免半截文件
    return path


def load_record(path: str | Path) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise PackageError(f"{p} 不是可用的状态记录（{e}）") from None
    if "packages" not in data:
        raise PackageError(f"{p} 的记录格式不认识")
    return data


def disable_packages(
    dev: AdbDevice,
    names: list[str],
    record_dir: str | Path,
    tag: str = "",
    dry_run: bool = False,
) -> DebloatResult:
    """禁用一批包（可逆）。

    流程：查状态 → 落盘 → 逐条禁用 → 复查验证。
    """
    result = DebloatResult()
    valid = [validate_package(n) for n in names]
    state = query_state(dev, valid)

    result.skipped_absent = [n for n, s in state.items() if s == STATE_ABSENT]
    result.skipped_already = [n for n, s in state.items() if s == STATE_DISABLED]
    targets = [n for n, s in state.items() if s == STATE_ENABLED]

    if not targets:
        return result

    if dry_run:
        result.disabled = targets
        return result

    # 先落盘，再动手
    result.record_path = save_record(dev, valid, state, record_dir, tag)

    for n in targets:
        try:
            out = dev.shell(f"pm disable-user --user 0 {n}").strip()
        except Exception as e:
            result.failed.append((n, str(e)))
            continue
        if "disabled" in out.lower():
            result.disabled.append(n)
        else:
            result.failed.append((n, out or "(无输出)"))

    return result


def enable_packages(
    dev: AdbDevice,
    record_path: str | Path,
    dry_run: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    """按状态记录恢复。

    只恢复记录里状态是 enabled 的包；absent / disabled 的一律不动。
    返回 (恢复成功的包, 失败的包)。
    """
    record = load_record(record_path)
    states: dict[str, str] = record["packages"]
    to_enable = [n for n, s in states.items() if s == STATE_ENABLED]
    if dry_run:
        return to_enable, []

    ok: list[str] = []
    failed: list[tuple[str, str]] = []
    for n in to_enable:
        try:
            out = dev.shell(f"pm enable {n}").strip()
        except Exception as e:
            failed.append((n, str(e)))
            continue
        if "enabled" in out.lower():
            ok.append(n)
        else:
            failed.append((n, out or "(无输出)"))
    return ok, failed


def clear_cache(dev: AdbDevice, packages: list[str]) -> dict[str, str]:
    """清缓存（pm clear）。只对用户应用有效，系统应用会返回失败。"""
    out: dict[str, str] = {}
    for p in packages:
        try:
            out[p] = dev.shell(f"pm clear {p}").strip()
        except Exception as e:
            out[p] = f"ERROR: {e}"
    return out


def export_csv(state: dict[str, str], path: str | Path) -> Path:
    """把状态导出成 CSV，方便人工检查。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["包名", "操作前状态"])
        for n, s in state.items():
            w.writerow([n, s])
    return p
