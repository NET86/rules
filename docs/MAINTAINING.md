# 维护与自动化

正常使用只订阅 `stable`。`main` 是开发/候选分支；`last-known-good` 是上一份已验证发布，仅用于恢复，不是长期订阅入口。

## 自动与人工边界

| 变化 | 默认处理 |
| --- | --- |
| `sources` 专属文件直接新增普通 DOMAIN / DOMAIN-SUFFIX | 自动吸收；新根域本身不再触发人工审批 |
| `sources` 新增 transitive include 规则 | 不继承专属来源权限，隔离并要求复核 |
| 仅来源快照/观察证据变化，订阅产物与产品契约未变 | 保存 main 证据；stable / last-known-good 不轮换 |
| 新 keyword / 未审核 regex / 整个共享平台根域 | 隔离该变化；其他安全更新继续 |
| `select` 目标从本层消失/移入 include | 视为结构漂移；冻结该厂商删除观察并要求复核 |
| 已维护的混合来源产品区段出现未选择规则 | 持续列入现有待审报告；纳入 catalog 或明确 drop 后消失 |
| v2fly 临时失败 | 使用验证过的旧 snapshot；删除观察不计时 |
| 官方网页失败/结构漂移 | 官方 radar 降级；production 主链继续 |
| OpenAI Voice 抓取失败 | 使用验证过的旧 Voice IP；运行报告标记 retained |
| Voice 地址覆盖骤减/骤扩、批量换段或新增 IP 家族 | Voice 单独保留旧版，域名继续更新；复核后才接受异常基线 |
| 普通上游删除 | 仅健康观察推进；至少 14 天且 3 个不同 UTC 日期后才可自动退役 |
| semantic contract 关键能力最后覆盖消失 | 保留旧规则并报告，不自动删除 |
| 从 `select` 移除、加入 `patches.drop` 或删除本地 patch | 立即按本地策略撤销，不允许 retention 复活 |
| 构建/独立验证/双核心失败 | 不推进 stable |
| 发布后远端回读或核心验证失败 | 只对 stable 做前滚式回滚并再次验证 |

人工应主要处理：产品成员变化、transitive include、宽匹配/regex、整个共享平台根域、许可证变化、客户端规则语义变化、长期来源降级，以及 semantic contract 的产品定义变化。专属主上游的普通新域名不再逐条人工确认。

## 发布与恢复

1. 在任何新下载、构建或来源抓取之前执行 `release.py --recover-only`：仅用 portable/hash/semantic gate 验证当前 `stable`；若上一轮异常中断，则验证 `last-known-good` 后以普通提交恢复 `stable`。
2. 准备固定版本的 Mihomo 与 FlClash 内嵌核心。
3. 同步 v2fly 与 OpenAI Voice；官方网络文档只做诊断 radar，并保存最近一次成功解析的事实基线。
4. `catalog + patches` 决定生产授权：专属 `sources` 直接规则自动，混合 `select` 与本地 patch 显式；未授权 provenance 隔离。
5. 删除观察只在健康 v2fly/厂商观察下推进；select 结构异常单独冻结相关厂商。
6. 确定性生成 Surge/Mihomo 规则和 manifest。
7. 运行 portable/cross-format/profile/semantic 验证，以及真实 Mihomo 与 FlClash core 验证。
8. 候选提交到 `main` 并按不可变 commit URL 回读实际发布字节；只有候选远端验证成功后才推进 `stable`。
9. 依据产物摘要、profile/feature、语义契约、格式/许可及转换边界判断新发布；纯来源证据变化不推进 `stable`。`stable` 变化时，原 `stable` 原子推进到 `last-known-good`；远端回读始终以实际 stable 版本为期望，再跑核心验证。
10. 若 post-promotion 失败，只恢复 `stable`；`main` 保留开发/候选状态，不再构造“新代码 + 旧 rules”的特殊回滚树。

不会 force push / reset 发布历史。并发更新通过远端 ref 比对 fail closed；如果 `stable` 已被独立修改，不覆盖它。

## 状态模型

持久状态只保留必要内容：

- `sources/snapshot/`：实际消费的 v2fly 文件、许可证和 OpenAI Voice JSON；固定内容摘要。
- `sources/automation-state.json`：隔离与删除观察；抓取失败不会制造新的观察日。
- `sources/official-state.json`：最近一次成功解析的官方事实基线；没有运行时间戳，事实未变时不会产生提交噪声，也不直接决定 stable 是否推进。
- `rules/manifest.json`：当前产物、来源、profile、转换边界和摘要。
- `stable` / `last-known-good`：当前发布与上一验证发布。

来源健康、官方网页 fresh/retained、Voice 本次抓取状态和 radar 结果属于**运行报告**，不写进生产 lock 来制造无意义 stable 更新。

如需展示 freshness，优先记录 `last_success_at` 并在读取时计算年龄，不维护 FRESH/RETAINED/STALE/DEGRADED 四套持久数据库。

## 文件职责

