"""
mitvclean.cli — 命令行入口

子命令：
    info                     读设备信息（型号/系统/内存/包统计）
    profiles                 列出可用机型画像
    scan                     提取广告域名（静态 APK + 动态 logcat），生成 hosts 清单
    debloat                  按画像禁用后台包（可逆）
    adswitch                 读/写系统里的广告开关
    cache                    清广告缓存
    hosts                    生成 hosts 清单（不写设备）
    restore                  按状态记录还原
    doctor                   体检：一次性报告这台电视的现状与可优化点

通用参数：
    --host <ip>              电视 IP（默认读环境变量 MITV_HOST）
    --port <n>               端口（默认 5555）
    --profile <slug>         机型画像（默认按设备代号自动匹配）
    --dry-run                只报告不执行
    --out <dir>              输出目录（默认 ./work）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import ads, packages
from .adb import AdbDevice, AdbError
from .profiles import ProfileError, list_profiles, load_profile, profile_table

DEFAULT_OUT = "work"


def _host(args) -> str:
    host = args.host or os.environ.get("MITV_HOST", "")
    if not host:
        raise SystemExit(
            "请指定电视 IP：--host 192.168.1.50，或设置环境变量 MITV_HOST"
        )
    return host


def _connect(args) -> AdbDevice:
    try:
        return AdbDevice(_host(args), args.port).connect()
    except AdbError as e:
        raise SystemExit(
            f"连不上电视 {_host(args)}:{args.port}\n"
            f"  {e}\n"
            "  请确认：\n"
            "   1) 电视和电脑在同一个网络\n"
            "   2) 电视上 设置 -> 账号与安全 -> ADB 调试 = 允许\n"
            "   3) 电视上已确认「允许 USB 调试」弹窗"
        ) from None


def _auto_profile(dev: AdbDevice) -> str | None:
    """按设备代号自动匹配机型画像。"""
    device = dev.run("getprop ro.product.device").strip()
    model = dev.run("getprop ro.product.model").strip()
    for slug in list_profiles():
        p = load_profile(slug)
        meta = p.meta
        for key in (device, model):
            if key and key.lower() in json.dumps(meta).lower():
                return slug
    return None


def _profile_for(args, dev) -> str:
    slug = args.profile or _auto_profile(dev)
    if not slug:
        raise SystemExit(
            "没识别出机型，请用 --profile 指定。可用画像：\n" + profile_table()
        )
    return slug


# ---------------------------------------------------------------- 子命令
def cmd_profiles(args) -> int:
    print("可用机型画像：")
    print(profile_table())
    return 0


def cmd_info(args) -> int:
    with _connect(args) as dev:
        props = {}
        for p in (
            "ro.product.model", "ro.product.device", "ro.product.manufacturer",
            "ro.build.version.release", "ro.build.version.sdk",
            "ro.build.display.id", "ro.board.platform",
        ):
            props[p] = dev.run(f"getprop {p}").strip()
        mem = {}
        for line in dev.run("cat /proc/meminfo").splitlines():
            for k in ("MemTotal", "MemFree", "MemAvailable"):
                if line.startswith(k):
                    mem[k] = line.split(":")[0].strip() + " " + line.split(":")[1].strip()
        installed = packages.list_packages(dev)
        disabled = packages.list_packages(dev, disabled_only=True)
        home = dev.run(
            "cmd package resolve-activity --brief -a android.intent.action.MAIN "
            "-c android.intent.category.HOME"
        ).strip().splitlines()
        slug = _auto_profile(dev)

        print("设备信息")
        print("-" * 56)
        for k, v in props.items():
            if v:
                print(f"  {k:<28} {v}")
        print()
        print("内存")
        for k, v in mem.items():
            print(f"  {k:<28} {v}")
        print()
        print(f"  已安装包 {len(installed)} 个 / 已禁用 {len(disabled)} 个")
        print(f"  HOME 组件 {home[-1] if home else '未知'}")
        if slug:
            print(f"  匹配到的机型画像 {slug}")
        else:
            print("  没有匹配到机型画像（可用 --profile 手动指定）")
    return 0


def cmd_doctor(args) -> int:
    """体检：一次报告现状 + 可优化点。"""
    with _connect(args) as dev:
        model = dev.run("getprop ro.product.model").strip()
        release = dev.run("getprop ro.build.version.release").strip()
        print("=" * 60)
        print(f"  {model} · Android {release}")
        print("=" * 60)

        print("\n[1] 广告相关系统设置（当前值）")
        found = ads.find_ad_settings(dev)
        if found:
            for k, v in sorted(found.items()):
                print(f"    {k} = {v}")
        else:
            print("    没有找到明显的广告开关")

        print("\n[2] 已知广告包（已启用则建议禁用）")
        for slug in list_profiles():
            p = load_profile(slug)
            names = packages.read_list(p.debloat_path)
            installed = packages.list_packages(dev)
            disabled = packages.list_packages(dev, disabled_only=True)
            present = [n for n in names if n in installed]
            on = [n for n in present if n not in disabled]
            if on:
                print(f"    画像 {slug}：{len(on)} 个包已启用")
                for n in on[:12]:
                    print(f"        {n}")
                if len(on) > 12:
                    print(f"        ...（共 {len(on)} 个）")

        print("\n[3] sdcard 上的广告缓存")
        for d in (
            "/sdcard/Android/data/com.mitv.tvhome/cache/miad",
            "/sdcard/Android/data/com.mitv.tvhome/cache/video-cache",
        ):
            try:
                listing = dev.run(f"ls {d}")
                if listing.strip() and "No such file" not in listing:
                    n = len([x for x in listing.splitlines() if x.strip()])
                    print(f"    {d}  ({n} 项)")
            except Exception:
                pass

        print("\n[4] 可用的画像")
        print(profile_table())
    return 0


def cmd_scan(args) -> int:
    """提取广告域名：静态 APK + 动态 logcat。"""
    out = Path(args.out or DEFAULT_OUT)
    out.mkdir(parents=True, exist_ok=True)
    report = ads.DomainReport()

    with _connect(args) as dev:
        model = dev.run("getprop ro.product.model").strip()
        device = dev.run("getprop ro.product.device").strip()
        print(f"设备：{model} / {device}")

        # 1) 动态：logcat（服务端下发的域名只有这里有）
        print("\n[1/3] 抓取 logcat…")
        try:
            log_file = ads.grab_logcat(dev, out / "logcat.txt")
            log_doms = ads.extract_from_logcat(log_file.read_text(encoding="utf-8", errors="replace"))
            report.from_logcat = log_doms
            print(f"  提取到 {len(log_doms)} 个域名 → {log_file}")
        except Exception as e:
            print(f"  ! logcat 抓取失败：{e}")
            log_doms = set()

        # 2) 静态：pull 相关 APK
        apks = args.apk or [
            "com.mitv.tvhome", "com.mitv.videoplayer", "com.xiaomi.eetv.litehome",
        ]
        print(f"\n[2/3] 拉取 APK：{', '.join(apks)}")
        apk_dir = out / "apk"
        try:
            pulled = ads.pull_apks(dev, apks, apk_dir)
            report.apks_scanned = pulled
            for pkg in pulled:
                doms, hits = ads.extract_from_apk(apk_dir / f"{pkg}.apk")
                for d in doms:
                    report.from_dex[d] = report.from_dex.get(d, 0) + hits.get(d, 0)
                print(f"  {pkg}: {len(doms)} 个域名")
        except Exception as e:
            print(f"  ! APK 提取失败：{e}")

        # 3) 归类
        print("\n[3/3] 归类…")
        for d in report.from_dex.keys() | log_doms:
            kind = ads.classify(d)
            if kind == "ad":
                report.ad_domains.add(d)
            elif kind == "source":
                report.source_domains.add(d)
            else:
                report.other_domains.add(d)

    hosts_file = out / "hosts-scan.txt"
    hosts_file.write_text(
        "\n".join(report.to_hosts_lines()) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "domains.json").write_text(
        json.dumps(
            {
                "ad": sorted(report.ad_domains),
                "source": sorted(report.source_domains),
                "other": sorted(report.other_domains),
                "from_logcat": sorted(report.from_logcat),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print()
    print(report.summary())
    print(f"  hosts 清单 → {hosts_file}")
    print(f"  域名明细   → {out / 'domains.json'}")
    print()
    print("把 hosts 清单加到路由器的「自定义 Hosts」（小米路由器在米家 App 里）")
    return 0


def cmd_hosts(args) -> int:
    """按画像生成 hosts 清单。

    默认按“组”分文件输出：第 1 组是纯广告域（拦了没副作用），第 2 组是
    内容源域（拦了对应 App 会打不开）。用 --group N 只出某一组，
    用 --group all 出一份全量。
    """
    out = Path(args.out or DEFAULT_OUT)
    out.mkdir(parents=True, exist_ok=True)
    slug = args.profile
    if not slug:
        with _connect(args) as dev:
            slug = _profile_for(args, dev)
    p = load_profile(slug)

    groups = p.host_groups()
    if not groups:
        print(f"画像 {slug} 的 hosts.txt 里没有域名")
        return 1

    want = getattr(args, "group", None) or "all"

    def write(name: str, title: str, domains: list[str]) -> Path:
        lines = [
            f"# mitvclean 生成 · 画像 {slug} · {title}",
            f"# {p.summary()}",
            "# 格式：IP地址 域名（IP 在前，小米路由器要求）",
            "# 用法：米家 App -> 路由器 -> 工具箱 -> 自定义 Hosts",
            "#",
            "# ⚠️ 内容源域名拦掉后该内容源会打不开 —— 哪条不行删哪条即可",
            "",
        ]
        lines += [f"127.0.0.1 {d}" for d in domains]
        f = out / name
        f.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return f

    if want == "all":
        all_domains = [d for _, ds in groups for d in ds]
        f = write(f"hosts-{slug}.txt", "全部", all_domains)
        print(f"已生成 {f}（{len(all_domains)} 条规则）")
    else:
        try:
            idx = int(want)
        except ValueError:
            print(f"--group 只能是数字或 all，收到 {want!r}")
            return 2
        if idx < 1 or idx > len(groups):
            print(f"画像 {slug} 只有 {len(groups)} 组，没有第 {idx} 组")
            return 2
        title, domains = groups[idx - 1]
        f = write(f"hosts-{slug}-group{idx}.txt", f"第 {idx} 组 · {title}", domains)
        print(f"已生成 {f}（{len(domains)} 条规则）")

    print()
    print("可用分组（分批生效，副作用从小到大）：")
    for i, (title, ds) in enumerate(groups, 1):
        print(f"  第 {i} 组（{len(ds):>2} 条）{title}")
    print()
    print("粘贴位置：米家 App -> 路由器 -> 工具箱 -> 自定义 Hosts")
    return 0


def cmd_debloat(args) -> int:
    slug = args.profile
    with _connect(args) as dev:
        if not slug:
            slug = _profile_for(args, dev)
        p = load_profile(slug)
        names = packages.read_list(p.debloat_path)
        print(f"画像 {slug}：{p.title}")
        print(f"清单 {len(names)} 个包")
        if args.dry_run:
            print("\n[dry-run] 将要禁用：")
            res = packages.disable_packages(dev, names, args.out or DEFAULT_OUT, dry_run=True)
            for n in res.disabled:
                print(f"    {n}")
            print(f"\n合计 {len(res.disabled)} 个（未实际执行）")
            return 0
        res = packages.disable_packages(
            dev, names, args.out or DEFAULT_OUT, tag=slug
        )
    print(f"\n已禁用 {len(res.disabled)} 个")
    if res.failed:
        print(f"失败 {len(res.failed)} 个（系统级保护包属正常）：")
        for n, e in res.failed:
            print(f"    {n}: {e}")
    if res.skipped_absent:
        print(f"跳过（本机没有）{len(res.skipped_absent)} 个")
    if res.skipped_already:
        print(f"跳过（原本就禁用）{len(res.skipped_already)} 个")
    if res.record_path:
        print(f"\n状态记录（还原依据）：{res.record_path}")
        print("  还原：mitvclean restore --record " + str(res.record_path))
    return 0


def cmd_adswitch(args) -> int:
    with _connect(args) as dev:
        if args.set:
            pairs = {}
            for item in args.set:
                k, _, v = item.partition("=")
                pairs[k] = v
            res = ads.set_ad_settings(dev, pairs)
            print("写入结果：")
            for k, v in res.items():
                print(f"    {k} = {v}")
        else:
            found = ads.find_ad_settings(dev)
            print("广告相关设置（当前值）：")
            for k, v in sorted(found.items()):
                print(f"    {k} = {v}")
            print("\n常用开关（--set 传入）：")
            for k, v in ads.KNOWN_AD_SWITCHES.items():
                print(f"    {k}={v}")
    return 0


def cmd_cache(args) -> int:
    with _connect(args) as dev:
        pkgs = args.package or [
            "com.xiaomi.mitv.tvmanager", "com.mitv.care", "com.xm.webcontent",
        ]
        dirs = args.dir or [
            "/sdcard/Android/data/com.mitv.tvhome/cache/miad",
            "/sdcard/Android/data/com.mitv.tvhome/cache/video-cache",
        ]
        res = ads.clean_ad_cache(dev, pkgs, dirs)
        for k, v in res.items():
            print(f"    {k} -> {v}")
    return 0


def cmd_restore(args) -> int:
    if not args.record:
        # 自动找最新的状态记录
        d = Path(args.out or DEFAULT_OUT)
        recs = sorted(d.glob("state-*.json"))
        if not recs:
            raise SystemExit(f"{d} 里没有找到状态记录，请用 --record 指定")
        args.record = str(recs[-1])
        print(f"使用最新的记录：{args.record}")
    with _connect(args) as dev:
        if args.dry_run:
            ok, _ = packages.enable_packages(dev, args.record, dry_run=True)
            print(f"[dry-run] 将要恢复 {len(ok)} 个包：")
            for n in ok:
                print(f"    {n}")
            return 0
        ok, failed = packages.enable_packages(dev, args.record)
    print(f"已恢复 {len(ok)} 个")
    for n, e in failed:
        print(f"    失败 {n}: {e}")
    print("建议重启电视让系统完全回到原状")
    return 0


# ---------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    # 全局参数既可以放在子命令前，也可以放在子命令后 —— 后者更符合直觉
    # （"mitvclean debloat --profile x" 比 "mitvclean --profile x debloat" 常见）。
    #
    # 关键点：公共参数用 default=SUPPRESS，否则子解析器会用默认值把父级已解析的值覆盖掉
    # （argparse 的已知行为）。没传的参数干脆不出现，解析完再补默认值。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=argparse.SUPPRESS,
                        help="电视 IP（也可用环境变量 MITV_HOST）")
    common.add_argument("--port", type=int, default=argparse.SUPPRESS,
                        help="ADB 端口（默认 5555）")
    common.add_argument("--profile", default=argparse.SUPPRESS,
                        help="机型画像 slug（默认按设备代号自动匹配）")
    common.add_argument("--out", default=argparse.SUPPRESS,
                        help=f"输出目录（默认 {DEFAULT_OUT}）")
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="只报告不执行")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)

    p = argparse.ArgumentParser(
        prog="mitvclean",
        description="小米电视去臃肿与去广告工具（只做可逆操作）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        parents=[common],
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="读设备信息", parents=[common]).set_defaults(func=cmd_info)
    sub.add_parser("profiles", help="列出机型画像", parents=[common]).set_defaults(func=cmd_profiles)
    sub.add_parser("doctor", help="体检报告", parents=[common]).set_defaults(func=cmd_doctor)
    sub.add_parser("debloat", help="禁用后台包", parents=[common]).set_defaults(func=cmd_debloat)

    s = sub.add_parser("scan", help="提取广告域名并生成 hosts 清单", parents=[common])
    s.add_argument("--apk", action="append", help="要扫描的包名（可重复）")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("hosts", help="按画像生成 hosts 清单", parents=[common])
    s.add_argument("--group", default="all",
                   help="只生成某一组（1/2/3…），或 all 生成全量（默认 all）")
    s.set_defaults(func=cmd_hosts)

    s = sub.add_parser("adswitch", help="读/写广告开关", parents=[common])
    s.add_argument("--set", action="append", help="键=值（可重复）")
    s.set_defaults(func=cmd_adswitch)

    s = sub.add_parser("cache", help="清广告缓存", parents=[common])
    s.add_argument("--package", action="append", help="要清缓存的包（可重复）")
    s.add_argument("--dir", action="append", help="要清的目录（可重复）")
    s.set_defaults(func=cmd_cache)

    s = sub.add_parser("restore", help="按记录还原", parents=[common])
    s.add_argument("--record", help="状态记录文件（默认取最新的）")
    s.set_defaults(func=cmd_restore)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # 公共参数用了 SUPPRESS 做默认值，没传的这里补上
    for name, default in (
        ("host", None), ("port", 5555), ("profile", None),
        ("out", DEFAULT_OUT), ("dry_run", False), ("verbose", False),
    ):
        if not hasattr(args, name):
            setattr(args, name, default)
    try:
        return args.func(args)
    except ProfileError as e:
        print(f"机型画像错误：{e}", file=sys.stderr)
        return 2
    except AdbError as e:
        print(f"ADB 错误：{e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
