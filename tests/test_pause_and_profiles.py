import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scenarios.care import CareScenario
from scenarios.employed import EmployedScenario
from scenarios.runner import TaskQueueRunner, _QueueTask
from src.config import Config
from src.runtime_control import PauseController
from src.scenario import DeviceScenario
from src import schedule_profiles as profiles


class PauseTests(unittest.TestCase):
    def test_pause_blocks_same_task_and_excludes_timeout(self):
        events = []
        entered = threading.Event()
        done = threading.Event()
        def emit(state):
            events.append(state)
            if state['state'] == 'paused':
                entered.set()
        control = PauseController(emit)
        control.before_pause = Mock()
        control.after_resume = Mock()
        calls = []
        control.request(True)
        def task():
            calls.append('started')
            start = control.monotonic()
            control.sleep(0.03)
            calls.append(control.monotonic() - start)
            done.set()
        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            time.sleep(0.08)
            self.assertFalse(done.is_set())
        finally:
            control.request(False)
            thread.join(1)
        self.assertTrue(done.is_set())
        self.assertEqual(calls[0], 'started')
        self.assertLess(calls[1], 0.075)
        self.assertEqual([e['state'] for e in events], ['paused', 'running'])
        control.before_pause.assert_called_once()
        control.after_resume.assert_called_once()

    def test_auto_resume_without_gui_timer(self):
        events = []
        with patch('src.runtime_control.AUTO_RESUME_SECONDS', 0.03):
            control = PauseController(events.append)
            control.request(True)
            control.checkpoint()
        self.assertTrue(events[-1]['automatic'])
        self.assertFalse(control._requested)


