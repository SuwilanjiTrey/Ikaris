"""
numbers.py  —  NumberedCodeEditor  +  MarkdownContainer  +  FindBar
Drop-in replacement.

Changes vs previous version:
  1. Tab key handling — always inserts real spaces (TAB_WIDTH spaces), never \\t
  2. Multi-line indent / dedent — Tab shifts selected lines right, Shift+Tab left
  3. FindBar — an inline VS Code-style find/replace bar that lives below the tab
     strip.  Call FindBar.show_find() / show_replace() to open it.
     It persists across tab switches because it lives at the editor_container
     level, not inside individual tabs.
"""

import os
import re as _re
from PyQt5.QtWidgets import (
    QPlainTextEdit, QWidget, QTextEdit, QPushButton,
    QLabel, QHBoxLayout, QVBoxLayout, QScrollArea,
    QSizePolicy, QToolTip, QLineEdit, QCheckBox,
)
from PyQt5.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal, QTimer, QUrl
from PyQt5.QtGui import (
    QPainter, QTextFormat, QColor, QFont,
    QTextCursor, QPixmap, QKeySequence,
)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

try:
    import markdown as md_lib
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LINE_BG_COLOR         = QColor(30,  30,  30,  80)
LINE_NUM_AREA_BG      = QColor(30,  30,  30,  120)
LINE_NUM_COLOR        = "#0091E7"
ERROR_GUTTER_COLOR    = QColor(255, 83,  112, 200)
WARNING_GUTTER_COLOR  = QColor(255, 203, 107, 200)

TAB_WIDTH = 4   # spaces per indent level — change here to affect everything


# ---------------------------------------------------------------------------
# Inline Find/Replace Bar  (goes between tab strip and editor area)
# ---------------------------------------------------------------------------
_BAR_STYLE = """
QWidget#findBar {
    background: #1e1e1e;
    border-bottom: 1px solid #3a3a3a;
}
QLineEdit {
    background: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 3px 7px;
    font-size: 12px;
    min-width: 180px;
}
QLineEdit:focus { border-color: #0091E7; }
QLineEdit#noMatch { border-color: #cc4444; background: #3a1a1a; }
QPushButton {
    background: #2d2d2d;
    color: #cccccc;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 11px;
    min-width: 28px;
}
QPushButton:hover  { background: #3a3a3a; color: #fff; }
QPushButton:pressed { background: #0091E7; border-color: #0091E7; color: #fff; }
QCheckBox { color: #888; font-size: 11px; spacing: 4px; }
QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid #555;
                       border-radius: 3px; background: #2d2d2d; }
QCheckBox::indicator:checked { background: #0091E7; border-color: #0091E7; }
QLabel#matchCount { color: #666; font-size: 11px; min-width: 60px; }
"""


