# 定时同步

Cloudflare Worker 按时调用 GitHub API，触发 `NET86/rules` 的 `sync.yml` 工作流；抓取、生成、验证和发布均由 GitHub Actions 执行。Worker 无运行依赖、数据库或公开 HTTP 入口。

## 时间与去重

| 触发方 | 北京时间 | 执行条件 |
| --- | --- | --- |
| Cloudflare 主调度 | `00:01 / 06:01 / 12:01 / 18:01` | 最近 5 小时已有 `main` 的 `workflow_dispatch` 记录时跳过。 |
| GitHub 兜底 | 同一小时的 `:31` | 实际启动时，最近 5 小时的最新 `workflow_dispatch` 已成功或仍活跃则跳过；失败、取消、过期、无记录或查询失败时补跑。 |

`workflow_dispatch` 包括 Cloudflare API 触发和人工点击“Run workflow”。GitHub 兜底记录不抑制主调度，两者共用发布锁。Cloudflare 对应 UTC 时刻为 `04:01 / 10:01 / 16:01 / 22:01`。

触发成功仅表示 GitHub 接受请求，执行结果以 Actions 为准。失败请求不重试，避免重复运行。

工作流因长期无活动自动停用时会恢复启用；维护者手动停用则保持停用，未知状态不触发。

## 部署

1. 登录 Cloudflare：

   ```sh
   npx --yes wrangler@4.135.0 login --device --browser=false --scopes account:read user:read workers:write workers_scripts:write workers_tail:read
   ```

   在浏览器打开终端显示的授权页并输入临时代码。

2. 使用 **NET86** 创建仅覆盖 **NET86/rules** 的 GitHub 细粒度令牌，授予 **Actions: read and write**。令牌身份会被校验，到期前需更新密钥。
3. 在 `infra/scheduler` 目录执行，令牌仅输入隐藏提示框：

   ```sh
   npx --yes wrangler@4.135.0 deploy --dry-run
   npx --yes wrangler@4.135.0 secret put GITHUB_TOKEN
   npx --yes wrangler@4.135.0 deploy
   ```

多账户环境使用 `CLOUDFLARE_ACCOUNT_ID` 指定账户。部署后以 Cloudflare 日志和 GitHub 运行记录确认生效，定时配置传播可能需要约 15 分钟。

## 验证与停用

仓库根目录运行：

```sh
node --test infra/scheduler/worker.test.mjs
```

本地可用 `wrangler dev --test-scheduled` 测试定时入口；配置真实密钥且满足触发条件时，会启动真实 GitHub 同步。停用时将 `triggers.crons` 设为空数组并重新部署。

参考：[Cloudflare 定时触发](https://developers.cloudflare.com/workers/configuration/cron-triggers/) · [GitHub 工作流触发接口](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
