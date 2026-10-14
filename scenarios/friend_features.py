"""好友页公共识别：好友边界与福袋状态。

福袋是 canvas 图片，没有稳定文字。用袋口和爪印两处灰度纹理联合匹配，
要求相对位置一致；系绳袋口为未领取，敞口袋沿为已领取。
背景颜色和动态金色光晕均不参与判断，低置信度时跳过领取。
"""
from __future__ import annotations

import time
import base64
import json
import zlib
from functools import lru_cache

import cv2
import numpy as np

from src.ocr import ocr_texts
from src.config import resource_path
from src.progress import log
from src.scenario import CLICK_INTERVAL

LUCKY_BAG_UNOPENED = '未领取'
LUCKY_BAG_CLAIMED = '已领取'
LUCKY_BAG_ABSENT = '无福袋'
LUCKY_BAG_UNKNOWN = '识别失败'

_BAG_MATCH_MIN = 0.78
_BAG_MATCH_MARGIN = 0.08


@lru_cache(maxsize=1)
def _bag_templates() -> tuple:
    """只保存袋口/爪印小特征，不携带完整截图、账号或背景。"""
    path = resource_path('assets/lucky_bag_features.json')
    raw = json.loads(path.read_text(encoding='utf-8'))
    return tuple((entry['state'], entry['offset'], tuple(
        np.frombuffer(zlib.decompress(base64.b64decode(part['data'])),
                      dtype=np.uint8).reshape(part['shape'])
        for part in entry['parts'])) for entry in raw['templates'])


def _bag_match_scores(screen: np.ndarray) -> dict[str, float]:
    """袋口和爪印都要匹配，且相对位置相符；较弱一处决定最终置信度。"""
    height, width = screen.shape[:2]
    # 只处理左下小区域，统一到 720x1440 的半尺寸坐标，兼容截图分辨率变化。
    roi = screen[round(height * 850 / 1440):round(height * 1045 / 1440),
                 round(width * 25 / 720):round(width * 200 / 720), :3]
    gray = cv2.cvtColor(cv2.resize(roi, (88, 98), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_RGB2GRAY)
    scores = {'unopened': 0.0, 'claimed': 0.0}
    for state, offset, (mouth, paw) in _bag_templates():
        for scale in (0.9, 1.0, 1.1):
            neck = cv2.resize(mouth, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_LINEAR)
            foot = cv2.resize(paw, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_LINEAR)
            matches = cv2.matchTemplate(gray, neck, cv2.TM_CCOEFF_NORMED)
            _, neck_score, _, (x, y) = cv2.minMaxLoc(matches)
            if neck_score < 0.6:
                continue
            # 只在袋口下方的预期位置找爪印，避免分别匹配到两个背景装饰。
            px, py = x + round(offset[0] * scale), y + round(offset[1] * scale)
            h, w = foot.shape
            x1, y1 = max(0, px - 3), max(0, py - 3)
            patch = gray[y1:min(gray.shape[0], py + h + 3),
                         x1:min(gray.shape[1], px + w + 3)]
            if patch.shape[0] < h or patch.shape[1] < w:
                continue
            _, paw_score, _, _ = cv2.minMaxLoc(
                cv2.matchTemplate(patch, foot, cv2.TM_CCOEFF_NORMED))
            scores[state] = max(scores[state], min(neck_score, paw_score))
    return scores


def lucky_bag_state(screen: np.ndarray) -> str:
    """区分当前页面左下福袋的未领取/已领取/不存在状态。"""
    if screen is None or screen.ndim != 3 or screen.shape[0] < 100 or screen.shape[1] < 100:
        return LUCKY_BAG_UNKNOWN
    try:
        scores = _bag_match_scores(screen)
    except (OSError, ValueError, KeyError, zlib.error, cv2.error) as exc:
        log(f'福袋特征加载/匹配失败，跳过领取: {exc}')
        return LUCKY_BAG_UNKNOWN
    best = max(scores, key=scores.get)
    other = 'claimed' if best == 'unopened' else 'unopened'
    if scores[best] >= _BAG_MATCH_MIN and scores[best] - scores[other] >= _BAG_MATCH_MARGIN:
        return LUCKY_BAG_UNOPENED if best == 'unopened' else LUCKY_BAG_CLAIMED
    return LUCKY_BAG_UNKNOWN if scores[best] >= 0.6 else LUCKY_BAG_ABSENT


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
                if state == LUCKY_BAG_UNKNOWN:
                    log(f'{owner}福袋点击后画面不确定，停止点击，留待下轮确认')
                else:
                    log(f'{owner}福袋领取完成，当前状态: {state}')
                return state
            log(f'{owner}福袋点击后仍显示未领取，重试 ({attempt}/2)')
        log(f'{owner}福袋两次点击后仍未领取，留待下轮护理重试')
        return LUCKY_BAG_UNOPENED
    except Exception as exc:
        log(f'{owner}福袋检测/领取失败，跳过且不影响护理: {exc}')
        return LUCKY_BAG_UNKNOWN