class FindBar(QWidget):
    """
    Inline find/replace bar — sits between the QTabWidget and the editor
    area in editor_container.  It operates on whichever NumberedCodeEditor
    (or MarkdownContainer) is currently active in the QTabWidget.

    Usage:
        self.find_bar = FindBar(self.current_file_tabs)
        layout.addWidget(self.find_bar)   # add AFTER the tab widget
        self.find_bar.hide()

        # wire shortcuts in CodeEditor.setup_shortcuts:
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self.find_bar.show_find)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(
            self.find_bar.show_replace)
        QShortcut(QKeySequence("Escape"), self).activated.connect(
            self.find_bar.close_bar)
    """

    def __init__(self, tab_widget, parent=None):
        super().__init__(parent)
        self.setObjectName("findBar")
        self._tabs      = tab_widget
        self._last_pos  = 0   # remembered cursor position across tab switches

        self.setStyleSheet(_BAR_STYLE)
        self.setFixedHeight(40)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(6)

        # ── Find input ────────────────────────────────────────────────
        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("Find…")
        self._find_input.textChanged.connect(self._on_find_changed)
        self._find_input.returnPressed.connect(self.find_next)

        self._match_label = QLabel("", objectName="matchCount")

        self._btn_prev = QPushButton("↑")
        self._btn_prev.setToolTip("Previous match  (Shift+Enter)")
        self._btn_prev.clicked.connect(self.find_prev)

        self._btn_next = QPushButton("↓")
        self._btn_next.setToolTip("Next match  (Enter / F3)")
        self._btn_next.clicked.connect(self.find_next)

        self._chk_case = QCheckBox("Aa")
        self._chk_case.setToolTip("Case sensitive")
        self._chk_case.stateChanged.connect(self._on_find_changed)

        self._chk_word = QCheckBox("W")
        self._chk_word.setToolTip("Whole words only")
        self._chk_word.stateChanged.connect(self._on_find_changed)

        self._chk_regex = QCheckBox(".*")
        self._chk_regex.setToolTip("Regular expression")
        self._chk_regex.stateChanged.connect(self._on_find_changed)

        # ── Replace input ─────────────────────────────────────────────
        self._sep = QLabel("|")
        self._sep.setStyleSheet("color:#444; margin: 0 2px;")

        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("Replace…")
        self._replace_input.returnPressed.connect(self.replace_next)

        self._btn_replace     = QPushButton("Replace")
        self._btn_replace_all = QPushButton("All")
        self._btn_replace_all.setToolTip("Replace all")
        self._btn_replace.clicked.connect(self.replace_next)
        self._btn_replace_all.clicked.connect(self.replace_all)

        # ── Close ─────────────────────────────────────────────────────
        btn_close = QPushButton("✕")
        btn_close.setToolTip("Close  (Esc)")
        btn_close.setFixedWidth(24)
        btn_close.clicked.connect(self.close_bar)

        # ── Assemble ──────────────────────────────────────────────────
        root.addWidget(self._find_input)
        root.addWidget(self._btn_prev)
        root.addWidget(self._btn_next)
        root.addWidget(self._match_label)
        root.addWidget(self._chk_case)
        root.addWidget(self._chk_word)
        root.addWidget(self._chk_regex)
        root.addWidget(self._sep)
        root.addWidget(self._replace_input)
        root.addWidget(self._btn_replace)
        root.addWidget(self._btn_replace_all)
        root.addStretch()
        root.addWidget(btn_close)

        self._show_replace_widgets(False)

    # ── public ────────────────────────────────────────────────────────

    def show_find(self):
        self._show_replace_widgets(False)
        self.setVisible(True)
        self._find_input.setFocus()
        self._find_input.selectAll()
        self._on_find_changed()

    def show_replace(self):
        self._show_replace_widgets(True)
        self.setVisible(True)
        self._find_input.setFocus()
        self._find_input.selectAll()
        self._on_find_changed()

    def close_bar(self):
        self.setVisible(False)
        # Return focus to the active editor
        ed = self._active_editor()
        if ed:
            ed.setFocus()

    # ── find ──────────────────────────────────────────────────────────

    def find_next(self):
        self._do_find(forward=True)

    def find_prev(self):
        self._do_find(forward=False)

    def _on_find_changed(self):
        """Highlight all matches and update the count label."""
        ed = self._active_editor()
        if not ed:
            self._match_label.setText("")
            return

        term = self._find_input.text()
        if not term:
            ed.setExtraSelections([])
            self._match_label.setText("")
            self._find_input.setObjectName("")
            self._find_input.setStyleSheet("")
            return

        flags = self._flags()
        # Count occurrences
        count = self._count_matches(ed, term)
        self._match_label.setText(f"{count} match{'es' if count != 1 else ''}")

        no_match = count == 0
        self._find_input.setObjectName("noMatch" if no_match else "")
        # Re-apply stylesheet to pick up QLineEdit#noMatch rule
        self._find_input.style().unpolish(self._find_input)
        self._find_input.style().polish(self._find_input)

        # Highlight all in the document using extra selections
        self._highlight_all(ed, term)

    def _do_find(self, forward: bool):
        ed = self._active_editor()
        if not ed:
            return
        term = self._find_input.text()
        if not term:
            return

        flags = self._qt_flags(forward)
        found = ed.find(term, flags)
        if not found:
            # Wrap
            cur = ed.textCursor()
            cur.movePosition(
                QTextCursor.Start if forward else QTextCursor.End
            )
            ed.setTextCursor(cur)
            ed.find(term, flags)

    # ── replace ───────────────────────────────────────────────────────

    def replace_next(self):
        ed = self._active_editor()
        if not ed:
            return
        cur = ed.textCursor()
        if cur.hasSelection():
            sel = cur.selectedText()
            term = self._find_input.text()
            if self._matches(sel, term):
                cur.insertText(self._replace_input.text())
        self.find_next()

    def replace_all(self):
        ed = self._active_editor()
        if not ed:
            return
        term    = self._find_input.text()
        rep     = self._replace_input.text()
        if not term:
            return

        cur = ed.textCursor()
        cur.beginEditBlock()
        cur.movePosition(QTextCursor.Start)
        ed.setTextCursor(cur)
        count = 0
        flags = self._qt_flags(forward=True)
        while ed.find(term, flags):
            ed.textCursor().insertText(rep)
            count += 1
        cur.endEditBlock()
        self._match_label.setText(f"Replaced {count}")

    # ── helpers ───────────────────────────────────────────────────────

    def _active_editor(self):
        """Return the current NumberedCodeEditor (unwrapping MarkdownContainer)."""
        w = self._tabs.currentWidget()
        if w is None:
            return None
        if isinstance(w, MarkdownContainer):
            return w.editor
        if isinstance(w, (QPlainTextEdit, QTextEdit)):
            return w
        return None

    def _qt_flags(self, forward: bool):
        from PyQt5.QtGui import QTextDocument
        flags = QTextDocument.FindFlags()
        if not forward:
            flags |= QTextDocument.FindBackward
        if self._chk_case.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self._chk_word.isChecked():
            flags |= QTextDocument.FindWholeWords
        return flags

    def _flags(self):
        """Return re flags for Python regex counting."""
        f = 0 if self._chk_case.isChecked() else _re.IGNORECASE
        return f

    def _matches(self, text: str, term: str) -> bool:
        if self._chk_case.isChecked():
            return text == term
        return text.lower() == term.lower()

    def _count_matches(self, ed, term: str) -> int:
        content = ed.toPlainText()
        try:
            if self._chk_regex.isChecked():
                return len(_re.findall(term, content, self._flags()))
            escaped = _re.escape(term)
            if self._chk_word.isChecked():
                escaped = r'\b' + escaped + r'\b'
            return len(_re.findall(escaped, content, self._flags()))
        except _re.error:
            return 0

    def _highlight_all(self, ed, term: str):
        """Paint yellow backgrounds on all matches using ExtraSelections."""
        fmt = QTextFormat()  # unused — we use QTextEdit.ExtraSelection below
        hi_fmt = QTextEdit.ExtraSelection() if False else None  # just for type hint
        from PyQt5.QtWidgets import QTextEdit as _QTE
        fmt2 = _QTE.ExtraSelection()

        yellow = QColor("#ffcc0044")   # semi-transparent yellow
        selections = []
        content = ed.toPlainText()
        try:
            escaped = (_re.escape(term) if not self._chk_regex.isChecked()
                       else term)
            if self._chk_word.isChecked() and not self._chk_regex.isChecked():
                escaped = r'\b' + escaped + r'\b'
            for m in _re.finditer(escaped, content, self._flags()):
                sel = _QTE.ExtraSelection()
                sel.format.setBackground(QColor("#554400"))
                cur = ed.textCursor()
                cur.setPosition(m.start())
                cur.setPosition(m.end(), QTextCursor.KeepAnchor)
                sel.cursor = cur
                selections.append(sel)
        except _re.error:
            pass
        ed.setExtraSelections(selections)

    def _show_replace_widgets(self, visible: bool):
        for w in [self._sep, self._replace_input,
                  self._btn_replace, self._btn_replace_all]:
            w.setVisible(visible)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_bar()
        elif event.key() == Qt.Key_Return and event.modifiers() & Qt.ShiftModifier:
            self.find_prev()
        elif event.key() == Qt.Key_F3:
            if event.modifiers() & Qt.ShiftModifier:
                self.find_prev()
            else:
                self.find_next()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Gutter / line-number area
