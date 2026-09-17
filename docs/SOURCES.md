# 来源、事实与生产权限

本仓库区分两件事：**谁能提供事实证据**，以及**谁能自动改变 production rules**。官方资料通常更接近事实原点，但企业 firewall allowlist 并不天然等于 proxy-routing list。

## 生产输入

| 来源 | 角色 | 自动改变 production |
| --- | --- | --- |
| [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) | 唯一通用域名生产流；固定 commit，MIT | 仅在 catalog + approvals 已审范围内可以 |
| [OpenAI Voice JSON](https://openai.com/chatgpt-voice.json) | 独立、结构化、用途明确的语音目的 IP | 通过公网 IP / 前缀 / 数量异常检查后可以 |
| `sources/patches.json` | 少量明确纠错与补缺 | patch 本身需人工审查；之后由确定性构建自动发布 |

v2fly 的目标是 geosite 域名分类，不负责决定某域名应代理、直连或阻断。本项目只消费明确产品范围内的规则，并通过 `approvals.json` 限制自动变化边界。

### `sources` 与 `select`

- `sources`：厂商明确对应一个上游文件时，允许按 v2fly 文件语义递归 include。
- `select`：只读取指定分类文件**本层显式规则**，不递归 include。
- 如果 `select` 目标从本层移动进 include，视为结构变化并隔离该厂商的删除观察；不自动扩大隐式依赖，也不把它当普通退役。

## 官方事实 radar

`sources/official.json` 当前监测 OpenAI、Anthropic/Claude Code、Cursor、Google Code Assist / Generative Language 等指定网络文档或结构化 API。提取结果只进入运行报告与 gap 分析，**不与 v2fly 自动 union**。

这样处理的原因是官方网络清单常混合：

- 已被更宽厂商 suffix 覆盖的精确主机；
- Auth0、Stripe、Datadog、Intercom、Google Storage、GitHub 等共享依赖；
- telemetry、updater、installer、enterprise feature、plugin marketplace 等可选功能；
- 某个固定 S3 / Azure Blob / WebPubSub 主机；
- 真正值得精确补入的厂商专用缺口。

官方文档可以证明“某功能需要访问某端点”，但不能自动证明“该端点的全部流量都应该进入 AI 专用出口”。因此新根域、共享云主机或产品范围变化必须显式判断后才能形成 patch / approval。

官方抓取或解析失败时保留已知事实基线用于诊断，但不会改变 production candidates，也不会因为网页失败把规则解释成空清单。

## Secondary radar

只保留 [Sukka `Source/non_ip/ai.conf`](https://github.com/SukkaW/Surge/blob/master/Source/non_ip/ai.conf) 作为每周低频、只读的 gap radar：

- 已覆盖规则静默处理；
- 过宽 keyword / URL 规则和明确排除项忽略；
- 未覆盖的 DOMAIN / DOMAIN-SUFFIX 只形成候选报告；
- 候选必须通过 v2fly、官方证据或明确人工 patch 才能进入 production。

RuleGo、VPSDance 和 Sukka compiled output 不再作为常态自动 radar。减少来源数量是为了降低相关来源造成的“假独立证据”、通知噪声和长期维护面。

## 当前产品范围

- `ai-daily`：OpenAI、Google Gemini、Claude、Grok、Perplexity + OpenAI Voice IP。
- `ai-core`：上述 5 家，加 Microsoft Copilot、GitHub Copilot、Cursor、Mistral、Poe、Midjourney、Runway、Suno、ElevenLabs。
- `ai-cn`：DeepSeek、Qwen、Kimi、豆包/Coze China、智谱/GLM、MiniMax/海螺、可灵、百度文心/文小言、腾讯元宝/混元、讯飞星火。

Google 默认只选 Gemini / AI Studio / NotebookLM 相关专用端点，不因 `google-deepmind` 分类文件包含更多实验或企业产品而自动扩张。

## 许可与历史证据

当前组合项目继续采用 AGPL-3.0，并保留已有 MIT / Sukka / VPSDance 等历史通知。Sukka 从生产输入降为 radar，不等于既往已经分发的组合内容自动变成 MIT，因此本轮不做许可迁移。

未来生成物不再以 Sukka 或 VPSDance 作为生产规则来源；历史来源、版权和许可证说明保留在 `THIRD_PARTY_NOTICES.md` 与私有历史归档中。生成订阅文件只保留简短 SPDX 与 notices 链接，不重复嵌入完整许可正文。官方网页只保存必要的提取事实/摘要和原始 URL，不重新分发整页内容。

OpenAI Help Center 在部分网络上会拒绝标准库 HTTPS 客户端，因此只对固定的 OpenAI 网络说明 URL 保留受限的浏览器兼容 HTTPS fallback：不跟随重定向、限制响应大小，并仍需通过章节和形状检查。
