"""
风控模块 — 止损 + 回落止盈

与原 015/016 的区别：
  ✅ 新增回落止盈（原项目定义了 STOP_PROFIT_PCT 但未使用）
  ✅ T+1 保护（当日新开仓跳过风控）
"""

from typing import Dict


def check_stop_loss(position: Dict, current_price: float, config: dict) -> bool:
    """
    固定止损检查。

    条件：当前价 < 买入均价 × (1 - STOP_LOSS_PCT)
    """
    if position.get('today_opened'):
        return False  # T+1 保护

    STOP_LOSS_PCT = config.get('STOP_LOSS_PCT', 0.05)
    avg_cost = position.get('avg_cost', 0)
    if avg_cost <= 0:
        return False

    return current_price < avg_cost * (1 - STOP_LOSS_PCT)


def check_trailing_stop(position: Dict, current_price: float, config: dict) -> bool:
    """
    回落止盈检查。

    条件：当前价 < 持仓期间最高价 × (1 - TRAILING_STOP_PCT)
    """
    if position.get('today_opened'):
        return False  # T+1 保护

    TRAILING_STOP_PCT = config.get('TRAILING_STOP_PCT', 0.03)
    highest = position.get('highest_price', 0)
    if highest <= 0:
        return False

    return current_price < highest * (1 - TRAILING_STOP_PCT)
