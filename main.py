import sys
import os
import json
import shutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QTextEdit, QTreeView, QFileSystemModel, QInputDialog, 
                             QMessageBox, QTabBar, QTabWidget, QLabel, QToolButton, QAction, QMenu, QFileDialog,
                             QSplitter)
from PyQt5.QtGui import QFont, QIcon, QTextCursor, QTextDocument, QPixmap, QDesktopServices,  QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt5.QtCore import Qt, QDir, QUrl, QRegularExpression, QSize, QObject, pyqtSlot
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEngineView
import subprocess
from pathlib import Path
from utils.numbers import NumberedCodeEditor, MarkdownContainer, FindBar
from utils.highlighter import get_highlighter, check_syntax
from components.Terminal import TerminalManager
from utils.tree_features import setup_tree_context_menu, toolbar_new_file
from utils.git_bridge import GitBridge
from utils.themes import ThemeEngine
from components.AI import AIPanel
from components.new_project import NewProjectWidget
from utils.recent_projects import RecentProjects
from components.database import DatabasePanel, DBBridge
from components.debug import DebugPanel



class WebBridge(QObject, GitBridge):
    def __init__(self, CodeEditor):
        QObject.__init__(self)
        GitBridge.__init__(self)
        self.mainWindow = CodeEditor

    
    @pyqtSlot()
    def testing(self):
        print(f"hello this is the hoome directory:  {str(Path.home())}")
        
    @pyqtSlot()    
    def OpenFiles(self):
        self.mainWindow.open_file_searcher()
        
    @pyqtSlot(str)    
    def install_plugin(self, name):
        print("checking plugin")
        
        
    @pyqtSlot(str)    
    def save_settings(settings):
        print("saving settings")
        
    @pyqtSlot()
    def open_theme_studio(self):
        self.mainWindow.show_themes_page()  # toggle themes page visible
        
    @pyqtSlot(str)
    def open_directory(self, path):
        self.mainWindow.update_directory(path)

    @pyqtSlot()
    def start_new_project(self):
        self.mainWindow.start_project()

    @pyqtSlot()
    def toggle_terminal(self):
        self.mainWindow.toggle_terminal()

    @pyqtSlot()
    def toggle_git(self):
        self.mainWindow.github()

    @pyqtSlot()
    def toggle_settings(self):
        self.mainWindow.settings()

        
##################### DOCS #########################
"""
WEb bridge connects the html rendered page to call functions
-register in the main code

"""
        

class MyCustomHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        # Define your rules here
        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor("blue"))

    def highlightBlock(self, text):
        # This method is called automatically for every line
        expression = QRegularExpression(r"\bclass\b")
        match_iterator = expression.globalMatch(text)
        while match_iterator.hasNext():
            match = match_iterator.next()
            self.setFormat(match.capturedStart(), match.capturedLength(), self.keyword_format)




class CustomFileSystemModel(QFileSystemModel):
    def __init__(self):
        super().__init__()
        # Load custom icons
        self.kotlin_icon = QIcon('images/fileIcons/kotlin.png')  # Replace with actual path
        self.java_icon = QIcon('images/fileIcons/java2.png')      # Replace with actual path
        self.javaClass_icon = QIcon('images/fileIcons/javaClass.png')      # Replace with actual path
        self.gradle_icon = QIcon('images/fileIcons/gradle.png')  # Replace with actual path
        self.xml_icon = QIcon('images/fileIcons/xml.png')  # Replace with actual path
        self.kts_icon = QIcon('images/fileIcons/kts2.png')  # Replace with actual path
        self.toml_icon = QIcon('images/fileIcons/toml.png')  # Replace with actual path
        self.properties_icon = QIcon('images/fileIcons/properties.png')  # Replace with actual path
        self.git_icon = QIcon('images/fileIcons/git.png')
        self.firebase_icon = QIcon('images/fileIcons/firebase.png')
        self.firefolder_icon = QIcon('images/fileIcons/firefolder.png')
        self.html_icon = QIcon('images/fileIcons/html.png')
        self.css_icon = QIcon('images/fileIcons/css.png')
        self.javascript_icon = QIcon('images/fileIcons/js.png')
        self.typescript_icon = QIcon('images/fileIcons/typescript.png')
        self.C_icon = QIcon('images/fileIcons/C.png')
        self.CPP_icon = QIcon('images/fileIcons/c++.png')
        self.python_icon = QIcon('images/fileIcons/python.png')
        self.react_icon = QIcon('images/fileIcons/react.png')
        self.database_icon = QIcon('images/fileIcons/database.png')
        self.image_icon = QIcon('images/fileIcons/imagefile.png')
        self.android_icon = QIcon('images/fileIcons/apk.png')
        self.android_folder =QIcon('images/fileIcons/androidFolder.png')
        self.json_icon =QIcon('images/fileIcons/json.png')
        self.linux_icon =QIcon('images/fileIcons/linux.png')
        self.readme_icon = QIcon('images/fileIcons/readme.png')
        self.markdown_icon = QIcon('images/fileIcons/md.png')
        self.pom_icon = QIcon('images/fileIcons/pom.png')


    def data(self, index, role):
        # Check if this is the icon role for the file name column
        if role == Qt.DecorationRole and index.column() == 0:
            file_path = self.filePath(index)
            file_name = os.path.basename(file_path) 
            
            # Check file extensions and return custom icons
            if file_name.endswith('.kt'):
                return self.kotlin_icon
            elif file_name.endswith('.java'):
                return self.java_icon
            elif file_name.endswith('.class'):
                return self.javaClass_icon
            elif file_name.endswith('.gradle'):
                return self.gradle_icon
            elif file_name.endswith('.xml'):
                return self.xml_icon
            elif file_name.endswith('.kts'):
                return self.kts_icon
            elif file_name.endswith('.toml'):
                return self.toml_icon
            elif file_name.endswith('pom.xml'):
                return self.pom_icon
            elif file_name.endswith('.properties'):
                return self.properties_icon
            elif file_name.endswith('.gitignore'):
                return self.git_icon
            elif file_name.endswith('firebase.js'):
                return self.firebase_icon
            elif file_name.endswith('.firebaserc'):
                return self.firebase_icon
            elif file_name.endswith('.firebase'):
                return self.firefolder_icon
            elif file_name.endswith('.html'):
                return self.html_icon
            elif file_name.endswith('.css'):
                return self.css_icon
            elif file_name.endswith('.js'):
                return self.javascript_icon
            elif file_name.endswith('.ts'):
                return self.typescript_icon
            elif file_name.endswith('.cpp'):
                return self.CPP_icon
            elif file_name.endswith('.py'):
                return self.python_icon
            elif file_name.endswith(('.png','.gif','.jpg','.bmp','.jpeg','.webp')):
                return self.image_icon
            elif file_name.endswith('.tsx'):
                return self.react_icon
            elif file_name.endswith('.jsx'):
                return self.react_icon
            elif file_name.endswith(('.sql','.db')):
                return self.database_icon
            elif file_name.endswith('.apk'):
                return self.android_icon
            elif file_name.endswith('android'):
                return self.android_folder
            elif file_name.endswith('.json'):
                return self.json_icon
            elif file_name.endswith('.desktop') or file_name.endswith('.deb'):
                return self.linux_icon
            elif file_name.lower().startswith('readme.md'):
                return self.readme_icon
            elif file_name.endswith('.md'):
                return self.markdown_icon
        # For all other cases, use the default implementation
        return super().data(index, role)




