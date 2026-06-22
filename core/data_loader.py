"""
数据加载 — 统一从 004_sequoia-x 数据库获取数据

数据源优先级：
  1. Sequoia-X 数据库（db_adapter）
  2. baostock 兜底（短区间，避免卡死）

用法:
  loader = DataLoader()
  df = loader.load_stock_data('000001')
  df = loader.load_etf_data('510300')
"""

import sys
from datetime import date, timedelta
from typing import Optional

import pandas as pd

_QUANT_DIR = '/public/home/hpc/zhulei/superman/quant'
if _QUANT_DIR not in sys.path:
    sys.path.insert(0, _QUANT_DIR)

from data.db_adapter import get_stock_data as _db_get_stock, get_etf_data as _db_get_etf


class DataLoader:
    """统一数据加载器。"""

    @staticmethod
    def load_stock_data(
        stock_code: str,
        start_date: str = '',
        end_date: str = '',
        min_days: int = 60,
    ) -> Optional[pd.DataFrame]:
        """
        加载个股日线数据。数据库优先，baostock 兜底。

        Returns
        -------
        DataFrame 包含: date, open, high, low, close, volume, amount
        """
        today = date.today()
        end = end_date or today.isoformat()
        start = start_date or (today.replace(year=today.year - 2)).isoformat()

        # 数据库优先
        df = _db_get_stock(stock_code, start, end, min_days)
        if df is not None and len(df) >= min_days:
            return df

        # baostock 兜底（短区间）
        fallback_start = (today - timedelta(days=400)).isoformat()
        df = _fetch_from_baostock(stock_code, fallback_start, end, min_days)
        if df is not None and len(df) >= min_days:
            return df

        return None

    @staticmethod
    def load_etf_data(
        etf_code: str,
        start_date: str = '',
        end_date: str = '',
        min_days: int = 50,
    ) -> Optional[pd.DataFrame]:
        """
        加载 ETF 日线数据。数据库优先，baostock 兜底。
        """
        today = date.today()
        end = end_date or today.isoformat()
        start = start_date or (today.replace(year=today.year - 2)).isoformat()

        # 数据库优先（ETF 存于 stock_daily 表）
        df = _db_get_etf(etf_code, start, end, min_days)
        if df is not None and len(df) >= min_days:
            return df

        # baostock 兜底
        fallback_start = (today - timedelta(days=400)).isoformat()
        df = _fetch_from_baostock(etf_code, fallback_start, end, min_days)
        if df is not None and len(df) >= min_days:
            return df

        return None

    @staticmethod
    def load_benchmark_data(
        index_code: str = 'sh.000300',
        start_date: str = '',
        end_date: str = '',
    ) -> Optional[pd.DataFrame]:
        """
        加载基准指数日线数据（数据库优先）。
        """
        from data.db_adapter import get_index_data
        return get_index_data(index_code, start_date, end_date)

    @staticmethod
    def get_today_status(symbol: str) -> Optional[pd.Series]:
        """
        获取某只股票/ETF 最新一日的行情（用于模拟盘）。
        """
        df = DataLoader.load_stock_data(symbol, min_days=20)
        if df is None:
            df = DataLoader.load_etf_data(symbol, min_days=20)
        if df is not None and len(df) > 0:
            return df.iloc[-1]
        return None


def _fetch_from_baostock(
    code: str, start_date: str, end_date: str, min_days: int = 50,
) -> Optional[pd.DataFrame]:
    """
    从 baostock 获取日线数据（短区间，带超时保护）。
    """
    import baostock as bs
    import signal

    # 交易所前缀
    if code.startswith(('6', '9', '5')):
        bs_code = f'sh.{code}'
    else:
        bs_code = f'sz.{code}'

    class _Timeout(Exception):
        pass

    def _alarm_handler(signum, frame):
        raise _Timeout('baostock 超时')

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(30)

    try:
        lg = bs.login()
        if lg.error_code != '0':
            return None

        fields = 'date,open,high,low,close,volume,amount'
        rs = bs.query_history_k_data_plus(
            bs_code, fields,
            start_date=start_date, end_date=end_date,
            frequency='d', adjustflag='2',
        )
        if rs.error_code != '0':
            bs.logout()
            return None

        data = []
        while rs.next():
            data.append(rs.get_row_data())
        bs.logout()

        if not data:
            return None

        df = pd.DataFrame(data, columns=rs.fields)
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date', 'open', 'close'])

        if len(df) < min_days:
            return None

        return df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']] \
            .reset_index(drop=True)

    except _Timeout:
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
