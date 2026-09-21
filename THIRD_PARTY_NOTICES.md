# 第三方声明

本项目采用 [AGPL-3.0](LICENSE)。第三方材料保留原版权与许可；以下说明不改变其授权，也不表示原作者或服务提供方对本项目的背书。

## 规则来源与署名

| 来源 | 许可 | 声明 |
| --- | --- | --- |
| [V2Fly](https://github.com/v2fly/domain-list-community) | [MIT 原文](sources/snapshot/V2FLY-LICENSE) | Copyright (c) 2018-2019 V2Ray. 域名快照固定提交和文件摘要，生成规则保留本声明链接。 |
| [Sukka](https://github.com/SukkaW/Surge) | [AGPL-3.0 原文](https://github.com/SukkaW/Surge/blob/4c5439b2d9d98c39a52691b8662c7e82bd1a2c40/LICENSE) | Copyright Sukka and contributors. 保留派生材料署名；相关修改包括厂商分类、范围筛选、去重及 Surge/Mihomo 格式转换。 |
| [VPSDance](https://github.com/VPSDance/ai-proxy-rules) | [MIT 原文](licenses/VPSDance-MIT.txt) | Copyright (c) 2026 VPSDance. 保留已分发 Google AI 派生补丁的版权与许可通知。 |

各来源在自动更新中的用途见 [数据来源](docs/SOURCES.md)。原 NET86 MIT 许可文本保留于 [licenses/NET86-MIT.txt](licenses/NET86-MIT.txt)。

## 官方资料

OpenAI、Anthropic、Cursor、Google 和 GitHub 的网络资料仅用于提取端点事实并保留出处，不分发网页正文。文档来源见 [官方资料配置](sources/official.json)；[OpenAI 语音数据](https://openai.com/chatgpt-voice.json) 的来源记录在 [快照清单](sources/snapshot/lock.json) 中。

官方资料、商标和服务受各自条款约束，不因被引用而改用本项目许可。

## 验证工具与运行依赖

| 工具或依赖 | 许可 | 使用方式 |
| --- | --- | --- |
| [Mihomo](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/LICENSE) | GPL-3.0 | 下载固定版本进行规则验证，不随仓库分发二进制。 |
| [FlClash](https://github.com/chen08209/FlClash/blob/7c61c90ac20493b474d19c75ec96262b478b4b88/LICENSE) / [内嵌核心](https://github.com/chen08209/Clash.Meta/blob/70f0570405c3c2c47bb113b88db95006d239b346/LICENSE) | GPL-3.0 | 按 [版本配置](sources/engines.json) 构建核心并验证，不随仓库分发二进制。 |
| [curl_cffi](https://github.com/lexiforest/curl_cffi/blob/v0.16.3/LICENSE) | MIT | 官方文档 HTTPS 请求。 |
| cffi | MIT-0，以安装包内 LICENSE 为准 | curl_cffi 运行依赖。 |
| [pycparser](https://github.com/eliben/pycparser/blob/main/LICENSE) | BSD-3-Clause | cffi 运行依赖。 |
| [certifi](https://github.com/certifi/python-certifi/blob/master/LICENSE) | MPL-2.0 | HTTPS 证书包。 |

Python 依赖的版本和文件摘要见 [requirements-intake.txt](requirements-intake.txt)。依赖及其原生组件按原样安装，源码包和二进制包不随本仓库分发；单独分发运行环境时须保留相应许可。GitHub Actions 以固定提交引用，遵循各自许可。

许可证原文保留原语言，本页中文说明不替代原文。