#main code logic
class CodeEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.plugins_visible = False
        self.github_visible = False
        
        
        ############   Themes
        self.theme_engine = ThemeEngine(self)
        self.themePage_visible = False
        self.Ai_visible = False
        self.active_panel = None
        self.debug_index = False
        
        
        
        self.settings_visible = False
        #self.plugin_manager = PluginManager()  # Initialize plugin manager
        self.recent_projects = RecentProjects()
        self.base_directory = None
       
        self.open_files = {}  # Dictionary to track open files
        self.modified_indicator = "● "
        self.modified_indicator_color = "#4CAF50"  # green
        self.current_file_tabs = QTabWidget()  # Create a tab widget
        
        self.setup_shortcuts()
        self.initUI()

        # Create the fixed AI button with a specific position
        #self.ai_fab = FixedAIButton(self, position='bottom-right')  # or any other position
        #self.ai_fab.show()
        #self.ai_fab.setVisible(True)

        # Example of how to change position:
        #self.ai_fab.set_position('bottom-left')  # Use predefined position
        #self.ai_fab.set_position((750, 300))   # Use custom coordinates
        



    def initUI(self):
        
        
        self.setWindowTitle(f"Ikaris Dev Studio - 2024-V3 TM.")
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowIcon(QIcon('images/ANDROID_MINI.png'))
        
        ## create a menu bar and place "files" and "create project"
