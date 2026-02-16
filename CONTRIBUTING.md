# Contributing to Polymarket Bot V2

Vielen Dank für dein Interesse, an der Migration und Weiterentwicklung des Polymarket Bots mitzuwirken!
Dieses Projekt befindet sich in einer **kritischen Migrationsphase** von einer Legacy-Skript-Sammlung (V1) zu einer robusten Nautilus Trader Architektur (V2).

## 🎯 Fokus: V1 -> V2 Migration

Unser Hauptziel ist es, die Funktionen der alten Skripte in die neue modulare Struktur zu überführen.

### 🚧 Offene Baustellen (Help Wanted)

1.  **Market Scanner (`src/scanner/`)**
    *   **Ziel:** Portierung der Logik, die liquide Märkte auf Polymarket findet.
    *   **Anforderung:** Implementierung eines `MarketScanner` Moduls, das die Polymarket API (Gamma) abfragt, nach Volumen/Spread filtert und eine Liste von `InstrumentId`s für Nautilus zurückgibt.
    *   **Referenz:** Siehe alte Skripte in `legacy_v1/`.

2.  **Data Loaders (`src/data/`)**
    *   **Ziel:** Laden von historischen Daten für Backtesting.
    *   **Anforderung:** Schreiben von Custom Data Loaders für Nautilus, die `.csv` oder SQLite Dumps von Polymarket Orderbooks lesen und in Nautilus `Bar` oder `QuoteTick` Objekte konvertieren.

3.  **Entry Point (`src/main.py`)**
    *   **Ziel:** Der Klebstoff, der alles zusammenhält.
    *   **Anforderung:** Ein Skript, das:
        *   Die Nautilus `TradingNode` initialisiert.
        *   Den `MarketScanner` startet.
        *   Die `GeminiSentimentStrategy` registriert.
        *   Den Live-Modus startet.

## 🛠 Entwicklungsumgebung

Bitte halte dich an folgende Standards:

1.  **Code Style:** Wir nutzen `flake8`, `black` und `isort`.
    ```bash
    # Check Style
    flake8 src/
    ```

2.  **Dependencies:**
    *   Die `requirements.txt` ist die Source of Truth.
    *   Neue Dependencies nur hinzufügen, wenn absolut notwendig.

3.  **Testing:**
    *   Schreibe Unit Tests für neue Module in `tests/`.
    *   Führe Tests mit `python -m pytest` aus.

## Workflow

1.  Fork das Repo.
2.  Erstelle einen Feature Branch (`feat/scanner-implementation`).
3.  Implementiere die Logik.
4.  Erstelle einen Pull Request mit Referenz auf die V1-Funktionalität, die du portiert hast.
