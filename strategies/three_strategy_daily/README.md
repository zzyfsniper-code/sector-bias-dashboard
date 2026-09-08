# 三策略每日总控

该入口只负责固定编排，不修改任何策略规则：

1. 五维成长价值轮动；
2. 中证500资金流向与底部杠杆；
3. 多资产风险平价。

三个子策略严格串行，每个固定脚本只运行一次。各子脚本自行完成数据刷新、信号生成、GitHub发布和线上核验；总控脚本在所有子进程结束后写入统一结果。

正常运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_daily_update.ps1
```

只校验当前三个持久化批次，不启动子脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_daily_update.ps1 -ValidateOnly
```

统一结果位于 `logs\daily\latest.json`。退出码为 `0` 表示三策略全部通过，`2` 表示部分失败，`1` 表示全部失败或总控校验失败。
