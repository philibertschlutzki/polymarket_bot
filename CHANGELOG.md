# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Automatic resolution checker (`src/resolution_checker.py`) that queries Goldsky GraphQL API
- Resolves expired bets within 1 hour after end_date instead of waiting 30 days
- Batch processing for efficient API usage (50 markets per query)
- Comprehensive error handling with 3 retries for network issues
- Unit tests for resolution logic (`tests/test_resolution_checker.py`)

### Changed
- Updated `main_loop()` in `src/main.py` to include resolution check after archiving expired bets
- Dashboard now shows resolved outcomes immediately instead of "⏳ Pending Resolution"

### Fixed
- Resolved bets stuck in pending state for 30 days

## [2.1.0] - 2026-02-01

### Added
- **Architecture**: Introduced `src/` directory structure for better modularity.
- **Documentation**: Added `ARCHITECTURE.md`, `CONTRIBUTING.md`, `OPERATIONS.md`, `docs/`.
- **Database**: Explicit SQLite support as default. PostgreSQL is now optional.
- **Scripts**: `deploy_raspberry_pi.sh` now supports SQLite setup automatically.
- **CI**: Added GitHub Actions workflow for code quality checks.

### Fixed
- **Critical**: Issue #62 - Deployment failure due to PostgreSQL dependency on Raspberry Pi. Fixed by making Postgres optional and defaulting to SQLite.
- **Imports**: Fixed Python imports to support new directory structure.

### Changed
- Moved source files to `src/`.
- Moved scripts to `scripts/`.
- Moved tests to `tests/`.
- Updated `requirements.txt` to remove `psycopg2-binary` (moved to `requirements-postgres.txt`).

## [2.0.0] - 2025-01-15

### Added
- **AI**: Integration with Google Gemini 2.0 Flash with Search Grounding.
- **Trading**: Kelly Criterion for dynamic stake sizing.
- **Automation**: Auto-resolution via Goldsky Subgraph GraphQL.
- **Reporting**: Automated `PERFORMANCE_DASHBOARD.md` and `AI_DECISIONS.md` generation.
- **Git**: Auto-push of dashboards to GitHub.
