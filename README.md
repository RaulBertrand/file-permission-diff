# file-permission-diff

Compares file modes (permission bits) and ownership (uid, gid) between two directory trees and reports the differences.

## Usage

```python
import os
import tempfile
from pathlib import Path

from file_permission_diff import diff_directories

# Create two directory trees with a small permission difference.
root = Path(tempfile.mkdtemp(prefix="fpd_"))
baseline = root / "baseline"
current = root / "current"
baseline.mkdir()
current.mkdir()
(baseline / "file.txt").write_text("x")
(current / "file.txt").write_text("x")
os.chmod(baseline / "file.txt", 0o644)
os.chmod(current / "file.txt", 0o600)

entries = diff_directories(baseline, current)
for e in entries:
    print(f"{e.kind}: {e.path} ({e.left!r} -> {e.right!r})")
```

Each `DiffEntry` has four fields: `path` (relative path with forward slashes), `kind` (one of `"mode"`, `"uid"`, `"gid"`, `"only_left"`, `"only_right"`), `left` (value from the left tree or `None`), and `right` (value from the right tree or `None`). Mode values are rendered as 4-digit octal strings (e.g. `"0644"`, `"4755"`); uid and gid are plain ints.

## Why this exists

When replicating a known-good filesystem tree onto a fresh host — a deployment target, a backup restore, a container image — it is easy to verify file *contents* with a checksum, but permission and ownership drift are silent and can cause real failures: a setuid binary that lost its bit, a world-readable secret that should be `0600`, a service file now owned by the wrong uid. This library exists to answer one question: "which files have different permissions or owners between these two trees?"

The trade-off: it compares *only* mode and ownership, deliberately ignoring file type, size, and mtime. If you need content comparison, pair it with something like `rsync --checksum` or a hashing pass. Keeping the scope small makes the output easy to read and easy to act on.

## Edge cases you will hit

- **Symlinks are resolved.** A symlink's own mode is not meaningful on most systems (it reads as `0777`), so this library follows the link and compares the target. A *dangling* symlink is treated as missing — it will show up as `only_left` or `only_right`, not crash the walk.
- **Root directories themselves are not compared.** Only their contents. This avoids noise when the two roots have different absolute paths but identical internal structure.
- **Ownership comparison requires root.** On POSIX, reading uid/gid is always possible, but if you are not root you will see your own process's view. The library does not attempt to resolve numeric uids to names — the numbers are what the filesystem stores and what matters for correctness.
- **Path separators are always `/`** in `DiffEntry.path`, regardless of platform, so trees compared on different operating systems still match.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

## Limitations

Values are coerced to floats, so very large integers lose precision. If you need
exact integer aggregates over a window, this is the wrong tool.

