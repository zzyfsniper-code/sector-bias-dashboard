from __future__ import annotations

import argparse
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import tushare as ts
from scipy.optimize import minimize


STRATEGY_DIR = Path(__file__).resolve().parent
REPO_DIR = Path(r"D:\agent工作目录\数据看板工作文件夹")
PAGE_DIR = REPO_DIR / "all-weather-risk-parity"
LIVE_DIR = STRATEGY_DIR / "data" / "live"
RESULTS_DIR = STRATEGY_DIR / "results" / "daily"
LOG_DIR = STRATEGY_DIR / "logs" / "daily"
SEED_PATH = Path(r"D:\agent工作目录\A股趋势看板\交易策略回测\strategies\four_asset_rotation_extension\data\tushare_20260904\etf_daily.csv.gz")

CORE = ["510300.SH", "513100.SH", "518880.SH", "511010.SH"]
CASH = "511880.SH"
ALL_CODES = CORE + [CASH]
ASSET_INFO = {
    "510300.SH": {"name": "沪深300ETF", "role": "权益", "market": "A股"},
    "513100.SH": {"name": "纳指ETF", "role": "权益", "market": "海外权益"},
    "518880.SH": {"name": "黄金ETF", "role": "黄金", "market": "商品"},
    "511010.SH": {"name": "国债ETF", "role": "债券", "market": "利率债"},
    "511880.SH": {"name": "货币ETF", "role": "现金", "market": "现金替代"},
}
LEVERAGE = 1.5
FINANCING_RATES = {"levered_0": 0.0, "levered_3": 0.03}
ONE_WAY_BPS = 10.0


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_frame(path: Path, frame: pd.DataFrame, **kwargs: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if path.suffix == ".gz":
        frame.to_csv(tmp, index=False, compression="gzip", **kwargs)
    elif path.suffix == ".parquet":
        frame.to_parquet(tmp, index=False)
    else:
        frame.to_csv(tmp, index=False, encoding="utf-8-sig", **kwargs)
    tmp.replace(path)


def month_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    return pd.Series(index, index=index).groupby(index.to_period("M")).max().tolist()


def quarter_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    return [date for date in month_end_dates(index) if date.month in {3, 6, 9, 12}]


def load_prices() -> pd.DataFrame:
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"seed price file not found: {SEED_PATH}")
    seed = pd.read_csv(SEED_PATH, compression="gzip", dtype={"trade_date": str})
    seed = seed.loc[seed["ts_code"].isin(ALL_CODES), ["ts_code", "trade_date", "adj_close"]].copy()
    seed["trade_date"] = pd.to_datetime(seed["trade_date"], format="%Y%m%d")
    delta_path = LIVE_DIR / "etf_daily_delta.parquet"
    if delta_path.exists():
        delta = pd.read_parquet(delta_path)
        delta = delta.loc[delta["ts_code"].isin(ALL_CODES), ["ts_code", "trade_date", "adj_close"]].copy()
        delta["trade_date"] = pd.to_datetime(delta["trade_date"])
        seed = pd.concat([seed, delta], ignore_index=True)
    seed = seed.drop_duplicates(["ts_code", "trade_date"], keep="last")
    prices = seed.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
    calendar = prices["510300.SH"].dropna().index
    return prices.reindex(calendar).reindex(columns=ALL_CODES).ffill()


def fetch_trade_context(pro: Any, as_of: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, list[pd.Timestamp]]:
    calendar = pro.trade_cal(
        exchange="SSE",
        start_date=(as_of - pd.Timedelta(days=120)).strftime("%Y%m%d"),
        end_date=(as_of + pd.Timedelta(days=150)).strftime("%Y%m%d"),
        is_open="1",
        fields="cal_date,is_open",
    )
    if calendar is None or calendar.empty:
        raise RuntimeError("trade_cal returned no open dates")
    dates = sorted(pd.to_datetime(calendar["cal_date"].astype(str)))
    eligible = [date for date in dates if date.normalize() <= as_of.normalize()]
    future = [date for date in dates if date.normalize() > as_of.normalize()]
    if not eligible or not future:
        raise RuntimeError("trade calendar has no target or next trading date")
    return eligible[-1], future[0], dates


