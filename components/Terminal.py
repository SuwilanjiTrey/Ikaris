"""
terminal_windows.py  —  Embedded terminal widget for Ikaris Dev Studio (Windows)
─────────────────────────────────────────────────────────────────────────────
Windows port of terminal.py.

WHY THIS ISN'T A DROP-IN PORT
──────────────────────────────
The original relied on a real Unix PTY (`pty.openpty` + `termios`/`fcntl` +
`os.fork`). Windows has no equivalent without the ConPTY API, which QProcess
does not expose. This version hosts `cmd.exe` as a plain QProcess with its
stdin/stdout connected via pipes instead of a pseudo-terminal. Concretely,
that changes behaviour in a few ways worth knowing before you rely on this:

  • No real console  →  full-screen / curses-style programs (vim, less,
    htop-alikes, etc.) will not render correctly. This is a line-oriented
    shell, not a general terminal emulator.
  • No kernel echo  →  a PTY echoes typed input back to you; a piped
    cmd.exe does not. So the widget itself is now the source of truth for
    what's on screen while you type — the full line is only sent to the
    process on Enter. (This actually removes the old `_echo_suppress` hack
    entirely — nothing to suppress anymore.)
  • No console-attached line editing  →  cmd.exe's own arrow-key history
    and Tab completion only work when it owns a real console. Over a pipe
    they're inert, so Ctrl+A/E/U/W, Tab, and history are now handled
    locally in the widget instead of being forwarded as control bytes.
  • No SIGINT byte  →  Windows delivers interrupts via console control
    events, not a stream byte. Ctrl+C is implemented as a best-effort
    AttachConsole + GenerateConsoleCtrlEvent call (see `_send_ctrl_c`).
    It can fail silently against processes that install their own
    handler — there is no fully reliable PTY-style SIGINT without ConPTY.
  • No TIOCSWINSZ  →  there's no real resize signal to deliver, so the
    old resize-debounce/redraw-swallowing logic is gone. Font metrics
    still drive local wrapping; the child process just never finds out
    the "window" changed size.
  • EOF is Ctrl+Z, not Ctrl+D  →  Windows' console EOF marker is 0x1A.

Everything else (ANSI parsing, the tab bar, the manager) is unchanged in
spirit and still Windows-safe as-is.
"""

import sys
import ctypes
import re
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QTabWidget, QTabBar,
    QLabel, QApplication, QSizePolicy,
)
from PyQt5.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor,
)
from PyQt5.QtCore import (
    Qt, QTimer, QObject, QProcess, QProcessEnvironment, pyqtSignal,
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


# ── Windows console-signal plumbing ──────────────────────────────────────────
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW         = 0x08000000
CTRL_C_EVENT             = 0


def _configure_windows_process(process: QProcess):
    """
    Give the child its own hidden console + process group.

    CREATE_NEW_PROCESS_GROUP is required so GenerateConsoleCtrlEvent can
    target just this child (and its descendants) rather than every console
    process attached to whatever console we happen to be near.
    CREATE_NO_WINDOW stops a visible console window from flashing up, since
    a plain console-subsystem child would otherwise get one automatically
    when its parent (this GUI app) has no console of its own.
    """
    if sys.platform != "win32":
        return
    try:
        def modifier(args):
            args.flags |= CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        process.setCreateProcessArgumentsModifier(modifier)
    except AttributeError:
        # Older PyQt5/Qt without this hook — Ctrl+C simply won't work below.
        pass


def _send_ctrl_c(pid: int) -> bool:
    """
    Best-effort SIGINT-equivalent for a Windows console process.

    There is no byte we can write to stdin that means "interrupt" on
    Windows the way 0x03 does on a Unix PTY — control events are delivered
    to whole console process groups via GenerateConsoleCtrlEvent, and only
    a process attached to that console can raise one. So: detach from
    whatever console we have (none, normally), attach to the child's
    console, fire the event at its process group, then detach again.

    Not guaranteed to work — a process that installed its own
    SetConsoleCtrlHandler can swallow it, and some processes never
    respond to it at all. That's an inherent Windows limitation, not a
    bug in this code.
    """
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.windll.kernel32
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        return False
    try:
        # Ignore the event in our own process, or the IDE itself would
        # also receive and act on the Ctrl+C we're about to generate.
        kernel32.SetConsoleCtrlHandler(None, True)
        kernel32.GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0)
        return True
    finally:
        kernel32.FreeConsole()
        kernel32.SetConsoleCtrlHandler(None, False)


# ── ANSI escape sequence parser ───────────────────────────────────────────────
# Unchanged from the Unix version — some Windows console programs (git,
# npm, modern PowerShell-aware tools, etc.) still emit ANSI/VT sequences
# even over a redirected pipe, others fall back to plain text when they
# detect stdout isn't a real console. Either way this is harmless to keep.
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


