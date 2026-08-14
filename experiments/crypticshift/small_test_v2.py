#!/usr/bin/env python3

import small_test as base


def corrected_landscapes() -> list[base.Landscape]:
    rows = base.landscapes()
    corrected = []
    for row in rows:
        if row.name == "ownership_dispatch":
            corrected.append(
                base.Landscape(
                    "ownership_dispatch",
                    {
                        "A": (1, 3, 5, 3),
                        "B": (3, 4, 3, 1),
                        "C": (3, 1, 3, 4),
                        "D": (4, 3, 1, 3),
                    },
                    ("B", "C"),
                    True,
                )
            )
        elif row.name == "dual_boundary":
            corrected.append(
                base.Landscape(
                    "dual_boundary",
                    {
                        "A": (2, 5, 3, 3),
                        "B": (3, 2, 5, 3),
                        "C": (5, 3, 3, 1),
                        "D": (4, 3, 2, 4),
                    },
                    ("A", "C"),
                    True,
                )
            )
        elif row.name == "adversarial_compatibility":
            corrected.append(
                base.Landscape(
                    "adversarial_compatibility",
                    {
                        "A": (5, 3, 0, 5),
                        "B": (3, 3, 5, 0),
                        "C": (2, 4, 3, 3),
                        "D": (4, 2, 3, 3),
                    },
                    ("C", "D"),
                    False,
                )
            )
        else:
            corrected.append(row)
    return corrected


base.landscapes = corrected_landscapes

if __name__ == "__main__":
    raise SystemExit(base.main())
