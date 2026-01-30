import os
import logging
from datetime import datetime
from git import Repo, GitCommandError

logger = logging.getLogger(__name__)

def push_dashboard_update():
    """Commits and pushes the dashboard update to the remote repository."""
    try:
        repo = Repo('.')

        # Check if there are changes to the dashboard file
        # We specifically check PERFORMANCE_DASHBOARD.md
        if 'PERFORMANCE_DASHBOARD.md' not in repo.untracked_files:
             changed_files = [item.a_path for item in repo.index.diff(None)]
             if 'PERFORMANCE_DASHBOARD.md' not in changed_files and not repo.is_dirty(path='PERFORMANCE_DASHBOARD.md'):
                 # It might be that the file is not tracked yet, so we should try to add it anyway?
                 # git add will add it if it is modified or untracked.
                 pass

        # Add dashboard file
        repo.git.add('PERFORMANCE_DASHBOARD.md')

        # Check status after add to see if there is anything to commit
        if not repo.is_dirty() and not repo.index.diff("HEAD"):
             logger.info("No changes to push.")
             return

        # Commit
        commit_message = f"🤖 Dashboard Update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        repo.index.commit(commit_message)
        logger.info(f"Committed dashboard update: {commit_message}")

        # Push
        origin = repo.remote(name='origin')
        origin.push()
        logger.info("✅ Dashboard pushed to remote.")

    except GitCommandError as e:
        logger.warning(f"⚠️  Git push failed: {e}")
    except Exception as e:
        logger.warning(f"⚠️  Git integration error: {e}")
