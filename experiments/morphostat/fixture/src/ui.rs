use crate::service;

pub fn render(value: i32) -> String {
    format!("value={}", service::process(value))
}

pub fn label(value: i32) -> String {
    format!("label:{value}")
}
