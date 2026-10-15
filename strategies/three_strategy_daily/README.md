# 三策略每日总控

该入口只负责固定编排，不修改任何策略规则：

1. 五维成长价值轮动；
2. 中证500资金流向与底部杠杆；
3. 多资产风险平价。

三个子策略严格串行，每个固定脚本只运行一次。各子脚本只完成数据刷新、信号生成和本地校验；总控脚本在所有子进程结束后创建一次合并 GitHub 提交，先等待两分钟，再查询该提交对应的 Pages 构建终态（每15秒查询，最多额外10分钟），构建成功后留出30秒缓存传播时间，最后对成功策略的线上 `run_id` 各检查一次。构建失败或超时不会重新提交、重新运行子策略或重试数据接口。某个策略失败不会阻断后续策略，失败策略的线上页面保持旧版本。

## 2026-10-14 发布核验修复

2026-10-13 总控 `three_strategy_live_20261013_210458` 的三个子策略均成功，合并提交 `459737e75a3b07cac2a99d1c9d62a309e1ec14da` 在21:06:48创建。旧脚本21:09:02结束单次线上核验，但该提交的 Pages 构建直到21:09:18才完成，自定义部署直到21:09:21才完成，因此等待两分钟不足以确认上线。

仓库实际 Pages 模式是 `legacy`，从 `main` 分支根目录发布。`.github/workflows/deploy.yml` 现在先查询发布模式：`legacy` 时跳过重复的自定义部署，只有 `workflow` 模式才执行 artifact 部署；自定义并发组与分支自动部署分开。

总控统一结果新增 `publish.build`，记录构建模式、目标提交、查询次数和构建状态。构建失败归入 `batch_pages_build`；部署成功但页面批次不匹配仍归入 `batch_online_verification`。策略中心请求失败会记录实际原因，不再统一误报为三个策略的 `run_id` 不匹配。

现有自动化仍只运行总控脚本一次；21点触发时间、三个策略的规则、参数、串行顺序、一次提交和一次最终页面核验均保持原设置。

## 2026-10-15 HTTPS核验修复

10月14日晚批次 `three_strategy_live_20261014_210142` 的数据更新和发布均成功，Pages构建检查也为PASS。最后访问策略中心时，PowerShell报告 `The SSL connection could not be established`，旧逻辑因此跳过全部策略页面检查，统一报为失败。

公开页面核验改由 `verify_online.py` 一次执行：使用Python requests，`trust_env=False`，与已经成功的发布器使用相同的直连方式；证书验证保持开启，不重试、不降级HTTP。每个地址仍只请求一次，策略中心失败也继续检查全部策略数据文件。仅从JSON的实际 `run_id` 或 `meta.runId` 字段核对批次，避免在说明文字中包含同名字符串时误通过。

结果存入 `publish.verification` 和本批次的 `*.verify.stdout.log`、`*.verify.stderr.log`，区分TLS、超时、HTTP错误、数据格式错误和批次不符。只有策略中心与全部成功策略页面都核验通过，整批才可PASS；中心单独失败而策略页面正常时，保留各策略PASS，整批报告PARTIAL（退出码2），中心错误写入 `publish.failure_stage` 和 `publish.error_summary`。

保留原始10月14日失败日志；修复后的独立只读核验结果为 `logs/daily/repair_20261015.verify.stdout.log`。未重跑子策略、未重新拉取行情或修改信号、权重和触发时间。

测试：`test_verify_online.py` 五项测试；`test_orchestrator.py` 九项测试，分别通过Windows PowerShell 5.1与PowerShell 7运行。

正常运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_daily_update.ps1
```

只校验当前三个持久化批次，不启动子脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_daily_update.ps1 -ValidateOnly
```

统一结果位于 `logs\daily\latest.json`。退出码为 `0` 表示三策略全部通过，`2` 表示部分失败，`1` 表示全部失败或总控校验失败。
