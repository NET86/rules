# 验证范围与记录

正常发布不设人工 smoke test 门槛。机器验证按“它真正证明什么”分层，避免用 manifest 自己生成的期望值冒充产品正确性。

## 五层验证

| 层 | 证明什么 | 不证明什么 |
| --- | --- | --- |
| Layer 1：parser / compiler | 输入语法、路径安全、类型转换、确定性生成正确 | 域名应该属于哪个产品 |
| Layer 2：cross-format | Surge / Mihomo 在共同支持语义内一致；已声明 adapter 被显式处理 | 一个更宽 adapter 因为“已声明”就一定安全 |
| Layer 3：engine consistency | 实际内核能加载 provider，并按生成规则执行 | manifest 中的规则本身就是正确产品定义 |
| Layer 4：independent semantic contracts | 少量关键正例必须命中、关键反例必须不命中；aggregate profile 精确等于声明成员/功能包并集 | 全部产品功能、全部域名永远正确 |
| Layer 5：source/release fail-safe | 抓取失败、删除观察、远端回读、稳定分支恢复不会静默污染 stable | GitHub 调度完全没启动时还能由仓库内部自证健康 |

## 当前自动覆盖

- 单元/回归：审批边界、select 不递归 include、删除观察冻结、官方只读 radar、Voice fallback、通知、发布/恢复故障注入。
- Portable gate：独立解析 committed Surge/Mihomo 产物，校验非空、去重、数量、摘要、许可和已声明格式差异。
- Profile equivalence：`ai-daily` / `ai-core` / `ai-cn` 的实际规则集合必须严格等于 manifest 声明的成员及 `profile_features` 的并集，不能多也不能少。
- Semantic contracts：直接读取实际单厂商产物和 aggregate 产物验证关键正反例，不用 provenance 自证。当前全部 24 家厂商均有独立契约；缺失厂商、空用例、相互矛盾或厂商错配均阻止发布。新候选必须使用 schema 2，旧 schema 1 只保留发布恢复兼容。
- Mihomo：固定版本真实 HTTP rule-provider 加载、数量核对、本机路由探针、provider 刷新/故障恢复。分别验证 ai-daily、海外分包和 ai-cn；Voice 每个网段的首尾及相邻地址均执行探针，相邻网段按完整并集判断，国内合集不应命中 Voice IP。
- 隔离探针只使用 HTTP 专用监听端口，避免 Windows 对同号 UDP 端口的限制使混合监听误失败；不据此声称验证 SOCKS/UDP 流量。
- FlClash core：从 `sources/engines.json` 固定的 FlClash 内嵌核心构建 CLI，用同一隔离测试验证；不是用独立最新版 Mihomo 冒充。
- Publication read-back：候选和 stable 的 manifest、所有规则文件以及 semantic contract 都按不可变/稳定 URL 下载并核对摘要，再运行核心验证。
- Recovery：临时 Git 仓库覆盖 candidate validation failure、post-promotion failure、并发 stable/main 更新、缺失 LKG 和下一轮恢复。
- 已确认缺陷回归：混合来源的新入口候选持续存在；区域 S3/公共后缀边界隔离；Voice 截断保留旧版、等价网段拆合自动通过；仅来源证据变化不轮换 stable，远端验证仍使用真实 stable 契约。
- 本轮补强回归：百度/腾讯归属互换而合集不变仍必须失败；非 daily 厂商的关键入口删除受到保护；依赖 PR 落后 main 不合并，检查后 main 并发前进也由真实 Git 拒绝推送。
- 雷达发现、区段变化与 Voice 截断的行为测试使用固定隔离样本，不能假设本轮真实上游没有待审项或 Voice 始终维持某个数量。生产数据继续由独立校验与真实内核验证约束。
- Cloudflare 调度：Node 内置测试覆盖身份拒绝、近期运行去重、固定仓库/工作流 dispatch 及 API 失败；部署前执行 Wrangler dry-run。该测试不代表已部署或真实定时执行成功。

## 独立 semantic contract

`sources/semantic-contracts.json` 只放少量关键产品事实：例如 OpenAI API / ChatGPT 必须命中，Stripe/Google Storage 等共享依赖不得因为官方文档列出就进入相应 AI profile；Google 必须保护 Gemini 主站和 Generative Language API，同时明确 `www.google.com`、`storage.googleapis.com`、Antigravity 等不属于当前默认范围。

它不是完整规则数据库，也不复制全部规则。每家只保留少量产品事实与反例；产品成员和预算仍由 `catalog.json` 管理。新增厂商需同步增加契约，普通域名更新无需逐条增加测试。

共享域边界使用有限禁止表与区域 S3 模式，覆盖已知相关云平台及公共后缀；不是完整 Public Suffix List，不声称能排除所有未知共享平台。Voice 相对保护检查网段覆盖变化，不能证明官方地址的全部产品归属。

## Manifest-derived 探针的正确定位

根据 manifest 生成根域、子域、欺骗后缀和相似主机的动态探针仍然有价值，但只证明“内核按照当前规则执行”。如果错误规则已经进入 manifest，这一层可能自洽通过，因此不能替代独立 semantic contract。

## 已知限制

Mihomo 某些版本可能把坏 YAML 接受为空 provider；因此不能把 provider update API 成功码当作规则有效。项目在发布前用独立 strict parser 拒绝坏内容，并单独实测 HTTP 下载失败后的旧缓存行为。

Surge 对一条 OpenAI WebPubSub `DOMAIN-REGEX` 没有同等原生语法，当前转换为经过审核但更宽的 `DOMAIN-WILDCARD`。该差异必须出现在 manifest / 产物 warning 中，不宣称严格等价，也不允许自动新增同类宽化转换。

## 没有声称验证

- Surge macOS/iOS 真实运行时、系统网络扩展和客户端更新缓存。
- FlClash UI 导入、覆写持久性、IPC 包装及未固定的其它核心版本。
- ChatGPT/Claude/Gemini 等真实账号、登录、上传、语音或 API 功能。
- 节点地域、IP 声誉、账号状态、DNS/UDP、防火墙、运营商或客户端本地缓存。

这些问题出现实际故障时再定位；日常更新不要求用户重复做人工 smoke test。

Actions artifact 应保存 sync/release 报告、portable validation、Mihomo/FlClash validation 和必要日志，但不得包含订阅密钥、Cookie、Authorization 或私人配置。
