"""刚开工时使用一次元气美式，异常交给通知并继续打工。"""
from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np
from PIL import Image

from src.config import APP_ROOT
from src.notify import send_work_coffee_issue
from src.ocr import ocr_texts
from src.progress import log
from src.runtime_control import clock as time
from src.scenario import CLICK_INTERVAL
from scenarios.school_milk import read_milk_usage as read_drink_usage


def find_americano(screen, *, anchor_y: int, used: bool = False) -> tuple[int, int] | None:
    """在已确认的道具区域找红棕色饮料和浅色杯盖/爪印，兼容选中前后的大小。"""
    height, width = screen.shape[:2]
    rgb = cv2.resize(screen[:, :, :3], (720, 1440), interpolation=cv2.INTER_AREA)
    anchor = round(anchor_y * 1440 / height)
    left, top, right, bottom = ((245, anchor + 120, 390, anchor + 230) if used
                                else (155, anchor + 73, 690, anchor + 283))
    top, bottom = max(0, top), min(1370, bottom)
    if bottom <= top:
        return None
    hsv = cv2.cvtColor(rgb[top:bottom, left:right], cv2.COLOR_RGB2HSV)
    brown = cv2.inRange(hsv, (0, 95, 55), (24, 255, 255))
    count, _, stats, centers = cv2.connectedComponentsWithStats(brown)
    candidates = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < 35 or w < 4 or h < 5:
            continue
        nearby = hsv[max(0, y - 20):min(hsv.shape[0], y + h + 20),
                     max(0, x - 18):min(hsv.shape[1], x + w + 18)]
        pale = (nearby[:, :, 1] < 90) & (nearby[:, :, 2] > 170)
        if np.count_nonzero(pale) >= 20:
            candidates.append((area, centers[index]))
    if not candidates:
        return None
    _, (x, y) = max(candidates, key=lambda item: item[0])
    return round((left + x) * width / 720), round((top + y) * height / 1440)


def _report(scen, reason: str, screen=None) -> None:
    log(f'元气美式: {reason}；本次打工不再尝试')
    try:
        scen.dismiss_system_update()
    except Exception as exc:
        log(f'饮料异常后检查系统弹窗失败: {exc}')
    path = None
    try:
        screen = scen.screen() if screen is None else screen
        folder = APP_ROOT / 'runs' / 'screenshots'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'work_coffee_{datetime.now():%Y%m%d_%H%M%S_%f}.png'
        Image.fromarray(screen).save(target)
        path = str(target)
        log(f'元气美式异常截图已保存: {target}')
    except Exception as exc:
        log(f'元气美式异常截图失败: {exc}')
    try:
        send_work_coffee_issue(reason, path)
    except Exception as exc:
        log(f'元气美式通知失败: {exc}')


def drink_americano_once(scen) -> None:
    """只从实际点击开工后的入口调用，加号和饮料各最多点击一次。"""
    if not getattr(scen.cfg.work, 'auto_americano', False):
        return
    if getattr(scen, '_coffee_attempted', False):
        return
    scen._coffee_attempted = True
    panel_open = False
    try:
        screen = scen.screen()
        working = scen.see('work_in', screen)
        if not working:
            raise RuntimeError('开工后未确认正在打工，跳过饮料')
        if find_americano(screen, anchor_y=working[1], used=True):
            log('本次打工道具栏已显示元气美式，结束喝饮料流程')
            return
        hint = scen.see('work_coffee_add_hint', screen)
        height, width = screen.shape[:2]
        plus_y = working[1] + round(height * 170 / 1440)
        if not hint or hint[0] < width * 0.5 or abs(hint[1] - plus_y) > height * 0.07:
            raise RuntimeError('未确认打工道具入口')
        scen.click(round(width * 316 / 720), plus_y)
        time.sleep(CLICK_INTERVAL)
        screen = scen.screen()
        title = scen.see('work_coffee_title', screen)
        panel_open = bool(title and abs(title[0] - screen.shape[1] / 2) <= screen.shape[1] * 0.1)
        if not (panel_open and scen.see('work_coffee_panel', screen)):
            raise RuntimeError('点击加号后未确认元气美式道具面板')
        if read_drink_usage(screen):
            log('道具面板已显示本次喝饮料记录，结束喝饮料流程')
            return
        coffee = find_americano(screen, anchor_y=title[1])
        if coffee is None:
            raise RuntimeError('未找到可用的元气美式，可能已用完或图像未识别')
        height, width = screen.shape[:2]
        x, y = coffee
        stock_region = screen[max(0, y - round(height * 0.07)):min(height, y + round(height * 0.015)),
                              max(0, x - round(width * 0.03)):min(width, x + round(width * 0.19))]
        counts = [text.replace(' ', '') for text, *_ in ocr_texts(stock_region)]
        if counts and all(text in ('0', 'x0', 'X0', '×0') for text in counts):
            raise RuntimeError('元气美式库存为 0，请补充')
        log('开工后使用元气美式（仅点击一次）')
        scen.click(*coffee)
        time.sleep(CLICK_INTERVAL)
        screen = scen.screen()
        usage = read_drink_usage(screen)
        if usage:
            log(f'元气美式使用成功：已喝 {usage[0]}/{usage[1]} 杯')
        else:
            working = scen.see('work_in', screen)
            if working and find_americano(screen, anchor_y=working[1], used=True):
                panel_open = False
                log('打工道具栏已显示元气美式，结束喝饮料流程')
            else:
                _report(scen, '点击后未确认使用成功，继续打工', screen)
    except Exception as exc:
        _report(scen, str(exc))
    finally:
        if panel_open:
            try:
                screen = scen.screen()
                title = scen.see('work_coffee_title', screen)
                if title and abs(title[0] - screen.shape[1] / 2) <= screen.shape[1] * 0.1:
                    height, width = screen.shape[:2]
                    # 标题中心下方约 20px 是右上关闭按钮，随面板高度移动。
                    scen.click(round(width * 658 / 720), title[1] + round(height * 20 / 1440))
                    time.sleep(CLICK_INTERVAL)
            except Exception as exc:
                log(f'收起元气美式道具面板失败: {exc}')
                try:
                    scen.dismiss_system_update()
                except Exception as update_exc:
                    log(f'收起饮料窗口异常后检查系统弹窗失败: {update_exc}')
