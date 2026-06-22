"""
动态指标策略 — 继承 015_indicator_scanner 的指标动态选优体系。

从 97 个技术指标中动态选出最佳指标，用于每日信号生成。

依赖：015_indicator_scanner 项目（signals/ 目录）
"""

import sys
import os
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

from strategies.base import BaseStrategy

# 依赖 015 项目的信号代码（追加到末尾，018 自身 core/ 优先）
_015_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        '..', '015_indicator_scanner')
_015_DIR = os.path.abspath(_015_DIR)
if _015_DIR not in sys.path:
    sys.path.append(_015_DIR)

from signals.gf import GFSignal
from core.signal_engine import SignalEngine


class DynamicIndicatorStrategy(BaseStrategy):
    """
    动态指标策略。

    每次 on_rescan() 触发时，扫描全部 97 个指标，
    选出综合评分最高的指标用于后续交易。

    config_overrides:
      - RESCAN_DAYS: 重新扫描间隔（默认 90 天）
      - SCAN_YEARS: 回测年数（默认 2）
      - TOP_N: 选股数量（默认 10）
    """

    config_overrides = {
        'RESCAN_DAYS': 90,
        'SCAN_YEARS': 2,
        'TOP_N': 10,
    }

    def __init__(self):
        self._indicator = ''
        self._last_scan_date: Optional[date] = None
        self.target_symbols = []
        self._state_manager = None  # 稍后由 run_daily 注入

    @property
    def name(self) -> str:
        return f'DynamicIndicator({self._indicator})' if self._indicator else 'DynamicIndicator'

    def attach_state(self, state_manager) -> None:
        """注入状态管理器（用于读取/写入扫描时间）。"""
        self._state_manager = state_manager

    def generate(self, symbol: str, df: pd.DataFrame) -> int:
        """用当前选定的最佳指标生成信号。"""
        if not self._indicator:
            return 0

        signal = GFSignal(indicator=self._indicator)
        engine = SignalEngine()
        engine.register(signal)
        result = engine.generate(df.copy())

        sig_col = 'GF_signal'
        if sig_col not in result.columns:
            return 0
        return int(result[sig_col].iloc[-1])

    def on_rescan(self) -> bool:
        """
        重新扫描选指标 + 选股。

        执行 015 的 Phase 1 → 2 → 3 流程。
        成功后更新 self._indicator 和 self.target_symbols。
        """
        return self._run_scan_pipeline()

    @staticmethod
    def _fetch_constituents() -> List[str]:
        """从 baostock 获取沪深300成分股。"""
        import baostock as bs
        lg = bs.login()
        if lg.error_code != '0':
            return []
        try:
            rs = bs.query_hs300_stocks()
            if rs.error_code != '0':
                return []
            codes = []
            while rs.next():
                row = rs.get_row_data()
                # row = [日期, sh.600000, 名称]
                code = row[1].split('.')[1] if '.' in row[1] else row[1]
                codes.append(code)
            return codes
        except Exception:
            return []
        finally:
            bs.logout()

    def _run_scan_pipeline(self) -> bool:
        """简易版扫描流水线（Phase 1 → 2 → 3）。"""
        print(f'\n{"=" * 50}')
        print(f'  🔍 动态指标策略 — 开始全量扫描')
        print(f'{"=" * 50}')

        # 获取沪深300成分股（自带缓存，7天有效）
        stock_codes = self._fetch_constituents()
        if not stock_codes:
            print('  ✗ 无法获取成分股')
            return False
        print(f'  成分股: {len(stock_codes)} 只')

        # ── Phase 1: 全指标扫描 ──
        indicators = list(GFSignal.INDICATORS)
        print(f'  指标数: {len(indicators)}')

        from core.data_loader import DataLoader
        loader = DataLoader()
        today = date.today()
        start_date = today.replace(year=today.year - 2).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')

        # 预检查
        valid_codes = []
        for code in stock_codes:
            try:
                df = loader.load_stock_data(code, start_date, end_date, 120)
                if df is not None and len(df) >= 60:
                    valid_codes.append(code)
            except Exception:
                pass
        print(f'  有效股票: {len(valid_codes)}/{len(stock_codes)}')

        if len(valid_codes) < 50:
            print('  ⚠ 有效股票过少，扫描可能不可靠')

        # 逐个指标扫描
        import numpy as np
        indicator_results = {}
        for i, ind in enumerate(indicators):
            try:
                excess_list = []
                for code in valid_codes[:50]:  # 取前50只加速
                    df = loader.load_stock_data(code, start_date, end_date, 120)
                    if df is None:
                        continue
                    signal = GFSignal(indicator=ind)
                    engine = SignalEngine()
                    engine.register(signal)
                    result = engine.generate(df.copy())
                    sig_col = 'GF_signal'
                    if sig_col not in result.columns:
                        continue
                    # 简单策略：买入持有 vs 基准持有
                    sigs = result[sig_col].values
                    if len(sigs) < 10:
                        continue
                    ret_strategy = 0
                    ret_benchmark = 0
                    buy_price = None
                    for t in range(len(sigs)):
                        px = df['close'].iloc[t]
                        if sigs[t] == 1 and buy_price is None:
                            buy_price = px
                            ret_strategy = (df['close'].iloc[-1] - buy_price) / buy_price
                        if buy_price is not None and sigs[t] == -1:
                            ret_strategy = (px - buy_price) / buy_price
                            buy_price = None
                    if buy_price is not None:
                        ret_strategy = (df['close'].iloc[-1] - buy_price) / buy_price
                    if ret_strategy != 0:
                        ret_benchmark = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]
                        excess = ret_strategy - ret_benchmark
                        excess_list.append(excess)

                if len(excess_list) >= 10:
                    mean_ex = float(np.mean(excess_list))
                    win_rate = float(np.mean(np.array(excess_list) > 0))
                    indicator_results[ind] = {
                        'score': mean_ex * win_rate,
                        'mean_excess': mean_ex,
                        'win_rate': win_rate,
                    }
            except Exception:
                continue

            if (i + 1) % 20 == 0:
                print(f'    扫描进度: {i + 1}/{len(indicators)}')

        if not indicator_results:
            print('  ✗ 无有效指标')
            return False

        # 排序选最佳
        sorted_inds = sorted(indicator_results.items(),
                             key=lambda x: x[1]['score'], reverse=True)
        self._indicator = sorted_inds[0][0]
        print(f'\n  🏆 最佳指标: {self._indicator} '
              f'(score={sorted_inds[0][1]["score"]:.4f}, '
              f'win={sorted_inds[0][1]["win_rate"]:.1%})')

        # ── Phase 2: 选股 ──
        top_stocks = self._select_top_stocks(valid_codes, self._indicator, loader,
                                             start_date, end_date)
        self.target_symbols = top_stocks
        print(f'  📋 选股结果: {top_stocks}')

        # 更新扫描时间
        self._last_scan_date = today
        if self._state_manager:
            self._state_manager.set_model_trained(f'scan_{today.isoformat()}')

        print(f'  ✅ 扫描完成')
        return True

    def _select_top_stocks(self, stock_codes: List[str], indicator: str,
                           loader, start_date: str, end_date: str) -> List[str]:
        """用最佳指标选出超额收益最高的 TOP_N 只股票。"""
        import numpy as np
        results = []
        for code in stock_codes:
            try:
                df = loader.load_stock_data(code, start_date, end_date, 120)
                if df is None:
                    continue
                signal = GFSignal(indicator=indicator)
                engine = SignalEngine()
                engine.register(signal)
                result = engine.generate(df.copy())
                sig_col = 'GF_signal'
                if sig_col not in result.columns:
                    continue
                sigs = result[sig_col].values
                if len(sigs) < 10:
                    continue
                buy_price = None
                ret_strategy = 0
                for t in range(len(sigs)):
                    px = df['close'].iloc[t]
                    if sigs[t] == 1 and buy_price is None:
                        buy_price = px
                    if buy_price is not None and sigs[t] == -1:
                        ret_strategy = (px - buy_price) / buy_price
                        buy_price = None
                if buy_price is not None:
                    ret_strategy = (df['close'].iloc[-1] - buy_price) / buy_price
                ret_benchmark = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]
                excess = ret_strategy - ret_benchmark
                results.append((code, excess))
            except Exception:
                continue

        results.sort(key=lambda x: x[1], reverse=True)
        top_n = self.config_overrides.get('TOP_N', 10)
        return [r[0] for r in results[:top_n]]
