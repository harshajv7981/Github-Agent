import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_service import _cleanup_repo_cache


class RepoCacheCleanupTests(unittest.TestCase):
    def test_removes_both_cached_clone_layouts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            owner_name_clone = cache_root / "owner" / "repo"
            sandbox_clone = cache_root / "owner__repo"
            owner_name_clone.mkdir(parents=True)
            sandbox_clone.mkdir()

            with patch("app.agent_service.REPOS_CACHE_DIR", cache_root):
                _cleanup_repo_cache("owner/repo")

            self.assertFalse(owner_name_clone.exists())
            self.assertFalse(sandbox_clone.exists())

    def test_rejects_invalid_repo_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            outside = cache_root.parent / f"{cache_root.name}-sentinel"
            outside.mkdir()
            try:
                with patch("app.agent_service.REPOS_CACHE_DIR", cache_root):
                    _cleanup_repo_cache("../sentinel")
                self.assertTrue(outside.exists())
            finally:
                outside.rmdir()


if __name__ == "__main__":
    unittest.main()