# 订阅目录

日常使用推荐 `ai-daily`。以下为 `stable` 规则文件，不包含代理节点。

本页由产品配置自动生成。

## 合集

| 规则集 | 用途 | Surge | Mihomo / FlClash |
| --- | --- | --- | --- |
| ai-daily | 5 家厂商。日常 AI 核心域名，含 OpenAI 官方语音 IP。 | [ai-daily.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-daily.list) | [ai-daily.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-daily.yaml) |
| ai-core | 14 家厂商。更多海外 AI 核心域名，不含语音 IP 和共享依赖。 | [ai-core.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-core.list) | [ai-core.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-core.yaml) |
| ai-cn | 10 家厂商。国内 AI 服务分类，出口策略自行选择。 | [ai-cn.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-cn.list) | [ai-cn.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-cn.yaml) |

使用 ai-core 且需要 OpenAI 语音时，另加 openai-voice-ip 并设置相同策略。

日常厂商：openai、google-ai、claude、grok、perplexity。

## 单厂商

需要独立出口时选择单厂商，并放在合集前。单厂商仅含核心域名；OpenAI 语音需另加语音 IP 包。

### 海外服务

| 文件 | 服务 | Surge | Mihomo / FlClash |
| --- | --- | --- | --- |
| openai | OpenAI / ChatGPT / Sora / Prism | [openai.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/openai.list) | [openai.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/openai.yaml) |
| claude | Anthropic / Claude / Claude Code | [claude.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/claude.list) | [claude.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/claude.yaml) |
| grok | xAI / Grok | [grok.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/grok.list) | [grok.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/grok.yaml) |
| perplexity | Perplexity | [perplexity.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/perplexity.list) | [perplexity.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/perplexity.yaml) |
| google-ai | Gemini / AI Studio / NotebookLM / Google AI | [google-ai.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/google-ai.list) | [google-ai.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/google-ai.yaml) |
| microsoft-copilot | Microsoft Copilot | [microsoft-copilot.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/microsoft-copilot.list) | [microsoft-copilot.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/microsoft-copilot.yaml) |
| github-copilot | GitHub Copilot | [github-copilot.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/github-copilot.list) | [github-copilot.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/github-copilot.yaml) |
| cursor | Cursor | [cursor.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/cursor.list) | [cursor.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/cursor.yaml) |
| poe | Poe | [poe.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/poe.list) | [poe.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/poe.yaml) |
| mistral | Mistral AI | [mistral.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/mistral.list) | [mistral.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/mistral.yaml) |
| elevenlabs | ElevenLabs | [elevenlabs.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/elevenlabs.list) | [elevenlabs.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/elevenlabs.yaml) |
| midjourney | Midjourney | [midjourney.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/midjourney.list) | [midjourney.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/midjourney.yaml) |
| runway | Runway | [runway.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/runway.list) | [runway.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/runway.yaml) |
| suno | Suno | [suno.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/suno.list) | [suno.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/suno.yaml) |

### 国内服务

| 文件 | 服务 | Surge | Mihomo / FlClash |
| --- | --- | --- | --- |
| deepseek | DeepSeek | [deepseek.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/deepseek.list) | [deepseek.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/deepseek.yaml) |
| qwen | 通义千问 / Qwen | [qwen.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/qwen.list) | [qwen.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/qwen.yaml) |
| kimi | Kimi / 月之暗面 | [kimi.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/kimi.list) | [kimi.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/kimi.yaml) |
| doubao | 豆包 / 扣子 | [doubao.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/doubao.list) | [doubao.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/doubao.yaml) |
| zhipu | 智谱 / GLM | [zhipu.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/zhipu.list) | [zhipu.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/zhipu.yaml) |
| minimax | MiniMax / 海螺 | [minimax.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/minimax.list) | [minimax.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/minimax.yaml) |
| kling | 可灵 AI | [kling.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/kling.list) | [kling.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/kling.yaml) |
| baidu-wenxin | 文心一言 / 文小言 | [baidu-wenxin.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/baidu-wenxin.list) | [baidu-wenxin.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/baidu-wenxin.yaml) |
| tencent-ai | 腾讯元宝 / 混元 | [tencent-ai.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/tencent-ai.list) | [tencent-ai.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/tencent-ai.yaml) |
| iflytek-spark | 讯飞星火 | [iflytek-spark.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/iflytek-spark.list) | [iflytek-spark.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/iflytek-spark.yaml) |

## 可选功能包

| 文件 | 功能 | Surge | Mihomo / FlClash |
| --- | --- | --- | --- |
| openai-voice-ip | OpenAI 官方语音目的 IP；ai-daily 已包含，单厂商 openai 未包含。 | [openai-voice-ip.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/openai-voice-ip.list) | [openai-voice-ip.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/openai-voice-ip.yaml) |

规则范围与客户端差异见 [格式兼容](../docs/COMPATIBILITY.md)。

[返回首页](../README.md) · [Surge 示例](../examples/surge-daily.conf) · [FlClash 示例](../examples/flclash-daily.yaml)