# ---------------------------------------------------------------------------
class LineNumberArea(QWidget):
    def __init__(self, editor: "NumberedCodeEditor"):
        super().__init__(editor)
        self.editor = editor
        self.setAttribute(Qt.WA_TranslucentBackground)

    def sizeHint(self) -> QSize:
        return self.editor.sizeHint()

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

    def mousePressEvent(self, event):
        y = event.pos().y()
        block = self.editor.firstVisibleBlock()
        top   = self.editor.blockBoundingGeometry(block).translated(
                    self.editor.contentOffset()).top()
        while block.isValid():
            h = self.editor.blockBoundingRect(block).height()
            if top <= y <= top + h:
                line = block.blockNumber() + 1
                msg  = self.editor._diagnostic_for_line(line)
                if msg:
                    QToolTip.showText(event.globalPos(), msg, self)
                break
            top  += h
            block = block.next()


# ---------------------------------------------------------------------------
# Main editor widget
# ---------------------------------------------------------------------------
class NumberedCodeEditor(QPlainTextEdit):
    contentChanged = pyqtSignal(str)

    def __init__(self, file_path: str = ""):
        super().__init__()
        self._file_path  = file_path
        self._diagnostics: list[dict] = []
        self._highlighter = None

        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.textChanged.connect(self._on_text_changed)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

        font = QFont("Courier New", 12)
        font.setFixedPitch(True)
        self.setFont(font)

        # Make the editor show TAB_WIDTH-wide tab stops visually too
        # (belt-and-suspenders; actual tab key now inserts spaces)
        metrics = self.fontMetrics()
        self.setTabStopDistance(TAB_WIDTH * metrics.horizontalAdvance(' '))

    # ── public API ────────────────────────────────────────────────────

    def setText(self, text: str):
        self.setPlainText(text)

    def toPlainText(self) -> str:
        return super().toPlainText()

    def set_file_path(self, path: str):
        self._file_path = path

    def set_diagnostics(self, issues: list[dict]):
        self._diagnostics = issues
        self.line_number_area.update()

    def set_highlighter(self, highlighter):
        self._highlighter = highlighter

    def get_markdown_container(self) -> "MarkdownContainer":
        if not hasattr(self, "_md_container"):
            self._md_container = MarkdownContainer(self, self._file_path)
        return self._md_container

    # ── Tab / indent handling ─────────────────────────────────────────

    def keyPressEvent(self, event):
        key   = event.key()
        mods  = event.modifiers()
        shift = bool(mods & Qt.ShiftModifier)
        ctrl  = bool(mods & Qt.ControlModifier)

        # ── Tab key ───────────────────────────────────────────────────
        if key == Qt.Key_Tab and not ctrl:
            cur = self.textCursor()

            if cur.hasSelection():
                # Multi-line selection → indent all selected lines RIGHT
                self._indent_selection(dedent=False)
            else:
                # No selection → insert exactly TAB_WIDTH spaces
                # (never insert a real \t character)
                cur.insertText(" " * TAB_WIDTH)
            return

        # ── Shift+Tab → dedent ────────────────────────────────────────
        if key == Qt.Key_Backtab:   # Qt.Key_Backtab is Shift+Tab
            cur = self.textCursor()
            if cur.hasSelection():
                self._indent_selection(dedent=True)
            else:
                self._dedent_single_line(cur)
            return

        # ── Enter → auto-indent to match previous line's indentation ──
        if key in (Qt.Key_Return, Qt.Key_Enter) and not ctrl:
            cur      = self.textCursor()
            cur.select(QTextCursor.LineUnderCursor)
            line_text = cur.selectedText()
            indent   = len(line_text) - len(line_text.lstrip(' '))
            # Restore cursor to original position
            cur = self.textCursor()
            super().keyPressEvent(event)
            # Insert matching spaces
            self.textCursor().insertText(' ' * indent)
            return

        # ── Backspace — eat up to TAB_WIDTH spaces if they're all spaces ──
        if key == Qt.Key_Backspace and not ctrl and not shift:
            cur = self.textCursor()
            if not cur.hasSelection():
                # Check how many spaces are to the left on this line
                cur.select(QTextCursor.LineUnderCursor)
                line_text = cur.selectedText()
                cur = self.textCursor()
                col = cur.positionInBlock()
                # Count trailing spaces up to col
                left = line_text[:col]
                spaces = len(left) - len(left.rstrip(' '))
                if spaces > 0 and spaces <= TAB_WIDTH and left == ' ' * col:
                    # Delete up to TAB_WIDTH spaces at once
                    delete_count = spaces if spaces % TAB_WIDTH != 0 else TAB_WIDTH
                    for _ in range(min(delete_count, spaces)):
                        cur.deletePreviousChar()
                    return
            # Fall through to default backspace
            super().keyPressEvent(event)
            return

        super().keyPressEvent(event)

    def _indent_selection(self, dedent: bool):
        """
        Indent or dedent every line that is (even partially) within the
        current selection.  Uses spaces only, TAB_WIDTH spaces per level.
        """
        cur   = self.textCursor()
        start = cur.selectionStart()
        end   = cur.selectionEnd()

        cur.beginEditBlock()

        # Expand to include full lines
        c = QTextCursor(self.document())
        c.setPosition(start)
        c.movePosition(QTextCursor.StartOfLine)
        line_start = c.position()

        c.setPosition(end)
        if c.positionInBlock() == 0 and end > start:
            # Selection ends at column 0 of the next line — don't indent that line
            c.movePosition(QTextCursor.PreviousCharacter)
        c.movePosition(QTextCursor.EndOfLine)
        line_end = c.position()

        # Work line by line
        c.setPosition(line_start)
        while c.position() <= line_end:
            c.movePosition(QTextCursor.StartOfLine)
            if dedent:
                # Remove up to TAB_WIDTH leading spaces
                line_cur = QTextCursor(self.document())
                line_cur.setPosition(c.position())
                removed = 0
                while removed < TAB_WIDTH:
                    line_cur.setPosition(c.position())
                    line_cur.movePosition(QTextCursor.NextCharacter,
                                          QTextCursor.KeepAnchor)
                    if line_cur.selectedText() == ' ':
                        line_cur.removeSelectedText()
                        removed += 1
                    else:
                        break
            else:
                c.insertText(' ' * TAB_WIDTH)

            # Move to next line
            if not c.movePosition(QTextCursor.NextBlock):
                break

        cur.endEditBlock()

        # Re-select the indented block (approximate)
        new_cur = self.textCursor()
        new_cur.setPosition(line_start)
        new_cur.setPosition(line_end, QTextCursor.KeepAnchor)
        self.setTextCursor(new_cur)

    def _dedent_single_line(self, cur: QTextCursor):
        """Remove up to TAB_WIDTH leading spaces from the current line."""
        cur.movePosition(QTextCursor.StartOfLine)
        removed = 0
        while removed < TAB_WIDTH:
            peek = QTextCursor(self.document())
            peek.setPosition(cur.position())
            peek.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            if peek.selectedText() == ' ':
                peek.removeSelectedText()
                removed += 1
            else:
                break

    # ── Gutter ────────────────────────────────────────────────────────

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 3 + self.fontMetrics().horizontalAdvance("9") * digits + 14

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0, rect.y(), self.line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def lineNumberAreaPaintEvent(self, event):
        painter  = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), LINE_NUM_AREA_BG)

        error_lines   = {d["line"] for d in self._diagnostics if d["severity"] == "error"}
        warning_lines = {d["line"] for d in self._diagnostics if d["severity"] == "warning"}

        block        = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top    = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        gutter_w = self.line_number_area.width()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_no = block_number + 1
                fh      = self.fontMetrics().height()

                painter.setPen(QColor(LINE_NUM_COLOR))
                painter.drawText(
                    4, int(top), gutter_w - 14, fh,
                    Qt.AlignLeft, str(line_no)
                )

                dot_x = gutter_w - 10
                dot_y = int(top) + (fh - 8) // 2
                if line_no in error_lines:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(ERROR_GUTTER_COLOR)
                    painter.drawEllipse(dot_x, dot_y, 8, 8)
                elif line_no in warning_lines:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(WARNING_GUTTER_COLOR)
                    painter.drawEllipse(dot_x, dot_y, 8, 8)

            block        = block.next()
            top          = bottom
            bottom       = top + self.blockBoundingRect(block).height()
            block_number += 1

    # ── Current-line highlight ────────────────────────────────────────

    def highlight_current_line(self):
        extra = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(LINE_BG_COLOR)
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)
        self.setExtraSelections(extra)

    def showEvent(self, event):
        super().showEvent(event)
        self.update_line_number_area_width(0)

    def _on_text_changed(self):
        self.contentChanged.emit(self.toPlainText())

    def _diagnostic_for_line(self, line: int) -> str:
        msgs = [d["message"] for d in self._diagnostics if d["line"] == line]
        return "\n".join(msgs) if msgs else ""


