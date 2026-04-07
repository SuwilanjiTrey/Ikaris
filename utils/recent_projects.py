"""
recent_projects.py  —  Recent project history for Ikaris Dev Studio
────────────────────────────────────────────────────────────────────
Stores up to 20 recent projects in ~/.ikaris/recent_projects.json.
Each entry: { name, path, type, language, opened_at }

Wire-up in main_editor.py:
    from components.recent_projects import RecentProjects

    # In __init__ (before initUI):
    self.recent_projects = RecentProjects()

    # Register on channel in setup_editor_and_image:
    self.channel.registerObject("RecentProjects", self.recent_projects)

    # Call when a project is opened (update_directory):
    self.recent_projects.record(path)

    # project_creator.py already calls open_project() which calls
    # update_directory() — so recording happens automatically there.
    # Just make sure update_directory calls self.recent_projects.record(path).
"""

import os
import json
from pathlib import Path
from datetime import datetime

from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal


RECENT_FILE = Path.home() / ".ikaris" / "recent_projects.json"
MAX_RECENT  = 20

# Language detection from project contents / path
_LANG_HINTS = {
    "package.json":      "javascript",
    "next.config.js":    "nextjs",
    "next.config.ts":    "nextjs",
    "vite.config.ts":    "vite",
    "vite.config.js":    "vite",
    "expo-env.d.ts":     "expo",
    "app.json":          "expo",        # expo projects have app.json
    "pom.xml":           "java",
    "build.gradle":      "kotlin",
    "build.gradle.kts":  "kotlin",
    "manage.py":         "django",
    "app.py":            "flask",
    "requirements.txt":  "python",
    "Cargo.toml":        "rust",
    "go.mod":            "go",
}

_ICON_MAP = {
    "javascript": "../images/fileIcons/js.png",
    "nextjs":     "../images/fileIcons/Next-js.png",
    "vite":       "../images/fileIcons/vite.png",
    "expo":       "../images/fileIcons/expo.png",
    "java":       "../images/fileIcons/java.png",
    "kotlin":     "../images/fileIcons/kotlin.png",
    "django":     "../images/fileIcons/django.png",
    "flask":      "../images/fileIcons/Flask.png",
    "python":     "../images/fileIcons/python.png",
    "rust":       "../images/fileIcons/Rust.png",
    "go":         "../images/fileIcons/Go.png",
    "unknown":    "📁",
}


def _detect_language(path: str) -> str:
    """Sniff a project directory for language/framework hints."""
    try:
        files = set(os.listdir(path))
    except OSError:
        return "unknown"

    for hint_file, lang in _LANG_HINTS.items():
        if hint_file in files:
            # Special case: app.json could be expo OR react-native
            if hint_file == "app.json" and "package.json" in files:
                return "expo"
            return lang

    # Fallback: scan for dominant extension
    exts = {}
    try:
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            exts[ext] = exts.get(ext, 0) + 1
    except Exception:
        pass

    if ".py"   in exts: return "python"
    if ".java" in exts: return "java"
    if ".kt"   in exts: return "kotlin"
    if ".rs"   in exts: return "rust"
    if ".go"   in exts: return "go"
    if ".js"   in exts: return "javascript"
    if ".ts"   in exts: return "javascript"

    return "unknown"


def _load() -> list[dict]:
    if RECENT_FILE.exists():
        try:
            return json.loads(RECENT_FILE.read_text())
        except Exception:
            pass
    return []


def _save(entries: list[dict]):
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(json.dumps(entries, indent=2))


class RecentProjects(QObject):
    """
    QObject registered on QWebChannel as "RecentProjects".
    Also exposes a Python-side record() method called from update_directory().
    """

    updated = pyqtSignal()   # emitted after any write

    def __init__(self):
        super().__init__()

    # ── Python-side API ───────────────────────────────────────────────────────

    def record(self, path: str, project_type: str = ""):
        """Call this from update_directory() every time a project is opened."""
        if not path or not os.path.isdir(path):
            return
        name = os.path.basename(path.rstrip("/\\"))
        lang = _detect_language(path)
        entry = {
            "name":      name,
            "path":      path,
            "type":      project_type or lang,
            "language":  lang,
            "icon":      _ICON_MAP.get(lang, "📁"),
            "opened_at": datetime.now().isoformat(timespec="seconds"),
        }
        entries = _load()
        # Remove duplicates for same path
        entries = [e for e in entries if e.get("path") != path]
        entries.insert(0, entry)
        entries = entries[:MAX_RECENT]
        _save(entries)
        self.updated.emit()

    # ── JS-callable slots ─────────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_recent(self) -> str:
        """Returns JSON array of recent project entries."""
        return json.dumps(_load())

    @pyqtSlot(str)
    def remove(self, path: str):
        """Remove a specific project from the recent list."""
        entries = [e for e in _load() if e.get("path") != path]
        _save(entries)

    @pyqtSlot()
    def clear_all(self):
        _save([])

    @pyqtSlot(str, result=bool)
    def path_exists(self, path: str) -> bool:
        return os.path.isdir(path)
