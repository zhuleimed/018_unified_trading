"""
状态管理 — JSON 原子写入持久化

职责：持仓、资金、待处理订单、策略元信息的存取。
"""

import json
import os
import tempfile
from datetime import date
from typing import Any, Dict


class StateManager:
    def __init__(self, state_file_path: str):
        self._path = state_file_path
        self._data: Dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
                default = self._default_state()
                for key, val in default.items():
                    if key not in self._data:
                        self._data[key] = val
            except (json.JSONDecodeError, IOError):
                self._data = self._default_state()
        else:
            self._data = self._default_state()
        return self._data

    def save(self):
        self._data['last_update_date'] = date.today().isoformat()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix='.json', prefix='state_',
            dir=os.path.dirname(self._path),
        )
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2,
                          default=str)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # ------------------------------------------------------------------
    # 访问
    # ------------------------------------------------------------------

    @property
    def data(self) -> Dict:
        return self._data

    @property
    def portfolio(self) -> Dict:
        return self._data.get('portfolio', {})

    @property
    def model_info(self) -> Dict[str, str]:
        return self._data.get('model_info', {})

    # ------------------------------------------------------------------
    # 组合操作
    # ------------------------------------------------------------------

    def update_portfolio(self, cash: float, positions: Dict,
                         pending_orders: Dict[str, str],
                         portfolio_value: float,
                         strategy_name: str = ''):
        pf = self._data.setdefault('portfolio', {})
        pf['cash'] = round(cash, 2)

        # 深拷贝持仓，避免外部引用修改
        positions_copy = {}
        for sym, pos in positions.items():
            positions_copy[sym] = dict(pos)
        pf['positions'] = positions_copy

        pf['pending_orders'] = dict(pending_orders)
        pf['initial_capital'] = pf.get('initial_capital', 1_000_000.0)
        pf['_last_portfolio_value'] = portfolio_value

        if strategy_name:
            pf['strategy'] = strategy_name

    def add_trade(self, entry: Dict, max_days: int = 180):
        log = self._data.setdefault('trade_log', [])
        log.append(dict(entry))  # 深拷贝
        if len(log) > 100:
            from datetime import timedelta
            cutoff = (date.today() - timedelta(days=max_days)).isoformat()
            self._data['trade_log'] = [
                t for t in log
                if t.get('date', '').startswith('20') and t.get('date', '') >= cutoff
            ]

    def set_benchmark_start_price(self, price: float):
        self._data['benchmark_start_price'] = price

    def get_benchmark_start_price(self) -> float:
        return self._data.get('benchmark_start_price', 0.0)

    def set_model_trained(self, model_key: str):
        models = self._data.setdefault('model_info', {})
        models[model_key] = date.today().isoformat()
        self.save()

    def needs_retrain(self, model_key: str, interval_days: int = 30) -> bool:
        from datetime import datetime
        last = self.model_info.get(model_key)
        if last is None:
            return True
        try:
            last_dt = datetime.strptime(str(last)[:10], '%Y-%m-%d').date()
            return (date.today() - last_dt).days >= interval_days
        except (ValueError, TypeError):
            return True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _default_state() -> Dict:
        return {
            'version': 2,
            'portfolio': {
                'cash': 1_000_000.0,
                'initial_capital': 1_000_000.0,
                'positions': {},
                'pending_orders': {},
                'strategy': '',
            },
            'model_info': {},
            'benchmark_start_price': 0.0,
            'trade_log': [],
            'last_update_date': None,
        }
