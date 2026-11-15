"""本地命名调度方案，覆盖任务页设置及调度表格。"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .config import APP_ROOT, TASK_KEYS, Config, TasksConfig, load_config
from . import settings
from .time_utils import clock_text, range_text

PROFILE_FILE = APP_ROOT / 'runs' / 'schedule_profiles.json'
BACKUP_NAME = '切换前（自动备份）'
ALLOWED_KEYS = {
    *(f'tasks.{key}' for key in ('order', 'main_order', 'failure_interval')),
    *(f'tasks.{task}.{key}' for task in TASK_KEYS
      for key in asdict(getattr(TasksConfig(), task))),
    *(key for key, _, _ in settings.TASK_SETTING_FIELDS),
    'schedule.coin_threshold',  # 兼容原有方案保存范围
}


def capture(config=None) -> dict:
    cfg = config or load_config()
    result = {}
    for key in sorted(ALLOWED_KEYS):
        value = cfg
        for part in key.split('.'):
            value = getattr(value, part)
        result[key] = copy.deepcopy(value)
    for key, value in list(result.items()):
        if key.endswith('.daily_times'):
            result[key] = [clock_text(t) for t in value or []]
        elif key.endswith('.start_time'):
            result[key] = clock_text(value)
        elif key.endswith(('.time_range', '.enabled_time_range')):
            result[key] = range_text(value, legacy_equal=True)
    return result


def validate(values: dict) -> dict:
    if not isinstance(values, dict) or not values or set(values) - ALLOWED_KEYS:
        raise ValueError('方案包含无效或非调度字段，请重新保存方案')
    # 每次按当前字段清单取默认值，旧方案及未来新增字段都能完整恢复。
    result = copy.deepcopy(capture(Config()))
    for key, value in values.items():
        if key.startswith('tasks.') and key.count('.') == 2:
            field = key.rsplit('.', 1)[1]
            if field == 'enabled':
                ok = isinstance(value, bool)
            elif field == 'trigger':
                ok = value in ('interval', 'daily')
            elif field == 'daily_times':
                try:
                    ok = isinstance(value, list)
                    value = [clock_text(t) for t in value] if ok else value
                except (TypeError, ValueError):
                    ok = False
            elif field == 'enabled_time_range':
                try:
                    value = range_text(value, legacy_equal=True)
                    ok = True
                except (TypeError, ValueError):
                    ok = False
            else:
                ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        elif key.endswith('.time_range'):
            try:
                value = range_text(value, legacy_equal=True)
                ok = True
            except (TypeError, ValueError):
                ok = False
        else:
            ok, value = settings.validate_field(key, value)
        if not ok:
            raise ValueError(f'方案中的 {key} 值无效')
        result[key] = copy.deepcopy(value)
    return result


def differences(current: dict, target: dict) -> list[tuple]:
    target = validate(target)
    return [(key, current.get(key), value) for key, value in target.items()
            if current.get(key) != value]


def load_store(path: Path | None = None) -> dict:
    path = path or PROFILE_FILE
    if not path.exists():
        return {'version': 1, 'profiles': {}}
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get('profiles'), dict):
        raise ValueError('调度方案文件格式无效，原文件已保留')
    return data


def save_store(data: dict, path: Path | None = None) -> None:
    path = path or PROFILE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def apply(values: dict, expected_current: dict) -> None:
    """用户确认差异后重新读取配置，只替换白名单字段；保留期间人工修改。"""
    values = validate(values)
    current = capture()
    if current != expected_current:
        raise ValueError('调度设置在预览期间发生了变化，请重新预览后应用')
    data = settings.load_raw()
    for key, _, value in differences(current, values):
        settings.set_value(data, key, value)
    settings.save_raw(data)
