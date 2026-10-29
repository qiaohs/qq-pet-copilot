from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

from scenarios.runner import Runner, ScenarioFailed
from src.scenario import DeviceScenario
from src import recover


class SystemUpdateTest(TestCase):
    def scenario(self, frames):
        scen = DeviceScenario.__new__(DeviceScenario)
        scen.dev = SimpleNamespace(hierarchy=Mock(side_effect=frames))
        scen.click = Mock()
        hits = {
            'update': {'system_software_update': (360, 700, 1),
                       'system_update_later': (360, 1265, 1)},
            'wlan': {'system_wlan_download': (360, 1100, 1),
                     'system_dialog_cancel': (211, 1260, 1)},
            'unrelated': {'system_dialog_cancel': (111, 222, 1)},
        }
        scen.see = lambda name, _screen=None, source=None: hits.get(source, {}).get(name)
        return scen

    def test_two_dialogs_are_cleared_as_one_action_even_if_second_is_delayed(self):
        scen = self.scenario(['waiting', 'wlan', 'clear'])
        with patch('src.scenario.time.sleep') as sleep:
            self.assertTrue(scen.dismiss_system_update(source='update'))
        self.assertEqual(scen.click.call_args_list,
                         [call(360, 1265), call(211, 1260)])
        self.assertEqual(sleep.call_args_list[:2], [call(1.0), call(1.0)])

    def test_second_dialog_can_appear_independently(self):
        scen = self.scenario(['clear'])
        with patch('src.scenario.time.sleep'):
            self.assertTrue(scen.dismiss_system_update(source='wlan'))
        scen.click.assert_called_once_with(211, 1260)

    def test_first_dialog_can_take_a_moment_to_disappear(self):
        scen = self.scenario(['update', 'wlan', 'clear'])
        with patch('src.scenario.time.sleep'):
            self.assertTrue(scen.dismiss_system_update(source='update'))
        self.assertEqual(scen.click.call_args_list, [call(360, 1265), call(211, 1260)])

    def test_title_without_safe_button_does_not_click_anything(self):
        scen = self.scenario([])
        scen.see = lambda name, _screen=None, source=None: (
            (360, 700, 1) if name == 'system_software_update' else None)
        with self.assertRaisesRegex(RuntimeError, '未找到'):
            scen.dismiss_system_update(source='update')
        scen.click.assert_not_called()

    def test_unrelated_cancel_is_never_clicked(self):
        scen = self.scenario([])
        self.assertFalse(scen.dismiss_system_update(source='unrelated'))
        scen.click.assert_not_called()

    def test_stuck_dialog_is_not_reported_as_cleared(self):
        scen = self.scenario(['wlan'])
        with patch('src.scenario.time.sleep'), self.assertRaisesRegex(RuntimeError, '尚未完全关闭'):
            scen.dismiss_system_update(source='wlan')

    def test_task_exception_clears_dialogs_before_retry_without_restarting(self):
        runner = Runner.__new__(Runner)
        scen = SimpleNamespace(dismiss_system_update=Mock(return_value=True))
        runner._run_round = Mock(side_effect=[RuntimeError('上课状态未识别'), True])
        runner.recover = Mock()
        self.assertTrue(runner.run_one(scen, '学习'))
        scen.dismiss_system_update.assert_called_once()
        self.assertEqual(runner._run_round.call_count, 2)
        runner.recover.assert_not_called()

    def test_recall_clears_dialogs_but_keeps_queue_retry_instead_of_immediate_recall(self):
        runner = Runner.__new__(Runner)
        scen = SimpleNamespace(dismiss_system_update=Mock(return_value=True))
        runner._run_round = Mock(side_effect=RuntimeError('召回状态未识别'))
        runner._capture_failure_image = Mock()
        with self.assertRaises(ScenarioFailed):
            runner.run_one(scen, '被雇佣检查', fatal=False)
        scen.dismiss_system_update.assert_called_once()
        runner._run_round.assert_called_once()

    def test_loop_recovery_handles_popup_before_recovery_limit_and_restart(self):
        runner = Runner.__new__(Runner)
        runner.school = SimpleNamespace(dismiss_system_update=Mock(return_value=True))
        # 不设置设备/恢复计数：弹窗清理成功应直接返回，不触发重启链路。
        with patch('scenarios.runner.reenter_pet') as restart:
            self.assertTrue(runner.recover())
        restart.assert_not_called()

    def test_recovery_wait_clears_popup_before_accepting_background_main_page(self):
        dev = SimpleNamespace(d=Mock(return_value=SimpleNamespace(exists=True)))
        with patch('src.recover._clear_update_during_recovery', side_effect=[True, False]) as clear:
            self.assertTrue(recover._wait_main_page(dev))
        self.assertEqual(clear.call_count, 2)
        dev.d.assert_called_once()
