import os
import sys
import subprocess
import threading
import json
import requests
import zipfile
import shutil
import urllib.parse
import traceback
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QFileDialog, QMessageBox, QProgressBar, QLabel, QPushButton
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QUrl, QStandardPaths, QThread, QTimer
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
    # Emitted for progress updates
    progress_updated = pyqtSignal(int, str)  # (percentage, message)

    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window
        self._current_process = None
        self._should_cancel = False

    # ── Utility ───────────────────────────────────────────────────────────────

    def _run(self, cmd: list, cwd: str = None, stream_output: bool = True, timeout: int = 300) -> tuple[int, str]:
        """Run a shell command, stream output through log_message, return (returncode, combined_output)."""
        self.log_message.emit(f"$ {' '.join(cmd)}")
        import time
        try:
            self._current_process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            output_lines = []
            start_time = time.time()

            for line in iter(self._current_process.stdout.readline, ''):
                if self._should_cancel:
                    self._current_process.terminate()
                    self._current_process.wait()
                    return 1, "Operation cancelled by user"

                if time.time() - start_time > timeout:
                    self._current_process.terminate()
                    self._current_process.wait()
                    return 1, f"Command timed out after {timeout}s"

                line = line.rstrip()
                output_lines.append(line)
                if stream_output:
                    self.log_message.emit(line)

            self._current_process.wait()
            return self._current_process.returncode, "\n".join(output_lines)

        except FileNotFoundError as exc:
            msg = f"Command not found: {cmd[0]}  →  {exc}"
            self.log_message.emit(msg)
            return 1, msg
        except Exception as exc:
            msg = f"Error running command: {exc}"
            self.log_message.emit(msg)
            return 1, msg
        finally:
            self._current_process = None
            
            
    def _run_with_input(self, cmd: list, input_text: str, cwd: str = None, timeout: int = 300) -> tuple[int, str]:
        """Like _run but pipes input_text to stdin — for interactive CLI tools."""
        self.log_message.emit(f"$ {' '.join(cmd)}")
        import time
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                output, _ = proc.communicate(input=input_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                return 1, f"Command timed out after {timeout}s"

            for line in output.splitlines():
                self.log_message.emit(line)

            return proc.returncode, output

        except FileNotFoundError as exc:
            msg = f"Command not found: {cmd[0]} → {exc}"
            self.log_message.emit(msg)
            return 1, msg
        except Exception as exc:
            msg = f"Error running command: {exc}"
            self.log_message.emit(msg)
            return 1, msg

    def _check_tool(self, tool: str) -> bool:
        """Return True if `tool` is on PATH."""
        return shutil.which(tool) is not None

    # ── Browse for directory ───────────────────────────────────────────────────

    @pyqtSlot(result=str)
    def browse_directory(self) -> str:
        desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        path = QFileDialog.getExistingDirectory(None, "Select Project Parent Directory", desktop)
        return path or ""

    # ── Cancel operation ───────────────────────────────────────────────────────

    @pyqtSlot()
    def cancel_operation(self):
        """Cancel the current operation."""
        self._should_cancel = True
        if self._current_process:
            self._current_process.terminate()
        self.log_message.emit("Cancelling operation...")

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

        # Reset cancel flag
        self._should_cancel = False

        # Dispatch in background thread so the UI stays responsive
        thread = threading.Thread(
            target=self._dispatch,
            args=(project_type, project_name, target_dir, project_path, cfg),
            daemon=True,
        )
        thread.start()

    def _dispatch(self, project_type, project_name, target_dir, project_path, cfg):
        self._ensure_npm_cache() 
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
        self.progress_updated.emit(10, f"Creating {framework} project structure...")

        if not self._check_tool("python3") and not self._check_tool("python"):
            self.creation_failed.emit("Python not found on PATH.")
            return

        py = "python3" if self._check_tool("python3") else "python"

        # Create virtualenv inside project folder
        os.makedirs(project_path, exist_ok=True)
        self.progress_updated.emit(20, "Creating virtual environment...")
        rc, _ = self._run([py, "-m", "venv", "venv"], cwd=project_path)
        if rc != 0:
            self.creation_failed.emit("Failed to create virtual environment.")
            return

        # Determine pip path inside venv
        venv_pip = os.path.join(project_path, "venv", "bin", "pip")
        if not os.path.exists(venv_pip):
            venv_pip = os.path.join(project_path, "venv", "Scripts", "pip.exe")

        self.progress_updated.emit(40, f"Installing {framework}...")

        if framework == "django":
            rc, _ = self._run([venv_pip, "install", "django"], cwd=project_path)
            if rc != 0:
                self.creation_failed.emit("Failed to install Django.")
                return

            django_admin = os.path.join(project_path, "venv", "bin", "django-admin")
            if not os.path.exists(django_admin):
                django_admin = os.path.join(project_path, "venv", "Scripts", "django-admin.exe")

            self.progress_updated.emit(70, "Creating Django project structure...")
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

            self.progress_updated.emit(70, "Creating Flask project structure...")
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

        self.progress_updated.emit(100, "Python project created successfully.")
        self.log_message.emit("✅  Python project created successfully.")
        self.project_created.emit(project_path)

    # ── 2. Java – Spring Boot with Maven ─────────────────────────────────────

    def _create_java(self, name, target_dir, project_path, cfg):
        self.log_message.emit(f"☕  Creating Java/Spring Boot project: {name}")
        self.progress_updated.emit(10, "Fetching Spring Initializr metadata...")

        zip_path = os.path.join(target_dir, f"{name}.zip")
        
        def get_package_path(base_path, group_id, artifact_id):
            package = f"{group_id}.{artifact_id}".replace("-", "").lower()
            return os.path.join(
                base_path,
                "src", "main", "java",
                *package.split(".")
            )


        try:
            # ── 1. Fetch metadata (dynamic config) ───────────────────────────────
            meta_url = "https://start.spring.io/metadata/client"
            meta = requests.get(meta_url).json()

            # Get latest default Spring Boot version
            # Hard whitelist of known-good versions
            SAFE_SPRING_VERSIONS = [
                "3.5.9",
                "3.4.5"
            ]

            spring_boot = SAFE_SPRING_VERSIONS[0]  # always pick latest safe

            self.log_message.emit(f"Using Spring Boot version: {spring_boot}")



            
            # Config inputs
            java_version = cfg.get("java_version", "17")
            group_id     = cfg.get("group_id", "com.example")

            # Support multiple dependencies cleanly
            framework = cfg.get("java_framework", "spring")

            if framework == "vaadin":
                dependencies = "web,vaadin"
            else:
                deps_input = cfg.get("dependencies", "web")
                dependencies = ",".join([
                    d.strip() for d in deps_input.split(",") if d.strip()
                ]) or "web"


            # Optional enhancements
            packaging = cfg.get("packaging", "jar")   # jar | war
            build_tool = cfg.get("build_tool", "maven")  # maven | gradle
            language = cfg.get("language", "java")   # java | kotlin

            # Sanitize project name
            safe_name = name.replace(" ", "-").lower()

            self.progress_updated.emit(25, "Preparing project request...")

            # ── 2. Build request params ─────────────────────────────────────────
            params = {
                "type": "maven-project" if build_tool == "maven" else "gradle-project",
                "language": language,
                "bootVersion": spring_boot,
                "baseDir": safe_name,
                "groupId": group_id,
                "artifactId": safe_name,
                "name": name,
                "packaging": packaging,
                "javaVersion": java_version,
                "dependencies": dependencies
            }

            self.log_message.emit(f"Using Spring Boot version: {spring_boot}")
            self.log_message.emit(f"Dependencies: {dependencies}")

            # ── 3. Download project ─────────────────────────────────────────────
            self.progress_updated.emit(40, "Downloading project...")

            response = requests.get(
                "https://start.spring.io/starter.zip",
                params=params,
                stream=True
            )

            # Better error reporting
            if response.status_code != 200:
                try:
                    error_json = response.json()
                    msg = error_json.get("message", str(error_json))
                except:
                    msg = response.text[:500]
                self.creation_failed.emit(f"Spring Initializr error: {msg}")
                return

            content_type = response.headers.get("content-type", "")
            if "zip" not in content_type:
                self.creation_failed.emit(f"Expected zip file, got {content_type}")
                return

            # Download with progress
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self._should_cancel:
                        response.close()
                        os.remove(zip_path)
                        return

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = 40 + int((downloaded / total_size) * 40)
                            self.progress_updated.emit(
                                progress,
                                f"Downloading... {downloaded // 1024} KB"
                            )

            # ── 4. Extract ──────────────────────────────────────────────────────
            self.progress_updated.emit(85, "Extracting project...")

            if not zipfile.is_zipfile(zip_path):
                self.creation_failed.emit("Downloaded file is not a valid zip.")
                os.remove(zip_path)
                return

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(target_dir)

            os.remove(zip_path)

            # Rename folder if needed
            extracted_path = os.path.join(target_dir, safe_name)
            if extracted_path != project_path and os.path.exists(extracted_path):
                if os.path.exists(project_path):
                    shutil.rmtree(project_path)
                shutil.move(extracted_path, project_path)


            if framework == "vaadin":
                self.log_message.emit("Applying Vaadin UI template...")
                self._apply_vaadin_template(project_path, group_id, safe_name)


            # ── 5. Success ──────────────────────────────────────────────────────
            self.progress_updated.emit(100, "Spring Boot project created.")
            self.log_message.emit("✅  Java/Spring Boot project created successfully.")
            self.project_created.emit(project_path)
            
            


        except requests.exceptions.RequestException as e:
            self.creation_failed.emit(f"Network error: {e}")
            if os.path.exists(zip_path):
                os.remove(zip_path)

        except Exception as e:
            error_details = traceback.format_exc()
            self.log_message.emit(error_details)  # shows full stack in console
            self.creation_failed.emit(f"Error: {str(e) or type(e).__name__}")
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def _apply_vaadin_template(self, project_path, group_id, artifact_id):
        try:
            package = f"{group_id}.{artifact_id}".replace("-", "").lower()

            package_path = os.path.join(
                project_path,
                "src", "main", "java",
                *package.split(".")
            )

            views_path = os.path.join(package_path, "views")
            os.makedirs(views_path, exist_ok=True)

            base_package = f"{package}.views"

            # MainView
            main_view = f"""package {base_package};

import com.vaadin.flow.component.applayout.AppLayout;
import com.vaadin.flow.component.html.H2;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.RouterLink;

public class MainView extends AppLayout {{

    public MainView() {{
        H2 logo = new H2("Vaadin App");

        RouterLink dashboard = new RouterLink("Dashboard", DashboardView.class);

        VerticalLayout menu = new VerticalLayout(logo, dashboard);
        addToDrawer(menu);
    }}
}}
    """

            # DashboardView
            dashboard_view = f"""package {base_package};

import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.notification.Notification;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.Route;

@Route(value = "", layout = MainView.class)
public class DashboardView extends VerticalLayout {{

    public DashboardView() {{
        setSizeFull();
        setAlignItems(Alignment.CENTER);
        setJustifyContentMode(JustifyContentMode.CENTER);

        H1 title = new H1("Dashboard");

        Button btn = new Button("Click Me", e ->
            Notification.show("Vaadin is working 🚀")
        );

        add(title, btn);
    }}
}}
    """

            with open(os.path.join(views_path, "MainView.java"), "w") as f:
                f.write(main_view)

            with open(os.path.join(views_path, "DashboardView.java"), "w") as f:
                f.write(dashboard_view)

            self.log_message.emit("✅ Vaadin template applied")

        except Exception as e:
            self.log_message.emit(f"Vaadin template error: {e}")





    # ── 3. Android – React Native + Expo ──────────────────────────────────────

    def _create_android(self, name, target_dir, project_path, cfg):
        self._ensure_npm_cache()
        self.log_message.emit(f"📱  Creating Android/Expo project: {name}")
        self.progress_updated.emit(10, "Initializing Expo project...")

        bare_workflow = cfg.get("bare_workflow", False)
        include_ios   = cfg.get("include_ios", False)

        if not self._check_tool("npx"):
            self.creation_failed.emit("npx not found. Please install Node.js.")
            return

        # Step 1 – scaffold only, skip install
        self.progress_updated.emit(25, "Scaffolding Expo project...")
        rc, _ = self._run_with_input(
            ["npx", "--yes", "create-expo-app@latest", name, "--template", "blank", "--no-install"],
            input_text="\n",
            cwd=target_dir,
            timeout=120
        )
        if rc != 0:
            self.creation_failed.emit("create-expo-app failed.")
            return

        # Step 2 – install with cache + offline preference
        self.progress_updated.emit(45, "Installing dependencies (cached)...")
        rc, _ = self._run(
            ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
            cwd=project_path,
            stream_output=False,
            timeout=180
        )
        if rc != 0:
            self.creation_failed.emit("npm install failed.")
            return

        # Step 3 – bare workflow (optional)
        if bare_workflow:
            self.progress_updated.emit(70, "Running expo prebuild (bare workflow)...")
            prebuild_cmd = ["npx", "expo", "prebuild", "--clean"]
            if not include_ios:
                prebuild_cmd += ["--platform", "android"]
            rc, _ = self._run(prebuild_cmd, cwd=project_path, timeout=300)
            if rc != 0:
                self.creation_failed.emit("expo prebuild failed.")
                return

        self.progress_updated.emit(100, "Expo project created successfully.")
        self.log_message.emit("✅  Expo project created successfully.")
        self.project_created.emit(project_path)

    # ── 4. Web – React variants ───────────────────────────────────────────────

    def _create_web(self, name, target_dir, project_path, cfg):
        variant  = cfg.get("web_variant", "react-bare")
        css_tool = cfg.get("css_tool", "css3")

        self.log_message.emit(f"🌐  Creating Web project ({variant}, {css_tool}): {name}")
        self.progress_updated.emit(10, f"Initializing {variant} project...")

        if not self._check_tool("npx"):
            self.creation_failed.emit("npx not found. Please install Node.js.")
            return

        if variant in ("react-bare", "vite"):
            self.progress_updated.emit(30, "Scaffolding Vite project...")

            # Use _run_with_input to answer any interactive prompts automatically
            rc, _ = self._run_with_input(
                ["npx", "--yes", "create-vite@latest", name, "--template", "react-ts"],
                input_text="\n",   # hits Enter on any confirmation prompt
                cwd=target_dir,
                timeout=120
            )
            if rc != 0:
                self.creation_failed.emit("create-vite failed.")
                return

            self.progress_updated.emit(60, "Installing dependencies...")
            rc, _ = self._run(
                ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
                cwd=project_path,
                stream_output=False,
                timeout=180
            )
            if rc != 0:
                self.creation_failed.emit("npm install failed.")
                return

            if css_tool == "tailwind":
                self.progress_updated.emit(80, "Adding Tailwind CSS...")
                self._add_tailwind_vite(project_path)

        elif variant == "nextjs":
            args = [
                "npx", "--yes", "create-next-app@latest", name,
                "--ts", "--eslint", "--app", "--no-git",
                "--tailwind" if css_tool == "tailwind" else "--no-tailwind"
            ]
            self.progress_updated.emit(30, "Creating Next.js project...")
            rc, _ = self._run_with_input(
                args,
                input_text="\n\n\n\n\n",  # answer any prompts with defaults
                cwd=target_dir,
                timeout=300
            )
            if rc != 0:
                self.creation_failed.emit("create-next-app failed.")
                return

        else:
            self.creation_failed.emit(f"Unknown web variant: {variant}")
            return

        self.progress_updated.emit(100, "Web project created successfully.")
        self.log_message.emit("✅  Web project created successfully.")
        self.project_created.emit(project_path)

    #------------------------------------ cache checker--------------------

    def _ensure_npm_cache(self):
        """Point npm to a persistent cache to avoid re-downloading packages."""
        cache_dir = os.path.join(os.path.expanduser("~"), ".npm_cache")
        os.makedirs(cache_dir, exist_ok=True)
        self._run(["npm", "config", "set", "cache", cache_dir], stream_output=False)

    # ── Tailwind helpers ──────────────────────────────────────────────────────

    def _add_tailwind_cra(self, project_path):
        self.log_message.emit("Adding Tailwind CSS to CRA project …")
        self._run(
            ["npm", "install", "--prefer-offline" ,"-D", "tailwindcss", "postcss", "autoprefixer"],
            cwd=project_path,
            stream_output=False
        )
        self._run(["npx", "tailwindcss", "init", "-p"], cwd=project_path, stream_output=False)
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
            ["npm", "install", "--prefer-offline", "-D", "tailwindcss", "postcss", "autoprefixer"],
            cwd=project_path,
            stream_output=False
        )
        self._run(["npx", "tailwindcss", "init", "-p"], cwd=project_path, stream_output=False)
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
