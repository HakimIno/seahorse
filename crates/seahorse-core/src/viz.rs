//! Native charting engine powered by Charming (ECharts).
//! 
//! Generates premium, interactive business charts as JSON configurations
//! that can be rendered to images or web-components.

use charming::{
    component::{Axis, Legend, Title},
    element::{AxisType, Tooltip, Trigger},
    series::{Bar, Line},
    Chart,
};
use crate::error::CoreResult;

pub struct ChartGenerator;

impl ChartGenerator {
    pub fn new() -> Self {
        Self
    }

    /// Create a premium bar chart configuration.
    pub fn bar_chart(
        &self,
        title: &str,
        categories: Vec<String>,
        values: Vec<f64>,
    ) -> CoreResult<String> {
        let chart = Chart::new()
            .title(Title::new().text(title))
            .tooltip(Tooltip::new().trigger(Trigger::Axis))
            .legend(Legend::new().data(vec!["Value"]))
            .x_axis(Axis::new().type_(AxisType::Category).data(categories))
            .y_axis(Axis::new().type_(AxisType::Value))
            .series(Bar::new().name("Value").data(values));

        Ok(chart.to_string())
    }

    /// Create a premium line chart configuration.
    pub fn line_chart(
        &self,
        title: &str,
        categories: Vec<String>,
        values: Vec<f64>,
    ) -> CoreResult<String> {
        let chart = Chart::new()
            .title(Title::new().text(title))
            .tooltip(Tooltip::new().trigger(Trigger::Axis))
            .x_axis(Axis::new().type_(AxisType::Category).data(categories))
            .y_axis(Axis::new().type_(AxisType::Value))
            .series(Line::new().name("Trend").data(values).smooth(true));

        Ok(chart.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bar_chart_gen() {
        let gen = ChartGenerator::new();
        let cats = vec!["Jan".to_string(), "Feb".to_string()];
        let vals = vec![100.0, 200.0];
        let json = gen.bar_chart("Sales", cats, vals).unwrap();
        assert!(json.contains("Sales"));
        assert!(json.contains("Value"));
    }
}
