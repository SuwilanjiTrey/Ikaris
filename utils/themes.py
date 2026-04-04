"""
themes.py  —  Theme engine for Ikaris Dev Studio
─────────────────────────────────────────────────
• Stores themes as JSON in  ~/.ikaris/themes/
• Applies themes to the live QApplication via setStyleSheet
• Exposes PyQt slots that the HTML theme editor calls via QWebChannel
• Emits theme_changed signal so other components can react

Usage in main.py:
    from utils.themes import ThemeEngine

    # In CodeEditor.__init__:
    self.theme_engine = ThemeEngine(self)

    # Register on the web channel (reuse existing channel):
    self.channel.registerObject("ThemeEngine", self.theme_engine)

    # Wire the themes page:
    self.themes_page = QWebEngineView()
    self.themes_page.page().setWebChannel(self.channel)
    self.themes_page.load(QUrl.fromLocalFile(os.path.abspath("web/themes.html")))

    # Apply saved theme on startup:
    self.theme_engine.apply_saved_theme()
"""

import os
import json
from pathlib import Path

from PyQt5.QtCore  import QObject, pyqtSlot, pyqtSignal
from PyQt5.QtGui   import QFont, QColor
from PyQt5.QtWidgets import QApplication


# ── Storage ───────────────────────────────────────────────────────────────────
THEMES_DIR    = Path.home() / ".ikaris" / "themes"
SETTINGS_FILE = Path.home() / ".ikaris" / "settings.json"
THEMES_DIR.mkdir(parents=True, exist_ok=True)


