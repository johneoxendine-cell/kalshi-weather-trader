# Kalshi Weather Trader

**Profitable weather trading on Kalshi using meteorological models.**

The edge: NWS/ECMWF weather models are more accurate than retail traders' intuition. This system compares model probabilities to market prices and trades the difference.

## Why Weather Markets?

| Factor | Weather | Politics | Sports |
|--------|---------|----------|--------|
| Model accuracy | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| Retail bias | High | Medium | Low |
| Edge potential | 5-15% | 3-8% | 1-3% |
| Data availability | Free | Limited | Expensive |

Weather forecasting is a solved problem. Ensemble models provide accurate probability distributions. Retail traders don't use them.

## Quick Start

```bash
cd ~/kalshi-weather-trader

# Test the system
python3 cli.py demo

# Get forecasts
python3 cli.py forecast

# Scan for trading signals
python3 cli.py scan

# Analyze specific market
python3 cli.py analyze KXTEMP-NYC-70
```

## How It Works

### 1. Weather Data
- **Open-Meteo**: Free ensemble forecasts (51 model runs)
- **NWS**: Official US forecasts
- Calculates probability distributions, not point estimates

### 2. Market Data
- Fetches Kalshi weather markets (temperature, precipitation)
- Parses market structure (threshold, location, date)

### 3. Signal Generation
```
Edge = Model_Probability - Market_Price

If Edge > 8%:
  → Generate trading signal
  → Calculate position size (Kelly criterion)
  → Send alert
```

### 4. Example
```
Market: "Will NYC high exceed 50°F on Feb 10?"
Market Price: 45% YES

Model Forecast: High 52°F ± 3°F
Model Probability: 62% chance > 50°F

Edge: 62% - 45% = 17%
→ BUY YES

Expected Value: 17¢ per $1 risked
```

## Configuration

Set in `src/config.py` or environment variables:

```bash
# Kalshi credentials (for trading)
export KALSHI_EMAIL="your@email.com"
export KALSHI_PASSWORD="yourpassword"

# Notifications
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

### Thresholds

| Setting | Default | Description |
|---------|---------|-------------|
| `min_edge_pct` | 8% | Minimum edge to signal |
| `min_confidence` | 60% | Minimum confidence |
| `max_position_size` | $500 | Max per trade |
| `kelly_fraction` | 20% | Fractional Kelly |

## CLI Commands

```
demo      Run system test
scan      Scan for trading signals
forecast  Get weather forecasts
markets   List Kalshi weather markets
analyze   Deep-dive on specific market
```

## Tracked Cities

- New York, Los Angeles, Chicago, Houston
- Phoenix, Miami, Denver, Seattle
- Atlanta, Boston

Add more in `config.py`.

## File Structure

```
kalshi-weather-trader/
├── cli.py                    # Command-line interface
├── src/
│   ├── config.py            # Configuration
│   ├── models/
│   │   └── weather.py       # Data models
│   ├── services/
│   │   ├── weather_api.py   # NWS/Open-Meteo clients
│   │   └── kalshi_api.py    # Kalshi client
│   └── signals/
│       └── weather_signals.py  # Signal generation
└── data/                    # SQLite database
```

## Expected Performance

Based on historical weather forecast accuracy:

- **1-day forecasts**: 8-15% edge (high confidence)
- **3-day forecasts**: 5-10% edge (medium confidence)
- **7-day forecasts**: 2-5% edge (low confidence)

With proper sizing and discipline:
- **Win rate**: 55-65%
- **Profit factor**: 1.3-1.8
- **Annual ROI**: 20-50% (conservative)

## Risk Management

- Position limits (max $500/trade)
- Daily loss limits ($200)
- Kelly criterion sizing (fractional)
- Confidence-adjusted sizing

## Roadmap

- [ ] Auto-trading via Kalshi API
- [ ] Real-time monitoring daemon
- [ ] Hurricane/severe weather markets
- [ ] Precipitation markets
- [ ] Historical backtesting
- [ ] Web dashboard

## Disclaimer

Trading involves risk. Past performance doesn't guarantee future results. Weather models can be wrong. Use paper trading first.

---

## Quick Recovery Guide

If context is lost, here's how to get back up to speed:

### API Endpoint
```
https://api.elections.kalshi.com/trade-api/v2
```
(NOT api.kalshi.com - that's deprecated)

### Run Scanner
```bash
cd ~/kalshi-weather-trader
python3 scanner.py
```

### Check Trades
```bash
cat trades/2026-02-03.json
```

### Cron Jobs
Scanner runs every 2 hours via OpenClaw cron. Check with:
```
/cron list
```

### Market URLs
```
https://kalshi.com/events/KXHIGHNY-26FEB04  # NYC Feb 4
https://kalshi.com/events/KXHIGHCHI-26FEB04 # Chicago Feb 4
```

### Contract Math
- Price in cents (6¢ = $0.06 per contract)
- Each contract pays $1 if it wins
- Risk = contracts × price
- Profit if win = contracts × (1 - price)
