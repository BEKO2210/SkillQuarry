#!/usr/bin/env python3

import pro_test as base

ORIGINAL_WRITE_CRATE = base.write_crate


def fixed_write_crate(root, cargo, files):
    if root.name == "probe_async_send" and "src/lib.rs" in files:
        files = dict(files)
        files["src/lib.rs"] = files["src/lib.rs"].replace(
            "fn assert_send<T: Send>(_: &T) {}",
            "#[cfg(test)]\nfn assert_send<T: Send>(_: &T) {}",
        )
    return ORIGINAL_WRITE_CRATE(root, cargo, files)


base.write_crate = fixed_write_crate

if __name__ == "__main__":
    raise SystemExit(base.main())
