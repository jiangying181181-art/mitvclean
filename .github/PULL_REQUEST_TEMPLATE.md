## 你要做什么

<!-- 例：给 mitv-ansp0 画像补一条实测结论 / 修 adb.py 的 AUTH 兼容 -->

## 机型信息（如果涉及机型画像）

| 项 | 值 |
|---|---|
| `ro.product.model` |  |
| `ro.product.device` |  |
| Android 版本 |  |
| 固件版本 |  |
| 是否实机验证过 |  |

## 改了什么

<!-- 一两句说清：动了哪个文件、为什么这么动 -->

## 实测证据

<!-- 关键命令与它的真实输出，不要写“应该可以” -->

```
```

## 自查

- [ ] 没有 `uninstall`，只有 `pm disable-user`
- [ ] 没有硬编码 IP / 设备型号 / 个人路径
- [ ] 包名做了合法性校验
- [ ] 命令逐条下发，没有用分号链式
- [ ] 桌面 / 系统设置 / 平台输入服务没被禁
- [ ] `python tests/test_offline.py` 全过
- [ ] `python tests/test_adb_protocol.py` 全过
- [ ] 提交里不含自己的 IP、MAC、SN、设备序列号
- [ ] Python 3.9 兼容（没用 3.10+ 语法）
- [ ] 没引入第三方依赖
