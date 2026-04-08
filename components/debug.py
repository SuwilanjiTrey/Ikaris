"""
debug.py — DebugPanel (Improved UX)
Detects the project type from its root directory and exposes the right
toolset in the sidebar.  The main output lives in web/debug.html, loaded
into a QWebEngineView that is injected into the editor area just like the
database view.
"""

import os
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QToolButton, QMenu, QAction,
    QMessageBox, QInputDialog, QLineEdit, QStatusBar, QProgressBar, QFrame
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import Qt, QUrl, QObject, pyqtSlot, pyqtSignal, QThread, QProcess, QTimer
from PyQt5.QtGui import QIcon, QColor


# ── project detector ──────────────────────────────────────────────────────────

def detect_project(root: str) -> dict:
    """
    Scan *root* and return a project-info dict:
    {
        'type':        'WEB' | 'REACT_NATIVE' | 'NODE' | 'SPRING' | 'MAVEN' | 'UNKNOWN',
        'framework':   str,   # 'React', 'Next.js', 'Vite', 'Expo', …
        'pkg':         dict,  # parsed package.json (or {})
        'pom_path':    str,   # path to pom.xml (or '')
        'root':        str,
    }
    """
    info = {
        'type':      'UNKNOWN',
        'framework': '',
        'pkg':       {},
        'pom_path':  '',
        'root':      root or '',
    }

    if not root or not os.path.isdir(root):
        return info

    pkg_path = os.path.join(root, 'package.json')
    pom_path = os.path.join(root, 'pom.xml')

    # ── JavaScript / Node ─────────────────────────────────────────────────────
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
        except Exception:
            pkg = {}

        info['pkg'] = pkg
        all_deps = {}
        all_deps.update(pkg.get('dependencies', {}))
        all_deps.update(pkg.get('devDependencies', {}))
        dep_names = set(all_deps.keys())

        # React Native / Expo check first
        rn_markers = {'react-native', 'expo', '@expo/metro-config', 'expo-router'}
        if dep_names & rn_markers:
            info['type'] = 'REACT_NATIVE'
            if 'expo' in dep_names:
                info['framework'] = 'Expo'
            else:
                info['framework'] = 'React Native'
            return info

        # Web frameworks
        if 'next' in dep_names:
            info['type'] = 'WEB'
            info['framework'] = 'Next.js'
        elif 'vite' in dep_names:
            info['type'] = 'WEB'
            info['framework'] = 'Vite'
        elif 'react' in dep_names:
            info['type'] = 'WEB'
            info['framework'] = 'React'
        elif 'vue' in dep_names:
            info['type'] = 'WEB'
            info['framework'] = 'Vue'
        elif '@angular/core' in dep_names:
            info['type'] = 'WEB'
            info['framework'] = 'Angular'
        elif 'svelte' in dep_names:
            info['type'] = 'WEB'
            info['framework'] = 'Svelte'
        else:
            info['type'] = 'NODE'
            info['framework'] = 'Node.js'

        return info

    # ── Java / Maven / Spring ─────────────────────────────────────────────────
    if os.path.isfile(pom_path):
        info['pom_path'] = pom_path
        try:
            tree  = ET.parse(pom_path)
            root_el = tree.getroot()
            # Strip xmlns from tags
            ns   = root_el.tag.split('}')[0].lstrip('{') if '}' in root_el.tag else ''
            tag  = lambda t: f'{{{ns}}}{t}' if ns else t
            xml  = ET.tostring(root_el, encoding='unicode')

            spring_markers = ['spring-boot', 'org.springframework', 'spring-framework']
            is_spring = any(m in xml for m in spring_markers)

            if is_spring:
                info['type']      = 'SPRING'
                info['framework'] = 'Spring Boot'
            else:
                info['type']      = 'MAVEN'
                info['framework'] = 'Maven'
        except Exception:
            info['type']      = 'MAVEN'
            info['framework'] = 'Maven'

        return info

    return info


# ── JS ↔ Python bridge ────────────────────────────────────────────────────────

