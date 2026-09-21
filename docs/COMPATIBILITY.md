# 格式兼容

| 规则类型 | Surge | Mihomo / FlClash |
| --- | --- | --- |
| 精确域名 | `DOMAIN` | `DOMAIN` |
| 后缀，含根域名 | `DOMAIN-SUFFIX` | `DOMAIN-SUFFIX` |
| 域名正则 | 仅允许审核后的转换 | 保留 `DOMAIN-REGEX` |
| IPv4 | `IP-CIDR`，附 `no-resolve` | `IP-CIDR`，附 `no-resolve` |
| IPv6 | `IP-CIDR6`，附 `no-resolve` | `IP-CIDR6`，附 `no-resolve` |

规范参考：[Surge 域名规则](https://manual.nssurge.com/rules/domain.html) · [Mihomo 规则](https://wiki.metacubex.one/config/rules/)

## OpenAI 正则转换

上游正则：

```text
^chatgpt-async-webps-prod-\S+-\d+\.webpubsub\.azure\.com$
```

Surge 转换：

```text
DOMAIN-WILDCARD,chatgpt-async-webps-prod-*-*.webpubsub.azure.com
```

Surge 通配符无法约束中间字段非空、末段仅含数字，因此比原正则更宽。匹配仍限定服务前缀和 Azure WebPubSub 后缀，不覆盖整个云平台。

转换记录在 [人工补丁](../sources/patches.json) 和 [发布清单](../rules/manifest.json) 中，Surge 文件也附带提示。其他正则转换须审核。

## 规则范围

合集成员和语音 IP 包的选择见 [订阅目录](../rules/README.md)。

规则默认不包含整个共享登录、存储、遥测或云平台。专用端点可经核对后精确补入；来源与 `include` 处理方式见 [数据来源](SOURCES.md)。

## 客户端配置

Surge 文件用于 `RULE-SET`。Mihomo 文件用于 `behavior: classical`、`format: yaml` 的规则源，均需接入已有客户端配置，见 [配置示例](../examples)。

已验证的内核与未覆盖场景见 [验证范围](VALIDATION.md)。
