use std::hint::black_box;
use std::sync::Arc;
use tokio::sync::{oneshot, Mutex, Notify, RwLock};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn tokio_guard_last_use_is_still_held_until_scope_exit() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let release = Arc::new(Notify::new());
    let (ready_tx, ready_rx) = oneshot::channel();

    let worker_state = Arc::clone(&state);
    let worker_release = Arc::clone(&release);
    let handle = tokio::spawn(async move {
        let guard = worker_state.lock().await;
        let n = guard.len();
        ready_tx.send(()).unwrap();
        worker_release.notified().await;
        black_box(n)
    });

    ready_rx.await.unwrap();
    assert!(
        state.try_lock().is_err(),
        "MutexGuard was unexpectedly released merely because its last textual use preceded await"
    );
    release.notify_one();
    assert_eq!(handle.await.unwrap(), 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn explicit_drop_releases_tokio_guard_before_await() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let release = Arc::new(Notify::new());
    let (ready_tx, ready_rx) = oneshot::channel();

    let worker_state = Arc::clone(&state);
    let worker_release = Arc::clone(&release);
    let handle = tokio::spawn(async move {
        let guard = worker_state.lock().await;
        let n = guard.len();
        drop(guard);
        ready_tx.send(()).unwrap();
        worker_release.notified().await;
        black_box(n)
    });

    ready_rx.await.unwrap();
    let guard = state
        .try_lock()
        .expect("explicit drop must release the Tokio mutex before await");
    drop(guard);
    release.notify_one();
    assert_eq!(handle.await.unwrap(), 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lexical_scope_releases_tokio_guard_before_await() {
    let state = Arc::new(Mutex::new(vec![1_u8]));
    let release = Arc::new(Notify::new());
    let (ready_tx, ready_rx) = oneshot::channel();

    let worker_state = Arc::clone(&state);
    let worker_release = Arc::clone(&release);
    let handle = tokio::spawn(async move {
        let n = {
            let guard = worker_state.lock().await;
            guard.len()
        };
        ready_tx.send(()).unwrap();
        worker_release.notified().await;
        black_box(n)
    });

    ready_rx.await.unwrap();
    let guard = state
        .try_lock()
        .expect("inner lexical scope must release Tokio mutex before await");
    drop(guard);
    release.notify_one();
    assert_eq!(handle.await.unwrap(), 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rwlock_reader_allows_reader_but_blocks_writer() {
    let state = Arc::new(RwLock::new(vec![1_u8]));
    let release = Arc::new(Notify::new());
    let (ready_tx, ready_rx) = oneshot::channel();

    let worker_state = Arc::clone(&state);
    let worker_release = Arc::clone(&release);
    let handle = tokio::spawn(async move {
        let guard = worker_state.read().await;
        ready_tx.send(()).unwrap();
        worker_release.notified().await;
        black_box(guard.len())
    });

    ready_rx.await.unwrap();
    let reader = state
        .try_read()
        .expect("an RwLock read guard must permit another reader");
    assert!(
        state.try_write().is_err(),
        "an RwLock read guard must block a concurrent writer"
    );
    drop(reader);
    release.notify_one();
    assert_eq!(handle.await.unwrap(), 1);
}
