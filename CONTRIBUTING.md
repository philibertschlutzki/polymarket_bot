# Contributing to Polymarket Bot V2

Vielen Dank für dein Interesse, den **Polymarket AI Trader** weiterzuentwickeln!
Wir befinden uns in der Phase **V2 (Beta)**. Das Ziel ist ein stabiles, speichereffizientes System, das auf kostengünstiger Hardware (VPS mit 1 GB RAM) läuft, aber professionelles Backtesting auf lokaler Hardware ermöglicht.

## 🏗 Architektur-Philosophie (WICHTIG)

Bevor du Code schreibst, verinnerliche bitte unser **Hybrid-Modell**:

1.  **Live-Trading (VPS - Low Resource):**
    * **Hardware:** 1 vCPU, **1 GB RAM**.
    * **Priorität:** Stabilität, Non-Blocking I/O, RAM-Effizienz.
    * **Regel:** Keine großen Pandas DataFrames im Speicher halten! Daten werden gestreamt und direkt in SQLite geschrieben.
    * **Komponenten:** Scanner, Execution Engine, Data Recorder.

2.  **Research & Backtesting (Local - High Resource):**
    * **Hardware:** Entwickler-Laptop / Workstation (z.B. 32 GB RAM).
    * **Priorität:** Analyse-Tiefe, Simulation.
    * **Datenfluss:** Liest die SQLite-DB (vom VPS), die via SCP/Git synchronisiert wurde.

---

## 🛠 Entwicklungsumgebung einrichten

Wir nutzen **Python 3.11+** und **Poetry** oder `pip` mit `venv`.

1.  **Repository klonen & Umgebung:**
    ```bash
    git clone [https://github.com/philibertschlutzki/polymarket_bot.git](https://github.com/philibertschlutzki/polymarket_bot.git)
    cd polymarket_bot
    python -m venv .venv
    source .venv/bin/activate  # oder .venv\Scripts\activate auf Windows
    pip install -r requirements.txt
    ```

2.  **Pre-Commit Hooks (Optional aber empfohlen):**
    Richte dir idealerweise Pre-Commit Hooks ein, um Linter-Fehler vor dem Push zu fangen.

---

## 🛡 Code Quality Standards

Unser CI/CD-Prozess (`.github/workflows/code-quality.yml`) ist streng. PRs, die diese Checks nicht bestehen, werden abgelehnt.

Führe **bevor** du pushst folgende Befehle aus:

1.  **Formatierung (Black):**
    ```bash
    black src/
    ```
2.  **Import-Sortierung (Isort):**
    ```bash
    isort src/
    ```
3.  **Linting (Flake8):**
    ```bash
    # Keine Syntaxfehler oder undefined names
    flake8 src/ --count --select=E9,F63,F7,F82 --show-source --statistics
    # Style Guide (Max Complexity 10)
    flake8 src/ --count --max-complexity=10 --max-line-length=127 --statistics
    ```
4.  **Type Checking (MyPy - Strict):**
    ```bash
    mypy src/ --ignore-missing-imports
    ```

---

## 🚀 Roadmap & Offene Aufgaben (Help Wanted)

Hier sind Bereiche, in denen wir dringend Unterstützung suchen oder sinnvolle Weiterentwicklungen sehen:

### 1. Core Stability & Performance
* **Verbesserung des Data Recorders:** Optimierung der SQLite Schreibzugriffe (WAL-Mode, Batch Inserts), um Disk-IO auf dem VPS zu minimieren.
* **Error Recovery:** Implementierung von automatischen Reconnect-Strategien für den WebSocket-Stream bei Verbindungsabbruch.

### 2. Strategie-Erweiterungen
* **Mean Reversion:** Entwicklung einer Strategie für korrelierte Märkte (z.B. "Trump gewinnt Pennsylvania" vs. "Trump gewinnt US-Wahl").
* **Arbitrage:** Erkennung von Preisunterschieden zwischen "Yes/No" Paaren, deren Summe < $1.00 (nach Gebühren) liegt.

### 3. Analyse & Dashboarding (Local)
* **Streamlit Dashboard:** Ein Tool, das die lokale `market_data.db` visualisiert (PNL-Kurve, Win-Rate, Gemini-Entscheidungen im Zeitverlauf).
* **Jupyter Notebooks:** Vorlagen im Ordner `notebooks/` zur Analyse der Sentiment-Performance.

### 4. Scanner-Logik
* **Whale Alert:** Erweiterung des Scanners um eine Funktion, die große Einzel-Trades auf der Blockchain erkennt und als Signal nutzt.

---

##  workflow für Pull Requests

1.  **Issue:** Suche dir ein Ticket aus oder erstelle eines für deinen Vorschlag.
2.  **Branch:** Erstelle einen Branch mit sprechendem Namen:
    * `feat/whale-alert-scanner`
    * `fix/sqlite-lock-error`
    * `docs/update-readme`
3.  **Changes:** Implementiere deine Änderungen. Achte auf **Asynchronität** (kein `time.sleep`, nutze `asyncio.sleep`)!
4.  **Test:** Schreibe Unit-Tests in `tests/` wenn du neue Logik hinzufügst.
5.  **Lint:** Führe die Quality-Checks aus (siehe oben).
6.  **PR:** Erstelle den Pull Request gegen `main`. Beschreibe genau, was du geändert hast und *warum*.

---

## 💡 Wichtige Hinweise für Entwickler

* **Async First:** Da der Bot in einem einzigen Event-Loop läuft, dürfen API-Calls (Gemini, Polymarket REST) niemals blockieren. Nutze `async/await` oder `loop.run_in_executor`.
* **Type Hints:** Wir nutzen striktes Typing. Jede Funktionssignatur muss typisiert sein (`def my_func(a: int) -> str:`).
* **Secrets:** Niemals API-Keys committen! Nutze `.env`.

Wir freuen uns auf deinen Code! Happy Trading! 📈
