"""Reject utility/dynamic classes; allow the reviewed semantic CSS hooks.

The UI primarily uses inline styles and shared theme tokens. Named component
hooks support responsive rules, focus and disabled states in theme.css.
Adding a hook requires explicitly reviewing this allowlist; arbitrary classes
(including Tailwind utilities) and computed class names still fail the gate.
"""
import re
import sys
from pathlib import Path

ALLOWED_CLASSES = frozenset({
    "application-settings", "application-settings-content", "settings-card",
    "settings-help", "settings-advanced", "settings-field-grid",
    "settings-provider-fields", "settings-integration-status",
    "crm-workspace", "crm-surface", "crm-actions", "crm-disclosure",
    "crm-account-search", "crm-list-controls", "crm-board", "crm-board-column",
    "crm-deal-detail",
})
ASSIGNMENT = re.compile(r"\bclassName\s*=\s*")
LITERAL = re.compile(r'''(["'])(.*?)\1''', re.DOTALL)


def violations(source: str) -> list[tuple[int, str]]:
    """Return line/reason pairs for unreviewed or nonliteral class attributes."""
    errors = []
    for match in ASSIGNMENT.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        literal = LITERAL.match(source, match.end())
        if literal is None:
            errors.append((line, "className must be a reviewed static string"))
            continue
        unknown = set(literal.group(2).split()) - ALLOWED_CLASSES
        if unknown:
            errors.append((line, "unreviewed CSS classes: " + ", ".join(sorted(unknown))))
    return errors


def main() -> int:
    roots = [Path("frontend/src/components"), Path("frontend/src/pages")]
    errors = []
    for root in roots:
        if not root.is_dir():
            print(f"ERROR: missing frontend source directory: {root}")
            return 1
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".tsx", ".jsx"}:
                continue
            errors.extend(f"{path}:{line}: {reason}" for line, reason in violations(path.read_text()))
    if errors:
        print("\n".join(errors))
        return 1
    print("PASS: frontend CSS classes use reviewed semantic hooks only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
