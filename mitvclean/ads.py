"""
mitvclean.ads — 广告处理

三层手段，按代价从低到高：

1. **系统开关**（最优）：部分 ROM 把广告开关放在 settings 里，直接改。
   本项目在探测阶段自动找出候选键并读取当前值。
2. **禁用广告包**：广告以独立包存在时，用 pm disable-user 禁用。
3. **hosts / DNS 拦截**（兜底）：广告素材由内容源服务端动态下发，
   域名会变，只能拦 DNS。本项目提供域名清单 + 从设备上提取域名的工具。

关于"从设备上提取域名"（本项目最有价值的部分）：

广告下发地址常由服务端配置（APK 里只有 `film_ad_online_server` 这样的键名，
值是服务端给的），所以**只静态分析 APK 会漏**。正确做法是两条腿走路：

  · 静态：从设备上 pull 出相关 APK，正则提取所有域名
  · 动态：抓 logcat，里面有配置接口返回的完整 JSON，能看到真实域名

两条腿的并集才是可信清单。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .adb import AdbDevice

# 从 APK 里提域名：宽松一点，宁可多收
DOMAIN_RE = re.compile(
    rb"[a-z0-9][a-z0-9-]{1,40}(?:\.[a-z0-9-]{1,30}){1,5}"
    rb"\.(?:xiaomi|com|cn|net|tv|org|io|me)"
    rb"\.(?:com|cn|net|tv|org|io|me)"
)

# APK 里需要扫描的条目后缀
SCAN_SUFFIXES = (".dex", ".arsc", ".xml", ".so", ".json", ".txt", ".properties")

# 已知与广告相关的域名特征
AD_HINTS = (
    # 小米广告配置与交易平台
    "ad.xiaomi", "ad1.xiaomi", "ad.mi.com", "sdkconfig.ad", "sdkconfig.xiaomi",
    "track.ad", "monitor-check.ad", "adx.v.mitvos", "ad.hpplay", "adeng.hpplay",
    # 各视频内容方的广告通道
    "cupid", "ptqy", "mgtv.com", "cibntv", "atiane", "aiseet", "aiseejapp",
    "gvod.", "mobaliyun", "cp-", "filmtv",
    # 代码里的模块名
    "filmad", "frontad", "flowad",
)

# 内容源特征（广告由这些内容源下发，拦它们是去贴片广告的关键）
SOURCE_HINTS = (
    "pandora", "mitvos", "ptmi.gitv", "ptxl.gitv", "migc", "migutv",
    "enttv", "bestv", "kuyun", "icntv", "market.xiaomi", "mddmcn", "gitv.tv",
)


@dataclass
class DomainReport:
    """域名提取结果。"""

    ad_domains: set[str] = field(default_factory=set)
    source_domains: set[str] = field(default_factory=set)
    other_domains: set[str] = field(default_factory=set)
    from_dex: dict[str, int] = field(default_factory=dict)
    from_logcat: set[str] = field(default_factory=set)
    apks_scanned: list[str] = field(default_factory=list)

    def all_domains(self) -> set[str]:
        return self.ad_domains | self.source_domains | self.other_domains

    def to_hosts_lines(self) -> list[str]:
        """生成 hosts 规则行（IP 在前，小米路由器的格式要求）。"""
        ordered = sorted(self.ad_domains) + sorted(self.source_domains)
        return [f"127.0.0.1 {d}" for d in ordered]

    def summary(self) -> str:
        return (
            f"广告域 {len(self.ad_domains)} 个 / "
            f"内容源域 {len(self.source_domains)} 个 / "
            f"其他 {len(self.other_domains)} 个；"
            f"APK {len(self.apks_scanned)} 个，logcat 新增 {len(self.from_logcat)} 个"
        )


def classify(domain: str) -> str:
    """把域名归到 广告 / 内容源 / 其他。"""
    low = domain.lower()
    if any(h in low for h in AD_HINTS):
        return "ad"
    if any(h in low for h in SOURCE_HINTS):
        return "source"
    return "other"


def extract_from_apk(apk_path: str | Path) -> tuple[set[str], dict[str, int]]:
    """从一个 APK 里提取域名。

    APK 是 zip 压缩包，strings 直接读是读不到的（压缩后的字节不可见），
    必须用 zipfile 逐条目解开再扫。
    """
    domains: set[str] = set()
    hits: dict[str, int] = {}
    p = Path(apk_path)
    try:
        z = zipfile.ZipFile(p)
    except Exception as e:
        raise RuntimeError(f"无法打开 APK {p}：{e}") from None
    with z:
        for name in z.namelist():
            if not name.endswith(SCAN_SUFFIXES):
                continue
            try:
                data = z.read(name)
            except Exception:
                continue
            for m in DOMAIN_RE.findall(data):
                d = m.decode("utf-8", "replace")
                if d and not d[0].isdigit():
                    domains.add(d)
                    hits[d] = hits.get(d, 0) + 1
    return domains, hits


def extract_from_logcat(text: str) -> set[str]:
    """从 logcat 文本里提取域名。

    这一步能拿到服务端动态下发的地址（APK 里只有键名没有值），
    是静态分析拿不到的部分。
    """
    # 宽一点的正则：任何常见后缀
    pat = re.compile(
        r"[a-z0-9][a-z0-9.-]{2,60}"
        r"\.(?:xiaomi|com|cn|net|tv|org|io|me|mitvos|gitv)"
        r"\.(?:com|cn|net|tv|org|io|me)"
    )
    return {m for m in pat.findall(text.lower()) if not m[0].isdigit()}


def pull_apks(
    dev: AdbDevice,
    packages: list[str],
    out_dir: str | Path,
) -> list[str]:
    """把指定包的 base.apk 从设备拉到本地。

    注意：只有 /data/app 下（用户安装的应用）能这样读出来，
    /system/app 下的系统应用 shell 读不到 base.apk 也没必要读。
    """
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    out = dev.run("pm list packages -f")
    paths: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            rest = line[len("package:"):]
            if "=" in rest:
                path, name = rest.split("=", 1)
                paths[name] = path
    pulled: list[str] = []
    for pkg in packages:
        src = paths.get(pkg)
        if not src or not src.startswith("/data/app/"):
            continue
        tmp = f"/data/local/tmp/{pkg}.apk"
        dev.run(f"cp {src} {tmp}")
        local = d / f"{pkg}.apk"
        try:
            dev.pull(tmp, str(local))
            pulled.append(pkg)
        except Exception as e:
            print(f"  ! 拉取 {pkg} 失败：{e}")
        finally:
            dev.run(f"rm -f {tmp}")
    return pulled


def grab_logcat(dev: AdbDevice, out_file: str | Path) -> Path:
    """把设备当前的 logcat 拉到本地。"""
    p = Path(out_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = dev.run("logcat -d -v time", read_timeout=120)
    p.write_text(text, encoding="utf-8", errors="replace")
    return p


def find_ad_settings(dev: AdbDevice) -> dict[str, str]:
    """在 settings 里找疑似广告相关的键及其当前值。

    只读，不改。返回 {键: 值}（值为 "null" 的跳过）。
    """
    found: dict[str, str] = {}
    keywords = ("ad", "splash", "boot", "front", "skip", "vip")
    for ns in ("global", "system", "secure"):
        try:
            listing = dev.run(f"settings list {ns}")
        except Exception:
            continue
        for line in listing.splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            key = line.split("=", 1)[0]
            # 过滤掉明显无关的键，避免噪音
            if any(k in key.lower() for k in keywords) and not any(
                x in key.lower()
                for x in ("bluetooth", "keyboard", "alarm", "brightness", "input")
            ):
                found[f"{ns}.{key}"] = line.split("=", 1)[1]
    return found


def set_ad_settings(dev: AdbDevice, values: dict[str, str]) -> dict[str, str]:
    """按 {ns.key: value} 写 settings，返回实际写入结果。"""
    out: dict[str, str] = {}
    for full, val in values.items():
        ns, _, key = full.partition(".")
        try:
            res = dev.run(f"settings put {ns} {key} {val}").strip()
            check = dev.run(f"settings get {ns} {key}").strip()
            out[full] = check if check else res
        except Exception as e:
            out[full] = f"ERROR: {e}"
    return out


# 已知可以直接关掉的广告开关（不同 ROM 键名不同，取交集再由使用者确认）
KNOWN_AD_SWITCHES = {
    "system.boot_ad": "0",
    "system.boot_ad_switch_show": "0",
    "global.predetail_ad_enable": "0",
    "system.show_boot_ad": "0",
}


def clean_ad_cache(
    dev: AdbDevice,
    packages: list[str],
    sdcard_cache_dirs: list[str] | None = None,
) -> dict[str, str]:
    """清广告缓存。

    两处：
      · 应用私有目录 —— 只能用 pm clear（会连带清应用数据，可接受）
      · sdcard 的 app 目录 —— shell 可读可写，可以只删缓存子目录
    """
    out: dict[str, str] = {}
    for p in packages:
        try:
            out[f"pm clear {p}"] = dev.run(f"pm clear {p}").strip()
        except Exception as e:
            out[f"pm clear {p}"] = f"ERROR: {e}"
    for d in sdcard_cache_dirs or []:
        try:
            listing = dev.run(f"ls {d}")
            if "No such file" in listing or not listing.strip():
                continue
            n = len([x for x in listing.splitlines() if x.strip()])
            dev.run(f"rm -rf {d}/*")
            out[d] = f"已清空（原 {n} 项）"
        except Exception as e:
            out[d] = f"ERROR: {e}"
    return out
