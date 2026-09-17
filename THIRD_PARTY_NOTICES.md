# Third-party notices / 上游许可证复核

复核日期：2026-09-16。组合项目继续采用 [AGPL-3.0](LICENSE)。历史版本曾吸收 Sukka 派生材料，本轮已将 Sukka 降级为只读 radar，但这不会自动把既往组合工作重新许可为 MIT；因此保留相关归因与历史通知。原 NET86 MIT 文本保存在 [licenses/NET86-MIT.txt](licenses/NET86-MIT.txt)，既往版本的许可不会因新版本切换而被追溯撤销。

## 核验结论

| 来源 | 已核验许可 / 限制 | 实际处理 |
| --- | --- | --- |
| [Sukka](https://github.com/SukkaW/Surge/blob/4c5439b2d9d98c39a52691b8662c7e82bd1a2c40/LICENSE) | AGPL-3.0；[README](https://github.com/SukkaW/Surge#条款和协议) 仅将 china_ip 文件列为其它许可，AI 文件不在该例外 | 历史版本曾吸收 `Source/non_ip/ai.conf`；当前仅把上游 Source 文件作为只读 gap radar，不复制进 production snapshot，不自动导入 |
| [v2fly](https://github.com/v2fly/domain-list-community/blob/6fe5416797ec88d29a3a1c69ce1431d73b955e88/LICENSE) | MIT，Copyright (c) 2018-2019 V2Ray | 当前唯一通用域名生产流；固定实际消费 commit/文件并保留 MIT 通知 |
| [VPSDance](https://github.com/VPSDance/ai-proxy-rules/blob/bfddc1078de74f5a12976c0c5800344766f4085a/LICENSE) | MIT，Copyright (c) 2026 VPSDance | 历史版本曾引用固定 commit 的 Google AI 补丁；当前不再作为 production 或常态 radar，历史通知继续保留 |
| [RuleGo ASCII master](https://github.com/ConnersHua/RuleGo/tree/master) | 当前核验分支未发现明确 LICENSE/COPYING | 历史上仅用于差异 radar；当前不再常态抓取，也未整包导入或改授 AGPL |
| OpenAI / Anthropic / Cursor 官方资料 | 未确认这些网络清单存在独立的开源再分发授权 | 只提取网络端点事实与章节摘要，不复制整页正文，不声称上游资料已改授 AGPL |
| [Google 官方文档](https://developers.google.com/terms/site-policies) | 默认文档 CC BY 4.0、示例代码 Apache-2.0，另有明确例外优先 | 只提取相关端点事实，保留文档来源；不将网页许可与 API 服务条款混为一谈 |
| [OpenAI 语音 JSON](https://openai.com/chatgpt-voice.json) | [官方网络说明](https://help.openai.com/en/articles/9247338) 指向的公开事实清单；未确认独立开源许可证 | 保留来源和用途，不称官方背书，不与爬虫 IP 清单混用 |
| [Mihomo](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/LICENSE) | GPL-3.0 | 固定官方二进制仅在忽略的工作目录验证，不随本仓库分发 |
| [FlClash](https://github.com/chen08209/FlClash/blob/7c61c90ac20493b474d19c75ec96262b478b4b88/LICENSE) / [其核心](https://github.com/chen08209/Clash.Meta/blob/70f0570405c3c2c47bb113b88db95006d239b346/LICENSE) | GPL-3.0 | 固定子模块源码在 CI 构建验证，不分发二进制；不会被本项目重新许可 |

上述核验支持当前的“AGPL 组合输出 + 保留 MIT 通知”处理，不代表逐条追溯验证所有上游贡献者权属，也不是法律担保。服务文档、商标和第三方资料的权利仍归原权利人。

## Sukka historical attribution and current radar role

Copyright Sukka and contributors. Source: [SukkaW/Surge](https://github.com/SukkaW/Surge). Historical NET86 releases beginning 2026-09-15 used a pinned copy of `Source/non_ip/ai.conf` and performed vendor classification, scope narrowing, selected omissions, deduplication and Surge/Mihomo conversion. Those releases were modified works rather than unchanged Sukka releases and were not endorsed by Sukka.

Historical snapshots, locks, licenses and commit metadata are preserved separately in private archival repositories. The new public `NET86/rules` repository starts from a clean history and does not carry those historical commits. Current automation fetches the Sukka Source file only as a read-only secondary gap radar; findings cannot change production candidates automatically.

Required attribution and license notices for previously distributed portions are retained here. Existing AGPL obligations and historical notices are not erased by the clean-history migration. Current v2fly production intake still validates its pinned license digest before accepting a new snapshot; secondary radar sources have no production intake authority.

## v2fly/domain-list-community

Copyright (c) 2018-2019 V2Ray. The complete MIT license accompanies the snapshot at [sources/snapshot/V2FLY-LICENSE](sources/snapshot/V2FLY-LICENSE). Generated subscription files link back to this notice instead of embedding the full MIT text. Input commit and hashes are locked; these MIT portions remain subject to their original notices within the AGPL combined work.

## VPSDance/ai-proxy-rules historical notice

Historical releases referenced a reviewed VPSDance commit for a Google AI patch. Current production rules no longer depend on that patch or source, but the original notice is retained for those distributed historical portions:

MIT License

Copyright (c) 2026 VPSDance

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Other sources and tools

Current secondary radar is stateless/read-only: it stores the source URL in policy and emits only run-time gap diagnostics, not a persistent copy or reviewed-candidate fingerprint database. Individual unresolved domain facts can appear in diagnostic reports; this does not authorize copying an entire collection.

Official pages are fetched into temporary memory for endpoint extraction; no full documentation pages are redistributed. Domain facts, service names and source links do not imply endorsement, account eligibility or permission to use the underlying service.

Python standard-library code is imported, not vendored; GitHub-hosted actions are pinned references, not copied into this source tree. Third-party build/runtime dependencies remain under their own licenses. If binaries or full documentation are distributed later, their separate redistribution obligations require another review.

## Optional official-document HTTPS transport

requirements-intake.txt pins curl_cffi 0.16.3 ([MIT](https://github.com/lexiforest/curl_cffi/blob/v0.16.3/LICENSE)), cffi 2.1.1 (MIT-0, verified installed distribution LICENSE), pycparser 3.0 ([BSD-3-Clause](https://github.com/eliben/pycparser/blob/main/LICENSE)) and certifi 2026.7.22 ([MPL-2.0 certificate bundle](https://github.com/certifi/python-certifi/blob/master/LICENSE)), including PyPI wheel hashes. These packages and their native dependencies are installed unmodified for runtime use; their binary/source packages are not redistributed by this repository. Preserve their own notices when separately redistributing an environment. No third-party account, scraping service or private credentials are used.
