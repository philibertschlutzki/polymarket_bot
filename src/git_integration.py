import logging
from datetime import datetime

from git import GitCommandError, Repo

from src import database, error_logger

logger = logging.getLogger(__name__)


def push_dashboard_update():
    """Pushes dashboard updates to the remote Git repository.

    Checks if enough time has passed since the last push or if there are
    significant changes. Commits and pushes `PERFORMANCE_DASHBOARD.md` and
    `AI_DECISIONS.md` to the configured remote.

    Uses `git_sync_state` in the database to track pending changes and
    throttle push frequency.
    """
    try:
        # Prüfe ob Push nötig ist
        if not database.should_push_to_git():
            logger.info(
                "ℹ️  No pending changes or too soon since last push. Skipping Git sync."
            )
            return

        repo = Repo(".")
        files_to_add = []

        # Immer Dashboard hinzufügen wenn Änderungen vorhanden
        if os.path.exists("PERFORMANCE_DASHBOARD.md"):  # noqa: F821
            files_to_add.append("PERFORMANCE_DASHBOARD.md")

        # AI_DECISIONS.md nur bei relevanten Änderungen
        if database.has_ai_decisions_changes() and os.path.exists(  # noqa: F821
            "AI_DECISIONS.md"
        ):
            files_to_add.append("AI_DECISIONS.md")

        if not files_to_add:
            logger.info("ℹ️  No files to commit.")
            database.reset_git_sync_flags()
            return

        # Add Files
        repo.git.add(*files_to_add)

        # Check if there's actually something to commit
        if not repo.is_dirty() and not repo.index.diff("HEAD"):
            logger.info("ℹ️  No changes detected after add. Skipping commit.")
            database.reset_git_sync_flags()
            return

        # Commit mit beschreibender Message
        file_list = ", ".join(files_to_add)
        commit_message = f"🤖 Batch Update - {datetime.now().strftime('%Y-%m-%d %H:%M')} CET\n\nUpdated: {file_list}"
        repo.index.commit(commit_message)
        logger.info(f"✅ Committed: {file_list}")

        # Push
        origin = repo.remote(name="origin")
        push_info = origin.push()

        # Check push result
        if push_info and push_info[0].flags & 1024:  # ERROR flag
            raise GitCommandError(f"Push rejected: {push_info[0].summary}")

        logger.info("✅ Dashboard batch pushed to remote.")
        database.reset_git_sync_flags()

    except GitCommandError as e:
        error_logger.log_git_error(
            operation="push",
            error=e,
            context={"files": files_to_add if "files_to_add" in locals() else []},
        )
        logger.warning(f"⚠️  Git push failed: {e}")

    except Exception as e:
        error_logger.log_git_error(
            operation="commit_or_push", error=e, context={}
        )
        logger.warning(f"⚠️  Git integration error: {e}")