# --- MENU BAR SETUP ---
        menubar = self.menuBar() # Access the native QMainWindow menu bar
        
        # 1. File Menu
        file_menu = menubar.addMenu("&File")
        
        # Create 'New Project' Action
        new_project_act = QAction("Create Project", self)
        new_project_act.setShortcut("Ctrl+N")
        new_project_act.triggered.connect(self.start_project) # Connect to your function
        file_menu.addAction(new_project_act)
        
        # Add a separator
        file_menu.addSeparator()
        
        open_recents = QAction("Open Recent Projects", self)
        open_recents.triggered.connect(self.show_recent_projects)
        file_menu.addAction(open_recents)
        
        # Add a separator
        file_menu.addSeparator()
        
        # Create 'New Project' Action
        open_folder = QAction("Open Folder", self)
        open_folder.setShortcut("Ctrl+Shift+O")
        open_folder.triggered.connect(self.open_file_searcher) # Connect to your function
        file_menu.addAction(open_folder)
        
        # Add a separator
        file_menu.addSeparator()
        
        
        # Create 'Exit' Action
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        # 2. Add other menus (Example: View)
        view_menu = menubar.addMenu("&View")
        toggle_terminal_act = QAction("Toggle Terminal", self)
        toggle_terminal_act.triggered.connect(self.toggle_terminal) # Example function
        view_menu.addAction(toggle_terminal_act)
       

        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create left sidebar for buttons
        left_sidebar = QWidget()
        left_sidebar.setFixedWidth(70)
        left_sidebar_layout = QVBoxLayout(left_sidebar)
        left_sidebar_layout.setContentsMargins(5, 5, 5, 5)
        left_sidebar_layout.setSpacing(2)
        
        

        # Create right-side container for everything else
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Create VERTICAL splitter for editor and terminal
        self.vertical_splitter = QSplitter(Qt.Vertical)

        # Create main HORIZONTAL splitter for tree view and editor
        self.main_splitter = QSplitter(Qt.Horizontal)

        # Create tree view container
        self.tree_container = QWidget()
        self.tree_container.setMinimumWidth(200)
        self.tree_container.setMaximumWidth(400)
        tree_layout = QVBoxLayout(self.tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(2)
        
        
        #DB CONNECT LAYOUT
        self.db_container = QWidget()
        self.db_container.setMinimumWidth(200)
        self.db_container.setMaximumWidth(400)
        db_layout = QVBoxLayout(self.db_container)
        db_layout.setContentsMargins(0,0,0,0)
        db_layout.setSpacing(2)
        
        #Debug LAYOUT
        self.debug_container = QWidget()
        self.debug_container.setMinimumWidth(200)
        self.debug_container.setMaximumWidth(400)
        debug_layout = QVBoxLayout(self.debug_container)
        debug_layout.setContentsMargins(0,0,0,0)
        debug_layout.setSpacing(2)
        
        
        # Create Right sidebar for AI
        self.ai_container = QWidget()
        self.ai_container.setMinimumWidth(200)
        self.ai_container_layout = QVBoxLayout(self.ai_container)
        self.ai_container_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_container_layout.setSpacing(2)

        # Create tree operations toolbar
        tree_toolbar = QWidget()
        tree_toolbar.setMaximumHeight(40)
        tree_toolbar_layout = QHBoxLayout(tree_toolbar)
        tree_toolbar_layout.setContentsMargins(4, 2, 4, 2)
        tree_toolbar_layout.setSpacing(4)

        # Create file operation buttons
        file_op_buttons = [
            ('New Folder', 'images/UI/newFile.png', self.create_new_folder),
            ('New File', 'images/UI/newdoc.png', self.create_new_file),
            ('Delete', 'images/UI/delete.png', self.delete_file),
            ('Rename', 'images/UI/rename.png', self.rename_file),
            #('AI', 'images/UI/ai.png',lambda: self.AI()),
        ]

        for text, icon_path, callback in file_op_buttons:
            btn = self.create_button('', icon_path, callback)
            btn.setFixedSize(20, 20)
            btn.setToolTip(text)
            tree_toolbar_layout.addWidget(btn)

        tree_layout.addWidget(tree_toolbar)

        # Set up tree view
        self.setup_sidePanel_view("tree", tree_layout)
        self.setup_sidePanel_view("db", db_layout)
        self.setup_sidePanel_view("debug", debug_layout)

        setup_tree_context_menu(self)

        # Create editor container
        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)

        # Set up editor and image label
        self.setup_editor_and_image(editor_layout)
        
       

        # Add tree and editor to horizontal splitter
        self.main_splitter.addWidget(self.tree_container)
        self.main_splitter.addWidget(self.db_container)
        self.main_splitter.addWidget(self.debug_container)
        self.main_splitter.addWidget(editor_container)
        self.main_splitter.addWidget(self.ai_container)

        

        # Create terminal container (initially hidden)
        self.terminal_container = QWidget()
        self.terminal_container.setVisible(True)
        terminal_layout = QVBoxLayout(self.terminal_container)
        terminal_layout.setContentsMargins(0, 0, 0, 0)
        
        self.terminal_manager = TerminalManager(
        self.terminal_container,
        terminal_layout,
        get_cwd=lambda: self.base_directory  # tracks your open project folder
        )
        
        
        # Initialize terminal widget as None
        self.terminal_widget = None
        self.terminal_visible = False

        # Add main splitter to vertical splitter
        self.vertical_splitter.addWidget(self.main_splitter)
        self.vertical_splitter.addWidget(self.terminal_container)
        
        # Set initial sizes for vertical splitter (editor takes all space initially)
        self.vertical_splitter.setSizes([800, 0])

        # Add vertical splitter to right container
        right_layout.addWidget(self.vertical_splitter)

        # Add sidebar and right container to main layout
        main_layout.addWidget(left_sidebar)
        main_layout.addWidget(right_container)
        #main_layout.addWidget(self.ai_container)

        # Create sidebar buttons
        self.create_sidebar_buttons(left_sidebar_layout)

        # Set initial splitter sizes for horizontal splitter
        # Order: tree_container | db_container | debug_container | editor_container | ai_container
        self.main_splitter.setSizes([0, 0, 0, 1200, 0])

        # Initialize state variables
        self.current_file = None
        self.tree_visible = False
        self.tree_container.setVisible(self.tree_visible)
        self.ai_container.setVisible(self.Ai_visible)

        
        # Create the fixed AI button
        #self.ai_fab = FixedAIButton(self, position='bottom-right')
        #self.ai_fab.show()
        #self.ai_fab.setVisible(True)


    def create_sidebar_buttons(self, layout):
        # Create buttons with icons (excluding file operations)
        buttons_data = [
            ('Toggle Tree', 'images/UI/file.png', lambda: self.toggle_tree_view()),
            #('Create Project', 'images/UI/layer-plus.png', self.start_project),
            ('Run', 'images/UI/play2.png', self.open_debug),
            ('commit', 'images/UI/code-branch.png',lambda: self.github()),
            ('run server', 'images/UI/database.png',lambda: self.open_db()),
            #('Plugins', 'images/UI/menu.png', lambda: self.plugins()),
            #('open existing project', 'images/UI/folder-open.png', self.open_file_searcher),
            ('open terminal', 'images/UI/terminal2.png', self.toggle_terminal),
            ('settings', 'images/UI/gear.png',lambda: self.settings()),
            ('AI', 'images/UI/ai.png',lambda: self.AI()),
        ]

        for text, icon_path, callback in buttons_data:
            btn = self.create_button('', icon_path, callback)
            btn.setFixedSize(50, 60)
            btn.setIconSize(QSize(40, 40))
            btn.setToolTip(text)
            layout.addWidget(btn)

        

        # Add options button
        self.create_options_button(layout)
        
        # Add stretch to push buttons to top
        layout.addStretch()

    def create_options_button(self, layout):
        self.tool_button = QToolButton()
        self.tool_button.setFixedSize(40, 40)
        self.tool_button.setIcon(QIcon('images/folder.png'))
        self.tool_button.setToolTip('Options')
        self.tool_button.setPopupMode(QToolButton.MenuButtonPopup)

        menu = QMenu(self)
        actions = [
            ('Edit XML', lambda: self.option_selected('')),
        ]

        for text, callback in actions:
            action = QAction(text, self)
            action.triggered.connect(callback)
            menu.addAction(action)

        #self.tool_button.setMenu(menu)
        #layout.addWidget(self.tool_button)

    def setup_sidePanel_view(self, panel_type, layout):
        """
        panel_type: "tree" | "db" | "debug"
        layout: QVBoxLayout
        """

        if panel_type == "tree":
            self.setup_tree_view(layout)

        elif panel_type == "db":
            self.setup_db_panel(layout)

        elif panel_type == "debug":
            self.setup_debug_panel(layout)

    def show_panel(self, panel_name):
        """Show exactly one side panel (tree/db/debug) and hide the others.
        Adjusts splitter sizes so the visible panel actually takes up space.
        Pass None to hide all side panels."""
        self.active_panel = panel_name

        show_tree  = (panel_name == "tree")
        show_db    = (panel_name == "db")
        show_debug = (panel_name == "debug")

        self.tree_container.setVisible(show_tree)
        self.db_container.setVisible(show_db)
        self.debug_container.setVisible(show_debug)

        # Keep tree_visible flag in sync
        self.tree_visible = show_tree

        # Splitter order: tree | db | debug | editor | ai
        side_width   = 250 if panel_name is not None else 0
        ai_width     = 300 if self.Ai_visible else 0
        editor_width = max(0, 1200 - side_width - ai_width)

        self.main_splitter.setSizes([
            side_width if show_tree  else 0,
            side_width if show_db    else 0,
            side_width if show_debug else 0,
            editor_width,
            ai_width,
        ])


    def setup_tree_view(self, layout):
    
        # Create directory label
        self.dir_label = QLabel()
        self.dir_label.setStyleSheet("""
            QLabel {
                padding: 5px;
                border-bottom: 1px solid #ddd;
                font-weight: bold;
            }
        """)
        
        # Set up model and tree
        self.model = CustomFileSystemModel()
        self.model.setRootPath(QDir.rootPath())
        
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setAnimated(False)
        self.tree.setIndentation(20)
        self.tree.setHeaderHidden(True)

        
        # Enable and set up sorting
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        
        # Set column properties
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)
        
        
        # Connect signals
        self.tree.clicked.connect(self.file_clicked)
        
        # Update directory label and tree view based on base_directory
        self.update_directory_label()
        self.update_tree_view()
        
        # Add widgets to layout
        layout.addWidget(self.dir_label)
        layout.addWidget(self.tree)


    def setup_db_panel(self, layout):
        # DatabasePanel creates its own internal channel for DBBridge.
        # self.channel (for WebBridge/ThemeEngine/etc) is set up in setup_editor_and_image.
        self.database_panel = DatabasePanel(
            db_layout    = layout,
            main_window  = self,
            channel      = None,   # panel manages its own channel
        )

    def setup_debug_panel(self, layout):
        # DebugPanel creates its own internal channel for DBBridge.
        # self.channel (for WebBridge/ThemeEngine/etc) is set up in setup_editor_and_image.
        self.debug_panel = DebugPanel(
            debug_layout    = layout,
            main_window  = self,
            channel      = None,   # panel manages its own channel
        )

        

    def update_directory_label(self):
        """Update the directory label with placeholder or current directory"""
        if self.base_directory is None:
            print(f"current directory {Path.home()}")
            self.dir_label.setText(f"📁 {Path.home()}")
            
        else:
            dir_name = os.path.basename(self.base_directory)
            self.dir_label.setText(f"📁 {dir_name}")

    def update_tree_view(self):
        """Update tree view based on base_directory"""
        if self.base_directory is None:
            self._dir = str(Path.home())
        else:
            self._dir = str(self.base_directory)
            # Show tree content for the selected directory
        self.tree.setRootIndex(self.model.index(self._dir))

    def setup_editor_and_image(self, layout):
        # Add file name label
        self.file_name_label = QLabel()
        self.file_name_label.setStyleSheet("""
            QLabel {
                padding: 5px;
                background-color: #1e1e1e;
                border-bottom: 1px solid #444444;
            }
        """)
        self.file_name_label.setVisible(False)  # Initially hidden
        
        self.editor = QTextEdit()
        
        self.editor.setFont(QFont('Courier', 12))
        
                # Create a comment highlighter and apply it to the editor
        self.highlighter = MyCustomHighlighter(self.editor.document())

        # Create bridge
        self.bridge = WebBridge(self)

        

        # Create channel
        self.channel = QWebChannel()
        self.channel.registerObject("WebBridge", self.bridge)
        self.channel.registerObject("ThemeEngine", self.theme_engine)
        self.channel.registerObject("RecentProjects", self.recent_projects)

        ## landing page
        self.landing_page = QWebEngineView()
        self.landing_page.page().setWebChannel(self.channel)
        self.landing_page.load(QUrl.fromLocalFile(os.path.abspath("web/landing.html")))
        
        ## Git pages
        self.gitHandler = QWebEngineView()
        self.gitHandler.page().setWebChannel(self.channel)
        self.gitHandler.load(QUrl.fromLocalFile(os.path.abspath("web/git.html")))
        self.bridge.setup_git(self.gitHandler)
        
        
        ## plugins page
        self.plugin_page = QWebEngineView()
        self.plugin_page.page().setWebChannel(self.channel)
        self.plugin_page.load(QUrl.fromLocalFile(os.path.abspath("web/plugins.html")))
        
        ## settings page
        self.settings_page = QWebEngineView()
        self.settings_page.page().setWebChannel(self.channel)
        self.settings_page.load(QUrl.fromLocalFile(os.path.abspath("web/settings.html")))
        
        ### Themes page
        self.themes_page = QWebEngineView()
        self.themes_page.page().setWebChannel(self.channel)
        self.themes_page.load(QUrl.fromLocalFile(os.path.abspath("web/themes.html")))
        self.theme_engine.setup(self.themes_page)
        self.theme_engine.apply_saved_theme()   # applies on startup

        ## new project page

        self.new_project_page = NewProjectWidget(self)
        self.new_project_page.project_created.connect(self.update_directory)
        layout.addWidget(self.new_project_page)
        self.new_project_page.setVisible(False)
        
        # database_view is owned by DatabasePanel (self.database_panel.database_view).
        # We just need a local reference so the layout addWidget call below works.
        # DatabasePanel is set up in setup_db_panel(), called earlier in initUI.
        
        
        
        # AI channel
        from components.AI import AIPanel
        self.ai_panel = AIPanel(
            container   = self.ai_container,
            layout      = self.ai_container_layout,
            main_window = self,
            channel     = self.channel,   # reuse your existing channel
        )
        
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)

        pixmap = QPixmap('images/IKARIS.png')
        scaled_pixmap = pixmap.scaled(500, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self.image_label.setPixmap(scaled_pixmap)


        layout.addWidget(self.file_name_label)  # Add label first

        layout.addWidget(self.editor)
        layout.addWidget(self.landing_page)
        layout.addWidget(self.plugin_page)
        layout.addWidget(self.image_label)
        layout.addWidget(self.gitHandler)
        layout.addWidget(self.settings_page)
        layout.addWidget(self.themes_page)
        layout.addWidget(self.current_file_tabs)
        layout.addWidget(self.new_project_page)
        layout.addWidget(self.database_panel.database_view)
        layout.addWidget(self.debug_panel.debug_view)

        self.find_bar = FindBar(self.current_file_tabs)
        layout.addWidget(self.find_bar)
        self.find_bar.setVisible(False)
                
        self.editor.setVisible(False)
        self.current_file_tabs.setVisible(False)
        self.image_label.setVisible(False)
        self.plugin_page.setVisible(False)
        self.gitHandler.setVisible(False)
        self.settings_page.setVisible(False)
        self.themes_page.setVisible(False)
        self.new_project_page.setVisible(False)     
        self.database_panel.database_view.setVisible(False)
        self.debug_panel.debug_view.setVisible(False)


    

    def create_button(self, text, icon_path, connection):
        button = QPushButton(text)
        button.setIcon(QIcon(icon_path))
        button.clicked.connect(connection)
        return button

    def toggle_tree_view(self, flag=None):
        if flag is not None and isinstance(flag, bool):
            self.tree_visible = flag
        else:
            self.tree_visible = not (self.active_panel == "tree")

        if self.tree_visible:
            self.show_panel("tree")
        else:
            self.show_panel(None)
            
    def open_db(self):
        if self.active_panel == "db":
            self.show_panel(None)            
        else:
            self.show_panel("db")
            self._hide_all_panels() 
            self.database_panel.database_view.setVisible(True) 

    def open_debug(self):
        if self.active_panel == "debug":
            # Toggle off
            self.show_panel(None)
            self.debug_panel.debug_view.setVisible(False)
        else:
            self.show_panel("debug")
            self._hide_all_panels()
            self.debug_panel.debug_view.setVisible(True)
            # Let the panel know which project is open
            if hasattr(self, 'base_directory') and self.base_directory:
                self.debug_panel.set_project_root(self.base_directory)

       
    
    def file_clicked(self, index):
        path = self.model.filePath(index)
        
        
        if os.path.isdir(path):
            self.current_folder = path
            self.current_file = None
            self.file_name_label.setVisible(False)
            return

        if os.path.isfile(path):
            self.current_file = path
            self.current_folder = None
            file_name = os.path.basename(path)
            self.file_name_label.setText(file_name)

            # Handle images
            if path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.gif', '.ico')):
                if path not in self.open_files:
                    self._hide_all_panels()
                    self.current_file_tabs.setVisible(True)
                    
                    
                    image_label = QLabel()
                    pixmap = QPixmap(path)
                    image_label.setPixmap(pixmap.scaled(image_label.size(), Qt.KeepAspectRatio))
                    image_label.setAlignment(Qt.AlignCenter)
                    
                    close_button = QPushButton("x")
                    close_button.setFixedSize(20, 20)
                    close_button.clicked.connect(lambda: self.close_tab(path))

                    # Style the tab bar for dark theme
                    self.current_file_tabs.setStyleSheet("""
                        QTabBar::tab {
                            background-color: #2d2d2d;
                            color: #ffffff;
                            padding: 5px;
                            font-style: italic;
                        }
                        QTabBar::tab:selected {
                            background-color: #3d3d3d;
                        }
                    """)

                    tab_index = self.current_file_tabs.addTab(image_label, file_name)
                    self.current_file_tabs.tabBar().setTabButton(tab_index, QTabBar.RightSide, close_button)
                    self.open_files[path] = {
                        'editor': image_label,
                        'tab_index': tab_index,
                        'modified': False
                    }
                    self.current_file_tabs.setCurrentIndex(tab_index)
                else:
                    tab_index = self.open_files[path]['tab_index']
                    self.current_file_tabs.setCurrentIndex(tab_index)
                return

            # Handle database files → open in DB panel
            if path.lower().endswith(('.db', '.sqlite', '.sqlite3', '.sql')):
                if hasattr(self, 'database_panel'):
                    self.show_panel("db")
                    self._hide_all_panels() 
                    self.database_panel.open_db_file(path)
                else:
                    QMessageBox.information(self, "Database", "Open the Database panel first.")
                return

            # Handle text files
            try:
                self._hide_all_panels() 
                self.current_file_tabs.setVisible(True)
 
                if path not in self.open_files:
                    # ── create editor ────────────────────────────────────
                    new_editor = NumberedCodeEditor(file_path=path)
                    new_editor.setFont(QFont('Courier', 12))
 
                    # ── attach syntax highlighter ─────────────────────────
                    hl = get_highlighter(path, new_editor.document())
                    new_editor.set_highlighter(hl)
 
                    # ── connect text-changed for modification tracking ─────
                    #    blockSignals around setText so loading ≠ "modified"
                    new_editor.blockSignals(True)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            new_editor.setText(f.read())
                    except UnicodeDecodeError:
                        QMessageBox.warning(self, "Encoding Error",
                                            "Cannot decode this file.")
                        new_editor.blockSignals(False)
                        return
                    new_editor.blockSignals(False)
 
                    # run first syntax check
                    self._run_syntax_check(path, new_editor)
 
                    # live syntax check on every edit (debounced enough for
                    # plain ast.parse; hook into a QTimer if you want delay)
                    new_editor.contentChanged.connect(
                        lambda text, p=path, ed=new_editor:
                            self._run_syntax_check(p, ed)
                    )
 
                    # modification tracking
                    new_editor.textChanged.connect(
                        lambda p=path: self.handle_text_changed(path)
                    )
 
                    # ── decide container: MarkdownContainer or bare editor ─
                    needs_preview = path.lower().endswith(('.md', '.markdown', '.html', '.htm'))
                    container = new_editor.get_markdown_container() if needs_preview else new_editor
 
                    # ── close button ──────────────────────────────────────
                    close_button = QPushButton("×")
                    close_button.setFixedSize(20, 20)
                    close_button.clicked.connect(lambda p=path: self.close_tab(path))
 
                    # ── tab styling ───────────────────────────────────────
                    self.current_file_tabs.setStyleSheet("""
                        QTabBar::tab {
                            background-color: #2d2d2d;
                            color: #ffffff;
                            padding: 5px 8px;
                            font-style: italic;
                        }
                        QTabBar::tab:selected { background-color: #3d3d3d; }
                    """)
 
                    tab_index = self.current_file_tabs.addTab(container, file_name)
                    self.current_file_tabs.tabBar().setTabButton(
                        tab_index, QTabBar.RightSide, close_button
                    )
 
                    self.open_files[path] = {
                        'editor':    new_editor,   # always the bare editor
                        'container': container,     # what's in the tab
                        'tab_index': tab_index,
                        'modified':  False,
                    }
                    self.current_file_tabs.setCurrentIndex(tab_index)
                    self.update_tab_appearance(path)
 
                else:
                    tab_index = self.open_files[path]['tab_index']
                    self.current_file_tabs.setCurrentIndex(tab_index)
 
            except UnicodeDecodeError:
                QMessageBox.warning(self, "Encoding Error",
                                    "Cannot decode this file.")


            #print(f'Selected file: {self.current_file}')               <--------------------print debug


    def _run_syntax_check(self, path: str, editor: "NumberedCodeEditor"):
        """Run syntax check and push results to the editor's gutter."""
        text   = editor.toPlainText()
        issues = check_syntax(path, text)
        editor.set_diagnostics(issues)
        
        
    def close_tab(self, path):
        if path in self.open_files:
            tab_index = self.open_files[path]['tab_index']
            self.current_file_tabs.removeTab(tab_index)
            del self.open_files[path]
        else:
            # Find the tab index by iterating through all tabs
            for i in range(self.current_file_tabs.count()):
                if self.current_file_tabs.tabText(i) == os.path.basename(path):
                    self.current_file_tabs.removeTab(i)
                    break
        
        # Update indices of remaining tabs
        self.update_tab_indices()
        
        # If no tabs are left, show the welcome image
        if self.current_file_tabs.count() == 0:
            self.current_file_tabs.setVisible(False)
            self.landing_page.setVisible(True)
            

    def update_tab_indices(self):
        """Update the stored tab indices after a tab is closed"""
        for path in self.open_files:
            widget = self.open_files[path]['editor']
            new_index = self.current_file_tabs.indexOf(widget)
            self.open_files[path]['tab_index'] = new_index

    def delete_file(self):
        if self.current_file:
            # Deleting a file
            reply = QMessageBox.question(self, 'Confirm Delete',
                                        f'Are you sure you want to delete the file "{self.current_file}"?',
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    os.remove(self.current_file)
                    QMessageBox.information(self, 'Deleted', f'File deleted: {self.current_file}')
                    self.editor.clear()  # Clear the text editor
                    self.current_file = None
                except OSError as e:
                    QMessageBox.warning(self, 'Error', f'Failed to delete file: {str(e)}')

        elif self.current_folder:
            # Deleting a folder
            reply = QMessageBox.question(self, 'Confirm Delete',
                                        f'Are you sure you want to delete the folder "{self.current_folder}" and all its contents?',
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    shutil.rmtree(self.current_folder)
                    QMessageBox.information(self, 'Deleted', f'Folder deleted: {self.current_folder}')
                    self.current_folder = None
                except OSError as e:
                    QMessageBox.warning(self, 'Error', f'Failed to delete folder: {str(e)}')
        else:
            QMessageBox.warning(self, 'Error', 'No file or folder is currently selected.')

    def rename_file(self):
        if self.current_file or self.current_folder:
            new_name, ok = QInputDialog.getText(self, 'Rename', 'Enter new name:')
            if ok and new_name:
                if self.current_file:
                    # Renaming a file
                    new_path = os.path.join(os.path.dirname(self.current_file), new_name)
                    try:
                        os.rename(self.current_file, new_path)
                        QMessageBox.information(self, 'Renamed', f'File renamed to: {new_path}')
                        self.current_file = new_path  # Update the current file path
                        # Update the editor with the renamed file's content
                        with open(new_path, 'r') as file:
                            self.editor.setText(file.read())
                    except OSError as e:
                        QMessageBox.warning(self, 'Error', f'Failed to rename file: {str(e)}')

                elif self.current_folder:
                    # Renaming a folder
                    new_path = os.path.join(os.path.dirname(self.current_folder), new_name)
                    try:
                        os.rename(self.current_folder, new_path)
                        QMessageBox.information(self, 'Renamed', f'Folder renamed to: {new_path}')
                        self.current_folder = new_path  # Update the current folder path
                    except OSError as e:
                        QMessageBox.warning(self, 'Error', f'Failed to rename folder: {str(e)}')
        else:
            QMessageBox.warning(self, 'Error', 'No file or folder is currently selected.')


#shortcuts
    def setup_shortcuts(self):
        """Set up keyboard shortcuts for common actions"""
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtWidgets import QShortcut

        # Save - Ctrl+S
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_current_file)

        # Open project - Ctrl+O
        open_shortcut = QShortcut(QKeySequence("Ctrl+Shift+O"), self)
        open_shortcut.activated.connect(self.open_file_searcher)


        # New project - Ctrl+N
        new_project_shortcut = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        new_project_shortcut.activated.connect(self.start_project)

        new_file = QShortcut(QKeySequence("Ctrl+N"), self)
        new_file.activated.connect(self.create_new_file)


        toggle_tree_view = QShortcut(QKeySequence("Ctrl+B"), self)
        toggle_tree_view.activated.connect(lambda: self.toggle_tree_view())


        # Git operations - Ctrl+G
        git_shortcut = QShortcut(QKeySequence("Ctrl+G"), self)
        git_shortcut.activated.connect(lambda: self.github())

        # Save All - Ctrl+Shift+S
        save_all_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        save_all_shortcut.activated.connect(self.save_all_files)

        # Find/Replace - Ctrl+F
        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self.show_find_replace_dialog)
        
        # Replace - Ctrl+H
        find_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        find_shortcut.activated.connect(self.show_replace_dialog)
        
        # Undo - Ctrl+Z
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self.undo_action)
        
        # Redo - Ctrl+Y
        redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_shortcut.activated.connect(self.redo_action)

        # call settings - Ctrl+Q
        settings_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        settings_shortcut.activated.connect(lambda: self.settings)

        # Toggle - Ctrl+Shift+I
        AI_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        AI_shortcut.activated.connect(self.AI)

        # call terminal - Ctrl+T
        terminal_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        terminal_shortcut.activated.connect(self.toggle_terminal)

        # Delete file - Delete key
        delete_shortcut = QShortcut(QKeySequence("Del"), self)
        delete_shortcut.activated.connect(self.delete_file)

    def show_find_replace_dialog(self):
        """Show the inline find bar (Ctrl+F)."""
        self.find_bar.show_find()
 
    def show_replace_dialog(self):
        """Show the inline find bar in replace mode (Ctrl+H)."""
        self.find_bar.show_replace()

    def undo_action(self):
        """Undo last action in current text editor"""
        current_tab = self.current_file_tabs.currentWidget()
        if isinstance(current_tab, QTextEdit):
            current_tab.undo()

    def redo_action(self):
        """Redo last undone action in current text editor"""
        current_tab = self.current_file_tabs.currentWidget()
        if isinstance(current_tab, QTextEdit):
            current_tab.redo()




    def save_current_file(self):
        """Save the currently active file, expanding tabs to 4 spaces if it's a .py file."""
        current_index = self.current_file_tabs.currentIndex()
        current_path = None

        for path, data in self.open_files.items():
            if data['tab_index'] == current_index:
                current_path = path
                break

        if current_path is None:
            QMessageBox.warning(self, 'Error', 'Cannot determine file path for current tab.')
            return

        # Always grab the bare editor from the dict, not currentWidget()
        # currentWidget() may return a MarkdownContainer, not the editor itself
        editor = self.open_files[current_path]['editor']

        try:
            content = editor.toPlainText()

            # Expand tabs → 4 spaces for Python files
            if current_path.endswith('.py'):
                process = subprocess.Popen(
                    ['expand', '-t', '4'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                content, stderr = process.communicate(input=content)
                if process.returncode != 0:
                    raise Exception(f"Expand command failed: {stderr}")

            with open(current_path, 'w', encoding='utf-8') as file:
                file.write(content)

            self.open_files[current_path]['modified'] = False
            self.update_tab_appearance(current_path)
            QMessageBox.information(self, 'Saved', f'File saved: {current_path}')

        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Failed to save file: {str(e)}')

    def save_all_files(self):
        """Save all open text files"""
        saved_count = 0
        for path, data in self.open_files.items():
            widget = data['editor']
            if isinstance(widget, QTextEdit):
                try:
                    with open(path, 'w', encoding='utf-8') as file:
                        file.write(widget.toPlainText())
                    saved_count += 1
                except Exception as e:
                    QMessageBox.warning(self, 'Error', f'Failed to save {path}: {str(e)}')
        
        if saved_count > 0:
            QMessageBox.information(self, 'Saved', f'Saved {saved_count} files successfully.')

        

    def create_new_folder(self):
        index = self.tree.currentIndex()
        if index.isValid():
            dir_path = self.model.filePath(index)
            if os.path.isfile(dir_path):
                dir_path = os.path.dirname(dir_path)
            folder_name, ok = QInputDialog.getText(self, 'New Folder', 'Enter folder name:')
            if ok and folder_name:
                os.mkdir(os.path.join(dir_path, folder_name))

    def create_new_file(self):
        toolbar_new_file(self)


    def handle_text_changed(self, path):
        """Handle text changes in the editor"""
        if path in self.open_files and not self.open_files[path]['modified']:
            self.open_files[path]['modified'] = True
            self.update_tab_appearance(path)

    def update_tab_appearance(self, path: str):
        if path not in self.open_files:
            return
        tab_index = self.open_files[path]['tab_index']
        file_name = os.path.basename(path)
        tab_bar   = self.current_file_tabs.tabBar()
 
        if self.open_files[path]['modified']:
            tab_bar.setTabText(tab_index, f"{self.modified_indicator}{file_name}")
            tab_bar.setTabTextColor(tab_index, QColor(self.modified_indicator_color))
        else:
            tab_bar.setTabText(tab_index, file_name)
            tab_bar.setTabTextColor(tab_index, QColor("#ffffff"))
 
        self.current_file_tabs.setStyleSheet("""
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 5px 8px;
                font-style: italic;
            }
            QTabBar::tab:selected { background-color: #3d3d3d; }
        """)

    def plugins(self):
        self.plugins_visible = not self.plugins_visible

        if self.plugins_visible:
            # SHOW plugins page
            self._hide_all_panels() 
            self.plugin_page.setVisible(True)

        else:
            # HIDE plugins page
            self.plugin_page.setVisible(False)

            if self.current_file_tabs.count() == 0:
                # No tabs → show landing
                self.landing_page.setVisible(True)
                self.current_file_tabs.setVisible(False)
            else:
                # Tabs exist → show tabs
                self.current_file_tabs.setVisible(True)
                self.landing_page.setVisible(False)
                self.plugin_page.setVisible(False)




    def toggle_terminal(self, commands=None):
        self.terminal_manager.toggle()

    def settings(self):
        self.settings_visible = not self.settings_visible

        if self.settings_visible:
            # SHOW settings page
            self._hide_all_panels() 
            self.settings_page.setVisible(True)

        else:
            # HIDE settings page
            self.settings_page.setVisible(False)

            if self.current_file_tabs.count() == 0:
                # No tabs → show landing
                self.landing_page.setVisible(True)
                self.current_file_tabs.setVisible(False)
            else:
                # Tabs exist → show tabs
                self.current_file_tabs.setVisible(True)
                self.landing_page.setVisible(False)
                self.settings_page.setVisible(False)
                self.gitHandler.setVisible(False)
                self.plugin_page.setVisible(False)
                self.themes_page.setVisible(False)
        

    def refresh_ui(self):
        """Force a refresh of the entire UI to apply new styles."""
        for widget in QApplication.instance().allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

        
    def update_window_title(self, new_name):
        self.setWindowTitle(f"Ikaris Dev Studio - 2024-V3 TM. WELCOME: {new_name}")
        
    def update_github_settings(self, username, token):
        pass
            
    def apply_theme(self, theme_name):
        pass

    def _hide_all_panels(self):
        """Hide every content panel. Call before showing any single panel."""
        for widget in [
            self.editor, self.current_file_tabs, self.image_label,
            self.landing_page, self.plugin_page, self.gitHandler,
            self.settings_page, self.themes_page, self.new_project_page,
            self.database_panel.database_view, self.debug_panel.debug_view
        ]:
            widget.setVisible(False)
            
    def show_recent_projects(self):
        """Show the landing page and tell it to highlight the recents section."""
        self._hide_all_panels()
        self.landing_page.setVisible(True)
        # Tell the JS to scroll recents into view and refresh the list
        self.landing_page.page().runJavaScript("loadRecents(); document.getElementById('recentGrid').scrollIntoView({behavior:'smooth'});")

    

    def start_project(self):
        self.new_project_visible = not getattr(self, 'new_project_visible', False)

        if self.new_project_visible:
            self._hide_all_panels() 
            self.new_project_page.setVisible(True)
        else:
            self.new_project_page.setVisible(False)

            if self.current_file_tabs.count() == 0:
                self.landing_page.setVisible(True)
                self.current_file_tabs.setVisible(False)
            else:
                self.current_file_tabs.setVisible(True)
                self.landing_page.setVisible(False)
        


    def github(self):
        self.github_visible = not self.github_visible

        if self.github_visible:
            # paint latest state
            self._hide_all_panels()
            self.bridge.git_refresh()            
            # SHOW github page
            self.gitHandler.setVisible(True)
        else:
            self.gitHandler.setVisible(False)

            if self.current_file_tabs.count() == 0:
                self.landing_page.setVisible(True)
                self.current_file_tabs.setVisible(False)
            else:
                self.current_file_tabs.setVisible(True)
                self.landing_page.setVisible(False)
           
        
           
    def show_themes_page(self):
        self._hide_all_panels()
        self.themes_page.setVisible(True)
    





    def open_file_searcher(self):
            # Create a file dialog for selecting a directory
        folder_path = QFileDialog.getExistingDirectory(
            None,               # Parent widget (None if no parent)
            "Select Folder",    # Dialog title
            str(Path.home()),                 # Starting directory (empty for default)
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        # Check if a directory was selected
        if folder_path:
            print("Selected folder:", folder_path)
            # You can add more functionality here, like returning the path
            self.update_directory(folder_path)
        else:
            print("No folder selected.")
            return None

    
    def update_directory(self, new_directory):
        
        path_string = str(new_directory)
        
        
        print(f"Updating directory to: {new_directory}")  # Debug print
        if os.path.isdir(path_string):
            self.tree.setRootIndex(self.model.index(path_string))
            self.base_directory = path_string
            self.update_directory_label()
            self.update_tree_view()
           
            print("Base directory: ", self.base_directory)  # Debug print
            if self.base_directory == str(Path.home()):
                pass
            else:
                QMessageBox.information(self, 'Directory Updated', f'Current directory changed to: {new_directory}')
                self.toggle_tree_view()
                # at the end of update_directory()
                self.terminal_manager.set_cwd(path_string)
                self.bridge.git_refresh()
                self.ai_panel.set_project_root(path_string)
                if hasattr(self, 'debug_panel'):
                    self.debug_panel.set_project_root(path_string)
                self.new_project_visible = False
                self.new_project_page.setVisible(False)
                self.recent_projects.record(path_string)
        else:
            print(f"Invalid directory: {new_directory}")  # Debug print
            QMessageBox.warning(self, 'Error', f'Invalid directory: {new_directory}')


    def AI(self):
        print("toggled ai button")
        print(f"current state: {self.Ai_visible}")
        self.Ai_visible = not self.Ai_visible
        
        self.ai_container.setVisible(self.Ai_visible)
        
        side_width   = 250 if self.active_panel is not None else 0
        ai_width     = 300 if self.Ai_visible else 0
        editor_width = max(0, 1200 - side_width - ai_width)

        show_tree  = (self.active_panel == "tree")
        show_db    = (self.active_panel == "db")
        show_debug = (self.active_panel == "debug")

        self.main_splitter.setSizes([
            side_width if show_tree  else 0,
            side_width if show_db    else 0,
            side_width if show_debug else 0,
            editor_width,
            ai_width,
        ])
        self.ai_panel.set_project_root(self.base_directory)
            
            
       
if __name__ == '__main__':
    sys.argv.append("--disable-web-security")
    app = QApplication(sys.argv)
    editor = CodeEditor()
    editor.show()
    sys.exit(app.exec_())
