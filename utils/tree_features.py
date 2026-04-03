"""
tree_features.py  —  Right-click context menu + typed new-file dialog for the file tree.

Drop-in additions to CodeEditor.  Call:
    setup_tree_context_menu(self)   →  in initUI after setup_tree_view()
"""

import os
import shutil
from PyQt5.QtWidgets import (
    QMenu, QAction, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QMessageBox, QInputDialog, QWidget, QAbstractItemView,
)
from PyQt5.QtGui import QIcon, QFont, QColor
from PyQt5.QtCore import Qt, QSize


# ── File type catalogue ───────────────────────────────────────────────────────
# (display_name, extension, icon_path)
FILE_TYPES = [
    ("Python",          ".py",          "images/fileIcons/python.png"),
    ("JavaScript",      ".js",          "images/fileIcons/js.png"),
    ("TypeScript",      ".ts",          "images/fileIcons/typescript.png"),
    ("React JSX",       ".jsx",         "images/fileIcons/react.png"),
    ("React TSX",       ".tsx",         "images/fileIcons/react.png"),
    ("HTML",            ".html",        "images/fileIcons/html.png"),
    ("CSS",             ".css",         "images/fileIcons/css.png"),
    ("Java",            ".java",        "images/fileIcons/java2.png"),
    ("Kotlin",          ".kt",          "images/fileIcons/kotlin.png"),
    ("Kotlin Script",   ".kts",         "images/fileIcons/kts2.png"),
    ("Gradle",          ".gradle",      "images/fileIcons/gradle.png"),
    ("XML",             ".xml",         "images/fileIcons/xml.png"),
    ("JSON",            ".json",        "images/fileIcons/json.png"),
    ("TOML",            ".toml",        "images/fileIcons/toml.png"),
    ("Markdown",        ".md",          "images/fileIcons/markdown.png"),
    ("C++",             ".cpp",         "images/fileIcons/c++.png"),
    ("SQL",             ".sql",         "images/fileIcons/database.png"),
    ("Shell Script",    ".sh",          "images/fileIcons/linux.png"),
    ("Plain Text",      ".txt",         "images/fileIcons/properties.png"),
    ("Properties",      ".properties",  "images/fileIcons/properties.png"),
    ("Git Ignore",      ".gitignore",   "images/fileIcons/git.png"),
    ("Plain (no ext)", "",              "images/fileIcons/properties.png"),
]

_DIALOG_STYLE = """
    QDialog {
        background: #1e1e1e;
        color: #e0e0e0;
    }
    QLabel {
        color: #cccccc;
        font-size: 12px;
        background: transparent;
        border: none;
    }
    QLineEdit {
        background: #2d2d2d;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 5px;
        padding: 6px 8px;
        font-size: 13px;
        font-family: Monospace;
    }
    QLineEdit:focus { border-color: #0091E7; }
    QListWidget {
        background: #252525;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 5px;
        outline: none;
    }
    QListWidget::item {
        padding: 6px 10px;
        border-radius: 4px;
    }
    QListWidget::item:selected {
        background: #0091E7;
        color: #ffffff;
    }
    QListWidget::item:hover:!selected { background: #2e2e2e; }
    QPushButton {
        background: #2d2d2d;
        color: #cccccc;
        border: 1px solid #444;
        border-radius: 5px;
        padding: 6px 18px;
        font-size: 12px;
    }
    QPushButton:hover  { background: #3a3a3a; color: #ffffff; }
    QPushButton#create { background: #0091E7; color: #ffffff; border-color: #0091E7; }
    QPushButton#create:hover { background: #007acc; }
"""

_MENU_STYLE = """
    QMenu {
        background: #1e1e1e;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 6px;
        padding: 4px;
    }
    QMenu::item {
        padding: 6px 28px 6px 12px;
        border-radius: 4px;
        font-size: 12px;
    }
    QMenu::item:selected { background: #0091E7; color: #ffffff; }
    QMenu::separator { height: 1px; background: #333; margin: 4px 8px; }
    QMenu::icon { padding-left: 8px; }
"""