# ── the input/output surface ─────────────────────────────────────────────────
class TerminalDisplay(QTextEdit):
    """
    A QTextEdit that acts as both the output display AND the input surface.

    Because a piped cmd.exe doesn't echo or line-edit for us, everything
    the user types lives locally in this widget until Enter sends the
    whole line. Ctrl+A/E/U/W move or delete within that local buffer
    instead of being forwarded as control bytes.
    """

    # signals to the owning TerminalPane
    line_submitted      = pyqtSignal(bytes)  # full line + terminator → stdin
    interrupt_requested = pyqtSignal()       # Ctrl+C with no selection

    def __init__(self):
        super().__init__()
        self.setFont(QFont("Consolas", 11))
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

        # Position after the last process output — user may only type here or later
        self._input_anchor = 0
        self._history: list[str] = []
        self._hist_idx = -1

    # ── anchor management ─────────────────────────────────────────────
    def _set_anchor(self):
        """Called after every write from the process; locks the editable region."""
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

    def _insert_local(self, text: str):
        """Insert text into the input region using default formatting."""
        cursor = self.textCursor()
        self._ensure_cursor_at_end()
        cursor = self.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_DEFAULT_FG))
        cursor.insertText(text, fmt)

    # ── keyboard handling ─────────────────────────────────────────────
    def keyPressEvent(self, event):
        key   = event.key()
        mods  = event.modifiers()
        ctrl  = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)

        # ── Ctrl+Shift+C → explicit copy ─────────────────────────────
        if ctrl and shift and key == Qt.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            return

        # ── Ctrl+C → copy if something's selected, else interrupt ───
        # (Windows has no SIGINT byte; interrupting is handled by the
        # owning TerminalPane via GenerateConsoleCtrlEvent — see
        # _send_ctrl_c. It's best-effort, not guaranteed.)
        if ctrl and key == Qt.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            else:
                self.interrupt_requested.emit()
            return

        # ── Paste: Ctrl+V ─────────────────────────────────────────────
        # Pasted text becomes part of the pending command line — it is
        # inserted locally, not sent immediately (there's no live echo
        # to rely on here, unlike the PTY version).
        if ctrl and key == Qt.Key_V:
            clipboard = QApplication.clipboard().text()
            if clipboard:
                self._insert_local(clipboard)
            return

        # ── Ctrl+D → Windows EOF is Ctrl+Z, not Ctrl+D ───────────────
        # Send whatever's typed so far, followed by the ^Z EOF marker.
        if ctrl and key == Qt.Key_D:
            text = self._get_input_text()
            self._clear_input()
            self.line_submitted.emit((text + "\x1a\r\n").encode("utf-8"))
            return

        # ── Ctrl+L → clear screen locally, and re-issue `cls` so the
        #    shell's own idea of the screen matches what we show ─────
        if ctrl and key == Qt.Key_L:
            self.clear()
            self._input_anchor = 0
            self.line_submitted.emit(b"cls\r\n")
            return

        # ── Ctrl+A → local: jump to start of input ───────────────────
        if ctrl and key == Qt.Key_A:
            c = self.textCursor()
            c.setPosition(self._input_anchor)
            self.setTextCursor(c)
            return

        # ── Ctrl+E → local: jump to end of input ─────────────────────
        if ctrl and key == Qt.Key_E:
            c = self.textCursor()
            c.movePosition(QTextCursor.End)
            self.setTextCursor(c)
            return

        # ── Ctrl+U → local: kill whole input line ────────────────────
        if ctrl and key == Qt.Key_U:
            self._clear_input()
            return

        # ── Ctrl+W → local: kill previous word ───────────────────────
        if ctrl and key == Qt.Key_W:
            c = self.textCursor()
            pos = c.position()
            if pos > self._input_anchor:
                c.setPosition(self._input_anchor)
                c.setPosition(pos, QTextCursor.KeepAnchor)
                fragment = c.selectedText()
                trimmed  = fragment.rstrip()
                cut      = len(fragment) - len(trimmed)
                word_start = trimmed.rfind(" ") + 1
                c.setPosition(self._input_anchor + word_start)
                c.setPosition(pos - cut, QTextCursor.KeepAnchor)
                c.removeSelectedText()
            return

        # ── Tab → cmd.exe can't complete over a pipe, so just insert
        #    a literal tab rather than pretending to complete ────────
        if key == Qt.Key_Tab:
            self._insert_local("\t")
            return

        # ── Enter → send the whole line ──────────────────────────────
        if key in (Qt.Key_Return, Qt.Key_Enter):
            text = self._get_input_text()
            if text:
                self._history.append(text)
                self._hist_idx = len(self._history)
            self.line_submitted.emit((text + "\r\n").encode("utf-8"))
            return

        # ── Backspace — only delete user's own input ─────────────────
        if key == Qt.Key_Backspace:
            if len(self.toPlainText()) > self._input_anchor:
                super().keyPressEvent(event)
            return

        # ── Arrow up/down → local history ────────────────────────────
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
        self._insert_local(entry)

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
        menu = QMenu(self)
        has_sel = self.textCursor().hasSelection()

        copy_act  = menu.addAction("Copy")
        paste_act = menu.addAction("Paste")
        menu.addSeparator()
        kill_act  = menu.addAction("Send Ctrl+C")
        clear_act = menu.addAction("Clear")

        copy_act.setEnabled(has_sel)

        act = menu.exec_(event.globalPos())

        if act == copy_act:
            self.copy()

        elif act == paste_act:
            clipboard = QApplication.clipboard().text()
            if clipboard:
                self._insert_local(clipboard)

        elif act == kill_act:
            self.interrupt_requested.emit()

        elif act == clear_act:
            self.clear()
            self._input_anchor = 0


