# 格式与匹配语义

| 规范规则 | Surge RULE-SET | FlClash / Mihomo classical YAML |
| --- | --- | --- |
| 精确域名 | DOMAIN | DOMAIN |
| 后缀（含根域名） | DOMAIN-SUFFIX | DOMAIN-SUFFIX |
| 域名正则 | 仅允许 `sources/patches.json` 中人工审核的转换 | DOMAIN-REGEX 原样保留 |
| IPv4 | IP-CIDR + no-resolve | IP-CIDR + no-resolve |
| IPv6 | IP-CIDR6 + no-resolve | IP-CIDR6 + no-resolve |

Surge 域名规则：https://manual.nssurge.com/rules/domain.html

Mihomo 规则：https://wiki.metacubex.one/config/rules/

## OpenAI 的一个已知非等价转换

上游原始模式：

```text
^chatgpt-async-webps-prod-\S+-\d+\.webpubsub\.azure\.com$
```

Surge 输出：

```text
DOMAIN-WILDCARD,chatgpt-async-webps-prod-*-*.webpubsub.azure.com
```

通配符不能保持“中间字段至少一个字符、最后字段只能是数字”的全部约束，因此 Surge 这一条比 Mihomo 原正则更宽。本项目保留特定服务前缀与 Azure WebPubSub 后缀，不扩大成整个 `webpubsub.azure.com` 或 Azure 域。

manifest 必须记录该转换和原因；Surge 产物必须带 warning。未审核的新正则不会自动新增 wildcard adapter，而是进入隔离/人工复核。

## 三个 aggregate profile

`ai-daily`、`ai-core`、`ai-cn` 的成员由 `sources/catalog.json` 显式声明，不从厂商数量或 group 隐式推导。

- `ai-daily`：日常厂商核心域名 + `openai-voice-ip`。
- `ai-core`：海外厂商核心域名，不含 Voice IP。
- `ai-cn`：国内 AI 分类。

当前厂商名单和数量见 [自动生成的订阅目录](../rules/README.md)。

`ai-daily` **不是** `ai-core + openai-voice-ip`。独立 verifier 会把 aggregate 产物与声明成员/功能包的实际单厂商产物做集合等价检查，避免 profile 静默膨胀或漏项。

共享认证、存储、遥测、包仓库、整片云平台和第三方通用依赖不再提供默认 compat 规则包。若未来确实需要某个共享依赖，应重新评估它是否值得精确纳入产品范围，而不是恢复一个大而宽的兼容合集。

## `select` 与 include

v2fly `sources` 类型按上游分类文件语义允许递归 include；`select` 类型只读取当前分类文件本层显式规则。

这样可以避免例如只选择 `meta.ai` 之类单项时，snapshot 因分类文件 include 自动拖入大量不相关 vendor。若上游把已选择域名移到 include 中，本项目会把它视为结构变化并冻结相关删除观察，而不是自动跟随 include 扩大依赖面。

## FlClash / Mihomo

`rules/mihomo/*.yaml` 是 `behavior: classical`、`format: yaml` 的 rule-provider 内容，不是完整客户端配置。

CI 同时验证固定 Mihomo 与 `sources/engines.json` 指定的 FlClash 内嵌路由核心，包括 provider 加载、路由探针和 HTTP 更新/恢复。该结果不等于所有 FlClash UI 版本、覆写机制或网络环境都已经实测。

## Surge 验证边界

仓库独立解析 Surge rule-set 产物并与 Mihomo 做跨格式检查；如有可用 Surge CLI，可额外执行原生 `--check`。CI 不把静态解析器冒充 Surge macOS/iOS 真实运行时，也不声称验证了客户端缓存或系统网络扩展。
