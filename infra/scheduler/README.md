# 定时同步

Worker 只触发 `NET86/rules` 的 `sync.yml`；抓取、验证和发布由 Actions 执行。无运行依赖、数据库或公开 HTTP 入口。

## 调度与去重

| 触发方 | 北京时间 | 跳过条件 |
| --- | --- | --- |
| Cloudflare | `00:01 / 06:01 / 12:01 / 18:01` | 最近 5 小时已有 `main` 的 `workflow_dispatch`。 |
| GitHub 兜底 | 同一小时 `:31` | 最近 5 小时最新 `workflow_dispatch` 成功或仍活跃；失败、取消、过期、无记录或查询失败则补跑。 |

`workflow_dispatch` 包括人工触发；兜底记录不抑制主调度。两者共用发布锁。触发成功不等于执行成功；失败请求不重试。因长期无活动停用的同步和补缺工作流可恢复，手动停用不恢复。同步状态未知时拒绝触发；补缺恢复失败记日志，不阻断主同步。

## 部署

登录 Cloudflare，多账户用 `CLOUDFLARE_ACCOUNT_ID` 指定账户：

```sh
npx --yes wrangler@4.135.0 login --device --browser=false --scopes account:read user:read workers:write workers_scripts:write workers_tail:read
```

使用 **NET86** 创建仅覆盖 **NET86/rules**、权限为 **Actions: read and write** 的细粒度令牌。身份会被校验；到期前更新。在 `infra/scheduler` 执行，令牌只输入隐藏提示框：

```sh
npx --yes wrangler@4.135.0 deploy --dry-run
npx --yes wrangler@4.135.0 secret put GITHUB_TOKEN
npx --yes wrangler@4.135.0 deploy
```

以 Cloudflare 日志和 GitHub 运行记录确认生效。仓库测试命令见[验证说明](../../docs/VALIDATION.md)。

`wrangler dev --test-scheduled` 在配置真实密钥且满足条件时会启动真实同步。停用将 `triggers.crons` 设为空数组并重新部署。

参考：[Cloudflare 定时触发](https://developers.cloudflare.com/workers/configuration/cron-triggers/) · [GitHub 触发接口](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
