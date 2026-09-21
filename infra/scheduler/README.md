# Cloudflare 主调度与 GitHub 兜底

一个无运行依赖、无 HTTP 入口的 Worker，每 6 小时（北京时间 `00:01/06:01/12:01/18:01`，UTC `04:01/10:01/16:01/22:01`）通过 GitHub API 发起 `workflow_dispatch`，相当于点击 `NET86/rules` 的 `sync.yml` 的 Run workflow。实际抓取、构建、验证与发布仍由 GitHub Actions 执行。最近 5 小时已有 main 的 `workflow_dispatch` 记录则跳过，避免人工触发或重复事件造成短时间重复构建。GitHub 兜底运行记录不抑制 CF 主调度。

GitHub cron 改到同一小时的 `:31`，比 CF 晚 30 分钟。它实际开始时检查最新 main dispatch：最近 5 小时已成功或仍在排队/运行，则跳过重型同步；失败、取消、过期、无记录或无法读取历史时，执行完整验证与发布。两者复用原发布锁；不存储状态、不新增告警。GitHub 兜底空跑不会被下次当成主同步成功。

CF 改善触发时机，**不能保证 GitHub runner 立即开始或来源抓取成功**。验证、恢复与异常处理仍由原工作流负责。GitHub API/Actions 故障时 Worker 也无法完成同步；不自动重试 POST，以免产生重复运行。主任务失败时由稍后的 GitHub 兜底补跑，不依赖 CF 判断发布健康。

若工作流被 GitHub 因 60 天无仓库活动自动停用（`disabled_inactivity`），补触发前会恢复启用；维护者手动停用（`disabled_manually`）则保持停用。未知状态不触发。

## 一次性部署

1. 登录 Cloudflare：`npx --yes wrangler@4.135.0 login --device --browser=false --scopes account:read user:read workers:write workers_scripts:write workers_tail:read`。用 Chrome 打开终端给出的设备授权页并输入临时代码，无需 localhost 回跳。
2. 以 **NET86** 登录 GitHub，创建只覆盖 **NET86/rules** 的 fine-grained PAT，仅授予 **Actions: read and write**（Metadata read 自动附带）。Worker 每次验证 token 身份，不使用其它账户或本机通用 OAuth token。到期前需更新一次 secret。
3. 在此目录依次执行（PAT 只粘贴进隐藏输入，不写入仓库）：

```sh
npx --yes wrangler@4.135.0 deploy --dry-run
npx --yes wrangler@4.135.0 secret put GITHUB_TOKEN
npx --yes wrangler@4.135.0 deploy
```

多账户时用 `CLOUDFLARE_ACCOUNT_ID` 指定目标账户。Cron 配置传播可能需要约 15 分钟；以 Cloudflare 执行日志与 GitHub 的实际运行记录核验。`dispatched` 只表示 GitHub 接受触发，后续结果看 Actions。

## 验证

```sh
node --test infra/scheduler/worker.test.mjs
```

从仓库根执行测试，无需安装 npm 依赖。可用 `wrangler dev --test-scheduled` 在本机测试 scheduled 入口；它在具备真实 secret 且历史已过期时会触发真实 GitHub 同步。禁用时把 `triggers.crons` 改为空数组再部署。

参考：[Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)、[GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。
