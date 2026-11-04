"""GUI 与调度器的轻量控制通道；协作暂停保留调用栈，不重跑任务。"""
from __future__ import annotations

import json
import sys
import threading
import time as real_time

CONTROL_PREFIX = '@@QQPET_CONTROL@@'
AUTO_RESUME_SECONDS = 300


class PauseController:
    def __init__(self, emit=None):
        self._condition = threading.Condition()
        self._requested = False
        self._deadline = 0.0
        self._paused_at = None
        self._paused_total = 0.0
        self._emit = emit or (lambda state: None)
        self.before_pause = None
        self.after_resume = None
        self._local = threading.local()

    def request(self, pause: bool) -> None:
        with self._condition:
            if pause == self._requested:
                return
            self._requested = pause
            if pause:
                self._deadline = real_time.monotonic() + AUTO_RESUME_SECONDS
            self._condition.notify_all()

    def monotonic(self) -> float:
        with self._condition:
            now = real_time.monotonic()
            return now - self._paused_total - (
                now - self._paused_at if self._paused_at is not None else 0)

    def checkpoint(self) -> None:
        if getattr(self._local, 'inside', False):
            return
        with self._condition:
            if not self._requested:
                return
            self._local.inside = True
            try:
                # 在执行线程释放正在搓洗的触摸，避免暂停时一直按住手机。
                self._run_hook(self.before_pause, '暂停时释放触摸')
                self._paused_at = real_time.monotonic()
                self._emit({'state': 'paused', 'remaining': max(
                    0, self._deadline - self._paused_at)})
                automatic = False
                while self._requested:
                    remaining = self._deadline - real_time.monotonic()
                    if remaining <= 0:
                        self._requested = False
                        automatic = True
                        break
                    self._condition.wait(remaining)
                self._paused_total += real_time.monotonic() - self._paused_at
                self._paused_at = None
                self._run_hook(self.after_resume, '恢复时重新按住触摸点')
                self._emit({'state': 'running', 'automatic': automatic})
            finally:
                self._local.inside = False

    @staticmethod
    def _run_hook(hook, stage):
        if hook:
            try:
                hook()
            except Exception as e:
                # 手动暂停不能因抬手失败触发任务重跑；恢复后的设备操作仍走原有自愈。
                from .progress import log
                log(f'{stage}未完成: {e}')

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError('sleep length must be non-negative')
        end = self.monotonic() + seconds
        while True:
            self.checkpoint()
            remaining = end - self.monotonic()
            if remaining <= 0:
                return
            with self._condition:
                self._condition.wait(min(remaining, 0.1))


controller = PauseController()


class _Clock:
    sleep = staticmethod(controller.sleep)
    monotonic = staticmethod(controller.monotonic)
    real_monotonic = staticmethod(real_time.monotonic)
    real_sleep = staticmethod(real_time.sleep)

    def __getattr__(self, name):
        return getattr(real_time, name)


clock = _Clock()


def start_control_listener() -> None:
    """仅 GUI 拉起的调度器监听 stdin；控制台无管道时保持原行为。"""
    if sys.stdin is None or sys.stdin.isatty():
        return

    def emit(state):
        print(CONTROL_PREFIX + json.dumps(state), flush=True)

    def listen():
        for line in sys.stdin:
            command = line.strip()
            if command in ('pause', 'resume'):
                controller.request(command == 'pause')

    controller._emit = emit
    threading.Thread(target=listen, name='runner-control', daemon=True).start()
