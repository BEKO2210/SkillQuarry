use crate::{domain, storage};

pub fn process(value: i32) -> i32 {
    let adjusted = domain::apply_delta(value, 1);
    storage::persist(adjusted) * 2
}
