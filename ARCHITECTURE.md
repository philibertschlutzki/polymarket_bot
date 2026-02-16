# Polymarket Bot V2 Architecture

Das System basiert auf einer Event-Driven Architecture unter Verwendung des **Nautilus Trader Frameworks**. Es integriert **Google Gemini 2.0 Flash** für Sentiment-Analyse mit real-time Marktdaten via Google Search Grounding.

## 🏗 High-Level Übersicht

```mermaid
graph TD
    A[Market Data Provider] -->|Bar/Quote| B(Nautilus Engine)
    B -->|on_bar Event| C{GeminiSentimentStrategy}
    C -->|Anfrage| D[Intelligence Layer (GeminiSentiment)]
    D -->|Prompt + Context| E[Google Gemini 2.0 Flash]
    E -->|Google Search Retrieval| F[Google Search]
    F -->|Suchergebnisse| E
    E -->|Sentiment JSON| D
    D -->|Signal (Bullish/Bearish)| C
    C -->|Order| B
    B -->|Execution| G[Polymarket Exchange]
```

## 🧩 Kern-Komponenten

### 1. Nautilus Trader Engine (Core)
Das Rückgrat des Systems (Library + `src/`). Verwaltet:
*   **Data Ingestion:** Empfang von Marktdaten via WebSocket/REST.
*   **Order Management:** Validierung und Routing von Orders.
*   **Risk Management:** Überwachung von Limits und Exposure.

### 2. Strategy Layer (`src/strategies/`)
Hier liegt die Handelslogik.
*   **File:** `src/strategies/sentiment.py`
*   **Klasse:** `GeminiSentimentStrategy` (erbt von `nautilus_trader.trading.strategy.Strategy`)
*   **Aufgabe:** Empfängt `on_bar` Events, prüft technische Indikatoren (oder Zeit-Trigger) und delegiert die komplexe Analyse an den Intelligence Layer.

### 3. Intelligence Layer (`src/intelligence/`)
Ein isolierter Wrapper für KI-Modelle, um die Strategie "sauber" zu halten.
*   **File:** `src/intelligence/gemini.py`
*   **Klasse:** `GeminiSentiment`
*   **Aufgabe:**
    *   Initialisierung der Google Generative AI API (`google-generativeai`).
    *   Konfiguration von **Search Grounding** (Tools).
    *   Prompt Engineering & Context Injection.
    *   **JSON Enforcement:** Stellt sicher, dass Gemini valides JSON zurückgibt (`{"sentiment": "bullish", "confidence": 0.9}`).

## 🔄 Execution Flow

1.  **Event Trigger:** Ein neuer Preis-Bar (z.B. 1 Minute) trifft ein. Die `on_bar` Methode der Strategie wird aufgerufen.
2.  **Filter:** Die Strategie prüft simple Bedingungen (z.B. "Ist der Markt noch offen?", "Haben wir Positionen?").
3.  **Analysis Request:** Die Strategie ruft `analyze_market(question, context)` auf dem `GeminiSentiment` Wrapper auf.
4.  **Grounding:**
    *   Der Wrapper sendet den Prompt an Gemini 2.0.
    *   Gemini erkennt, dass es aktuelle Infos braucht und nutzt das `google_search_retrieval` Tool.
    *   Gemini liest aktuelle News-Schlagzeilen zu dem Event.
5.  **Decision:**
    *   Gemini bewertet die News vs. den aktuellen Preis.
    *   Gibt ein JSON-Objekt mit `sentiment`, `confidence` und `reasoning` zurück.
6.  **Action:**
    *   Die Strategie empfängt das Resultat.
    *   Wenn `confidence > threshold` (z.B. 0.75) UND Sentiment passt zur Richtung -> **Submit Order**.

## 🚧 Status der Migration

Aktuell befindet sich die Architektur in der Transition von V1 (Skripte) zu V2 (Nautilus).
*   **Intelligence Layer:** ✅ Implementiert (`gemini.py`)
*   **Strategy Core:** 🚧 In Entwicklung (`sentiment.py` ist ein Skelett)
*   **Data Loading:** 🚧 Geplant (`src/data/`)
*   **Scanner:** 🚧 Geplant (`src/scanner/`)
