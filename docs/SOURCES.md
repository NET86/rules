# 数据来源

自动更新来源与补缺参考分开管理。官方网络白名单说明某项功能访问哪些端点，不等于其中所有域名都应进入 AI 分流。

## 自动更新来源

| 来源 | 用途 | 更新边界 |
| --- | --- | --- |
| [V2Fly](https://github.com/v2fly/domain-list-community) | 通用域名来源，固定提交与文件摘要 | 专属分类中的直接规则可自动更新；混合分类仅维护明确选定项。 |
| [OpenAI 语音数据](https://openai.com/chatgpt-voice.json) | 语音目的 IP | 通过地址、前缀和覆盖变化检查后更新。 |
| [人工补丁](../sources/patches.json) | 精确补缺、排除及格式适配 | 修改需审核，之后由构建流程统一生成。 |

## 域名范围

[catalog.json](../sources/catalog.json) 定义厂商、合集成员和来源权限：

- `sources`：专属分类直接列出的精确域名和后缀规则可自动更新。读取 `include` 保留上游语义，但被包含文件中的新增规则需另行审核。
- `select`：仅维护混合分类本层明确选定的域名。选定项消失或移入 `include` 时报告结构变化，并冻结相关删除观察。
- 整个共享平台根域、已知公共后缀和未审核的宽匹配规则不会自动进入核心规则。厂商专用的精确主机可单独核对。

Google AI 范围以 Gemini、AI Studio、NotebookLM 为主。完整产品名单见 [订阅目录](../rules/README.md)。

## 补缺监测

| 来源 | 频率 | 检查范围 |
| --- | --- | --- |
| [官方资料](../sources/official.json) | 随每 6 小时同步 | OpenAI、Claude Code、Cursor、Google AI、GitHub Copilot 的指定章节或结构化 API。 |
| [Sukka AI 源文件](https://github.com/SukkaW/Surge/blob/master/Source/non_ip/ai.conf) | 每周 | [watch.json](../sources/watch.json) 指定的产品区段，只比较精确域名与后缀。 |
| V2Fly 混合分类 | 随每 6 小时同步 | 已维护产品区段中尚未选定的域名。 |

已覆盖和明确排除的条目静默处理；新候选持续留在待审报告，直到被接纳、明确排除或由来源撤回。候选不会自动扩大产品范围。章节变化或抓取失败会报告异常；官方资料保留最近有效基线，规则更新继续使用已验证输入。

GitHub Copilot 仅检查 `Specific required domains` 章节。共享 GitHub 服务、遥测、实验及企业用量报告按用途排除；`githubusercontent.com` 下的精确专用主机仍可进入待审。GHE、编辑器、语音模型下载和云端代理的通用访问清单不在检查范围内。

官方提取支持完整主机及前导 `*.` / `.` 后缀；主机中间或末尾的通配符不转成父域。共享登录、支付、存储、遥测等端点按 [排除策略](../sources/intake-policy.json) 处理，具体产品补缺记录在人工补丁中。

## 来源记录

[快照清单](../sources/snapshot/lock.json) 固定实际使用的上游提交、文件摘要和许可摘要；[发布清单](../rules/manifest.json) 记录规则出处、产物摘要及格式差异。官方资料仅保存提取事实和来源链接。

版权与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
