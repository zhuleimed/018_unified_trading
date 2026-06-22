"""
策略基类 — 所有策略的抽象接口。

只需子类实现 generate() 方法，其余继承。
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import pandas as pd


class BaseStrategy(ABC):
    """策略基类。"""

    # 策略覆盖的配置项（优先级高于全局 config）
    config_overrides: dict = {}

    # 策略交易的标的列表
    target_symbols: List[str] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称。"""
        ...

    @abstractmethod
    def generate(self, symbol: str, df: pd.DataFrame) -> int:
        """
        对单只标的生成次日交易信号。

        Parameters
        ----------
        symbol : str
            股票/ETF 代码。
        df : pd.DataFrame
            日线数据（含 date, open, high, low, close, volume, amount）。

        Returns
        -------
        int : 1=买入, -1=卖出, 0=持有
        """
        ...

    def get_target_symbols(self) -> List[str]:
        """返回该策略当前关注的标的列表。"""
        return self.target_symbols

    def get_config(self, global_config: dict) -> dict:
        """合并全局配置与策略特有配置（策略覆盖优先）。"""
        return {**global_config, **self.config_overrides}

    def train(self, data_dict: Optional[Dict[str, pd.DataFrame]] = None) -> bool:
        """可选：训练模型（需要预训练的策略实现此方法）。"""
        return True

    def on_rescan(self) -> bool:
        """可选：重新扫描/选股（动态指标策略实现此方法）。"""
        return True
