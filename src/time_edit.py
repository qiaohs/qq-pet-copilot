"""支持整段数字输入、中文冒号和粘贴的分钟级时间输入框。"""
import unicodedata

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import LineEdit

from .time_utils import clock_text, display_range, range_text


class TimeInput(LineEdit):
    valueCommitted = pyqtSignal(str)

    def __init__(self, parent=None, *, is_range=False):
        self.is_range = is_range
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setInputMask('00:00-00:00;_' if is_range else '00:00;_')
        self.editingFinished.connect(self._commit)
        self._help_text = ('可全选输入 08301945，自动变为 08:30-19:45；开始秒数为 00，结束为 59'
                           if is_range else '可全选输入 0830，自动变为 08:30；支持中文冒号')
        self.setToolTip(self._help_text)

    def setText(self, value):
        try:
            text = display_range(value) if self.is_range else clock_text(value)
        except (TypeError, ValueError):
            text = str(value)
        super().setText(text)
        self.setModified(False)

    def insert(self, text):
        super().insert(unicodedata.normalize('NFKC', text))

    def paste(self):
        text = QApplication.clipboard().text()
        try:
            text = display_range(text) if self.is_range else clock_text(text)
        except (TypeError, ValueError):
            pass
        self.insert(text)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.text() and unicodedata.normalize('NFKC', event.text()) != event.text():
            self.insert(event.text())
        else:
            super().keyPressEvent(event)

    def inputMethodEvent(self, event):
        if event.commitString():
            event.setCommitString(unicodedata.normalize('NFKC', event.commitString()),
                                  event.replacementStart(), event.replacementLength())
        super().inputMethodEvent(event)

    def wheelEvent(self, event):
        event.ignore()

    def _commit(self):
        if not self.isModified():
            return
        try:
            if not self.hasAcceptableInput():
                raise ValueError('时间未填完整')
            value = range_text(self.text()) if self.is_range else clock_text(self.text())
        except (TypeError, ValueError):
            self.setError(True)
            self.setToolTip('请填写完整且有效的时间，小时为 00–23，分钟为 00–59')
            return
        self.setError(False)
        self.setToolTip(self._help_text)
        self.setText(value)
        self.valueCommitted.emit(value)
