#!/usr/bin/env python3

import pro_test

pro_test.RUST["domain/src/policy.rs"] = """use crate::value::DomainValue;

pub(crate) const POLICY_MARKER: i32 = 11;

pub fn apply_policy(value: DomainValue) -> DomainValue {
    let _ = POLICY_MARKER;
    DomainValue::new(value.get() + 1)
}
"""

pro_test.RUST["domain/src/audit.rs"] = """use crate::value::DomainValue;

pub(crate) const AUDIT_MARKER: i32 = 7;

pub fn audit_code(value: DomainValue) -> i32 {
    let _ = AUDIT_MARKER;
    value.get() & 1
}
"""

raise SystemExit(pro_test.main())