# ---------------------------------------------------------------------------
# Markdown container
# ---------------------------------------------------------------------------
_MD_BUTTON_STYLE = """
    QPushButton {
        background: #2d2d2d;
        color: #aaaaaa;
        border: 1px solid #444;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 11px;
    }
    QPushButton:hover  { background: #3a3a3a; color: #ffffff; }
    QPushButton:checked {
        background: #0091E7;
        color: #ffffff;
        border-color: #0091E7;
    }
"""

_MD_CSS = """
    body {
        font-family: 'Segoe UI', system-ui, sans-serif;
        font-size: 14px;
        line-height: 1.7;
        color: #e0e0e0;
        background: #1e1e1e;
        max-width: 860px;
        margin: 0 auto;
        padding: 24px 32px;
    }
    h1,h2,h3,h4,h5,h6 { color: #C792EA; border-bottom: 1px solid #333;
        padding-bottom: 4px; margin-top: 1.4em; }
    a  { color: #82AAFF; }
    code { background: #2d2d2d; color: #F78C6C; border-radius: 3px;
           padding: 1px 5px; font-family: 'Courier New', monospace; }
    pre  { background: #252525; border: 1px solid #333; border-radius: 6px;
           padding: 14px 16px; overflow-x: auto; }
    pre code { background: none; padding: 0; }
    blockquote { border-left: 3px solid #546E7A; margin: 0;
                 padding-left: 16px; color: #888; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th,td { border: 1px solid #333; padding: 6px 12px; text-align: left; }
    th    { background: #2d2d2d; color: #FFCB6B; }
    img   { max-width: 100%; border-radius: 4px; }
    hr    { border: none; border-top: 1px solid #333; margin: 1.5em 0; }
"""


