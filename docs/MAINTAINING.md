# 维护说明

订阅使用 `stable`；`main` 保存开发与候选版本；`last-known-good` 保存上一份已验证发布，用于恢复。

## 自动更新与人工审核

| 情况 | 处理 |
| --- | --- |
| 专属来源直接新增普通域名 | 自动吸收。 |
| 混合分类的新条目、被包含文件的新规则、宽匹配或未审核正则 | 进入待审，其他安全更新继续。 |
| 选定域名消失或移入被包含文件 | 报告结构变化，冻结相关删除观察。 |
| 抓取失败 | 沿用有效基线，删除观察不计入失败日期。 |
| 语音 IP 覆盖骤变 | 保留旧版并报告，其他域名更新继续。 |
| 普通上游删除 | 健康观察至少 14 天、覆盖 3 个不同 UTC 日期后退役。 |
| 删除导致关键语义用例失效 | 保留旧规则并报告。 |
| 从选定项移除、增加明确排除或删除人工补丁 | 按本地策略立即撤销。 |
| 校验失败 | 不推进 `stable`；发布后失败则恢复已验证版本。 |
| 仅来源证据变化 | 保存证据，不轮换发布分支。 |

来源和范围定义见 [数据来源](SOURCES.md)。

## 发布流程

1. 验证 `stable`；需要恢复时，先从 `last-known-good` 创建恢复提交。
2. 获取固定验证内核，刷新上游与官方资料，执行范围检查及删除观察。
3. 生成规则，通过单元测试、跨格式检查、语义用例和双内核验证。
4. 提交候选到 `main`，按不可变提交地址回读文件并再次验证。
5. 将已验证候选发布到 `stable`，同时将原发布保留为 `last-known-good`。
6. 回读稳定订阅并验证；失败时以新提交恢复 `stable`，不改写历史。

发布会核对远端分支位置；并发变化时停止，避免覆盖他人更新。订阅内容和产品契约未变时不发布空版本。

## 配置与记录

以下文件位于 `sources/`，除特别注明外：

| 文件 | 职责 |
| --- | --- |
| `catalog.json` | 产品、合集成员和来源权限。 |
| `patches.json` | 审核后的补缺、排除与 Surge 正则适配。 |
| `semantic-contracts.json` | 关键命中与不命中用例。 |
| `official.json` / `official-state.json` | 官方资料配置与最近有效事实。 |
| `intake-policy.json` | 共享端点和占位域名排除策略。 |
| `watch.json` | Sukka 与混合分类的监测区段。 |
| `automation.json` / `automation-state.json` | 删除观察参数、隔离与保留状态。 |
| `snapshot/` | 上游文件、许可和语音数据快照。 |
| `engines.json` | FlClash 应用及内嵌核心版本；Mihomo 版本见 `scripts/download_mihomo.py`。 |
| `rules/manifest.json`（仓库根目录下） | 产物、来源、合集成员、格式差异与摘要。 |

来源抓取状态和待审项保存在运行报告中。Actions 摘要区分抓取成功、沿用旧版、无有效基线及本地输入；发布成功不代表所有来源都抓取成功。

## 本地验证

使用 Python 3.12+。FlClash 核心构建还需要与 CI 一致的 Go 环境。离线检查已有产物：

```sh
python -m unittest discover -s tests -v
python scripts/rules.py --check
python scripts/verify_rules.py
node --test infra/scheduler/worker.test.mjs
```

更新来源并验证真实内核：

```sh
python -m pip install --only-binary=:all: --require-hashes -r requirements-intake.txt
python scripts/sync.py
python scripts/download_mihomo.py
python scripts/verify_mihomo.py
python scripts/verify_mihomo.py --profile split
python scripts/verify_mihomo.py --profile ai-cn
python scripts/build_flclash_core.py
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core --profile split
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core --profile ai-cn
python scripts/audit_sources.py
```

浏览器兼容 HTTPS 依赖仅用于 OpenAI 文档返回 403 时的后备请求。依赖安装失败不会直接阻止生产同步；实际抓取失败时记录异常并沿用有效基线。CI 必须通过锁定依赖安装和真实传输测试。

核实语音数据后，可用 `python scripts/sync.py --voice-file <官方JSON路径>` 更新基线；仍会检查结构和单条网段范围。修改规则配置后运行 `python scripts/rules.py` 重新生成产物，再执行校验。

## 调度与异常报告

规则每 6 小时同步，Sukka 每周检查。Cloudflare 主触发和 GitHub 延后兜底的时间、去重及部署方式见 [调度说明](../infra/scheduler/README.md)。客户端示例每小时下载已发布规则；已有配置需自行设置刷新间隔。

同步与来源检查各维护一个异常 Issue。状态不变时不重复评论，问题消失后自动关闭。报告上传成功后才更新 Issue；工作流最终状态以 Actions 为准。调度、来源、CDN 和客户端缓存均可能延迟，绿色历史记录不代表当前资料始终最新。

## 依赖升级

Dependabot 每周检查 GitHub Actions 和 Python HTTPS 依赖，包含主版本更新。每类最多一个待合并 PR；通过当前提交的 Linux、Windows 完整 CI 后自动合并。

自动合并只接受指定仓库、Dependabot 分组和文件范围。验证提交必须包含当前 `main`，以普通快进推送合入；主分支变化或测试失败时保持未合并，等待重新变基和验证。合并任务不执行 PR 代码或下载 PR 产物。

Mihomo 与 FlClash 的固定版本需手动更新，并执行全部双内核验证。FlClash 必须使用应用实际引用的核心版本。

身份检查扫描已获取的 Git 引用；它用于发现账户误用，不替代访问权限控制。请勿提交订阅密钥、API 密钥、Cookie、Authorization 或私人网络记录。
