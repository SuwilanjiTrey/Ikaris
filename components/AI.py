"""
AI.py  —  Ikaris AI Panel (batched streaming, tuned)
=====================================================
Batches tokens for BATCH_MS milliseconds before emitting to JS.
Set higher = fewer bridge calls = less CPU = smoother on low-end devices.
"""

import os
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QApplication
from PyQt5.QtCore    import QUrl, pyqtSlot, QObject, pyqtSignal, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel       import QWebChannel


OLLAMA_BASE         = "http://192.168.1.206:5001" #http://127.0.0.1:11434
MAX_FILE_SIZE_BYTES = 256 * 1024
MAX_FILES_RETURNED  = 300

# ── Tune this value ────────────────────────────────────────────────────────
# 500ms  = chunks of ~1-2 sentences, very light on CPU (recommended for you)
# 300ms  = slightly more frequent updates, still low overhead
# 150ms  = original batch setting
BATCH_MS = 500

READABLE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx',
    '.html', '.htm', '.css', '.json', '.md', '.markdown',
    '.txt', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg',
    '.kt', '.java', '.cpp', '.c', '.h', '.hpp',
    '.sh', '.bash', '.zsh', '.gradle', '.properties',
    '.sql', '.gitignore', '.env', '.dockerfile',
    '.rs', '.go', '.rb', '.php', '.swift',
}
SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', '.gradle',
    'build', 'dist', '.venv', 'venv', '.idea', '.vscode',
    'target', '.next', 'out', '.cache',
}


class AIBridge(QObject):
    streamChunk  = pyqtSignal(str)   # batched tokens
    streamDone   = pyqtSignal()
    streamError  = pyqtSignal(str)
    ollamaStatus = pyqtSignal(bool)

    def __init__(self, main_window=None):
        super().__init__()
        self.main_window  = main_window
        self.project_root = None

        self._cancel_flag   = threading.Event()
        self._stream_thread = None
        self._buf_lock      = threading.Lock()
        self._token_buf     = []
        self._worker_done   = False
        self._worker_error  = None

        self._flush_timer = QTimer()
        self._flush_timer.setInterval(BATCH_MS)
        self._flush_timer.timeout.connect(self._flush)

    # ── Ollama ─────────────────────────────────────────────────────────────

    @pyqtSlot(result=bool)
    def checkOllama(self):
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3):
                self.ollamaStatus.emit(True)
                return True
        except Exception:
            self.ollamaStatus.emit(False)
            return False

    @pyqtSlot(result=str)
    def getModels(self):
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=4) as r:
                data = json.loads(r.read().decode())
                self.ollamaStatus.emit(True)
                return json.dumps([{"name": m["name"]} for m in data.get("models", [])])
        except Exception:
            self.ollamaStatus.emit(False)
            return json.dumps([])

    # ── Chat ───────────────────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def chat(self, model, messages_json):
        if self._stream_thread and self._stream_thread.is_alive():
            self._cancel_flag.set()
            self._stream_thread.join(timeout=3)

        self._cancel_flag.clear()
        self._worker_done  = False
        self._worker_error = None
        with self._buf_lock:
            self._token_buf.clear()

        self._stream_thread = threading.Thread(
            target=self._worker,
            args=(model, json.loads(messages_json)),
            daemon=True,
        )
        self._flush_timer.start()
        self._stream_thread.start()

    def _worker(self, model, messages):
        payload = json.dumps({
            "model": model, "messages": messages, "stream": True
        }).encode()
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                for raw in resp:
                    if self._cancel_flag.is_set():
                        return
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        tok = obj.get("message", {}).get("content", "")
                        if tok:
                            with self._buf_lock:
                                self._token_buf.append(tok)
                        if obj.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
        except urllib.error.URLError as e:
            self._worker_error = str(e.reason)
        except Exception as e:
            self._worker_error = str(e)
        finally:
            self._worker_done = True

    def _flush(self):
        """Runs on the Qt main thread every BATCH_MS ms."""
        # handle error
        if self._worker_error:
            err = self._worker_error
            self._worker_error = None
            self._flush_timer.stop()
            self.streamError.emit(f"Ollama error: {err}")
            return

        # drain buffer
        with self._buf_lock:
            batch = "".join(self._token_buf)
            self._token_buf.clear()

        if batch:
            self.streamChunk.emit(batch)

        # worker finished — one final flush already happened, signal done
        if self._worker_done:
            self._worker_done = False
            self._flush_timer.stop()
            self.streamDone.emit()

    @pyqtSlot()
    def cancelStream(self):
        self._cancel_flag.set()
        self._flush_timer.stop()

    # ── Clipboard ──────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def copyToClipboard(self, text):
        """Copy via Python — Qt WebEngine blocks navigator.clipboard on file://"""
        QApplication.clipboard().setText(text)

    # ── Files ──────────────────────────────────────────────────────────────

    @pyqtSlot(str, result=str)
    def readFile(self, path):
        try:
            p = Path(path)
            if not p.exists():
                return f"[Error: not found: {path}]"
            if p.stat().st_size > MAX_FILE_SIZE_BYTES:
                return f"[Skipped: too large ({p.stat().st_size // 1024} KB)]"
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[Error reading {path}: {e}]"

    @pyqtSlot(result=str)
    def getProjectFiles(self):
        if not self.project_root or not os.path.isdir(self.project_root):
            return json.dumps([])
        files = []
        for root, dirs, fnames in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in fnames:
                ext = Path(fname).suffix.lower()
                if ext not in READABLE_EXTENSIONS:
                    continue
                full = os.path.join(root, fname)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                if size > MAX_FILE_SIZE_BYTES:
                    continue
                rel = os.path.relpath(full, self.project_root)
                files.append({"name": fname, "path": full, "rel": rel, "ext": ext})
                if len(files) >= MAX_FILES_RETURNED:
                    break
            if len(files) >= MAX_FILES_RETURNED:
                break
        return json.dumps(files)

    @pyqtSlot(result=str)
    def getProjectRoot(self):
        return self.project_root or ""


# ───────────────────────────────────────────────────────────────────────────

class AIPanel:
    def __init__(self, container, layout, main_window=None, channel=None):
        self.main_window  = main_window
        self.project_root = None
        self.bridge       = AIBridge(main_window)

        self._channel = channel if channel is not None else QWebChannel()
        self._channel.registerObject("AIBridge", self.bridge)

        self.view = QWebEngineView(container)
        self.view.page().setWebChannel(self._channel)
        self.view.load(QUrl.fromLocalFile(os.path.abspath("web/ai.html")))
        self.view.loadFinished.connect(self._on_load_finished)

        layout.addWidget(self.view)

    def _on_load_finished(self, ok):
        if ok:
            self._push_project_files()

    def set_project_root(self, path):
        self.project_root        = path
        self.bridge.project_root = path
        self._push_project_files()

    def _push_project_files(self):
        escaped = json.dumps(self.bridge.getProjectFiles())
        self.view.page().runJavaScript(
            f"if(window.setProjectFiles) window.setProjectFiles({escaped});"
        )


class FixedAIButton:
    def __init__(self, *a, **kw): pass
    def show(self):            pass
    def setVisible(self, v):   pass
    def set_position(self, p): pass
    def update_position(self): pass

