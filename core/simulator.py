"""
模拟盘引擎 — 每日流程编排

职责：
  1. 交易日判断
  2. 加载数据
  3. 更新持仓最高价（回落止盈用）
  4. 执行昨日待处理订单（T+1 开盘执行）
  5. 风控检查（T+1 保护）
  6. 生成明日信号
  7. 计算组合收益 + 基准对比
  8. 持久化状态
  9. 返回摘要

修复的原项目问题：
  ✅ PnL 含买入佣金
  ✅ 等额资金分配
  ✅ 回落止盈
  ✅ 基准从启动日算
  ✅ T+1 保护
"""

from datetime import date
from typing import Any, Dict, List, Optional

from config.config import (
    INITIAL_CAPITAL, MAX_POSITIONS, SLIPPAGE, COMMISSION_RATE,
    MIN_COMMISSION, TAX_RATE, STOP_LOSS_PCT, TRAILING_STOP_PCT,
    POSITION_PCT, MIN_TRADE_UNIT,
)
from core.data_loader import DataLoader
from core.broker import buy, sell, clear_today_opened_flag, update_highest_prices
from core.risk import check_stop_loss, check_trailing_stop
from core.portfolio import (
    calculate_portfolio_value, calculate_return,
    calculate_benchmark_return, build_position_details,
)
from core.log_utils import get_logger

logger = get_logger(__name__)

# 全局默认配置（策略可覆盖）
_GLOBAL_CONFIG = {
    'SLIPPAGE': SLIPPAGE,
    'COMMISSION_RATE': COMMISSION_RATE,
    'MIN_COMMISSION': MIN_COMMISSION,
    'TAX_RATE': TAX_RATE,
    'STOP_LOSS_PCT': STOP_LOSS_PCT,
    'TRAILING_STOP_PCT': TRAILING_STOP_PCT,
    'POSITION_PCT': POSITION_PCT,
    'MIN_TRADE_UNIT': MIN_TRADE_UNIT,
    'TAX_FREE': False,
}