# ── Single terminal pane ──────────────────────────────────────────────────────
class TerminalPane(QWidget):
    """
    One terminal session: cmd.exe hosted via QProcess, rendered in a
    unified TerminalDisplay. Emits `closed` when the shell exits or the
    pane is killed.
    """
    closed = pyqtSignal(object)

    def __init__(self, cwd: str | None = None):
        super().__init__()
        self._cwd     = cwd or str(Path.home())
        self._process: QProcess | None = None
        self._parser  = AnsiParser()

        self._build_ui()
        self._spawn_shell()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._display = TerminalDisplay()
        self._display.line_submitted.connect(self._write_to_process)
        self._display.interrupt_requested.connect(self._interrupt)
        layout.addWidget(self._display)
        self._display.setFocus()

    # ── shell spawning ────────────────────────────────────────────────
    def _spawn_shell(self):
        self._process = QProcess(self)
        self._process.setWorkingDirectory(self._cwd)
        # Merge stdout/stderr the way a real terminal would present them
        # as a single interleaved stream.
        self._process.setProcessChannelMode(QProcess.MergedChannels)

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PROMPT", "$P$G")  # normal "C:\path>" prompt
        self._process.setProcessEnvironment(env)

        _configure_windows_process(self._process)

        self._process.readyRead.connect(self._on_data)
        self._process.finished.connect(self._on_shell_exit)
        self._process.errorOccurred.connect(self._on_process_error)

        self._process.start("cmd.exe", [])
        if not self._process.waitForStarted(3000):
            self._on_process_error(self._process.error())

    # ── incoming data from the process ────────────────────────────────
    def _on_data(self):
        raw = bytes(self._process.readAll())
        if not raw:
            return

        filtered = self._strip_cursor_sequences(raw)
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
        # Lock: everything written by the process is "output", user types after this
        self._display._set_anchor()

    def _strip_cursor_sequences(self, raw: bytes) -> bytes:
        text = raw.decode("utf-8", errors="replace")
        def _keep_sgr(m):
            return m.group(0) if m.group(2) == "m" else ""
        return _ESC_RE.sub(_keep_sgr, text).encode("utf-8")

    def _on_shell_exit(self, exit_code: int, exit_status):
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#888888"))
        fmt.setFontItalic(True)
        cursor.insertText(f"\n[Process exited ({exit_code})]\n", fmt)
        self._display.setTextCursor(cursor)
        self.closed.emit(self)

    def _on_process_error(self, error):
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#ff5555"))
        fmt.setFontItalic(True)
        cursor.insertText(f"\n[Terminal error: {error}]\n", fmt)
        self._display.setTextCursor(cursor)

    # ── writing to the process ────────────────────────────────────────
    def _write_to_process(self, data: bytes):
        if self._process is not None:
            self._process.write(data)

    def _interrupt(self):
        if self._process is None:
            return
        pid_obj = self._process.processId()
        if pid_obj:
            _send_ctrl_c(int(pid_obj))

    # ── public helpers ────────────────────────────────────────────────
    def set_cwd(self, path: str):
        if Path(path).is_dir() and self._process is not None:
            # /d also switches drive letter, matching the "cd" a user
            # would type by hand on Windows.
            self._process.write(f'cd /d "{path}"\r\n'.encode())

    def focus_input(self):
        self._display.setFocus()

    def kill(self):
        if self._process is not None:
            self._process.readyRead.disconnect(self._on_data)
            self._process.finished.disconnect(self._on_shell_exit)
            self._process.errorOccurred.disconnect(self._on_process_error)
            # QProcess.terminate() on Windows posts WM_CLOSE to top-level
            # windows, which cmd.exe (headless, no window) doesn't have —
            # so it's unreliable here. kill() (TerminateProcess) is blunt
            # but is the version that actually works for a console child.
            self._process.kill()
            self._process.waitForFinished(500)
            self._process = None


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

        label = f"cmd {self._tab_count}"
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
        """Send 'cd /d <path>' to the currently active terminal."""
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
