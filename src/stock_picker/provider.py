from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import time

import pandas as pd


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


@dataclass
class AkshareProvider:
    retries: int = 3
    last_source: str = ""

    def _call(self, func, **kwargs):
        last_error = None
        for attempt in range(self.retries):
            try:
                return func(**kwargs)
            except Exception as error:  # provider/network exceptions vary
                last_error = error
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"数据源连续失败 {self.retries} 次: {last_error}") from last_error

    def spot(self) -> pd.DataFrame:
        import akshare as ak

        try:
            raw = self._call(ak.stock_zh_a_spot_em)
            self.last_source = "eastmoney"
        except RuntimeError:
            return self._spot_tencent(ak)
        required = ["代码", "名称", "成交额", "总市值", "市盈率-动态", "市净率", "涨跌幅"]
        missing = set(required) - set(raw.columns)
        if missing:
            raise RuntimeError(f"行情字段变化，缺少: {sorted(missing)}")
        result = pd.DataFrame({
            "code": raw["代码"].astype(str).str.zfill(6),
            "name": raw["名称"].astype(str),
            "last_price": _number(raw["最新价"]),
            "amount": _number(raw["成交额"]),
            "market_cap": _number(raw["总市值"]),
            "pe": _number(raw["市盈率-动态"]),
            "pb": _number(raw["市净率"]),
            "pct_change": _number(raw["涨跌幅"]),
        })
        return result

    def _spot_tencent(self, ak) -> pd.DataFrame:
        """Tencent fallback. It has no PB field; valuation scoring tolerates that."""
        raw = self._call(ak.stock_zh_a_spot_tx)
        self.last_source = "tencent"
        required = ["code", "name", "turnover", "zsz", "pe_ttm", "zdf"]
        missing = set(required) - set(raw.columns)
        if missing:
            raise RuntimeError(f"腾讯行情字段变化，缺少: {sorted(missing)}")
        codes = raw["code"].astype(str)
        return pd.DataFrame({
            "code": codes.str[-6:],
            "name": raw["name"].astype(str),
            "last_price": _number(raw["zxj"]) if "zxj" in raw.columns else (
                _number(raw["price"]) if "price" in raw.columns else float("nan")
            ),
            # Tencent expresses turnover in 10k CNY and market cap in 100m CNY.
            "amount": _number(raw["turnover"]) * 10_000,
            "market_cap": _number(raw["zsz"]) * 100_000_000,
            "pe": _number(raw["pe_ttm"]),
            "pb": float("nan"),
            "pct_change": _number(raw["zdf"]),
        })

    def history(self, code: str, start: date, end: date, adjust: str) -> pd.DataFrame:
        import akshare as ak

        try:
            raw = self._call(
                ak.stock_zh_a_hist,
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust=adjust,
            )
            self.last_source = "eastmoney"
            columns = {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量", "amount": "成交额"}
        except RuntimeError:
            prefix = "sh" if code.startswith(("60", "68")) else "sz"
            raw = self._call(
                ak.stock_zh_a_hist_tx,
                symbol=prefix + code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust=adjust,
            )
            self.last_source = "tencent"
            columns = {key: key for key in ("date", "open", "high", "low", "close", "volume", "amount")}
        if raw.empty:
            return pd.DataFrame()
        result = pd.DataFrame({
            "code": code,
            "trade_date": pd.to_datetime(raw[columns["date"]]).dt.strftime("%Y-%m-%d"),
            "open": _number(raw[columns["open"]]),
            "high": _number(raw[columns["high"]]),
            "low": _number(raw[columns["low"]]),
            "close": _number(raw[columns["close"]]),
            "volume": _number(raw[columns["volume"]]),
            "amount": _number(raw[columns["amount"]]),
        })
        return result.dropna(subset=["trade_date", "close"])