class ProfileTests(unittest.TestCase):
    def test_capture_excludes_private_and_normalizes_old_clock(self):
        cfg = Config()
        cfg.tasks.visit.daily_times = [970]
        values = profiles.capture(cfg)
        self.assertEqual(values['tasks.visit.daily_times'], ['16:10'])
        profiles.validate(values)
        self.assertFalse(any('friend_name' in key or key.startswith(('gui.', 'adb.', 'notify.'))
                             for key in values))

    def test_apply_changes_only_schedule_and_rechecks_preview(self):
        current = profiles.capture(Config())
        target = copy.deepcopy(current)
        target['work.duration'] = '2小时'
        data = {'gui': {'shortcut_phrase': 'private'},
                'notify': {'onepush_config': 'private'},
                'friend_care': {'friend_name': 'private'},
                'work': {'duration': '45分钟'}}
        with patch.object(profiles, 'capture', return_value=current), \
             patch.object(profiles.settings, 'load_raw', return_value=data), \
             patch.object(profiles.settings, 'save_raw') as save:
            profiles.apply(target, current)
        self.assertEqual(data['work']['duration'], '2小时')
        self.assertEqual(data['gui']['shortcut_phrase'], 'private')
        self.assertEqual(data['friend_care']['friend_name'], 'private')
        save.assert_called_once_with(data)
        with patch.object(profiles, 'capture', return_value=target), \
             patch.object(profiles.settings, 'save_raw') as save:
            with self.assertRaises(ValueError):
                profiles.apply(target, current)
            save.assert_not_called()

    def test_store_roundtrip_and_bad_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profiles.json'
            store = {'version': 1, 'profiles': {'均衡': profiles.capture(Config())}}
            profiles.save_store(store, path)
            self.assertEqual(profiles.load_store(path), store)
            path.write_text('broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                profiles.load_store(path)
            self.assertEqual(path.read_text(encoding='utf-8'), 'broken')

    def test_config_atomic_save_retains_comments_order_and_private_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.yaml'
            path.write_text('# personal settings\ngui:\n  shortcut_phrase: private\n'
                            'work:\n  duration: 45分钟 # keep comment\n', encoding='utf-8')
            with patch.object(profiles.settings, 'CONFIG_FILE', path):
                data = profiles.settings.load_raw()
                profiles.settings.set_value(data, 'work.duration', '2小时')
                profiles.settings.save_raw(data)
            result = path.read_text(encoding='utf-8')
            self.assertIn('shortcut_phrase: private', result)
            self.assertIn('# keep comment', result)
            self.assertLess(result.index('gui:'), result.index('work:'))
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_reject_private_or_invalid_profile_fields(self):
        for values in ({'gui.shortcut_phrase': 'secret'},
                       {'tasks.school.enabled': 'yes'},
                       {'tasks.school.enabled_time_range': 'bad'},
                       {'tasks.school.daily_times': ['99:99']}):
            with self.assertRaises(ValueError):
                profiles.validate(values)

    def test_switch_reopens_quota_flags_preserving_pending_and_backoff(self):
        runner = TaskQueueRunner.__new__(TaskQueueRunner)
        runner._last_cfg = Config()
        task = _QueueTask('work')
        tasks, order = {'work': task}, []
        runner._apply_tasks_config(tasks, order)
        task.dead = True
        until = task.next_at
        runner._last_cfg.work.times_per_day = 100
        runner._apply_tasks_config(tasks, order)
        self.assertFalse(task.dead)
        self.assertEqual(task.next_at, until)


class NavigationTests(unittest.TestCase):
    def test_feed_reclicks_entry_after_missing_panel(self):
        scen = CareScenario.__new__(CareScenario)
        scen.dev = SimpleNamespace(hierarchy=Mock(return_value='fresh'))
        scen.wait_attempts = lambda n: 4
        scen.see = Mock(side_effect=lambda name, **_: (600, 630, 1) if name == 'feed' else None)
        scen._care_item = Mock(side_effect=[None, None, None, (360, 900, 1), (360, 900, 1)])
        scen.click = Mock()
        scen.snapshot = Mock(return_value=('image', 'source'))
        scen.read_status = Mock(return_value={'体力': 100})
        scen.cache_care_items = Mock()
        scen.energy_threshold = 90
        with patch('scenarios.care.time.sleep'):
            scen.feed()
        self.assertEqual(scen.click.call_args_list[0].args, (600, 630))
        self.assertEqual(scen.click.call_args_list[1].args, (600, 630))
        self.assertEqual(scen.click.call_args_list[-1].args, (360, 900))

    def test_closed_feed_panel_never_triggers_purchase(self):
        scen = CareScenario.__new__(CareScenario)
        scen.dev = SimpleNamespace(hierarchy=Mock(return_value='fresh'))
        scen.wait_attempts = lambda _: 4
        scen.see = Mock(side_effect=lambda name, **_: (600, 630, 1) if name == 'feed' else None)
        scen._care_item = Mock(return_value=None)
        scen.click = Mock()
        scen._exchange_food = Mock()
        with patch('scenarios.care.time.sleep'), self.assertRaises(RuntimeError):
            scen.feed()
        scen._exchange_food.assert_not_called()

    def test_settlement_waits_for_animation_then_counts_once(self):
        scen = EmployedScenario.__new__(EmployedScenario)
        scen.dev = SimpleNamespace(hierarchy=Mock(return_value='report'), d=Mock())
        scen.wait_attempts = lambda _: 6
        scen._detect_settlement = Mock(side_effect=['school', 'school', 'school', None])
        scen.snapshot = Mock(return_value=('image', 'tree'))
        scen.settlement_completed = Mock()
        scen.ensure_main_page = Mock()
        scen.leave_home = Mock()
        with patch('src.scenario.time.sleep'):
            self.assertTrue(scen._settle_finished_activity('report_image'))
        scen.dev.d.press.assert_called_once_with('back')
        scen.settlement_completed.assert_called_once_with('school', 'report_image', 'report')

    def test_stuck_settlement_retries_back_but_does_not_count(self):
        scen = EmployedScenario.__new__(EmployedScenario)
        scen.dev = SimpleNamespace(hierarchy=Mock(return_value='report'), d=Mock())
        scen.wait_attempts = lambda _: 4
        scen._detect_settlement = Mock(return_value='school')
        scen.snapshot = Mock(return_value=('image', 'tree'))
        scen.dismiss_system_update = Mock(return_value=False)
        scen.settlement_completed = Mock()
        with patch('src.scenario.time.sleep'), self.assertRaises(RuntimeError):
            scen._settle_finished_activity('report_image')
        self.assertEqual(scen.dev.d.press.call_count, 2)
        scen.settlement_completed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
