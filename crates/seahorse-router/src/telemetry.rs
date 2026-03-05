use opentelemetry::global;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::runtime;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

/// Initialise structured JSON logging + OpenTelemetry tracing.
///
/// - Logs go to stdout as JSON (consumed by any log aggregator).
/// - Traces go to the OTLP gRPC endpoint (default `http://localhost:4317`)
///   which Jaeger's all-in-one collector listens on.
///
/// Environment variables
/// ---------------------
/// OTEL_SERVICE_NAME              Service name in Jaeger (default: seahorse-router)
/// OTEL_EXPORTER_OTLP_ENDPOINT   gRPC endpoint (default: http://localhost:4317)
/// OTEL_DISABLE_TRACES            Set to "1" to skip OTLP export (e.g. CI)
/// RUST_LOG                       Log level filter (default: info)
pub fn init_telemetry() -> anyhow::Result<()> {
    let service_name = std::env::var("OTEL_SERVICE_NAME")
        .unwrap_or_else(|_| "seahorse-router".to_string());
    let otlp_endpoint = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .unwrap_or_else(|_| "http://localhost:4317".to_string());
    let disable_traces = std::env::var("OTEL_DISABLE_TRACES")
        .unwrap_or_default() == "1";

    let env_filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));

    if disable_traces {
        tracing_subscriber::fmt()
            .compact()
            .with_env_filter(env_filter)
            .with_target(true)
            .with_thread_ids(false)
            .with_level(true)
            .init();
        return Ok(());
    }

    // OTLP span exporter → Jaeger
    let exporter = opentelemetry_otlp::new_exporter()
        .tonic()
        .with_endpoint(&otlp_endpoint);

    let tracer = opentelemetry_otlp::new_pipeline()
        .tracing()
        .with_exporter(exporter)
        .with_trace_config(
            opentelemetry_sdk::trace::Config::default().with_resource(
                opentelemetry_sdk::Resource::new(vec![opentelemetry::KeyValue::new(
                    "service.name",
                    service_name.clone(),
                )]),
            ),
        )
        .install_batch(runtime::Tokio)?;

    // Bridge `tracing` spans → OTel spans
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    let console_log_layer = tracing_subscriber::fmt::layer()
        .compact()
        .with_target(true)
        .with_thread_ids(false)
        .with_level(true);

    tracing_subscriber::registry()
        .with(env_filter)
        .with(console_log_layer)
        .with(otel_layer)
        .init();

    tracing::info!(
        service = %service_name,
        endpoint = %otlp_endpoint,
        "OpenTelemetry tracing initialised",
    );
    Ok(())
}

/// Flush all pending spans and shutdown the global tracer provider.
/// Call this before process exit.
pub fn shutdown_telemetry() {
    global::shutdown_tracer_provider();
}
