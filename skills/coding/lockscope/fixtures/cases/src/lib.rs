#![allow(dead_code)]

pub mod hardening;
pub mod v2_cases;

use parking_lot::Mutex as ParkingGate;
use std::hint::black_box;
use std::sync::{Arc, Mutex as StdGate};
use tokio::sync::{Mutex as AsyncGate, RwLock as AsyncRwGate};

type AsyncAlias<T> = AsyncGate<T>;

pub async fn tokio_exclusive_live(state: &AsyncGate<Vec<u8>>) {
    let mut guard = state.lock().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn tokio_alias_live(state: &AsyncAlias<Vec<u8>>) {
    let mut guard = state.lock().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn tokio_owned_live(state: Arc<AsyncGate<Vec<u8>>>) {
    let mut guard = state.clone().lock_owned().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn tokio_last_use_only(state: &AsyncGate<Vec<u8>>) -> usize {
    let guard = state.lock().await;
    let n = guard.len();
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn tokio_explicit_drop(state: &AsyncGate<Vec<u8>>) -> usize {
    let guard = state.lock().await;
    let n = guard.len();
    drop(guard);
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn tokio_scope(state: &AsyncGate<Vec<u8>>) -> usize {
    let n = {
        let guard = state.lock().await;
        guard.len()
    };
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn rw_read_live(state: &AsyncRwGate<Vec<u8>>) -> usize {
    let guard = state.read().await;
    tokio::task::yield_now().await;
    black_box(guard.len())
}

pub async fn rw_write_live(state: &AsyncRwGate<Vec<u8>>) {
    let mut guard = state.write().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn std_live(state: &StdGate<Vec<u8>>) {
    let mut guard = state.lock().unwrap();
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn std_last_use(state: &StdGate<Vec<u8>>) -> usize {
    let guard = state.lock().unwrap();
    let n = guard.len();
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn std_explicit_drop(state: &StdGate<Vec<u8>>) -> usize {
    let guard = state.lock().unwrap();
    let n = guard.len();
    drop(guard);
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn std_scope(state: &StdGate<Vec<u8>>) -> usize {
    let n = {
        let guard = state.lock().unwrap();
        guard.len()
    };
    tokio::task::yield_now().await;
    black_box(n)
}

pub async fn parking_live(state: &ParkingGate<Vec<u8>>) {
    let mut guard = state.lock();
    tokio::task::yield_now().await;
    guard.push(1);
}

pub async fn multiline_live(state: &AsyncGate<Vec<u8>>) {
    let mut guard = state
        .lock()
        .await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub struct FakeMutex;
pub struct FakeGuard;

impl FakeMutex {
    pub async fn lock(&self) -> FakeGuard {
        FakeGuard
    }
}

pub async fn fake_lock_method(fake: &FakeMutex) {
    let guard = fake.lock().await;
    tokio::task::yield_now().await;
    black_box(guard);
}

pub struct TwoCycle {
    a2: AsyncGate<()>,
    b2: AsyncGate<()>,
}

impl TwoCycle {
    pub async fn ab(&self) {
        let ga = self.a2.lock().await;
        let gb = self.b2.lock().await;
        black_box((&*ga, &*gb));
    }

    pub async fn ba(&self) {
        let gb = self.b2.lock().await;
        let ga = self.a2.lock().await;
        black_box((&*ga, &*gb));
    }
}

pub struct ThreeCycle {
    a3: AsyncGate<()>,
    b3: AsyncGate<()>,
    c3: AsyncGate<()>,
}

impl ThreeCycle {
    pub async fn ab3(&self) {
        let ga = self.a3.lock().await;
        let gb = self.b3.lock().await;
        black_box((&*ga, &*gb));
    }

    pub async fn bc3(&self) {
        let gb = self.b3.lock().await;
        let gc = self.c3.lock().await;
        black_box((&*gb, &*gc));
    }

    pub async fn ca3(&self) {
        let gc = self.c3.lock().await;
        let ga = self.a3.lock().await;
        black_box((&*ga, &*gc));
    }
}

pub struct SelfCycle {
    self_lock: AsyncGate<()>,
}

impl SelfCycle {
    pub async fn same_lock_twice(&self) {
        let ga = self.self_lock.lock().await;
        let ga2 = self.self_lock.lock().await;
        black_box((&*ga, &*ga2));
    }
}

pub struct ConsistentOrder {
    left: AsyncGate<()>,
    right: AsyncGate<()>,
}

impl ConsistentOrder {
    pub async fn ab_one(&self) {
        let ga = self.left.lock().await;
        let gb = self.right.lock().await;
        black_box((&*ga, &*gb));
    }

    pub async fn ab_two(&self) {
        let ga = self.left.lock().await;
        let gb = self.right.lock().await;
        black_box((&*ga, &*gb));
    }
}

macro_rules! hold_tokio {
    ($state:expr, $guard:ident) => {
        let mut $guard = $state.lock().await;
    };
}

pub async fn macro_generated_live(state: &AsyncGate<Vec<u8>>) {
    hold_tokio!(state, guard);
    tokio::task::yield_now().await;
    guard.push(1);
}
