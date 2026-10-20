"""
mitvclean.adb — 极简 ADB-over-TCP 客户端（纯标准库，零第三方依赖）

为什么不用 adb.exe / adb-shell：
  · 免安装：不需要 Android SDK / platform-tools，Linux/macOS/Windows 都能跑
  · 免子进程：不依赖 PATH 里的 adb，Windows 上不用处理 adb.exe 的编码与控制台问题
  · 够用：只实现本项目需要的 shell / pull

协议（依据 AOSP system/core/adb，完整说明见
https://android.googlesource.com/platform/system/core/+/master/docs/devices/adb/protocol.txt）：

  每个包 = 24 字节小端头 + 可选负载

    偏移  长度  字段
      0     4   command
      4     4   arg0
      8     4   arg1
     12     4   data_length   负载字节数
     16     4   data_check     负载字节和
     20     4   magic          command ^ 0xFFFFFFFF

  命令字：
    CNXN  建立连接（arg0=版本, arg1=最大负载, 负载=banner）
    AUTH  认证（arg0=1 token / 2 签名 / 3 公钥）
    OPEN  打开一个流（arg0=本地 id, 负载=服务名）
    OKAY  确认
    WRTE  数据
    CLSE  关闭

  连接流程：
    client → CNXN(0x01000001, 1MiB, "host::features=shell_v2,...")  →
    device → (AUTH token) → client 回签名 → device → CNXN(成功)  →
    client → OPEN(local_id, 0, "shell:cmd\0") → device → OKAY → 数据流

  shell 的数据流用 sync 协议（SYNC/OKAY/WRTE），命令输出以 4 字节长度 + 数据
  分块传输，长度 0 表示结束。
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

__all__ = ["AdbError", "AdbDevice", "connect", "list_devices"]

# 命令字
A_SYNC = 0x434E5953  # "SYNC"
A_CNXN = 0x4E584E43  # "CNXN"
A_OPEN = 0x4E45504F  # "OPEN"
A_OKAY = 0x59414B4F  # "OKAY"
A_CLSE = 0x45534C43  # "CLSE"
A_WRTE = 0x45545257  # "WRTE"
A_AUTH = 0x48545541  # "AUTH"

# CNXN 参数
CNXN_VERSION = 0x01000001
CNXN_MAXDATA = 1024 * 1024

# AUTH 参数
AUTH_TOKEN = 1
AUTH_SIGNATURE = 2
AUTH_RSAPUBLICKEY = 3


class AdbError(RuntimeError):
    """ADB 通信或设备侧错误。"""


# ---------------------------------------------------------------- 密钥
def _keydir() -> Path:
    d = Path.home() / ".android"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key_paths() -> tuple[Path, Path]:
    d = _keydir()
    return d / "adbkey", d / "adbkey.pub"


def _load_private_key() -> bytes:
    keyfile, _ = _key_paths()
    if keyfile.exists():
        return keyfile.read_bytes()
    raise AdbError(
        f"没有找到 adb 私钥（{keyfile}）。\n"
        "  装一次官方 platform-tools 并执行一次 adb connect，或者安装 cryptography "
        "让本工具自己生成：pip install cryptography"
    )


def _rsa_sign(data: bytes) -> bytes:
    """用 RSA-SHA1 签 ADB 认证 challenge。"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        keyfile, _ = _key_paths()
        priv = serialization.load_pem_private_key(keyfile.read_bytes(), password=None)
        return priv.sign(data, padding.PKCS1v15(), hashes.SHA1())
    except ImportError:
        return _rsa_sign_pure(data)
    except FileNotFoundError:
        raise AdbError("没有 adb 私钥，无法完成认证") from None


def _rsa_sign_pure(data: bytes) -> bytes:
    """纯 Python 的 RSA PKCS#1 v1.5 签名（没有 cryptography 时的兜底）。"""
    keyfile, _ = _key_paths()
    if not keyfile.exists():
        raise AdbError("没有 adb 私钥，无法完成认证")
    n, d, _e = _parse_pem_rsa(keyfile.read_text(encoding="utf-8", errors="replace"))
    k = (n.bit_length() + 7) // 8
    prefix = bytes.fromhex("3021300906052b0e03021a05000414")  # SHA-1 DigestInfo
    t = prefix + hashlib.sha1(data).digest()
    ps = b"\xff" * (k - len(t) - 3)
    em = b"\x00\x01" + ps + b"\x00" + t
    s = pow(int.from_bytes(em, "big"), d, n)
    return s.to_bytes(k, "big")


