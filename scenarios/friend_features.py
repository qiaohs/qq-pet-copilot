"""好友页公共识别：好友边界与福袋状态。

福袋是 canvas 图片，控件树和 OCR 都没有稳定文字。样本中自己/好友使用同一套
素材和位置：未领取为金棕袋体并带黄色动态光晕，领取后为白色袋体且无光。
因此只在左下固定比例区域做 HSV 连通域判断，不受宠物和大部分背景变化影响。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from src.ocr import ocr_texts
from src.progress import log
from src.scenario import CLICK_INTERVAL

LUCKY_BAG_UNOPENED = '未领取'
LUCKY_BAG_CLAIMED = '已领取'
LUCKY_BAG_ABSENT = '无福袋'
LUCKY_BAG_UNKNOWN = '识别失败'

# 阈值基于用户提供的 720x1440 多背景样本，运行时按像素面积等比缩放。
_REFERENCE_AREA = 720 * 1440
_GLOW_COMPONENT_AREA = 600
_GLOW_COMPONENT_HEIGHT = 70
_BAG_ORANGE_MIN_AREA = 400
_BAG_ORANGE_MAX_AREA = 4000


def _has_bag_glow(mask: np.ndarray, area_scale: float, height_scale: float) -> bool:
    """金色区域既要够大，也要有福袋光晕的纵向跨度。

    只看面积会把暖色地板、发光宠物窝识别成福袋；这些背景通常是横向扁块，
    而用户样本里的福袋动画至少形成约 70px 高的纵向连通区域。
    """
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        area = stats[index, cv2.CC_STAT_AREA]
        height = stats[index, cv2.CC_STAT_HEIGHT]
        if (area >= _GLOW_COMPONENT_AREA * area_scale
                and height >= _GLOW_COMPONENT_HEIGHT * height_scale):
            return True
    return False


def lucky_bag_state(screen: np.ndarray) -> str:
    """区分当前页面左下福袋的未领取/已领取/不存在状态。"""
    if screen is None or screen.ndim != 3 or screen.shape[0] < 100 or screen.shape[1] < 100:
        return LUCKY_BAG_UNKNOWN
    height, width = screen.shape[:2]
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    area_scale = width * height / _REFERENCE_AREA
    height_scale = height / 1440

    # 未领取福袋的动态金色光晕；取宽松区域，动画各帧的光点位置变化也能命中。
    x1, x2 = int(width * 0.02), int(width * 0.29)
    y1, y2 = int(height * 0.57), int(height * 0.73)
    glow_roi = hsv[y1:y2, x1:x2]
    glow = cv2.inRange(glow_roi, (15, 70, 170), (40, 255, 255))
    if _has_bag_glow(glow, area_scale, height_scale):
        return LUCKY_BAG_UNOPENED

    # 无光时再找袋口/系绳处稳定的橙色连通块，用于区分白色已领取袋与无福袋。
    x1, x2 = int(width * 0.04), int(width * 0.27)
    y1, y2 = int(height * 0.59), int(height * 0.72)
    orange_roi = hsv[y1:y2, x1:x2]
    orange = cv2.inRange(orange_roi, (3, 100, 90), (20, 255, 255))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(orange, 8)
    for index in range(1, count):
        component_area = stats[index, cv2.CC_STAT_AREA] / area_scale
        cx = (centroids[index, 0] + x1) / width
        cy = (centroids[index, 1] + y1) / height
        if (_BAG_ORANGE_MIN_AREA <= component_area <= _BAG_ORANGE_MAX_AREA
                and 0.11 <= cx <= 0.18 and 0.61 <= cy <= 0.65):
            return LUCKY_BAG_CLAIMED
    return LUCKY_BAG_ABSENT


def is_non_friend_page(screen: np.ndarray) -> bool:
    """用顶部大字“加好友”判断当前访问对象不是好友。"""
    if screen is None or screen.ndim != 3:
        return False
    try:
        top = screen[:max(1, int(screen.shape[0] * 0.20))]
        results = ocr_texts(top)
        texts = [str(text).replace(' ', '') for text, *_ in results]
        detected = any('加好友' in text for text in texts)
        if detected:
            log('检测到顶部“加好友”，当前对象不是好友')
        return detected
    except Exception as exc:
        log(f'非好友识别失败，继续使用最大遍历数兜底: {exc}')
        return False


def claim_lucky_bag(scenario, owner: str, screen: np.ndarray | None = None) -> str:
    """检测并领取福袋；任何识别/点击问题只记日志，不中断护理流程。

    领取后无论是否出现详情弹窗，都点击最左侧空白处。弹窗存在时该点位于阴影区，
    不存在时只是点击无控件的背景；全程不用 Android 返回键，避免关闭宠物页面。
    """
    try:
        current = screen if screen is not None else scenario.screen()
        state = lucky_bag_state(current)
        log(f'{owner}福袋状态: {state}')
        if state != LUCKY_BAG_UNOPENED:
            return state

        for attempt in (1, 2):
            height, width = current.shape[:2]
            bag_x, bag_y = round(width * 0.155), round(height * 0.66)
            log(f'检测到{owner}未领取福袋，点击领取 ({bag_x}, {bag_y})')
            scenario.click(bag_x, bag_y)
            time.sleep(CLICK_INTERVAL)

            # 详情弹窗有深浅两套主题，但两者左右都留有阴影空白；固定点阴影关闭，
            # 不依赖弹窗 OCR，也不会误用会关闭宠物页的返回键。
            shadow_x, shadow_y = max(2, round(width * 0.025)), round(height * 0.48)
            # 连点两轮之间留半秒：兼容领取响应稍慢、弹窗在第一次空白点击后才出现。
            for _ in range(2):
                scenario.click(shadow_x, shadow_y)
                time.sleep(CLICK_INTERVAL / 2)
            current = scenario.screen()
            state = lucky_bag_state(current)
            if state != LUCKY_BAG_UNOPENED:
                log(f'{owner}福袋领取完成，当前状态: {state}')
                return state
            log(f'{owner}福袋点击后仍显示未领取，重试 ({attempt}/2)')
        log(f'{owner}福袋两次点击后仍未领取，留待下轮护理重试')
        return LUCKY_BAG_UNOPENED
    except Exception as exc:
        log(f'{owner}福袋检测/领取失败，跳过且不影响护理: {exc}')
        return LUCKY_BAG_UNKNOWN
