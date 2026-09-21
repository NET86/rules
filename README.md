# AI 分流规则

[![规则校验](https://github.com/NET86/rules/actions/workflows/ci.yml/badge.svg)](https://github.com/NET86/rules/actions/workflows/ci.yml)
[![规则同步](https://github.com/NET86/rules/actions/workflows/sync.yml/badge.svg)](https://github.com/NET86/rules/actions/workflows/sync.yml)

面向 Surge、Mihomo 和 FlClash 的 AI 分流规则，自动更新、验证后发布。

## 选择规则集

订阅使用 `stable` 分支，`main` 用于开发与测试。以下链接是规则文件，不包含代理节点。

| 规则集 | 用途 | Surge | Mihomo / FlClash |
| --- | --- | --- | --- |
| **ai-daily** | 日常海外 AI 核心域名，含 OpenAI 语音 IP | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-daily.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-daily.yaml) |
| **ai-core** | 更多海外 AI 核心域名，不含语音 IP | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-core.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-core.yaml) |
| **ai-cn** | 国内 AI 分类，出口策略自行选择 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-cn.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-cn.yaml) |

日常使用推荐 `ai-daily`。使用 `ai-core` 且需要 OpenAI 语音时，另加 `openai-voice-ip` 并设置相同策略。完整成员、单厂商和语音订阅见 [订阅目录](rules/README.md)。

## 接入配置

1. 将规则加入已有客户端配置，并选择可用代理节点。
2. 放在宽泛的 Google、Microsoft、GitHub 规则及最终匹配规则之前。
3. `ai-cn` 只负责分类，直连或代理由你的网络环境决定。

示例：[Surge 日常](examples/surge-daily.conf) · [FlClash 日常](examples/flclash-daily.yaml) · [Surge 分包](examples/surge.conf) · [FlClash 分包](examples/flclash-mihomo.yaml)

## 更新与校验

域名主要来自 [V2Fly](https://github.com/v2fly/domain-list-community)，语音 IP 来自 OpenAI 官方数据。官方资料与 Sukka 规则用于发现遗漏，候选经审核后才能补入。

仓库每 6 小时同步，由 Cloudflare 主触发、GitHub 延后兜底。示例配置每小时下载已发布规则。更新经过格式、匹配范围和双内核验证；失败时保留或恢复已验证版本。

[数据来源](docs/SOURCES.md) · [维护说明](docs/MAINTAINING.md) · [验证范围](docs/VALIDATION.md) · [格式兼容](docs/COMPATIBILITY.md) · [调度说明](infra/scheduler/README.md) · [更新记录](CHANGELOG.md)

## 许可

项目采用 [AGPL-3.0](LICENSE)。第三方材料保留各自的版权和许可，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。
