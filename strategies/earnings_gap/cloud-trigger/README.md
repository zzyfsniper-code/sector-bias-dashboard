# 净利润断层独立云端触发

这是 Cloudflare Workers Cron 的部署源码。它只调用现有 GitHub 更新任务，不承担选股计算，不改变策略规则，也不替换 GitHub Pages。

2026年10月15日15:20、15:30的真实定时事件暴露了请求参数兼容问题：当前 workerd 不接受 `redirect: 'error'`，请求发出前即报错。16:06已部署修复版本 `838e5714-31cf-465f-8c1e-d7392177358a`，改用 `manual`；现有 HTTP 状态检查继续拒绝重定向，不会跟随跳转传递凭据。原定时配置、去重和超时不立即重试的边界不变。当前状态为“已部署、运行内核回归通过，待下一次真实定时验收”；人工补跑不能代替定时验收。

## 运行方式

所有时间均为北京时间，周一至周五运行，节假日沿用原更新任务的交易日处理。

| 用途 | 原 GitHub 定时配置 | Cloudflare 独立检查 |
| --- | --- | --- |
| 早盘前更新公告和财务候选 | 08:25 | 08:30、08:40、08:50 |
| 收盘归档 | 15:15 | 15:20、15:30、15:40 |

每次先查询本策略在 main 分支的 GitHub 任务。有排队或运行中的任务时不再触发；刚结束的任务最多等待 5 分钟给 Pages 发布留出时间。只有 live.json、monitor.json 同批次、同策略版本，公告核对通过、待处理为零，且与最新成功任务对应时，才视为已更新。下午不能用早盘快照代替收盘归档。

未更新时调用固定仓库 `zzyfsniper-code/sector-bias-dashboard` 的 `earnings-gap-data.yml`，分支固定 main。快照读取失败按未确认处理；GitHub 任务列表无法读取时停止本次操作并记录失败。POST 超时后不立即重试，由下一个定时点先查询 GitHub 确认，避免盲目重复触发。平台自动重试关闭，补查次数限定为上述六个时点。GitHub 自身的延迟定时任务仍可能随后执行，这是保留原定时作为备用的结果。

Worker 不开放公共访问地址。任务结果写入 Cloudflare 日志和调用追踪。网页沿用现有更新时效、任务失败、公告漏收提示；未部署完成前不能声称已启用独立触发。独立触发可以绕过 GitHub schedule 事件延迟，仍依赖 GitHub Actions 的可用性、数据源和 Pages 发布。

## 验证与部署

在此目录使用 Node.js 22 或更高版本，先通过 `npm ci` 安装锁定版本的依赖。

1. 执行 `npm test`，检查更新判断、早晚分离、任务去重、错误恢复、凭据隔离和超时边界。测试包含21项检查，其中5项使用锁定版本的真实 workerd 内核和原生 fetch；所有外发请求均在本地截获，使用测试凭据，不访问生产接口。旧请求参数会使这组运行内核测试失败。
2. 执行 `npm exec -- wrangler deploy --dry-run --outdir .build`，验证 Worker 配置和打包；此步不会部署。
3. 首次使用本机发布工具时，执行 `npm exec -- wrangler login --use-keyring` 完成浏览器授权，执行 `npm exec -- wrangler whoami` 确认账号。本机 Windows 已安装 Wrangler 要求的系统凭据库组件。若存在多个账号，先明确目标账号再部署。Cloudflare MCP 连接与发布工具分别授权。
4. 执行 `npm run deploy` 部署此配置；`predeploy` 自动运行上述测试，失败时停止发布，不要绕过它直接部署。GitHub 凭据必须保存为名为 `GITHUB_TOKEN` 的 Worker Secret。推荐只授权目标仓库、Actions 读写权限的独立细粒度令牌；不需要 Contents 写权限。不得放入源码、普通变量、前端或日志。通过工具配置时，从既有环境变量经标准输入传给 `wrangler secret put GITHUB_TOKEN`，不要将值拼进命令行或写入文件。新账号必须先初始化 Workers 的 workers.dev 子域，即使 Worker 不开放访问地址；本次已创建账号子域 `zzyfsniper-code.workers.dev`，未开放 Worker 公共地址。
5. 读取云端部署版本、Secret 名称和实际 cron 配置，逐项确认。Cloudflare cron 变更最多可能需要 15 分钟传播。检查云端日志中实际发生的 scheduled 事件；若快照已更新，应记录 fresh 并不新增 GitHub 任务。
6. 补触发验收必须证明一次真实云端 scheduled 事件使 GitHub 创建任务，再核对任务成功、live.json/monitor.json 同步和线上页面正常。若当日快照已新，等待下一次常规定时；不得把本机手动 workflow_dispatch 或本地测试称为云端触发验收。

未获得账号授权或未验证真实 scheduled 事件时，不得报告“云端定时验收通过”；应按实际情况分别报告“未部署”或“已部署、待定时验收”。不要删除原 GitHub 定时。

停用时使用 `npm exec -- wrangler delete` 删除此 Worker，保留原 GitHub 更新任务。只处理本项目创建的 `earnings-gap-scheduler`，不要操作其他 Worker。

参考官方说明：[Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)、[Worker Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)、[GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。
