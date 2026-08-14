use std::hint::black_box;
use std::sync::{Arc, Mutex as StdGate};
use tokio::sync::Mutex as AsyncGate;

pub async fn multiline_comment_live(state: &AsyncGate<Vec<u8>>) {
    let mut guard = state
        // legal formatting between receiver and method
        .lock()
        .await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn parenthesized_live(state: &AsyncGate<Vec<u8>>) {
    let mut guard = (state).lock().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn arc_clone_owned_live(state: Arc<AsyncGate<Vec<u8>>>) {
    let mut guard = Arc::clone(&state).lock_owned().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn nested_scope_quiet(state: &AsyncGate<Vec<u8>>) -> usize {
    let n = {
        let guard = state
            .lock()
            .await;
        guard.len()
    };
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn std_multiline_live(state: &StdGate<Vec<u8>>) {
    let mut guard = state
        .lock()
        .unwrap();
    tokio::task::yield_now().await;
    guard.push(1);
}
