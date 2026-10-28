"""新开课程的一次性喝奶操作；图像不确定时跳过，绝不重试投喂。"""
from __future__ import annotations

import time
from datetime import datetime

import cv2
import numpy as np
from PIL import Image

from src.config import APP_ROOT
from src.notify import send_school_milk_issue
from src.progress import log
from src.scenario import CLICK_INTERVAL


def find_yellow_milk(screen, *, used: bool = False,
                     anchor_y: int | None = None) -> tuple[int, int] | None:
    """在已确认的道具面板内找黄色奶，不依赖选中后的大小或奶盒图案。

    面板底色为深色，黄色高钙奶同时有黄色与浅色包装；蓝色杯没有黄色。
    用连通区域的位置、黄色面积和附近浅色包装排除文字和蓝杯。
    """
    height, width = screen.shape[:2]
    rgb = cv2.resize(screen[:, :, :3], (720, 1440), interpolation=cv2.INTER_AREA)
    anchor = (855 if used else 922) if anchor_y is None else round(anchor_y * 1440 / height)
    x1, y1, x2, y2 = ((245, anchor + 120, 390, anchor + 230) if used
                      else (155, anchor + 73, 690, anchor + 283))
    y1, y2 = max(0, y1), min(1370, y2)
    if y2 <= y1:
        return None
    roi = rgb[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    yellow = cv2.inRange(hsv, (15, 95, 130), (39, 255, 255))
    count, _, stats, centers = cv2.connectedComponentsWithStats(yellow)
    candidates = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < 25 or w < 4 or h < 3:
            continue
        nearby = hsv[max(0, y - 18):min(hsv.shape[0], y + h + 26),
                     max(0, x - 18):min(hsv.shape[1], x + w + 18)]
        white = (nearby[:, :, 1] < 80) & (nearby[:, :, 2] > 170)
        if np.count_nonzero(white) < 20:
            continue
        candidates.append((area, centers[index]))
    if not candidates:
        return None
    _, (x, y) = max(candidates, key=lambda item: item[0])
    return round((x1 + x) * width / 720), round((y1 + y) * height / 1440)


def _report(scen, reason: str, screen=None) -> None:
    """通知和存图失败也只记日志，不能把可选道具故障升级成学习失败。"""
    log(f'高钙奶: {reason}；本节不再尝试')
    path = None
    try:
        screen = scen.screen() if screen is None else screen
        folder = APP_ROOT / 'runs' / 'screenshots'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'school_milk_{datetime.now():%Y%m%d_%H%M%S_%f}.png'
        Image.fromarray(screen).save(target)
        path = str(target)
        log(f'高钙奶异常截图已保存: {target}')
    except Exception as exc:
        log(f'高钙奶异常截图失败: {exc}')
    try:
        send_school_milk_issue(reason, path)
    except Exception as exc:
        log(f'高钙奶通知失败: {exc}')


def drink_milk_once(scen) -> None:
    """仅由 attend_class 的开课入口调用；加号和黄色奶盒各最多点击一次。"""
    if not getattr(scen.cfg.school, 'auto_calcium_milk', False):
        return
    if getattr(scen, '_milk_attempted', False):
        return
    # 点击前就消费本节机会，点击/截图/OCR 失败也不允许再次投喂。
    scen._milk_attempted = True
    panel_open = False
    try:
        screen = scen.screen()
        learning = scen.see('school_in', screen)
        if not learning:
            raise RuntimeError('开课后未确认正在学习，跳过喝奶')
        if find_yellow_milk(screen, used=True, anchor_y=learning[1]):
            log('本节已显示黄色高钙奶，跳过喝奶')
            return
        hint = scen.see('school_milk_add_hint', screen)
        if not hint:
            raise RuntimeError('未确认学习道具入口提示，跳过喝奶')
        height, width = screen.shape[:2]
        # 学习标题跟随整个面板移动；相对标题定位加号，避免使用旧面板的绝对高度。
        plus_y = learning[1] + round(height * 170 / 1440)
        if hint[0] < width * 0.5 or abs(hint[1] - plus_y) > height * 0.07:
            raise RuntimeError('学习标题与道具提示位置不一致，跳过喝奶')
        log(f'学习道具入口: 标题 y={learning[1]}，加号 y={plus_y}')
        scen.click(round(width * 316 / 720), plus_y)
        time.sleep(CLICK_INTERVAL)
        screen = scen.screen()
        title = scen.see('school_milk_title', screen)
        panel_open = bool(title)
        if not (panel_open and scen.see('school_milk_panel', screen)):
            raise RuntimeError('点击加号后未确认高钙奶道具面板')
        milk = find_yellow_milk(screen, anchor_y=title[1])
        if milk is None:
            raise RuntimeError('未找到可用的黄色高钙奶，可能已用完或图像未识别')
        # 库存数字优先从黄色奶盒附近取；不读右边蓝色杯的数字。
        from src.ocr import ocr_texts
        height, width = screen.shape[:2]
        mx, my = milk
        top = max(0, my - round(height * 0.07))
        bottom = min(height, my + round(height * 0.015))
        left = max(0, mx - round(width * 0.03))
        right = min(width, mx + round(width * 0.19))
        counts = [t.replace(' ', '') for t, *_ in ocr_texts(screen[top:bottom, left:right])]
        if counts and all(t in ('0', 'x0', 'X0', '×0') for t in counts):
            raise RuntimeError('黄色高钙奶库存为 0，请补充')
        log('开课后使用黄色高钙奶（仅点击一次）')
        scen.click(*milk)
        time.sleep(CLICK_INTERVAL)
        screen = scen.screen()
        learning = scen.see('school_in', screen)
        if learning and find_yellow_milk(screen, used=True, anchor_y=learning[1]):
            panel_open = False
            log('课堂道具栏已显示黄色高钙奶，结束本次喝奶流程')
        else:
            _report(scen, '点击黄色高钙奶后未确认使用成功，继续学习', screen)
    except Exception as exc:
        _report(scen, str(exc))
    finally:
        if panel_open:
            # 只收起道具面板；不用系统返回，避免退出课堂或宠物。
            try:
                screen = scen.screen()
                title = scen.see('school_milk_title', screen)
                # “使用道具”也包含“道具”，只有高钙奶说明仍在时才能认作道具面板。
                if title and scen.see('school_milk_panel', screen):
                    height, width = screen.shape[:2]
                    scen.click(round(width * 658 / 720), title[1])
                    time.sleep(CLICK_INTERVAL)
            except Exception as exc:
                log(f'收起高钙奶道具面板失败: {exc}；本节不再尝试喝奶')
