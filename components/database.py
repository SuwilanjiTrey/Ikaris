"""
database.py  –  DatabasePanel (Refactored to use SQLAlchemy)
Manages connections to Firestore, SQL, MSSQL, SQLite, and ORM (SQLAlchemy).
The left sidebar (pure PyQt5) lists connections; the right area is a QWebEngineView
that renders the rich db_panel.html interface.
"""

import os
import json
from pathlib import Path
from urllib.parse import quote_plus

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QMenu, QAction,
    QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
    QMessageBox, QSplitter, QToolBar, QSizePolicy, QFileDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import Qt, QUrl, QSize, QObject, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QIcon, QColor, QFont
from utils.firestoreUtil import SQLToFirestoreTranslator



import datetime
from decimal import Decimal

class DatabaseJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        elif isinstance(obj, datetime.date):
            return obj.isoformat()
        elif isinstance(obj, datetime.time):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super().default(obj)


# ──────────────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────────────

DB_TYPES = ["SQLite", "SQL (PostgreSQL)", "SQL (MySQL)", "MSSQL", "Firestore", "ORM (SQLAlchemy)"]

# Maps db_type → icon path (fall back to a generic icon if image missing)
DB_ICONS = {
    "SQLite":            "images/dbIcons/sqlite.png",
    "SQL (PostgreSQL)":  "images/dbIcons/postgressql.webp",
    "SQL (MySQL)":       "images/dbIcons/mysql1.png",
    "MSSQL":             "images/dbIcons/mssql.png",
    "Firestore":         "images/dbIcons/firebase.png",
    "ORM (SQLAlchemy)":  "images/dbIcons/orm.png",
}

STATUS_COLORS = {
    "connected":    "#4CAF50",
    "disconnected": "#9E9E9E",
    "error":        "#F44336",
}

CONNECTIONS_FILE = str(Path.home() / ".ikaris_db_connections.json")


# ──────────────────────────────────────────────────────────────────────────────
#  SQLAlchemy Connection Manager
# ──────────────────────────────────────────────────────────────────────────────

class SQLAlchemyConnectionManager:
    """
    Unified connection manager using SQLAlchemy for all SQL databases.
    """
    
    def __init__(self):
        self.engines = {}  # conn_id -> engine
    
    def get_connection_string(self, conn: dict) -> str:
        """Generate SQLAlchemy connection string based on connection type."""
        db_type = conn.get("db_type", "")
        
        if db_type == "SQLite":
            path = conn.get("path", "")
            return f"sqlite:///{path}"
        
        elif db_type == "SQL (PostgreSQL)":
            host = conn.get("host", "localhost")
            port = conn.get("port", "5432")
            database = conn.get("database", "")
            username = conn.get("username", "")
            password = conn.get("password", "")
            return f"postgresql://{username}:{quote_plus(password)}@{host}:{port}/{database}"
        
        elif db_type == "SQL (MySQL)":
            host = conn.get("host", "localhost")
            port = conn.get("port", "3306")
            database = conn.get("database", "")
            username = conn.get("username", "")
            password = conn.get("password", "")
            return f"mysql+pymysql://{username}:{quote_plus(password)}@{host}:{port}/{database}"
        
        elif db_type == "MSSQL":
            host = conn.get("host", "localhost")
            port = conn.get("port", "1433")
            database = conn.get("database", "")
            username = conn.get("username", "")
            password = conn.get("password", "")
            return f"mssql+pyodbc://{username}:{quote_plus(password)}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
        
        elif db_type == "ORM (SQLAlchemy)":
            return conn.get("url", "")
        
        return ""
    
    def connect(self, conn_id: str, conn: dict) -> tuple[bool, str]:
        """Connect to database using SQLAlchemy and return (success, error_message)."""
        try:
            from sqlalchemy import create_engine, text
            
            connection_string = self.get_connection_string(conn)
            if not connection_string:
                return False, "Unsupported database type or missing connection parameters."
            
            # Create engine with echo=False for production
            engine = create_engine(connection_string, echo=False)
            
            # Test the connection
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            
            # Store engine for later use
            self.engines[conn_id] = engine
            return True, ""
            
        except ImportError as e:
            if "pymysql" in str(e):
                return False, "MySQL support requires pymysql. Install with: pip install pymysql"
            elif "psycopg2" in str(e):
                return False, "PostgreSQL support requires psycopg2. Install with: pip install psycopg2-binary"
            elif "pyodbc" in str(e):
                return False, "MSSQL support requires pyodbc. Install with: pip install pyodbc"
            else:
                return False, f"Missing required driver: {str(e)}"
        except Exception as e:
            return False, str(e)
    
    def disconnect(self, conn_id: str):
        """Disconnect from database."""
        if conn_id in self.engines:
            engine = self.engines[conn_id]
            engine.dispose()
            del self.engines[conn_id]
    
    def execute_query(self, conn_id: str, query: str) -> dict:
        """
        Execute a query (SQL-like or Firestore native) and return results.
        """
        if conn_id not in self.clients:
            return {"error": "Not connected to Firestore."}
        
        try:
            # Translate query
            translated = self.translator.translate(query)
            
            if 'error' in translated:
                return {"error": translated['error']}
            
            client = self.clients[conn_id]
            
            # Execute based on operation type
            if translated['operation'] == 'select':
                return self._execute_select(client, translated)
            elif translated['operation'] == 'count':
                return self._execute_count(client, translated)
            elif translated['operation'] == 'insert':
                return self._execute_insert(client, translated)
            elif translated['operation'] == 'update':
                return self._execute_update(client, translated)
            elif translated['operation'] == 'delete':
                return self._execute_delete(client, translated)
            else:
                return {"error": f"Unsupported operation: {translated['operation']}"}
                
        except Exception as e:
            return {"error": str(e)}
            
    def _execute_count(self, client, translated: dict) -> dict:
        """Execute COUNT query."""
        collection_ref = client.collection(translated['collection'])
        
        # Apply WHERE conditions
        for field, operator, value in translated['where_conditions']:
            collection_ref = collection_ref.where(field, operator, value)
        
        # Count documents ( Firestore doesn't have a direct count, so we need to fetch all)
        docs = collection_ref.stream()
        count = sum(1 for _ in docs)
        
        return {
            "columns": ["count"],
            "rows": [[count]],
            "rowcount": 1
        }
    
    def get_schema(self, conn_id: str) -> dict:
        """Get database schema (table names)."""
        if conn_id not in self.engines:
            return {"error": "Not connected to database."}
        
        try:
            from sqlalchemy import inspect
            
            engine = self.engines[conn_id]
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            return {"tables": tables}
            
        except Exception as e:
            return {"error": str(e)}




