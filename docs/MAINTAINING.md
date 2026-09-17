# 维护与自动化

正常使用只订阅 `stable`。`main` 是开发/候选分支；`last-known-good` 是上一份已验证发布，仅用于恢复，不是长期订阅入口。

## 自动与人工边界

| 变化 | 默认处理 |
| --- | --- |
| 已审批后缀内新增更窄主机 | 自动吸收或被现有 suffix 覆盖，不制造冗余 |
| 上游 commit 变化但消费内容不变 | 自动 no-op |
| 新根域、匹配放宽、新 regex、共享基础设施 | 隔离该变化；其他安全更新继续 |
| `select` 目标从本层消失/移入 include | 视为结构漂移；冻结该厂商删除观察并要求复核 |
| v2fly 临时失败 | 使用验证过的旧 snapshot；删除观察不计时 |
| 官方网页失败/结构漂移 | 官方 radar 降级；production 主链继续 |
| OpenAI Voice 抓取失败 | 使用验证过的旧 Voice IP；运行报告标记 retained |
| 普通上游删除 | 仅健康观察推进；至少 14 天且 3 个不同 UTC 日期后才可自动退役 |
| semantic contract 关键能力最后覆盖消失 | 保留旧规则并报告，不自动删除 |
| 明确撤销 approval | 立即按本地策略撤销，不允许 retention 复活 |
| 构建/独立验证/双核心失败 | 不推进 stable |
| 发布后远端回读或核心验证失败 | 只对 stable 做前滚式回滚并再次验证 |

人工应主要处理：产品成员变化、新根域或新共享云端点、匹配语义放宽、许可证变化、客户端规则语义变化、长期来源降级，以及 semantic contract 的产品定义变化。

## 发布与恢复

1. 在任何新下载、构建或来源抓取之前执行 `release.py --recover-only`：仅用 portable/hash/semantic gate 验证当前 `stable`；若上一轮异常中断，则验证 `last-known-good` 后以普通提交恢复 `stable`。
2. 准备固定版本的 Mihomo 与 FlClash 内嵌核心。
3. 同步 v2fly 与 OpenAI Voice；官方网络文档只做诊断 radar，并保存最近一次成功解析的事实基线。
4. `catalog + approvals + patches` 产生候选；未知/放宽范围隔离。
5. 删除观察只在健康 v2fly/厂商观察下推进；select 结构异常单独冻结相关厂商。
6. 确定性生成 Surge/Mihomo 规则和 manifest。
7. 运行 portable/cross-format/profile/semantic 验证，以及真实 Mihomo 与 FlClash core 验证。
8. 候选提交到 `main` 并按不可变 commit URL 回读实际发布字节；只有候选远端验证成功后才推进 `stable`。
9. `stable` 变化时，原 `stable` 原子推进到 `last-known-good`；新 `stable` 再次从远端回读并跑核心验证。
10. 若 post-promotion 失败，只恢复 `stable`；`main` 保留开发/候选状态，不再构造“新代码 + 旧 rules”的特殊回滚树。

不会 force push / reset 发布历史。并发更新通过远端 ref 比对 fail closed；如果 `stable` 已被独立修改，不覆盖它。

## 状态模型

持久状态只保留必要内容：

- `sources/snapshot/`：实际消费的 v2fly 文件、许可证和 OpenAI Voice JSON；固定内容摘要。
- `sources/automation-state.json`：隔离与删除观察；抓取失败不会制造新的观察日。
- `sources/official-state.json`：最近一次成功解析的官方事实基线；没有运行时间戳，事实未变时不会产生提交噪声，也不直接决定 stable 是否推进。
- `rules/manifest.json`：当前产物、来源、profile、转换边界和摘要。
- `stable` / `last-known-good`：当前发布与上一验证发布。

来源健康、官方网页 fresh/retained、Voice 本次抓取状态和 radar 结果属于**运行报告**，不写进生产 lock 来制造无意义 stable 更新。

如需展示 freshness，优先记录 `last_success_at` 并在读取时计算年龄，不维护 FRESH/RETAINED/STALE/DEGRADED 四套持久数据库。

## 文件职责

- `catalog.json`：厂商与三个显式 profile 成员/预算。
- `approvals.json`：自动变化允许范围；自动化不能自己扩大。
- `patches.json`：少量人工审查过的精确补丁/排除/Surge 适配。
- `semantic-contracts.json`：少量关键正例、关键反例及关键能力保护；不是完整规则数据库。
- `official.json` / `official-state.json`：官方事实 radar 配置与最近解析基线；不直接生成 production rules。
- `intake-policy.json`：官方共享依赖/placeholder 排除策略。
- `automation.json` / `automation-state.json`：删除观察参数与运行状态。
- `watch.json`：只读 Sukka secondary radar 配置；不保存自动 ack baseline。
- `engines.json`：双核心验证固定版本。

## 本地验证

Python 3.12+。在线官方抓取使用 `requirements-intake.txt` 中锁定的浏览器兼容 HTTPS 依赖，仅对固定 OpenAI Help Center URL 的 403 fallback 使用。

~~~sh
python -m pip install --only-binary=:all: --require-hashes -r requirements-intake.txt
python scripts/sync.py
python -m unittest discover -s tests -v
python scripts/rules.py --check
python scripts/verify_rules.py
python scripts/download_mihomo.py
python scripts/verify_mihomo.py
python scripts/verify_mihomo.py --profile split
python scripts/build_flclash_core.py
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core --profile split
python scripts/audit_sources.py
~~~

## Issue 与调度噪声

保留 sync / secondary-radar 两类异常通知；状态不变时不重复制造评论。Secondary radar 每周运行且只读，不提交 baseline、不占用 production publication concurrency。

GitHub Actions cron 可能延迟；公共仓库长期无活动时计划任务也可能被停用。仓库内部无法在“调度完全没有启动”时自证健康，因此不要把历史绿色状态当永久 freshness 证明。无规则变化时不制造空 stable 提交。

不要上传订阅密钥、API key、Cookie、Authorization 或完整 HAR。
