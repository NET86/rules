# 订阅目录

本页自动生成。日常使用只需选 ai-daily；合集与单厂商分层展示。

下列链接是规则文件，不是节点订阅。stable 是支持的订阅入口；main 仅用于开发与候选。

## 合集

| 版本 | 功能与选择建议 | Surge | Mihomo |
| --- | --- | --- | --- |
| ai-daily | 5 家厂商。日常 AI 核心域名 + OpenAI 官方语音 IP。 | [ai-daily.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-daily.list) | [ai-daily.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-daily.yaml) |
| ai-core | 14 家厂商。海外主流 AI 合集：显式维护的应用级厂商核心域名，不含语音 IP 和共享依赖。 | [ai-core.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-core.list) | [ai-core.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-core.yaml) |
| ai-cn | 10 家厂商。国内主流 AI 独立分类：只包含显式维护的产品端点，不代表全部入口都应直连。 | [ai-cn.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/ai-cn.list) | [ai-cn.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/ai-cn.yaml) |

ai-daily 含日常厂商核心域名和 openai-voice-ip；ai-core 覆盖更多海外厂商但不含 Voice IP。ai-cn 可另外分配策略。

日常厂商：openai、google-ai、claude、grok、perplexity。

## 单厂商

需要独立出口时才选单厂商，并放在合集前。仅含核心域名；OpenAI 语音需同策略的语音 IP 包（ai-daily 已包含）。

### 国外服务

| 文件 | 服务 | Surge | Mihomo |
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

### 国内厂商分类

| 文件 | 服务 | Surge | Mihomo |
| --- | --- | --- | --- |
| deepseek | DeepSeek | [deepseek.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/deepseek.list) | [deepseek.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/deepseek.yaml) |
| qwen | Qwen / Tongyi | [qwen.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/qwen.list) | [qwen.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/qwen.yaml) |
| kimi | Kimi / Moonshot | [kimi.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/kimi.list) | [kimi.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/kimi.yaml) |
| doubao | Doubao / Coze China | [doubao.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/doubao.list) | [doubao.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/doubao.yaml) |
| zhipu | Zhipu / GLM | [zhipu.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/zhipu.list) | [zhipu.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/zhipu.yaml) |
| minimax | MiniMax / Hailuo | [minimax.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/minimax.list) | [minimax.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/minimax.yaml) |
| kling | Kling AI | [kling.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/kling.list) | [kling.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/kling.yaml) |
| baidu-wenxin | Baidu Wenxin / Wenxiaoyan | [baidu-wenxin.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/baidu-wenxin.list) | [baidu-wenxin.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/baidu-wenxin.yaml) |
| tencent-ai | Tencent Yuanbao / Hunyuan | [tencent-ai.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/tencent-ai.list) | [tencent-ai.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/tencent-ai.yaml) |
| iflytek-spark | iFlytek Spark | [iflytek-spark.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/iflytek-spark.list) | [iflytek-spark.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/iflytek-spark.yaml) |

## 可选功能包

| 文件 | 功能 | Surge | Mihomo |
| --- | --- | --- | --- |
| openai-voice-ip | OpenAI 官方语音目的 IP：不含域名；ai-daily 已包含，单厂商 openai 未包含。 | [openai-voice-ip.list](https://raw.githubusercontent.com/NET86/rules/stable/rules/surge/openai-voice-ip.list) | [openai-voice-ip.yaml](https://raw.githubusercontent.com/NET86/rules/stable/rules/mihomo/openai-voice-ip.yaml) |

进程、整片云服务/ASN、共享遥测/登录依赖、第三方托管模型、自建反代不自动包含。

[返回首页](../README.md) · [日常示例](../examples/surge-daily.conf) · [分包示例](../examples/flclash-mihomo.yaml) · [格式边界](../docs/COMPATIBILITY.md)
