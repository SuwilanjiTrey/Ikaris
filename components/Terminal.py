"""
terminal.py  —  Embedded terminal widget for Ikaris Dev Studio
──────────────────────────────────────────────────────────────
• Real PTY-backed shell (bash)  — proper interactive programs work
• ANSI / VT100 colour + style parsing
• Tab bar with  [+]  button to open new terminals
• Closing the last tab hides the container rather than leaving a blank panel
• Drop-in: instantiate  TerminalManager(container, layout)  and call
  terminal_manager.toggle()  from your sidebar button / shortcut.
"""

import os
import re
import pty
import fcntl
import termios
import struct
import signal
import shutil
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QTabWidget, QTabBar,
    QLabel, QApplication, QSizePolicy,
)
from PyQt5.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor,
    QKeySequence,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QObject,
)


# ── colour palette (ANSI 8/16 colours) ───────────────────────────────────────
_ANSI_COLORS = {
    # normal
    30: "#4C4C4C",  31: "#FF5555",  32: "#55FF55",  33: "#FFFF55",
    34: "#5555FF",  35: "#FF55FF",  36: "#55FFFF",  37: "#CCCCCC",
    # bright
    90: "#555555",  91: "#FF5555",  92: "#55FF55",  93: "#FFFF55",
    94: "#5599FF",  95: "#FF55FF",  96: "#55FFFF",  97: "#FFFFFF",
    # bg normal
    40: "#000000",  41: "#AA0000",  42: "#00AA00",  43: "#AA5500",
    44: "#0000AA",  45: "#AA00AA",  46: "#00AAAA",  47: "#AAAAAA",
    # bg bright
   100: "#555555", 101: "#FF5555", 102: "#55FF55", 103: "#FFFF55",
   104: "#5599FF", 105: "#FF55FF", 106: "#55FFFF", 107: "#FFFFFF",
}
_DEFAULT_FG = "#E0E0E0"
_DEFAULT_BG = "transparent"


# ── PTY reader thread ─────────────────────────────────────────────────────────
class _PtyReader(QThread):
    """Reads raw bytes from the pty master fd and emits them as chunks."""
    data_ready = pyqtSignal(bytes)
    finished   = pyqtSignal()

    def __init__(self, master_fd: int):
        super().__init__()
        self._fd     = master_fd
        self._active = True

    def run(self):
        import select
        while self._active:
            try:
                r, _, _ = select.select([self._fd], [], [], 0.05)
                if r:
                    chunk = os.read(self._fd, 4096)
                    if chunk:
                        self.data_ready.emit(chunk)
                    else:
                        break
            except OSError:
                break
        self.finished.emit()

    def stop(self):
        self._active = False


# ── ANSI escape sequence parser ───────────────────────────────────────────────
_ESC_RE = re.compile(
    r'\x1b'
    r'(?:'
    r'\[([0-9;?]*)([A-Za-z])'   # CSI sequences  \x1b[ ... final
    r'|'
    r'\]([^\x07\x1b]*)(?:\x07|\x1b\\)'  # OSC  \x1b] ... BEL/ST
    r'|'
    r'([PX^_])([^\x1b]*)(?:\x1b\\)'     # DCS / SOS / PM / APC
    r'|'
    r'([()#%])(.)' # two-char sequences
    r'|'
    r'(.)'         # single-char escape
    r')'
)


