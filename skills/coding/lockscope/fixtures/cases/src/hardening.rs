//! Shapes that were not needed to pass the research evaluation.
//!
//! Everything here is valid Rust that a real codebase produces: comments inside
//! a method chain, guards taken in a match arm, two unrelated types with a field
//! of the same name. The analysis has to be right about all of it without the
//! fixture being bent to make the answer easy.

use std::hint::black_box;
use std::sync::{Arc, Mutex as StdGate};
use tokio::sync::{Mutex as AsyncGate, RwLock as AsyncRwGate};

pub mod deep {
    pub mod inner {
        pub type Guarded<T> = tokio::sync::Mutex<T>;
    }
}

use deep::inner::Guarded;
use tokio::sync::Mutex as RenamedElsewhere;

/// A comment sits between every step of the chain.
pub async fn comments_between_calls(state: &AsyncGate<Vec<u8>>) {
    let mut guard = state // receiver
        // then the method
        .lock()
        // and the suspension point
        .await;
    tokio::task::yield_now().await;
    guard.push(1);
}

/// The guard lives in the outer function while an inner async block awaits.
pub async fn nested_async_block(state: &AsyncGate<Vec<u8>>) {
    let mut guard = state.lock().await;
    let inner = async {
        tokio::task::yield_now().await;
        7_u8
    }
    .await;
    guard.push(inner);
}

/// The guard is taken inside a spawned `async move` closure body.
pub async fn async_move_closure(state: Arc<AsyncGate<Vec<u8>>>) {
    let handle = tokio::spawn(async move {
        let mut guard = state.lock().await;
        tokio::task::yield_now().await;
        guard.push(2);
    });
    handle.await.unwrap();
}

/// Two guards whose lifetimes overlap; both are live across the same await.
pub async fn overlapping_guards(first: &AsyncGate<Vec<u8>>, second: &AsyncGate<Vec<u8>>) {
    let mut a = first.lock().await;
    let mut b = second.lock().await;
    tokio::task::yield_now().await;
    a.push(1);
    b.push(2);
}

pub struct SameLockTwice {
    inner: AsyncGate<Vec<u8>>,
}

impl SameLockTwice {
    /// The same lock reached through two different expressions.
    pub async fn two_expressions(&self, alias: &AsyncGate<Vec<u8>>) {
        let first = self.inner.lock().await;
        let second = alias.lock().await;
        black_box((&*first, &*second));
    }
}

/// The type is an alias declared in a nested module.
pub async fn alias_through_module(state: &Guarded<Vec<u8>>) {
    let mut guard = state.lock().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

/// The type is imported under a different name.
pub async fn imported_rename(state: &RenamedElsewhere<Vec<u8>>) {
    let mut guard = state.lock().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

macro_rules! take_guard {
    ($state:expr, $guard:ident) => {
        let mut $guard = $state.lock().await;
    };
}

/// A macro wraps the acquisition, and the guard outlives an await.
pub async fn macro_wrapper(state: &AsyncGate<Vec<u8>>) {
    take_guard!(state, wrapped);
    tokio::task::yield_now().await;
    wrapped.push(1);
}

/// A second binding shadows the guard before the await.
pub async fn guard_shadowing(state: &AsyncGate<Vec<u8>>) -> usize {
    let guard = state.lock().await;
    let guard = guard.len();
    tokio::task::yield_now().await;
    black_box(guard)
}

/// The function returns early while the guard is still live.
pub async fn early_return(state: &AsyncGate<Vec<u8>>, bail: bool) -> usize {
    let guard = state.lock().await;
    if bail {
        return guard.len();
    }
    tokio::task::yield_now().await;
    black_box(guard.len())
}

/// Each arm takes its own guard; only one arm awaits while holding it.
pub async fn match_arms(state: &AsyncGate<Vec<u8>>, which: u8) -> usize {
    match which {
        0 => {
            let guard = state.lock().await;
            guard.len()
        }
        _ => {
            let guard = state.lock().await;
            tokio::task::yield_now().await;
            guard.len()
        }
    }
}

/// `if let` binds the guard for the length of its own block.
pub async fn if_let_scope(state: &AsyncGate<Option<u8>>) -> u8 {
    if let Some(value) = *state.lock().await {
        tokio::task::yield_now().await;
        return value;
    }
    0
}

/// `while let` takes the lock once per iteration.
pub async fn while_let_scope(state: &AsyncGate<Vec<u8>>) -> usize {
    let mut seen = 0_usize;
    while let Some(value) = state.lock().await.pop() {
        seen += value as usize;
        tokio::task::yield_now().await;
    }
    seen
}

/// `?` propagates out of the function while the guard is live.
pub async fn question_mark_near_scope(state: &StdGate<Vec<u8>>) -> Result<usize, std::io::Error> {
    let guard = state.lock().unwrap();
    let n = guard.len();
    let value: usize = "3"
        .parse()
        .map_err(|_| std::io::Error::other("not a number"))?;
    tokio::task::yield_now().await;
    Ok(black_box(n + value))
}

/// Three separate await points while one guard is live.
pub async fn multiple_await_points(state: &AsyncGate<Vec<u8>>) {
    let mut guard = state.lock().await;
    tokio::task::yield_now().await;
    tokio::task::yield_now().await;
    tokio::task::yield_now().await;
    guard.push(1);
}

pub struct ReadThenWrite {
    left: AsyncRwGate<Vec<u8>>,
    right: AsyncRwGate<Vec<u8>>,
}

impl ReadThenWrite {
    /// A read guard is held while a write guard is taken on another lock.
    pub async fn read_then_write(&self) {
        let reader = self.left.read().await;
        let mut writer = self.right.write().await;
        writer.push(reader.len() as u8);
    }
}

/// The acquisition happens in a helper; the async caller has none of its own.
pub async fn calls_helper(state: &AsyncGate<Vec<u8>>) -> usize {
    let n = helper(state).await;
    tokio::task::yield_now().await;
    black_box(n)
}

async fn helper(state: &AsyncGate<Vec<u8>>) -> usize {
    let guard = state.lock().await;
    tokio::task::yield_now().await;
    guard.len()
}

pub struct PretendLock;
pub struct PretendGuard(pub u8);

impl PretendLock {
    pub async fn read(&self) -> PretendGuard {
        PretendGuard(1)
    }
    pub async fn write(&self) -> PretendGuard {
        PretendGuard(2)
    }
}

/// An API that spells itself like a lock and is not one.
pub async fn fake_lock_api(fake: &PretendLock) {
    let reader = fake.read().await;
    let writer = fake.write().await;
    tokio::task::yield_now().await;
    black_box((reader.0, writer.0));
}

pub struct AccountState {
    balance: AsyncGate<u64>,
}

pub struct SessionState {
    balance: AsyncGate<u64>,
}

impl AccountState {
    /// Same field name as `SessionState::balance`, different lock entirely.
    pub async fn touch(&self, session: &SessionState) {
        let account = self.balance.lock().await;
        let sess = session.balance.lock().await;
        black_box((*account, *sess));
    }
}

impl SessionState {
    pub async fn touch(&self, account: &AccountState) {
        let sess = self.balance.lock().await;
        let acct = account.balance.lock().await;
        black_box((*sess, *acct));
    }
}
