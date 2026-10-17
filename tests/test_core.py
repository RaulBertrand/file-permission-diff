import os
import stat
import tempfile
import unittest
from pathlib import Path

from file_permission_diff import DiffEntry, diff_directories


class _TempTrees:
    """Context manager that creates two empty sibling directory trees."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="fpd_test_")
        self.left = Path(self.root) / "left"
        self.right = Path(self.root) / "right"
        self.left.mkdir()
        self.right.mkdir()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


def _write(path: Path, content: str = "x", mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, mode)


def _chown_if_possible(path: Path, uid: int, gid: int) -> bool:
    """Try to chown; return True if we can (running as root). False otherwise."""
    try:
        os.chown(path, uid, gid)
        return True
    except (PermissionError, OSError):
        return False


class TestDiffHappyPath(unittest.TestCase):

    def test_identical_trees_produce_no_diffs(self):
        with _TempTrees() as t:
            _write(t.left / "a.txt", "hello", 0o644)
            _write(t.right / "a.txt", "hello", 0o644)
            _write(t.left / "sub" / "b.txt", "y", 0o755)
            _write(t.right / "sub" / "b.txt", "y", 0o755)

            diffs = diff_directories(t.left, t.right)
            self.assertEqual(diffs, [])

    def test_mode_difference_detected(self):
        with _TempTrees() as t:
            _write(t.left / "file.txt", "x", 0o644)
            _write(t.right / "file.txt", "x", 0o600)

            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "mode")
            self.assertEqual(diffs[0].path, "file.txt")
            self.assertEqual(diffs[0].left, "0644")
            self.assertEqual(diffs[0].right, "0600")

    def test_multiple_differences_on_one_file_sorted_by_kind(self):
        # requires root; if we can't chown, skip — test what we actually support.
        with _TempTrees() as t:
            _write(t.left / "f", "x", 0o644)
            _write(t.right / "f", "x", 0o640)
            can_chown = _chown_if_possible(t.left / "f", 1001, 1001) and _chown_if_possible(t.right / "f", 1002, 1002)

            diffs = diff_directories(t.left, t.right)
            kinds = [d.kind for d in diffs if d.path == "f"]
            self.assertIn("mode", kinds)

            if can_chown:
                self.assertEqual(kinds, ["gid", "mode", "uid"])
            else:
                # Without root we can still verify mode diff was found.
                self.assertEqual(kinds, ["mode"])


class TestMissingFiles(unittest.TestCase):

    def test_file_only_on_left(self):
        with _TempTrees() as t:
            _write(t.left / "only_left.txt", "x", 0o644)
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "only_left")
            self.assertEqual(diffs[0].path, "only_left.txt")
            self.assertEqual(diffs[0].left, "0644")
            self.assertIsNone(diffs[0].right)

    def test_file_only_on_right(self):
        with _TempTrees() as t:
            _write(t.right / "only_right.txt", "x", 0o600)
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "only_right")
            self.assertEqual(diffs[0].path, "only_right.txt")
            self.assertIsNone(diffs[0].left)
            self.assertEqual(diffs[0].right, "0600")


class TestEdgeCases(unittest.TestCase):

    def test_subdirectory_paths_use_forward_slashes(self):
        with _TempTrees() as t:
            _write(t.left / "sub" / "deep" / "file.txt", "x", 0o644)
            _write(t.right / "sub" / "deep" / "file.txt", "x", 0o600)
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].path, "sub/deep/file.txt")

    def test_setuid_bit_difference_detected(self):
        with _TempTrees() as t:
            _write(t.left / "suid", "x", 0o4755)
            _write(t.right / "suid", "x", 0o0755)
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "mode")
            self.assertEqual(diffs[0].left, "4755")
            self.assertEqual(diffs[0].right, "0755")

    def test_sticky_bit_difference_detected(self):
        with _TempTrees() as t:
            os.makedirs(t.left / "dir", exist_ok=True)
            os.makedirs(t.right / "dir", exist_ok=True)
            os.chmod(t.left / "dir", 0o1777)
            os.chmod(t.right / "dir", 0o0777)
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].kind, "mode")
            self.assertEqual(diffs[0].left, "1777")
            self.assertEqual(diffs[0].right, "0777")

    def test_empty_directories_produce_no_diffs(self):
        with _TempTrees() as t:
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(diffs, [])

    def test_results_are_sorted_deterministically(self):
        with _TempTrees() as t:
            _write(t.left / "c.txt", "x", 0o644)
            _write(t.right / "c.txt", "x", 0o600)
            _write(t.left / "a.txt", "x", 0o644)
            _write(t.right / "a.txt", "x", 0o600)
            _write(t.left / "b.txt", "x", 0o644)
            _write(t.right / "b.txt", "x", 0o600)

            diffs = diff_directories(t.left, t.right)
            paths = [d.path for d in diffs]
            self.assertEqual(paths, ["a.txt", "b.txt", "c.txt"])

    def test_non_directory_left_root_raises(self):
        with _TempTrees() as t:
            not_a_dir = t.left / "file.txt"
            not_a_dir.write_text("x")
            with self.assertRaises(NotADirectoryError):
                diff_directories(not_a_dir, t.right)

    def test_non_directory_right_root_raises(self):
        with _TempTrees() as t:
            not_a_dir = t.right / "file.txt"
            not_a_dir.write_text("x")
            with self.assertRaises(NotADirectoryError):
                diff_directories(t.left, not_a_dir)

    def test_diff_entry_fields_match_documented_contract(self):
        with _TempTrees() as t:
            _write(t.left / "f", "x", 0o644)
            _write(t.right / "f", "x", 0o600)
            diffs = diff_directories(t.left, t.right)
            self.assertEqual(len(diffs), 1)
            d = diffs[0]
            self.assertIsInstance(d, DiffEntry)
            self.assertIsInstance(d.path, str)
            self.assertIsInstance(d.kind, str)
            self.assertIsInstance(d.left, str)
            self.assertIsInstance(d.right, str)


if __name__ == "__main__":
    unittest.main()
