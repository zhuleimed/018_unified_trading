"""
策略注册表 — 懒加载，避免导入冲突。

用法:
  from strategies import get_strategy, list_strategies
  strategy = get_strategy('lstm')
"""

import importlib

# ── 策略注册表 ──────────────────────────────────
# 格式: '策略名': '模块路径:类名'
# 新增策略只需在此添加一行
# ────────────────────────────────────────────────
STRATEGY_REGISTRY = {
    'indicator': 'strategies.dynamic_indicator:DynamicIndicatorStrategy',
    'lstm': 'strategies.model_lstm:LSTMEtfStrategy',
}

# 缓存已加载的类
_CLASS_CACHE = {}


def get_strategy(name: str):
    """按名称获取策略实例（懒加载）。"""
    if name not in STRATEGY_REGISTRY:
        raise ValueError(
            f'未知策略: "{name}"。可用策略: {list_strategies()}'
        )

    # 首次加载：字符串 → 类
    if name not in _CLASS_CACHE:
        entry = STRATEGY_REGISTRY[name]
        mod_name, cls_name = entry.split(':')
        mod = importlib.import_module(mod_name)
        _CLASS_CACHE[name] = getattr(mod, cls_name)

    return _CLASS_CACHE[name]()


def list_strategies() -> list:
    """列出所有已注册策略名。"""
    return list(STRATEGY_REGISTRY.keys())