# ── Built-in themes ───────────────────────────────────────────────────────────
BUILTIN_THEMES: dict[str, dict] = {
    "Ikaris Dark": {
        "name":            "Ikaris Dark",
        "builtin":         True,
        # UI structure
        "sidebar_bg":      "#1a1a1a",
        "sidebar_btn":     "#2a2a2a",
        "sidebar_hover":   "#3a3a3a",
        "sidebar_icon":    "#aaaaaa",
        "tree_bg":         "#1e1e1e",
        "tree_text":       "#cccccc",
        "tree_hover":      "#2a2a2a",
        "tree_selected":   "#094771",
        "tree_header_bg":  "#1a1a1a",
        "editor_bg":       "#1e1e1e",
        "editor_text":     "#d4d4d4",
        "editor_line_hl":  "#2a2a2a",
        "editor_gutter_bg":"#1a1a1a",
        "editor_gutter_fg":"#0091E7",
        "tab_bar_bg":      "#252526",
        "tab_bg":          "#2d2d2d",
        "tab_active_bg":   "#1e1e1e",
        "tab_text":        "#888888",
        "tab_active_text": "#ffffff",
        "tab_border":      "#007acc",
        "scrollbar":       "#424242",
        # Syntax colours
        "syn_keyword":     "#C792EA",
        "syn_builtin":     "#FFCB6B",
        "syn_string":      "#C3E88D",
        "syn_number":      "#F78C6C",
        "syn_comment":     "#546E7A",
        "syn_function":    "#82AAFF",
        "syn_class":       "#FFCB6B",
        "syn_operator":    "#89DDFF",
        # Terminal
        "term_bg":         "#1a1a1a",
        "term_text":       "#e0e0e0",
        "term_green":      "#55FF55",
        # Typography
        "editor_font":     "Courier New",
        "editor_font_size": 12,
        "ui_font":         "Segoe UI",
        "ui_font_size":    12,
    },
    "Ikaris Light": {
        "name":            "Ikaris Light",
        "builtin":         True,
        "sidebar_bg":      "#f3f3f3",
        "sidebar_btn":     "#e8e8e8",
        "sidebar_hover":   "#d0d0d0",
        "sidebar_icon":    "#444444",
        "tree_bg":         "#f8f8f8",
        "tree_text":       "#333333",
        "tree_hover":      "#e8e8e8",
        "tree_selected":   "#cce5ff",
        "tree_header_bg":  "#eeeeee",
        "editor_bg":       "#ffffff",
        "editor_text":     "#1e1e1e",
        "editor_line_hl":  "#f0f0f0",
        "editor_gutter_bg":"#f0f0f0",
        "editor_gutter_fg":"#0070c1",
        "tab_bar_bg":      "#ececec",
        "tab_bg":          "#e0e0e0",
        "tab_active_bg":   "#ffffff",
        "tab_text":        "#666666",
        "tab_active_text": "#111111",
        "tab_border":      "#0070c1",
        "scrollbar":       "#c0c0c0",
        "syn_keyword":     "#af00db",
        "syn_builtin":     "#795e26",
        "syn_string":      "#a31515",
        "syn_number":      "#098658",
        "syn_comment":     "#6a9955",
        "syn_function":    "#0000ff",
        "syn_class":       "#267f99",
        "syn_operator":    "#000000",
        "term_bg":         "#f8f8f8",
        "term_text":       "#1e1e1e",
        "term_green":      "#008000",
        "editor_font":     "Courier New",
        "editor_font_size": 12,
        "ui_font":         "Segoe UI",
        "ui_font_size":    12,
    },
    "Midnight Ocean": {
        "name":            "Midnight Ocean",
        "builtin":         True,
        "sidebar_bg":      "#0a1628",
        "sidebar_btn":     "#0d1f3c",
        "sidebar_hover":   "#152a4e",
        "sidebar_icon":    "#5a8fd8",
        "tree_bg":         "#0c1a2e",
        "tree_text":       "#a8c4e8",
        "tree_hover":      "#112240",
        "tree_selected":   "#1a3a5c",
        "tree_header_bg":  "#0a1628",
        "editor_bg":       "#0d1b2a",
        "editor_text":     "#cdd6f4",
        "editor_line_hl":  "#112240",
        "editor_gutter_bg":"#0a1628",
        "editor_gutter_fg":"#3a7bd5",
        "tab_bar_bg":      "#091525",
        "tab_bg":          "#0c1a2e",
        "tab_active_bg":   "#0d1b2a",
        "tab_text":        "#5a8fd8",
        "tab_active_text": "#cdd6f4",
        "tab_border":      "#3a7bd5",
        "scrollbar":       "#1a3a5c",
        "syn_keyword":     "#89b4fa",
        "syn_builtin":     "#fab387",
        "syn_string":      "#a6e3a1",
        "syn_number":      "#fab387",
        "syn_comment":     "#45475a",
        "syn_function":    "#89dceb",
        "syn_class":       "#f9e2af",
        "syn_operator":    "#cba6f7",
        "term_bg":         "#091525",
        "term_text":       "#cdd6f4",
        "term_green":      "#a6e3a1",
        "editor_font":     "JetBrains Mono",
        "editor_font_size": 12,
        "ui_font":         "Segoe UI",
        "ui_font_size":    12,
    },
    "Solarized Dark": {
        "name":            "Solarized Dark",
        "builtin":         True,
        "sidebar_bg":      "#002b36",
        "sidebar_btn":     "#073642",
        "sidebar_hover":   "#094652",
        "sidebar_icon":    "#839496",
        "tree_bg":         "#002b36",
        "tree_text":       "#839496",
        "tree_hover":      "#073642",
        "tree_selected":   "#073642",
        "tree_header_bg":  "#00212b",
        "editor_bg":       "#002b36",
        "editor_text":     "#839496",
        "editor_line_hl":  "#073642",
        "editor_gutter_bg":"#00212b",
        "editor_gutter_fg":"#268bd2",
        "tab_bar_bg":      "#001f27",
        "tab_bg":          "#00212b",
        "tab_active_bg":   "#002b36",
        "tab_text":        "#586e75",
        "tab_active_text": "#93a1a1",
        "tab_border":      "#268bd2",
        "scrollbar":       "#073642",
        "syn_keyword":     "#859900",
        "syn_builtin":     "#b58900",
        "syn_string":      "#2aa198",
        "syn_number":      "#d33682",
        "syn_comment":     "#586e75",
        "syn_function":    "#268bd2",
        "syn_class":       "#cb4b16",
        "syn_operator":    "#657b83",
        "term_bg":         "#001f27",
        "term_text":       "#839496",
        "term_green":      "#859900",
        "editor_font":     "Fira Code",
        "editor_font_size": 12,
        "ui_font":         "Segoe UI",
        "ui_font_size":    12,
    },
    "Dracula": {
        "name":            "Dracula",
        "builtin":         True,
        "sidebar_bg":      "#21222c",
        "sidebar_btn":     "#282a36",
        "sidebar_hover":   "#343746",
        "sidebar_icon":    "#6272a4",
        "tree_bg":         "#1e1f29",
        "tree_text":       "#f8f8f2",
        "tree_hover":      "#282a36",
        "tree_selected":   "#44475a",
        "tree_header_bg":  "#191a21",
        "editor_bg":       "#282a36",
        "editor_text":     "#f8f8f2",
        "editor_line_hl":  "#2d2f3f",
        "editor_gutter_bg":"#21222c",
        "editor_gutter_fg":"#6272a4",
        "tab_bar_bg":      "#191a21",
        "tab_bg":          "#21222c",
        "tab_active_bg":   "#282a36",
        "tab_text":        "#6272a4",
        "tab_active_text": "#f8f8f2",
        "tab_border":      "#bd93f9",
        "scrollbar":       "#44475a",
        "syn_keyword":     "#ff79c6",
        "syn_builtin":     "#8be9fd",
        "syn_string":      "#f1fa8c",
        "syn_number":      "#bd93f9",
        "syn_comment":     "#6272a4",
        "syn_function":    "#50fa7b",
        "syn_class":       "#8be9fd",
        "syn_operator":    "#ff79c6",
        "term_bg":         "#191a21",
        "term_text":       "#f8f8f2",
        "term_green":      "#50fa7b",
        "editor_font":     "Fira Code",
        "editor_font_size": 12,
        "ui_font":         "Segoe UI",
        "ui_font_size":    12,
    },
}


