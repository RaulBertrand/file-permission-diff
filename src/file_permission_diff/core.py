"""Core logic for comparing file modes and ownership between two directory trees."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiffEntry:
    """A single difference found between two directory trees.

    Fields:
        path: Path relative to the compared root (forward slashes).
        kind: Category of difference — 'mode', 'uid', 'gid', or
            'only_left' / 'only_right' when the file exists in only one tree.
        left:  Value from the left tree (mode as octal string, uid/gid as
            int, or None for 'only_right').
        right: Value from the right tree (mode as octal string, uid/gid as
            int, or None for 'only_left').
    """

    path: str
    kind: str
    left: object
    right: object

    def __str__(self) -> str:  # pragma: no cover — convenience only
        return f"{self.kind}: {self.path} ({self.left!r} -> {self.right!r})"


_PERMISSION_MASK = 0o7777


def _relativise(base: Path, path: Path) -> str:
    """Return ``path`` relative to ``base`` using POSIX separators.

    A stable key regardless of the platform's native separator is essential
    so that a tree compared on Windows can still match a tree compared on a
    Unix host. We deliberately raise if ``path`` is not under ``base`` rather
    than silently producing an absolute key — a silent fallback here would
    hide a bug in the walker.
    """
    rel = path.relative_to(base)
    return rel.as_posix()


def _stat_path(path: Path) -> os.stat_result:
    """``stat`` following symlinks (the default), without "lstat".

    Symbolic links themselves carry a trivial mode (0o777 on most systems and
    are not meaningfully comparable. We resolve them and compare the target,
    which is the mode that actually matters for permissions. A dangling link
    raises ``FileNotFoundError`` which the walker catches at the call site.
    """
    return path.stat()


def _scan_tree(root: Path) -> dict[str, tuple[int, int, int]]:
    """Walk ``root`` and return a mapping of relative path to (mode, uid, gid).

    We use ``os.walk(followlinks=False)`` so that symlinked directories don't
    cause infinite loops and we stay within the requested root. Entries that
    vanish during the walk or dangling symlinks are skipped: a file that
    disappears between the listing and the ``stat`` is inherently racing and
    is reported as 'missing' by the caller's comparison, not as a crash here.
    """
    results: dict[str, tuple[int, int, int]] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)

        # os.walk yields the root directory itself as '.' relative — we skip
        # the root to keep keys focused on the contents.
        for name in dirnames + filenames:
            entry = base / name
            try:
                st = _stat_path(entry)
            except OSError:
                continue
            key = _relativise(root, entry)
            results[key] = (st.st_mode & _PERMISSION_MASK, st.st_uid, st.st_gid)

    return results


def _format_mode(mode: int) -> str:
    """Render a mode integer as a 4-digit octal string.

    Leading zero preserved so that '0040' and '0000' sort and compare cleanly
    as strings, and so the setuid/setgid/sticky bits are visually explicit.
    """
    return format(mode, "04o")


def diff_directories(left: str | os.PathLike, right: str | os.PathLike) -> list[DiffEntry]:
    """Compare file modes and ownership of two directory trees.

    Args:
        left:  Path to the left/baseline directory tree.
        right: Path to the right/target directory tree.

    Returns:
        A list of :class:`DiffEntry` objects describing per-file differences,
        sorted lexicographically by ``path`` so output is deterministic.

    Notes:
        - Symlinks are resolved; a dangling symlink is treated as missing.
        - The comparison considers the permission bits (setuid/setgid/sticky
          plus rwxrwxrwx) and the numeric uid and gid. It deliberately does
          not consider file type, size, or modification time.
        - The root directories themselves are not compared — only their
          contents. This avoids noise when the roots have different absolute
          paths but identical internal structure.
    """
    left_path = Path(left)
    right_path = Path(right)

    if not left_path.is_dir():
        raise NotADirectoryError(f"left root is not a directory: {left_path}")
    if not right_path.is_dir():
        raise NotADirectoryError(f"right root is not a directory: {right_path}")

    left_map = _scan_tree(left_path)
    right_map = _scan_tree(right_path)

    entries: list[DiffEntry] = []
    all_keys = set(left_map) | set(right_map)

    for key in all_keys:
        left_stat = left_map.get(key)
        right_stat = right_map.get(key)

        if left_stat is None and right_stat is not None:
            entries.append(DiffEntry(key, "only_right", None, _format_mode(right_stat[0])))
            continue
        if right_stat is None and left_stat is not None:
            entries.append(DiffEntry(key, "only_left", _format_mode(left_stat[0]), None))
            continue
        if left_stat is None or right_stat is None:
            # Defensive — unreachable given the guards above, but keeps
            # mypy/pyright happy and prevents a silent crash if logic changes.
            continue

        l_mode, l_uid, l_gid = left_stat
        r_mode, r_uid, r_gid = right_stat

        if l_mode != r_mode:
            entries.append(DiffEntry(key, "mode", _format_mode(l_mode), _format_mode(r_mode)))
        if l_uid != r_uid:
            entries.append(DiffEntry(key, "uid", l_uid, r_uid))
        if l_gid != r_gid:
            entries.append(DiffEntry(key, "gid", l_gid, r_gid))

    entries.sort(key=lambda e: (e.path, e.kind))
    return entries
