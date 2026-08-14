//! Four tasks, one mutex, one barrier — a deadlock that is not a maybe.
//!
//! Each task takes the mutex and only then waits for the other three. The first
//! task to arrive holds the lock while the barrier waits for tasks that can
//! never get it. The program exits 3 on the timeout, so the failure is a fact
//! the test can read rather than a judgement about how the code looks.
//!
//! Moving the acquisition after the barrier is exactly the repair LockScope
//! makes, and it is the whole proof: same program, same timeout, completes.

use std::sync::Arc;
use tokio::sync::{Barrier, Mutex};
use tokio::time::{timeout, Duration};

async fn worker(state: Arc<Mutex<Vec<u8>>>, barrier: Arc<Barrier>) {
    let mut guard = state.lock().await;
    barrier.wait().await;
    guard.push(1);
}

#[tokio::main(flavor = "multi_thread", worker_threads = 4)]
async fn main() {
    let state = Arc::new(Mutex::new(Vec::new()));
    let barrier = Arc::new(Barrier::new(4));
    let mut handles = Vec::new();
    for _ in 0..4 {
        let state = Arc::clone(&state);
        let barrier = Arc::clone(&barrier);
        handles.push(tokio::spawn(worker(state, barrier)));
    }
    let joined = async move {
        for handle in handles {
            handle.await.unwrap();
        }
    };
    if timeout(Duration::from_millis(300), joined).await.is_err() {
        std::process::exit(3);
    }
    assert_eq!(state.lock().await.len(), 4);
}
