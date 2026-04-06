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


# This is the replacement TerminalPane class + TerminalDisplay helper.
# Everything from line 244 to line 535 in terminal.py gets replaced with this.

class TerminalDisplay(QTextEdit):
    """
    A QTextEdit that acts as both the output display AND the input surface.
    - Output from the PTY is appended at the end
    - The user types after the last output position (_input_anchor)
    - Ctrl+C, Ctrl+D, Ctrl+L, Tab, arrows all send bytes directly to the PTY
    - Selection + copy works normally (mouse drag / Ctrl+Shift+C or Ctrl+C
      when text is selected)
    - Paste sends clipboard text straight to the PTY
    """

    # signals to the owning TerminalPane
    char_written  = pyqtSignal(bytes)   # user typed something → write to pty
    # sigint_req removed: Ctrl+C now writes \x03 directly via char_written

    def __init__(self):
        super().__init__()
        self.setFont(QFont("Monospace", 11))
        self.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border: none;
                padding: 4px;
                selection-background-color: #3a5a8a;
            }
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setUndoRedoEnabled(False)
        self.setAcceptRichText(False)

        # Position after the last PTY output — user may only type here or later
        self._input_anchor = 0
        self._history: list[str] = []
        self._hist_idx = -1

    # ── anchor management ─────────────────────────────────────────────
    def _set_anchor(self):
        """Called after every PTY write; locks the editable region."""
        self._input_anchor = len(self.toPlainText())

    def _get_input_text(self) -> str:
        """Return whatever the user has typed after the anchor."""
        return self.toPlainText()[self._input_anchor:]

    def _clear_input(self):
        """Erase user-typed text after the anchor."""
        doc    = self.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.End)
        anchor_cursor = QTextCursor(doc)
        anchor_cursor.setPosition(self._input_anchor)
        anchor_cursor.setPosition(cursor.position(), QTextCursor.KeepAnchor)
        anchor_cursor.removeSelectedText()

    def _ensure_cursor_at_end(self):
        c = self.textCursor()
        if c.position() < self._input_anchor:
            c.movePosition(QTextCursor.End)
            self.setTextCursor(c)

    # ── keyboard handling ─────────────────────────────────────────────
    def keyPressEvent(self, event):
        from PyQt5.QtGui import QKeyEvent
        key  = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift= bool(mods & Qt.ShiftModifier)

        # ── Ctrl+Shift+C → copy selected text ────────────────────────
        if ctrl and shift and key == Qt.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            return

        # ── Ctrl+C → always send raw \x03 to PTY (kills foreground process)
        # Writing the ETX byte to the PTY master is how real terminals send
        # SIGINT. The kernel line discipline delivers it to the foreground
        # process group — works for any subprocess, not just the shell.
        if ctrl and key == Qt.Key_C:
            self.char_written.emit(b"\x03")
            return

        # ── Paste: Ctrl+V or Ctrl+Shift+V ────────────────────────────
        if ctrl and key == Qt.Key_V:
            clipboard = QApplication.clipboard().text()
            if clipboard:
                self.char_written.emit(clipboard.encode("utf-8"))
            return

        # ── Ctrl+D → EOF ──────────────────────────────────────────────
        if ctrl and key == Qt.Key_D:
            self.char_written.emit(b"\x04")
            return

        # ── Ctrl+L → clear screen ─────────────────────────────────────
        if ctrl and key == Qt.Key_L:
            self.clear()
            self._input_anchor = 0
            self.char_written.emit(b"\x0c")   # also send to shell for PS1 redraw
            return

        # ── Ctrl+A → beginning of line ───────────────────────────────
        if ctrl and key == Qt.Key_A:
            self.char_written.emit(b"\x01")
            return

        # ── Ctrl+E → end of line ──────────────────────────────────────
        if ctrl and key == Qt.Key_E:
            self.char_written.emit(b"\x05")
            return

        # ── Ctrl+U → kill line ───────────────────────────────────────
        if ctrl and key == Qt.Key_U:
            self._clear_input()
            self.char_written.emit(b"\x15")
            return

        # ── Ctrl+W → kill word ───────────────────────────────────────
        if ctrl and key == Qt.Key_W:
            self.char_written.emit(b"\x17")
            return

        # ── Tab → completion ─────────────────────────────────────────
        if key == Qt.Key_Tab:
            input_so_far = self._get_input_text()
            self._clear_input()
            self.char_written.emit((input_so_far + "\t").encode("utf-8"))
            return

        # ── Enter → send line ────────────────────────────────────────
        if key in (Qt.Key_Return, Qt.Key_Enter):
            text = self._get_input_text()
            if text:
                self._history.append(text)
                self._hist_idx = len(self._history)
            self.char_written.emit((text + "\n").encode("utf-8"))
            return

        # ── Backspace — only delete user's own input ─────────────────
        if key == Qt.Key_Backspace:
            if len(self.toPlainText()) > self._input_anchor:
                super().keyPressEvent(event)
            return

        # ── Arrow up/down → history ───────────────────────────────────
        if key == Qt.Key_Up:
            self._nav_history(-1)
            return
        if key == Qt.Key_Down:
            self._nav_history(1)
            return

        # ── Left arrow — don't go before anchor ──────────────────────
        if key == Qt.Key_Left:
            c = self.textCursor()
            if c.position() > self._input_anchor:
                super().keyPressEvent(event)
            return

        # ── Home → jump to anchor ─────────────────────────────────────
        if key == Qt.Key_Home:
            c = self.textCursor()
            c.setPosition(self._input_anchor)
            self.setTextCursor(c)
            return

        # ── Printable characters ──────────────────────────────────────
        if event.text() and not ctrl:
            self._ensure_cursor_at_end()
            super().keyPressEvent(event)
            return

        # Everything else (page up/down for scroll, etc.)
        super().keyPressEvent(event)

    def _nav_history(self, direction: int):
        if not self._history:
            return
        self._hist_idx = max(0, min(len(self._history) - 1,
                                    self._hist_idx + direction))
        self._clear_input()
        entry = self._history[self._hist_idx]
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        # Insert history entry with default formatting
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_DEFAULT_FG))
        cursor.insertText(entry, fmt)

    def mousePressEvent(self, event):
        # Allow clicks anywhere for selection, but snap cursor to end for typing
        super().mousePressEvent(event)
        # Don't snap on right-click (context menu) or middle-click
        if event.button() == Qt.LeftButton:
            QTimer.singleShot(0, self._snap_if_before_anchor)

    def _snap_if_before_anchor(self):
        """If user clicked before the anchor (output area), snap to end."""
        c = self.textCursor()
        if not c.hasSelection() and c.position() < self._input_anchor:
            c.movePosition(QTextCursor.End)
            self.setTextCursor(c)

    def contextMenuEvent(self, event):
        from PyQt5.QtWidgets import QMenu
        has_sel = self.textCursor().hasSelection()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 5px 22px 5px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected { background: #094771; }
            QMenu::item:disabled { color: #555; }
            QMenu::separator { height:1px; background:#333; margin:3px 8px; }
        """)

        copy_act   = menu.addAction("📋  Copy")
        paste_act  = menu.addAction("📌  Paste")
        menu.addSeparator()

        kill_act   = menu.addAction("⛔  Force Kill (Ctrl+C)")
        kill_act.setToolTip("Sends raw interrupt byte to foreground process")
        menu.addSeparator()

        clear_act  = menu.addAction("🧹  Clear terminal")

        copy_act.setEnabled(has_sel)

        act = menu.exec_(event.globalPos())

        if act == copy_act:
            self.copy()

        elif act == paste_act:
            clipboard = QApplication.clipboard().text()
            if clipboard:
                self.char_written.emit(clipboard.encode("utf-8"))

        elif act == kill_act:
            # Write \x03 (ETX / Ctrl+C) directly to PTY — kills foreground
            # process group via kernel line discipline. Safe: only the
            # subprocess is killed, not the shell or the Qt application.
            self.char_written.emit(b"\x03")
            # Also send \x15 (Ctrl+U) to clear any partial line afterwards
            self.char_written.emit(b"\x15")

        elif act == clear_act:
            self.clear()
            self._input_anchor = 0


# ── Single terminal pane ──────────────────────────────────────────────────────
class TerminalPane(QWidget):
    """
    One terminal session: PTY-backed shell rendered in a unified TerminalDisplay.
    Emits `closed` when the shell exits or the pane is killed.
    """
    closed = pyqtSignal(object)

    def __init__(self, cwd: str | None = None):
        super().__init__()
        self._cwd    = cwd or str(Path.home())
        self._master = None
        self._pid    = None
        self._reader = None
        self._parser      = AnsiParser()
        self._last_cols   = 80
        self._last_rows   = 24
        self._is_resizing = False
        self._echo_suppress = ""   # text we just sent; strip its echo

        # Debounce resize: only send TIOCSWINSZ 300ms after the last resize event
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(300)
        self._resize_timer.timeout.connect(self._flush_resize)

        self._build_ui()
        self._spawn_shell()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._display = TerminalDisplay()
        self._display.char_written.connect(self._write_to_pty)
        # Ctrl+C is now sent as \x03 via char_written; no separate sigint_req needed
        layout.addWidget(self._display)
        self._display.setFocus()

    # ── shell spawning ────────────────────────────────────────────────
    def _spawn_shell(self):
        shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
        self._master, slave = pty.openpty()
        self._set_pty_size(80, 24)

        flags = fcntl.fcntl(self._master, fcntl.F_GETFL)
        fcntl.fcntl(self._master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._pid = os.fork()
        if self._pid == 0:
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
        if self._master is None:
            return
        char_w = self._display.fontMetrics().horizontalAdvance("M")
        char_h = self._display.fontMetrics().height()
        if char_w > 0 and char_h > 0:
            self._last_cols = max(10, self._display.width()  // char_w)
            self._last_rows = max(4,  self._display.height() // char_h)
        # Debounce: restart the timer on every resize event.
        # _flush_resize fires only once, 300ms after the user stops dragging.
        self._resize_timer.start()

    def _flush_resize(self):
        """Actually send TIOCSWINSZ after the resize settles."""
        if self._master is None:
            return
        self._is_resizing = True
        self._set_pty_size(self._last_cols, self._last_rows)
        # Give bash a moment to emit its redrawn prompt, then swallow it
        QTimer.singleShot(120, self._finish_resize)

    def _finish_resize(self):
        """
        After bash redraws the prompt in response to SIGWINCH, trim any
        duplicate prompt lines that were appended to the display.
        We do this by truncating back to the last anchor point.
        """
        self._is_resizing = False

    # ── incoming data from PTY ────────────────────────────────────────
    def _on_data(self, raw: bytes):
        # While a resize is in flight, bash sends a redrawn prompt via SIGWINCH.
        # Swallow that output entirely — we already have the prompt on screen.
        if self._is_resizing:
            return

        filtered = self._strip_cursor_sequences(raw)

        # ── Echo suppression ──────────────────────────────────────────
        # The PTY echoes back exactly what we typed. Strip it so the
        # command doesn't appear twice. We match against the start of the
        # decoded chunk (after cursor-sequence stripping).
        if self._echo_suppress:
            decoded = filtered.decode("utf-8", errors="replace")
            # The echo arrives as the typed text followed by \r\n
            echo_candidate = self._echo_suppress
            if echo_candidate in decoded:
                decoded = decoded.replace(echo_candidate, "", 1)
                filtered = decoded.encode("utf-8")
            self._echo_suppress = ""

        spans    = self._parser.feed(filtered)

        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)

        for text, fmt in spans:
            text = text.replace("\r\n", "\n").replace("\r", "")
            while "\x08" in text:
                idx  = text.index("\x08")
                text = text[:max(0, idx - 1)] + text[idx + 1:]
            if text:
                cursor.insertText(text, fmt)

        self._display.setTextCursor(cursor)
        self._display.ensureCursorVisible()
        # Lock: everything written by PTY is "output", user types after this
        self._display._set_anchor()

    def _strip_cursor_sequences(self, raw: bytes) -> bytes:
        text = raw.decode("utf-8", errors="replace")
        def _keep_sgr(m):
            return m.group(0) if m.group(2) == "m" else ""
        return _ESC_RE.sub(_keep_sgr, text).encode("utf-8")

    def _on_shell_exit(self):
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#888888"))
        fmt.setFontItalic(True)
        cursor.insertText("\n[Process exited]\n", fmt)
        self._display.setTextCursor(cursor)
        self.closed.emit(self)

    # ── writing to PTY ────────────────────────────────────────────────
    def _write_to_pty(self, data: bytes):
        if self._master is not None:
            try:
                os.write(self._master, data)
                # Track printable text for echo suppression.
                # The PTY will echo back exactly what we sent (minus the \n
                # which becomes \r\n in the output stream).
                text = data.decode("utf-8", errors="replace")
                printable = text.rstrip("\n\r")
                if printable:
                    self._echo_suppress = printable
            except OSError:
                pass

    def _send_signal(self, sig):
        if self._pid:
            try:
                os.killpg(os.getpgid(self._pid), sig)
            except (OSError, ProcessLookupError):
                pass

    # ── public helpers ────────────────────────────────────────────────
    def set_cwd(self, path: str):
        if os.path.isdir(path) and self._master:
            try:
                os.write(self._master, f'cd "{path}"\n'.encode())
            except OSError:
                pass

    def focus_input(self):
        self._display.setFocus()

    def kill(self):
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
