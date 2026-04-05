```json
{
  "name": "Data_Analysis",
  "description": "Core data processing and memory retrieval.",
  "tools": ["polars_query", "native_polars_aggregate", "memory_search"]
}
```

# Rules
- Prioritize `polars_query` for data transformation; it is faster than Python lists.
- Use `native_polars_aggregate` for large datasets to leverage Rust performance.
- ALWAYS check memory via `memory_search` if the user refers to past discussions.
