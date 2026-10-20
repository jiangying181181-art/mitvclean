"""
mitvclean.adb — 极简 ADB-over-TCP 客户端（纯标准库，零第三方依赖）

为什么不用 adb.exe / adb-shell：
  · 免安装：不需要 Android SDK / platform-tools，Linux/macOS/Windows 都能跑
  · 免子进程：不依赖 PATH 里的 adb，Windows 上不用处理 adb.exe 的编码与控制台问题
  · 只实现本项目用到的四条命令：shell / pull / connect / devices

协议说明（ADB over TCP，Android 4.4+）：
  1. 客户端发 24 字节头：命令(4) + 参数长度(4) + 校验和(4) + 魔数(0x4f584e42)
  2. 发送命令字符串（如 "shell:pm list packages"），以 \0 结尾
  3. 设备回 8 字节 ACK（4 字节命令 + 4 字节结果）
  4. 流式模式：再发 8 字节（4 字节长度 + 4 字节 0）后接收数据，
     以 "OKAY"/"FAIL" 结束，剩余长度置 0 表示数据结束

认证（auth）：
  设备要求时返回 AUTH token，用 RSA 私钥签名后回传。
  密钥持久化在用户目录（.android/adbkey 兼容官方 adb 的位置，
  这样装了 Android Studio 的用户不用再授权一次）。
"""

from __future__ import annotations

import hashlib
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

__all__ = ["AdbError", "AdbDevice", "connect", "list_devices"]

A_SYNC = 0x434E5953  # "SYNC"
A_OPEN = 0x4E45504F  # "OPEN"
A_OKAY = 0x59414B4F  # "OKAY"
A_FAIL = 0x4C494641  # "FAIL"
A_AUTH = 0x48545541  # "AUTH"
A_STLS = 0x534C5453  # "STLS"
A_WRTE = 0x45545257  # "WRTE"

MAXDATA = 64 * 1024


class AdbError(RuntimeError):
    """ADB 通信或设备侧错误。"""


def _keydir() -> Path:
    d = Path.home() / ".android"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rsa_sign(data: bytes) -> bytes:
    """用 RSA-SHA1 签名 adb 认证 challenge。

    优先用 cryptography；没有就退到纯 Python 的最小 PKCS#1 v1.5 实现，
    保证零第三方依赖也能跑（代价是慢一点，认证只做一次）。
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key = _load_or_create_key()
        priv = serialization.load_pem_private_key(key, password=None)
        return priv.sign(data, padding.PKCS1v15(), hashes.SHA1())
    except Exception:
        return _rsa_sign_pure(data)


def _load_or_create_key() -> bytes:
    keyfile = _keydir() / "adbkey"
    if not keyfile.exists():
        raise AdbError(
            "未找到 adb 私钥，且自动生成失败。请安装 cryptography：pip install cryptography"
        )
    return keyfile.read_bytes()


def _rsa_sign_pure(data: bytes) -> bytes:
    """纯 Python 的 RSA PKCS#1 v1.5 签名（无第三方依赖时使用）。"""
    keyfile = _keydir() / "adbkey"
    if not keyfile.exists():
        raise AdbError("未找到 adb 私钥，请先运行一次 adb 或安装 cryptography")
    text = keyfile.read_text(encoding="utf-8", errors="replace")
    n, d, e = _parse_pem_rsa(text)
    k = (n.bit_length() + 7) // 8
    digest = hashlib.sha1(data).digest()
    # DigestInfo for SHA-1
    prefix = bytes.fromhex("3021300906052b0e03021a05000414")
    t = prefix + digest
    ps = b"\xff" * (k - len(t) - 3)
    em = b"\x00\x01" + ps + b"\x00" + t
    m = int.from_bytes(em, "big")
    s = pow(m, d, n)
    return s.to_bytes(k, "big")


def _parse_pem_rsa(text: str):
    """从 PEM 文本里解析 RSA 的 n/d/e（够用即可，不做完整 DER 校验）。"""
    import base64

    body = []
    inside = False
    for line in text.splitlines():
        if line.startswith("-----BEGIN"):
            inside = True
            continue
        if line.startswith("-----END"):
            break
        if inside:
            body.append(line.strip())
    der = base64.b64decode("".join(body))

    # 极简 DER 解析：SEQUENCE { INTEGER n, INTEGER e, INTEGER d }
    def read_int(buf, pos):
        assert buf[pos] == 0x02, "期望 INTEGER"
        pos += 1
        ln = buf[pos]
        pos += 1
        if ln & 0x80:
            nbytes = ln & 0x7F
            pos += 1
        else:
            nbytes = ln
        val = int.from_bytes(buf[pos:pos + nbytes], "big")
        return val, pos + nbytes

    assert der[0] == 0x30, "期望 SEQUENCE"
    pos = 1
    if der[1] & 0x80:
        pos = 2 + (der[1] & 0x7F)
    else:
        pos = 2
    n, pos = read_int(der, pos)
    e, pos = read_int(der, pos)
    d, pos = read_int(der, pos)
    return n, d, e


