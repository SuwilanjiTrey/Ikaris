
# Database Component Documentation

## Overview

The Database Component is a unified database management interface for IDEs that provides a consistent way to connect to, query, and manage multiple database types. It supports both SQL databases (SQLite, PostgreSQL, MySQL, MSSQL) and NoSQL databases (Firestore) through a unified interface.

## Architecture

The component is built with a modular architecture consisting of:

### Core Components

1. **DatabasePanel** - Main UI component that provides the interface for database connections and queries
2. **SQLAlchemyConnectionManager** - Handles all SQL database connections using SQLAlchemy
3. **FirestoreConnectionManager** - Manages Firestore connections with SQL-to-NoSQL query translation
4. **SQLToFirestoreTranslator** - Translates SQL-like queries to Firestore operations
5. **DatabaseJSONEncoder** - Custom JSON encoder for handling database-specific data types

### UI Components

- **Connection List** - Sidebar showing all configured database connections
- **Query Editor** - Interface for writing and executing queries
- **Results Viewer** - Table-based display of query results
- **Schema Explorer** - View of database tables/collections

## Supported Database Types

### SQL Databases
- SQLite
- PostgreSQL
- MySQL
- Microsoft SQL Server (MSSQL)

### NoSQL Databases
- Google Firestore (with SQL-like query translation)

## Setup and Installation

### Prerequisites

```bash
# Core SQLAlchemy
pip install sqlalchemy

# Database-specific drivers
pip install pymysql          # For MySQL
pip install psycopg2-binary  # For PostgreSQL
pip install pyodbc           # For MSSQL
pip install firebase-admin   # For Firestore
```

### Basic Usage

1. **Adding a Database Connection**
   - Click the "+" button in the database panel
   - Select the database type
   - Fill in connection details
   - Click "Connect" to establish the connection

2. **Executing Queries**
   - Select a connection from the sidebar
   - Write your query in the query editor
   - Click "Run Query" to execute
   - View results in the results panel

## Query Capabilities

### SQL Databases

All standard SQL operations are supported:

```sql
-- Basic SELECT
SELECT * FROM table_name LIMIT 100;

-- With conditions
SELECT * FROM users WHERE age > 25;

-- With joins
SELECT u.name, p.title FROM users u JOIN posts p ON u.id = p.user_id;

-- Aggregations
SELECT COUNT(*) FROM users;
SELECT department, AVG(salary) FROM employees GROUP BY department;
```

### Firestore

The Firestore interface supports both SQL-like queries and native Firestore syntax:

#### SQL-like Queries

```sql
-- View all documents (most common use case)
SELECT * FROM users;

-- Just provide the collection name (simpler)
users;

-- Filter documents
SELECT * FROM users WHERE age > 25;

-- Multiple conditions
SELECT * FROM users WHERE active = true AND age > 18;

-- With ordering
SELECT * FROM users ORDER BY name DESC;

-- With limit
SELECT * FROM users LIMIT 10;

-- Combined
SELECT * FROM users WHERE active = true ORDER BY created_at DESC LIMIT 20;

-- Count documents
COUNT(*) FROM users;

-- Insert a document
INSERT INTO users (name, email, age) VALUES ("John", "john@example.com", 30);

-- Update documents
UPDATE users SET age = 31 WHERE name = "John";

-- Delete documents
DELETE FROM users WHERE active = false;
```

#### Native Firestore Queries

```
-- Get all documents from a collection
users

-- Access subcollections
users/12345/orders
```

## API Reference

### DatabasePanel

#### Methods

- `connect_connection(conn_id)` - Connect to a database
- `disconnect_connection(conn_id)` - Disconnect from a database
- `run_query(conn_id, query)` - Execute a query
- `refresh_schema(conn_id)` - Refresh database schema
- `export_connection(conn_id)` - Export database data
- `delete_connection(conn_id)` - Delete a connection

### SQLAlchemyConnectionManager

#### Methods

- `connect(conn_id, conn)` - Connect to a SQL database
- `disconnect(conn_id)` - Disconnect from a SQL database
- `execute_query(conn_id, query)` - Execute a SQL query
- `get_schema(conn_id)` - Get database schema

### FirestoreConnectionManager

#### Methods

- `connect(conn_id, conn)` - Connect to Firestore
- `disconnect(conn_id)` - Disconnect from Firestore
- `execute_query(conn_id, query)` - Execute a Firestore query (SQL-like or native)
- `get_collections(conn_id)` - Get all collections in the database

### SQLToFirestoreTranslator

#### Methods

- `translate(query)` - Translate SQL-like query to Firestore operation

## Data Type Handling

The component automatically handles conversion between database-specific data types and JSON-serializable formats:

- **Datetime objects** → ISO format strings
- **Decimal objects** → Floats or strings
- **Bytes** → UTF-8 strings
- **Firestore documents** → Table-like format with columns and rows

## Configuration

### Connection Storage

Connection details are stored in `~/.ikaris_db_connections.json` in the following format:

```json
[
  {
    "id": "uuid",
    "name": "Connection Name",
    "db_type": "SQLite",
    "path": "/path/to/database.db",
    "status": "connected",
    "last_used": "2023-01-01T12:00:00"
  }
]
```

### Customization

The component can be customized by modifying:

- **DB_TYPES** - List of supported database types
- **DB_ICONS** - Icon paths for each database type
- **STATUS_COLORS** - Color codes for connection status

## Troubleshooting

### Common Issues

1. **"Missing required driver" errors**
   - Install the appropriate database driver (see Prerequisites)

2. **"Object of type X is not JSON serializable" errors**
   - The component automatically handles most data types
   - For custom types, extend the `DatabaseJSONEncoder` class

3. **Firestore connection issues**
   - Ensure the service account JSON file is valid
   - Check that the Firebase project has the correct permissions

4. **Query syntax errors**
   - SQL databases: Check standard SQL syntax
   - Firestore: Use the simplified SQL-like syntax or native collection names

## Examples

### Example 1: Connecting to a SQLite Database

```python
# Add connection through UI or programmatically
conn = {
    "id": "sqlite-1",
    "name": "App Database",
    "db_type": "SQLite",
    "path": "/path/to/app.db"
}

# Connect
database_panel.connect_connection("sqlite-1")

# Execute query
database_panel.run_query("sqlite-1", "SELECT * FROM users LIMIT 10")
```

### Example 2: Querying Firestore

```python
# Add connection through UI or programmatically
conn = {
    "id": "firestore-1",
    "name": "App Firestore",
    "db_type": "Firestore",
    "project_id": "my-project",
    "credentials_path": "/path/to/serviceAccount.json"
}

# Connect
database_panel.connect_connection("firestore-1")

# Execute query (SQL-like)
database_panel.run_query("firestore-1", "SELECT * FROM users WHERE active = true")

# Or native Firestore syntax
database_panel.run_query("firestore-1", "users")
```

## Future Enhancements

Potential improvements for future versions:

1. **Query Builder** - Visual query construction interface
2. **Data Import/Export** - Enhanced data transfer capabilities
3. **Query History** - Track and reuse previous queries
4. **Schema Visualization** - Visual representation of database structure
5. **Query Performance Analysis** - Tools for optimizing query performance

## Contributing

To contribute to the database component:

1. Fork the repository
2. Create a feature branch
3. Implement your changes with appropriate tests
4. Submit a pull request with a clear description of your changes

## License

This component is licensed under the MIT License.