class AnsiParser:
    """
    Converts a raw byte stream into a list of (text, QTextCharFormat) spans.
    Maintains state across calls so sequences split across chunks work.
    """

    def __init__(self):
        self._fg      = _DEFAULT_FG
        self._bg      = _DEFAULT_BG
        self._bold    = False
        self._italic  = False
        self._under   = False
        self._buf     = ""       # leftover incomplete sequence

    # ------------------------------------------------------------------
    def feed(self, raw: bytes) -> list[tuple[str, QTextCharFormat]]:
        text  = self._buf + raw.decode("utf-8", errors="replace")
        self._buf = ""
        spans: list[tuple[str, QTextCharFormat]] = []
        pos   = 0

        while pos < len(text):
            esc = _ESC_RE.search(text, pos)
            if esc is None:
                # No more escapes — check for a partial one at the end
                tail = text[pos:]
                esc_pos = tail.rfind('\x1b')
                if esc_pos != -1:
                    self._buf = tail[esc_pos:]
                    tail = tail[:esc_pos]
                if tail:
                    spans.append((tail, self._make_fmt()))
                break

            # Plain text before the escape
            if esc.start() > pos:
                chunk = text[pos:esc.start()]
                if chunk:
                    spans.append((chunk, self._make_fmt()))

            pos = esc.end()

            csi_params, csi_final = esc.group(1), esc.group(2)
            if csi_final:
                self._handle_csi(csi_params or "", csi_final)
                continue

            # Everything else (OSC, DCS, single-char) — just discard

        return spans

    # ------------------------------------------------------------------
    def _handle_csi(self, params: str, final: str):
        if final != "m":
            return   # only care about SGR (colour/style)

        parts = params.split(";") if params else ["0"]
        i = 0
        while i < len(parts):
            try:
                n = int(parts[i]) if parts[i] else 0
            except ValueError:
                i += 1
                continue

            if n == 0:
                self._reset()
            elif n == 1:
                self._bold   = True
            elif n == 3:
                self._italic = True
            elif n == 4:
                self._under  = True
            elif n == 22:
                self._bold   = False
            elif n == 23:
                self._italic = False
            elif n == 24:
                self._under  = False
            elif 30 <= n <= 37 or 90 <= n <= 97:
                self._fg = _ANSI_COLORS.get(n, _DEFAULT_FG)
            elif n == 38:
                # 256-colour or truecolor fg
                if i + 2 < len(parts) and parts[i+1] == "5":
                    self._fg = _256_color(int(parts[i+2]))
                    i += 2
                elif i + 4 < len(parts) and parts[i+1] == "2":
                    r, g, b = int(parts[i+2]), int(parts[i+3]), int(parts[i+4])
                    self._fg = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            elif n == 39:
                self._fg = _DEFAULT_FG
            elif 40 <= n <= 47 or 100 <= n <= 107:
                self._bg = _ANSI_COLORS.get(n, _DEFAULT_BG)
            elif n == 48:
                if i + 2 < len(parts) and parts[i+1] == "5":
                    self._bg = _256_color(int(parts[i+2]))
                    i += 2
                elif i + 4 < len(parts) and parts[i+1] == "2":
                    r, g, b = int(parts[i+2]), int(parts[i+3]), int(parts[i+4])
                    self._bg = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            elif n == 49:
                self._bg = _DEFAULT_BG
            i += 1

    def _reset(self):
        self._fg     = _DEFAULT_FG
        self._bg     = _DEFAULT_BG
        self._bold   = False
        self._italic = False
        self._under  = False

    def _make_fmt(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._fg))
        if self._bg != _DEFAULT_BG:
            fmt.setBackground(QColor(self._bg))
        if self._bold:
            fmt.setFontWeight(QFont.Bold)
        if self._italic:
            fmt.setFontItalic(True)
        if self._under:
            fmt.setFontUnderline(True)
        return fmt


def _256_color(idx: int) -> str:
    """Convert xterm 256-color index to hex."""
    if idx < 16:
        return _ANSI_COLORS.get(30 + idx, _DEFAULT_FG)
    if 16 <= idx <= 231:
        idx -= 16
        b = idx % 6;  idx //= 6
        g = idx % 6;  r = idx // 6
        to_val = lambda x: 0 if x == 0 else 55 + x * 40
        return f"#{to_val(r):02x}{to_val(g):02x}{to_val(b):02x}"
    # greyscale 232–255
    v = 8 + (idx - 232) * 10
    return f"#{v:02x}{v:02x}{v:02x}"


