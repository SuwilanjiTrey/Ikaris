class SQLToFirestoreTranslator:
    """
    Translates SQL-like queries to Firestore queries with a focus on NoSQL patterns.
    Simplified for Firestore's document-based structure.
    """
    
    def __init__(self):
        # SQL keywords to Firestore operations
        self.operators = {
            '=': '==',
            '==': '==',
            '>': '>',
            '<': '<',
            '>=': '>=',
            '<=': '<=',
            '!=': '!=',
            'LIKE': 'array_contains',  # Simplified for array fields
            'IN': 'in',
            'NOT IN': 'not_in',
        }
    
    def translate(self, query: str) -> dict:
        """
        Translate SQL query to Firestore query parameters.
        
        Returns:
            dict: {
                'collection': str,
                'operation': str,  # 'select', 'insert', 'update', 'delete', 'count'
                'fields': list,    # For SELECT (empty means all fields)
                'where_conditions': list,  # List of (field, operator, value) tuples
                'limit': int,
                'order_by': list,  # List of (field, direction) tuples
                'error': str       # If translation failed
            }
        """
        try:
            # Normalize query
            query = query.strip()
            if not query:
                return {'error': 'Empty query'}
            
            # Check if this is a Firestore native query (just collection name)
            if not query.upper().startswith(('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'COUNT')):
                # Assume this is a Firestore native query (collection path)
                return {
                    'collection': query.strip(),
                    'operation': 'select',
                    'fields': [],  # Empty means all fields
                    'where_conditions': [],
                    'limit': 100,
                    'order_by': []
                }
            
            # Parse SQL query
            return self._parse_sql_query(query)
            
        except Exception as e:
            return {'error': f'Query translation failed: {str(e)}'}
    
    def _parse_sql_query(self, query: str) -> dict:
        """Parse SQL query and convert to Firestore format."""
        import re
        
        # Convert to uppercase for parsing
        upper_query = query.upper()
        
        # Extract operation
        if upper_query.startswith('SELECT'):
            return self._parse_select(query)
        elif upper_query.startswith('COUNT'):
            return self._parse_count(query)
        elif upper_query.startswith('INSERT'):
            return self._parse_insert(query)
        elif upper_query.startswith('UPDATE'):
            return self._parse_update(query)
        elif upper_query.startswith('DELETE'):
            return self._parse_delete(query)
        else:
            return {'error': 'Unsupported SQL operation. Use SELECT, COUNT, INSERT, UPDATE, or DELETE.'}
    
    def _parse_select(self, query: str) -> dict:
        """Parse SELECT statement."""
        import re
        
        # Basic SELECT pattern: SELECT * FROM table [WHERE conditions] [LIMIT n] [ORDER BY field]
        pattern = r'SELECT\s+\*\s+FROM\s+(\w+)(?:\s+WHERE\s+(.*?))?(?:\s+LIMIT\s+(\d+))?(?:\s+ORDER\s+BY\s+(.*?))?$'
        match = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        
        if not match:
            # Try pattern with specific fields
            pattern = r'SELECT\s+(.*?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.*?))?(?:\s+LIMIT\s+(\d+))?(?:\s+ORDER\s+BY\s+(.*?))?$'
            match = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
            
            if not match:
                return {'error': 'Invalid SELECT syntax. Use: SELECT * FROM table [WHERE conditions] [LIMIT n] [ORDER BY field]'}
            
            fields_str, table, where_str, limit_str, order_str = match.groups()
            
            # Parse fields
            fields = [f.strip() for f in fields_str.split(',') if f.strip()]
        else:
            table, where_str, limit_str, order_str = match.groups()
            fields = []  # Empty means all fields
        
        # Parse WHERE conditions
        where_conditions = []
        if where_str:
            where_conditions = self._parse_where_clause(where_str)
            if isinstance(where_conditions, dict) and 'error' in where_conditions:
                return where_conditions
        
        # Parse LIMIT
        limit = int(limit_str) if limit_str else 100
        
        # Parse ORDER BY
        order_by = []
        if order_str:
            order_by = self._parse_order_by(order_str)
        
        return {
            'collection': table,
            'operation': 'select',
            'fields': fields,
            'where_conditions': where_conditions,
            'limit': limit,
            'order_by': order_by
        }
    
    def _parse_count(self, query: str) -> dict:
        """Parse COUNT statement."""
        import re
        
        # Basic COUNT pattern: COUNT(*) FROM table [WHERE conditions]
        pattern = r'COUNT\(\*\)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.*?))?$'
        match = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return {'error': 'Invalid COUNT syntax. Use: COUNT(*) FROM table [WHERE conditions]'}
        
        table, where_str = match.groups()
        
        # Parse WHERE conditions
        where_conditions = []
        if where_str:
            where_conditions = self._parse_where_clause(where_str)
            if isinstance(where_conditions, dict) and 'error' in where_conditions:
                return where_conditions
        
        return {
            'collection': table,
            'operation': 'count',
            'where_conditions': where_conditions
        }
    
    def _parse_where_clause(self, where_str: str) -> list:
        """Parse WHERE clause into conditions."""
        conditions = []
        
        # Split by AND (simplified - doesn't handle OR or parentheses)
        parts = [part.strip() for part in where_str.split('AND')]
        
        for part in parts:
            # Try to match condition: field operator value
            import re
            # Handle quoted strings
            pattern = r'(\w+)\s*(=|==|>|<|>=|<=|!=|LIKE|IN|NOT\s+IN)\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))'
            match = re.match(pattern, part, re.IGNORECASE)
            
            if match:
                field, operator, quoted_val, single_val, unquoted_val = match.groups()
                value = quoted_val or single_val or unquoted_val
                
                # Convert value to appropriate type
                if value.lower() in ('true', 'false'):
                    value = value.lower() == 'true'
                elif value.isdigit():
                    value = int(value)
                elif re.match(r'^\d+\.\d+$', value):
                    value = float(value)
                
                # Convert operator
                operator = operator.replace(' ', '')
                if operator in self.operators:
                    operator = self.operators[operator]
                
                conditions.append((field, operator, value))
            else:
                return {'error': f'Invalid WHERE condition: {part}'}
        
        return conditions
    
    def _parse_order_by(self, order_str: str) -> list:
        """Parse ORDER BY clause."""
        order_by = []
        parts = [part.strip() for part in order_str.split(',')]
        
        for part in parts:
            if ' ' in part:
                field, direction = part.rsplit(' ', 1)
                direction = direction.upper()
                if direction not in ('ASC', 'DESC'):
                    direction = 'ASC'
            else:
                field = part
                direction = 'ASC'
            
            order_by.append((field.strip(), direction))
        
        return order_by
    
    def _parse_insert(self, query: str) -> dict:
        """Parse INSERT statement."""
        import re
        
        # Basic INSERT pattern: INSERT INTO table (field1, field2) VALUES (value1, value2)
        pattern = r'INSERT\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)'
        match = re.match(pattern, query, re.IGNORECASE)
        
        if not match:
            return {'error': 'Invalid INSERT syntax. Use: INSERT INTO table (field1, field2) VALUES (value1, value2)'}
        
        table, fields_str, values_str = match.groups()
        fields = [f.strip() for f in fields_str.split(',')]
        values = []
        
        # Parse values (handle quoted strings)
        value_pattern = r'"([^"]*)"|\'([^\']*)\'|(\S+)'
        for val_match in re.finditer(value_pattern, values_str):
            quoted_val, single_val, unquoted_val = val_match.groups()
            value = quoted_val or single_val or unquoted_val
            
            # Convert to appropriate type
            if value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
            elif re.match(r'^\d+\.\d+$', value):
                value = float(value)
            
            values.append(value)
        
        if len(fields) != len(values):
            return {'error': 'Number of fields and values must match in INSERT statement'}
        
        return {
            'collection': table,
            'operation': 'insert',
            'fields': fields,
            'values': values
        }
    
    def _parse_update(self, query: str) -> dict:
        """Parse UPDATE statement."""
        import re
        
        # Basic UPDATE pattern: UPDATE table SET field1=value1, field2=value2 WHERE condition
        pattern = r'UPDATE\s+(\w+)\s+SET\s+(.*?)\s+WHERE\s+(.*)'
        match = re.match(pattern, query, re.IGNORECASE)
        
        if not match:
            return {'error': 'Invalid UPDATE syntax. Use: UPDATE table SET field1=value1, field2=value2 WHERE condition'}
        
        table, set_str, where_str = match.groups()
        
        # Parse SET clause
        set_conditions = {}
        for set_part in set_str.split(','):
            if '=' in set_part:
                field, value = set_part.split('=', 1)
                field = field.strip()
                value = value.strip()
                
                # Parse value (handle quoted strings)
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                elif value.lower() in ('true', 'false'):
                    value = value.lower() == 'true'
                elif value.isdigit():
                    value = int(value)
                elif re.match(r'^\d+\.\d+$', value):
                    value = float(value)
                
                set_conditions[field] = value
        
        # Parse WHERE clause
        where_conditions = self._parse_where_clause(where_str)
        if isinstance(where_conditions, dict) and 'error' in where_conditions:
            return where_conditions
        
        return {
            'collection': table,
            'operation': 'update',
            'set_conditions': set_conditions,
            'where_conditions': where_conditions
        }
    
    def _parse_delete(self, query: str) -> dict:
        """Parse DELETE statement."""
        import re
        
        # Basic DELETE pattern: DELETE FROM table WHERE condition
        pattern = r'DELETE\s+FROM\s+(\w+)\s+WHERE\s+(.*)'
        match = re.match(pattern, query, re.IGNORECASE)
        
        if not match:
            return {'error': 'Invalid DELETE syntax. Use: DELETE FROM table WHERE condition'}
        
        table, where_str = match.groups()
        
        # Parse WHERE clause
        where_conditions = self._parse_where_clause(where_str)
        if isinstance(where_conditions, dict) and 'error' in where_conditions:
            return where_conditions
        
        return {
            'collection': table,
            'operation': 'delete',
            'where_conditions': where_conditions
        }
