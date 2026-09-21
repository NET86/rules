# rules

[![Validate rules](https://github.com/NET86/rules/actions/workflows/ci.yml/badge.svg)](https://github.com/NET86/rules/actions/workflows/ci.yml)
[![Sync reviewed upstreams](https://github.com/NET86/rules/actions/workflows/sync.yml/badge.svg)](https://github.com/NET86/rules/actions/workflows/sync.yml)

Surge / Mihomo 规则仓库。当前主要维护常用海外与国内 AI 服务分流规则，自动更新并持续校验。

## AI 规则集

推荐使用 `stable` 分支订阅；`main` 用于开发与测试。

| 规则集 | 适合场景 | Surge | Mihomo |
| --- | --- | --- | --- |
| **ai-daily** | 日常常用海外 AI 核心域名 + OpenAI 官方语音 IP | [ai-daily.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-daily.list) | [ai-daily.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-daily.yaml) |
| **ai-core** | 更完整的海外 AI 核心域名合集，不含 Voice IP | [ai-core.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-core.list) | [ai-core.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-core.yaml) |
| **ai-cn** | 国内 AI 服务分类，可独立选择直连或代理策略 | [ai-cn.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-cn.list) | [ai-cn.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-cn.yaml) |

多数用户可直接使用 `ai-daily`；需要更多海外 AI 服务时使用 `ai-core`，需要 OpenAI 语音分流时另加 `openai-voice-ip` 并使用相同策略。各合集的厂商数量、完整成员和单独订阅入口统一见 [自动生成的订阅目录](rules/README.md)。

## 使用说明

- 规则文件不是完整客户端配置，需要加入你现有的 Surge / Mihomo 配置中。
- AI 规则建议放在宽泛的 Google、Microsoft、GitHub、Global、DIRECT、MATCH 等规则之前。
- `ai-cn` 只负责分类，具体走直连还是代理由你的网络环境决定。
- OpenAI 域名与 Voice IP 如需使用同一出口，请设置为相同策略。

示例：[Surge 日常](examples/surge-daily.conf) / [FlClash 日常](examples/flclash-daily.yaml) / [Surge 分包](examples/surge.conf) / [FlClash 分包](examples/flclash-mihomo.yaml)

## 数据来源与更新

规则主要基于 [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) 和 OpenAI 官方 Voice 数据维护。官方网络文档用于补充核对，不会未经审核直接加入规则。

自动更新会经过范围、格式、规则一致性和实际运行验证；如果更新异常，`stable` 会继续保留上一份已验证版本。

仓库每 6 小时计划同步：[Cloudflare 主触发、GitHub 延后兜底](infra/scheduler/README.md)。客户端示例每 1 小时下载已发布的规则文件，不在客户端生成规则；已有配置需自行采用该间隔。仅来源证据变化不会产生空发布，无需新增告警服务。

更多说明：[数据来源](docs/SOURCES.md) / [维护方式](docs/MAINTAINING.md) / [验证说明](docs/VALIDATION.md) / [格式兼容](docs/COMPATIBILITY.md)

## 许可

项目按 [AGPL-3.0](LICENSE) 分发，并保留相关第三方许可与署名。详情见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
