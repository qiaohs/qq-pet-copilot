"""config.yaml 读写（ruamel 往返模式，保留注释和格式），供设置页面使用。"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, LiteralScalarString

from .config import CONFIG_FILE, MAIN_TASK_KEYS, TASK_KEYS
from .time_utils import clock_text, range_text

_yaml = YAML()  # 默认 round-trip，保留注释

# 打工地点可选列表（设置页下拉 + 校验共用，新增地图时在这里加）
WORK_LOCATIONS = ('风铃旅社', '彩虹画室', '迷雾侦探所', '星尘魔法塔',
                  '咕噜厨房', '竹影武馆', '云朵梦舍', '闪耀星屋')

# 任务页与命名方案共用字段清单，新增任务设置同时纳入方案。
TASK_SETTING_FIELDS = [
    ('tasks.order', '任务执行顺序（> 分隔）', 'str'),
    ('tasks.main_order', '主任务顺序（> 分隔）', 'str'),
    ('school.attribute', '属性点课程', ['力量', '智力', '魅力']),
    ('school.times_per_day', '每天学习次数（0 不限）', 'int'),
    ('school.duration_minutes', '学习时长识别失败兜底（分钟）', 'int'),
    ('school.duration_candidates', '学习时长候选（逗号分隔）', 'str'),
    ('school.auto_calcium_milk', '开课时自动喝高钙奶（仅尝试一次）', 'bool'),
    ('schedule.daily_hour_limit', '学习工作时长上限（小时，0 不限）', 'int'),
    ('schedule.encourage_times', '鼓励次数（进行中页面快速点击）', 'int'),
    ('work.location', '打工地点', list(WORK_LOCATIONS)),
    ('work.duration', '打工时长选择', ['10分钟', '45分钟', '2小时']),
    ('work.times_per_day', '每天打工次数（0 不限）', 'int'),
    ('work.auto_americano', '开工时自动喝元气美式（仅尝试一次）', 'bool'),
    ('work.employ_scroll_limit', '雇佣拖动上限', 'int'),
    ('adventure.times_per_day', '每天冒险次数（0 不冒险）', 'int'),
    ('adventure.start_time', '冒险调度时间', 'str'),
    ('adventure.skip_bad_weather', '冒险跳过"天色不对"', 'bool'),
    ('adventure.batch', '单轮冒险次数', 'int'),
    ('adventure.type', '冒险类型', ['附近走走', '诗和远方']),
    ('visit.continuous_target', '踩踩连续运行目标（0 不踩）', 'int'),
    ('visit.exit_complete_count', '踩踩退出后完成阈值（0 禁用）', 'int'),
    ('visit.start_time', '踩踩调度时间', 'str'),
    ('pk.times_per_day', '每天 PK 次数（0 不 PK）', 'int'),
    ('pk.start_time', 'PK 调度时间', 'str'),
    ('pk.friend_name', '仅 PK 这些好友（完整昵称，逗号分隔；留空不 PK）', 'str'),
    ('pk.max_scan_count', 'PK 最大遍历好友数', 'int'),
    ('friend_care.enabled', '启用好友护理', 'bool'),
    ('friend_care.time_range', '好友护理时间段', 'str'),
    ('friend_care.friend_name', '护理好友名称（逗号分隔多个）', 'str'),
    ('friend_care.method', '护理好友方式', ['一键护理', 'ocr检测']),
    ('friend_care.energy_target', '好友喂食目标体力', 'int'),
    ('friend_care.clean_target', '好友洗澡目标清洁', 'int'),
    ('friend_care.post_one_click_care', '护理完成后点击“照顾一下”', 'bool'),
    ('friend_care.max_scan_count', '好友护理最大遍历数', 'int'),
    ('friend_care.interval_seconds', '好友护理调度间隔（秒）', 'int'),
    ('hire_friend.enabled', '雇佣好友开关', 'bool'),
    ('hire_friend.time_range', '雇佣好友时间段', 'str'),
    ('hire_friend.interval_seconds', '雇佣好友调度间隔（秒）', 'int'),
    ('hire_friend.friend_name', '雇佣好友名称（逗号分隔多个）', 'str'),
    ('hire_friend.max_scan_count', '雇佣好友最大遍历数', 'int'),
    ('hire_friend.times_per_day', '雇佣好友次数（0 不雇佣）', 'int'),
    ('friend_navigation.stop_at_non_friend', '遇到非好友时停止遍历', 'bool'),
    ('friend_navigation.min_scan_count', '非好友停止前最少遍历数', 'int'),
    ('lucky_bag.self_enabled', '护理自己时领取福袋', 'bool'),
    ('lucky_bag.friend_enabled', '好友护理时领取福袋', 'bool'),
    ('care.method', '护理方式', ['一键护理', 'ocr检测']),
    ('care.energy_threshold', '体力阈值', 'int'),
    ('care.clean_threshold', '清洁阈值', 'int'),
    ('care.interval_seconds', '护理间隔（秒）', 'int'),
    ('employed.action', '被雇佣后处理', ['等到25/75（小于45min）', '等到25/75', '立刻召回']),
    ('employed.enabled', '被雇佣开关', 'bool'),
    ('employed.time_range', '被雇佣时间段', 'str'),
    ('employed.interval_seconds', '被雇佣检查间隔（秒）', 'int'),
    ('employed.off_hours_recall', '非被雇佣时段按50/50召回并通知', 'bool'),
    ('employed.off_hours_interval_seconds', '非被雇佣时段检查间隔（秒）', 'int'),
    ('employed.unemployed_reminder', '时段内连续未被雇佣提醒', 'bool'),
    ('employed.available_reminder', '进入被雇佣时段空闲时提醒', 'bool'),
    ('employed.unemployed_reminder_minutes', '未被雇佣提醒等待（分钟）', 'int'),
]

# 各配置项默认值：设置页校验不通过时恢复
DEFAULTS = {
    'adb.path': 'resources/scrcpy-win64/adb.exe',
    'adb.device_serial': '',
    'gui.theme': '跟随系统',
    'gui.mirror': True,
    'gui.log_max_lines': 500,
    'gui.shortcut_phrase': '',
    'control.method': 'injectInputEvent',
    'emulator.type': 'auto',
    'emulator.name': '',
    'emulator.path': '',
    'emulator.device_spoof': False,
    'school.attribute': '力量',
    'school.times_per_day': 0,
    'school.duration_minutes': 135,
    'school.duration_candidates': '45,135',
    'school.auto_calcium_milk': False,
    'work.location': '风铃旅社',
    'work.times_per_day': 0,
    'work.auto_americano': False,
    'work.employ_scroll_limit': 5,
    'schedule.coin_threshold': 2000,
    'schedule.daily_hour_limit': 8,
    'schedule.check_interval': 8,
    'schedule.main_page_checks': 1,
    'schedule.ui_wait_multiplier': 1,
    'schedule.back_method': '系统返回',
    'schedule.encourage_times': 10,
    'adventure.times_per_day': 1,
    'adventure.start_time': '08:00',
    'adventure.skip_bad_weather': False,
    'adventure.batch': 12,
    'adventure.type': '附近走走',
    'visit.continuous_target': 950,
    'visit.exit_complete_count': 200,
    'visit.start_time': '00:01',
    'pk.times_per_day': 15,
    'pk.start_time': '00:01',
    'pk.friend_name': '',
    'pk.max_scan_count': 20,
    'friend_care.enabled': False,
    'friend_care.time_range': '14:00-19:30',
    'friend_care.friend_name': '',
    'friend_care.method': 'ocr检测',
    'friend_care.energy_target': 70,
    'friend_care.clean_target': 90,
    'friend_care.post_one_click_care': True,
    'friend_care.max_scan_count': 20,
    'friend_care.interval_seconds': 60,
    'hire_friend.enabled': False,
    'hire_friend.time_range': '19:31-23:59',
    'hire_friend.interval_seconds': 5,
    'hire_friend.friend_name': '',
    'hire_friend.max_scan_count': 20,
    'hire_friend.times_per_day': 8,
    'friend_navigation.stop_at_non_friend': True,
    'friend_navigation.min_scan_count': 10,
    'lucky_bag.self_enabled': True,
    'lucky_bag.friend_enabled': True,
    'runner.engine': 'task_queue',
    'tasks.order': 'care>friend_care>rest1>rest2>school>adventure>hire_friend>visit>pk>work',
    'tasks.main_order': 'school>adventure>hire_friend>work',
    'tasks.failure_interval': 1800,
    'care.energy_threshold': 60,
    'care.clean_threshold': 60,
    'care.method': '一键护理',
    'care.interval_seconds': 60,
    'work.duration': '45分钟',
    'employed.enabled': False,
    'employed.time_range': '19:31-23:59',
    'employed.interval_seconds': 60,
    'employed.off_hours_recall': True,
    'employed.off_hours_interval_seconds': 480,
    'employed.unemployed_reminder': True,
    'employed.available_reminder': True,
    'employed.unemployed_reminder_minutes': 30,
    'employed.action': '等到25/75（小于45min）',
    'recover.emulator_restart_cmd': '',
    'notify.employed_recall': True,
    'notify.critical_errors': True,
    'notify.duplicate_cooldown_minutes': 360,
    'notify.win_toast': True,
    'notify.onepush_config': '',
}


def validate_field(key: str, value):
    """校验单个配置项，返回 (是否通过, 修正后的值)；不通过时给出默认值。"""
    default = DEFAULTS.get(key)
    choices = next((kind for field, _, kind in TASK_SETTING_FIELDS
                    if field == key and isinstance(kind, list)), None)
    if choices is not None and value not in choices:
        return False, default
    if key in ('adventure.start_time', 'visit.start_time', 'pk.start_time'):
        try:
            return True, DoubleQuotedScalarString(clock_text(value))
        except (TypeError, ValueError):
            return False, DoubleQuotedScalarString(str(default))
    if key == 'work.location':
        return (True, value) if value in WORK_LOCATIONS else (False, default)
    if key == 'school.attribute':
        return (True, value) if value in ('力量', '智力', '魅力') else (False, default)
    if key == 'school.duration_minutes':
        try:
            return (True, int(value)) if 1 <= int(value) <= 1440 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key == 'school.duration_candidates':
        import re
        try:
            values = [int(part) for part in re.split(r'[,，;；\s]+', str(value).strip())
                      if part]
            if not values or any(item < 1 or item > 1440 for item in values):
                return False, default
            return True, ','.join(str(item) for item in dict.fromkeys(values))
        except (TypeError, ValueError):
            return False, default
    if key == 'work.duration':
        return (True, value) if value in ('10分钟', '45分钟', '2小时') else (False, default)
    if key == 'adventure.type':
        return (True, value) if value in ('附近走走', '诗和远方') else (False, default)
    if key == 'care.method' or key == 'friend_care.method':
        return (True, value) if value in ('ocr检测', '一键护理') else (False, default)
    if key in ('friend_care.time_range', 'employed.time_range', 'hire_friend.time_range'):
        try:
            return True, DoubleQuotedScalarString(range_text(value))
        except (TypeError, ValueError):
            return False, DoubleQuotedScalarString(str(default))
    if key in ('friend_care.friend_name', 'hire_friend.friend_name', 'pk.friend_name'):
        return True, str(value).strip()
    if key in ('school.auto_calcium_milk', 'work.auto_americano', 'friend_care.enabled',
               'friend_care.post_one_click_care',
               'hire_friend.enabled', 'employed.enabled',
               'employed.off_hours_recall', 'employed.unemployed_reminder',
               'employed.available_reminder',
               'friend_navigation.stop_at_non_friend', 'lucky_bag.self_enabled',
               'lucky_bag.friend_enabled'):
        return (True, value) if isinstance(value, bool) else (False, default)
    if key == 'runner.engine':
        return (True, value) if value in ('task_queue', 'legacy') else (False, default)
    if key == 'control.method':
        return (True, value) if value in ('injectInputEvent', 'minitouch') else (False, default)
    if key == 'gui.theme':
        return (True, value) if value in ('跟随系统', '深色', '浅色') else (False, default)
    if key == 'gui.log_max_lines':
        try:
            return (True, int(value)) if 50 <= int(value) <= 99999 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key == 'emulator.type':
        from .emulator import EMULATOR_TYPES
        return (True, value) if value in ('auto', *EMULATOR_TYPES) else (False, default)
    if key in ('emulator.name', 'emulator.path'):
        return True, str(value).strip()
    if key == 'tasks.order':
        keys = [k.strip() for k in str(value).split('>') if k.strip()]
        if keys and all(k in TASK_KEYS for k in keys):
            return True, '>'.join(keys)
        return False, default
    if key == 'tasks.main_order':
        # 主任务组内优先级：只需要求非空且都是主任务名；没列出的按默认顺序兜底
        keys = [k.strip() for k in str(value).split('>') if k.strip()]
        if keys and all(k in MAIN_TASK_KEYS for k in keys):
            return True, '>'.join(keys)
        return False, default
    if key in ('care.energy_threshold', 'care.clean_threshold',
               'friend_care.energy_target', 'friend_care.clean_target'):
        return (True, value) if 0 <= int(value) <= 100 else (False, default)
    if key in ('friend_care.max_scan_count', 'hire_friend.max_scan_count', 'pk.max_scan_count'):
        try:
            return (True, int(value)) if 1 <= int(value) <= 999 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key == 'friend_navigation.min_scan_count':
        try:
            return (True, int(value)) if 1 <= int(value) <= 999 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key == 'schedule.back_method':
        return (True, value) if value in ('返回图标', '系统返回') else (False, default)
    if key == 'tasks.failure_interval':
        # 失败重试间隔至少 1 秒（0 会变成无间隔连续重试死循环）
        try:
            return (True, value) if int(value) >= 1 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key in ('schedule.check_interval', 'schedule.main_page_checks'):
        # 检查间隔至少 1 秒 / 检测次数至少 1 次（0 会变成无间隔死循环或不设防点 back）
        try:
            return (True, value) if int(value) >= 1 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key == 'schedule.ui_wait_multiplier':
        try:
            return (True, int(value)) if 1 <= int(value) <= 5 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key in ('visit.continuous_target', 'visit.exit_complete_count'):
        try:
            return (True, int(value)) if 0 <= int(value) <= 99999 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key in ('employed.interval_seconds', 'employed.off_hours_interval_seconds',
               'hire_friend.interval_seconds',
               'friend_care.interval_seconds', 'care.interval_seconds'):
        # 调度间隔至少 1 秒（0 会变成无间隔连续调度）
        try:
            return (True, value) if int(value) >= 1 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key == 'employed.unemployed_reminder_minutes':
        try:
            return (True, int(value)) if 1 <= int(value) <= 1440 else (False, default)
        except (TypeError, ValueError):
            return False, default
    if key in ('notify.win_toast', 'notify.employed_recall', 'notify.critical_errors') \
            or key == 'adventure.skip_bad_weather' \
            or key == 'emulator.device_spoof' or key == 'gui.mirror':
        return (True, value) if isinstance(value, bool) else (False, default)
    if key == 'notify.onepush_config':
        # OnePush 推送配置（YAML，支持多行）：留空，或能解析出含 provider 的字典
        text = str(value).strip()
        if not text:
            return True, ''
        try:
            cfg = yaml.safe_load(text)
        except yaml.YAMLError:
            return False, default
        if not (isinstance(cfg, dict) and cfg.get('provider')):
            return False, default
        # 多行用块样式写回（保留换行可读性），单行仍用带引号标量
        if '\n' in text:
            return True, LiteralScalarString(text)
        return True, DoubleQuotedScalarString(text)
    # 其余整数字段（次数/阈值/系数）非负即可，空字符串不允许
    if isinstance(DEFAULTS.get(key), int):
        try:
            return (True, value) if int(value) >= 0 else (False, default)
        except (TypeError, ValueError):
            return False, default
    return True, value


def load_raw():
    """读取 config.yaml 为可修改的映射对象（保留注释）。"""
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return _yaml.load(f) or {}


def save_raw(data) -> None:
    """保留注释和格式，整份写好后原子替换，防止调度器热加载到半份方案。"""
    target = Path(CONFIG_FILE)
    fd, temp = tempfile.mkstemp(prefix=target.name, suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            _yaml.dump(data, f)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def get_value(data, dotted_key: str, default=None):
    """按 'school.attribute' 形式的点路径取值。"""
    cur = data
    for part in dotted_key.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_value(data, dotted_key: str, value) -> None:
    """按点路径写值，中间层级不存在则创建。"""
    parts = dotted_key.split('.')
    cur = data
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
