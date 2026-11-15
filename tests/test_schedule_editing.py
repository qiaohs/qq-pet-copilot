import copy
import os
from datetime import datetime, time
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QInputMethodEvent, QKeyEvent, QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from qfluentwidgets import Theme, setTheme

import main
from src import schedule_profiles as profiles
from src.config import Config
from src.settings import TASK_SETTING_FIELDS, validate_field
from src.time_edit import TimeInput
from src.time_utils import parse_range, in_clock_range
from scenarios.friend_care import parse_time_range
from scenarios.runner import _parse_range


class CompleteProfileTests(TestCase):
    def test_profile_captures_every_task_field(self):
        cfg = Config()
        cfg.friend_care.friend_name = '好友A'
        cfg.work.auto_americano = True
        cfg.school.auto_calcium_milk = True
        values = profiles.capture(cfg)
        self.assertTrue({key for key, _, _ in TASK_SETTING_FIELDS}.issubset(values))
        self.assertEqual(values['friend_care.friend_name'], '好友A')
        self.assertTrue(values['work.auto_americano'])
        self.assertTrue(values['school.auto_calcium_milk'])

    def test_old_profile_missing_fields_uses_defaults_and_previews_them(self):
        cfg = Config()
        cfg.work.auto_americano = True
        cfg.friend_care.energy_target = 40
        cfg.pk.friend_name = '好友A'
        old = {'tasks.order': cfg.tasks.order, 'work.duration': '2小时'}
        current = profiles.capture(cfg)
        changes = {key: (before, after) for key, before, after in profiles.differences(current, old)}
        self.assertEqual(changes['work.auto_americano'], (True, False))
        self.assertEqual(changes['friend_care.energy_target'], (40, Config().friend_care.energy_target))
        self.assertEqual(changes['pk.friend_name'], ('好友A', ''))
        original = copy.deepcopy(old)
        data = {'gui': {'shortcut_phrase': 'local'}, 'notify': {'onepush_config': 'local'}}
        with patch.object(profiles, 'load_config', return_value=cfg), \
             patch.object(profiles.settings, 'load_raw', return_value=data), \
             patch.object(profiles.settings, 'save_raw'):
            profiles.apply(old, current)
        self.assertEqual(old, original)
        self.assertFalse(data['work']['auto_americano'])
        self.assertEqual(data['gui']['shortcut_phrase'], 'local')
        self.assertEqual(data['notify']['onepush_config'], 'local')

    def test_range_defaults_and_runtime_agree(self):
        value = '08：30-19：45'
        expected = (time(8, 30), time(19, 45, 59))
        self.assertEqual(parse_range(value), expected)
        self.assertEqual(parse_time_range(value), expected)
        self.assertEqual(_parse_range(value, 'test'), expected)
        self.assertEqual(validate_field('employed.time_range', value),
                         (True, '08:30:00-19:45:59'))
        self.assertTrue(in_clock_range(time(19, 45, 59, 900000), *expected))
        self.assertFalse(in_clock_range(time(19, 46), *expected))
        old = profiles.validate({'friend_care.time_range': '00:00-00:00'})
        self.assertEqual(old['friend_care.time_range'], '00:00:00-00:00:00')
        self.assertTrue(main.MainWindow._in_time_range(datetime(2026, 11, 16, 0, 5), '23：30-01：00'))


class ScheduleInputTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_input(self, is_range=False):
        parent = QWidget()
        parent.resize(380, 120)
        layout = QVBoxLayout(parent)
        field = TimeInput(is_range=is_range)
        layout.addWidget(field)
        field.setText('00:00-23:59' if is_range else '00:00')
        parent.show()
        self.app.processEvents()
        self.addCleanup(parent.close)
        return parent, field

    def test_full_selection_digits_skip_separators_and_commit_once(self):
        for ranged, digits, shown, saved in (
                (False, '0830', '08:30', '08:30'),
                (True, '08301945', '08:30-19:45', '08:30:00-19:45:59')):
            parent, field = self.make_input(ranged)
            field.setFocus()
            field.selectAll()
            values = []
            field.valueCommitted.connect(values.append)
            QTest.keyClicks(field, digits)
            self.assertEqual(field.text(), shown)
            self.assertEqual(values, [])
            QTest.keyClick(field, Qt.Key.Key_Return)
            self.assertEqual(values, [saved])
            QTest.keyClick(field, Qt.Key.Key_Return)
            self.assertEqual(values, [saved])
            parent.close()

    def test_chinese_colon_paste_and_ime(self):
        _, field = self.make_input(True)
        field.selectAll()
        QApplication.clipboard().setText('08：30-19：45')
        QTest.keySequence(field, QKeySequence.StandardKey.Paste)
        self.assertEqual(field.text(), '08:30-19:45')
        field.selectAll()
        event = QInputMethodEvent()
        event.setCommitString('０９：１５-２０：４０')
        QApplication.sendEvent(field, event)
        self.assertEqual(field.text(), '09:15-20:40')
        field.selectAll()
        QTest.keyClicks(field, '08')
        QApplication.sendEvent(field, QKeyEvent(QKeyEvent.Type.KeyPress, 0,
                                                Qt.KeyboardModifier.NoModifier, '：'))
        QTest.keyClicks(field, '30-19')
        QApplication.sendEvent(field, QKeyEvent(QKeyEvent.Type.KeyPress, 0,
                                                Qt.KeyboardModifier.NoModifier, '：'))
        QTest.keyClicks(field, '45')
        self.assertEqual(field.text(), '08:30-19:45')

    def test_hover_does_not_focus_or_select_input(self):
        parent, field = self.make_input()
        parent.setFocus()
        field.deselect()
        QTest.mouseMove(field, field.rect().center())
        self.app.processEvents()
        self.assertFalse(field.hasFocus())
        self.assertFalse(field.hasSelectedText())
        values = []
        field.valueCommitted.connect(values.append)
        field.setFocus()
        parent.setFocus()
        self.app.processEvents()
        self.assertEqual(values, [])

    def test_invalid_time_is_kept_for_correction_without_saving(self):
        _, field = self.make_input()
        field.selectAll()
        values = []
        field.valueCommitted.connect(values.append)
        QTest.keyClicks(field, '2560')
        QTest.keyClick(field, Qt.Key.Key_Return)
        self.assertTrue(field.isError())
        self.assertEqual(values, [])
        self.assertEqual(field.text(), '25:60')

    def test_difference_dialog_background_matches_theme(self):
        for theme, dark in ((Theme.DARK, True), (Theme.LIGHT, False)):
            setTheme(theme)
            dialog = main.ScheduleDiffDialog('方案差异', [('work.auto_americano', False, True)])
            dialog.show()
            self.app.processEvents()
            color = dialog.grab().toImage().pixelColor(3, 3)
            self.assertEqual(color.lightness() < 100, dark)
            dialog.close()
