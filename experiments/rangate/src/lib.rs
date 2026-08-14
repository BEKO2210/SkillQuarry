use std::ptr::NonNull;

/// Baseline-style API: every caller must prove pointer validity.
///
/// # Safety
/// `ptr` must be non-null, aligned, and point to a live `i32` for the duration
/// of the call.
pub unsafe fn baseline_read(ptr: *const i32) -> i32 {
    // SAFETY: upheld by the caller under the function's unsafe contract.
    unsafe { *ptr }
}

/// RanGate-style boundary. Raw representation is accepted once and then kept
/// private behind a safe API.
pub struct IntHandle {
    raw: NonNull<i32>,
}

impl IntHandle {
    /// Takes ownership of a pointer created by `Box::into_raw`.
    ///
    /// # Safety
    /// `ptr` must either be null or come from `Box<i32>::into_raw`, and no
    /// other owner may free or mutably alias it after this call succeeds.
    pub unsafe fn from_raw_owned(ptr: *mut i32) -> Option<Self> {
        NonNull::new(ptr).map(|raw| Self { raw })
    }

    pub fn get(&self) -> i32 {
        // SAFETY: construction guarantees a live, owned `i32`; `self` keeps
        // the allocation alive and shared access cannot mutate it.
        unsafe { *self.raw.as_ptr() }
    }

    pub fn set(&mut self, value: i32) {
        // SAFETY: `&mut self` provides exclusive access to this owner and the
        // allocation remains live until Drop.
        unsafe { *self.raw.as_ptr() = value }
    }
}

impl Drop for IntHandle {
    fn drop(&mut self) {
        // SAFETY: `from_raw_owned` accepts only Box-owned pointers and this
        // type is the sole owner. Drop runs once for the owning value.
        unsafe {
            drop(Box::from_raw(self.raw.as_ptr()));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn beginner_safe_api_hides_raw_dereference() {
        let raw = Box::into_raw(Box::new(41));
        // SAFETY: `raw` was just produced by Box::into_raw and ownership is
        // transferred exactly once into IntHandle.
        let mut handle = unsafe { IntHandle::from_raw_owned(raw).unwrap() };
        assert_eq!(handle.get(), 41);
        handle.set(42);
        assert_eq!(handle.get(), 42);
    }

    #[test]
    fn null_pointer_is_rejected_at_boundary() {
        // SAFETY: null is explicitly accepted and rejected by this boundary.
        let result = unsafe { IntHandle::from_raw_owned(std::ptr::null_mut()) };
        assert!(result.is_none());
    }

    #[test]
    fn baseline_requires_unsafe_at_every_call_site() {
        let value = 7;
        // SAFETY: pointer is derived from a live local value for this call.
        let observed = unsafe { baseline_read(&value) };
        assert_eq!(observed, 7);
    }
}
