# Contributing Guidelines

Thank you for your interest in contributing to the Polymarket AI Bot!

## Code Style
- **Python Version**: 3.10+
- **Style Guide**: PEP 8
- **Docstrings**: Google Style (mandatory for all new functions/classes).
- **Type Hinting**: Required for all function signatures.

## Repository Structure
- `src/`: Source code modules.
- `scripts/`: Deployment and maintenance scripts (bash).
- `tests/`: Unit tests.
- `database/`: SQLite database files (ignored by git except placeholders).
- `docs/`: Documentation.

## Workflow
1.  **Branching**: Work directly on `main` is discouraged but permitted for the sole developer. For contributors, please fork and create a PR.
2.  **Commits**: Use Conventional Commits.
    - `feat: ...` for new features.
    - `fix: ...` for bug fixes.
    - `docs: ...` for documentation.
    - `refactor: ...` for code restructuring.
3.  **Testing**: Run tests before submitting.
    ```bash
    pytest tests/
    ```

## Setting Up Development Environment
1.  Clone the repo.
2.  Create virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Configure `.env`:
    ```bash
    cp .env.example .env
    # Edit .env with your API keys
    ```
5.  Initialize DB (SQLite):
    ```bash
    python -c "from src import database; database.init_database()"
    ```

## Pull Request Process
1.  Update the README.md with details of changes to the interface, this includes new environment variables, exposed ports, useful file locations and container parameters.
2.  Increase the version numbers in any examples files and the README.md to the new version that this Pull Request would represent.
3.  You may merge the Pull Request in once you have the sign-off of other developers.
