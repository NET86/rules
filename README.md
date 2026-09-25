# AI 分流规则

[![规则校验](https://github.com/NET86/rules/actions/workflows/ci.yml/badge.svg)](https://github.com/NET86/rules/actions/workflows/ci.yml)
[![规则同步](https://github.com/NET86/rules/actions/workflows/sync.yml/badge.svg)](https://github.com/NET86/rules/actions/workflows/sync.yml)

AI 分流规则，每日自动更新（支持Surge、Mihomo）

## 订阅

| 规则集 | 用途 | Surge | Mihomo |
| --- | --- | --- | --- |
| `ai-daily` | 日常 AI，含 OpenAI 语音 IP | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-daily.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-daily.yaml) |
| `ai-core` | 更多海外 AI，不含语音 IP | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-core.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-core.yaml) |
| `ai-cn` | 国内 AI，出口策略自行选择 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-cn.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-cn.yaml) |

日常推荐 `ai-daily`。使用 `ai-core` 或单厂商 `openai` 且需要语音时，另加 `openai-voice-ip` 并设置相同策略。全部厂商和功能包见[订阅目录](rules/README.md)。

## 配置

将规则绑定到自己的出口策略。单厂商规则放在合集前，AI 规则放在宽泛平台规则和兜底规则前。不要同时添加用途重叠的合集。

[Surge 日常示例](examples/surge-daily.conf) · [Mihomo 日常示例](examples/flclash-daily.yaml) · [Surge 分拆示例](examples/surge.conf) · [Mihomo 分拆示例](examples/flclash-mihomo.yaml)

## 说明

[来源与范围](docs/SOURCES.md) · [维护与自动化](docs/MAINTAINING.md) · [校验与限制](docs/VALIDATION.md) · [客户端兼容](docs/COMPATIBILITY.md) · [更新记录](CHANGELOG.md)

[AGPL-3.0-only](LICENSE)；第三方许可与来源条款见[第三方声明](THIRD_PARTY_NOTICES.md)。
