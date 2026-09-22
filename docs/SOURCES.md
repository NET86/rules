# 来源与策略

## 生产授权

域名主要来自 [V2Fly](https://github.com/v2fly/domain-list-community)：`catalog.sources` 授权专用文件中直接写出的规则，include 不继承授权；混合文件仅采用 `catalog.select` 指定域名的直接规则，同域名的多种匹配类型按上游并集处理，逐条过滤排除项。人工补充写入 `patches.add`，必须附 HTTPS 证据和理由。

规则按服务归属分组，不保证服务器地域或直连可用。多模型共用的云 API 不按模型名自动归类；专用 API、下载与产物主机可依据官方资料精确补入。

语音 IP 来自 [OpenAI 官方 JSON](https://openai.com/chatgpt-voice.json)。更新与失败处理见[维护说明](MAINTAINING.md)，合集成员见[订阅目录](../rules/README.md)。

## 发现不等于授权

**官方事实、产品范围、生产授权是三个不同判断。** 网络白名单中的依赖不一定属于 AI 核心。

官方资料、V2Fly 产品区段和 [Sukka AI 规则](https://github.com/SukkaW/Surge/blob/master/Source/non_ip/ai.conf) 用于发现缺口，不自动授权。候选按厂商区分；另一厂商已覆盖或已 drop，不能替当前厂商作决定。候选持续待审，直到覆盖、明确排除或来源撤回。

Source Radar 使用本地快照：`confirmed` 表示证据覆盖候选范围，不表示本次抓取成功或获准生产。exact 不能证明更宽 suffix；更宽证据也不自动授权新的规则表达。读取失败不能推断为 absent。

Google 范围为 Gemini、AI Studio、NotebookLM。GitHub Copilot 只解析 `Specific required domains`；共享平台、遥测、实验和报表排除，精确专用端点仍可待审。不解析 GHE、编辑器、语音和云代理的其他访问清单。

官方提取仅接受完整主机名及前导 `*.` / `.`；局部通配符不能截成父域。

## 文件职责

输入文件位于 [sources/](../sources/)：

| 文件 | 职责 |
| --- | --- |
| `catalog.json` | 厂商、来源授权、显式选择、合集成员与预算 |
| `patches.json` | 人工 add、按厂商精确规则 drop、Surge 正则转换 |
| `semantic-contracts.json` | 独立正反例，不从生成规则反推 |
| `intake-policy.json` | 官方报告的占位符、共享依赖和范围排除 |
| `official.json` / `official-state.json` | 官方来源与提取约束 / 最近有效事实 |
| `watch.json` | 雷达来源、产品区段和仅对雷达生效的忽略项 |
| `automation.json` / `automation-state.json` | 退役阈值 / 待审与删除观察状态 |
| `snapshot/lock.json` | 快照版本、文件及许可证摘要 |
| `engines.json` | FlClash 核心锁定；Mihomo 锁定在 `scripts/download_mihomo.py` |

`patches.drop` 撤销该厂商的生产规则并抑制相同候选；intake exclusion 只筛官方报告；`FORBIDDEN_CORE` 拒绝已知共享根边界进入生产。三者不能合并。`drop` 和 `@ads` 只过滤对应条目，不生成拒绝或直连规则；其他已授权后缀仍可能命中，必须不命中的边界由语义契约验证。官方共享后缀的根边界须通过生产保护一致性测试，窄租户仍按来源授权判断；该保护不是完整 Public Suffix List。

快照、[manifest](../rules/manifest.json) 和订阅由脚本生成，不手改。客户端差异见[兼容说明](COMPATIBILITY.md)，许可与署名见[第三方声明](../THIRD_PARTY_NOTICES.md)。
