"""
组合管理 — 市值、收益、基准对比

与原 015/016 的区别：
  ✅ 基准从模拟启动日算起（原项目全量数据首末收益）
  ✅ 等额资金分配（每只标的独立预算）
"""

from typing import Dict, List


def calculate_portfolio_value(cash: float, positions: Dict,
                              prices: Dict[str, float]) -> float:
    """计算组合总市值。"""
    value = cash
    for sym, pos in positions.items():
        price = prices.get(sym)
        if price and pos['shares'] > 0:
            value += pos['shares'] * price
    return value


def calculate_return(portfolio_value: float, initial_capital: float) -> float:
    """计算累计收益率。"""
    if initial_capital <= 0:
        return 0.0
    return (portfolio_value - initial_capital) / initial_capital


def calculate_benchmark_return(current_price: float,
                               start_price: float) -> float:
    """计算基准收益率（从模拟启动日算起）。"""
    if start_price <= 0:
        return 0.0
    return (current_price - start_price) / start_price


def build_position_details(positions: Dict,
                           prices: Dict[str, float]) -> List[Dict]:
    """构建持仓详情列表（用于展示）。"""
    details = []
    for sym, pos in positions.items():
        price = prices.get(sym)
        if price and pos['shares'] > 0:
            market_value = pos['shares'] * price
            pnl_pct = (price - pos['avg_cost']) / pos['avg_cost'] \
                if pos['avg_cost'] > 0 else 0
            details.append({
                'symbol': sym,
                'shares': pos['shares'],
                'avg_cost': round(pos['avg_cost'], 4),
                'last_close': round(price, 4),
                'market_value': round(market_value, 2),
                'pnl_pct': round(pnl_pct, 4),
            })
    return details


def calc_position_budgets(initial_capital: float,
                          max_positions: int) -> Dict[str, float]:
    """
    计算等额资金分配表。

    返回 {index: budget}，每只标的预算 = INITIAL_CAPITAL / MAX_POSITIONS
    """
    if max_positions <= 0:
        return {}
    per_position = initial_capital / max_positions
    return {str(i): per_position for i in range(max_positions)}
