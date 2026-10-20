# ADB over TCP 协议实现笔记

本项目的 `mitvclean/adb.py` 是从零实现的 ADB 客户端（纯标准库，不依赖 adb.exe）。
这份笔记记录实现过程中**抓包实测**到的关键细节 —— 网上流传的很多说法是错的。

## 方法：用中间人代理抓官方 adb 的报文

```python
# 起一个转发器：本地端口 -> 真机:5555，中间记录双向字节
# 然后让官方 adb 连这个转发器，就能看到它的每一个包
```

对照 `adb devices` 的官方行为和 AOSP 文档，能定位到 4 处偏差。

---

## 一、包头（24 字节，6 个小端 u32）

| 偏移 | 长度 | 字段 |
|---|---|---|
| 0 | 4 | command |
| 4 | 4 | arg0 |
| 8 | 4 | arg1 |
| 12 | 4 | data_length |
| 16 | 4 | data_check（负载字节和）|
| 20 | 4 | **magic = command ^ 0xFFFFFFFF** |

⚠️ magic 不是固定 0xFFFFFFFF，而是**随 command 变化**。写死会导致设备直接丢包。

## 二、握手

```
client → CNXN(arg0=0x01000001, arg1=0x00100000, payload=banner)
device → AUTH(arg0=1, payload=token20)          # 要认证
client → AUTH(arg0=2, payload=签名256字节)        # 签完
device → CNXN(payload=设备信息)                    # 认证通过
```

**CNXN 版本号**：AOSP 常量 `A_VERSION` 是 `0x01000000`，但**官方 adb 实际发的是 `0x01000001`**，
老固件（Android 9/10）认后者。照抄 AOSP 常量会握手失败。

**banner**：格式是 `host::<serial>:<features>\0`。adbd 会按 features 决定用哪种流协议，
声明不全会导致后续服务不可用。官方 adb 的完整 features 列表见 `adb.py` 里的 `_handshake()`。

## 三、AUTH 签名格式（最容易踩坑的地方）

设备用 `RSA_public_decrypt` 验签后，**把解出的明文和 token 逐字节比较**。

所以客户端要做的不是标准 PKCS#1 签名，而是：

```
00 01 FF FF ... FF 00 || 3021300906052b0e03021a05000414 || <token 原文>
└── PKCS#1 type 1 填充 ──┘ └─ SHA-1 DigestInfo 前缀(15B) ─┘ └─ 原始 token
```

三个要点：
1. **末尾放的是 token 本身，不是 token 的 SHA-1 摘要**
2. 中间保留了 15 字节的 SHA-1 DigestInfo 前缀（但摘要位置放的是 token）
3. `0xFF` 的个数 = `k - 3 - len(DigestInfo) - len(token)`

用标准 `EVP_PKEY_sign`（PKCS#1 + SHA1 摘要）→ 设备验签失败 → AUTH 无限循环。
用裸 RSA（无 DigestInfo）→ 同样失败。

验证方法：拿官方 adb 抓的 token + 签名，用同一把私钥本地复现，看字节是否完全一致。

## 四、shell 服务

**服务名要用 v2 形式**：

```
shell,v2,TERM=dumb,raw:<命令>
```

不是 `shell:<命令>`。v1 的 `shell:` 在新 adbd 上可能被拒。

**v2 的输出帧格式**：

```
1 字节 类型 + 4 字节**小端**长度 + N 字节数据
```

| 类型 | 含义 |
|---|---|
| 0x01 | stdout |
| 0x02 | stdin EOF |
| 0x03 | stderr |
| 0x04 | exit code |

⚠️ **长度是小端**。按大端读会得到 83886080 这种荒谬值，导致解析全乱。
⚠️ stderr 帧（0x03）必须剔除，否则会混进命令输出里。

## 五、pull 走 sync 子协议（8 字节头）

和 shell 不同，pull 是独立分帧：

```
4 字节 ASCII id + 4 字节小端 length + 负载
```

流程：开 `sync:` 流 → 发 `RECV` + 路径 → 收若干 `DATA` 块 → 收 `DONE`。
注意 `sync:` 流的 OKAY 之后，整个字节流都是 8 字节 sync 帧，不能再用 24 字节主协议头解析。

## 六、小米 adbd 的特性：同一连接上不能连续开流

实测 MiTV-ANSP0（Android 9）上，**同一条连接里连续开第二个 shell 流会被 CLSE 拒绝**：

```
第 1 条命令  → OK
第 2 条命令  → CLSE（设备拒绝打开）
第 3 条命令  → OK
第 4 条命令  → CLSE
```

隔一条就好，说明是上一条流的 CLSE 还没被设备处理完。

两种解法，本项目都用了：
1. `shell()` 结束后主动发 CLSE
2. `run()` 在失败时**换一条新连接重试**（更稳，官方 adb 也是每条命令一条连接）

## 七、为什么不用现成的库

| 方案 | 问题 |
|---|---|
| `adb-shell` (pip) | 要装第三方依赖；签名实现与 AOSP 不一致时会 AUTH 循环 |
| `adb.exe` / platform-tools | 要额外下载 8MB；二进制分发有平台限制 |
| 自己实现 | 零依赖，但要照着上面的细节写对 |

本项目选自己实现，因为它同时解决了"免安装"和"可读性"——
协议细节全在代码注释里，读者能看懂每一步为什么这么写。
