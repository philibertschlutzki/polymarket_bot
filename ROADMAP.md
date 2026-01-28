---

### 3. Datei: `ROADMAP.md`

Dies hilft Ihnen, den Überblick zu behalten, was als Nächstes zu tun ist.

```markdown
# Projekt Roadmap 🗺️

## Phase 1: Der "Advisory Bot" (Aktueller Status) ✅
- [x] Anbindung an Polymarket Gamma API (Lesen von Märkten).
- [x] Integration von Gemini 2.0 Flash.
- [x] Aktivierung von Google Search Grounding für Echtzeit-Daten.
- [x] Implementierung des Kelly-Kriteriums mit 50% Cap.
- [x] Konsolenausgabe mit klaren Handelsempfehlungen.

## Phase 2: Automatisierte Ausführung (Execution) 🚧
- [ ] Wallet-Setup (Polygon Private Key Integration).
- [ ] Integration der `py-clob-client` Bibliothek.
- [ ] Erstellung von API Keys auf Polymarket (L2 Keys).
- [ ] Automatische Platzierung von Limit-Orders.

## Phase 3: Erweiterte Intelligenz 🧠
- [ ] **Spezialisierte Agenten:** Unterscheidung der Prompts nach Kategorie (z.B. Sport-Prompt vs. Politik-Prompt vs. Krypto-Prompt).
- [ ] **Multi-Model Validierung:** Nutzung eines zweiten LLMs zur Überprüfung der Gemini-Aussagen (Critic-Pattern).
- [ ] **Sentiment Analyse:** Analyse von Twitter/X Trends zu bestimmten Märkten.

## Phase 4: Professionalisierung 💼
- [ ] Datenbank-Integration (SQLite) zum Tracken der eigenen Wetthistorie und KI-Performance.
- [ ] Web-Dashboard (Streamlit) zur Visualisierung offener Positionen.
- [ ] Stop-Loss Logik (Automatischer Verkauf, wenn sich die Wahrscheinlichkeit dreht).