class DebugBridge(QObject):
    """
    Exposed to the WebEngineView so debug.html can call Python.
    Each method posts a result back via runJavaScript.
    """

    output_ready = pyqtSignal(str, str)   # (channel, text)
    operation_started = pyqtSignal(str, int)  # (operation_name, max_progress)
    operation_progress = pyqtSignal(int)      # (current_progress)
    operation_finished = pyqtSignal(str)      # (operation_name)

    def __init__(self, panel: "DebugPanel"):
        super().__init__()
        self._panel = panel
        self._proc: QProcess | None = None
        self._current_operation = ""
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._update_progress)
        self._progress_value = 0
        self._progress_max = 100

    # ── called by HTML ────────────────────────────────────────────────────────

    @pyqtSlot()
    def request_project_info(self):
        """Push project info to the HTML page."""
        self._panel._push_project_info()

    @pyqtSlot(str)
    def run_npm(self, cmd: str):
        """Run  npm <cmd>  in the project root and stream output."""
        self._run_in_terminal(['npm'] + cmd.split(), label=f'npm {cmd}')

    @pyqtSlot(str)
    def run_npx(self, cmd: str):
        self._run_in_terminal(['npx'] + cmd.split(), label=f'npx {cmd}')

    @pyqtSlot(str)
    def install_package(self, pkg_spec: str):
        self._run_in_terminal(['npm', 'install', pkg_spec], label=f'npm install {pkg_spec}', show_progress=True)

    @pyqtSlot(str)
    def remove_package(self, pkg_name: str):
        self._run_in_terminal(['npm', 'uninstall', pkg_name], label=f'npm uninstall {pkg_name}', show_progress=True)

    @pyqtSlot(str)
    def update_package(self, pkg_name: str):
        cmd = ['npm', 'update']
        if pkg_name:
            cmd.append(pkg_name)
        self._run_in_terminal(cmd, label=f'npm update {pkg_name}', show_progress=True)

    @pyqtSlot()
    def audit_fix(self):
        self._run_in_terminal(['npm', 'audit', 'fix'], label='npm audit fix', show_progress=True)

    @pyqtSlot()
    def list_outdated(self):
        self._run_in_terminal(['npm', 'outdated'], label='npm outdated')

    # ── ADB ───────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def adb_devices(self):
        self._run_in_terminal(['adb', 'devices'], label='adb devices')

    @pyqtSlot()
    def adb_logcat(self):
        """Start streaming logcat (killed when a new command starts)."""
        self._run_in_terminal(['adb', 'logcat', '-v', 'brief'], label='adb logcat', stream=True)

    @pyqtSlot()
    def adb_logcat_crash(self):
        self._run_in_terminal(
            ['adb', 'logcat', '-v', 'brief', '*:E'],
            label='adb logcat (errors)', stream=True
        )

    @pyqtSlot()
    def adb_clear_logcat(self):
        self._run_in_terminal(['adb', 'logcat', '-c'], label='adb logcat -c')

    @pyqtSlot(str)
    def adb_install(self, apk_path: str):
        self._run_in_terminal(['adb', 'install', '-r', apk_path], label=f'adb install {apk_path}', show_progress=True)

    # ── Maven / Spring ────────────────────────────────────────────────────────

    @pyqtSlot()
    def mvn_clean_install(self):
        self._run_in_terminal(['mvn', 'clean', 'install'], label='mvn clean install', show_progress=True)

    @pyqtSlot()
    def mvn_clean(self):
        self._run_in_terminal(['mvn', 'clean'], label='mvn clean')

    @pyqtSlot()
    def mvn_build(self):
        self._run_in_terminal(['mvn', 'package', '-DskipTests'], label='mvn package', show_progress=True)

    @pyqtSlot()
    def spring_run(self):
        self._run_in_terminal(
            ['mvn', 'spring-boot:run'],
            label='Spring Boot: run', stream=True
        )

    @pyqtSlot(str)
    def search_maven_dependency(self, query: str):
        """
        Quick search via Maven Central REST API and push results to HTML.
        Runs in a thread to avoid blocking UI.
        """
        import threading
        def _search():
            try:
                import urllib.request, urllib.parse
                q   = urllib.parse.quote(query)
                url = f"https://search.maven.org/solrsearch/select?q={q}&rows=10&wt=json"
                with urllib.request.urlopen(url, timeout=8) as r:
                    data = json.loads(r.read())
                docs = data.get('response', {}).get('docs', [])
                results = [
                    {'g': d.get('g',''), 'a': d.get('a',''), 'latestVersion': d.get('latestVersion','')}
                    for d in docs
                ]
            except Exception as e:
                results = [{'error': str(e)}]
            payload = json.dumps(results).replace("'", "\\'")
            self._panel._js(f"window.onMavenSearchResults && window.onMavenSearchResults({payload});")
        threading.Thread(target=_search, daemon=True).start()

    @pyqtSlot(str, str, str)
    def add_maven_dependency(self, group_id: str, artifact_id: str, version: str):
        """Insert a <dependency> block into pom.xml."""
        pom = self._panel._project_info.get('pom_path', '')
        if not pom or not os.path.isfile(pom):
            self._panel._js("window.onOutput && window.onOutput('system','❌ pom.xml not found.');")
            return
        try:
            with open(pom, 'r', encoding='utf-8') as f:
                content = f.read()

            dep_block = (
                f'\n\t\t<dependency>\n'
                f'\t\t\t<groupId>{group_id}</groupId>\n'
                f'\t\t\t<artifactId>{artifact_id}</artifactId>\n'
                f'\t\t\t<version>{version}</version>\n'
                f'\t\t</dependency>'
            )

            if '<dependencies>' in content:
                content = content.replace('<dependencies>', '<dependencies>' + dep_block, 1)
            else:
                content = content.replace(
                    '</project>',
                    f'\n\t<dependencies>{dep_block}\n\t</dependencies>\n</project>'
                )

            with open(pom, 'w', encoding='utf-8') as f:
                f.write(content)

            msg = f"✅ Added {group_id}:{artifact_id}:{version} to pom.xml"
            self._panel._js(f"window.onOutput && window.onOutput('system',{json.dumps(msg)});")
        except Exception as e:
            self._panel._js(f"window.onOutput && window.onOutput('system',{json.dumps(str(e))});")

    # ── shared runner ─────────────────────────────────────────────────────────

    def _run_in_terminal(self, cmd: list, label: str, stream: bool = False, show_progress: bool = False):
        root = self._panel._project_info.get('root', '')

        # Kill any running streamed process
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(1000)

        self._current_operation = label
        
        # Show operation in status bar
        if show_progress:
            self.operation_started.emit(label, 100)
            self._progress_value = 0
            self._progress_max = 100
            self._progress_timer.start(100)  # Update progress every 100ms

        self._panel._js(
            f"window.onOutput && window.onOutput('cmd', {json.dumps('▶ ' + label)});"
        )

        proc = QProcess()
        proc.setWorkingDirectory(root or os.getcwd())

        if stream:
            self._proc = proc
            proc.readyReadStandardOutput.connect(
                lambda: self._stream_out(proc, 'stdout')
            )
            proc.readyReadStandardError.connect(
                lambda: self._stream_out(proc, 'stderr')
            )
            proc.finished.connect(
                lambda: self._on_process_finished(label)
            )
            proc.start(cmd[0], cmd[1:])
        else:
            proc.start(cmd[0], cmd[1:])
            proc.waitForFinished(60000)
            stdout = bytes(proc.readAllStandardOutput()).decode('utf-8', errors='replace')
            stderr = bytes(proc.readAllStandardError()).decode('utf-8', errors='replace')
            out    = (stdout + stderr).strip()
            if not out:
                out = f'[{label}] done (exit {proc.exitCode()})'
            self._panel._js(
                f"window.onOutput && window.onOutput('stdout', {json.dumps(out)});"
            )
            
            if show_progress:
                self.operation_finished.emit(label)
                self._progress_timer.stop()

    def _stream_out(self, proc: QProcess, channel: str):
        data = bytes(proc.readAllStandardOutput() if channel == 'stdout'
                     else proc.readAllStandardError()).decode('utf-8', errors='replace')
        if data.strip():
            self._panel._js(
                f"window.onOutput && window.onOutput({json.dumps(channel)}, {json.dumps(data.rstrip())});"
            )
            
            # Update progress for npm install operations
            if self._current_operation and "install" in self._current_operation.lower():
                self._update_progress_from_output(data)

    def _on_process_finished(self, label: str):
        """Called when a streamed process finishes."""
        if self._current_operation == label:
            self.operation_finished.emit(label)
            self._progress_timer.stop()

    def _update_progress(self):
        """Update progress bar with simulated progress."""
        if self._progress_value < self._progress_max:
            self._progress_value += 1
            self.operation_progress.emit(self._progress_value)

    def _update_progress_from_output(self, output: str):
        """Try to extract progress information from npm output."""
        # Simple pattern matching for npm install progress
        import re
        # Look for patterns like "added 150 packages in 10s"
        match = re.search(r'added (\d+) packages', output)
        if match:
            # Estimate total packages based on first batch
            added = int(match.group(1))
            if self._progress_value == 0 and added > 0:
                # Estimate total packages (rough guess)
                self._progress_max = max(added * 2, 100)
            self._progress_value = min(added, self._progress_max)
            self.operation_progress.emit(self._progress_value)


