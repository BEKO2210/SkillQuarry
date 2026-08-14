use std::marker::PhantomData;
use std::ptr::NonNull;
use std::rc::Rc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceError {
    AllocationRejected,
}

mod ffi {
    use std::sync::atomic::{AtomicUsize, Ordering};

    static ACTIVE: AtomicUsize = AtomicUsize::new(0);

    pub struct RawDevice {
        value: i32,
    }

    pub fn create(initial: i32) -> *mut RawDevice {
        if initial == i32::MIN {
            return std::ptr::null_mut();
        }
        ACTIVE.fetch_add(1, Ordering::SeqCst);
        Box::into_raw(Box::new(RawDevice { value: initial }))
    }

    pub unsafe fn read(ptr: *const RawDevice) -> i32 {
        // SAFETY: caller guarantees `ptr` points to a live RawDevice.
        unsafe { (*ptr).value }
    }

    pub unsafe fn write(ptr: *mut RawDevice, value: i32) {
        // SAFETY: caller guarantees exclusive access to a live RawDevice.
        unsafe {
            (*ptr).value = value;
        }
    }

    pub unsafe fn destroy(ptr: *mut RawDevice) {
        // SAFETY: caller guarantees `ptr` came from `create`, is still live,
        // and is destroyed exactly once.
        unsafe {
            drop(Box::from_raw(ptr));
        }
        ACTIVE.fetch_sub(1, Ordering::SeqCst);
    }

    #[cfg(test)]
    pub fn active_count() -> usize {
        ACTIVE.load(Ordering::SeqCst)
    }
}

/// Safe boundary around a private raw FFI-like handle.
///
/// `Device` intentionally does not implement `Send` or `Sync`: the simulated
/// foreign API has no cross-thread contract.
///
/// Double ownership is rejected by Rust's move semantics:
///
/// ```compile_fail
/// use rangate_eval::Device;
/// let device = Device::open(1).unwrap();
/// let moved = device;
/// drop(device);
/// drop(moved);
/// ```
///
/// Mutable aliasing is rejected before an unsafe operation is reached:
///
/// ```compile_fail
/// use rangate_eval::Device;
/// let mut device = Device::open(1).unwrap();
/// let first = &mut device;
/// let second = &mut device;
/// first.set(2);
/// second.set(3);
/// ```
///
/// Cross-thread transport is rejected because the external concurrency
/// contract is deliberately unknown:
///
/// ```compile_fail
/// use rangate_eval::Device;
/// let device = Device::open(1).unwrap();
/// std::thread::spawn(move || drop(device));
/// ```
pub struct Device {
    raw: NonNull<ffi::RawDevice>,
    _not_send_or_sync: PhantomData<Rc<()>>,
}

impl Device {
    pub fn open(initial: i32) -> Result<Self, DeviceError> {
        let raw = NonNull::new(ffi::create(initial)).ok_or(DeviceError::AllocationRejected)?;
        Ok(Self {
            raw,
            _not_send_or_sync: PhantomData,
        })
    }

    pub fn get(&self) -> i32 {
        // SAFETY: `open` accepts only a non-null handle returned by `ffi::create`.
        // The handle remains owned by `self` until Drop and shared access does
        // not mutate the foreign object.
        unsafe { ffi::read(self.raw.as_ptr()) }
    }

    pub fn set(&mut self, value: i32) {
        // SAFETY: `&mut self` gives exclusive Rust access to this unique owner,
        // and the raw handle remains live until Drop.
        unsafe { ffi::write(self.raw.as_ptr(), value) }
    }
}

impl Drop for Device {
    fn drop(&mut self) {
        // SAFETY: `Device` is the unique owner of the handle returned by
        // `ffi::create`; the type is not Clone and Drop runs once per owner.
        unsafe {
            ffi::destroy(self.raw.as_ptr());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::panic::{catch_unwind, AssertUnwindSafe};
    use std::sync::Mutex;

    static RESOURCE_TEST_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn beginner_safe_api_contains_raw_pointer_knowledge() {
        let _guard = RESOURCE_TEST_LOCK.lock().unwrap();
        let mut device = Device::open(41).unwrap();
        assert_eq!(device.get(), 41);
        device.set(42);
        assert_eq!(device.get(), 42);
    }

    #[test]
    fn null_like_foreign_failure_is_rejected_at_boundary() {
        let _guard = RESOURCE_TEST_LOCK.lock().unwrap();
        let before = ffi::active_count();
        let result = Device::open(i32::MIN);
        assert_eq!(result.err(), Some(DeviceError::AllocationRejected));
        assert_eq!(ffi::active_count(), before);
    }

    #[test]
    fn drop_releases_exactly_one_foreign_allocation() {
        let _guard = RESOURCE_TEST_LOCK.lock().unwrap();
        let before = ffi::active_count();
        {
            let device = Device::open(9).unwrap();
            assert_eq!(device.get(), 9);
            assert_eq!(ffi::active_count(), before + 1);
        }
        assert_eq!(ffi::active_count(), before);
    }

    #[test]
    fn panic_unwinding_still_runs_raii_cleanup() {
        let _guard = RESOURCE_TEST_LOCK.lock().unwrap();
        let before = ffi::active_count();
        let result = catch_unwind(AssertUnwindSafe(|| {
            let device = Device::open(77).unwrap();
            assert_eq!(ffi::active_count(), before + 1);
            assert_eq!(device.get(), 77);
            panic!("intentional pro-test panic");
        }));
        assert!(result.is_err());
        assert_eq!(ffi::active_count(), before);
    }

    #[test]
    fn repeated_create_mutate_drop_cycles_do_not_leak() {
        let _guard = RESOURCE_TEST_LOCK.lock().unwrap();
        let before = ffi::active_count();
        for value in 0..10_000 {
            let mut device = Device::open(value).unwrap();
            device.set(value + 1);
            assert_eq!(device.get(), value + 1);
        }
        assert_eq!(ffi::active_count(), before);
    }
}
