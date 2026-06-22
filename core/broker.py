"""
交易执行 — 买入/卖出

职责：
  - 买入：等额资金分配，含佣金计入成本
  - 卖出：全额清仓，含印花税
  - T+1 标记：当日新开仓跳过风控

与原 015/016 的区别：
  ✅ 买入佣金计入 total_cost（PnL 不再被高估）
  ✅ 等额资金分配（不再第一笔吃 95%）
  ✅ T+1 保护（新开仓当天不触发风控卖出）
"""

from datetime import date
from typing import Dict, Optional


def buy(
    symbol: str,
    open_price: float,
    cash: float,
    positions: Dict,
    available_budget: float,
    config: dict,
) -> Optional[Dict]:
    """
    执行买入。

    Parameters
    ----------
    available_budget : float
        此标的可用资金上限（等额分配后的额度）。

    Returns
    -------
    dict or None : 交易记录
    """
    MIN_TRADE_UNIT = config.get('MIN_TRADE_UNIT', 100)
    SLIPPAGE = config.get('SLIPPAGE', 0.003)
    COMMISSION_RATE = config.get('COMMISSION_RATE', 0.0005)
    MIN_COMMISSION = config.get('MIN_COMMISSION', 5.0)
    POSITION_PCT = config.get('POSITION_PCT', 0.95)

    # 实际可用 = min(剩余现金, 此标的预算) × 仓位比例
    available = min(cash, available_budget) * POSITION_PCT
    if available < open_price * MIN_TRADE_UNIT:
        return None  # 连一手都买不起

    exec_price = open_price * (1 + SLIPPAGE)
    raw_shares = int(available / exec_price)
    shares = (raw_shares // MIN_TRADE_UNIT) * MIN_TRADE_UNIT
    if shares == 0:
        return None

    gross_cost = shares * exec_price
    commission = max(gross_cost * COMMISSION_RATE, MIN_COMMISSION)
    total_cost = gross_cost + commission  # 含买入佣金

    if total_cost > cash:
        return None

    # 更新持仓（含买入佣金 + 最高价追踪 + T+1标记）
    if symbol in positions:
        old = positions[symbol]
        new_shares = old['shares'] + shares
        new_total = old['total_cost'] + total_cost
        positions[symbol] = {
            'shares': new_shares,
            'avg_cost': round(new_total / new_shares, 4),
            'total_cost': round(new_total, 2),
            'highest_price': max(old.get('highest_price', 0), exec_price),
            'today_opened': True,  # T+1 保护
        }
    else:
        positions[symbol] = {
            'shares': shares,
            'avg_cost': round(exec_price, 4),
            'total_cost': round(total_cost, 2),
            'highest_price': exec_price,
            'today_opened': True,  # T+1 保护
        }

    return {
        'date': date.today().isoformat(),
        'symbol': symbol,
        'action': 'buy',
        'price': round(exec_price, 4),
        'shares': shares,
        'cost': round(total_cost, 2),
        'commission': round(commission, 2),
        'cash_after': round(cash - total_cost, 2),
        'reason': 'signal_buy',
    }


def sell(
    symbol: str,
    open_price: float,
    positions: Dict,
    config: dict,
    reason: str = 'signal_sell',
) -> Optional[Dict]:
    """
    执行卖出（全额清仓）。

    Parameters
    ----------
    reason : str
        卖出原因：signal_sell / risk_stop_loss / risk_trailing_stop
    """
    if symbol not in positions:
        return None

    pos = positions[symbol]
    SLIPPAGE = config.get('SLIPPAGE', 0.003)
    COMMISSION_RATE = config.get('COMMISSION_RATE', 0.0005)
    MIN_COMMISSION = config.get('MIN_COMMISSION', 5.0)
    TAX_RATE = config.get('TAX_RATE', 0.001)
    TAX_FREE = config.get('TAX_FREE', False)

    exec_price = open_price * (1 - SLIPPAGE)
    gross_revenue = pos['shares'] * exec_price
    commission = max(gross_revenue * COMMISSION_RATE, MIN_COMMISSION)
    tax = 0 if TAX_FREE else gross_revenue * TAX_RATE
    net_revenue = gross_revenue - commission - tax

    # 盈亏 = 净收入 - 持仓总成本（含买入佣金）
    pnl = round(net_revenue - pos['total_cost'], 2)

    del positions[symbol]

    return {
        'date': date.today().isoformat(),
        'symbol': symbol,
        'action': 'sell',
        'price': round(exec_price, 4),
        'shares': pos['shares'],
        'net_revenue': round(net_revenue, 2),
        'commission': round(commission, 2),
        'tax': round(tax, 2),
        'pnl': pnl,
        'reason': reason,
    }


def clear_today_opened_flag(positions: Dict):
    """每天开始时清空 T+1 标记。"""
    for pos in positions.values():
        pos['today_opened'] = False


def update_highest_prices(positions: Dict, current_prices: Dict[str, float]):
    """更新各持仓的最高价（用于回落止盈计算）。"""
    for sym, pos in positions.items():
        price = current_prices.get(sym)
        if price and price > pos.get('highest_price', 0):
            pos['highest_price'] = price
