"""使用临时方案和真实 Qt 点击验证删除流程，不连接手机、不写用户配置。"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

import main
from src.config import Config
from src import schedule_profiles as profiles


class ProfileHarness(QWidget):
    _delete_schedule_profile = main.MainWindow._delete_schedule_profile
    _finish_delete_schedule_profile = main.MainWindow._finish_delete_schedule_profile
    _reload_profile_names = main.MainWindow._reload_profile_names
    _describe_schedule_profile = main.MainWindow._describe_schedule_profile
    _profile_feedback = main.MainWindow._profile_feedback

    def __init__(self):
        super().__init__()
        self._profile_name = main._NoInsertEditableComboBox(self)
        self._profile_status = main.CaptionLabel(self)
        self._profile_delete_dialog = None
        self._profile_name.currentTextChanged.connect(self._describe_schedule_profile)
        self._reload_profile_names()


class ProfileDeleteUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'profiles.json'
        self.values = profiles.capture(Config())
        self.store = {'version': 1, 'active': '学习模式', 'profiles': {
            '学习模式': self.values, '打工模式': copy.deepcopy(self.values)}}
        self.patchers = [patch.object(profiles, 'PROFILE_FILE', self.path),
                         patch.object(profiles, 'capture', return_value=self.values),
                         patch.object(main, 'log')]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        profiles.save_store(self.store)
        self.window = ProfileHarness()
        self.window.show()
        self.addCleanup(self.window.close)
        self.app.processEvents()

    def open_dialog(self):
        self.window._delete_schedule_profile()
        self.app.processEvents()
        dialog = self.window._profile_delete_dialog
        self.assertIsInstance(dialog, main.ScheduleDeleteDialog)
        self.assertTrue(dialog.isVisible())
        return dialog

    def test_delete_returns_immediately_and_timers_keep_running(self):
        original = self.path.read_bytes()
        dialog = self.open_dialog()
        beats = []
        timer = QTimer()
        timer.timeout.connect(lambda: beats.append(1))
        timer.start(5)
        QTest.qWait(40)
        timer.stop()
        self.assertTrue(beats)
        self.assertEqual(self.path.read_bytes(), original)
        QTest.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        saved = profiles.load_store()
        self.assertNotIn('学习模式', saved['profiles'])
        self.assertIn('打工模式', saved['profiles'])
        self.assertNotIn('active', saved)
        self.assertIsNone(self.window._profile_delete_dialog)
        self.assertEqual(self.window._profile_name.count(), 1)

    def test_cancel_escape_and_close_leave_file_unchanged(self):
        original = self.path.read_bytes()
        for action in ('cancel', 'escape', 'close'):
            dialog = self.open_dialog()
            if action == 'cancel':
                QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
            elif action == 'escape':
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                dialog.close()
            self.app.processEvents()
            self.assertIsNone(self.window._profile_delete_dialog)
            self.assertEqual(self.path.read_bytes(), original)

    def test_confirmation_does_not_overwrite_newly_saved_other_profile(self):
        dialog = self.open_dialog()
        changed = profiles.load_store()
        changed['profiles']['新方案'] = copy.deepcopy(self.values)
        profiles.save_store(changed)
        dialog.delete_button.click()
        self.app.processEvents()
        self.assertIn('新方案', profiles.load_store()['profiles'])

    def test_changed_target_requires_fresh_confirmation(self):
        dialog = self.open_dialog()
        changed = profiles.load_store()
        changed['profiles']['学习模式']['work.duration'] = '2小时'
        profiles.save_store(changed)
        dialog.delete_button.click()
        self.app.processEvents()
        self.assertIn('学习模式', profiles.load_store()['profiles'])
        self.assertIn('发生了变化', self.window._profile_status.text())
        self.assertIsNone(self.window._profile_delete_dialog)

    def test_repeated_delete_keeps_single_dialog(self):
        dialog = self.open_dialog()
        self.window._delete_schedule_profile()
        self.assertIs(self.window._profile_delete_dialog, dialog)
        dialog.reject()
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
