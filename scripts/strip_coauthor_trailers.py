"""prepare-commit-msg helper: remove Co-authored-by lines so commits stay single-author."""
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    path = Path(sys.argv[1])
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    out = [L for L in lines if not L.strip().lower().startswith("co-authored-by:")]
    if out != lines:
        path.write_text("".join(out), encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
