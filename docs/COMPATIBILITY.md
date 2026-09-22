# 客户端兼容

| 规则 | Surge | Mihomo / FlClash |
| --- | --- | --- |
| 精确主机 | `DOMAIN` | `DOMAIN` |
| 根域及子域 | `DOMAIN-SUFFIX` | `DOMAIN-SUFFIX` |
| 已审核正则 | 转为受限通配符 | `DOMAIN-REGEX` |
| IPv4 / IPv6 | `IP-CIDR` / `IP-CIDR6`，`no-resolve` | 同左 |

Surge 使用 `RULE-SET`。Mihomo / FlClash 使用 `rule-providers`，配置 `behavior: classical`、`format: yaml`；接入见[示例](../README.md#配置)。

## OpenAI 正则转换

OpenAI 的正则：

```text
^chatgpt-async-webps-prod-\S+-\d+\.webpubsub\.azure\.com$
```

在 Surge 中转换为：

```text
DOMAIN-WILDCARD,chatgpt-async-webps-prod-*-*.webpubsub.azure.com
```

通配符不能保留非空和纯数字约束，因此比正则更宽，但仍限定固定前缀和 Web PubSub 后缀，不匹配整个 Azure。转换必须在 [patches.json](../sources/patches.json) 审核并在 manifest 声明；其他正则不能自动套用。

校验与实际客户端限制见[验证说明](VALIDATION.md)。格式依据：[Surge](https://manual.nssurge.com/rules/domain.html)、[Mihomo](https://wiki.metacubex.one/config/rules/)。