class Simulator:
    """每日模拟盘引擎。"""

    def __init__(self):
        self.loader = DataLoader()

    def run_daily(
        self,
        strategy: Any,
        state_manager: Any,
        dry_run: bool = False,
    ) -> Optional[Dict]:
        """
        执行每日模拟盘。

        Parameters
        ----------
        strategy : BaseStrategy
            策略实例（已初始化）。
        state_manager : StateManager
            状态管理器。
        dry_run : bool
            True = 只输出不修改状态。

        Returns
        -------
        dict or None : 日报摘要
        """
        # ---- 1. 交易日检查 ----
        if not self._is_trading_day():
            logger.info(f'[{date.today()}] 非交易日，跳过')
            return None

        today = date.today()
        today_str = today.isoformat()
        logger.info(f'[{today_str}] 开始模拟盘…')

        # ---- 2. 获取策略配置 & 标的 ----
        cfg = strategy.get_config(_GLOBAL_CONFIG)
        target_symbols = strategy.get_target_symbols()

        # 提前读取持仓（无标的时也需要用于构建摘要推送）
        pf = state_manager.portfolio
        cash = pf.get('cash', INITIAL_CAPITAL)
        positions = dict(pf.get('positions', {}))
        pending_orders = dict(pf.get('pending_orders', {}))
        initial_capital = pf.get('initial_capital', INITIAL_CAPITAL)

        if not target_symbols:
            logger.warning('策略未返回交易标的')
            pv = pf.get('_last_portfolio_value') or calculate_portfolio_value(cash, positions, {})
            return {
                'date': today_str,
                'strategy': strategy.name,
                'trades_today': [],
                'positions': build_position_details(positions, {}),
                'cash': round(cash, 2),
                'portfolio_value': round(pv, 2),
                'initial_capital': initial_capital,
                'cumulative_return': round(calculate_return(pv, initial_capital), 4),
                'benchmark_return': None,
                'excess_return': None,
                'pending_orders': pending_orders,
                'signal_details': {},
                'dry_run': dry_run,
                'no_targets': True,
            }

        logger.info(f'  策略: {strategy.name}')
        logger.info(f'  标的: {len(target_symbols)} 只')

        # ---- 3. 加载数据 ----
        stock_data = self._load_data(target_symbols, cfg)
        if not stock_data:
            logger.warning('无法加载数据')
            return None

        prices = {s: d['latest']['close'] for s, d in stock_data.items()}

        # ---- 4. 获取持仓 & 资金 ----
        pf = state_manager.portfolio
        cash = pf.get('cash', INITIAL_CAPITAL)
        positions = dict(pf.get('positions', {}))  # 深拷贝
        pending_orders = dict(pf.get('pending_orders', {}))
        initial_capital = pf.get('initial_capital', INITIAL_CAPITAL)

        # ---- 5. 清空 T+1 标记 & 更新最高价 ----
        clear_today_opened_flag(positions)
        update_highest_prices(positions, prices)

        # ---- 6. 执行昨日待处理订单 ----
        trades_today = []
        if pending_orders:
            for sym, action in list(pending_orders.items()):
                if sym not in stock_data:
                    continue
                row = stock_data[sym]['latest']

                if action == 'buy' and cash > 0:
                    # 等额资金分配
                    remaining_slots = max(1, MAX_POSITIONS - len(positions))
                    budget = cash / remaining_slots
                    trade = buy(sym, row['open'], cash, positions, budget, cfg)
                    if trade:
                        cash = trade['cash_after']
                        trades_today.append(trade)

                elif action == 'sell' and sym in positions:
                    trade = sell(sym, row['open'], positions, cfg, 'signal_sell')
                    if trade:
                        cash += trade['net_revenue']
                        trades_today.append(trade)

            pending_orders = {}

        # ---- 7. 风控检查（T+1 保护：今日新开仓跳过）----
        for sym, pos in list(positions.items()):
            if sym not in stock_data:
                continue
            row = stock_data[sym]['latest']
            current_price = row.get('open', 0) or row.get('close', 0)

            if check_stop_loss(pos, current_price, cfg):
                trade = sell(sym, row['open'], positions, cfg, 'risk_stop_loss')
                if trade:
                    cash += trade['net_revenue']
                    trades_today.append(trade)
                continue

            if check_trailing_stop(pos, current_price, cfg):
                trade = sell(sym, row['open'], positions, cfg, 'risk_trailing_stop')
                if trade:
                    cash += trade['net_revenue']
                    trades_today.append(trade)

        # ---- 8. 生成明日信号 ----
        new_pending = {}
        signal_details = {}
        for sym in target_symbols:
            if sym not in stock_data:
                continue
            sig = strategy.generate(sym, stock_data[sym]['df'])

            # 有效信号：空仓时卖出信号视为持有（无股可卖）
            if sig == -1 and sym not in positions:
                effective_sig = 0
            else:
                effective_sig = sig

            signal_details[sym] = effective_sig

            if effective_sig == 1 and sym not in positions:
                new_pending[sym] = 'buy'
            elif effective_sig == -1 and sym in positions:
                new_pending[sym] = 'sell'
            else:
                new_pending[sym] = 'hold'

        # ---- 9. 计算组合市值 ----
        portfolio_value = calculate_portfolio_value(cash, positions, prices)
        cumulative_return = calculate_return(portfolio_value, initial_capital)

        # ---- 10. 基准对比 ----
        benchmark_return = self._calc_benchmark(state_manager, stock_data)
        excess_return = cumulative_return - benchmark_return \
            if benchmark_return is not None else None

        # ---- 11. 构建摘要 ----
        position_details = build_position_details(positions, prices)
        summary = {
            'date': today_str,
            'strategy': strategy.name,
            'trades_today': trades_today,
            'positions': position_details,
            'cash': round(cash, 2),
            'portfolio_value': round(portfolio_value, 2),
            'initial_capital': initial_capital,
            'cumulative_return': round(cumulative_return, 4),
            'benchmark_return': round(benchmark_return, 4)
            if benchmark_return is not None else None,
            'excess_return': round(excess_return, 4)
            if excess_return is not None else None,
            'pending_orders': new_pending,
            'signal_details': signal_details,
            'dry_run': dry_run,
        }

        # ---- 12. 更新状态 ----
        if not dry_run:
            # 清理不再持有的标的（重新选股后旧持仓已卖完）
            state_manager.update_portfolio(
                cash, positions, new_pending, portfolio_value, strategy.name,
            )
            # 基准起始价已由 _calc_benchmark 在首次运行时设置
            for trade in trades_today:
                state_manager.add_trade(trade)
            state_manager.save()

        self._print_summary(summary)
        return summary

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_data(self, symbols: List[str],
                   config: dict) -> Dict[str, Dict]:
        """批量加载数据。"""
        result = {}
        for sym in symbols:
            try:
                # 判断是否 ETF（纯数字6位，上海5开头或深圳1开头）
                is_etf = sym.isdigit() and (
                    sym.startswith(('5', '1', '9'))
                )
                if is_etf:
                    df = self.loader.load_etf_data(sym)
                else:
                    df = self.loader.load_stock_data(sym)

                if df is not None and len(df) > 30:
                    result[sym] = {'df': df, 'latest': df.iloc[-1]}
                    logger.info(f'  {sym}: {len(df)} 行')
                else:
                    logger.warning(f'{sym}: 数据不足')
            except Exception as e:
                logger.warning(f'{sym}: 加载失败: {e}')
        return result

    # 基准指数：沪深300指数（sh.000300），所有策略统一使用
    _BENCHMARK_INDEX = 'sh.000300'

    def _calc_benchmark(self, state_manager: Any,
                        stock_data: Dict) -> Optional[float]:
        """计算沪深300指数（sh.000300）基准收益。

        基准从策略首次执行交易的日期开始，以当日**开盘价**为起始价，
        与策略以开盘价买入/卖出的时间点一致。
        后续每日取最新收盘价计算累计收益率：(今日收盘 - 首日开盘) / 首日开盘。
        """
        start_price = state_manager.get_benchmark_start_price()
        start_date = state_manager.data.get('benchmark_start_date', '')

        # 加载沪深300指数日线
        try:
            df = self.loader.load_benchmark_data(
                self._BENCHMARK_INDEX,
                start_date=start_date,
            )
            if df is None or len(df) < 1:
                return None
            df = df.sort_values('date')
        except Exception as e:
            logger.debug(f"_calc_benchmark: 加载基准指数失败: {e}")
            return None

        if start_price <= 0:
            # 首次运行：以当日开盘价作为基准起点（与策略开盘执行一致）
            today_str = date.today().isoformat()
            today_data = df[df['date'].dt.strftime('%Y-%m-%d') == today_str]
            if today_data.empty:
                start_price = float(df['close'].iloc[-1])
            else:
                start_price = float(today_data['open'].iloc[0])  # 用开盘价
            state_manager.set_benchmark_start_price(start_price)
            state_manager.data['benchmark_start_date'] = today_str
            state_manager.save()

        current = float(df['close'].iloc[-1])
        return calculate_benchmark_return(current, start_price)

    @staticmethod
    def _is_trading_day() -> bool:
        """判断今天是否为交易日。"""
        import baostock as bs
        today_str = date.today().strftime('%Y-%m-%d')
        try:
            lg = bs.login()
            if lg.error_code != '0':
                return date.today().weekday() < 5
            rs = bs.query_trade_dates(start_date=today_str, end_date=today_str)
            is_trade = False
            if rs.error_code == '0':
                while rs.next():
                    row = rs.get_row_data()
                    if len(row) >= 2 and row[0] == today_str and row[1] == '1':
                        is_trade = True
            bs.logout()
            return is_trade
        except Exception:
            return date.today().weekday() < 5

    @staticmethod
    def _print_summary(summary: Dict):
        """控制台输出。"""
        print(f'\n{"=" * 55}')
        print(f'  📊 统一模拟盘日报 — {summary["date"]}')
        print(f'  策略: {summary.get("strategy", "N/A")}')
        if summary.get('dry_run'):
            print(f'  ⚠ DRY RUN 模式')
        print(f'{"=" * 55}')

        if summary['trades_today']:
            print(f'\n  当日操作:')
            for t in summary['trades_today']:
                action = '🟢 买入' if t['action'] == 'buy' else '🔴 卖出'
                reason = t.get('reason', '')
                r = f' ({reason})' if reason and reason != 'signal_buy' and reason != 'signal_sell' else ''
                print(f'    {action} {t["symbol"]}: {t["shares"]}份 @ {t["price"]:.4f}  '
                      f'金额={t.get("cost", 0):.2f}  '
                      f'盈亏={t.get("pnl", 0):+.2f}{r}')
        else:
            print(f'\n  当日无操作')

        if summary['positions']:
            print(f'\n  持仓摘要:')
            for p in summary['positions']:
                sign = '+' if p['pnl_pct'] >= 0 else ''
                print(f'    {p["symbol"]}: {p["shares"]}份  '
                      f'成本={p["avg_cost"]:.4f}  '
                      f'现价={p["last_close"]:.4f}  '
                      f'({sign}{p["pnl_pct"]:.2%})')
        else:
            print(f'\n  空仓')

        print(f'\n  账户摘要:')
        print(f'    总资产:   {summary["portfolio_value"]:,.2f}')
        print(f'    现金:     {summary["cash"]:,.2f}')
        print(f'    策略收益: {summary["cumulative_return"]:+.2%}')
        if summary.get('benchmark_return') is not None:
            print(f'    基准收益: {summary["benchmark_return"]:+.2%}')
        if summary.get('excess_return') is not None:
            print(f'    超额收益: {summary["excess_return"]:+.2%}')

        if summary.get('signal_details'):
            held_symbols = {p['symbol'] for p in summary.get('positions', [])}
            print(f'\n  信号状态:')
            for sym, sig in summary['signal_details'].items():
                if sig == 1:
                    label = '🟢 买入' if sym not in held_symbols else '🟢 加仓'
                elif sig == -1:
                    label = '🔴 卖出'  # 仅持仓股会出现卖出信号
                else:
                    label = '⚪ 持有'
                print(f'    {label} {sym} (sig={sig})')

        if summary.get('pending_orders'):
            active = {s: a for s, a in summary['pending_orders'].items()
                      if a != 'hold'}
            if active:
                print(f'\n  明日信号:')
                for sym, action in active.items():
                    emoji = '🟢' if action == 'buy' else '🔴'
                    print(f'    {emoji} {sym}: {action}')

        print(f'{"=" * 55}')
