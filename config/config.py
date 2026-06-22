"""
统一配置 — 018_unified_trading

所有参数集中管理，策略通过 config_overrides 按需覆盖。
"""

import os
import torch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.dirname(PROJECT_DIR)

# ============================================================================
# 路径
# ============================================================================
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'output')
MODEL_DIR = os.path.join(OUTPUT_DIR, 'models')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')
STATE_FILE = os.path.join(OUTPUT_DIR, 'state.json')

# ============================================================================
# 资金与交易成本（全局默认 — 偏 A 股股票）
# ============================================================================
INITIAL_CAPITAL = 1_000_000.0        # 初始资金（元）
MAX_POSITIONS = 10                   # 最大同时持仓数
POSITION_PCT = 0.95                  # 单笔仓位比例上限
MIN_TRADE_UNIT = 100                 # 最小交易单位（股/份）

SLIPPAGE = 0.003                     # 滑点 0.3%
COMMISSION_RATE = 0.0005             # 佣金万五
MIN_COMMISSION = 5.0                 # 最低佣金（A股5元，ETF可设为0）
TAX_RATE = 0.001                     # 印花税千分之一（卖出时，ETF免收）

# ============================================================================
# 风控
# ============================================================================
STOP_LOSS_PCT = 0.05                 # 固定止损 5%
TRAILING_STOP_PCT = 0.03             # 回落止盈 3%（从持仓最高点回撤）

# ============================================================================
# 信号阈值（仅对模型类策略生效，指标类策略自行控制）
# ============================================================================
SIGNAL_THRESHOLD = 0.0036            # 0.36%

# ============================================================================
# 默认策略（cron 运行时使用）
# ============================================================================
DEFAULT_STRATEGY = 'indicator'       # 'indicator' | 'lstm'

# ============================================================================
# 数据
# ============================================================================
MIN_TRADING_DAYS = 60                # 最少交易天数（次新股过滤）
SCAN_YEARS = 2                       # 回测扫描年数
RESCAN_DAYS = 90                     # 动态指标重新扫描间隔（自然日）

# ============================================================================
# ETF 列表（用于 LSTM 等 ETF 策略）
# ============================================================================
ETF_CODES = ['510300', '510310', '510330', '159919']
TRADING_ETF = '510300'

# ============================================================================
# LSTM 模型参数
# ============================================================================
USE_SIMPLE_MODEL = True
WINDOW_SIZE = 20
PREDICTION_HORIZON = 1
TRAIN_RATIO = 0.6
VAL_RATIO = 0.2
TEST_RATIO = 0.2
NUM_EPOCHS = 100
EARLY_STOPPING_PATIENCE = 15
MODEL_RETRAIN_INTERVAL = 30

SIMPLE_MODEL_PARAMS = {
    'lstm_hidden': 32,
    'lstm_layers': 1,
    'fc_hidden': 16,
    'dropout': 0.2,
    'lr': 0.0005,
    'batch_size': 8,
    'epochs': 50,
}

PRODUCTION_MODEL_PARAMS = {
    'lstm_hidden': 48,
    'lstm_layers': 1,
    'transformer_dim': 48,
    'nhead': 4,
    'num_transformer_layers': 1,
    'fc_hidden': 24,
    'additional_fc_layers': 0,
    'dropout': 0.3,
    'lr': 0.0005,
    'batch_size': 8,
    'epochs': 100,
}

# ============================================================================
# 设备
# ============================================================================
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
SEED = 42

# ============================================================================
# WxPusher
# ============================================================================
WXPUSHER_TOKEN = 'AT_hKGG0UfwrCP7bpcsO8cbQkrc4bZ9G3RX'
WXPUSHER_UIDS = ['<uids>']
WXPUSHER_TOPIC_IDS = ['39277']


def ensure_dirs():
    for d in [OUTPUT_DIR, MODEL_DIR, LOG_DIR]:
        os.makedirs(d, exist_ok=True)
