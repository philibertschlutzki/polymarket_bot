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
- [x] Datenbank-Integration (SQLite) zum Tracken der eigenen Wetthistorie und KI-Performance.
- [ ] Web-Dashboard (Streamlit) zur Visualisierung offener Positionen.
- [ ] Stop-Loss Logik (Automatischer Verkauf, wenn sich die Wahrscheinlichkeit dreht).

## Phase 5: Production Deployment ✅ (Januar 2026)
- [x] SQLite Persistence Layer (active_bets, results, portfolio_state)
- [x] 24/7 Scheduler mit Quota-Management (95% Nutzung)
- [x] Market Resolution Detection & Auto-Settlement
- [x] Performance Dashboard mit ASCII Charts
- [x] Git Auto-Push Integration
- [x] Raspberry Pi Deployment Script
- [x] systemd Service mit Auto-Restart
- [x] Log Rotation (7-Tage-Retention)

## Phase 6: Advanced Features 🔮 (Future)
- [ ] Telegram/Email Notifications bei High-Value Bets
- [ ] Multi-Model Validation (Critic Pattern)
- [ ] Dynamic Kelly-Fraction basierend auf Performance
- [ ] Web-Dashboard (Streamlit/Flask)
- [ ] Stop-Loss Logic (Auto-Exit bei negativem Shift)
