import os
import sys
import subprocess
import threading
import json
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QMessageBox
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QUrl, QStandardPaths
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel


# ──────────────────────────────────────────────────────────────────────────────
#  Bridge – connects the HTML UI to Python CLI logic
# ──────────────────────────────────────────────────────────────────────────────
class ProjectBridge(QObject):
    """
    All @pyqtSlot methods here are callable from JavaScript via qt.webChannelTransport.
    Signals travel the other direction (Python → JS).
    """

    # Emitted when a project is fully created; carries the new project path
    project_created = pyqtSignal(str)
    # Emitted to stream log lines back to the UI
    log_message = pyqtSignal(str)
    # Emitted on error
    creation_failed = pyqtSignal(str)

    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window

    # ── Utility ───────────────────────────────────────────────────────────────

    def _run(self, cmd: list, cwd: str = None) -> tuple[int, str]:
        """Run a shell command, stream output through log_message, return (returncode, combined_output)."""
        self.log_message.emit(f"$ {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            output_lines = []
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                self.log_message.emit(line)
            proc.wait()
            return proc.returncode, "\n".join(output_lines)
        except FileNotFoundError as exc:
            msg = f"Command not found: {cmd[0]}  →  {exc}"
            self.log_message.emit(msg)
            return 1, msg

    def _check_tool(self, tool: str) -> bool:
        """Return True if `tool` is on PATH."""
        import shutil
        return shutil.which(tool) is not None

    # ── Browse for directory ───────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def browse_directory(self) -> str:
        desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        path = QFileDialog.getExistingDirectory(None, "Select Project Parent Directory", desktop)
        return path or ""

    # ── Main create_project entry point ───────────────────────────────────────

    @pyqtSlot(str)
    def create_project(self, config_json: str):
        """
        config_json is a JSON string with at minimum:
          {
            "project_type": "python" | "java" | "android" | "web",
            "project_name": "my-app",
            "target_dir":   "/home/user/projects",
            ... type-specific keys ...
          }
        """
        try:
            cfg = json.loads(config_json)
        except json.JSONDecodeError as e:
            self.creation_failed.emit(f"Bad config JSON: {e}")
            return

        project_type = cfg.get("project_type", "")
        project_name = cfg.get("project_name", "").strip()
        target_dir   = cfg.get("target_dir", "").strip()

        if not project_name:
            self.creation_failed.emit("Project name is required.")
            return
        if not target_dir or not os.path.isdir(target_dir):
            self.creation_failed.emit("A valid target directory is required.")
            return

        project_path = os.path.join(target_dir, project_name)
        if os.path.exists(project_path):
            self.creation_failed.emit(f"Directory already exists: {project_path}")
            return

        # Dispatch in background thread so the UI stays responsive
        thread = threading.Thread(
            target=self._dispatch,
            args=(project_type, project_name, target_dir, project_path, cfg),
            daemon=True,
        )
        thread.start()

    def _dispatch(self, project_type, project_name, target_dir, project_path, cfg):
        try:
            if project_type == "python":
                self._create_python(project_name, target_dir, project_path, cfg)
            elif project_type == "java":
                self._create_java(project_name, target_dir, project_path, cfg)
            elif project_type == "android":
                self._create_android(project_name, target_dir, project_path, cfg)
            elif project_type == "web":
                self._create_web(project_name, target_dir, project_path, cfg)
            else:
                self.creation_failed.emit(f"Unknown project type: {project_type}")
        except Exception as exc:
            self.creation_failed.emit(str(exc))

    # ── 1. Python – Django or Flask ───────────────────────────────────────────

    def _create_python(self, name, target_dir, project_path, cfg):
        framework = cfg.get("python_framework", "django")  # "django" | "flask"
        self.log_message.emit(f"🐍  Creating Python/{framework} project: {name}")

        if not self._check_tool("python3") and not self._check_tool("python"):
            self.creation_failed.emit("Python not found on PATH.")
            return

        py = "python3" if self._check_tool("python3") else "python"

        # Create virtualenv inside project folder
        os.makedirs(project_path, exist_ok=True)
        rc, _ = self._run([py, "-m", "venv", "venv"], cwd=project_path)
        if rc != 0:
            self.creation_failed.emit("Failed to create virtual environment.")
            return

        # Determine pip path inside venv
        venv_pip = os.path.join(project_path, "venv", "bin", "pip")
        if not os.path.exists(venv_pip):
            venv_pip = os.path.join(project_path, "venv", "Scripts", "pip.exe")

        if framework == "django":
            rc, _ = self._run([venv_pip, "install", "django"], cwd=project_path)
            if rc != 0:
                self.creation_failed.emit("Failed to install Django.")
                return

            django_admin = os.path.join(project_path, "venv", "bin", "django-admin")
            if not os.path.exists(django_admin):
                django_admin = os.path.join(project_path, "venv", "Scripts", "django-admin.exe")

            rc, _ = self._run([django_admin, "startproject", name, "."], cwd=project_path)
            if rc != 0:
                self.creation_failed.emit("django-admin startproject failed.")
                return

            # Write a friendly requirements.txt
            with open(os.path.join(project_path, "requirements.txt"), "w") as f:
                f.write("django>=4.2\n")

        else:  # flask
            rc, _ = self._run([venv_pip, "install", "flask", "python-dotenv"], cwd=project_path)
            if rc != 0:
                self.creation_failed.emit("Failed to install Flask.")
                return

            # Scaffold minimal Flask structure
            app_dir = os.path.join(project_path, "app")
            os.makedirs(os.path.join(app_dir, "templates"), exist_ok=True)
            os.makedirs(os.path.join(app_dir, "static"), exist_ok=True)

            with open(os.path.join(app_dir, "__init__.py"), "w") as f:
                f.write(
                    "from flask import Flask\n\n"
                    "def create_app():\n"
                    "    app = Flask(__name__)\n\n"
                    "    @app.route('/')\n"
                    "    def index():\n"
                    "        return '<h1>Hello from Flask!</h1>'\n\n"
                    "    return app\n"
                )

            with open(os.path.join(project_path, "run.py"), "w") as f:
                f.write(
                    "from app import create_app\n\n"
                    "app = create_app()\n\n"
                    "if __name__ == '__main__':\n"
                    "    app.run(debug=True)\n"
                )

            with open(os.path.join(project_path, "requirements.txt"), "w") as f:
                f.write("flask>=3.0\npython-dotenv>=1.0\n")

            with open(os.path.join(project_path, ".env"), "w") as f:
                f.write("FLASK_APP=run.py\nFLASK_ENV=development\n")

        self.log_message.emit("✅  Python project created successfully.")
        self.project_created.emit(project_path)

    # ── 2. Java – Spring Boot with Maven ─────────────────────────────────────

    def _create_java(self, name, target_dir, project_path, cfg):
        self.log_message.emit(f"☕  Creating Java/Spring Boot project: {name}")

        # Spring Initializr via curl or the spring CLI
        # We use the REST API so no extra tool is needed beyond curl
        if not self._check_tool("curl"):
            self.creation_failed.emit("curl not found. Please install curl.")
            return

        java_version  = cfg.get("java_version", "17")
        spring_boot   = cfg.get("spring_boot_version", "3.3.0")
        group_id      = cfg.get("group_id", "com.example")
        dependencies  = cfg.get("dependencies", "web")  # comma-sep Spring deps

        zip_path = os.path.join(target_dir, f"{name}.zip")

        # Build the Initializr URL
        initializr_url = (
            f"https://start.spring.io/starter.zip"
            f"?type=maven-project"
            f"&language=java"
            f"&bootVersion={spring_boot}"
            f"&baseDir={name}"
            f"&groupId={group_id}"
            f"&artifactId={name}"
            f"&name={name}"
            f"&javaVersion={java_version}"
            f"&dependencies={dependencies}"
        )

        self.log_message.emit(f"Downloading from Spring Initializr …")
        rc, _ = self._run(
            ["curl", "-o", zip_path, "-L", initializr_url],
            cwd=target_dir,
        )
        if rc != 0 or not os.path.exists(zip_path):
            self.creation_failed.emit("Failed to download Spring Boot project from start.spring.io.")
            return

        import zipfile
        self.log_message.emit("Extracting …")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
        os.remove(zip_path)

        self.log_message.emit("✅  Java/Spring Boot project created successfully.")
        self.project_created.emit(project_path)

    # ── 3. Android – React Native + Expo ──────────────────────────────────────

    def _create_android(self, name, target_dir, project_path, cfg):
        self.log_message.emit(f"📱  Creating Android/Expo project: {name}")

        bare_workflow = cfg.get("bare_workflow", False)   # True = prebuild
        include_ios   = cfg.get("include_ios", False)

        if not self._check_tool("npx"):
            self.creation_failed.emit("npx not found. Please install Node.js.")
            return

        # Always use Expo (managed by default, prebuild = bare)
        rc, _ = self._run(
            ["npx", "create-expo-app@latest", name, "--template", "blank"],
            cwd=target_dir,
        )
        if rc != 0:
            self.creation_failed.emit("create-expo-app failed.")
            return

        if bare_workflow:
            self.log_message.emit("Running expo prebuild (bare workflow) …")
            prebuild_cmd = ["npx", "expo", "prebuild", "--clean"]
            if not include_ios:
                prebuild_cmd += ["--platform", "android"]
            rc, _ = self._run(prebuild_cmd, cwd=project_path)
            if rc != 0:
                self.creation_failed.emit("expo prebuild failed.")
                return

        self.log_message.emit("✅  Expo project created successfully.")
        self.project_created.emit(project_path)

    # ── 4. Web – React variants ───────────────────────────────────────────────

    def _create_web(self, name, target_dir, project_path, cfg):
        variant  = cfg.get("web_variant", "react-bare")   # react-bare | vite | nextjs
        css_tool = cfg.get("css_tool", "css3")             # css3 | tailwind

        self.log_message.emit(f"🌐  Creating Web project ({variant}, {css_tool}): {name}")

        if not self._check_tool("npx"):
            self.creation_failed.emit("npx not found. Please install Node.js.")
            return

        if variant == "react-bare":
            rc, _ = self._run(
                ["npx", "create-react-app@latest", name],
                cwd=target_dir,
            )
            if rc != 0:
                self.creation_failed.emit("create-react-app failed.")
                return

            if css_tool == "tailwind":
                self._add_tailwind_cra(project_path)

        elif variant == "vite":
            rc, _ = self._run(
                ["npx", "create-vite@latest", name, "--template", "react"],
                cwd=target_dir,
            )
            if rc != 0:
                self.creation_failed.emit("create-vite failed.")
                return

            # npm install first, then optionally add tailwind
            self._run(["npm", "install"], cwd=project_path)

            if css_tool == "tailwind":
                self._add_tailwind_vite(project_path)

        elif variant == "nextjs":
            args = ["npx", "create-next-app@latest", name, "--ts", "--eslint", "--app", "--no-git"]
            if css_tool == "tailwind":
                args.append("--tailwind")
            else:
                args.append("--no-tailwind")

            rc, _ = self._run(args, cwd=target_dir)
            if rc != 0:
                self.creation_failed.emit("create-next-app failed.")
                return
        else:
            self.creation_failed.emit(f"Unknown web variant: {variant}")
            return

        self.log_message.emit("✅  Web project created successfully.")
        self.project_created.emit(project_path)

    # ── Tailwind helpers ──────────────────────────────────────────────────────

    def _add_tailwind_cra(self, project_path):
        self.log_message.emit("Adding Tailwind CSS to CRA project …")
        self._run(
            ["npm", "install", "-D", "tailwindcss", "postcss", "autoprefixer"],
            cwd=project_path,
        )
        self._run(["npx", "tailwindcss", "init", "-p"], cwd=project_path)
        tw_config = os.path.join(project_path, "tailwind.config.js")
        if os.path.exists(tw_config):
            with open(tw_config, "w") as f:
                f.write(
                    "/** @type {import('tailwindcss').Config} */\n"
                    "module.exports = {\n"
                    "  content: ['./src/**/*.{js,jsx,ts,tsx}'],\n"
                    "  theme: { extend: {} },\n"
                    "  plugins: [],\n"
                    "}\n"
                )
        index_css = os.path.join(project_path, "src", "index.css")
        tw_directives = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"
        if os.path.exists(index_css):
            with open(index_css, "r+") as f:
                existing = f.read()
                f.seek(0)
                f.write(tw_directives + existing)
        else:
            with open(index_css, "w") as f:
                f.write(tw_directives)

    def _add_tailwind_vite(self, project_path):
        self.log_message.emit("Adding Tailwind CSS to Vite project …")
        self._run(
            ["npm", "install", "-D", "tailwindcss", "postcss", "autoprefixer"],
            cwd=project_path,
        )
        self._run(["npx", "tailwindcss", "init", "-p"], cwd=project_path)
        tw_config = os.path.join(project_path, "tailwind.config.js")
        if os.path.exists(tw_config):
            with open(tw_config, "w") as f:
                f.write(
                    "/** @type {import('tailwindcss').Config} */\n"
                    "export default {\n"
                    "  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],\n"
                    "  theme: { extend: {} },\n"
                    "  plugins: [],\n"
                    "}\n"
                )
        index_css = os.path.join(project_path, "src", "index.css")
        tw_directives = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"
        if os.path.exists(index_css):
            with open(index_css, "r+") as f:
                existing = f.read()
                f.seek(0)
                f.write(tw_directives + existing)
        else:
            with open(index_css, "w") as f:
                f.write(tw_directives)




# ──────────────────────────────────────────────────────────────────────────────
#  Widget – drop this into your main editor wherever you show panel pages
# ──────────────────────────────────────────────────────────────────────────────
class NewProjectWidget(QWidget):
    """
    A self-contained widget that embeds the HTML new-project UI.
    Connect `project_created` to your main editor's `update_directory`.

    Usage inside CodeEditor:
        self.new_project_page = NewProjectWidget(self)
        self.new_project_page.project_created.connect(self.update_directory)
        self.new_project_page.setVisible(False)
        # add to your stacked layout / splitter as you do other pages
    """

    project_created = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QWebEngineView()
        layout.addWidget(self.view)

        self.channel = QWebChannel()
        self.bridge  = ProjectBridge(parent_window=self.parent())
        self.channel.registerObject("projectBridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        # Forward the signal out so the main window can react
        self.bridge.project_created.connect(self.project_created.emit)

        self.view.load(QUrl.fromLocalFile(os.path.abspath("web/project.html")))


# ──────────────────────────────────────────────────────────────────────────────
#  Standalone test
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = NewProjectWidget()
    w.setWindowTitle("New Project")
    w.resize(860, 640)

    def on_created(path):
        QMessageBox.information(w, "Done", f"Project created at:\n{path}")

    w.project_created.connect(on_created)
    w.show()
    sys.exit(app.exec_())