class FirestoreConnectionManager:
    """
    Connection manager for Firestore databases with SQL translation support.
    """
    
    def __init__(self):
        self.clients = {}  # conn_id -> firestore client
        self.translator = SQLToFirestoreTranslator()
    
    def connect(self, conn_id: str, conn: dict) -> tuple[bool, str]:
        """Connect to Firestore and return (success, error_message)."""
        try:
            # Try to import firebase_admin
            try:
                import firebase_admin
                from firebase_admin import credentials, firestore
            except ImportError:
                return False, "Firestore support requires firebase-admin. Install with: pip install firebase-admin"
            
            # Check if already initialized
            if not firebase_admin._apps:
                # Initialize with credentials
                cred_path = conn.get("credentials_path", "")
                if not cred_path or not os.path.exists(cred_path):
                    return False, "Service account JSON file not found or not specified."
                
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            
            # Create client
            client = firestore.client()
            self.clients[conn_id] = client
            return True, ""
            
        except Exception as e:
            return False, str(e)
    
    def disconnect(self, conn_id: str):
        """Disconnect from Firestore."""
        if conn_id in self.clients:
            del self.clients[conn_id]
    
    def get_collections(self, conn_id: str) -> dict:
        """Get all collections in the Firestore database."""
        if conn_id not in self.clients:
            return {"error": "Not connected to Firestore."}
        
        try:
            client = self.clients[conn_id]
            collections = [col.id for col in client.collections()]
            return {"collections": collections}
        except Exception as e:
            return {"error": str(e)}
    
    def execute_query(self, conn_id: str, query: str) -> dict:
        """
        Execute a query (SQL-like or Firestore native) and return results.
        """
        if conn_id not in self.clients:
            return {"error": "Not connected to Firestore."}
        
        try:
            # Translate query
            translated = self.translator.translate(query)
            
            if 'error' in translated:
                return {"error": translated['error']}
            
            client = self.clients[conn_id]
            
            # Execute based on operation type
            if translated['operation'] == 'select':
                return self._execute_select(client, translated)
            elif translated['operation'] == 'insert':
                return self._execute_insert(client, translated)
            elif translated['operation'] == 'update':
                return self._execute_update(client, translated)
            elif translated['operation'] == 'delete':
                return self._execute_delete(client, translated)
            else:
                return {"error": f"Unsupported operation: {translated['operation']}"}
                
        except Exception as e:
            return {"error": str(e)}
    
    def _execute_select(self, client, translated: dict) -> dict:
        """Execute SELECT query — supports document_id and subcollection paths."""
        from google.cloud.firestore import Query

        collection_name  = translated['collection']
        document_id      = translated.get('document_id')
        subcollection    = translated.get('subcollection')
        sub_document_id  = translated.get('sub_document_id')
        fields           = translated.get('fields', [])

        # ── Single document fetch ─────────────────────────────────────────────
        if document_id and not subcollection:
            doc_ref  = client.collection(collection_name).document(document_id)
            snapshot = doc_ref.get()
            if not snapshot.exists:
                return {"documents": []}
            doc_dict = snapshot.to_dict() or {}
            doc_dict['_id'] = snapshot.id
            if fields:
                doc_dict = {k: v for k, v in doc_dict.items() if k in fields or k == '_id'}
            return {"documents": [doc_dict]}

        # ── Sub-document fetch ────────────────────────────────────────────────
        if document_id and subcollection and sub_document_id:
            doc_ref  = (client.collection(collection_name)
                              .document(document_id)
                              .collection(subcollection)
                              .document(sub_document_id))
            snapshot = doc_ref.get()
            if not snapshot.exists:
                return {"documents": []}
            doc_dict = snapshot.to_dict() or {}
            doc_dict['_id'] = snapshot.id
            if fields:
                doc_dict = {k: v for k, v in doc_dict.items() if k in fields or k == '_id'}
            return {"documents": [doc_dict]}

        # ── Collection / sub-collection query ─────────────────────────────────
        if document_id and subcollection:
            collection_ref = (client.collection(collection_name)
                                    .document(document_id)
                                    .collection(subcollection))
        else:
            collection_ref = client.collection(collection_name)

        # WHERE
        for field, operator, value in translated.get('where_conditions', []):
            collection_ref = collection_ref.where(field, operator, value)

        # ORDER BY
        for field, direction in translated.get('order_by', []):
            fs_direction = Query.ASCENDING if direction.upper() == 'ASC' else Query.DESCENDING
            collection_ref = collection_ref.order_by(field, direction=fs_direction)

        # LIMIT
        limit = translated.get('limit', 100)
        if limit and limit > 0:
            collection_ref = collection_ref.limit(limit)

        documents = []
        for doc in collection_ref.stream():
            doc_dict = doc.to_dict() or {}
            doc_dict['_id'] = doc.id
            if fields:
                doc_dict = {k: v for k, v in doc_dict.items() if k in fields or k == '_id'}
            documents.append(doc_dict)

        return {"documents": documents}
    
    def _execute_insert(self, client, translated: dict) -> dict:
        """Execute INSERT query — supports single and multi-row inserts."""
        collection_ref = client.collection(translated['collection'])
        fields         = translated['fields']
        multi_insert   = translated.get('multi_insert', [])

        # Normalise to a list of rows
        if multi_insert:
            rows = multi_insert
        else:
            rows = [translated['values']]

        inserted_ids = []
        for row in rows:
            doc_data = {fields[i]: row[i] for i in range(len(fields))}
            doc_ref  = collection_ref.add(doc_data)
            inserted_ids.append(doc_ref[1].id)

        if len(inserted_ids) == 1:
            return {
                "success":     True,
                "message":     f"Document inserted with ID: {inserted_ids[0]}",
                "document_id": inserted_ids[0],
                "rowcount":    1,
            }
        return {
            "success":      True,
            "message":      f"{len(inserted_ids)} documents inserted.",
            "document_ids": inserted_ids,
            "rowcount":     len(inserted_ids),
        }
    
    def _execute_update(self, client, translated: dict) -> dict:
        """Execute UPDATE query."""
        collection_ref = client.collection(translated['collection'])
        
        # Apply WHERE conditions
        for field, operator, value in translated['where_conditions']:
            collection_ref = collection_ref.where(field, operator, value)
        
        # Get matching documents
        docs = collection_ref.stream()
        updated_count = 0
        
        for doc in docs:
            doc_ref = client.collection(translated['collection']).document(doc.id)
            doc_ref.update(translated['set_conditions'])
            updated_count += 1
        
        return {
            "success": True,
            "message": f"Updated {updated_count} documents",
            "rowcount": updated_count
        }
    
    def _execute_delete(self, client, translated: dict) -> dict:
        """Execute DELETE query."""
        collection_ref = client.collection(translated['collection'])
        
        # Apply WHERE conditions
        for field, operator, value in translated['where_conditions']:
            collection_ref = collection_ref.where(field, operator, value)
        
        # Get matching documents
        docs = collection_ref.stream()
        deleted_count = 0
        
        for doc in docs:
            doc_ref = client.collection(translated['collection']).document(doc.id)
            doc_ref.delete()
            deleted_count += 1
        
        return {
            "success": True,
            "message": f"Deleted {deleted_count} documents",
            "rowcount": deleted_count
        }


