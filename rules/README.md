# 订阅目录

日常使用推荐 `ai-daily`。以下为 `stable` 规则文件，不包含代理节点。

<!-- 本页由 scripts/rules.py 自动生成，请勿手改。 -->

## 合集

| 规则集 | 用途 | Surge | Mihomo |
| --- | --- | --- | --- |
| ai-daily | 5 家厂商。日常 AI 核心域名，含 OpenAI 官方语音 IP。 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-daily.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-daily.yaml) |
| ai-core | 14 家厂商。更多海外 AI 核心域名，不含语音 IP 和共享依赖。 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-core.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-core.yaml) |
| ai-cn | 10 家厂商。国内 AI 服务分类，出口策略自行选择。 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-cn.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-cn.yaml) |

使用 `ai-core` 或单厂商 `openai` 且需要语音时，另加 `openai-voice-ip` 并设置相同策略。

日常厂商：openai、google-ai、claude、grok、perplexity。

## 单厂商

仅含核心域名。需要独立出口时选用，并放在合集前。

### 海外服务

| 文件 | 服务 | Surge | Mihomo |
| --- | --- | --- | --- |
| openai | OpenAI / ChatGPT / Sora / Prism | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/openai.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/openai.yaml) |
| claude | Anthropic / Claude / Claude Code | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/claude.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/claude.yaml) |
| grok | xAI / Grok | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/grok.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/grok.yaml) |
| perplexity | Perplexity | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/perplexity.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/perplexity.yaml) |
| google-ai | Gemini / AI Studio / NotebookLM / Google AI | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/google-ai.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/google-ai.yaml) |
| microsoft-copilot | Microsoft Copilot | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/microsoft-copilot.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/microsoft-copilot.yaml) |
| github-copilot | GitHub Copilot | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/github-copilot.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/github-copilot.yaml) |
| cursor | Cursor | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/cursor.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/cursor.yaml) |
| poe | Poe | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/poe.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/poe.yaml) |
| mistral | Mistral AI | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/mistral.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/mistral.yaml) |
| elevenlabs | ElevenLabs | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/elevenlabs.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/elevenlabs.yaml) |
| midjourney | Midjourney | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/midjourney.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/midjourney.yaml) |
| runway | Runway | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/runway.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/runway.yaml) |
| suno | Suno | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/suno.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/suno.yaml) |

### 国内服务

| 文件 | 服务 | Surge | Mihomo |
| --- | --- | --- | --- |
| deepseek | DeepSeek | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/deepseek.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/deepseek.yaml) |
| qwen | 通义千问 / Qwen | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/qwen.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/qwen.yaml) |
| kimi | Kimi / 月之暗面 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/kimi.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/kimi.yaml) |
| doubao | 豆包 / 扣子 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/doubao.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/doubao.yaml) |
| zhipu | 智谱 / GLM | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/zhipu.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/zhipu.yaml) |
| minimax | MiniMax / 海螺 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/minimax.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/minimax.yaml) |
| kling | 可灵 AI | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/kling.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/kling.yaml) |
| baidu-wenxin | 文心一言 / 文小言 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/baidu-wenxin.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/baidu-wenxin.yaml) |
| tencent-ai | 腾讯元宝 / 混元 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/tencent-ai.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/tencent-ai.yaml) |
| iflytek-spark | 讯飞星火 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/iflytek-spark.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/iflytek-spark.yaml) |

## 可选功能包

| 文件 | 功能 | Surge | Mihomo |
| --- | --- | --- | --- |
| openai-voice-ip | OpenAI 官方语音目的 IP；ai-daily 已包含，单厂商 openai 未包含。 | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/openai-voice-ip.list) | [订阅](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/openai-voice-ip.yaml) |

规则范围与客户端差异见 [格式兼容](../docs/COMPATIBILITY.md)。

[返回首页](../README.md) · [Surge 示例](../examples/surge-daily.conf) · [Mihomo 示例](../examples/flclash-daily.yaml)
