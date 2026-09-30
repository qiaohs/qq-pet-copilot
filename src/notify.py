"""关键事件通知：召回成功和需要人工介入的致命异常。

渠道由 config.yaml 的 notify 段统一配置：
- Windows Toast：notify.win_toast
- OnePush：notify.onepush_config，支持 Bark / PushPlus / Server酱 / SMTP /
  Telegram / 自定义 webhook 等。Bark 示例：
  ``{provider: bark, key: 你的Key}``

只有真正需要用户知情的事件才调用本模块。重复致命异常在首次成功
送达后进入冷却，状态存在 runs/notify_state.json，程序重启也不会刷屏。
通知失败只记日志，绝不影响自动化主流程。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from .config import APP_ROOT, NotifyConfig, load_config
from .progress import log

ALERT_TITLE = '[QQ宠物助手] 需要查看'
RECALL_TITLE = '[QQ宠物助手] 被雇佣召回完成'
TEST_TITLE = '[QQ宠物助手] 通知测试'
# Bark 通知专用图标；不影响 Windows Toast 的应用图标。
BARK_ICON_URL = (
    'https://raw.githubusercontent.com/qiaohs/qq-pet-copilot/main/'
    'assets/bark_icon.png'
)
_STATE_FILE = APP_ROOT / 'runs' / 'notify_state.json'
_STATE_LOCK = threading.Lock()


def _load_notify_config() -> NotifyConfig:
    try:
        return load_config().notify
    except Exception as e:
        # 配置坏了也要尽量把硬故障报出去：用内置默认值继续。
        log(f'通知: 读取配置失败（{e}），按默认配置发送')
        return NotifyConfig()


def send_alert(reason: str, image_path: str | None = None,
               event_key: str | None = None) -> bool:
    """发送需要人工介入的致命异常。

    event_key 用于对会反复重试的同类异常去重；只有至少一个渠道
    成功送达才记入冷却，发送失败后下次仍会尝试。
    """
    cfg = _load_notify_config()
    if not bool(getattr(cfg, 'critical_errors', True)):
        log('致命异常通知已关闭，仅记录日志')
        return False
    cooldown = max(0, int(getattr(cfg, 'duplicate_cooldown_minutes', 360) or 0))
    return _send_notification(
        cfg, ALERT_TITLE, reason, image_path,
        event_key=event_key, cooldown_seconds=cooldown * 60,
    )


def send_employed_recall(action: str) -> bool:
    """被雇佣宠物由程序成功召回后发送；每次召回都是独立事件，不去重。"""
    cfg = _load_notify_config()
    if not bool(getattr(cfg, 'employed_recall', True)):
        log('被雇佣召回通知已关闭')
        return False
    action = str(action or '按配置策略')
    return _send_notification(
        cfg, RECALL_TITLE,
        f'宠物已按“{action}”由程序成功召回，并完成被雇佣结算。',
    )


def send_test_notification(reason: str) -> bool:
    """测试通知渠道：不受事件开关和去重限制。"""
    return _send_notification(_load_notify_config(), TEST_TITLE, reason)


def _send_notification(cfg: NotifyConfig, title: str, reason: str,
                       image_path: str | None = None,
                       event_key: str | None = None,
                       cooldown_seconds: int = 0) -> bool:
    """向所有已配置渠道发送；任一渠道成功即算送达。"""
    try:
        if event_key and cooldown_seconds > 0:
            remaining = _cooldown_remaining(event_key, cooldown_seconds)
            if remaining > 0:
                log(f'通知: 同类异常在冷却中，本次不重复推送'
                    f'（约 {max(1, int(remaining // 60))} 分钟后可再推送）')
                return False
        sent = False
        if cfg.win_toast:
            sent = _send_windows_toast(title, reason, image_path) or sent
        if str(cfg.onepush_config).strip():
            sent = _send_onepush(
                str(cfg.onepush_config), title, reason, image_path) or sent
        if sent and event_key and cooldown_seconds > 0:
            _mark_sent(event_key)
        if not sent:
            log('通知: 未发送成功（未配置渠道或发送失败，详见上方日志）')
        return sent
    except Exception as e:
        # 通知本身绝不能再把调度器弄崩。
        log(f'通知: 发送过程异常: {e}')
        return False


def _read_state() -> dict[str, float]:
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding='utf-8'))
        return {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _cooldown_remaining(event_key: str, cooldown_seconds: int) -> float:
    with _STATE_LOCK:
        last = _read_state().get(event_key, 0.0)
    return max(0.0, last + cooldown_seconds - time.time())


def _mark_sent(event_key: str) -> None:
    """持久化最后成功时间；临时文件带 PID，避免多进程抢同一 .tmp。"""
    with _STATE_LOCK:
        state = _read_state()
        state[event_key] = time.time()
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(f'{_STATE_FILE}.tmp.{os.getpid()}')
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, _STATE_FILE)
        except OSError as e:
            log(f'通知: 保存去重状态失败（{e}）')


def _send_windows_toast(title: str, reason: str,
                        image_path: str | None = None) -> bool:
    """发送 Windows Toast 通知。"""
    if not sys.platform.startswith('win'):
        log('通知: 非 Windows 平台，跳过 Toast')
        return False
    try:
        from winotify import Notification
    except ImportError:
        log('通知: 未安装 winotify，跳过 Windows Toast')
        return False
    except Exception as e:
        log(f'通知: winotify 导入失败: {e}，跳过 Windows Toast')
        return False
    icon = str(image_path or '')
    if not icon or not os.path.exists(icon):
        icon = ''
    try:
        toast = Notification(
            app_id='QQPetCopilot', title=title, msg=str(reason), duration='long',
            **({'icon': icon} if icon else {}),
        )
        toast.show()
        log('通知: Windows Toast 推送成功')
        return True
    except Exception as e:
        log(f'通知: Windows Toast 发送失败: {e}')
        return False


def _send_onepush(config_text: str, title: str, reason: str,
                  image_path: str | None = None) -> bool:
    """发送 OnePush 通知。config_text 必须是含 provider 的 YAML。"""
    import yaml

    try:
        cfg = yaml.safe_load(config_text.strip())
    except yaml.YAMLError as e:
        log(f'通知: OnePush 配置 YAML 解析失败: {e}')
        return False
    if not isinstance(cfg, dict):
        log('通知: OnePush 配置不是字典，跳过推送')
        return False
    cfg = dict(cfg)
    provider = str(cfg.pop('provider', '') or '').strip()
    if not provider:
        log('通知: OnePush 未配置 provider，跳过推送')
        return False
    try:
        from onepush import get_notifier
        from onepush.providers.custom import Custom
    except ImportError:
        log('通知: 未安装 onepush，跳过 OnePush 推送')
        return False
    except Exception as e:
        log(f'通知: onepush 导入失败: {e}，跳过 OnePush 推送')
        return False
    try:
        notifier = get_notifier(provider)
        payload: dict = dict(cfg)
        if provider.casefold() == 'bark' and not str(payload.get('icon', '')).strip():
            # Bark 的 icon 是通知参数，不使用桌面应用图标；保留用户手动配置的 icon。
            payload['icon'] = BARK_ICON_URL
        payload['title'] = title
        payload['content'] = str(reason)
        if image_path and os.path.exists(image_path):
            payload['image_path'] = image_path
        if isinstance(notifier, Custom):
            # 自定义 webhook：默认 JSON POST，title/content 固定塞进 data。
            if str(payload.get('method', 'post')).lower() == 'post':
                payload['datatype'] = 'json'
            data = payload.get('data')
            if not isinstance(data, dict):
                data = {}
            data['title'] = payload['title']
            data['content'] = payload['content']
            payload['data'] = data
        response = notifier.notify(**payload)
        status_code = int(getattr(response, 'status_code', 200) or 200)
        if status_code != 200:
            log(f'通知: OnePush 推送失败，状态码={status_code}')
            return False
        log(f'通知: OnePush 推送成功（{provider}）')
        return True
    except Exception as e:
        detail = str(e).strip() or repr(e)
        log(f'通知: OnePush 推送失败（{provider}）: '
            f'{type(e).__name__}: {detail}')
        return False
