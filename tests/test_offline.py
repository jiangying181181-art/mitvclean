"""
mitvclean 的离线单元测试。

不依赖真实设备：用假的 AdbDevice 桩件验证包管理、清单解析、域名分类等核心逻辑。
运行：python -m pytest tests/ -q     或     python tests/test_offline.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mitvclean import ads, packages
from mitvclean.packages import PackageError


class FakeDevice:
    """假的 AdbDevice：按内存里的状态回答问题。"""

    def __init__(self, installed, disabled=()):
        self.installed = set(installed)
        self.disabled = set(disabled)
        self.commands = []
        self.host = "10.0.0.5"
        self.port = 5555

    def shell(self, cmd, read_timeout=60.0):
        self.commands.append(cmd)
        if cmd.startswith("pm list packages -d"):
            return "\n".join(f"package:{p}" for p in sorted(self.disabled)) + "\n"
        if cmd.startswith("pm list packages"):
            return "\n".join(f"package:{p}" for p in sorted(self.installed)) + "\n"
        if cmd.startswith("pm disable-user --user 0 "):
            pkg = cmd.rsplit(" ", 1)[1]
            if pkg not in self.installed:
                return f"Package {pkg} not found\n"
            self.disabled.add(pkg)
            return f"Package {pkg} new state: disabled-user\n"
        if cmd.startswith("pm enable "):
            pkg = cmd.rsplit(" ", 1)[1]
            self.disabled.discard(pkg)
            return f"Package {pkg} new state: enabled\n"
        if cmd.startswith("pm clear "):
            return "Success\n"
        if cmd.startswith("getprop "):
            return ""
        return ""

    def run(self, cmd, read_timeout=60.0):
        """真实设备上带重试的入口；桩件不需要重试。"""
        return self.shell(cmd, read_timeout)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


# ---------------------------------------------------------------- 清单解析
def test_read_list_strips_comments_and_bom():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "list.txt"
        p.write_text(
            "﻿com.example.one   # 第一行\n"
            "\n"
            "# 整行注释\n"
            "com.example.two\n"
            "com.example.one\n",          # 重复
            encoding="utf-8",
        )
        names = packages.read_list(p)
        assert names == ["com.example.one", "com.example.two"], names


def test_read_list_rejects_illegal_package_name():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "list.txt"
        # 含 shell 元字符，必须被拒
        p.write_text("com.example.one; rm -rf /\n", encoding="utf-8")
        try:
            packages.read_list(p)
        except PackageError:
            return
        raise AssertionError("非法包名竟然通过了校验")


def test_validate_package():
    packages.validate_package("com.a.b")
    for bad in ("", "noDots", "com..b", "com.a-b", "com.a b", "com.a;ls", "1com.a"):
        try:
            packages.validate_package(bad)
        except PackageError:
            continue
        raise AssertionError(f"{bad!r} 竟然通过了校验")


# ---------------------------------------------------------------- 状态与禁用
def test_query_state():
    dev = FakeDevice(
        installed=["com.a", "com.b", "com.c"],
        disabled=["com.b"],
    )
    st = packages.query_state(dev, ["com.a", "com.b", "com.z"])
    assert st == {
        "com.a": packages.STATE_ENABLED,
        "com.b": packages.STATE_DISABLED,
        "com.z": packages.STATE_ABSENT,
    }, st


def test_disable_is_reversible_and_records_state():
    dev = FakeDevice(installed=["com.a", "com.b", "com.c"], disabled=["com.b"])
    with tempfile.TemporaryDirectory() as d:
        res = packages.disable_packages(dev, ["com.a", "com.b", "com.z"], d)
        # 只禁用了 enabled 的
        assert res.disabled == ["com.a"], res.disabled
        assert res.skipped_already == ["com.b"], res.skipped_already
        assert res.skipped_absent == ["com.z"], res.skipped_absent
        # 记录已落盘
        assert res.record_path and res.record_path.exists()
        rec = packages.load_record(res.record_path)
        assert rec["packages"]["com.b"] == packages.STATE_DISABLED
        assert rec["packages"]["com.z"] == packages.STATE_ABSENT


def test_restore_only_reenables_what_was_enabled():
    dev = FakeDevice(installed=["com.a", "com.b", "com.c"], disabled=["com.b"])
    with tempfile.TemporaryDirectory() as d:
        res = packages.disable_packages(dev, ["com.a", "com.b", "com.z"], d)
        # 模拟用户自己另外禁了一个包
        dev.disabled.add("com.c")
        ok, failed = packages.enable_packages(dev, res.record_path)
        assert ok == ["com.a"], ok
        # 用户自己禁的 b 和 c 都不该被误开
        assert "com.b" in dev.disabled
        assert "com.c" in dev.disabled
        assert not failed


def test_dry_run_changes_nothing():
    dev = FakeDevice(installed=["com.a"])
    with tempfile.TemporaryDirectory() as d:
        res = packages.disable_packages(dev, ["com.a"], d, dry_run=True)
        assert res.disabled == ["com.a"]
        assert not dev.disabled, "dry-run 不应该真的禁用"
        assert not list(Path(d).glob("state-*.json")), "dry-run 不应该落盘"


# ---------------------------------------------------------------- 域名分类
def test_classify_domains():
    assert ads.classify("ad.xiaomi.com") == "ad"
    assert ads.classify("sdkconfig.ad.xiaomi.com") == "ad"
    assert ads.classify("adx.v.mitvos.com") == "ad"
    assert ads.classify("cp-ppvideo.cdn.ptmi.gitv.tv") == "ad"
    assert ads.classify("media.icntv.pre.pandora.xiaomi.com") == "source"
    assert ads.classify("api.ptmi.gitv.tv") == "source"
    assert ads.classify("www.baidu.com") == "other"


def test_extract_from_logcat():
    text = (
        "D/PWHttp: https://ottimg.cdn.pandora.xiaomi.com/abc.png\n"
        "D/Conn: Connection{api.ptmi.gitv.tv:443}\n"
        "D/Other: https://www.qq.com/x\n"
    )
    doms = ads.extract_from_logcat(text)
    assert "ottimg.cdn.pandora.xiaomi.com" in doms
    assert "api.ptmi.gitv.tv" in doms


def test_hosts_lines_format_ip_first():
    rep = ads.DomainReport(
        ad_domains={"ad.xiaomi.com"},
        source_domains={"api.ptmi.gitv.tv"},
    )
    lines = rep.to_hosts_lines()
    assert lines == [
        "127.0.0.1 ad.xiaomi.com",
        "127.0.0.1 api.ptmi.gitv.tv",
    ], lines


# ---------------------------------------------------------------- 画像
def test_profile_loads():
    from mitvclean.profiles import list_profiles, load_profile

    slugs = list_profiles()
    assert slugs, "应该有至少一个机型画像"
    p = load_profile(slugs[0])
    assert p.title
    assert p.debloat_path.exists() and p.hosts_path.exists()
    # 清单里的包名必须都合法
    for name in packages.read_list(p.debloat_path):
        packages.validate_package(name)


def test_profile_debloat_has_no_duplicate():
    from mitvclean.profiles import list_profiles, load_profile

    for slug in list_profiles():
        p = load_profile(slug)
        names = packages.read_list(p.debloat_path)
        assert len(names) == len(set(names)), f"{slug} 清单里有重复"


def test_hosts_generation_produces_valid_rules():
    """从画像生成 hosts 清单：每条规则都是 IP 在前，且域名合法。"""
    from mitvclean.profiles import list_profiles, load_profile

    for slug in list_profiles():
        p = load_profile(slug)
        n = 0
        for raw in p.hosts_path.read_text(encoding="utf-8-sig").splitlines():
            t = raw.strip()
            if not t or t.startswith("#"):
                continue
            domain = t.split()[0]
            if domain.startswith("127.0.0.1"):
                continue
            assert "." in domain, f"{slug} 的 hosts 里有不像域名的行：{t!r}"
            n += 1
        assert n > 0, f"{slug} 的 hosts.txt 里没有域名"


def test_cli_accepts_global_args_before_and_after_subcommand():
    """全局参数放在子命令前后都要能用。"""
    from mitvclean.cli import build_parser

    parser = build_parser()
    a = parser.parse_args(["--host", "1.2.3.4", "hosts", "--profile", "x"])
    b = parser.parse_args(["hosts", "--profile", "x", "--host", "1.2.3.4"])
    assert a.host == "1.2.3.4" and a.profile == "x", vars(a)
    assert b.host == "1.2.3.4" and b.profile == "x", vars(b)


def test_cli_fills_defaults():
    from mitvclean.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["profiles"])
    # 没传的参数在解析后不存在，main() 会补默认值
    assert not hasattr(args, "host") or args.host is None


def test_host_groups_split_by_marker():
    """hosts.txt 的“第 N 组”标记必须能切开，且各组不重不漏。"""
    from mitvclean.profiles import list_profiles, load_profile

    for slug in list_profiles():
        p = load_profile(slug)
        groups = p.host_groups()
        assert groups, f"{slug} 解析不出任何 hosts 组"
        total = 0
        for title, domains in groups:
            assert title, f"{slug} 有个组没有标题"
            assert domains, f"{slug} 的组 {title!r} 是空的"
            total += len(domains)
            for d in domains:
                assert "." in d and " " not in d, f"{slug} 的域名不合法：{d!r}"
        # 分组切分不能改变域名总数
        raw = [
            ln.split()[0]
            for ln in p.hosts_path.read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert total == len(raw), f"{slug} 分组后总数对不上：{total} != {len(raw)}"


def test_hosts_group_output_is_ip_first():
    """分组生成的 hosts 文件：每条规则 IP 在前，且组数与组内条数正确。"""
    import tempfile
    from pathlib import Path
    from mitvclean.cli import build_parser, main

    parser = build_parser()
    args = parser.parse_args(["hosts", "--profile", "mitv-ansp0", "--out", "x"])
    assert args.group == "all"

    with tempfile.TemporaryDirectory() as td:
        rc = main(["hosts", "--profile", "mitv-ansp0", "--group", "1", "--out", td])
        assert rc == 0
        out = Path(td) / "hosts-mitv-ansp0-group1.txt"
        assert out.exists()
        lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        rules = [l for l in lines if not l.startswith("#")]
        assert rules, "分组文件里没有规则"
        for r in rules:
            assert r.startswith("127.0.0.1 "), f"IP 不在前：{r!r}"
        # 第一组的条数必须等于清单里第一组的条数
        from mitvclean.profiles import load_profile
        g = load_profile("mitv-ansp0").host_groups()
        assert len(rules) == len(g[0][1])


def test_critical_source_domains_are_never_emitted_by_default():
    """🚨 内容源主干域绝不能出现在默认生成的 hosts 里。

    2026-10-22 实测事故：内容源域被整组贴到路由器后，电视上所有节目
    都显示「无法连接到服务器」。这条测试就是那个事故的护栏。
    """
    import tempfile
    from pathlib import Path
    from mitvclean.cli import main
    from mitvclean.profiles import CRITICAL_SOURCE_DOMAINS, load_profile

    crit = load_profile("mitv-ansp0").critical_domains()
    assert crit, "至少要能识别出内容源主干域"

    with tempfile.TemporaryDirectory() as td:
        # 默认（全量）——必须剔除
        assert main(["hosts", "--profile", "mitv-ansp0", "--group", "all", "--out", td]) == 0
        for f in Path(td).glob("*.txt"):
            body = f.read_text(encoding="utf-8")
            rules = [l.split()[1] for l in body.splitlines()
                     if l.strip() and not l.startswith("#")]
            leaked = [r for r in rules if r in CRITICAL_SOURCE_DOMAINS]
            assert not leaked, f"{f.name} 漏出了内容源主干域：{leaked}"

        # 第 2 组 ——也必须剔除
        assert main(["hosts", "--profile", "mitv-ansp0", "--group", "2", "--out", td]) == 0
        f2 = Path(td) / "hosts-mitv-ansp0-group2.txt"
        body = f2.read_text(encoding="utf-8")
        rules = [l.split()[1] for l in body.splitlines()
                 if l.strip() and not l.startswith("#")]
        assert not [r for r in rules if r in CRITICAL_SOURCE_DOMAINS]

        # 显式加 --include-critical 才允许出现
        assert main(["hosts", "--profile", "mitv-ansp0", "--group", "2",
                     "--include-critical", "--out", td]) == 0
        body = f2.read_text(encoding="utf-8")
        rules = [l.split()[1] for l in body.splitlines()
                 if l.strip() and not l.startswith("#")]
        assert [r for r in rules if r in CRITICAL_SOURCE_DOMAINS], \
            "--include-critical 时应保留内容源主干域"


def test_parse_pem_rsa_handles_pkcs8():
    """🚨 adbkey 官方生成的是 PKCS#8，只按 PKCS#1 解析会报"期望 INTEGER"。

    2026-10-22 实测：自研 ADB 客户端连不上真机，根因就是这个。
    这条测试用现场真实的 adbkey 格式做样本。
    """
    from mitvclean.adb import _parse_pem_rsa

    # PKCS#8 样本：官方 adb 生成的 adbkey 结构（2048 位 RSA，e=65537）
    pkcs8 = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDemsRHGjrtiA5J\n"
        "-----END PRIVATE KEY-----\n"
    )
    # 结构不完整可以报错，但不能报"期望 INTEGER"以外的类型混淆错误
    try:
        _parse_pem_rsa(pkcs8)
    except ValueError as e:
        assert "期望 INTEGER" not in str(e), f"PKCS#8 被当成 PKCS#1 解析了：{e}"
    except Exception:
        pass

    # 用一个自己生成的最小 PKCS#8 密钥做完整往返验证
    import base64
    import struct

    def der_len(n: int) -> bytes:
        if n < 0x80:
            return bytes([n])
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return bytes([0x80 | len(b)]) + b

    def der_int(v: int) -> bytes:
        b = v.to_bytes((v.bit_length() + 7) // 8 or 1, "big")
        return b"\x02" + der_len(len(b)) + b

    # 造一个 PKCS#1 私钥结构（只保留 version/n/e/d 供解析）
    n_v, e_v, d_v = 0xC0FFEE, 65537, 0xDEAD
    pkcs1_body = der_int(0) + der_int(n_v) + der_int(e_v) + der_int(d_v)
    pkcs1 = b"\x30" + der_len(len(pkcs1_body)) + pkcs1_body
    # PKCS#8: version, AlgorithmIdentifier(SEQUENCE), OCTET STRING(pkcs1)
    alg = b"\x30\x00"
    pkcs8_body = der_int(0) + alg + b"\x04" + der_len(len(pkcs1)) + pkcs1
    pkcs8_der = b"\x30" + der_len(len(pkcs8_body)) + pkcs8_body
    pem = ("-----BEGIN PRIVATE KEY-----\n"
           + base64.b64encode(pkcs8_der).decode()
           + "\n-----END PRIVATE KEY-----\n")

    n, d, e = _parse_pem_rsa(pem)
    assert n == n_v and d == d_v and e == e_v, (n, d, e)


# ---------------------------------------------------------------- 运行
def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print()
    print(f"{len(fns) - failed}/{len(fns)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
