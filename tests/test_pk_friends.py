from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from scenarios.pk import PKScenario


class PkFriendsTest(TestCase):
    def make_scenario(self, friends, names='qq1，qq2', limit=20):
        scen = PKScenario.__new__(PKScenario)
        scen.cfg = SimpleNamespace(
            pk=SimpleNamespace(friend_name=names, max_scan_count=limit),
            friend_navigation=SimpleNamespace(stop_at_non_friend=True, min_scan_count=10))
        state = {'index': 0}
        scen.begin_friend_walk = Mock()
        scen.current_friend = lambda: (friends[state['index']], [])
        scen.screen = lambda: state['index']
        scen.leave_result_page = Mock()
        scen.next_friend = lambda _visible=None: (
            state.__setitem__('index', state['index'] + 1)
            or state['index'] < len(friends))
        challenged = []
        scen.pk_friend = lambda _max, _day, done, _history: (
            challenged.append(friends[state['index']]) or done + 3)
        return scen, state, challenged

    def test_only_named_friends_in_list_order_and_no_partial_name_match(self):
        scen, state, challenged = self.make_scenario(
            ['好友 qq10', '好友 qq2', '好友 路人', '好友 qq1', '好友 其他'])
        with patch('scenarios.pk.is_non_friend_page', return_value=False):
            done = scen._pk_all(15, '2026-10-28', 0, {})
        self.assertEqual(done, 6)
        self.assertEqual(challenged, ['好友 qq2', '好友 qq1'])
        self.assertEqual(state['index'], 3)
        scen.begin_friend_walk.assert_called_once()

    def test_missing_target_stops_at_scan_limit(self):
        scen, state, challenged = self.make_scenario(
            ['好友 qq1', '好友 路人', '好友 qq2'], limit=2)
        with patch('scenarios.pk.is_non_friend_page', return_value=False):
            self.assertEqual(scen._pk_all(15, '2026-10-28', 0, {}), 3)
        self.assertEqual(challenged, ['好友 qq1'])
        self.assertEqual(state['index'], 1)

    def test_non_friend_even_with_configured_name_is_never_challenged(self):
        friends = [f'好友 非好友{i}' for i in range(12)]
        scen, state, challenged = self.make_scenario(friends, names='非好友0')
        with patch('scenarios.pk.is_non_friend_page', return_value=True):
            self.assertEqual(scen._pk_all(15, '2026-10-28', 0, {}), 0)
        self.assertEqual(challenged, [])
        self.assertEqual(state['index'], 9)

    def test_empty_list_does_not_visit_or_prepare_care(self):
        scen, _, challenged = self.make_scenario(['好友 qq1'], names=' ， ')
        scen.times_per_day = 15
        scen._prepare_stats = Mock()
        self.assertFalse(scen.run())
        scen.begin_friend_walk.assert_not_called()
        scen._prepare_stats.assert_not_called()
        self.assertEqual(challenged, [])

    def test_failures_still_close_friend_page(self):
        scen, _, _ = self.make_scenario(['好友 qq1'])
        scen.times_per_day = 15
        scen.ensure_main_page = Mock()
        scen._prepare_stats = Mock()
        scen._pk_all = Mock(side_effect=RuntimeError('网络异常'))
        scen.close = Mock()
        with patch('scenarios.pk.load_progress', return_value=('2026-10-28', 0, {})), \
                patch('scenarios.pk.log_history'), self.assertRaisesRegex(RuntimeError, '网络异常'):
            scen.run()
        scen.close.assert_called_once()
        self.assertEqual(scen.ensure_main_page.call_count, 2)