# ──────────────────────────────────────────────────────────────────────────────
#  Persistence helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_connections() -> list:
    if os.path.exists(CONNECTIONS_FILE):
        try:
            with open(CONNECTIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_connections(connections: list):
    try:
        with open(CONNECTIONS_FILE, "w") as f:
            json.dump(connections, f, indent=2)
    except Exception as e:
        print(f"[DB] Failed to save connections: {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  JS ↔ Python bridge
# ──────────────────────────────────────────────────────────────────────────────

class DBBridge(QObject):
    """Exposed to the WebEngineView so HTML can call Python methods."""

    connection_status_changed = pyqtSignal(str, str)   # conn_id, status

    def __init__(self, panel: "DatabasePanel"):
        super().__init__()
        self._panel = panel

    # Called by HTML toolbar buttons
    @pyqtSlot(str)
    def connect_db(self, conn_id: str):
        self._panel.connect_connection(conn_id)

    @pyqtSlot(str)
    def disconnect_db(self, conn_id: str):
        self._panel.disconnect_connection(conn_id)

    @pyqtSlot(str, str)
    def run_query(self, conn_id: str, query: str):
        self._panel.run_query(conn_id, query)

    @pyqtSlot(str)
    def export_db(self, conn_id: str):
        self._panel.export_connection(conn_id)

    @pyqtSlot(str)
    def delete_connection(self, conn_id: str):
        self._panel.delete_connection(conn_id)

    @pyqtSlot(str)
    def refresh_schema(self, conn_id: str):
        self._panel.refresh_schema(conn_id)

    @pyqtSlot()
    def add_connection(self):
        """Called from the home screen '+ New Connection' button."""
        self._panel._add_connection()


# ──────────────────────────────────────────────────────────────────────────────
#  Add / Edit connection dialog
# ──────────────────────────────────────────────────────────────────────────────

class ConnectionDialog(QDialog):
    """Dialog to add or edit a database connection."""

    def __init__(self, parent=None, existing: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Add Connection" if existing is None else "Edit Connection")
        self.setMinimumWidth(440)
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QLabel  { color: #cdd6f4; font-size: 13px; }
            QLineEdit, QComboBox {
                background: #313244; border: 1px solid #45475a;
                border-radius: 6px; padding: 6px 10px;
                color: #cdd6f4; font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus { border-color: #89b4fa; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #313244; color: #cdd6f4; }
            QDialogButtonBox QPushButton {
                background: #89b4fa; color: #1e1e2e;
                border-radius: 6px; padding: 6px 18px; font-weight: bold;
            }
            QDialogButtonBox QPushButton:hover { background: #b4befe; }
            QDialogButtonBox QPushButton[text="Cancel"] {
                background: #313244; color: #cdd6f4;
            }
        """)

        self._data = existing.copy() if existing else {}
        self._fields: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title label
        title = QLabel("Database Connection")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #89b4fa;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Name
        self.name_edit = QLineEdit(self._data.get("name", ""))
        self.name_edit.setPlaceholderText("My SQLite DB")
        form.addRow("Connection Name:", self.name_edit)

        # DB Type
        self.type_combo = QComboBox()
        self.type_combo.addItems(DB_TYPES)
        current_type = self._data.get("db_type", DB_TYPES[0])
        idx = self.type_combo.findText(current_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Database Type:", self.type_combo)

        layout.addLayout(form)

        # Dynamic fields container
        self.dynamic_form = QFormLayout()
        self.dynamic_form.setSpacing(10)
        self.dynamic_form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(self.dynamic_form)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed(current_type)

    def _clear_dynamic(self):
        while self.dynamic_form.rowCount():
            self.dynamic_form.removeRow(0)
        self._fields.clear()

    def _add_field(self, label: str, key: str, placeholder: str = "", password: bool = False):
        edit = QLineEdit(self._data.get(key, ""))
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.Password)
        self.dynamic_form.addRow(label + ":", edit)
        self._fields[key] = edit

    def _on_type_changed(self, db_type: str):
        self._clear_dynamic()
        if db_type == "SQLite":
            self._add_field("File Path", "path", "/path/to/database.db")
            # Browse button
            browse_btn = QPushButton("Browse…")
            browse_btn.setStyleSheet("background:#313244; color:#cdd6f4; border-radius:5px; padding:4px 10px;")
            browse_btn.clicked.connect(self._browse_sqlite)
            self.dynamic_form.addRow("", browse_btn)

        elif db_type == "Firestore":
            self._add_field("Project ID",          "project_id",      "my-firebase-project")
            self._add_field("Service Account JSON", "credentials_path", "/path/to/serviceAccount.json")

            # Row with Browse + ⓘ info button side-by-side
            cred_row = QHBoxLayout()
            cred_row.setSpacing(6)

            browse_btn = QPushButton("Browse…")
            browse_btn.setStyleSheet("background:#313244; color:#cdd6f4; border-radius:5px; padding:4px 10px;")
            browse_btn.clicked.connect(self._browse_json)
            cred_row.addWidget(browse_btn)

            info_btn = QPushButton("ⓘ")
            info_btn.setFixedSize(26, 26)
            info_btn.setToolTip(
                "<b>How to get a Service Account JSON</b><br/><br/>"
                "1. Go to <b>Firebase Console</b> → your project<br/>"
                "2. Click the ⚙ gear → <b>Project settings</b><br/>"
                "3. Open the <b>Service accounts</b> tab<br/>"
                "4. Click <b>Generate new private key</b> and save the JSON<br/><br/>"
                "This file grants admin access — keep it secret and never commit it to version control."
            )
            info_btn.setStyleSheet(
                "QPushButton { background:#1e3a5f; color:#89b4fa; border:1px solid #89b4fa;"
                "border-radius:5px; font-size:13px; font-weight:bold; padding:0; }"
                "QPushButton:hover { background:#89b4fa; color:#1e1e2e; }"
            )
            info_btn.clicked.connect(self._show_credentials_help)
            cred_row.addWidget(info_btn)
            cred_row.addStretch()

            self.dynamic_form.addRow("", cred_row)

        elif db_type == "ORM (SQLAlchemy)":
            self._add_field("Connection URL", "url", "sqlite:///path/to/db.db  or  postgresql://user:pass@host/db")

        else:  # SQL variants / MSSQL
            self._add_field("Host",     "host",     "localhost")
            self._add_field("Port",     "port",     "5432" if "Postgres" in db_type else ("3306" if "MySQL" in db_type else "1433"))
            self._add_field("Database", "database", "my_database")
            self._add_field("Username", "username", "admin")
            self._add_field("Password", "password", "", password=True)

    def _browse_sqlite(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select SQLite File", str(Path.home()), "SQLite Files (*.db *.sqlite *.sqlite3);;All Files (*)")
        if path and "path" in self._fields:
            self._fields["path"].setText(path)

    def _browse_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Service Account JSON", str(Path.home()), "JSON Files (*.json)")
        if path and "credentials_path" in self._fields:
            self._fields["credentials_path"].setText(path)

    def _show_credentials_help(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Service Account JSON — Help")
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            "<b>How to obtain a Firebase Service Account JSON</b><br/><br/>"
            "<ol>"
            "<li>Open the <a href='https://console.firebase.google.com/'>Firebase Console</a> "
            "and select your project.</li>"
            "<li>Click the ⚙ <b>gear icon</b> next to <i>Project Overview</i> → "
            "<b>Project settings</b>.</li>"
            "<li>Navigate to the <b>Service accounts</b> tab.</li>"
            "<li>Click <b>Generate new private key</b> and confirm.</li>"
            "<li>Save the downloaded <code>.json</code> file somewhere secure "
            "(e.g. outside your project repo).</li>"
            "</ol>"
            "<br/>"
            "<b style='color:#f38ba8;'>⚠ Security notice:</b> This file grants full admin "
            "access to your Firebase project. Never commit it to version control or share it publicly."
        )
        msg.setStyleSheet("""
            QMessageBox { background: #1e1e2e; color: #cdd6f4; }
            QLabel { color: #cdd6f4; font-size: 13px; }
            QPushButton { background: #89b4fa; color: #1e1e2e; border-radius: 6px;
                          padding: 5px 16px; font-weight: bold; }
            QPushButton:hover { background: #b4befe; }
        """)
        msg.exec_()

    def get_data(self) -> dict:
        data = {
            "name":    self.name_edit.text().strip(),
            "db_type": self.type_combo.currentText(),
        }
        for key, edit in self._fields.items():
            data[key] = edit.text().strip()
        return data


# ──────────────────────────────────────────────────────────────────────────────
#  Connection list item widget
# ──────────────────────────────────────────────────────────────────────────────

class ConnectionItemWidget(QWidget):
    """Custom row in the connections list."""

    def __init__(self, conn: dict, parent=None):
        super().__init__(parent)
        self.conn = conn
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # DB type icon
        icon_lbl = QLabel()
        icon_path = DB_ICONS.get(conn.get("db_type", ""), "")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            pixmap = icon.pixmap(QSize(22, 22))
            icon_lbl.setPixmap(pixmap)
        else:
            # Fallback text badge
            db_short = {
                "SQLite": "SQ", "SQL (PostgreSQL)": "PG",
                "SQL (MySQL)": "MY", "MSSQL": "MS",
                "Firestore": "FS", "ORM (SQLAlchemy)": "ORM",
            }.get(conn.get("db_type", ""), "DB")
            icon_lbl.setText(db_short)
            icon_lbl.setStyleSheet(
                "background:#89b4fa; color:#1e1e2e; border-radius:4px;"
                "font-size:9px; font-weight:bold; padding:2px 4px;"
            )
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        # Text block
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_lbl = QLabel(conn.get("name", "Unnamed"))
        name_lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #cdd6f4;")
        type_lbl = QLabel(conn.get("db_type", ""))
        type_lbl.setStyleSheet("font-size: 10px; color: #6c7086;")
        text_col.addWidget(name_lbl)
        text_col.addWidget(type_lbl)
        layout.addLayout(text_col)

        layout.addStretch()

        # Status dot
        status = conn.get("status", "disconnected")
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {STATUS_COLORS.get(status, '#9E9E9E')}; font-size: 12px;")
        dot.setToolTip(status.capitalize())
        layout.addWidget(dot)

        self.dot_label = dot  # keep ref for updates

    def set_status(self, status: str):
        self.conn["status"] = status
        self.dot_label.setStyleSheet(f"color: {STATUS_COLORS.get(status, '#9E9E9E')}; font-size: 12px;")
        self.dot_label.setToolTip(status.capitalize())


# ──────────────────────────────────────────────────────────────────────────────
#  Main DatabasePanel
# ──────────────────────────────────────────────────────────────────────────────

class DatabasePanel(QWidget):
    """
    The full DB side panel that lives inside db_container.
    Left: connection list + toolbar
    Right: QWebEngineView rendering db_panel.html
    """

    # Emitted when a .db / .sqlite / .sql file is opened from the tree view
    open_file_in_db = pyqtSignal(str)

    def __init__(self, db_layout: QVBoxLayout, main_window, channel=None):
        super().__init__()
        self._main = main_window
        self._connections: list[dict] = load_connections()
        self._active_conn_id: str | None = None
        self._item_widgets: dict[str, ConnectionItemWidget] = {}
        
        # Initialize SQLAlchemy connection manager
        self.db_manager = SQLAlchemyConnectionManager()
        self.firestore_manager = FirestoreConnectionManager()

        # ── Layout ────────────────────────────────────────────────────────────
        db_layout.addWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background:#181825; border-bottom:1px solid #313244;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 6, 0)
        h_lay.setSpacing(4)

        title_lbl = QLabel("Database")
        title_lbl.setStyleSheet("color:#cdd6f4; font-weight:bold; font-size:13px;")
        h_lay.addWidget(title_lbl)
        h_lay.addStretch()

        # Toolbar action buttons
        for tip, icon_fallback, slot in [
            ("Add Connection",    "+",   self._add_connection),
            ("Refresh All",       "↺",   self._refresh_all),
        ]:
            btn = QPushButton(icon_fallback)
            btn.setFixedSize(26, 26)
            btn.setToolTip(tip)
            btn.setStyleSheet("""
                QPushButton { background:#313244; color:#cdd6f4; border-radius:5px;
                              font-size:14px; font-weight:bold; border:none; }
                QPushButton:hover { background:#45475a; }
            """)
            btn.clicked.connect(slot)
            h_lay.addWidget(btn)

        root.addWidget(header)

        # Connection list
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: #1e1e2e;
                border: none;
                outline: none;
            }
            QListWidget::item { border-bottom: 1px solid #2a2a3e; padding: 0; }
            QListWidget::item:selected { background: #313244; }
            QListWidget::item:hover    { background: #26263a; }
        """)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setMinimumHeight(200)
        root.addWidget(self.list_widget)

        # Populate list
        self._rebuild_list()

        # Section label: Recent
        recent_lbl = QLabel("  RECENT")
        recent_lbl.setStyleSheet(
            "color:#6c7086; font-size:10px; font-weight:bold; letter-spacing:1px;"
            "padding: 6px 0 2px 0; background:#1e1e2e;"
        )
        root.addWidget(recent_lbl)

        # Recent connections (last 3 used)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(100)
        self.recent_list.setStyleSheet(self.list_widget.styleSheet())
        self.recent_list.itemClicked.connect(self._on_recent_clicked)
        root.addWidget(self.recent_list)
        self._rebuild_recent()

        
        #root.addWidget(self.web_view, 1)

        # ── Web view: self-contained channel + bridge ────────────────────────
        # DatabasePanel owns its own QWebChannel so it works standalone.
        # main_editor adds database_view to the editor layout then hides it.
        self._db_channel = QWebChannel()
        self._db_bridge  = DBBridge(self)
        self._db_channel.registerObject('DBBridge', self._db_bridge)

        self.database_view = QWebEngineView()
        self.database_view.page().setWebChannel(self._db_channel)

        html_path = os.path.abspath('web/db_panel.html')
        self.database_view.load(QUrl.fromLocalFile(html_path))
        

    # ──────────────────────────────────────────────────────────────────────────
    #  List building
    # ──────────────────────────────────────────────────────────────────────────

    def _rebuild_list(self):
        self.list_widget.clear()
        self._item_widgets.clear()
        for conn in self._connections:
            self._append_list_item(conn)

    def _append_list_item(self, conn: dict):
        item = QListWidgetItem(self.list_widget)
        w = ConnectionItemWidget(conn)
        item.setSizeHint(w.sizeHint())
        item.setData(Qt.UserRole, conn.get("id", ""))
        self.list_widget.setItemWidget(item, w)
        self._item_widgets[conn.get("id", "")] = w

    def _rebuild_recent(self):
        self.recent_list.clear()
        recents = [c for c in self._connections if c.get("last_used")]
        recents.sort(key=lambda c: c.get("last_used", ""), reverse=True)
        for conn in recents[:3]:
            item = QListWidgetItem(f"  {conn.get('name', '')}  [{conn.get('db_type','')}]")
            item.setData(Qt.UserRole, conn.get("id", ""))
            item.setForeground(QColor("#a6adc8"))
            self.recent_list.addItem(item)

    # ──────────────────────────────────────────────────────────────────────────
    #  Slots – toolbar
    # ──────────────────────────────────────────────────────────────────────────

    def _add_connection(self):
        dlg = ConnectionDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        data = dlg.get_data()
        if not data.get("name"):
            QMessageBox.warning(self, "Missing Name", "Please enter a connection name.")
            return

        import uuid, datetime
        data["id"] = str(uuid.uuid4())
        data["status"] = "disconnected"
        data["last_used"] = ""
        self._connections.append(data)
        save_connections(self._connections)
        self._append_list_item(data)
        self._rebuild_recent()

    def _refresh_all(self):
        self._rebuild_list()
        self._rebuild_recent()
        self._load_home_page()

    # ──────────────────────────────────────────────────────────────────────────
    #  Slots – list interaction
    # ──────────────────────────────────────────────────────────────────────────

    def _on_item_clicked(self, item: QListWidgetItem):
        conn_id = item.data(Qt.UserRole)
        self._open_connection_detail(conn_id)

    def _on_recent_clicked(self, item: QListWidgetItem):
        conn_id = item.data(Qt.UserRole)
        self._open_connection_detail(conn_id)

    def _open_connection_detail(self, conn_id: str):
        import datetime
        self._active_conn_id = conn_id
        conn = self._get_conn(conn_id)
        if conn:
            conn["last_used"] = datetime.datetime.now().isoformat()
            save_connections(self._connections)
            self._rebuild_recent()
            self._load_connection_page(conn)

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        conn_id = item.data(Qt.UserRole)
        conn = self._get_conn(conn_id)
        if not conn:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#1e1e2e; color:#cdd6f4; border:1px solid #313244; }
            QMenu::item:selected { background:#313244; }
        """)
        menu.addAction("✏  Edit",       lambda: self._edit_connection(conn_id))
        menu.addAction("🗑  Delete",     lambda: self.delete_connection(conn_id))
        menu.addSeparator()
        menu.addAction("⬆  Export DB",  lambda: self.export_connection(conn_id))
        menu.exec_(self.list_widget.viewport().mapToGlobal(pos))

    # ──────────────────────────────────────────────────────────────────────────
    #  Connection CRUD
    # ──────────────────────────────────────────────────────────────────────────

    def _edit_connection(self, conn_id: str):
        conn = self._get_conn(conn_id)
        if not conn:
            return
        dlg = ConnectionDialog(self, existing=conn)
        if dlg.exec_() != QDialog.Accepted:
            return
        new_data = dlg.get_data()
        conn.update(new_data)
        save_connections(self._connections)
        self._rebuild_list()

    def delete_connection(self, conn_id: str):
        conn = self._get_conn(conn_id)
        if not conn:
            return
        reply = QMessageBox.question(
            self, "Delete Connection",
            f"Delete '{conn.get('name', '')}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._connections = [c for c in self._connections if c["id"] != conn_id]
            save_connections(self._connections)
            self._rebuild_list()
            self._rebuild_recent()
            self._load_home_page()
            
            # Disconnect from database manager
            self.db_manager.disconnect(conn_id)

    # ──────────────────────────────────────────────────────────────────────────
    #  Connection actions (called from bridge or context menus)
    # ──────────────────────────────────────────────────────────────────────────

    def connect_connection(self, conn_id: str):
        """Attempt to connect using the appropriate manager."""
        conn = self._get_conn(conn_id)
        if not conn:
            return

        db_type = conn.get("db_type", "")
        
        # Initialize status and error_msg
        status = "error"
        error_msg = "Unknown error"
        
        if db_type == "Firestore":
            # Use Firestore connection manager
            success, error_msg = self.firestore_manager.connect(conn_id, conn)
            status = "connected" if success else "error"
        else:
            # Use SQLAlchemy connection manager for all SQL databases
            success, error_msg = self.db_manager.connect(conn_id, conn)
            status = "connected" if success else "error"

        conn["status"] = status
        save_connections(self._connections)

        # Update dot in sidebar
        w = self._item_widgets.get(conn_id)
        if w:
            w.set_status(status)

        # Tell the web view
        js_status = json.dumps({"id": conn_id, "status": status, "error": error_msg})
        self.database_view.page().runJavaScript(f"window.onConnectionStatus && window.onConnectionStatus({js_status});")

    def disconnect_connection(self, conn_id: str):
        conn = self._get_conn(conn_id)
        if conn:
            conn["status"] = "disconnected"
            save_connections(self._connections)
            w = self._item_widgets.get(conn_id)
            if w:
                w.set_status("disconnected")
            
            # Disconnect from the appropriate manager
            db_type = conn.get("db_type", "")
            if db_type == "Firestore":
                self.firestore_manager.disconnect(conn_id)
            else:
                self.db_manager.disconnect(conn_id)  # Changed from sql_manager to db_manager

    def run_query(self, conn_id: str, query: str):
        """Execute a query and push results to the web view."""
        conn = self._get_conn(conn_id)
        if not conn:
            return

        db_type = conn.get("db_type", "")
        
        if db_type == "Firestore":
            # Use the new execute_query method that handles both SQL and Firestore syntax
            results = self.firestore_manager.execute_query(conn_id, query)
        else:
            # Use SQLAlchemy connection manager for all SQL databases
            results = self.db_manager.execute_query(conn_id, query)
        
        # Handle Firestore documents
        if "documents" in results:
            # Convert Firestore documents to a table-like format
            if results["documents"]:
                # Get all unique keys from all documents
                all_keys = set()
                for doc in results["documents"]:
                    all_keys.update(doc.keys())
                
                # Convert to rows and columns
                columns = list(all_keys)
                rows = []
                for doc in results["documents"]:
                    row = []
                    for key in columns:
                        value = doc.get(key, None)
                        # Handle non-serializable values
                        if value is None:
                            row.append(None)
                        elif hasattr(value, '__dict__'):
                            row.append(str(value))
                        else:
                            row.append(value)
                    rows.append(row)
                
                results = {"columns": columns, "rows": rows, "rowcount": len(results["documents"])}
            else:
                results = {"columns": [], "rows": [], "rowcount": 0}
        elif "success" in results and results["success"]:
            # For INSERT, UPDATE, DELETE operations
            results = {
                "columns": ["message"],
                "rows": [[results["message"]]],
                "rowcount": results.get("rowcount", 1)
            }
        
        try:
            js_payload = json.dumps(results, cls=DatabaseJSONEncoder)
            self.database_view.page().runJavaScript(f"window.onQueryResults && window.onQueryResults({js_payload});")
        except (TypeError, ValueError) as e:
            error_msg = f"Error serializing query results: {str(e)}"
            error_payload = json.dumps({"error": error_msg})
            self.database_view.page().runJavaScript(f"window.onQueryResults && window.onQueryResults({error_payload});")

    def refresh_schema(self, conn_id: str):
        """Fetch table/collection names using SQLAlchemy and push to web view."""
        conn = self._get_conn(conn_id)
        if not conn:
            return

        db_type = conn.get("db_type", "")
        
        # Handle Firestore separately
        if db_type == "Firestore":
            # Get collections from Firestore
            schema = self.firestore_manager.get_collections(conn_id)
            # Convert collections format to tables format for UI
            if "collections" in schema:
                schema = {"tables": schema["collections"]}
        else:
            # Use SQLAlchemy connection manager for all SQL databases
            schema = self.db_manager.get_schema(conn_id)

        js_payload = json.dumps(schema)
        self.database_view.page().runJavaScript(f"window.onSchemaResults && window.onSchemaResults({js_payload});")

    def export_connection(self, conn_id: str):
        conn = self._get_conn(conn_id)
        if not conn:
            return
        db_type = conn.get("db_type", "")
        if db_type == "SQLite":
            src = conn.get("path", "")
            if not src or not os.path.exists(src):
                QMessageBox.warning(self, "Export", "SQLite file not found.")
                return
            dest, _ = QFileDialog.getSaveFileName(self, "Export SQLite DB", str(Path.home()), "SQLite (*.db *.sqlite)")
            if dest:
                import shutil
                shutil.copy2(src, dest)
                QMessageBox.information(self, "Export", f"Exported to {dest}")
        else:
            QMessageBox.information(self, "Export", f"Export for {db_type} coming soon.\nUse your DB tool to dump the schema.")

    # ──────────────────────────────────────────────────────────────────────────
    #  Web view page loading
    #�──────────────────────────────────────────────────────────────────────────

    def _load_home_page(self):
        self.database_view.page().runJavaScript("window.showHome && window.showHome();")

    def _load_connection_page(self, conn: dict):
        payload = json.dumps(conn)
        self.database_view.page().runJavaScript(f"window.showConnection && window.showConnection({payload});")

    # ──────────────────────────────────────────────────────────────────────────
    #  Open a .db/.sqlite/.sql file from the tree view
    # ──────────────────────────────────────────────────────────────────────────

    def open_db_file(self, file_path: str):
        """Called when user clicks a database file in the tree view."""
        ext = os.path.splitext(file_path)[1].lower()
        name = os.path.basename(file_path)

        # Check if already have a connection for this file
        existing = next((c for c in self._connections if c.get("path") == file_path), None)
        if existing:
            self._open_connection_detail(existing["id"])
            return

        # Auto-create a SQLite connection for .db/.sqlite files
        if ext in (".db", ".sqlite", ".sqlite3"):
            reply = QMessageBox.question(
                self, "Open Database",
                f"Add '{name}' as a new SQLite connection?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                import uuid, datetime
                conn = {
                    "id":       str(uuid.uuid4()),
                    "name":     name,
                    "db_type":  "SQLite",
                    "path":     file_path,
                    "status":   "disconnected",
                    "last_used": datetime.datetime.now().isoformat(),
                }
                self._connections.append(conn)
                save_connections(self._connections)
                self._append_list_item(conn)
                self._rebuild_recent()
                self._open_connection_detail(conn["id"])
        else:
            # .sql file – open in SQL editor mode
            try:
                with open(file_path, "r") as f:
                    sql_content = f.read()
                payload = json.dumps({"file": file_path, "content": sql_content})
                self.database_view.page().runJavaScript(f"window.openSQLFile && window.openSQLFile({payload});")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read file: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_conn(self, conn_id: str) -> dict | None:
        return next((c for c in self._connections if c["id"] == conn_id), None)
