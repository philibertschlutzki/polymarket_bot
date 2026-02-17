# Contributing to Polymarket AI Trader

Thank you for your interest in contributing to the **Polymarket AI Trader** project!
We are currently in **V2 (Beta)**, focusing on stability, memory efficiency, and robust testing.

## 🏗 Architecture & Philosophy

Before you start coding, please understand our core principles:

1.  **Low-Resource Priority:** The bot must run efficiently on a 1GB VPS. Avoid blocking I/O and large in-memory data structures.
2.  **Async First:** Use `asyncio` for all I/O operations (API calls, DB writes).
3.  **Strict Typing:** All Python code must be strictly typed (`mypy --strict`).
4.  **Test-Driven:** New features must include unit tests with mocks. Live API calls are forbidden in tests.

---

## 🛠 Development Setup

We use **Python 3.11+** and **Poetry** for dependency management.

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/philibertschlutzki/polymarket_bot.git
    cd polymarket_bot
    ```

2.  **Install Dependencies:**
    ```bash
    poetry install
    ```

3.  **Activate Virtual Environment:**
    ```bash
    poetry shell
    ```

4.  **Install Pre-Commit Hooks (Recommended):**
    Install `pre-commit` locally if you want automatic checks before pushing.

---

## 🛡 Code Quality Standards

Our CI/CD pipeline enforces strict quality checks. Ensure your code passes these before submitting a PR.

Run all checks locally with:

1.  **Formatting (Black & Isort):**
    ```bash
    poetry run black src tests
    poetry run isort src tests
    ```

2.  **Linting (Flake8):**
    ```bash
    # Check for syntax errors and undefined names
    poetry run flake8 src tests --count --select=E9,F63,F7,F82 --show-source --statistics
    # Check for style guide adherence (max-complexity=10)
    poetry run flake8 src tests --count --max-complexity=10 --max-line-length=127 --statistics
    ```

3.  **Type Checking (MyPy - Strict):**
    ```bash
    poetry run mypy src
    ```

4.  **Testing (Pytest):**
    ```bash
    poetry run pytest
    ```

---

## 🚀 Roadmap & Help Wanted

We welcome contributions in the following areas:

### 1. Core Stability
*   **Database Optimization:** Improve SQLite performance with better batching strategies.
*   **Reconnection Logic:** Enhance WebSocket reconnection robustness for long-running sessions.

### 2. Strategy Development
*   **Mean Reversion:** Implement strategies for correlated markets.
*   **Arbitrage:** Detect price discrepancies between Yes/No pairs.

### 3. Analysis Tools
*   **Local Dashboard:** Create a Streamlit app to visualize `market_data.db`.
*   **Jupyter Notebooks:** Add analysis templates in `notebooks/`.

---

## 📝 Pull Request Workflow

1.  **Issue:** Create an issue describing the bug or feature.
2.  **Branch:** Create a branch with a descriptive name (e.g., `feat/whale-alert`, `fix/sqlite-lock`).
3.  **Code:** Implement changes following the guidelines above.
4.  **Test:** Add unit tests in `tests/`.
5.  **Verify:** Run all code quality checks locally.
6.  **Submit:** Open a PR against `main` with a clear description of your changes.

---

## 💡 Developer Tips

*   **Async/Await:** Use `await asyncio.sleep()` instead of `time.sleep()`.
*   **Secrets:** Never commit API keys. Use `.env`.
*   **Logging:** Use the project's logging setup (`logger.info()`), not `print()`.

Happy Coding! 🚀
