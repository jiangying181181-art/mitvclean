"""
用假 ADB 服务端验证 adb.py 的协议实现。

不需要真电视：起一个本地 TCP 服务模拟 adbd，按 AOSP 的 ADB 协议回包，
验证客户端的握手、流打开、流式读取、认证流程都是对的。

运行：python tests/test_adb_protocol.py
"""

import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mitvclean.adb as adbmod
from mitvclean.adb import (
    A_AUTH, A_CLSE, A_CNXN, A_OKAY, A_OPEN, A_SYNC, A_WRTE, AdbDevice, AdbError,
)

CNXN_VERSION = 0x01000001
CNXN_MAXDATA = 1024 * 1024


class FakeAdbd:
    """最小的 adbd 模拟器：接受连接，按协议回 shell 命令的预设输出。"""

    def __init__(self, output="MiTV-ANSP0\n", require_auth=False):
        self.output = output.encode()
        self.require_auth = require_auth
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.services: list[str] = []
        self._stop = False

    def serve(self):
        try:
            conn, _ = self.sock.accept()
        except Exception:
            return
        try:
            self._session(conn)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _session(self, conn):
        # 1) 客户端先发 CNXN
        cmd, arg0, arg1, payload = self._recv(conn)
        assert cmd == A_CNXN, f"首个包应为 CNXN，实际 {cmd:#x}"
        assert payload.endswith(b"\x00"), "banner 应以 NUL 结尾"

        if self.require_auth:
            # 2) 发 AUTH token
            token = b"\x01" * 20
            self._send(conn, A_AUTH, adbmod.AUTH_TOKEN, 0, token)
            # 3) 客户端回签名
            cmd, atype, _, _ = self._recv(conn)
            assert cmd == A_AUTH and atype == adbmod.AUTH_SIGNATURE, "应回 AUTH signature"

        # 4) 回 CNXN 表示连接成功
        self._send(conn, A_CNXN, CNXN_VERSION, CNXN_MAXDATA,
                   b"device::ro.product.name=test\x00")

        # 5) 处理流请求
        while not self._stop:
            cmd, arg0, arg1, payload = self._recv(conn)
            if cmd == A_OPEN:
                service = payload.rstrip(b"\x00").decode("utf-8", "replace")
                self.services.append(service)
                # 先回主协议 OKAY，表示流建立成功
                self._send(conn, A_OKAY, arg0, 7, b"")
                if service.startswith("shell:"):
                    self._serve_shell(conn, arg0)
                elif service == "sync:":
                    self._serve_pull(conn, arg0)
                continue
            if cmd == A_CLSE:
                continue

    def _serve_shell(self, conn, local_id):
        """shell 服务：adb 主协议分帧，WRTE 送数据，CLOSE 表示结束。"""
        self._send(conn, A_WRTE, local_id, 7, self.output)
        self._send(conn, A_CLSE, local_id, 7, b"")

    def _serve_pull(self, conn, local_id):
        """pull 走 sync 子协议：8 字节头（ASCII id + 小端 length）。

        真实设备的行为：收到 RECV 后先回一个 sync 层的 "OKAY"，
        再回若干 "DATA"，最后 "DONE"。这里照做。
        """
        # 先读掉客户端发的 RECV 请求
        head = self._exact(conn, 8)
        sid, length = struct.unpack("<4sI", head)
        assert sid == b"RECV", f"应收到 RECV，实际 {sid!r}"
        self._exact(conn, length)
        # sync 层 OKAY -> DATA -> DONE
        conn.sendall(struct.pack("<4sI", b"OKAY", 0))
        conn.sendall(struct.pack("<4sI", b"DATA", len(self.output)) + self.output)
        conn.sendall(struct.pack("<4sI", b"DONE", 0))

    def _send(self, conn, cmd, arg0=0, arg1=0, payload=b""):
        check = sum(payload) & 0xFFFFFFFF
        conn.sendall(struct.pack("<6I", cmd, arg0, arg1, len(payload), check,
                                cmd ^ 0xFFFFFFFF) + payload)

    def _recv(self, conn):
        header = self._exact(conn, 24)
        cmd, arg0, arg1, dlen, _c, magic = struct.unpack("<6I", header)
        assert magic == (cmd ^ 0xFFFFFFFF), f"magic 校验失败 {cmd:#x} {magic:#x}"
        payload = self._exact(conn, dlen) if dlen else b""
        return cmd, arg0, arg1, payload

    def _exact(self, conn, n):
        out = b""
        while len(out) < n:
            chunk = conn.recv(n - len(out))
            if not chunk:
                break
            out += chunk
        return out

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 测试
def test_magic_is_command_xor_ones():
    """adb 包的 magic 必须是 command ^ 0xFFFFFFFF。"""
    dev = AdbDevice("127.0.0.1", 5555)
    pkt = dev._send_msg.__self__ and None  # 只是占位
    # 直接检查 _send_msg 产生的字节
    import io

    class FakeSock:
        def __init__(self):
            self.buf = b""

        def sendall(self, b):
            self.buf += b

    dev.sock = FakeSock()
    dev._send_msg(A_CNXN, 1, 2, b"hello")
    data = dev.sock.buf
    cmd, arg0, arg1, dlen, check, magic = struct.unpack("<6I", data[:24])
    assert cmd == A_CNXN
    assert magic == (A_CNXN ^ 0xFFFFFFFF), hex(magic)
    assert data[24:] == b"hello"


def test_shell_roundtrip():
    """完整跑一遍：握手 → 开流 → 读输出。"""
    srv = FakeAdbd(output="MiTV-ANSP0\n")
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    time.sleep(0.1)

    dev = AdbDevice("127.0.0.1", srv.port, timeout=10)
    dev.connect()
    out = dev.shell("getprop ro.product.model")
    dev.close()
    srv.close()

    assert out.strip() == "MiTV-ANSP0", repr(out)
    assert srv.services, "服务端没收到 OPEN"
    assert srv.services[0] == "shell:getprop ro.product.model", srv.services


def test_pull_roundtrip():
    srv = FakeAdbd(output="BINARYDATA")
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    time.sleep(0.1)

    import tempfile
    dev = AdbDevice("127.0.0.1", srv.port, timeout=10)
    dev.connect()
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "out.bin"
        dev.pull("/sdcard/x", str(target))
        assert target.read_bytes() == b"BINARYDATA"
    dev.close()
    srv.close()


def test_auth_flow():
    """要求认证时，客户端会走 AUTH 握手并回签名。"""
    srv = FakeAdbd(output="ok\n", require_auth=True)
    t = threading.Thread(target=srv.serve, daemon=True)
    t.start()
    time.sleep(0.1)

    orig = adbmod._rsa_sign
    adbmod._rsa_sign = lambda data: b"\x01" * 256
    try:
        dev = AdbDevice("127.0.0.1", srv.port, timeout=10)
        dev.connect()
        out = dev.shell("echo ok")
        assert out.strip() == "ok", repr(out)
        dev.close()
    finally:
        adbmod._rsa_sign = orig
        srv.close()


def test_connection_refused_gives_clear_error():
    import socket as s

    tmp = s.socket()
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()
    try:
        AdbDevice("127.0.0.1", port, timeout=3).connect()
    except (AdbError, OSError) as e:
        assert "连接" in str(e) or "refused" in str(e).lower() or isinstance(e, OSError), str(e)
        return
    raise AssertionError("连不上的端口竟然连接成功了")


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
