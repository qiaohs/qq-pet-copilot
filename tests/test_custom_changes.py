from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import tempfile

from scenarios.friend_care import FriendCareScenario
from scenarios.hire_friend import FriendHireScenario
from main import ScrcpyContainer
from src.scenario import TaskDeferred
from scenarios.care import CareScenario
from scenarios.runner import TaskQueueRunner, _QueueTask
from src import progress, progress_store
from src.coins import read_coins_from_ocr
from src.config import TaskItemConfig


class CustomChangesTest(TestCase):
    def test_scrcpy_fit_uses_native_client_pixels(self):
        fake = SimpleNamespace(
            _hwnd=123,
            _aspect=(9, 16),
            _native_client_size=lambda: (900, 1800),
        )
        with patch('main.win32gui.MoveWindow') as move:
            ScrcpyContainer._fit(fake)
        move.assert_called_once_with(123, 0, 100, 900, 1600, True)

    def test_rest_window_supports_normal_and_cross_midnight_ranges(self):
        runner = TaskQueueRunner.__new__(TaskQueueRunner)
        rest1 = _QueueTask('rest1')
        rest1.cfg = TaskItemConfig(enabled=True, enabled_time_range='19:46-19:58')
        rest2 = _QueueTask('rest2')
        rest2.cfg = TaskItemConfig(enabled=False, enabled_time_range='23:50-00:10')
        tasks = {'rest1': rest1, 'rest2': rest2}

        active = runner._active_rest(tasks, ['rest1', 'rest2'],
                                     datetime(2026, 9, 27, 19, 50))
        self.assertEqual(active[0].key, 'rest1')
        self.assertEqual(active[1], datetime(2026, 9, 27, 19, 58))
        self.assertIsNone(runner._active_rest(
            tasks, ['rest1', 'rest2'], datetime(2026, 9, 27, 19, 58)))

        rest1.cfg.enabled = False
        rest2.cfg.enabled = True
        active = runner._active_rest(tasks, ['rest1', 'rest2'],
                                     datetime(2026, 9, 27, 23, 55))
        self.assertEqual(active[1], datetime(2026, 9, 28, 0, 10))

    def test_care_runs_before_rest_and_rest_blocks_employed_check(self):
        runner = TaskQueueRunner.__new__(TaskQueueRunner)
        runner._active_rest_key = None
        runner._rest_until = None
        runner._current_task = None
        runner._pending_finish_first = lambda: None
        runner._eligible = lambda task, now: task.cfg.enabled
        care = _QueueTask('care')
        friend = _QueueTask('friend_care')
        rest = _QueueTask('rest1')
        rest.cfg = TaskItemConfig(enabled=True, enabled_time_range='00:00-00:00')
        tasks = {'care': care, 'friend_care': friend, 'rest1': rest}
        order = ['care', 'friend_care', 'rest1']
        executed = []
        runner._execute = lambda task, *_args: executed.append(task.key)
        runner._task_due = lambda key, *_args: key == 'care'
        employed_checks = []
        runner.employed_due = lambda: employed_checks.append(True) or False

        self.assertTrue(runner._run_first_due(tasks, order))
        self.assertEqual(executed, ['care'])
        self.assertEqual(employed_checks, [])

        runner._task_due = lambda *_args: False
        self.assertFalse(runner._run_first_due(tasks, order))
        self.assertEqual(runner._current_task, '休息1')
        self.assertEqual(employed_checks, [])

    def test_coin_reader_uses_rightmost_top_bar_number(self):
        results = [
            ('14', 198, 218, 0.9),
            ('354', 388, 218, 0.9),
            ('1.1w', 521, 220, 0.9),
        ]
        self.assertEqual(read_coins_from_ocr(results), 11000)

    def test_status_reader_reclicks_once_when_panel_never_opened(self):
        scen = CareScenario.__new__(CareScenario)
        reads = iter(({}, {}, {'体力': 96, '清洁': 74, '金币': 11000}))
        scen.snapshot = lambda: (object(), object())

        def read_status(_screen, _source):
            status = next(reads)
            scen._status_panel_visible = '体力' in status
            return status

        scen.read_status = read_status
        clicks = []
        scen.toggle_status = lambda source=None: clicks.append(source)
        with patch('scenarios.care.time.sleep'):
            status = scen.read_status_ready()
        self.assertEqual(status['体力'], 96)
        self.assertEqual(len(clicks), 1)

    def test_advanced_school_old_30_minutes_is_repaired_to_150(self):
        with tempfile.TemporaryDirectory() as tmp:
            school_file = Path(tmp) / 'school.json'
            work_file = Path(tmp) / 'work.json'
            progress_store.write_raw(school_file, {
                'date': progress_store.today_str(),
                'learned': 1,
                'school': '高级学园',
                'study_secs': 30 * 60,
            })
            with patch.object(progress, 'SCHOOL_PROGRESS_FILE', school_file), \
                    patch.object(progress, 'WORK_PROGRESS_FILE', work_file):
                study_secs, _ = progress.load_durations()
            self.assertEqual(study_secs, 150 * 60)

    def test_friend_care_uses_list_order_and_enters_once(self):
        scen = FriendCareScenario.__new__(FriendCareScenario)
        scen.cfg = SimpleNamespace(friend_care=SimpleNamespace(
            enabled=True,
            friend_name='qq1,qq2',
            method='ocr检测',
            energy_target=70,
            clean_target=90,
            time_range='00:00-00:00',
        ))
        state = {'index': 0, 'begins': 0, 'closes': 0}
        friends = ['好友 qq2', '好友 其他人', '好友 qq1']
        cared = []
        scen.ensure_main_page = lambda: None
        scen.wait_attempts = lambda value: 1
        scen.begin_friend_walk = lambda: state.__setitem__('begins', state['begins'] + 1)
        scen.current_friend = lambda: (friends[state['index']], [])

        def next_friend(_visible):
            state['index'] += 1
            return state['index'] < len(friends)

        scen.next_friend = next_friend
        scen.close = lambda: state.__setitem__('closes', state['closes'] + 1)
        scen.care_friend = lambda: cared.append(friends[state['index']]) or True

        self.assertTrue(scen.run())
        self.assertEqual(cared, ['好友 qq2', '好友 qq1'])
        self.assertEqual(state['begins'], 1)
        self.assertEqual(state['closes'], 1)

    def test_hire_uses_first_available_configured_friend_in_list_order(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.cfg = SimpleNamespace(hire_friend=SimpleNamespace(
            enabled=True,
            friend_name='qq1,qq2',
            times_per_day=1,
        ))
        scen.defer_wait = True
        state = {'index': 0, 'begins': 0}
        friends = ['好友 qq2', '好友 qq1']
        selected = []
        scen.ensure_main_page = lambda: None
        scen.detect_busy_remaining = lambda: None
        scen.begin_friend_walk = lambda: state.__setitem__('begins', state['begins'] + 1)
        scen.current_friend = lambda: (friends[state['index']], [])
        scen.next_friend = lambda _visible: False
        scen.wait_hire_ready = lambda: selected.append(friends[state['index']])
        scen._enter_work_panel = lambda: None
        scen._hire_and_work = lambda panel_ready=False: None

        with patch('scenarios.hire_friend.load_progress',
                   return_value=(progress_store.today_str(), 0, {})), \
                patch('scenarios.hire_friend.log_history'):
            self.assertTrue(scen.run())
        self.assertEqual(selected, ['好友 qq2'])
        self.assertEqual(state['begins'], 1)

    def test_friend_care_stops_after_configured_scan_limit(self):
        scen = FriendCareScenario.__new__(FriendCareScenario)
        scen.cfg = SimpleNamespace(friend_care=SimpleNamespace(
            enabled=True,
            friend_name='不存在的好友',
            method='ocr检测',
            energy_target=40,
            clean_target=80,
            max_scan_count=3,
            time_range='00:00-00:00',
        ))
        state = {'index': 0, 'closes': 0}
        friends = [f'好友 路人{i}' for i in range(10)]
        scen.ensure_main_page = lambda: None
        scen.wait_attempts = lambda value: 1
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])

        def next_friend(_visible):
            state['index'] += 1
            return state['index'] < len(friends)

        scen.next_friend = next_friend
        scen.close = lambda: state.__setitem__('closes', state['closes'] + 1)
        scen.care_friend = lambda: self.fail('不应护理非目标好友')

        self.assertTrue(scen.run())
        self.assertEqual(state['index'], 2)
        self.assertEqual(state['closes'], 1)

    def test_hire_stops_after_configured_scan_limit(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.cfg = SimpleNamespace(hire_friend=SimpleNamespace(
            enabled=True,
            friend_name='不存在的好友',
            max_scan_count=3,
            times_per_day=1,
        ))
        scen.defer_wait = True
        state = {'index': 0, 'closes': 0}
        friends = [f'好友 路人{i}' for i in range(10)]
        scen.ensure_main_page = lambda: None
        scen.detect_busy_remaining = lambda: None
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])

        def next_friend(_visible):
            state['index'] += 1
            return state['index'] < len(friends)

        scen.next_friend = next_friend
        scen.close = lambda: state.__setitem__('closes', state['closes'] + 1)

        with patch('scenarios.hire_friend.load_progress',
                   return_value=(progress_store.today_str(), 0, {})), \
                patch('scenarios.hire_friend.log_history'):
            with self.assertRaises(TaskDeferred):
                scen.run()
        self.assertEqual(state['index'], 2)
        self.assertEqual(state['closes'], 1)
