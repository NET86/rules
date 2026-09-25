# 定时同步

Worker 只负责按 Cloudflare Cron 固定触发 `NET86/rules` 的 `sync.yml`；抓取、验证和发布由 Actions 执行。无运行依赖、数据库或公开 HTTP 入口。

## 调度与兜底

| 触发方 | 北京时间 | 行为 |
| --- | --- | --- |
| Cloudflare | `00:01 / 06:01 / 12:01 / 18:01` | 每次触发完整同步。 |
| GitHub 兜底 | 每天 `00:31` | 检查最近 6 小时内最后一次带 Cloudflare 标记的 `main` 运行；已完成且成功则跳过，否则执行完整同步。 |

Cloudflare 运行带有 `trigger_source=cloudflare` 标记，运行名为 `Cloudflare scheduled sync`。人工运行不影响定时调度。两个触发方共用发布锁。

GitHub 兜底只覆盖 `00:31` 前最近一轮主调度。该轮仍在排队或运行、失败、取消、无记录或记录查询失败时，执行完整同步。

Cloudflare 自动恢复因长期无活动停用的同步与补缺工作流；手动停用的工作流不会自动恢复。同步状态未知时不触发；补缺恢复失败不阻断主同步。

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
