"""
LSTM 策略 — 继承 016_etf_lstm_predict 的深度学习预测体系。

用 LSTM 模型预测 ETF 次日涨跌幅，以阈值过滤生成买卖信号。

依赖：016_etf_lstm_predict 项目（model/ 目录）
"""

import sys
import os
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from strategies.base import BaseStrategy

# 依赖 016 项目的模型代码
# 用 importlib 预注册 config.etf_config，避免 018 的 config/ 包名冲突
_016_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        '..', '016_etf_lstm_predict')
_016_DIR = os.path.abspath(_016_DIR)

import importlib.util
_etf_config_path = os.path.join(_016_DIR, 'config', 'etf_config.py')
if os.path.exists(_etf_config_path):
    spec = importlib.util.spec_from_file_location('config.etf_config', _etf_config_path)
    _mod = importlib.util.module_from_spec(spec)
    sys.modules['config.etf_config'] = _mod
    spec.loader.exec_module(_mod)

# 临时插入路径用于 016 内部跨模块引用
if _016_DIR not in sys.path:
    sys.path.insert(0, _016_DIR)

from model.lstm_transformer_predictor import LSTMTransformerPredictor
from model.feature_engineer import compute_features


class LSTMEtfStrategy(BaseStrategy):
    """
    LSTM-Transformer ETF 预测策略。

    用单一合并模型（4只ETF数据合并训练）预测 510300 次日涨跌幅，
    预测绝对值超过 SIGNAL_THRESHOLD 时生成买卖信号。

    config_overrides:
      - TAX_FREE: True（ETF 免印花税）
      - MIN_COMMISSION: 0.0（ETF 无最低5元）
      - SIGNAL_THRESHOLD: 0.0036
    """

    config_overrides = {
        'TAX_FREE': True,
        'MIN_COMMISSION': 0.0,
        'WINDOW_SIZE': 20,
    }

    def __init__(self, trading_etf: str = '510300',
                 train_etfs: Optional[List[str]] = None):
        super().__init__()
        self.trading_etf = trading_etf
        self.train_etfs = train_etfs or ['510300', '510310', '510330', '159919']
        self.target_symbols = [trading_etf]
        self._predictor: Optional[LSTMTransformerPredictor] = None
        self._last_train_date: Optional[date] = None

    @property
    def name(self) -> str:
        return 'LSTMEtf(510300)'

    def generate(self, symbol: str, df: pd.DataFrame) -> int:
        """用 LSTM 模型预测并生成买卖信号。"""
        if self._predictor is None:
            return 0

        pred = self._predictor.predict_next_day(df)
        if pred is None:
            return 0

        from config.config import SIGNAL_THRESHOLD
        threshold = SIGNAL_THRESHOLD * 100  # 转为百分比

        if pred > threshold:
            return 1   # 买入
        elif pred < -threshold:
            return -1  # 卖出
        return 0       # 持有

    def train(self, data_dict: Optional[Dict[str, pd.DataFrame]] = None) -> bool:
        """
        训练 LSTM 模型。

        从数据库或 data_dict 加载 ETF 数据，合并训练单一模型。
        """
        from config.config import USE_SIMPLE_MODEL
        from core.data_loader import DataLoader

        loader = DataLoader()
        dfs = []

        if data_dict:
            # 用传入的数据
            for code in self.train_etfs:
                if code in data_dict:
                    dfs.append(data_dict[code])
        else:
            # 从数据库/baostock 加载
            for code in self.train_etfs:
                df = loader.load_etf_data(code, min_days=30)
                if df is not None and len(df) > 30:
                    dfs.append(df)
                    print(f'  ✓ {code}: {len(df)} 行')
                else:
                    print(f'  ✗ {code}: 数据不足')

        if len(dfs) < 2:
            print(f'  有效 ETF 不足 2 只，无法训练')
            return False

        self._predictor = LSTMTransformerPredictor(use_simple=USE_SIMPLE_MODEL)
        success = self._predictor.train_combined(dfs, use_simple=USE_SIMPLE_MODEL)
        if success:
            self._predictor.save('combined')
            self._last_train_date = date.today()
        return success

    def needs_retrain(self, interval_days: int = 30) -> bool:
        """检查是否需要重训练。"""
        if self._predictor is None:
            return True
        if self._last_train_date is None:
            return True
        return (date.today() - self._last_train_date).days >= interval_days

    def load_model(self) -> bool:
        """加载已训练的模型。"""
        self._predictor = LSTMTransformerPredictor()
        return self._predictor.load('combined')

    def get_prediction(self, df: pd.DataFrame) -> Optional[float]:
        """获取次日预测涨跌幅（%）。"""
        if self._predictor is None:
            return None
        # 计算特征
        feat_df = compute_features(df)
        if feat_df is None or len(feat_df) < 25:
            return None
        return self._predictor.predict_next_day(df)
