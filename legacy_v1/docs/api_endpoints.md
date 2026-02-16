# API Documentation

## 1. Polymarket Gamma API (REST)
**Base URL:** `https://gamma-api.polymarket.com`

### GET /markets
Fetches active markets. Used for market discovery.

**Key Parameters:**
- `closed`: `false` (only open markets)
- `limit`: `100` (batch size)
- `order`: `volume`
- `ascending`: `false`

**Response Structure:**
```json
[
  {
    "id": "0x...",
    "question": "Will X happen?",
    "volume": "150000",
    "outcome_prices": "[0.60, 0.40]",
    "end_date": "2024-12-31..."
  }
]
```

## 2. Goldsky Markets Subgraph (GraphQL)
**URL:** `https://api.goldsky.com/api/public/project_clrb8pu7r0abk01w14w7o5rkl/subgraphs/polymarket-markets/latest/gn`

### Query: `market(id: ...)`
Used for:
1.  Checking resolution status (`closed`, `resolvedBy`).
2.  Fetching exact outcome prices for settlement.
3.  Fetching missing end dates.

**Sample Query:**
```graphql
query {
  market(id: "0x123...") {
    closed
    resolvedBy
    outcomes {
      price
    }
    end_date_iso
  }
}
```

## 3. Google Gemini API
**Model:** `gemini-2.0-flash`

### POST /generateContent
Used for market probability estimation.

**Features:**
- **Tools**: `google_search` (Search Grounding) enabled.
- **Prompt**: Structured prompt requesting JSON output with `estimated_probability` and `reasoning`.

**Rate Limits (Free Tier):**
- 15 RPM (Requests Per Minute)
- 1,500 RPD (Requests Per Day)
- 1M TPM (Tokens Per Minute)

The bot implements a `RateLimiter` class in `src/main.py` to respect the 15 RPM limit.