class MarkdownContainer(QWidget):
    def __init__(self, editor: NumberedCodeEditor, file_path: str = ""):
        super().__init__()
        self._editor    = editor
        self._file_path = file_path
        self._preview   = None
        self._showing_preview = False

        is_md   = file_path.lower().endswith((".md", ".markdown"))
        is_html = file_path.lower().endswith((".html", ".htm"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if is_md or is_html:
            toolbar = QWidget()
            toolbar.setFixedHeight(30)
            toolbar.setStyleSheet("background: #252525; border-bottom: 1px solid #333;")
            tb_layout = QHBoxLayout(toolbar)
            tb_layout.setContentsMargins(6, 2, 6, 2)
            tb_layout.addStretch()

            self._toggle_btn = QPushButton("⬜ Preview")
            self._toggle_btn.setCheckable(True)
            self._toggle_btn.setChecked(False)
            self._toggle_btn.setStyleSheet(_MD_BUTTON_STYLE)
            self._toggle_btn.setFixedHeight(22)
            self._toggle_btn.clicked.connect(self._on_toggle)
            tb_layout.addWidget(self._toggle_btn)

            layout.addWidget(toolbar)

        self._stack = QWidget()
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.addWidget(editor)
        layout.addWidget(self._stack)

        if is_md or is_html:
            editor.contentChanged.connect(self._on_content_changed)

    @property
    def editor(self) -> NumberedCodeEditor:
        return self._editor

    def toPlainText(self) -> str:
        return self._editor.toPlainText()

    def setText(self, text: str):
        self._editor.setText(text)

    def textChanged(self):
        return self._editor.textChanged

    def _on_toggle(self, checked: bool):
        if checked:
            self._toggle_btn.setText("✏️ Edit")
            self._show_preview()
        else:
            self._toggle_btn.setText("⬜ Preview")
            self._show_editor()

    def _show_editor(self):
        if self._preview:
            self._preview.setVisible(False)
        self._editor.setVisible(True)
        self._showing_preview = False

    def _show_preview(self):
        self._editor.setVisible(False)
        html = self._render_html()
        if HAS_WEBENGINE:
            if self._preview is None:
                self._preview = QWebEngineView()
                self._stack.layout().addWidget(self._preview)
            is_html = self._file_path.lower().endswith((".html", ".htm"))
            if is_html:
                import os as _os
                base = QUrl.fromLocalFile(
                    _os.path.dirname(_os.path.abspath(self._file_path)) + "/")
                self._preview.setHtml(html, base)
            else:
                self._preview.setHtml(html)
            self._preview.setVisible(True)
        else:
            if self._preview is None:
                scroll = QScrollArea()
                lbl    = QLabel()
                lbl.setWordWrap(True)
                lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                lbl.setTextFormat(Qt.RichText)
                lbl.setOpenExternalLinks(True)
                scroll.setWidget(lbl)
                scroll.setWidgetResizable(True)
                self._preview = scroll
                self._preview_label = lbl
                self._stack.layout().addWidget(self._preview)
            self._preview_label.setText(html)
            self._preview.setVisible(True)
        self._showing_preview = True

    def _on_content_changed(self, _text: str):
        if self._showing_preview and self._preview:
            html = self._render_html()
            if HAS_WEBENGINE and isinstance(self._preview, QWebEngineView):
                self._preview.setHtml(html)
            elif hasattr(self, "_preview_label"):
                self._preview_label.setText(html)

    def _render_html(self) -> str:
        source  = self._editor.toPlainText()
        is_html = self._file_path.lower().endswith((".html", ".htm"))
        if is_html:
            return source
        if HAS_MARKDOWN:
            body = md_lib.markdown(
                source,
                extensions=["fenced_code", "tables", "toc", "nl2br", "sane_lists"],
            )
        else:
            import html as html_lib
            body = "<pre>" + html_lib.escape(source) + "</pre>"
        return (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                f'<style>{_MD_CSS}</style></head><body>{body}</body></html>')
