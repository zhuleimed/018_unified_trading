"""
消息推送 — WxPusher 微信推送
"""

from datetime import date
from typing import Any, Dict

from wxpusher import WxPusher

from config.config import WXPUSHER_TOKEN, WXPUSHER_UIDS, WXPUSHER_TOPIC_IDS


def _send(message: str):
    try:
        WxPusher.send_message(
            message,
            uids=WXPUSHER_UIDS,
            topic_ids=WXPUSHER_TOPIC_IDS,
            token=WXPUSHER_TOKEN,
        )
    except Exception as e:
        print(f'[WxPusher] 推送失败: {e}')


def push_daily_report(summary: Dict[str, Any]):
    today = summary.get('date', date.today().isoformat())

    lines = [
        f'📊 统一模拟盘 · 日报',
        f'日期: {today}',
        f'策略: {summary.get("strategy", "N/A")}',
    ]

    if summary.get('dry_run'):
        lines.append('⚠ DRY RUN 模式')

    if summary.get('no_targets'):
        lines.append('')
        lines.append('⚠ 策略今日未选出交易标的，无操作')
        lines.append('')

    # 操作
    trades = summary.get('trades_today', [])
    lines.append('')
    lines.append('── 当日操作 ──')
    if trades:
        for t in trades:
            action = '🟢 买入' if t['action'] == 'buy' else '🔴 卖出'
            reason = t.get('reason', '')
            reason_tag = f' ({reason})' if reason else ''
            lines.append(
                f'{action} {t["symbol"]}: {t["shares"]}份 @ {t["price"]:.4f}  '
                f'金额={t.get("cost", 0):.2f}  '
                f'盈亏={t.get("pnl", 0):+.2f}{reason_tag}'
            )
    else:
        lines.append('  无操作')

    # 持仓
    positions = summary.get('positions', [])
    lines.append('')
    lines.append('── 持仓摘要 ──')
    if positions:
        for p in positions:
            sign = '+' if p['pnl_pct'] >= 0 else ''
            lines.append(
                f'  {p["symbol"]}: {p["shares"]}份  '
                f'成本={p["avg_cost"]:.4f}  '
                f'现价={p["last_close"]:.4f}  '
                f'({sign}{p["pnl_pct"]:.2%})'
            )
    else:
        lines.append('  空仓')

    # 账户
    lines.append('')
    lines.append('── 账户摘要 ──')
    lines.append(f'总资产:     {summary["portfolio_value"]:,.2f}')
    lines.append(f'现金:       {summary["cash"]:,.2f}')
    cum_ret = summary.get('cumulative_return', 0)
    lines.append(f'策略累计收益: {"+" if cum_ret >= 0 else ""}{cum_ret:.2%}')

    bench_ret = summary.get('benchmark_return')
    if bench_ret is not None:
        lines.append(f'基准累计收益: {"+" if bench_ret >= 0 else ""}{bench_ret:.2%}')

    excess = summary.get('excess_return')
    if excess is not None:
        lines.append(f'超额收益:     {"+" if excess >= 0 else ""}{excess:.2%}')

    # 明日信号
    pending = summary.get('pending_orders', {})
    active = {s: a for s, a in pending.items() if a != 'hold'}
    if active:
        lines.append('')
        lines.append('── 明日信号 ──')
        for sym, action in active.items():
            emoji = '🟢' if action == 'buy' else '🔴'
            lines.append(f'  {emoji} {sym}: {action}')

    # 预测
    predictions = summary.get('predictions', {})
    if predictions:
        lines.append('')
        lines.append('── 模型预测 ──')
        for code, pred in predictions.items():
            if pred is not None:
                lines.append(f'  {"🟢" if pred > 0 else "🔴"} {code}: {pred:+.4f}%')

    lines.append('')
    lines.append('── 信号状态 ──')
    held_symbols = {p['symbol'] for p in summary.get('positions', [])}
    for sym, sig in summary.get('signal_details', {}).items():
        if sig == 1:
            label = '🟢 买入' if sym not in held_symbols else '🟢 加仓'
        elif sig == -1:
            label = '🔴 卖出' if sym in held_symbols else '⚪ 观望'
        else:
            label = '⚪ 持有'
        lines.append(f'  {label} {sym}')

    _send('\n'.join(lines))


def push_error(error_msg: str, phase: str = ''):
    lines = [
        '⚠ 统一模拟盘 · 异常告警',
        f'日期: {date.today().isoformat()}',
    ]
    if phase:
        lines.append(f'阶段: {phase}')
    lines.append('')
    lines.append(f'错误: {error_msg}')
    _send('\n'.join(lines))


def push_training_complete(results: Dict[str, str]):
    lines = [
        '🤖 模型训练完成',
        f'日期: {date.today().isoformat()}',
        '',
    ]
    for model, status in results.items():
        emoji = '✓' if status == 'ok' else '✗'
        lines.append(f'  {emoji} {model}: {status}')
    _send('\n'.join(lines))