# ── QSS generator ─────────────────────────────────────────────────────────────
def theme_to_qss(t: dict) -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {t['sidebar_bg']};
        color: {t['editor_text']};
        font-family: "{t['ui_font']}";
        font-size: {t['ui_font_size']}pt;
        border: none;
    }}
    QSplitter::handle {{
        background: {t['tree_bg']};
        width: 1px; height: 1px;
    }}
    /* ── Sidebar ── */
    QPushButton, QToolButton {{
        background-color: {t['sidebar_btn']};
        color: {t['sidebar_icon']};
        border: none;
        border-radius: 6px;
        padding: 2px;
        margin: 1px;
    }}
    QPushButton:hover, QToolButton:hover {{
        background-color: {t['sidebar_hover']};
        color: {t['editor_text']};
    }}
    QPushButton:pressed, QToolButton:pressed {{
        background-color: {t['tree_selected']};
    }}
    /* ── File tree ── */
    QTreeView {{
        background-color: {t['tree_bg']};
        color: {t['tree_text']};
        border: none;
        font-family: "{t['ui_font']}";
        font-size: {t['ui_font_size']}pt;
    }}
    QTreeView::item:hover    {{ background-color: {t['tree_hover']};    }}
    QTreeView::item:selected {{ background-color: {t['tree_selected']}; color: {t['editor_text']}; }}
    QLabel {{
        background: {t['tree_header_bg']};
        color: {t['tree_text']};
        border: none;
    }}
    /* ── Editor ── */
    QTextEdit, QPlainTextEdit {{
        background-color: {t['editor_bg']};
        color: {t['editor_text']};
        border: none;
        font-family: "{t['editor_font']}";
        font-size: {t['editor_font_size']}pt;
        selection-background-color: {t['tree_selected']};
    }}
    /* ── Tabs ── */
    QTabWidget::pane {{
        background-color: {t['editor_bg']};
        border: none;
    }}
    QTabBar {{
        background-color: {t['tab_bar_bg']};
    }}
    QTabBar::tab {{
        background-color: {t['tab_bg']};
        color: {t['tab_text']};
        padding: 5px 10px;
        font-style: italic;
        border-bottom: 2px solid transparent;
        font-family: "{t['ui_font']}";
        font-size: {t['ui_font_size']}pt;
    }}
    QTabBar::tab:selected {{
        background-color: {t['tab_active_bg']};
        color: {t['tab_active_text']};
        border-bottom: 2px solid {t['tab_border']};
        font-style: normal;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {t['tree_hover']};
    }}
    /* ── Scrollbars ── */
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: {t['editor_bg']};
        width: 8px; height: 8px;
        border: none;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {t['scrollbar']};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; }}
    /* ── Menus ── */
    QMenu {{
        background-color: {t['tab_bg']};
        color: {t['editor_text']};
        border: 1px solid {t['tree_hover']};
        border-radius: 6px;
    }}
    QMenu::item:selected {{ background-color: {t['tree_selected']}; }}
    QMenu::separator      {{ background: {t['tree_hover']}; height: 1px; margin: 3px 8px; }}
    /* ── Input widgets ── */
    QLineEdit, QInputDialog QLineEdit {{
        background: {t['tree_bg']};
        color: {t['editor_text']};
        border: 1px solid {t['tree_hover']};
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QMessageBox {{ background: {t['sidebar_bg']}; }}
    QDialog      {{ background: {t['sidebar_bg']}; }}
    """


def theme_to_highlighter_palette(t: dict) -> dict:
    """Return the PALETTE dict that highlighter.py expects."""
    return {
        "keyword":   t["syn_keyword"],
        "keyword2":  t["syn_keyword"],
        "builtin":   t["syn_builtin"],
        "string":    t["syn_string"],
        "string2":   t["syn_string"],
        "number":    t["syn_number"],
        "comment":   t["syn_comment"],
        "function":  t["syn_function"],
        "class_name":t["syn_class"],
        "decorator": t["syn_keyword"],
        "operator":  t["syn_operator"],
        "type":      t["syn_class"],
        "tag":       t["syn_function"],
        "attr":      t["syn_keyword"],
        "selector":  t["syn_keyword"],
        "property":  t["syn_function"],
        "md_heading":t["syn_keyword"],
        "md_bold":   t["syn_builtin"],
        "md_italic": t["syn_string"],
        "md_code":   t["syn_number"],
        "md_link":   t["syn_function"],
        "error":     "#FF5370",
    }


# ── Storage helpers ───────────────────────────────────────────────────────────
def _load_user_themes() -> dict[str, dict]:
    themes = {}
    for f in THEMES_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if "name" in data:
                themes[data["name"]] = data
        except Exception:
            pass
    return themes


def _save_user_theme(theme: dict):
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_"
                        for c in theme.get("name", "custom"))
    path = THEMES_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(theme, indent=2))


def _delete_user_theme(name: str):
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    path = THEMES_DIR / f"{safe_name}.json"
    if path.exists():
        path.unlink()


def all_themes() -> dict[str, dict]:
    themes = dict(BUILTIN_THEMES)
    themes.update(_load_user_themes())
    return themes


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {"active_theme": "Ikaris Dark"}


def save_settings(data: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


# ── ThemeEngine (PyQt bridge) ─────────────────────────────────────────────────
class ThemeEngine(QObject):
    """
    QObject registered on QWebChannel as "ThemeEngine".
    Receives calls from themes.html and applies them live.
    """
    theme_changed = pyqtSignal(dict)   # emitted whenever a theme is applied

    def __init__(self, main_window):
        super().__init__()
        self._win     = main_window
        self._view    = None    # set via setup()
        self._current = load_settings().get("active_theme", "Ikaris Dark")

    def setup(self, themes_view):
        """Call after creating the QWebEngineView for themes.html."""
        self._view = themes_view

    def apply_saved_theme(self):
        themes = all_themes()
        theme  = themes.get(self._current) or list(themes.values())[0]
        self._apply(theme, save=False)

    # ── internal ──────────────────────────────────────────────────────────────

    def _apply(self, theme: dict, save: bool = True):
        qss = theme_to_qss(theme)
        QApplication.instance().setStyleSheet(qss)

        # Push updated palette to highlighter module at runtime
        try:
            import utils.highlighter as hl_mod
            hl_mod.PALETTE.update(theme_to_highlighter_palette(theme))
            # Re-highlight all open editors
            for path, data in getattr(self._win, "open_files", {}).items():
                editor = data.get("editor")
                if editor and hasattr(editor, "_highlighter") and editor._highlighter:
                    editor._highlighter.rehighlight()
        except Exception:
            pass

        self._current = theme.get("name", "Custom")
        self.theme_changed.emit(theme)

        if save:
            settings = load_settings()
            settings["active_theme"] = self._current
            save_settings(settings)

    def _push_js(self, js: str):
        if self._view:
            self._view.page().runJavaScript(js)

    # ── slots called from HTML ────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_all_themes(self) -> str:
        return json.dumps(list(all_themes().values()))

    @pyqtSlot(result=str)
    def get_current_theme(self) -> str:
        themes = all_themes()
        theme  = themes.get(self._current) or list(themes.values())[0]
        return json.dumps(theme)

    @pyqtSlot(str)
    def apply_theme_by_name(self, name: str):
        themes = all_themes()
        if name in themes:
            self._apply(themes[name])

    @pyqtSlot(str)
    def apply_theme_json(self, json_str: str):
        """Live-preview: called on every colour picker change."""
        try:
            theme = json.loads(json_str)
            self._apply(theme, save=False)
        except Exception as e:
            print(f"[ThemeEngine] apply_theme_json error: {e}")

    @pyqtSlot(str)
    def save_theme(self, json_str: str):
        try:
            theme = json.loads(json_str)
            _save_user_theme(theme)
            self._apply(theme, save=True)
            self._push_js(f'onThemeSaved({json.dumps(theme["name"])})')
        except Exception as e:
            print(f"[ThemeEngine] save_theme error: {e}")

    @pyqtSlot(str)
    def delete_theme(self, name: str):
        if name in BUILTIN_THEMES:
            return   # cannot delete built-ins
        _delete_user_theme(name)
        self._push_js(f'onThemeDeleted({json.dumps(name)})')

    @pyqtSlot(result=str)
    def get_settings(self) -> str:
        return json.dumps(load_settings())

    @pyqtSlot(str)
    def save_settings_json(self, json_str: str):
        try:
            data = json.loads(json_str)
            # Merge into existing
            existing = load_settings()
            existing.update(data)
            save_settings(existing)
            # Apply non-theme settings
            self._apply_aux_settings(data)
        except Exception as e:
            print(f"[ThemeEngine] save_settings error: {e}")

    def _apply_aux_settings(self, data: dict):
        """Apply word-wrap, tab-size, font etc to open editors."""
        for path, file_data in getattr(self._win, "open_files", {}).items():
            editor = file_data.get("editor")
            if not editor:
                continue
            if "editor_font" in data:
                from PyQt5.QtGui import QFont
                f = QFont(data["editor_font"],
                          int(data.get("editor_font_size", 12)))
                editor.setFont(f)
            if "word_wrap" in data:
                from PyQt5.QtWidgets import QPlainTextEdit
                editor.setLineWrapMode(
                    QPlainTextEdit.WidgetWidth if data["word_wrap"]
                    else QPlainTextEdit.NoWrap
                )
