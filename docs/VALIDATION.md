# 校验与限制

## 检查什么

| 检查 | 契约 |
| --- | --- |
| 单元测试 | 来源解析、授权隔离、失败保底、退役、雷达、发布恢复、Issue 与调度 |
| 确定性重建 | 固定快照、来源完整性、许可摘要、文件集合及内容一致 |
| 独立产物校验 | 语法、摘要、数量、跨格式差异、合集恰为声明成员与功能包的并集 |
| 语义契约 | 每个单厂商和合集产物的必命中 / 必不命中，不只检查 manifest 声明 |
| Mihomo / FlClash 核心 | 真实解析、HTTP provider 加载、三种配置路由、更新、断网保留与恢复 |
| 发布回读 | 不可变候选及稳定地址的实际下载内容、摘要、语义与核心验证 |

固定语义用例独立于生成规则；动态探针补充当前域名及 IP 边界，不能替代语义契约。语音探针按完整网段并集判断首尾与相邻地址；另用不会发布的固定 IPv6 测试段覆盖 IPv6 路径。正反例必须分别收到明确本地出口响应，超时或断连不能判通过。

## 命令

Python 3.12+、Node；构建 FlClash 核心还需与 [CI](../.github/workflows/ci.yml) 一致的 Go 环境。离线校验现有输入和产物：

```sh
python scripts/check_git_identity.py
python -m unittest discover -s tests -v
python scripts/rules.py --check
python scripts/verify_rules.py
node --test infra/scheduler/worker.test.mjs
```

联网更新会修改快照和产物；更新后重新执行上面的检查：

```sh
python -m pip install --only-binary=:all: --require-hashes -r requirements-intake.txt
python scripts/sync.py
python scripts/audit_sources.py
```

完整内核验证（Windows 的 FlClash 二进制路径加 `.exe`）：

```sh
python scripts/download_mihomo.py
python scripts/verify_mihomo.py
python scripts/verify_mihomo.py --profile split
python scripts/verify_mihomo.py --profile ai-cn
python scripts/build_flclash_core.py
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core --profile split
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core --profile ai-cn
```

## 不保证什么

Surge 在 CI 中没有原生运行时，只执行可移植校验；可用 `verify_rules.py --surge-cli <路径>` 补原生解析。FlClash 验证的是锁定的内嵌核心，不是 GUI / IPC。测试仅使用隔离本地 HTTP，不修改系统代理或 TUN，也不证明远端 AI 登录、账号权限、真实语音 UDP 或全部 DNS 行为可用。

HTTP 503 必须保留活动规则和缓存；畸形 YAML 的内核原生保留能力单独记录，可能为 `false`，因此发布前严格语法检查不可删除。报告位于 `.work/`，以本次执行结果为准。

已发布的 schema 1 语义契约仍可被恢复校验读取；新候选必须使用覆盖所有厂商的 schema 2。不要将这项持久数据兼容当成死代码删除。共享根域保护的边界见[来源与策略](SOURCES.md)，Surge 通配符差异见[兼容说明](COMPATIBILITY.md)。
