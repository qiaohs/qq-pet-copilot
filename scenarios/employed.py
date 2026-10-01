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

from src.progress import log
from src.scenario import BUSY_GATE_ATTEMPTS, DeviceScenario


class EmployedScenario(DeviceScenario):
    """被雇佣检查：出门看一眼是否被雇佣中，是则按配置策略召回。"""

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
        # 出门后活动面板有几秒加载延迟，多检测几轮再下结论
        for attempt in range(1, BUSY_GATE_ATTEMPTS + 1):
            screen = self.screen()
            if self.see('employed_in', screen):
                off_hours = self.is_employed_off_hours()
                if off_hours:
                    self.notify_off_hours_employed_once()
                if self.employed_recall_ready(
                        screen,
                        off_hours=off_hours or self.off_hours_employed_mode_active()):
                    self._recall_employed()
                else:
                    log('仍在被雇佣中，未到召回时机，回主页面（间隔后再检查）')
                self.ensure_main_page()
                return True
            if attempt < BUSY_GATE_ATTEMPTS:
                time.sleep(0.5)
        log('未被雇佣')
        self.clear_off_hours_employed_notice()
        self.ensure_main_page()
        return True
