pub mod domain;
pub mod service;
pub mod storage;
pub mod ui;

#[cfg(test)]
mod tests {
    use super::{service, ui};

    #[test]
    fn service_behavior_is_stable() {
        assert_eq!(service::process(5), 12);
    }

    #[test]
    fn ui_behavior_is_stable() {
        assert_eq!(ui::render(5), "value=12");
    }
}
