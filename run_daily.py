#!/usr/bin/env python3
"""
run_daily.py — 018_unified_trading 统一模拟盘入口

用法:
  python run_daily.py                           # 自动判断（默认）
  python run_daily.py --strategy indicator      # 用动态指标策略
  python run_daily.py --strategy lstm           # 用 LSTM 策略
  python run_daily.py --train                   # 训练/扫描
  python run_daily.py --dry-run                 # 不修改状态
"""

import argparse
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from config.config import ensure_dirs, STATE_FILE, OUTPUT_DIR, DEFAULT_STRATEGY
from core.state_manager import StateManager
from core.simulator import Simulator
from core.notification import push_daily_report, push_error
from core.log_utils import get_logger
from strategies import get_strategy, list_strategies

logger = get_logger(__name__)

LOCK_FILE = os.path.join(OUTPUT_DIR, '.run_trading.lock')


def _check_stale_process():
    """检查并清理残留进程。"""
    my_pid = os.getpid()

    def _is_same_script(pid: int) -> bool:
        try:
            cmdline_path = f'/proc/{pid}/cmdline'
            if not os.path.exists(cmdline_path):
                return False
            with open(cmdline_path, 'rb') as f:
                raw = f.read()
            parts = raw.decode('utf-8', errors='replace').split('\0')
            if len(parts) < 2:
                return False
            if 'python' not in parts[0].lower():
                return False
            return any('run_daily.py' in p for p in parts[1:])
        except (OSError, IOError):
            return False

    try:
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == my_pid:
                continue
            if _is_same_script(pid):
                print(f'[启动] 发现残留进程 PID={pid}，清理…')
                try:
                    os.kill(pid, 15)
                    import time
                    time.sleep(0.5)
                    os.kill(pid, 0)
                    os.kill(pid, 9)
                except OSError:
                    pass
    except PermissionError:
        pass

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old = f.read().strip()
            if old and old.isdigit():
                old_pid = int(old)
                if old_pid != my_pid and _is_same_script(old_pid):
                    try:
                        os.kill(old_pid, 15)
                        import time
                        time.sleep(0.5)
                        os.kill(old_pid, 0)
                        os.kill(old_pid, 9)
                    except OSError:
                        pass
        except (ValueError, OSError):
            pass

    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, 'w') as f:
        f.write(str(my_pid))


def _cleanup_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(LOCK_FILE)
    except Exception:
        pass


def _resolve_strategy(name: str):
    """按名称解析策略实例。"""
    s = get_strategy(name)
    logger.info(f'策略: {s.name}')

    # 策略特有的初始化
    if name == 'indicator':
        s.attach_state(StateManager(STATE_FILE))
        from config.config import RESCAN_DAYS
        if s._state_manager.needs_retrain('scan_check', RESCAN_DAYS):
            logger.info('指标过期，开始重新扫描…')
            if s.on_rescan():
                s._state_manager.set_model_trained('scan_check')
                logger.info('扫描完成')
            else:
                logger.warning('扫描失败')
    elif name == 'lstm':
        if not s.load_model():
            logger.info('无已训练模型，需要 --train 先训练')

    return s


def main():
    _check_stale_process()

    parser = argparse.ArgumentParser(
        description='018_unified_trading — 统一模拟盘系统',
    )
    parser.add_argument('--strategy', type=str, default=DEFAULT_STRATEGY,
                        help=f'策略名，默认={DEFAULT_STRATEGY}。可用: {list_strategies()}')
    parser.add_argument('--dry-run', action='store_true',
                        help='dry-run 不修改状态')
    parser.add_argument('--train', action='store_true',
                        help='训练/扫描后退出')
    parser.add_argument('--list-strategies', action='store_true',
                        help='列出所有可用策略')
    args = parser.parse_args()

    ensure_dirs()

    # --list-strategies
    if args.list_strategies:
        print(f'可用策略 ({len(list_strategies())} 个):')
        for name in list_strategies():
            s = get_strategy(name)
            print(f'  {name:20s} ← {s.name}')
        _cleanup_lock()
        return

    state = StateManager(STATE_FILE)
    simulator = Simulator()

    # 解析策略
    try:
        strategy = _resolve_strategy(args.strategy)
    except Exception as e:
        logger.error(f'策略初始化失败: {e}')
        _cleanup_lock()
        return

    # --train 模式
    if args.train:
        if hasattr(strategy, 'on_rescan'):
            logger.info('执行全量扫描…')
            strategy.on_rescan()
        elif hasattr(strategy, 'train'):
            logger.info('执行模型训练…')
            strategy.train()
        logger.info('训练完成')
        _cleanup_lock()
        return

    # 每日模拟盘
    try:
        summary = simulator.run_daily(
            strategy=strategy,
            state_manager=state,
            dry_run=args.dry_run,
        )

        if summary is None:
            # 非交易日
            return

        if not args.dry_run:
            push_daily_report(summary)

    except Exception as e:
        logger.error(f'模拟盘异常: {e}', exc_info=True)
        push_error(str(e), '模拟盘')

    logger.info('执行完毕')
    _cleanup_lock()


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        _cleanup_lock()
        raise
