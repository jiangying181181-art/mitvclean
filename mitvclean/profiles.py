"""
mitvclean.profiles — 设备画像（机型适配数据层）

一个 profile 描述一类设备：它的去臃肿包清单、hosts 拦截清单、已知注意事项。

目录结构：
    profiles/
      mitv-ansp0/
        profile.json        # 元信息：型号、代号、系统版本、注意事项
        debloat.txt         # 去臃肿包清单（每行一个包名，# 注释）
        hosts.txt           # hosts 拦截清单（每行一个域名或完整规则）

新增机型只要复制一个目录改内容，不需要动代码。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


class ProfileError(RuntimeError):
    pass


@dataclass
class Profile:
    """一个机型画像。"""

    slug: str
    meta: dict
    debloat_path: Path
    hosts_path: Path
    root: Path

    @property
    def title(self) -> str:
        return self.meta.get("title", self.slug)

    @property
    def model(self) -> str:
        return self.meta.get("model", "")

    @property
    def android(self) -> str:
        return self.meta.get("android", "")

    @property
    def notes(self) -> list[str]:
        return self.meta.get("notes", [])

    @property
    def verified(self) -> bool:
        return bool(self.meta.get("verified", False))

    def summary(self) -> str:
        bits = [f"{self.title}"]
        if self.model:
            bits.append(f"型号 {self.model}")
        if self.android:
            bits.append(self.android)
        bits.append("已实机验证" if self.verified else "未实机验证")
        return " · ".join(bits)


def _load_meta(path: Path) -> dict:
    p = path / "profile.json"
    if not p.exists():
        raise ProfileError(f"{path} 缺少 profile.json")
    return json.loads(p.read_text(encoding="utf-8"))


def load_profile(slug: str) -> Profile:
    """按 slug 加载机型画像。"""
    root = PROFILES_DIR / slug
    if not root.is_dir():
        available = ", ".join(list_profiles()) or "（无）"
        raise ProfileError(f"找不到机型画像 {slug!r}。现有：{available}")
    debloat = root / "debloat.txt"
    hosts = root / "hosts.txt"
    if not debloat.exists():
        raise ProfileError(f"{root} 缺少 debloat.txt")
    if not hosts.exists():
        raise ProfileError(f"{root} 缺少 hosts.txt")
    return Profile(
        slug=slug,
        meta=_load_meta(root),
        debloat_path=debloat,
        hosts_path=hosts,
        root=root,
    )


def list_profiles() -> list[str]:
    """列出所有可用的机型画像。"""
    if not PROFILES_DIR.is_dir():
        return []
    out = []
    for d in sorted(PROFILES_DIR.iterdir()):
        if d.is_dir() and (d / "profile.json").exists():
            out.append(d.name)
    return out


def profile_table() -> str:
    """生成机型列表表格（给 CLI 打印用）。"""
    rows = []
    for slug in list_profiles():
        try:
            p = load_profile(slug)
        except ProfileError:
            continue
        rows.append((slug, p.title, p.android, "是" if p.verified else "否"))
    if not rows:
        return "（还没有机型画像）"
    lines = [f"{'slug':<20} {'名称':<34} {'系统':<16} 实机验证"]
    for r in rows:
        lines.append(f"{r[0]:<20} {r[1]:<34} {r[2]:<16} {r[3]}")
    return "\n".join(lines)