class AdbDevice:
    """一台通过 TCP 连接的设备。"""

    def __init__(self, host: str, port: int = 5555, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._buf = b""

    # ---------- 底层 ----------
    def _recv_exact(self, n: int) -> bytes:
        assert self.sock is not None
        out = bytearray()
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise AdbError("设备连接被关闭")
            out += chunk
        return bytes(out)

    def _send(self, payload: bytes) -> None:
        assert self.sock is not None
        self.sock.sendall(payload)

    def _make_request(self, cmd: str) -> bytes:
        raw = cmd.encode("utf-8")
        return struct.pack("<6I", A_SYNC, len(raw), sum(raw) & 0xFFFFFFFF, A_OPEN) + raw

    def _auth(self) -> None:
        """完成 AUTH 握手。"""
        token = self._recv_exact(4)
        if token == A_AUTH:
            sig = _rsa_sign(self._recv_exact(20))
            self._send(struct.pack("<I", A_AUTH) + sig)
            reply = self._recv_exact(4)
            if reply == A_AUTH:
                raise AdbError("ADB 认证失败：电视拒绝了本机的密钥。请在电视上重新确认授权。")
        elif token != A_OKAY:
            raise AdbError(f"意外的 adb 响应：{token!r}")

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._send(self._make_request("host:connect:" + f"{self.host}:{self.port}"))
        self._auth()
        # connect 之后服务端会发 OKAY/FAIL 表示结果，然后是 8 字节长度
        self._recv_exact(8)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- 高层 ----------
    def shell(self, command: str, read_timeout: float = 60.0) -> str:
        """执行一条 shell 命令并返回完整输出（文本）。

        注意：一次只发一条命令。部分国产 ROM 的 shell 在收到分号链式命令时
        会静默中断后续语句，所以本项目坚持逐条下发。
        """
        assert self.sock is not None
        self.sock.settimeout(read_timeout)
        self._send(self._make_request("shell:" + command))
        self._auth()

        length = struct.unpack("<I", self._recv_exact(4))[0]
        if length == 0:
            return ""
        self._recv_exact(4)  # 第二个 0
        data = b""
        while True:
            chunk = self._recv_exact(length)
            data += chunk
            more = struct.unpack("<I", self._recv_exact(4))[0]
            if more == 0:
                break
            length = more
        # 收尾
        self._recv_exact(4)
        return data.decode("utf-8", errors="replace")

    def pull(self, remote: str, local: str) -> None:
        """把设备上的文件拉到本地。"""
        assert self.sock is not None
        self._send(self._make_request("pull:" + remote))
        self._auth()
        self._recv_exact(4)  # OKAY
        while True:
            cmd = self._recv_exact(4)
            if cmd == A_WRTE:
                size = struct.unpack("<I", self._recv_exact(4))[0]
                with open(local, "wb") as f:
                    remaining = size
                    while remaining > 0:
                        buf = self.sock.recv(min(MAXDATA, remaining))
                        if not buf:
                            break
                        f.write(buf)
                        remaining -= len(buf)
                self._recv_exact(4)
                continue
            if cmd == A_FAIL:
                size = struct.unpack("<I", self._recv_exact(4))[0]
                msg = self._recv_exact(size) if size else b""
                raise AdbError(f"pull 失败：{msg.decode('utf-8', 'replace')}")
            break


def connect(host: str, port: int = 5555, timeout: float = 30.0) -> AdbDevice:
    """连接一台设备；连接失败抛 AdbError。"""
    dev = AdbDevice(host, port, timeout)
    dev.connect()
    return dev


def list_devices() -> list[str]:
    """列出本机能连上的 adb 设备（需要系统里有 adb 可执行文件时才有意义）。"""
    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return []
    return [
        line.split("\t")[0]
        for line in out.splitlines()[1:]
        if "\t" in line
    ]
