# 净利润断层财务数据补缺

优先级为东财、Tushare、Wind Excel。公告清单仍以巨潮正式定期报告为核对依据；预告、快报和摘要不能补成正式报告。

1. 东财已具备有效累计归母净利润及所需同期/前季金额时，不调用备用源。
2. 缺失公司、报告期或单季还原组成项时，Tushare `income` 按公司补查。只取合并累计报表 `report_type=1` 的 `n_income_attr_p`，单位元；不混用单季报表、母公司报表、扣非利润或累计同比。公告日与实际公告日的较晚者不得晚于巨潮目标公告日；同日冲突不任意选值。凭据只读环境变量 `TUSHARE_TOKEN`，云端使用同名Actions Secret。
3. 仍缺项时，读取本机Wind Excel补数快照 `earnings-gap/data/wind_financial_fallback.json`。它必须来源于已有隔离Excel的 `WDF.Addin` 通道，标记 `source=Wind Excel WDF.Addin`、`basis=cumulative_parent_profit`、`unit=CNY`；`rows` 中每项包含 `SECUCODE`、`REPORTDATE`、`NOTICE_DATE`、`PARENT_NETPROFIT`。日期应是该版本的实际披露日，不是取数日期；必须保留插件原始批次作为核验依据。无法核验报告期、版本或单位时不得导入。

Wind是本机补数后可同步使用的最后备选，不是GitHub Ubuntu任务能直接调用的在线服务。本次不新增本机定时任务，不使用WindPy/Wind MCP，不自动购买或反复试探额度。没有合格Wind快照就继续显示待补，输出 `wind_financial_pending` 缺项，不伪装补齐。

Tushare与Wind均只填缺项，不能替换东财已有有效金额。Tushare同公司同截止日不重复查询，每批最多60个补查请求；出现认证、权限或配额错误后，本批其他公司不再重复请求该服务。单笔记录和监控保留组成项来源及披露日，批次保留 `financial_fallback_audit`。旧持仓与已完成的检查不因启用备用源而重建。东财与备用源均失败时保留旧数据并明确失败/待补，不输出零候选的虚假成功。

现有买卖、归母净利增长30%、交易日历、缺口、成本及止盈止损规则不变。公告只有日期、供应商后续修订风险仍存在，不能把日期校验宣称为完整历史发布版本保证。

验收：`python strategies/earnings_gap/test_financial_sources.py`，并运行现有策略、更新、监控、公告处理及浏览器规则回归。部署仅发布本次相关文件，保留其他工作树修改；线上更新成功与数据已全部补齐分别验收。