def refresh_prices(pro: Any, target: pd.Timestamp, prices: pd.DataFrame) -> dict[str, Any]:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    last_date = prices.index.max()
    if last_date >= target:
        return {"previous_latest": last_date.date().isoformat(), "latest": last_date.date().isoformat(), "rows_added": 0}
    start = (last_date + pd.Timedelta(days=1)).strftime("%Y%m%d")
    end = target.strftime("%Y%m%d")
    additions: list[pd.DataFrame] = []
    for code in ALL_CODES:
        daily = pro.fund_daily(ts_code=code, start_date=start, end_date=end)
        adj = pro.fund_adj(ts_code=code, start_date=start, end_date=end)
        if daily is None or daily.empty:
            if code == "510300.SH":
                raise RuntimeError(f"fund_daily returned no rows for primary ETF {code}")
            continue
        if adj is None or adj.empty:
            raise RuntimeError(f"fund_adj returned no rows for {code}")
        daily = daily[["ts_code", "trade_date", "close"]].copy()
        adj = adj[["ts_code", "trade_date", "adj_factor"]].copy()
        daily["trade_date"] = pd.to_datetime(daily["trade_date"].astype(str))
        adj["trade_date"] = pd.to_datetime(adj["trade_date"].astype(str))
        frame = daily.merge(adj, on=["ts_code", "trade_date"], how="left")
        frame["adj_factor"] = pd.to_numeric(frame["adj_factor"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame["adj_close"] = frame["close"] * frame["adj_factor"]
        frame = frame.dropna(subset=["adj_close"])[["ts_code", "trade_date", "adj_close"]]
        additions.append(frame)
    if not additions:
        raise RuntimeError("no ETF price additions were returned")
    delta_path = LIVE_DIR / "etf_daily_delta.parquet"
    old = pd.read_parquet(delta_path) if delta_path.exists() else pd.DataFrame(columns=["ts_code", "trade_date", "adj_close"])
    merged = pd.concat([old, *additions], ignore_index=True).drop_duplicates(["ts_code", "trade_date"], keep="last")
    merged = merged.sort_values(["trade_date", "ts_code"])
    write_frame(delta_path, merged)
    return {
        "previous_latest": last_date.date().isoformat(),
        "latest": target.date().isoformat(),
        "rows_added": int(len(merged) - len(old.drop_duplicates(["ts_code", "trade_date"]))),
    }


def annualized_covariance(returns: pd.DataFrame) -> np.ndarray:
    cov = returns.cov().to_numpy(dtype=float) * 252.0
    cov = np.nan_to_num((cov + cov.T) / 2.0, nan=0.0, posinf=0.0, neginf=0.0)
    scale = max(float(np.nanmean(np.diag(cov))), 1e-8)
    cov += np.eye(len(cov)) * scale * 1e-6
    return cov


def normalized_risk_contribution(weights: np.ndarray, cov: np.ndarray) -> tuple[float, np.ndarray]:
    sigma = float(np.sqrt(max(weights @ cov @ weights, 1e-16)))
    contributions = weights * (cov @ weights) / sigma
    return sigma, contributions / max(float(contributions.sum()), 1e-12)


def covariance_weights(returns: pd.DataFrame, max_weight: float = 0.60) -> np.ndarray:
    cov = annualized_covariance(returns)

    def risk_contribution(w: np.ndarray) -> np.ndarray:
        sigma = float(np.sqrt(max(w @ cov @ w, 1e-16)))
        return w * (cov @ w) / sigma

    target = 1.0 / len(cov)

    def objective(w: np.ndarray) -> float:
        rc = risk_contribution(w)
        return float(np.sum((rc / max(float(rc.sum()), 1e-12) - target) ** 2))

    result = minimize(
        objective,
        x0=np.repeat(1.0 / len(cov), len(cov)),
        method="SLSQP",
        bounds=[(1e-6, max_weight)] * len(cov),
        constraints={"type": "eq", "fun": lambda w: float(w.sum() - 1.0)},
        options={"maxiter": 500, "ftol": 1e-12},
    )
    if not result.success:
        vol = returns.std(ddof=1).to_numpy(dtype=float) * np.sqrt(252.0)
        inv = 1.0 / np.maximum(vol, 1e-8)
        return inv / inv.sum()
    return result.x / result.x.sum()


def weight_diagnostics(prices: pd.DataFrame, signals: pd.DataFrame) -> dict[str, Any]:
    latest = signals.iloc[-1]
    signal_date = pd.Timestamp(latest["signal_date"])
    execution_date = pd.Timestamp(latest["execution_date"])
    history = prices.loc[:signal_date, CORE].dropna(how="any").tail(127)
    returns = history.pct_change(fill_method=None).dropna(how="any")
    cov = annualized_covariance(returns)
    weights = np.array([float(latest[f"weight_{code}"]) for code in CORE], dtype=float)
    portfolio_volatility, risk_contributions = normalized_risk_contribution(weights, cov)
    asset_volatility = np.sqrt(np.maximum(np.diag(cov), 0.0))
    assets = []
    for code, weight, volatility, contribution in zip(CORE, weights, asset_volatility, risk_contributions):
        assets.append({
            "code": code,
            **ASSET_INFO[code],
            "final_weight": float(weight),
            "annualized_volatility": float(volatility),
            "risk_contribution": float(contribution),
            "target_risk_contribution": float(1.0 / len(CORE)),
            "cap_applied": bool(abs(weight - 0.60) < 1e-6),
        })
    return {
        "signal_date": signal_date.date().isoformat(),
        "execution_date": execution_date.date().isoformat(),
        "window_start": returns.index[0].date().isoformat(),
        "window_end": returns.index[-1].date().isoformat(),
        "lookback_days": int(len(returns)),
        "portfolio_annualized_volatility": float(portfolio_volatility),
        "target_risk_contribution": float(1.0 / len(CORE)),
        "weight_sum": float(weights.sum()),
        "max_weight": 0.60,
        "assets": assets,
    }


def build_targets(prices: pd.DataFrame, target: pd.Timestamp) -> tuple[dict[pd.Timestamp, np.ndarray], pd.DataFrame]:
    calendar = prices.loc[:target].index
    targets: dict[pd.Timestamp, np.ndarray] = {}
    rows: list[dict[str, Any]] = []
    for signal_date in quarter_end_dates(calendar):
        history = prices.loc[:signal_date, CORE].dropna(how="any").tail(127)
        returns = history.pct_change(fill_method=None).dropna(how="any")
        if len(returns) < 126:
            continue
        position = calendar.get_loc(signal_date)
        if position + 1 >= len(calendar):
            continue
        weights = covariance_weights(returns)
        execution_date = calendar[position + 1]
        targets[execution_date] = weights
        rows.append({
            "signal_date": signal_date,
            "execution_date": execution_date,
            **{f"weight_{code}": float(weight) for code, weight in zip(CORE, weights)},
        })
    return targets, pd.DataFrame(rows)


def simulate(prices: pd.DataFrame, targets: dict[pd.Timestamp, np.ndarray], target: pd.Timestamp) -> pd.DataFrame:
    sample = prices.loc[:target, CORE].copy()
    returns = sample.ffill().pct_change(fill_method=None).fillna(0.0)
    current = np.zeros(len(CORE), dtype=float)
    base_nav = lev0_nav = lev3_nav = 1.0
    one_way = ONE_WAY_BPS / 10_000.0
    rows: list[dict[str, Any]] = []
    for date in sample.index:
        gross = float(current @ returns.loc[date, CORE].to_numpy(dtype=float))
        turnover = 0.0
        if date in targets:
            new = targets[date]
            turnover = float(np.abs(new - current).sum())
            current = new
        base_cost = turnover * one_way
        base_net = gross - base_cost
        lev_gross = LEVERAGE * gross
        lev_cost = LEVERAGE * base_cost
        lev0_net = lev_gross - lev_cost
        lev3_net = lev_gross - lev_cost - max(LEVERAGE - 1.0, 0.0) * FINANCING_RATES["levered_3"] / 252.0
        base_nav *= 1.0 + base_net
        lev0_nav *= 1.0 + lev0_net
        lev3_nav *= 1.0 + lev3_net
        rows.append({
            "trade_date": date,
            "base_return": base_net,
            "levered_0_return": lev0_net,
            "levered_3_return": lev3_net,
            "base_nav": base_nav,
            "levered_0_nav": lev0_nav,
            "levered_3_nav": lev3_nav,
            "turnover": turnover,
            "base_exposure": float(current.sum()),
            "levered_exposure": float(current.sum() * LEVERAGE),
            **{f"weight_{code}": float(weight) for code, weight in zip(CORE, current)},
        })
    frame = pd.DataFrame(rows)
    first = frame.loc[frame["turnover"] > 0, "trade_date"].min()
    return frame.loc[frame["trade_date"] >= first].reset_index(drop=True)


def metric(frame: pd.DataFrame, return_col: str, nav_col: str) -> dict[str, Any]:
    r = frame[return_col].astype(float)
    curve = frame[nav_col].astype(float) / float(frame[nav_col].iloc[0])
    years = max((frame["trade_date"].iloc[-1] - frame["trade_date"].iloc[0]).days / 365.25, 1 / 365.25)
    dd = curve / curve.cummax() - 1.0
    vol = float(r.std(ddof=1) * np.sqrt(252.0))
    cagr = float(curve.iloc[-1] ** (1.0 / years) - 1.0)
    return {
        "start": frame["trade_date"].iloc[0].date().isoformat(),
        "end": frame["trade_date"].iloc[-1].date().isoformat(),
        "total_return": float(curve.iloc[-1] - 1.0),
        "cagr": cagr,
        "volatility": vol,
        "max_drawdown": float(dd.min()),
        "sharpe_zero_rf": float(np.sqrt(252.0) * r.mean() / r.std(ddof=1)) if r.std(ddof=1) else None,
        "calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else None,
        "annual_turnover": float(frame["turnover"].sum() / years),
        "rebalances": int((frame["turnover"] > 0).sum()),
    }


def active_state(targets: dict[pd.Timestamp, np.ndarray], signals: pd.DataFrame, target: pd.Timestamp, calendar: list[pd.Timestamp]) -> dict[str, Any]:
    valid = signals.loc[signals["execution_date"] <= target]
    active = valid.iloc[-1] if not valid.empty else None
    all_signals = signals.sort_values("signal_date")
    latest = all_signals.loc[all_signals["signal_date"] <= target].iloc[-1]
    pending = all_signals.loc[all_signals["signal_date"] > target]
    pending_row = pending.iloc[0] if not pending.empty else None
    active_weights = [float(active[f"weight_{code}"]) for code in CORE]
    target_weights = [float(latest[f"weight_{code}"]) for code in CORE]
    pending_signal = None
    action = "持有当前组合，等待下一季度信号"
    execution_date = pd.Timestamp(latest["execution_date"])
    if execution_date > target:
        action = "下一交易日执行最新季度调仓"
        target_weights = [float(latest[f"weight_{code}"]) for code in CORE]
    if pending_row is not None:
        pending_signal = pd.Timestamp(pending_row["signal_date"])
    next_signal_candidates = [date for date in quarter_end_dates(pd.DatetimeIndex(calendar)) if date > target]
    next_signal = next_signal_candidates[0] if next_signal_candidates else None
    next_execution = None
    if next_signal is not None:
        future = [date for date in calendar if date > next_signal]
        next_execution = future[0] if future else None
    return {
        "signal_date": pd.Timestamp(latest["signal_date"]).date().isoformat(),
        "execution_date": execution_date.date().isoformat(),
        "action": action,
        "active_weights": dict(zip(CORE, active_weights)),
        "target_weights": dict(zip(CORE, target_weights)),
        "next_signal_date": None if next_signal is None else next_signal.date().isoformat(),
        "next_execution_date": None if next_execution is None else next_execution.date().isoformat(),
        "pending_signal_date": None if pending_signal is None else pending_signal.date().isoformat(),
    }


def build_payload(run_id: str, target: pd.Timestamp, next_trade_date: pd.Timestamp, prices: pd.DataFrame, daily: pd.DataFrame, signals: pd.DataFrame, state: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    specs = {
        "base": {"label": "稳健版 ERC 1.0x", "return_col": "base_return", "nav_col": "base_nav", "exposure": 1.0, "financing_rate": 0.0},
        "levered_0": {"label": "1.5x（0%融资成本）", "return_col": "levered_0_return", "nav_col": "levered_0_nav", "exposure": 1.5, "financing_rate": 0.0},
        "levered_3": {"label": "1.5x（年化3%融资）", "return_col": "levered_3_return", "nav_col": "levered_3_nav", "exposure": 1.5, "financing_rate": 0.03},
    }
    performance = {key: {**spec, "metrics": metric(daily, spec["return_col"], spec["nav_col"])} for key, spec in specs.items()}
    series = []
    for row in daily.itertuples(index=False):
        series.append({
            "date": row.trade_date.date().isoformat(),
            "base": float(row.base_nav),
            "levered_0": float(row.levered_0_nav),
            "levered_3": float(row.levered_3_nav),
            "base_dd": 0.0,
        })
    # Compute drawdowns with vectorized curves after the compact series is built.
    for key in ["base", "levered_0", "levered_3"]:
        nav = daily[key + "_nav"]
        dd = nav / nav.cummax() - 1.0
        for i, value in enumerate(dd):
            series[i][key + "_dd"] = float(value)
    latest_daily = daily.iloc[-1]
    diagnostics = weight_diagnostics(prices, signals)
    current = {code: float(state["active_weights"].get(code, 0.0)) for code in CORE}
    target_weights = {code: float(state["target_weights"].get(code, 0.0)) for code in CORE}
    holdings = []
    for code in CORE:
        holdings.append({
            "code": code,
            **ASSET_INFO[code],
            "current_weight": current[code],
            "target_weight": target_weights[code],
            "levered_target_weight": target_weights[code] * LEVERAGE,
        })
    return {
        "schema_version": "1.0",
        "strategy_id": "all_weather_risk_parity",
        "strategy_number": "03",
        "strategy_name": "多资产风险平价",
        "status": "PASS",
        "run_id": run_id,
        "generated_at": now_iso(),
        "data_as_of": target.date().isoformat(),
        "next_trade_date": next_trade_date.date().isoformat(),
        "execution": "季度末收盘形成信号，下一交易日收盘执行；执行日之后的收益开始计入",
        "source": {"primary": "Tushare Pro", "update": source},
        "trade": {
            "action": state["action"],
            "signal_date": state["signal_date"],
            "signal_execution_date": state["execution_date"],
            "next_signal_date": state["next_signal_date"],
            "next_execution_date": state["next_execution_date"],
            "current_exposure": 1.0,
            "target_exposure": 1.0,
            "levered_target_exposure": 1.5,
            "financing_rate_options": [0.0, 0.03],
        },
        "portfolio": {
            "asset_count": len(CORE),
            "assets": holdings,
            "cash_asset": CASH,
            "current_total": float(sum(current.values())),
            "target_total": float(sum(target_weights.values())),
            "levered_target_total": float(sum(target_weights.values()) * LEVERAGE),
        },
        "performance": performance,
        "weight_diagnostics": diagnostics,
        "latest": {
            "base_nav": float(latest_daily["base_nav"]),
            "levered_0_nav": float(latest_daily["levered_0_nav"]),
            "levered_3_nav": float(latest_daily["levered_3_nav"]),
            "turnover": float(latest_daily["turnover"]),
        },
        "signals": signals.to_dict(orient="records"),
        "series": series,
        "rules": {
            "universe": [{"code": code, **ASSET_INFO[code]} for code in CORE],
            "risk_method": "过去126个交易日收益率协方差矩阵的等风险贡献（ERC）",
            "rebalance": "每季度最后一个交易日盘后计算，下一交易日收盘执行",
            "weight_constraint": "不做空，单资产权重上限60%",
            "cost": "调仓按权重绝对变化计单边10bp",
            "robust_version": "1.0x，不融资",
            "levered_version": "1.5x，将四个资产权重同比放大到150%总敞口",
            "financing_options": "1.5x版本可选择0%或年化3%融资成本；3%成本按超出100%的50%融资敞口逐日计提",
            "lookahead_control": "信号只使用信号日及之前价格，执行滞后一个交易日",
        },
        "validation": {
            "status": "PASS",
            "price_date": target.date().isoformat(),
            "signal_count": int(len(signals)),
            "daily_rows": int(len(daily)),
            "no_future_price_in_signal": True,
            "cost_model": "one_way_10bp",
        },
    }


def publish_local_payload(payload: dict[str, Any], run_dir: Path) -> None:
    json_path = run_dir / "strategy.json"
    js_path = run_dir / "strategy-data.js"
    write_json(json_path, payload)
    js_path.write_text(
        "window.ALL_WEATHER_RISK_PARITY = "
        + json.dumps(json_ready(payload), ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    page_data = PAGE_DIR / "data"
    page_data.mkdir(parents=True, exist_ok=True)
    shutil.copy2(json_path, page_data / "strategy.json")
    shutil.copy2(js_path, page_data / "strategy-data.js")


def main() -> None:
    parser = argparse.ArgumentParser(description="多资产风险平价每日数据与信号更新")
    parser.add_argument("--as-of", help="按 YYYY-MM-DD 指定可用数据日")
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else pd.Timestamp.now().normalize()
    run_id = f"all_weather_rp_live_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {"run_id": run_id, "status": "RUNNING", "started_at": now_iso(), "requested_as_of": as_of.date().isoformat()}
    try:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("TUSHARE_TOKEN is required in the process environment")
        ts.set_token(token)
        pro = ts.pro_api()
        prices = load_prices()
        target, next_trade_date, open_dates = fetch_trade_context(pro, as_of)
        source = refresh_prices(pro, target, prices)
        prices = load_prices()
        if prices.index.max() < target:
            raise RuntimeError(f"price data ended at {prices.index.max().date()}, target is {target.date()}")
        targets, signals = build_targets(prices, target)
        if signals.empty:
            raise RuntimeError("no valid quarterly ERC signal was generated")
        daily = simulate(prices, targets, target)
        state = active_state(targets, signals, target, open_dates)
        payload = build_payload(run_id, target, next_trade_date, prices, daily, signals, state, source)
        write_frame(run_dir / "daily.csv.gz", daily)
        write_frame(run_dir / "signals.csv", signals, date_format="%Y-%m-%d")
        publish_local_payload(payload, run_dir)
        manifest.update({
            "status": "PASS",
            "finished_at": now_iso(),
            "target_trade_date": target.date().isoformat(),
            "next_trade_date": next_trade_date.date().isoformat(),
            "trade": payload["trade"],
            "performance": payload["performance"],
            "validation": payload["validation"],
            "data_quality": {"status": "PASS", "price_date": target.date().isoformat(), "asset_count": len(CORE)},
            "publish": {"git_status": "PENDING", "online_status": "PENDING"},
        })
        write_json(run_dir / "manifest.json", manifest)
        write_json(LOG_DIR / "latest.json", manifest)
        print(json.dumps(json_ready(manifest), ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc:
        manifest.update({"status": "FAIL", "finished_at": now_iso(), "error": f"{type(exc).__name__}: {exc}"})
        write_json(run_dir / "manifest.json", manifest)
        raise


if __name__ == "__main__":
    main()
