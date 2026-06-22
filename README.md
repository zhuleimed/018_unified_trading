# 🏦 018_unified_trading — 统一量化模拟盘系统

> **用统一框架管理不同选股策略的模拟盘交易，只需更换策略模块，基础设施不动。**

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](https://python.org)

---

## 📑 目录

- [项目定位](#-项目定位)
- [数据来源](#-数据来源)
- [核心逻辑](#-核心逻辑)
- [项目结构](#-项目结构)
- [模块详解](#-模块详解)
- [策略体系](#-策略体系)
- [运行方式](#-运行方式)
- [交易规则](#-交易规则)
- [风控体系](#-风控体系)
- [收益计算](#-收益计算)
- [与 015/016 的关系](#-与-015016-的关系)
- [常见问题](#-常见问题)
- [运维指南](#-运维指南)

---

## 🎯 项目定位

本项目的核心思想是 **将模拟盘交易的基础设施（买卖、风控、持仓、推送）与策略逻辑分离**，实现：

```
更换策略 = 新建一个 strategies/xxx.py 文件 + 在注册表中加一行
不改任何 core/ 模块
```

目前内置两个策略：
| 策略 | 来源 | 方法论 |
|------|------|--------|
| `indicator`（默认） | 继承 015 项目 | 从 97 个技术指标中动态选出最佳指标，再用该指标扫描沪深300成分股选股，每日生成信号 |
| `lstm` | 继承 016 项目 | 用 LSTM-Transformer 深度学习模型预测 ETF 次日涨跌幅，超阈值生成买卖信号 |

---

## 📡 数据来源

### 优先级

```
004_sequoia-x 数据库（/data/sequoia_v2.db）
    ↓ 有数据？← 直接使用
    ↓ 无数据？
baostock API（短区间 ~400天，30秒超时保护）
```

### 数据库 vs baostock 对比

| 维度 | 004_sequoia-x 数据库 | baostock 兜底 |
|------|---------------------|--------------|
| 数据范围 | 2024-01 至今 | 自定义区间 |
| 覆盖标的 | 5200+ 只 A 股 | 全部 A 股 + ETF |
| ETF 数据 | ❌ 暂未同步 | ✅ 正常获取 |
| 稳定性 | 高（本地 SQLite） | 中（网络依赖） |
| 超时风险 | 无 | 30s alarm 保护 |

> **注意**：004_sequoia-x 的数据同步框架当前未包含 ETF，所以 ETF 类策略（如 `lstm`）会触发 baostock 兜底。后续修复 004 的 ETF 同步后，ETF 数据也会从数据库优先获取。

### 交易日判断

通过 baostock `query_trade_dates()` 判断，失败时回退到 `weekday() < 5`。

---

## 🔄 核心逻辑

### 每日执行流程（模拟盘 Phase）

```
Day N 开盘
  │
  ├─ 1️⃣ 交易日检查
  │     └─ baostock query_trade_dates → 非交易日→静默退出
  │
  ├─ 2️⃣ 加载数据
  │     ├─ 从数据库/baostock 获取所有标的最新日线
  │     └─ 需满足最少 min_days=60 行
  │
  ├─ 3️⃣ 更新持仓最高价
  │     └─ 每只持仓 max(昨高, 今日close) → 用于回落止盈
  │
  ├─ 4️⃣ 清空 T+1 标记
  │     └─ 昨日的买入标记 → 今日可风控
  │
  ├─ 5️⃣ 执行昨日待处理订单
  │     ├─ 🟢 买入：等额资金分配 → 整数手 → 含佣金计入成本
  │     └─ 🔴 卖出：全部清仓 → 扣除佣金+印花税 → 计算盈亏
  │
  ├─ 6️⃣ 风控检查
  │     ├─ 🛑 固定止损：现价 < 成本×(1-5%) → 强制卖出
  │     └─ 📉 回落止盈：现价 < 最高价×(1-3%) → 强制卖出
  │     └─ T+1保护：当日新开仓跳过风控
  │
  ├─ 7️⃣ 生成明日信号
  │     ├─ strategy.generate(df) → 1(买)/-1(卖)/0(持)
  │     ├─ 有持仓时信号-1 → 明日卖出
  │     └─ 无持仓时信号+1 → 明日买入
  │
  ├─ 8️⃣ 计算组合市值
  │     ├─ 市值 = 现金 + Σ(股数×最新价)
  │     └─ 收益率 = (市值 − 初始资金) / 初始资金
  │
  ├─ 9️⃣ 基准对比
  │     ├─ 基准从模拟启动日开始算 → buy-and-hold
  │     └─ 超额收益 = 策略收益 − 基准收益
  │
  ├─ 🔟 持久化状态
  │     └─ 原子写入（tmp→rename）→ JSON
  │
  └─ 1️⃣1️⃣ 推送日报（WxPusher 微信）
```

---

## 🏗 项目结构

```
018_unified_trading/
│
├── run_daily.py                    ← 🚀 唯一入口
│
├── config/
│   └── config.py                   ← 📋 全局配置（资金/费用/风控/路径/推送）
│
├── core/                           ← ⚙️ 基础设施（一次写好，不再改动）
│   ├── broker.py                   ← 💹 买卖执行（买入/卖出/持仓更新）
│   ├── risk.py                     │ 🛡 风控（止损/回落止盈/T+1保护）
│   ├── portfolio.py                │ 💰 组合管理（市值/收益/基准）
│   ├── simulator.py                │ 🔄 每日流程编排
│   ├── state_manager.py            │ 💾 JSON 原子写入持久化
│   ├── data_loader.py              │ 📡 数据加载（数据库→baostock）
│   ├── notification.py             │ 📱 WxPusher 微信推送
│   ├── signal_engine.py            │ 🔌 信号引擎（从 015 移植）
│   └── log_utils.py                │ 🎨 ANSI 彩色日志
│
├── strategies/                     ← 📦 策略模块（只需换这里）
│   ├── __init__.py                 ← 策略注册表
│   ├── base.py                     ← 抽象基类（定义 generate 接口）
│   ├── dynamic_indicator.py        ← 动态指标选优策略（来自 015）
│   └── model_lstm.py               ← LSTM ETF 预测策略（来自 016）
│
├── output/                         ← 📊 运行时产物
│   └── state.json                  ← 持仓/资金/状态
│
└── logs/                           ← 📜 运行日志
```

---

## 🧩 模块详解

### config/config.py — 全局配置中心

所有可调参数集中管理，按功能分区：

| 区块 | 关键配置 | 默认值 | 说明 |
|------|---------|--------|------|
| 资金 | `INITIAL_CAPITAL` | 1,000,000 | 初始资金 |
| | `MAX_POSITIONS` | 10 | 最大持仓数 |
| 费用 | `SLIPPAGE` | 0.003 | 滑点 0.3% |
| | `COMMISSION_RATE` | 0.0005 | 佣金万五 |
| | `MIN_COMMISSION` | 5.0 | A股最低5元，ETF可设0 |
| | `TAX_RATE` | 0.001 | 印花税千分之一（卖出） |
| 风控 | `STOP_LOSS_PCT` | 0.05 | 止损 5% |
| | `TRAILING_STOP_PCT` | 0.03 | 回落止盈 3% |
| 策略 | `DEFAULT_STRATEGY` | 'indicator' | 默认策略名 |
| | `RESCAN_DAYS` | 90 | 动态指标重扫间隔 |
| 数据 | `MIN_TRADING_DAYS` | 60 | 次新股过滤 |

**策略可覆盖配置**：策略类通过 `config_overrides` 字段覆盖全局默认值：
```python
class LSTMEtfStrategy(BaseStrategy):
    config_overrides = {
        'TAX_FREE': True,       # ETF 免印花税
        'MIN_COMMISSION': 0.0,  # ETF 无最低5元
    }
```

### core/broker.py — 交易执行

**买入流程**：
```
1. 可用资金 = min(剩余现金, 等额预算) × 仓位比例(95%)
2. 执行价 = 开盘价 × (1 + 滑点)
3. 股数 = floor(可用资金 / 执行价) 向下取整到整手(100)
4. 买入佣金 = max(成交额 × 万五, 最低佣金)
5. 总成本 = 成交额 + 买入佣金 ✅ （原项目漏记买入佣金）
6. 更新持仓：含 T+1 标记 + 最高价追踪
```

**卖出流程**：
```
1. 执行价 = 开盘价 × (1 - 滑点)
2. 卖出佣金 = max(成交额 × 万五, 最低佣金)
3. 印花税 = ETF免收 / 股票收千分之一
4. 净收入 = 成交额 - 佣金 - 印花税
5. 盈亏 = 净收入 - 持仓总成本（含买入佣金）✅
6. 清仓：删除持仓记录
```

**等额资金分配**（不同于原 015/016）：
```python
# 原项目：第1笔吃95%，后续吃残渣
available = cash * POSITION_PCT

# 新项目：每只标的固定预算
每只预算 = 初始资金 / MAX_POSITIONS
可用 = min(剩余现金, 每只预算) × 仓位比例
```

### core/risk.py — 风控

| 风控项 | 触发条件 | 执行 |
|--------|---------|------|
| 固定止损 | 现价 < 买入价 × (1 - 5%) | 开盘价强制卖出 |
| 回落止盈 | 现价 < 持仓最高价 × (1 - 3%) | 开盘价强制卖出 |
| T+1 保护 | 当日开仓标记 `today_opened=True` | 跳过风控 |

**持仓最高价更新**：每天开盘前用 `max(昨高, 今日收盘)` 更新。

### core/portfolio.py — 组合管理

```python
组合市值 = 现金 + Σ(股数 × 最新收盘价)
累计收益率 = (当前市值 - 初始资金) / 初始资金
基准收益率 = (基准当前价 - 基准启动价) / 基准启动价  # 从模拟日算起 ✅
超额收益 = 策略收益率 - 基准收益率
```

**基准起步价**：首次运行模拟盘时，记录当日标的收盘价为基准起点，后续始终以该起点计算。

### core/data_loader.py — 数据加载

```python
load_stock_data(code, start, end, min_days=60)   # 个股
load_etf_data(code, start, end, min_days=50)     # ETF
load_benchmark_data(code, start, end)             # 指数
```

### core/simulator.py — 每日流程编排

见上方"每日执行流程"图。关键修复：

| 修复项 | 原项目问题 | 新项目方案 |
|--------|-----------|-----------|
| 买入佣金 | PnL 漏记 | 计入持仓 total_cost |
| 资金分配 | 第1笔吃95% | 等额分配 |
| 回落止盈 | 定义了但没用 | 已实现 |
| T+1保护 | 无保护 | 当日开仓标记跳过风控 |
| 基准起点 | 全量数据 | 模拟启动日算起 |
| 持仓深拷贝 | 引用共享 | save 时深拷贝 |

---

## 🎯 策略体系

### 策略接口

所有策略必须继承 `BaseStrategy` 并实现 `generate()`：

```python
class MyStrategy(BaseStrategy):
    """自定义策略只需实现 generate() 方法。"""
    
    # 覆盖全局配置（可选）
    config_overrides: dict = {}
    # 交易标的名细（股票用 load_stock_data，ETF 用 load_etf_data）
    target_symbols: List[str] = []

    @property
    def name(self) -> str:
        return 'MyStrategy'

    def generate(self, symbol: str, df: pd.DataFrame) -> int:
        """
        对单只标的生成次日信号。
        
        Parameters
        ----------
        symbol : str
            股票/ETF 代码
        df : pd.DataFrame
            日线数据（含 date, open, high, low, close, volume, amount）
        
        Returns
        -------
        int : 1=买入, -1=卖出, 0=持有
        """
        ...
```

### 策略注册

在 `strategies/__init__.py` 注册表中加一行即可启用：

```python
STRATEGY_REGISTRY = {
    'indicator': 'strategies.dynamic_indicator:DynamicIndicatorStrategy',
    'lstm': 'strategies.model_lstm:LSTMEtfStrategy',
    'my': 'strategies.my_strategy:MyStrategy',  # ← 新增
}
```

### 内置策略 1：DynamicIndicator（默认）

**来源**：015_indicator_scanner

**流程**：
```
每 RESCAN_DAYS=90 天或 --force：
  ├─ Phase 1: 扫描全部 97 个指标 × 300 只沪深300成分股
  │     评分 = mean_excess_return × win_rate - STD_PENALTY × std
  │     选出综合评分最高的指标
  │
  ├─ Phase 2: 用最佳指标选出超额收益前10的股票
  │
  └─ Phase 3: 验证选中股票在最近3个月是否跑赢基准
    
每日运行时：
  用选中的指标对持仓股票计算信号 → 1/-1/0
```

### 内置策略 2：LSTMEtf

**来源**：016_etf_lstm_predict

**流程**：
```
每 MODEL_RETRAIN_INTERVAL=30 天或 --train：
  ├─ 加载 4 只沪深300 ETF（510300/510310/510330/159919）
  ├─ 计算 30+ 维技术指标特征
  └─ 训练 LSTM-Transformer 合并模型

每日运行时：
  ├─ 加载已训练模型
  ├─ 准备最新 WINDOW_SIZE=20 日特征
  ├─ 模型预测次日涨跌幅%
  └─ 预测 > +0.36% → 买入 | < -0.36% → 卖出 | 其余 → 持有
```

---

## 🚀 运行方式

### 基础命令

```bash
# 切换到项目目录
cd /public/home/hpc/zhulei/superman/quant/code/018_unified_trading

# 查看可用策略
python run_daily.py --list-strategies

# 用默认策略运行（indicator）
python run_daily.py

# 指定策略运行
python run_daily.py --strategy lstm

# Dry-run 不修改状态
python run_daily.py --dry-run
python run_daily.py --strategy lstm --dry-run
```

### 训练/扫描

```bash
# 强制重新扫描指标（indicator 策略）
python run_daily.py --strategy indicator --train

# 强制重新训练模型（lstm 策略）
python run_daily.py --strategy lstm --train
```

### Cron 配置

```bash
# 交易日 21:10 运行（与 016 错开）
10 21 * * 1-5 cd /public/home/hpc/zhulei/superman/quant/code/018_unified_trading && \
  /home/zhulei/anaconda3/envs/zhulei/bin/python run_daily.py \
  >> logs/daily_$(date +\%Y\%m\%d).log 2>&1
```

切换默认策略只需改 `config/config.py`：
```python
DEFAULT_STRATEGY = 'lstm'  # 改为 LSTM 策略
```

---

## 📋 交易规则

### 买入规则

| 规则 | 说明 |
|------|------|
| 触发条件 | `strategy.generate()` 返回 1，且该标的不在持仓中 |
| 执行时间 | 下一交易日开盘（`date.today() + 1`） |
| 执行价格 | 开盘价 × (1 + 滑点) |
| 买入数量 | 等额预算 / 执行价，向下取整到 100 的倍数 |
| 资金上限 | min(剩余现金, 等额每只预算) × 95% |
| 费用 | 佣金 = max(成交额 × 万五, 最低佣金)，计入成本 |

### 卖出规则

| 规则 | 说明 |
|------|------|
| 触发条件 | `strategy.generate()` 返回 -1，且该标的有持仓 |
| 执行时间 | 下一交易日开盘 |
| 执行价格 | 开盘价 × (1 - 滑点) |
| 卖出数量 | 全部持仓（不留零股） |
| 费用 | 佣金 + 印花税（ETF免印花税） |

### 风控卖出规则

风控卖出在信号卖出之前执行，优先级更高：

| 风控 | 触发条件 | 说明 |
|------|---------|------|
| 固定止损 | 开盘价 < 买入均价 × (1 - 5%) | 防止大幅亏损 |
| 回落止盈 | 开盘价 < 持仓最高价 × (1 - 3%) | 锁定利润，防止利润回吐 |

### 最大持仓限制

- `MAX_POSITIONS` 配置最大同时持仓数（默认 10）
- 买入信号超过最大持仓时，不再开新仓
- 资金在未满仓时等额分配到各持仓

---

## 🛡 风控体系

### 固定止损

```python
条件：当前价 < 买入均价 × (1 - STOP_LOSS_PCT)
     = 买入均价 × 0.95（默认 5%）
```

作用：单只标的亏损达到 5% 时无条件卖出，防止亏损扩大。

### 回落止盈

```python
条件：当前价 < 持仓期间最高价 × (1 - TRAILING_STOP_PCT)
     = 最高价 × 0.97（默认 3%）
```

作用：持仓价格上涨后回落 3% 时卖出，在保护利润的同时让利润奔跑。

举例：
```
买入 100 元 → 涨到 120 元 → 最高价 = 120
回落到 120 × 0.97 = 116.4 元 → 止盈卖出，锁定 (116.4-100)=16.4% 收益
```

### T+1 保护

当日新开仓标记 `today_opened=True`，当天不执行风控检查。次日开盘自动清空标记，风控生效。

---

## 📊 收益计算

### 组合市值

```python
组合市值 = 现金余额 + Σ(股数 × 最新收盘价)
```

### 累计收益率

```python
累计收益率 = (组合市值 - 初始资金) / 初始资金
```

### 基准收益率

```python
基准收益率 = (基准当前价 - 基准启动价) / 基准启动价
```

- 基准启动价在首次运行模拟盘时记录
- 此后始终以该价格计算基准，不随数据更新漂移 ✅

### 超额收益

```python
超额收益 = 策略累计收益率 - 基准累计收益率
```

---

## 🔗 与 015/016 的关系

| 维度 | 015/016 | 018 统一框架 |
|------|---------|-------------|
| 交易执行 | 两套重复代码 | 统一 broker.py |
| 风控 | 只有止损，止盈未启用 | 止损 + 回落止盈 |
| 资金分配 | 第1笔吃95%残渣 | 等额分配 |
| 买入佣金 | 不计入成本（PnL偏高） | 计入成本（真实PnL） |
| 基准 | 全量数据首末收益 | 从模拟启动日算 |
| T+1 | 无保护 | `today_opened` 标记 |
| 策略 | 与基础设施耦合 | 解耦，可插拔 |
| 数据源 | 015用数据库，016用baostock | 数据库优先统一 |

### 迁移建议

1. **如果你在用 016（LSTM ETF）** → 直接切到 `--strategy lstm`，预测结果一致，额外获得风控和正确 PnL
2. **如果你在用 015（指标扫描）** → 切到 `--strategy indicator`，选指标逻辑一致，额外获得回落止盈和等额分配
3. **如果你想写新策略** → 在 `strategies/` 下新建文件，继承 `BaseStrategy`，注册即可

---

## ❓ 常见问题

### Q1: 为什么跑 indicator 策略时第一次很慢？

第一次运行需要扫描全部 97 个指标 × 300 只股票，约 2~3 分钟。之后的 90 天内再运行直接走模拟盘，1 秒完成。也可以 `--strategy lstm` 跳过扫描。

### Q2: 数据从哪里来？

优先从 004_sequoia-x 的 SQLite 数据库（本地）。如果数据库没有对应的股票/ETF 数据，自动走 baostock 兜底（有 30 秒超时保护）。

### Q3: ETF 数据为什么没有在数据库里？

004_sequoia-x 的同步框架 `get_active_stocks()` 过滤了 ETF 代码前缀（仅保留 `sh.6/sz.0/sz.3`）。后续修复后可正常同步。

### Q4: 买入佣金怎么算？为什么说原项目 PnL 偏高？

原项目买入时佣金计入 `total_cost` 用于资金检查，但存入持仓时只记了成交额（不含佣金）。卖出结算 PnL 时也只扣了成交额，所以 PnL 偏高万五。新项目修复了此问题。

### Q5: 回测和实盘的关系？

本系统是模拟盘（paper trading），非实盘交易。信号生成 → 订单记录 → 次日检查是否成交，全程不涉及真实资金。实盘操作需自行对接券商 API。

### Q6: 如何添加自己的策略？

```python
# 1. 新建 strategies/my_strategy.py
from strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    name = 'MyStrategy'
    target_symbols = ['000001', ...]
    
    def generate(self, symbol, df):
        return 1 if ... else 0

# 2. 在 strategies/__init__.py 注册
STRATEGY_REGISTRY['my'] = 'strategies.my_strategy:MyStrategy'
```

### Q7: 为什么信号状态显示"卖出"但当日无操作？

正常。信号是当日生成的，**次日开盘才执行**。所以卖出信号在今天生成，明天开盘卖出。如果当前空仓，卖出信号被抑制（无仓位可卖）。

---

## 🛠 运维指南

### 日志

```bash
# 查看最近日志
tail -20 logs/daily_$(date +%Y%m%d).log

# 查看当日详细输出
python run_daily.py --dry-run
```

### 状态文件

```bash
# 查看当前持仓
python -c "import json; d=json.load(open('output/state.json')); print(json.dumps(d['portfolio'], indent=2))"
```

### 防重复运行

系统自动检测并清理残留进程（通过 `/proc/PID/cmdline` 精确匹配 + PID 锁文件），防止同一时间多个实例冲突。

### 退出清理

退出时自动删除 PID 锁文件，异常退出也保证清理（`try/finally`）。

### GitHub 同步

```bash
# 首次推送
git init && git branch -m master main
# 创建 .gitignore 后再 add
git add .
git commit -m "init: 018_unified_trading 统一模拟盘系统"
gh repo create zhuleimed/018_unified_trading --public --description "统一量化模拟盘系统 — 可插拔策略框架"
git remote add origin git@github.com:zhuleimed/018_unified_trading.git
git push -u origin main
```

---

## 📜 更新日志

| 日期 | 版本 | 内容 |
|------|------|------|
| 2026-06-22 | v1.0 | 初始版本，indicator + lstm 双策略 |

---

> **核心思想：写策略的人只需要关心 `generate()`，其余一切由框架保障。**