def _parse_pem_rsa(text: str):
    """从 PEM 文本解析 RSA 的 n/d/e。"""
    body: list[str] = []
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

    def read_int(buf: bytes, pos: int) -> tuple[int, int]:
        if buf[pos] != 0x02:
            raise ValueError("期望 INTEGER")
        pos += 1
        ln = buf[pos]
        pos += 1
        if ln & 0x80:
            nbytes = ln & 0x7F
            pos += 1
        else:
            nbytes = ln
        return int.from_bytes(buf[pos:pos + nbytes], "big"), pos + nbytes

    if der[0] != 0x30:
        raise ValueError("期望 SEQUENCE")
    pos = 2 + (der[1] & 0x7F) if der[1] & 0x80 else 2
    n, pos = read_int(der, pos)
    e, pos = read_int(der, pos)
    d, _ = read_int(der, pos)
    return n, d, e


# ---------------------------------------------------------------- 设备
class AdbDevice:
    """一台通过 TCP 连接的设备。"""

    def __init__(self, host: str, port: int = 5555, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._local_id = 0
        self._remote_id = 0

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

    def _recv_msg(self) -> tuple[int, int, int, bytes]:
        """收一个包，返回 (command, arg0, arg1, payload)。

        两种帧格式：
          · adb 主协议（A_CNXN/A_OPEN/A_OKAY/…）：magic = command ^ 0xFFFFFFFF
          · sync 子协议（A_SYNC/A_WRTE/…）：magic 固定 0xFFFFFFFF，不做 command 校验
        """
        header = self._recv_exact(24)
        cmd, arg0, arg1, dlen, _check, magic = struct.unpack("<6I", header)
        if cmd == A_SYNC:
            # sync 子协议用固定 magic，不能按主协议校验
            if magic != 0xFFFFFFFF:
                raise AdbError(f"sync 包 magic 不对：{magic:#x}")
        elif magic != (cmd ^ 0xFFFFFFFF):
            raise AdbError(f"adb 包校验失败：cmd={cmd:#x} magic={magic:#x}")
        payload = self._recv_exact(dlen) if dlen else b""
        return cmd, arg0, arg1, payload

    def _send_msg(self, cmd: int, arg0: int = 0, arg1: int = 0, payload: bytes = b"") -> None:
        assert self.sock is not None
        check = sum(payload) & 0xFFFFFFFF
        header = struct.pack(
            "<6I", cmd, arg0, arg1, len(payload), check, cmd ^ 0xFFFFFFFF
        )
        self.sock.sendall(header + payload)

    def _next_local_id(self) -> int:
        self._local_id += 1
        return self._local_id

    # ---------- 连接 ----------
    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._handshake()

    def _handshake(self) -> None:
        banner = b"host::features=shell_v2,cmd,stat_v2,ls_v2,fixed_push_mkdir\x00"
        self._send_msg(A_CNXN, CNXN_VERSION, CNXN_MAXDATA, banner)

        # 设备回 AUTH（要认证）或 CNXN（已信任，直接成功）
        cmd, arg0, arg1, payload = self._recv_msg()
        if cmd == A_AUTH:
            self._handle_auth(arg0, payload)
            cmd, arg0, arg1, payload = self._recv_msg()
        if cmd != A_CNXN:
            raise AdbError(
                f"adb 握手失败：设备回了 {cmd:#x}（期望 CNXN）"
                + ("（可能是电视拒绝了本机密钥，请在电视上重新确认授权）" if cmd == A_AUTH else "")
            )
        # 设备报的 maxdata 在 arg1，取较小者
        self._maxdata = min(CNXN_MAXDATA, arg1) if arg1 else CNXN_MAXDATA

    def _handle_auth(self, auth_type: int, payload: bytes) -> None:
        """处理 AUTH 握手。"""
        if auth_type == AUTH_TOKEN:
            # 用私钥签 token 回传
            sig = _rsa_sign(payload)
            self._send_msg(A_AUTH, AUTH_SIGNATURE, 0, sig)
            return
        if auth_type == AUTH_RSAPUBLICKEY:
            # 设备不认识我们的公钥：把它发过去，电视上会弹出「允许 USB 调试吗」
            keyfile, pubfile = _key_paths()
            if not pubfile.exists():
                raise AdbError(
                    "缺少 adbkey.pub，无法请求电视授权。"
                    "请先装一次官方 platform-tools 并 adb connect 一次，"
                    "或安装 cryptography 让本工具生成密钥：pip install cryptography"
                )
            self._send_msg(A_AUTH, AUTH_RSAPUBLICKEY, 0, pubfile.read_bytes())
            return
        raise AdbError(f"未知的 AUTH 类型 {auth_type}")

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

    # ---------- 流 ----------
    def _open_stream(self, service: str) -> int:
        """开一个流，返回本地 id。

        设备回 OKAY 表示流建立成功。sync: 这类服务在 OKAY 之后会立刻切换成
        sync 子协议（8 字节 ASCII 帧），所以这里只消费到第一个 OKAY 为止，
        剩下的字节留给调用方按对应协议读。
        """
        self._local_id = self._next_local_id()
        self._send_msg(A_OPEN, self._local_id, 0, service.encode("utf-8") + b"\x00")
        # 设备回 OKAY（成功）或 CLSE（拒绝）
        while True:
            cmd, arg0, arg1, _ = self._recv_msg()
            if cmd == A_OKAY:
                self._remote_id = arg0
                return self._local_id
            if cmd == A_CLSE:
                raise AdbError(f"设备拒绝打开 {service}（可能是未授权或该服务不可用）")
            if cmd == A_AUTH:
                self._handle_auth(arg0, b"")
                continue
            # 其他包忽略

    def _read_stream(self, local_id: int) -> bytes:
        """读一个流上的全部数据。

        shell 服务的输出走 adb 主协议分帧：
          WRTE 包（24 字节头 + 负载）逐块送数据，
          最后是一个 CLOSE 表示流结束。

        注意：sync 子协议（8 字节头、id 为 ASCII）只用于 sync: 服务（文件传输），
        这里不涉及。
        """
        assert self.sock is not None
        out = bytearray()
        while True:
            cmd, arg0, arg1, payload = self._recv_msg()
            if cmd == A_WRTE:
                out += payload
                # 回 OKAY 表示收到了（流控，避免设备端阻塞）
                self._send_msg(A_OKAY, local_id, self._remote_id)
                continue
            if cmd == A_OKAY:
                # shell 服务的 OKAY 表示"就绪"，不是数据
                continue
            if cmd == A_CLSE:
                break
            if cmd == A_AUTH:
                self._handle_auth(arg0, b"")
                continue
        return bytes(out)

    # ---------- 高层 ----------
    def shell(self, command: str, read_timeout: float = 60.0) -> str:
        """执行一条 shell 命令并返回完整输出（文本）。

        注意：一次只发一条命令。部分国产 ROM 的 shell 收到分号链式命令时
        会静默中断后续语句，所以本项目坚持逐条下发。
        """
        assert self.sock is not None
        self.sock.settimeout(read_timeout)
        local = self._open_stream("shell:" + command)
        data = self._read_stream(local)
        self._send_msg(A_CLSE, local, self._remote_id)
        return data.decode("utf-8", errors="replace")

    def pull(self, remote: str, local: str) -> None:
        """把设备上的文件拉到本地。

        走 sync 子协议：8 字节头（4 字节 ASCII id + 4 字节小端 length）+ 负载。
        流程：开 sync: 流 -> 发 RECV + 路径 -> 收若干 DATA 块 -> 收 DONE。

        分帧边界：sync: 流在 adb 主协议的 OKAY 之后，整个后续字节流都是
        sync 帧。所以这里不能复用 _recv_msg（那是 24 字节主协议头），
        必须用独立的 8 字节读法。
        """
        assert self.sock is not None
        local_id = self._open_stream("sync:")
        name = remote.encode("utf-8")
        # RECV 请求：4 字节 id + 4 字节 length + 路径
        self.sock.sendall(struct.pack("<4sI", b"RECV", len(name)) + name)

        out = bytearray()
        while True:
            head = self._recv_exact(8)
            sid, length = struct.unpack("<4sI", head)
            if sid == b"DATA":
                out += self._recv_exact(length)
                continue
            if sid == b"DONE":
                break
            if sid == b"FAIL":
                msg = self._recv_exact(length) if length else b""
                raise AdbError(f"pull 失败：{msg.decode('utf-8', 'replace')}")
            if sid == b"OKAY":
                # sync 层的 OKAY 表示请求被接受，继续等 DATA
                continue
            raise AdbError(f"pull 收到意外响应：{sid!r}")
        self._send_msg(A_CLSE, local_id, self._remote_id)
        Path(local).write_bytes(bytes(out))


def connect(host: str, port: int = 5555, timeout: float = 30.0) -> AdbDevice:
    """连接一台设备；连接失败抛 AdbError。"""
    dev = AdbDevice(host, port, timeout)
    dev.connect()
    return dev


def list_devices() -> list[str]:
    """列出本机能连上的 adb 设备（需要系统里有 adb 可执行文件）。"""
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
