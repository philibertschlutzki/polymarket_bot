import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure src is in path
sys.path.append(os.getcwd())

# Import module to allow patching
try:
    import src.git_integration
except Exception as e:
    # If import fails (e.g. DB connection), we might need to mock before import
    print(f"Warning: import src.git_integration failed: {e}")

class TestGitIntegration(unittest.TestCase):

    @patch('src.git_integration.database')
    @patch('src.git_integration.Repo')
    @patch('src.git_integration.os.path.exists')
    def test_push_dashboard_update_success(self, mock_exists, mock_repo, mock_database):
        # Setup mocks
        mock_database.should_push_to_git.return_value = True
        mock_database.has_ai_decisions_changes.return_value = True

        # Mock file existence to True
        mock_exists.return_value = True

        # Mock Repo
        mock_repo_instance = MagicMock()
        mock_repo.return_value = mock_repo_instance
        # Make sure it thinks there are changes
        mock_repo_instance.is_dirty.return_value = True

        # Mock push info to avoid error
        mock_push_info = MagicMock()
        # Ensure flags & 1024 is False (0)
        mock_push_info.flags = 0
        mock_repo_instance.remote().push.return_value = [mock_push_info]

        # Execute
        try:
            src.git_integration.push_dashboard_update()
        except NameError as e:
            self.fail(f"NameError raised: {e}")
        except Exception as e:
            self.fail(f"Unexpected exception raised: {e}")

        # Verify interactions
        mock_exists.assert_any_call("PERFORMANCE_DASHBOARD.md")
        mock_repo_instance.git.add.assert_called()
        mock_repo_instance.index.commit.assert_called()
        mock_repo_instance.remote().push.assert_called()

if __name__ == '__main__':
    unittest.main()