# ── Single terminal pane ──────────────────────────────────────────────────────
class TerminalPane(QWidget):
    """
    One terminal session: a PTY-backed shell + display widget.
    Emits  closed  when the shell exits or the pane is explicitly killed.
    """
    closed = pyqtSignal(object)   # passes self

    def __init__(self, cwd: str | None = None):
        super().__init__()
        self._cwd    = cwd or str(Path.home())
        self._master = None
        self._pid    = None
        self._reader = None
        self._parser = AnsiParser()
        self._history: list[str] = []
        self._hist_idx = -1
        self._input_start_pos = 0   # cursor position where current input begins

        self._build_ui()
        self._spawn_shell()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setFont(QFont("Monospace", 11))
        self._display.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border: none;
                padding: 4px;
                selection-background-color: #3a5a8a;
            }
        """)
        self._display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Input bar
        input_bar = QWidget()
        input_bar.setFixedHeight(32)
        input_bar.setStyleSheet("background: #111111; border-top: 1px solid #333;")
        bar_layout = QHBoxLayout(input_bar)
        bar_layout.setContentsMargins(6, 2, 6, 2)
        bar_layout.setSpacing(4)

        self._prompt_label = QLabel("$")
        self._prompt_label.setStyleSheet("color: #55FF55; font-family: Monospace; font-size: 11px;")
        self._prompt_label.setFixedWidth(14)

        self._input = QLineEdit()
        self._input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                color: #e0e0e0;
                border: none;
                font-family: Monospace;
                font-size: 11px;
            }
        """)
        self._input.returnPressed.connect(self._send_input)
        self._input.installEventFilter(self)

        bar_layout.addWidget(self._prompt_label)
        bar_layout.addWidget(self._input)

        layout.addWidget(self._display)
        layout.addWidget(input_bar)

        self._input.setFocus()

    # ── shell spawning ────────────────────────────────────────────────
    def _spawn_shell(self):
        shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"

        self._master, slave = pty.openpty()

        # Set terminal size (80×24 default)
        self._set_pty_size(80, 24)

        # Make master non-blocking
        flags = fcntl.fcntl(self._master, fcntl.F_GETFL)
        fcntl.fcntl(self._master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._pid = os.fork()
        if self._pid == 0:
            # ── child ──────────────────────────────────────────────
            os.close(self._master)
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            os.dup2(slave, 0)
            os.dup2(slave, 1)
            os.dup2(slave, 2)
            os.close(slave)
            os.chdir(self._cwd)
            env = os.environ.copy()
            env.update({
                "TERM":      "xterm-256color",
                "COLORTERM": "truecolor",
                "COLUMNS":   "80",
                "LINES":     "24",
            })
            os.execve(shell, [shell, "-i"], env)
            os._exit(1)

        # ── parent ─────────────────────────────────────────────────
        os.close(slave)
        self._reader = _PtyReader(self._master)
        self._reader.data_ready.connect(self._on_data)
        self._reader.finished.connect(self._on_shell_exit)
        self._reader.start()

    def _set_pty_size(self, cols: int, rows: int):
        if self._master is None:
            return
        size = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self._master, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._master is not None:
            char_w = self._display.fontMetrics().horizontalAdvance("M")
            char_h = self._display.fontMetrics().height()
            if char_w > 0 and char_h > 0:
                cols = max(10, self._display.width()  // char_w)
                rows = max(4,  self._display.height() // char_h)
                self._set_pty_size(cols, rows)

    # ── incoming data ─────────────────────────────────────────────────
    def _on_data(self, raw: bytes):
        # Filter out common cursor/mode sequences we don't need to render
        # but keep text + colour sequences
        filtered = self._strip_cursor_sequences(raw)
        spans    = self._parser.feed(filtered)

        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)

        for text, fmt in spans:
            # Normalise line endings:
            #   \r\n  → \n   (Windows-style, safe)
            #   \r     → ""   (bare CR = cursor-to-col-0 in a real terminal;
            #                   in our QTextEdit it just causes duplicate lines
            #                   so we strip it entirely — the shell redraws the
            #                   prompt on the same line after a clear/resize and
            #                   we don't want that to produce an extra blank line)
            text = text.replace("\r\n", "\n").replace("\r", "")

            # Remove backspace sequences (simple overstrike removal)
            while "\x08" in text:
                idx = text.index("\x08")
                text = text[:max(0, idx - 1)] + text[idx + 1:]

            if text:
                cursor.insertText(text, fmt)

        self._display.setTextCursor(cursor)
        self._display.ensureCursorVisible()

    def _strip_cursor_sequences(self, raw: bytes) -> bytes:
        """
        Remove PTY sequences that mess up a QTextEdit display:
        cursor movement, clear screen, alternate screen buffer, etc.
        We keep SGR (colour) sequences intact.
        """
        text = raw.decode("utf-8", errors="replace")
        # Strip: cursor movement, erase, screen mode switches, etc.
        # Keep:  \x1b[...m  (SGR colour)
        def _replace(m):
            final = m.group(2)
            if final == "m":
                return m.group(0)   # keep colour sequences
            return ""               # drop everything else
        cleaned = _ESC_RE.sub(_replace, text)
        return cleaned.encode("utf-8")

    def _on_shell_exit(self):
        self._append_system_msg("\n[Process exited]\n")
        self.closed.emit(self)

    # ── sending input ─────────────────────────────────────────────────
    def _send_input(self):
        text = self._input.text()
        self._input.clear()

        if text:
            self._history.append(text)
            self._hist_idx = len(self._history)

        cmd = text + "\n"
        try:
            os.write(self._master, cmd.encode("utf-8"))
        except OSError:
            pass

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                self._nav_history(-1)
                return True
            if key == Qt.Key_Down:
                self._nav_history(1)
                return True
            if key == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
                self._send_signal(signal.SIGINT)
                return True
            if key == Qt.Key_D and event.modifiers() & Qt.ControlModifier:
                try:
                    os.write(self._master, b"\x04")  # EOF
                except OSError:
                    pass
                return True
            if key == Qt.Key_L and event.modifiers() & Qt.ControlModifier:
                self._display.clear()
                return True
            if key == Qt.Key_Tab:
                # Send TAB to shell for completion
                try:
                    text = self._input.text()
                    os.write(self._master, (text + "\t").encode())
                    self._input.clear()
                except OSError:
                    pass
                return True
        return super().eventFilter(obj, event)

    def _nav_history(self, direction: int):
        if not self._history:
            return
        self._hist_idx = max(0, min(len(self._history) - 1,
                                    self._hist_idx + direction))
        self._input.setText(self._history[self._hist_idx])
        self._input.end(False)

    def _send_signal(self, sig):
        if self._pid:
            try:
                os.killpg(os.getpgid(self._pid), sig)
            except (OSError, ProcessLookupError):
                pass

    # ── helpers ───────────────────────────────────────────────────────
    def _append_system_msg(self, msg: str):
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#888888"))
        fmt.setFontItalic(True)
        cursor.insertText(msg, fmt)
        self._display.setTextCursor(cursor)
        self._display.ensureCursorVisible()

    def set_cwd(self, path: str):
        """Change the working directory of the running shell."""
        if os.path.isdir(path) and self._master:
            try:
                os.write(self._master, f'cd "{path}"\n'.encode())
            except OSError:
                pass

    def kill(self):
        """Terminate the shell process and reader thread."""
        if self._reader:
            self._reader.stop()
            self._reader.wait(500)
        if self._pid:
            try:
                os.kill(self._pid, signal.SIGTERM)
                os.waitpid(self._pid, os.WNOHANG)
            except (OSError, ChildProcessError):
                pass
            self._pid = None
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None

    def focus_input(self):
        self._input.setFocus()


# ── Tab manager ───────────────────────────────────────────────────────────────
_TAB_STYLE = """
    QTabWidget::pane {
        border: none;
        background: #1a1a1a;
    }
    QTabBar {
        background: #111111;
    }
    QTabBar::tab {
        background: #1e1e1e;
        color: #888888;
        padding: 4px 12px;
        border: none;
        border-right: 1px solid #333;
        font-size: 11px;
        min-width: 80px;
    }
    QTabBar::tab:selected {
        background: #1a1a1a;
        color: #e0e0e0;
        border-bottom: 2px solid #0091E7;
    }
    QTabBar::tab:hover:!selected {
        background: #252525;
        color: #cccccc;
    }
"""

_BTN_STYLE = """
    QPushButton {
        background: transparent;
        color: #888888;
        border: none;
        font-size: 14px;
        padding: 2px 6px;
    }
    QPushButton:hover { color: #ffffff; background: #2a2a2a; }
    QPushButton:pressed { color: #0091E7; }
"""


class TerminalManager(QObject):
    """
    Manages a QTabWidget of TerminalPane instances inside the given
    container widget / layout.

    Usage in CodeEditor:
        self.terminal_manager = TerminalManager(
            self.terminal_container,
            terminal_layout,
            get_cwd=lambda: self.base_directory   # optional
        )
        # In toggle_terminal:
        self.terminal_manager.toggle()
    """

    def __init__(self, container: QWidget, layout: QVBoxLayout,
                 get_cwd=None):
        super().__init__()
        self._container = container
        self._layout    = layout
        self._get_cwd   = get_cwd   # callable → str | None
        self._tab_count = 0         # ever-increasing, for default labels
        self._visible   = False

        self._build_tab_widget()
        self._container.setVisible(False)

    # ── build the permanent tab widget ───────────────────────────────
    def _build_tab_widget(self):
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_TAB_STYLE)
        self._tabs.setTabsClosable(False)   # we handle close ourselves
        self._tabs.setMovable(True)

        # Header bar: title label + [+] new tab + [×] close all
        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet("background: #111111; border-bottom: 1px solid #2a2a2a;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 4, 0)
        h_layout.setSpacing(4)

        title = QLabel("TERMINAL")
        title.setStyleSheet("color: #555555; font-size: 10px; font-weight: bold; letter-spacing: 1px;")

        new_btn = QPushButton("+")
        new_btn.setFixedSize(24, 24)
        new_btn.setStyleSheet(_BTN_STYLE)
        new_btn.setToolTip("New terminal tab")
        new_btn.clicked.connect(self.new_tab)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(_BTN_STYLE)
        close_btn.setToolTip("Close terminal panel")
        close_btn.clicked.connect(self.hide)

        h_layout.addWidget(title)
        h_layout.addStretch()
        h_layout.addWidget(new_btn)
        h_layout.addWidget(close_btn)

        wrapper = QWidget()
        w_layout = QVBoxLayout(wrapper)
        w_layout.setContentsMargins(0, 0, 0, 0)
        w_layout.setSpacing(0)
        w_layout.addWidget(header)
        w_layout.addWidget(self._tabs)

        self._layout.addWidget(wrapper)
        self._wrapper = wrapper

    # ── public API ────────────────────────────────────────────────────
    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self):
        if self._tabs.count() == 0:
            self.new_tab()
        self._container.setVisible(True)
        self._visible = True
        # Give focus to the current pane's input
        pane = self._current_pane()
        if pane:
            pane.focus_input()

    def hide(self):
        self._container.setVisible(False)
        self._visible = False

    def new_tab(self, cwd: str | None = None):
        if cwd is None and self._get_cwd:
            cwd = self._get_cwd()
        self._tab_count += 1
        pane = TerminalPane(cwd=cwd)
        pane.closed.connect(self._on_pane_closed)

        label = f"bash {self._tab_count}"
        idx   = self._tabs.addTab(pane, label)
        self._tabs.setCurrentIndex(idx)

        # Per-tab close button
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #666; border: none;
                font-size: 10px; padding: 0;
            }
            QPushButton:hover { color: #ff5555; }
        """)
        close_btn.clicked.connect(lambda: self._close_tab_for_pane(pane))
        self._tabs.tabBar().setTabButton(idx, QTabBar.RightSide, close_btn)

        self._container.setVisible(True)
        self._visible = True
        pane.focus_input()
        return pane

    def set_cwd(self, path: str):
        """Send 'cd <path>' to the currently active terminal."""
        pane = self._current_pane()
        if pane:
            pane.set_cwd(path)

    def kill_all(self):
        for i in range(self._tabs.count()):
            pane = self._tabs.widget(i)
            if isinstance(pane, TerminalPane):
                pane.kill()

    # ── internal ──────────────────────────────────────────────────────
    def _current_pane(self) -> TerminalPane | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, TerminalPane) else None

    def _close_tab_for_pane(self, pane: TerminalPane):
        pane.kill()
        idx = self._tabs.indexOf(pane)
        if idx != -1:
            self._tabs.removeTab(idx)
        self._maybe_hide()

    def _on_pane_closed(self, pane: TerminalPane):
        """Called when the shell process exits on its own."""
        idx = self._tabs.indexOf(pane)
        if idx != -1:
            self._tabs.removeTab(idx)
        self._maybe_hide()

    def _maybe_hide(self):
        if self._tabs.count() == 0:
            self.hide()
