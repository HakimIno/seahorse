use pyo3::prelude::*;
use regex::Regex;
use unicode_normalization::UnicodeNormalization;
use std::collections::HashSet;

/// Aggressive text normalization (alphanumeric only)
#[pyfunction]
pub fn normalize_text(text: &str) -> String {
    let normalized = text.nfc().collect::<String>();
    let lowercase = normalized.to_lowercase();
    let re = Regex::new(r"[^a-z0-9]").unwrap();
    re.replace_all(&lowercase, "").to_string()
}

/// High-performance text deduplication for lists of dictionaries
#[pyfunction]
pub fn deduplicate_by_text(items: Vec<PyObject>, py: Python) -> Vec<PyObject> {
    let mut unique_items = Vec::new();
    let mut seen_texts = HashSet::new();

    for item in items {
        // Handle PyObject as a dictionary
        let text_res: PyResult<String> = item.bind(py).get_item("text").and_then(|t| t.extract());
        
        if let Ok(text) = text_res {
            let norm = normalize_text(&text);
            if !norm.is_empty() && !seen_texts.contains(&norm) {
                unique_items.push(item);
                seen_texts.insert(norm);
            }
        }
    }
    
    unique_items
}