# ── Main DebugPanel ───────────────────────────────────────────────────────────

class DebugPanel(QWidget):
    """
    Left sidebar panel: detects project type and shows relevant action buttons.
    debug_view (QWebEngineView) is stored as self.debug_view so main_editor
    can add it to the editor area and show/hide it just like database_view.
    """

    def __init__(self, debug_layout: QVBoxLayout, main_window, channel=None):
        super().__init__()
        self._main = main_window
        self._project_info: dict = {'type': 'UNKNOWN', 'framework': '', 'pkg': {}, 'pom_path': '', 'root': ''}

        debug_layout.addWidget(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background:#181825; border-bottom:1px solid #313244;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 6, 0)
        h_lay.setSpacing(4)

        self._title_lbl = QLabel("Debug")
        self._title_lbl.setStyleSheet("color:#cdd6f4; font-weight:bold; font-size:13px;")
        h_lay.addWidget(self._title_lbl)
        h_lay.addStretch()

        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip("Re-scan project")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#313244;color:#cdd6f4;border-radius:5px;"
            "font-size:14px;border:none;}"
            "QPushButton:hover{background:#45475a;}"
        )
        refresh_btn.clicked.connect(self._rescan)
        h_lay.addWidget(refresh_btn)

        root.addWidget(header)

        # ── Dynamic toolbar area ───────────────────────────────────────────────
        self._toolbar_widget = QWidget()
        self._toolbar_layout = QVBoxLayout(self._toolbar_widget)
        self._toolbar_layout.setContentsMargins(8, 8, 8, 8)
        self._toolbar_layout.setSpacing(6)
        root.addWidget(self._toolbar_widget)
        root.addStretch()

        # ── Status Bar ───────────────────────────────────────────────────────────
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet("""
            QStatusBar {
                background: #181825;
                color: #cdd6f4;
                border-top: 1px solid #313244;
                font-size: 11px;
            }
        """)
        self._status_bar.setSizeGripEnabled(False)
        
        # Add progress bar to status bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #313244;
                border-radius: 3px;
                text-align: center;
                background: #1e1e2e;
                color: #cdd6f4;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background: #89b4fa;
                border-radius: 2px;
            }
        """)
        self._status_bar.addPermanentWidget(self._progress_bar)
        
        root.addWidget(self._status_bar)

        # ── WebEngineView (output panel in editor area) ───────────────────────
        self._debug_channel = QWebChannel()
        self._debug_bridge  = DebugBridge(self)
        self._debug_channel.registerObject('DebugBridge', self._debug_bridge)

        self.debug_view = QWebEngineView()
        self.debug_view.page().setWebChannel(self._debug_channel)

        html_path = os.path.abspath('web/debug.html')
        self.debug_view.load(QUrl.fromLocalFile(html_path))

        # Connect signals from bridge
        self._debug_bridge.operation_started.connect(self._on_operation_started)
        self._debug_bridge.operation_progress.connect(self._on_operation_progress)
        self._debug_bridge.operation_finished.connect(self._on_operation_finished)

        # Rebuild toolbar once page is ready
        self.debug_view.loadFinished.connect(self._on_page_ready)

    # ── project scanning ──────────────────────────────────────────────────────

    def set_project_root(self, root: str):
        """Called by main_editor when a new project folder is opened."""
        self._project_info = detect_project(root)
        self._rebuild_toolbar()
        self._push_project_info()

    def _rescan(self):
        root = self._project_info.get('root', '')
        if not root:
            root = getattr(self._main, 'base_directory', '') or ''
        self.set_project_root(root)

    def _on_page_ready(self, ok: bool):
        if ok:
            self._push_project_info()

    def _push_project_info(self):
        payload = json.dumps(self._project_info)
        self._js(f"window.onProjectInfo && window.onProjectInfo({payload});")

    # ── sidebar toolbar builder ───────────────────────────────────────────────

    def _rebuild_toolbar(self):
        # Clear existing
        while self._toolbar_layout.count():
            item = self._toolbar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        t = self._project_info.get('type', 'UNKNOWN')

        if t in ('WEB', 'NODE'):
            self._build_npm_toolbar()
        elif t == 'REACT_NATIVE':
            self._build_npm_toolbar()
            self._add_separator()
            self._build_adb_toolbar()
        elif t in ('SPRING', 'MAVEN'):
            self._build_maven_toolbar()
        else:
            lbl = QLabel("No project detected.\nOpen a project folder first.")
            lbl.setStyleSheet("color:#6c7086; font-size:11px; padding:8px;")
            lbl.setWordWrap(True)
            self._toolbar_layout.addWidget(lbl)

    def _add_separator(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("background:#313244; max-height:1px; border:none;")
        self._toolbar_layout.addWidget(sep)

    def _section_label(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#6c7086; font-size:9px; font-weight:bold; "
            "letter-spacing:1px; text-transform:uppercase; padding:4px 0 2px 0;"
        )
        self._toolbar_layout.addWidget(lbl)

    def _action_btn(self, label: str, icon: str, slot, tooltip: str = ""):
        btn = QPushButton(f"  {icon}  {label}")
        btn.setStyleSheet("""
            QPushButton {
                background:#313244; color:#cdd6f4;
                border:1px solid #45475a; border-radius:6px;
                padding:6px 10px; font-size:11px;
                text-align:left;
            }
            QPushButton:hover { background:#45475a; border-color:#89b4fa; color:#89b4fa; }
            QPushButton:pressed { background:#1e1e2e; }
        """)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        self._toolbar_layout.addWidget(btn)
        return btn

    def _build_npm_toolbar(self):
        fw = self._project_info.get('framework', 'NPM')
        self._section_label(f"{fw} · NPM Manager")

        self._action_btn("Install deps",   "⬇", lambda: self._debug_bridge.run_npm("install"),        "npm install")
        self._action_btn("List outdated",  "📋", lambda: self._debug_bridge.list_outdated(),           "npm outdated")
        self._action_btn("Audit fix",      "🛡", lambda: self._debug_bridge.audit_fix(),               "npm audit fix")
        self._action_btn("Add package…",   "＋", self._prompt_install_pkg,                             "npm install <package>")
        self._action_btn("Remove pkg…",    "✕", self._prompt_remove_pkg,                              "npm uninstall <package>")
        self._action_btn("Update pkg…",    "↑", self._prompt_update_pkg,                              "npm update <package>")

        # Scripts from package.json
        scripts = self._project_info.get('pkg', {}).get('scripts', {})
        if scripts:
            self._add_separator()
            self._section_label("NPM Scripts")
            for script_name in list(scripts.keys())[:8]:   # cap at 8
                name = script_name
                self._action_btn(
                    name, "▶",
                    lambda s=name: self._debug_bridge.run_npm(f'run {s}'),
                    f'npm run {name}'
                )

    def _build_adb_toolbar(self):
        self._section_label("Android · ADB")
        self._action_btn("Show devices",    "📱", lambda: self._debug_bridge.adb_devices(),        "adb devices")
        self._action_btn("Stream logcat",   "📡", lambda: self._debug_bridge.adb_logcat(),         "adb logcat")
        self._action_btn("Errors only",     "🔴", lambda: self._debug_bridge.adb_logcat_crash(),   "adb logcat *:E")
        self._action_btn("Clear logcat",    "🗑", lambda: self._debug_bridge.adb_clear_logcat(),   "adb logcat -c")
        self._action_btn("Install APK…",    "📦", self._prompt_install_apk,                        "adb install <apk>")

    def _build_maven_toolbar(self):
        fw = self._project_info.get('framework', 'Maven')
        self._section_label(f"{fw} · Build")

        self._action_btn("Clean & Install", "⚙", lambda: self._debug_bridge.mvn_clean_install(), "mvn clean install")
        self._action_btn("Clean",           "🗑", lambda: self._debug_bridge.mvn_clean(),         "mvn clean")
        self._action_btn("Build (skip tests)", "📦", lambda: self._debug_bridge.mvn_build(),      "mvn package -DskipTests")

        if self._project_info.get('type') == 'SPRING':
            self._add_separator()
            self._section_label("Spring Boot")
            self._action_btn("Run application", "▶", lambda: self._debug_bridge.spring_run(), "mvn spring-boot:run")

        self._add_separator()
        self._section_label("Dependency Search")
        self._action_btn("Search Maven Central…", "🔍", self._open_dep_search, "Search & add dependencies")

    # ── prompts ───────────────────────────────────────────────────────────────

    def _prompt_install_pkg(self):
        text, ok = QInputDialog.getText(self, "Add Package", "Package (e.g. axios@1.6.0):",
                                        QLineEdit.Normal, "")
        if ok and text.strip():
            self._debug_bridge.install_package(text.strip())

    def _prompt_remove_pkg(self):
        text, ok = QInputDialog.getText(self, "Remove Package", "Package name to remove:",
                                        QLineEdit.Normal, "")
        if ok and text.strip():
            self._debug_bridge.remove_package(text.strip())

    def _prompt_update_pkg(self):
        text, ok = QInputDialog.getText(self, "Update Package",
                                        "Package name (leave blank for all):",
                                        QLineEdit.Normal, "")
        if ok:
            self._debug_bridge.update_package(text.strip())

    def _prompt_install_apk(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select APK", "", "APK Files (*.apk)")
        if path:
            self._debug_bridge.adb_install(path)

    def _open_dep_search(self):
        """Tell the HTML page to show the dependency search UI."""
        self._js("window.showDepSearch && window.showDepSearch();")

    # ── status bar handlers ─────────────────────────────────────────────────────

    def _on_operation_started(self, operation_name: str, max_progress: int):
        """Called when a long-running operation starts."""
        self._status_bar.showMessage(f"Running: {operation_name}")
        self._progress_bar.setMaximum(max_progress)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

    def _on_operation_progress(self, value: int):
        """Called to update progress bar."""
        self._progress_bar.setValue(value)
        # Calculate percentage
        percent = int((value / self._progress_bar.maximum()) * 100)
        self._status_bar.showMessage(f"Running: {self._debug_bridge._current_operation} ({percent}%)")

    def _on_operation_finished(self, operation_name: str):
        """Called when a long-running operation finishes."""
        self._status_bar.showMessage(f"Completed: {operation_name}", 3000)  # Show for 3 seconds
        self._progress_bar.setVisible(False)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _js(self, script: str):
        """Safe runJavaScript — only if the page is loaded."""
        try:
            self.debug_view.page().runJavaScript(script)
        except Exception:
            pass