# ── Typed new-file dialog ─────────────────────────────────────────────────────
class NewFileDialog(QDialog):
    """
    Modal dialog: user picks a file type from a list and types a name.
    The extension is auto-appended when the type is selected, but the
    user can still type a fully custom name.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New File")
        self.setFixedSize(440, 480)
        self.setStyleSheet(_DIALOG_STYLE)
        self._selected_ext = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Title
        title = QLabel("Create New File")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff; border:none;")
        layout.addWidget(title)

        # Type list
        type_label = QLabel("File Type")
        layout.addWidget(type_label)

        self._type_list = QListWidget()
        self._type_list.setIconSize(QSize(20, 20))
        self._type_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._type_list.setFixedHeight(220)

        for display, ext, icon_path in FILE_TYPES:
            item = QListWidgetItem(f"{display}  {ext}")
            item.setData(Qt.UserRole, ext)
            icon = QIcon(icon_path)
            if not icon.isNull():
                item.setIcon(icon)
            self._type_list.addItem(item)

        self._type_list.currentItemChanged.connect(self._on_type_changed)
        layout.addWidget(self._type_list)

        # File name input
        name_label = QLabel("File Name")
        layout.addWidget(name_label)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g.  main  or  main.py")
        layout.addWidget(self._name_input)

        # Hint
        self._hint = QLabel("")
        self._hint.setStyleSheet("color: #666; font-size: 11px; border:none;")
        layout.addWidget(self._hint)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self._create_btn = QPushButton("Create")
        self._create_btn.setObjectName("create")
        self._create_btn.clicked.connect(self._on_create)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._create_btn)
        layout.addLayout(btn_row)

        # Select "Plain Text" by default
        self._type_list.setCurrentRow(18)   # Plain Text row
        self._name_input.setFocus()

    def _on_type_changed(self, item):
        if item is None:
            return
        ext = item.data(Qt.UserRole)
        self._selected_ext = ext
        if ext:
            self._hint.setText(f"Extension  '{ext}'  will be added if you don't include it")
        else:
            self._hint.setText("No extension will be added")

    def _on_create(self):
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "No name", "Please enter a file name.")
            return

        # Auto-append extension only if the name doesn't already end with it
        if self._selected_ext and not name.endswith(self._selected_ext):
            # Also skip if name already has any dot extension
            if "." not in name:
                name += self._selected_ext

        self._final_name = name
        self.accept()

    def get_filename(self) -> str:
        return getattr(self, "_final_name", "")


# ── Context menu mixin / helpers ──────────────────────────────────────────────
def setup_tree_context_menu(editor):
    """
    Call this once after setup_tree_view().
    Wires right-click on editor.tree to show a context menu.
    'editor' is the CodeEditor instance.
    """
    editor.tree.setContextMenuPolicy(Qt.CustomContextMenu)
    editor.tree.customContextMenuRequested.connect(
        lambda pos: _show_tree_menu(editor, pos)
    )


def _show_tree_menu(editor, pos):
    index      = editor.tree.indexAt(pos)
    path       = editor.model.filePath(index) if index.isValid() else None
    is_dir     = os.path.isdir(path) if path else False
    is_file    = os.path.isfile(path) if path else False
    global_pos = editor.tree.viewport().mapToGlobal(pos)

    menu = QMenu(editor)
    menu.setStyleSheet(_MENU_STYLE)

    # ── always available ──────────────────────────────────────────────
    act_new_file   = menu.addAction(QIcon("images/UI/newdoc.png"),   "New File…")
    act_new_folder = menu.addAction(QIcon("images/UI/newFile.png"),  "New Folder…")
    menu.addSeparator()

    # ── file/folder specific ──────────────────────────────────────────
    act_rename = act_delete = act_copy_path = act_open_terminal = None

    if path:
        act_rename     = menu.addAction(QIcon("images/UI/rename.png"), "Rename…")
        act_delete     = menu.addAction(QIcon("images/UI/delete.png"), "Delete")
        menu.addSeparator()
        act_copy_path  = menu.addAction("Copy Path")
        if is_dir:
            act_open_terminal = menu.addAction(QIcon("images/UI/terminal2.png"),
                                               "Open in Terminal")

    chosen = menu.exec_(global_pos)
    if chosen is None:
        return

    # Resolve the directory to act in
    if path:
        target_dir = path if is_dir else os.path.dirname(path)
    elif editor.base_directory:
        target_dir = editor.base_directory
    else:
        target_dir = str(__import__("pathlib").Path.home())

    # ── dispatch ──────────────────────────────────────────────────────
    if chosen == act_new_file:
        _ctx_new_file(editor, target_dir)

    elif chosen == act_new_folder:
        _ctx_new_folder(editor, target_dir)

    elif chosen == act_rename and path:
        _ctx_rename(editor, path)

    elif chosen == act_delete and path:
        _ctx_delete(editor, path, is_dir)

    elif chosen == act_copy_path and path:
        __import__("PyQt5.QtWidgets", fromlist=["QApplication"]).QApplication.clipboard().setText(path)

    elif act_open_terminal and chosen == act_open_terminal:
        editor.terminal_manager.new_tab(cwd=target_dir)
        if not editor.terminal_manager._visible:
            editor.terminal_manager.show()


# ── individual operations ─────────────────────────────────────────────────────

def _ctx_new_file(editor, target_dir: str):
    dlg = NewFileDialog(editor)
    if dlg.exec_() != QDialog.Accepted:
        return
    name = dlg.get_filename()
    if not name:
        return
    full_path = os.path.join(target_dir, name)
    if os.path.exists(full_path):
        QMessageBox.warning(editor, "Exists", f"'{name}' already exists.")
        return
    try:
        open(full_path, "w").close()
    except OSError as e:
        QMessageBox.warning(editor, "Error", str(e))


def _ctx_new_folder(editor, target_dir: str):
    name, ok = QInputDialog.getText(editor, "New Folder", "Folder name:")
    if not ok or not name.strip():
        return
    full_path = os.path.join(target_dir, name.strip())
    if os.path.exists(full_path):
        QMessageBox.warning(editor, "Exists", f"'{name}' already exists.")
        return
    try:
        os.mkdir(full_path)
    except OSError as e:
        QMessageBox.warning(editor, "Error", str(e))


def _ctx_rename(editor, path: str):
    old_name = os.path.basename(path)
    new_name, ok = QInputDialog.getText(editor, "Rename", "New name:", text=old_name)
    if not ok or not new_name.strip() or new_name == old_name:
        return
    new_path = os.path.join(os.path.dirname(path), new_name.strip())
    if os.path.exists(new_path):
        QMessageBox.warning(editor, "Exists", f"'{new_name}' already exists.")
        return
    try:
        os.rename(path, new_path)
        # Update any open tab that references the old path
        if path in editor.open_files:
            data = editor.open_files.pop(path)
            editor.open_files[new_path] = data
            tab_idx = data["tab_index"]
            editor.current_file_tabs.setTabText(tab_idx, new_name.strip())
    except OSError as e:
        QMessageBox.warning(editor, "Error", str(e))


def _ctx_delete(editor, path: str, is_dir: bool):
    label = "folder and all its contents" if is_dir else "file"
    reply = QMessageBox.question(
        editor, "Confirm Delete",
        f"Delete {label}:\n{path}?",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if reply != QMessageBox.Yes:
        return
    try:
        if is_dir:
            shutil.rmtree(path)
        else:
            os.remove(path)
        # Close any open tab for this path
        if path in editor.open_files:
            editor.close_tab(path)
    except OSError as e:
        QMessageBox.warning(editor, "Error", str(e))


# ── typed new-file from toolbar (replaces create_new_file in CodeEditor) ─────
def toolbar_new_file(editor):
    """
    Replacement for CodeEditor.create_new_file().
    Uses NewFileDialog instead of plain QInputDialog.
    """
    index = editor.tree.currentIndex()
    if index.isValid():
        dir_path = editor.model.filePath(index)
        if os.path.isfile(dir_path):
            dir_path = os.path.dirname(dir_path)
    elif editor.base_directory:
        dir_path = editor.base_directory
    else:
        QMessageBox.information(editor, "No folder", "Open a project folder first.")
        return

    dlg = NewFileDialog(editor)
    if dlg.exec_() != QDialog.Accepted:
        return
    name = dlg.get_filename()
    if not name:
        return
    full_path = os.path.join(dir_path, name)
    if os.path.exists(full_path):
        QMessageBox.warning(editor, "Exists", f"'{name}' already exists.")
        return
    try:
        open(full_path, "w").close()
    except OSError as e:
        QMessageBox.warning(editor, "Error", str(e))
