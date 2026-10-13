# -*- coding: utf-8 -*-
"""被雇佣检查场景：出门检测是否"被雇佣中"，是则按 employed.action 召回处理。

调度由执行器负责：employed.enabled 开关 + employed.time_range 时间段 +
employed.interval_seconds 检查间隔（默认 60 秒出门检查一次）；开启
employed.off_hours_recall 后，非时间段也会巡检，按 50/50 召回并通知；
被雇佣时间段内主任务（冒险/学习/打工/雇佣好友）不触发。

召回判定/动作复用基类：employed_recall_ready 单次判定是否到召回时机
（等到25/75 / 小于45min / 立刻召回策略），_recall_employed 执行召回
（召回确认、点 quit 后 count_cross('employed') 计数）。本场景**非阻塞**：
没到召回时机就回主页面，间隔后再检查，不驻留等待（基类 wait_employed_back
仍是阻塞版，供主任务流程的 wait_busy_end 用）。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from src.notify import send_employment_time, send_unemployed_reminder
from src.progress import log
from src.scenario import BUSY_GATE_ATTEMPTS, DeviceScenario


class EmployedScenario(DeviceScenario):
    """被雇佣检查：出门看一眼是否被雇佣中，是则按配置策略召回。"""

    def __init__(self, dev=None):
        super().__init__(dev)
        self._unemployed_since: float | None = None
        self._unemployed_reminded = False
        self._employment_time_notified: str | None = None
        self._recall_pending = False

    def _notify_available_once(self, now: datetime | None = None) -> None:
        """每个被雇佣时间窗首次确认空闲时提醒，跨零点归属开始日期。"""
        ec = self.cfg.employed
        if not ec.enabled or not getattr(ec, 'available_reminder', True):
            return
        now = now or datetime.now()
        start_s, end_s = ec.time_range.split('-', 1)
        start = datetime.strptime(start_s.strip(), '%H:%M').time()
        end = datetime.strptime(end_s.strip(), '%H:%M').time()
        current = now.time()
        in_window = (start <= current < end if end > start
                     else current >= start or current < end)
        if not in_window:
            return
        day = now.date()
        if end <= start and current < end:
            day -= timedelta(days=1)
        window = f'{day.isoformat()}:{ec.time_range}'
        if self._employment_time_notified == window:
            return
        send_employment_time(window)
        self._employment_time_notified = window

    def _reset_unemployed_reminder(self) -> None:
        self._unemployed_since = None
        self._unemployed_reminded = False

    def _record_unemployed(self, *, off_hours: bool, now: float | None = None) -> None:
        """记录时段内连续未被雇佣；达到阈值后本段只提醒一次。"""
        ec = self.cfg.employed
        if off_hours or not bool(getattr(ec, 'unemployed_reminder', True)):
            self._reset_unemployed_reminder()
            return
        now = time.monotonic() if now is None else now
        if self._unemployed_since is None:
            self._unemployed_since = now
            self._unemployed_reminded = False
            return
        minutes = max(1, int(getattr(ec, 'unemployed_reminder_minutes', 30)))
        if not self._unemployed_reminded and now - self._unemployed_since >= minutes * 60:
            sent = send_unemployed_reminder(minutes)
            self._unemployed_reminded = True
            log(f'被雇佣时段内连续 {minutes} 分钟未被雇佣，已发送提醒'
                if sent else f'被雇佣时段内连续 {minutes} 分钟未被雇佣，提醒未送达')

    def run(self, max_times: int | None = None, max_rounds: int = 1) -> bool:
        """出门检查一次。无论是否检测到被雇佣都返回 True（巡检语义同好友护理：
        返回 False 会被任务队列标记当天不可继续，导致间隔后不再复查）。

        非阻塞：到召回条件（employed.action 策略）就召回；没到就回主页面，
        按 employed.interval_seconds 间隔再来检查，中间调度器可以跑其他任务。
        """
        off_hours_mode = (self.is_employed_off_hours()
                          or self.off_hours_employed_mode_active())
        action = ('50/50（非被雇佣时段）' if off_hours_mode
                  else self.cfg.employed.action)
        log(f'被雇佣检查: 出门查看是否被雇佣中（处理方式: {action}）')
        self.ensure_main_page()
        self.leave_home()
        busy = False
        # 出门后活动面板有几秒加载延迟，多检测几轮再下结论
        for attempt in range(1, BUSY_GATE_ATTEMPTS + 1):
            screen = self.screen()
            if self.see('employed_in', screen):
                self._reset_unemployed_reminder()
                off_hours = self.is_employed_off_hours()
                if off_hours:
                    self.notify_off_hours_employed_once()
                if getattr(self, '_recall_pending', False) or self.employed_recall_ready(
                        screen,
                        off_hours=off_hours or self.off_hours_employed_mode_active()):
                    if getattr(self, '_recall_pending', False):
                        log('上次召回尚未完成，继续重试召回')
                    self._recall_pending = True
                    self._recall_employed()
                    self._recall_pending = False
                else:
                    log('仍在被雇佣中，未到召回时机，回主页面（间隔后再检查）')
                self.ensure_main_page()
                return True
            if any(self.see(sign, screen) for sign in
                   ('school_in', 'work_in', 'adventure_in')):
                busy = True
                break
            if attempt < BUSY_GATE_ATTEMPTS:
                time.sleep(0.5)
        if busy:
            self._recall_pending = False
            self.clear_off_hours_employed_notice()
            log('宠物仍在学习、工作或冒险，暂不发送可被雇佣提醒')
            self._reset_unemployed_reminder()
            self.ensure_main_page()
            return True
        # 同时确认出门地图，避免把未加载完成或异常弹窗当成空闲。
        source = self.dev.hierarchy()
        if not self.see('school', screen, source=source):
            raise RuntimeError('未能确认被雇佣状态或空闲地图，保留召回状态等待重试')
        log('已确认空闲地图，未被雇佣')
        self._recall_pending = False
        self.clear_off_hours_employed_notice()
        self._notify_available_once()
        self._record_unemployed(off_hours=self.is_employed_off_hours())
        self.ensure_main_page()
        return True
