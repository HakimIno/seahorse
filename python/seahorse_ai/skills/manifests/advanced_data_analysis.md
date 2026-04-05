```json
{
  "name": "Advanced_Data_Analysis",
  "description": "Professional data science, anomaly detection, high-performance visualization, and forecasting.",
  "tools": [
    "data_profile",
    "detect_numeric_anomalies",
    "detect_timeseries_anomalies",
    "polars_query",
    "native_echarts_chart",
    "echarts_composer",
    "create_custom_chart",
    "create_table_image",
    "forecast_sales"
  ]
}
```

# Rules
- **ANOMALIES**: ALWAYS use `detect_numeric_anomalies` and `detect_timeseries_anomalies` when the user asks about outliers, spikes, drops, fraud, or anomalies. Do NOT write manual Polars expressions for finding anomalies.
- Use `data_profile` first if you don't know the schema of the file.
- Use `native_echarts_chart` for quick Bar/Line charts.
- Use `echarts_composer` (ECharts) for ANY complex or premium visuals (Scatter, Heatmap, etc.).
- **ONCE SUCCESSFUL**: If you have the `ECHART_JSON:` path, you are DONE with visualization. Answer the user.
- **DEPRECATED**: Only use `create_custom_chart` (Matplotlib) if ECharts is impossible.
- Use `forecast_sales` when the user asks about future trends or predictions.
- Ensure charts use a modern color palette to look premium.
- Use `create_table_image` to present tabular data beautifully instead of simple Markdown.