- `catalog.json`：厂商、三个显式 profile，以及生产授权边界；`sources` 表示信任专属文件的直接规则持续自动维护，`select` 表示只维护混合分类中的显式选择项。
- `patches.json`：少量人工审查过的精确补丁、明确排除和 Surge regex 适配；也是本地撤销/例外的唯一入口。
- `semantic-contracts.json`：少量关键正例、关键反例及关键能力保护；不是完整规则数据库。
- `official.json` / `official-state.json`：官方事实 radar 配置与最近解析基线；不直接生成 production rules。
- `intake-policy.json`：官方共享依赖/placeholder 排除策略。
- `automation.json` / `automation-state.json`：删除观察参数与运行状态。
- `watch.json`：只读 Sukka secondary radar 与混合来源产品区段配置；不保存自动 ack baseline。
- `engines.json`：FlClash 应用与内嵌核心的固定版本；Mihomo 版本及下载摘要固定在 `scripts/download_mihomo.py`。

## 本地验证

Python 3.12+。在线官方抓取使用 `requirements-intake.txt` 中锁定的浏览器兼容 HTTPS 依赖，仅对固定 OpenAI Help Center URL 的 403 fallback 使用。

生产工作流中的可选安装允许失败，实际抓取报告说明是否降级；生产输入、生成、核心和发布验证仍必须通过。Voice 异常变化经核对官方数据后，可用已有 `python scripts/sync.py --voice-file <已核对的官方JSON>` 更新基线；该显式入口仍执行结构与单条范围检查。

~~~sh
python -m pip install --only-binary=:all: --require-hashes -r requirements-intake.txt
python scripts/sync.py
python -m unittest discover -s tests -v
python scripts/rules.py --check
python scripts/verify_rules.py
python scripts/download_mihomo.py
python scripts/verify_mihomo.py
python scripts/verify_mihomo.py --profile split
python scripts/build_flclash_core.py
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core
python scripts/verify_mihomo.py --binary .work/bin/flclash-core --engine-label flclash-core --profile split
python scripts/audit_sources.py
~~~

身份检查扫描已获取的全部 refs，Git 读取失败即失败。main CI、sync 和每周 radar 均执行检查；stable/LKG 独立快进提交不保证立即触发检查。这是误用检测，不是写权限或签名验证。

## Issue 与调度噪声

保留 sync / secondary-radar 两类异常通知；状态不变时不重复制造评论。通知在证据上传后执行，上传失败不会先被当成恢复；通知自身或 runner 收尾失败仍以 Actions 状态为准。Production sync 每 6 小时运行一次；Secondary radar 每周运行且只读，不提交 baseline、不占用 production publication concurrency。

GitHub Actions cron 可能延迟；公共仓库长期无活动时计划任务也可能被停用。仓库内部无法在“调度完全没有启动”时自证健康，因此不要把历史绿色状态当永久 freshness 证明。无规则变化时不制造空 stable 提交。

使用 [Cloudflare 主调度](../infra/scheduler/README.md)：每 6 小时的 `:19` dispatch 原工作流，最近 5 小时已有 dispatch 则跳过。GitHub cron 延后到 `:49`；最新 dispatch 在 5 小时内成功或仍活跃则跳过重型同步，失败或缺失则补跑，历史查询异常也保留兜底。GitHub 兜底空跑记录不抑制 CF。没有数据库、HTTP 入口或新增告警；CF 仍依赖 GitHub API 和 runner。

示例客户端刷新间隔为 1 小时，即 FlClash/Mihomo/Surge 下载 stable 上已经生成的规则文件，不是在本机抓取上游或构建。既有用户配置不会远程自动改写。生效仍取决于上游发现、仓库调度、发布/CDN 和客户端刷新，不构成端到端时效承诺。

## 低频依赖维护

Dependabot 每月检查 Actions 构建组件（检出代码、准备 Python/Go、上传验证报告等）和可选 Python HTTPS 库（curl-cffi、cffi、certifi、pycparser），与分流域名更新无关。每类最多一个未合并 PR；minor/patch 分别进入 `actions-safe` / `transport-safe` 组，大版本单独提出，仍需人工确认。

普通分组升级自动检查、开 PR、测试并合并。`workflow_run` 后续任务只检出可信 main，不执行 PR 代码或下载 PR 产物；重查 Dependabot 身份、固定仓库/分组、文件范围、当前提交与 Linux/Windows 两个 CI job 成功，合并 API 再绑定已验证 SHA。旧提交的绿色结果、大版本、测试失败或不符合范围的修改均不自动合并。没有开启不带测试门槛的通用 auto-merge，也不改动发布分支保护。首次真实依赖升级仍需由实际 PR 验证端到端流程。

Python fetcher 支持 `requirements-intake.txt`，updater 支持更新 hash；依赖 PR 在 Windows/Linux CI 中强制执行 wheel-only / require-hashes 安装，人工重跑也按 PR 作者识别，不能依赖生产流程的可选降级掩盖坏 pin。内置 GITHUB_TOKEN 合并不会再触发 push CI；合并前的 PR CI 已通过，后续规则发布仍跑原完整验证链。失败或大版本 PR 未处理会占用每类的单 PR 上限，这是明确的人工例外。

自定义 Mihomo / FlClash pin 不在 Dependabot 支持范围内，不新增一套版本监控器。升级客户端核心时，核对 FlClash 应用引用的实际 revision，更新已有固定版本后运行上述 daily/split 双核心验证；不得把最新版 Mihomo 当作 FlClash 核心。

不要上传订阅密钥、API key、Cookie、Authorization 或完整 HAR。
