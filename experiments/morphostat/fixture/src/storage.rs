use crate::domain;

pub fn persist(value: i32) -> i32 {
    domain::apply_delta(value, 0)
}
