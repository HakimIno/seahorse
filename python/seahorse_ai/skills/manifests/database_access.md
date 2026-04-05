```json
{
  "name": "Database_Access",
  "description": "Ability to query corporate databases and analyze schemas.",
  "tools": ["database_query", "database_schema"]
}
```

# Rules
- You MUST call `database_schema` before any query to verify table names.
- Never guess table names. Use the schema results to build accurate SQL.
- Always ensure data integrity and accuracy in your queries.
