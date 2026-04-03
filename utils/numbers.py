"""
numbers.py  —  NumberedCodeEditor  +  MarkdownToggleButton
Drop-in replacement for the original numbers.py
"""

import os
from PyQt5.QtWidgets import (
    QPlainTextEdit, QWidget, QTextEdit, QPushButton,
    QLabel, QHBoxLayout, QVBoxLayout, QScrollArea,
    QSizePolicy, QToolTip,
)
from PyQt5.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QTextFormat, QColor, QFont,
    QTextCursor, QPixmap,
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
# Colour constants  (edit freely)
# ---------------------------------------------------------------------------
LINE_BG_COLOR         = QColor(30,  30,  30,  80)    # current-line highlight
LINE_NUM_AREA_BG      = QColor(30,  30,  30,  120)   # gutter background
LINE_NUM_COLOR        = "#0091E7"                      # line number text
ERROR_GUTTER_COLOR    = QColor(255, 83,  112, 200)    # error dot  (red)
WARNING_GUTTER_COLOR  = QColor(255, 203, 107, 200)    # warning dot (amber)


# ---------------------------------------------------------------------------
# Gutter / line-number area
# ---------------------------------------------------------------------------
class LineNumberArea(QWidget):
    """Painting surface for line numbers + diagnostic dots."""

    def __init__(self, editor: "NumberedCodeEditor"):
        super().__init__(editor)
        self.editor = editor
        self.setAttribute(Qt.WA_TranslucentBackground)

    def sizeHint(self) -> QSize:
        return self.editor.sizeHint()

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

    def mousePressEvent(self, event):
        """Show tooltip for diagnostic on clicked line."""
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
    """
    QPlainTextEdit with:
    • Line-number gutter with diagnostic dots
    • Current-line highlight
    • Pluggable syntax highlighter (set via set_highlighter())
    • Markdown preview toggle (call get_markdown_container() to embed)
    """

    # Emitted after every keystroke; connect to your checker
    contentChanged = pyqtSignal(str)   # passes current plain text

    def __init__(self, file_path: str = ""):
        super().__init__()
        self._file_path = file_path
        self._diagnostics: list[dict] = []   # {"line", "col", "message", "severity"}
        self._highlighter = None

        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.textChanged.connect(self._on_text_changed)

        self.update_line_number_area_width(0)
        self.highlight_current_line()

        # Font
        font = QFont("Courier New", 12)
        font.setFixedPitch(True)
        self.setFont(font)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setText(self, text: str):
        self.setPlainText(text)

    def toPlainText(self) -> str:
        return super().toPlainText()

    def set_file_path(self, path: str):
        self._file_path = path

    def set_diagnostics(self, issues: list[dict]):
        """Feed in results from highlighter.check_syntax()."""
        self._diagnostics = issues
        self.line_number_area.update()

    def set_highlighter(self, highlighter):
        """Attach a QSyntaxHighlighter instance (already created with this document)."""
        self._highlighter = highlighter

    def get_markdown_container(self) -> "MarkdownContainer":
        """
        Returns a MarkdownContainer that wraps *this* editor.
        Use this as the widget you add to tabs instead of the bare editor.
        """
        if not hasattr(self, "_md_container"):
            self._md_container = MarkdownContainer(self, self._file_path)
        return self._md_container

    # ------------------------------------------------------------------
    # Line-number gutter
    # ------------------------------------------------------------------

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 3 + self.fontMetrics().horizontalAdvance("9") * digits + 14  # +14 for dot

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
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), LINE_NUM_AREA_BG)

        # Build a quick lookup: line → severity
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

                # Line number text
                painter.setPen(QColor(LINE_NUM_COLOR))
                painter.drawText(
                    4, int(top), gutter_w - 14, fh,
                    Qt.AlignLeft, str(line_no)
                )

                # Diagnostic dot
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

    # ------------------------------------------------------------------
    # Current-line highlight
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        # Font metrics are only reliable once the widget is actually shown,
        # so recalculate the gutter width here to fix the overlap-on-load bug.
        self.update_line_number_area_width(0)

    def _on_text_changed(self):
        self.contentChanged.emit(self.toPlainText())

    def _diagnostic_for_line(self, line: int) -> str:
        msgs = [d["message"] for d in self._diagnostics if d["line"] == line]
        return "\n".join(msgs) if msgs else ""


# ---------------------------------------------------------------------------
# Markdown container  — wraps editor + toggle button in a QWidget
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
    h1,h2,h3,h4,h5,h6 {
        color: #C792EA;
        border-bottom: 1px solid #333;
        padding-bottom: 4px;
        margin-top: 1.4em;
    }
    a  { color: #82AAFF; }
    code {
        background: #2d2d2d;
        color: #F78C6C;
        border-radius: 3px;
        padding: 1px 5px;
        font-family: 'Courier New', monospace;
    }
    pre {
        background: #252525;
        border: 1px solid #333;
        border-radius: 6px;
        padding: 14px 16px;
        overflow-x: auto;
    }
    pre code { background: none; padding: 0; }
    blockquote {
        border-left: 3px solid #546E7A;
        margin: 0;
        padding-left: 16px;
        color: #888;
    }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th,td { border: 1px solid #333; padding: 6px 12px; text-align: left; }
    th    { background: #2d2d2d; color: #FFCB6B; }
    img   { max-width: 100%; border-radius: 4px; }
    hr    { border: none; border-top: 1px solid #333; margin: 1.5em 0; }
"""


class MarkdownContainer(QWidget):
    """
    A widget that contains:
    ┌──────────────────── toolbar ─────────────────┐
    │  [MD Preview ◉]                              │
    └──────────────────────────────────────────────┘
    ┌──────────────── editor / preview ────────────┐
    │  NumberedCodeEditor   OR   rendered HTML      │
    └──────────────────────────────────────────────┘

    Add *this* to your QTabWidget instead of the bare editor.
    The editor reference is still accessible via .editor
    """

    def __init__(self, editor: NumberedCodeEditor, file_path: str = ""):
        super().__init__()
        self._editor    = editor
        self._file_path = file_path
        self._preview   = None   # lazy-created QWebEngineView or QLabel
        self._showing_preview = False

        is_md = file_path.lower().endswith((".md", ".markdown"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── toolbar (only for markdown files) ──────────────────────────
        if is_md:
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

        # ── content area ───────────────────────────────────────────────
        self._stack = QWidget()
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.addWidget(editor)
        layout.addWidget(self._stack)

        # when editor text changes, live-update preview if open
        if is_md:
            editor.contentChanged.connect(self._on_content_changed)

    # ------------------------------------------------------------------

    @property
    def editor(self) -> NumberedCodeEditor:
        return self._editor

    # forward common QTextEdit-ish calls so the tab system still works
    def toPlainText(self) -> str:
        return self._editor.toPlainText()

    def setText(self, text: str):
        self._editor.setText(text)

    def textChanged(self):
        return self._editor.textChanged

    # ------------------------------------------------------------------

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
            self._preview.setHtml(html)
            self._preview.setVisible(True)
        else:
            # Fallback: plain QLabel with basic HTML (no CSS, but better than nothing)
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
        source = self._editor.toPlainText()
        if HAS_MARKDOWN:
            body = md_lib.markdown(
                source,
                extensions=["fenced_code", "tables", "toc", "nl2br", "sane_lists"],
            )
        else:
            # Very naive fallback
            import html as html_lib
            body = "<pre>" + html_lib.escape(source) + "</pre>"

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>{_MD_CSS}</style>
</head><body>{body}</body></html>"""
