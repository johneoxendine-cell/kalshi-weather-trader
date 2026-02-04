#!/usr/bin/env python3
"""
Weather Trading Scanner - Finds edges between weather models and Kalshi markets.
Optimized for reliability and rate limit compliance.
"""
import json
import time
import requests
from datetime import datetime, date
from dataclasses import dataclass
from typing import List, Optional, Dict

# Configuration
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
OPEN_METEO_API = "https://api.open-meteo.com/v1"
ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"

MIN_EDGE_PCT = 0.08  # 8% minimum edge
MIN_LIQUIDITY = 100  # Minimum volume
INITIAL_CAPITAL = 1000  # Starting capital
MAX_POSITION_SIZE = 100  # Max per trade (10% of capital)
KELLY_FRACTION = 0.20  # 20% Kelly

# Cities with weather markets
CITIES = [
    {"name": "New York", "lat": 40.7128, "lon": -74.0060, "series": ["KXHIGHNY", "KXLOWNY", "KXLOWTNYC"]},
    {"name": "Chicago", "lat": 41.8781, "lon": -87.6298, "series": ["KXHIGHCHI", "KXLOWCHI"]},
    {"name": "Miami", "lat": 25.7617, "lon": -80.1918, "series": ["KXHIGHMIA", "KXLOWMIA", "KXLOWTMIA"]},
    {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437, "series": ["KXHIGHLAX", "KXLOWLAX"]},
    {"name": "Denver", "lat": 39.7392, "lon": -104.9903, "series": ["KXHIGHDEN", "KXHIGHTEMPDEN"]},
    {"name": "Houston", "lat": 29.7604, "lon": -95.3698, "series": ["KXHIGHOU", "KXHOUHIGH"]},
    {"name": "Phoenix", "lat": 33.4484, "lon": -112.0740, "series": ["KXHIGHTPHX"]},
    {"name": "Austin", "lat": 30.2672, "lon": -97.7431, "series": ["KXHIGHAUS"]},
    {"name": "Philadelphia", "lat": 39.9526, "lon": -75.1652, "series": ["KXHIGHPHIL", "KXLOWPHIL"]},
    {"name": "Seattle", "lat": 47.6062, "lon": -122.3321, "series": ["KXHIGHTSEA"]},
]


@dataclass
class Signal:
    """Trading signal with edge calculation."""
    ticker: str
    title: str
    city: str
    target_date: str
    market_price: float  # YES price as decimal
    model_prob: float    # Model probability as decimal
    edge: float          # Edge as decimal
    direction: str       # "YES" or "NO"
    forecast_temp: float
    threshold: float
    confidence: float
    suggested_size: float
    
    def to_alert(self) -> str:
        emoji = "📈" if self.direction == "YES" else "📉"
        return f"""🌡️ **WEATHER SIGNAL**

**{self.title[:60]}**
📍 {self.city} | 📅 {self.target_date}

{emoji} **{self.direction}** @ {self.market_price:.0%}

**Edge: {self.edge*100:.1f}%**
• Model says: {self.model_prob:.0%}
• Market says: {self.market_price:.0%}
• Forecast: {self.forecast_temp:.0f}°F

**Confidence:** {self.confidence:.0%}
**Suggested size:** ${self.suggested_size:.0f}

Ticker: `{self.ticker}`"""


def get_weather_events(series_ticker: str) -> List[dict]:
    """Get open events for a weather series."""
    try:
        resp = requests.get(
            f"{KALSHI_API}/events",
            params={"series_ticker": series_ticker, "status": "open", "limit": 10},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("events", [])
    except Exception as e:
        print(f"  Error fetching events for {series_ticker}: {e}")
        return []


def get_event_markets(event_ticker: str) -> List[dict]:
    """Get markets for an event."""
    try:
        resp = requests.get(
            f"{KALSHI_API}/markets",
            params={"event_ticker": event_ticker, "limit": 50},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("markets", [])
    except Exception as e:
        print(f"  Error fetching markets for {event_ticker}: {e}")
        return []


def get_ensemble_forecast(lat: float, lon: float, days: int = 7) -> Dict[str, List[float]]:
    """Get ensemble temperature forecast."""
    try:
        resp = requests.get(
            ENSEMBLE_API,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": "America/New_York",
                "forecast_days": days,
                "models": "gfs_seamless"
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        
        # Extract all ensemble members for each day
        result = {"dates": daily.get("time", [])}
        
        for day_idx in range(len(result["dates"])):
            high_temps = []
            low_temps = []
            
            for key, vals in daily.items():
                if "max" in key and isinstance(vals, list) and len(vals) > day_idx:
                    high_temps.append(vals[day_idx])
                elif "min" in key and isinstance(vals, list) and len(vals) > day_idx:
                    low_temps.append(vals[day_idx])
            
            result[f"high_{day_idx}"] = high_temps
            result[f"low_{day_idx}"] = low_temps
        
        return result
        
    except Exception as e:
        print(f"  Error fetching forecast: {e}")
        return {}


def calc_probability(temps: List[float], threshold: float, above: bool = True) -> float:
    """Calculate probability from ensemble members."""
    if not temps:
        return 0.5
    if above:
        return sum(1 for t in temps if t > threshold) / len(temps)
    else:
        return sum(1 for t in temps if t < threshold) / len(temps)


def calc_range_probability(temps: List[float], low: float, high: float) -> float:
    """Calculate probability of temp falling in a range."""
    if not temps:
        return 0.0
    return sum(1 for t in temps if low <= t < high) / len(temps)


def parse_market_threshold(ticker: str, title: str) -> Optional[tuple]:
    """Parse threshold and direction from market ticker/title."""
    # Formats: 
    # KXHIGHNY-26FEB04-T30 (above 30)
    # KXHIGHNY-26FEB04-B32.5 (range 32-33)
    
    import re
    
    # Try to extract from ticker
    if "-T" in ticker:
        # Threshold format: above/below
        match = re.search(r'-T(\d+\.?\d*)$', ticker)
        if match:
            thresh = float(match.group(1))
            if "high" in title.lower() and ">" in title:
                return (thresh, "above", None)
            elif "<" in title:
                return (thresh, "below", None)
    
    if "-B" in ticker:
        # Bucket format: range
        match = re.search(r'-B(\d+\.?\d*)$', ticker)
        if match:
            base = float(match.group(1))
            # Typically X.5 means range X to X+2
            return (base - 0.5, "range", base + 1.5)
    
    return None


def kelly_size(edge: float, win_prob: float, capital: float = INITIAL_CAPITAL) -> float:
    """Calculate Kelly criterion position size."""
    if edge <= 0 or win_prob <= 0 or win_prob >= 1:
        return 0
    
    # Simplified Kelly for binary markets
    # f* = (p * b - q) / b where b = odds, p = win prob, q = 1-p
    # For prediction markets: f* = 2p - 1 (when fair odds)
    
    kelly = edge * KELLY_FRACTION
    size = capital * kelly
    return min(size, MAX_POSITION_SIZE)


def scan_city(city: dict) -> List[Signal]:
    """Scan all weather markets for a city."""
    signals = []
    
    print(f"\n📍 Scanning {city['name']}...")
    
    # Get forecast
    forecast = get_ensemble_forecast(city["lat"], city["lon"])
    if not forecast.get("dates"):
        print(f"  ⚠️ Could not get forecast")
        return signals
    
    # Scan each series
    for series in city["series"]:
        time.sleep(0.3)  # Rate limit
        events = get_weather_events(series)
        
        for event in events:
            event_ticker = event.get("event_ticker", "")
            event_title = event.get("title", "")
            
            # Extract date from event
            # Format: KXHIGHNY-26FEB04
            import re
            date_match = re.search(r'-(\d{2})([A-Z]{3})(\d{2})$', event_ticker)
            if not date_match:
                continue
                
            year = int("20" + date_match.group(1))
            month_str = date_match.group(2)
            day = int(date_match.group(3))
            
            months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                     'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
            month = months.get(month_str, 1)
            
            target_date = f"{year}-{month:02d}-{day:02d}"
            
            # Find day index in forecast
            day_idx = None
            for i, d in enumerate(forecast.get("dates", [])):
                if d == target_date:
                    day_idx = i
                    break
            
            if day_idx is None:
                continue
            
            # Get ensemble temps for this day
            is_high = "high" in series.lower()
            temps_key = f"high_{day_idx}" if is_high else f"low_{day_idx}"
            temps = forecast.get(temps_key, [])
            
            if not temps:
                continue
            
            mean_temp = sum(temps) / len(temps)
            
            # Get markets for this event
            time.sleep(0.3)
            markets = get_event_markets(event_ticker)
            
            for market in markets:
                ticker = market.get("ticker", "")
                title = market.get("title", "")
                yes_bid = market.get("yes_bid", 0) / 100
                yes_ask = market.get("yes_ask", 0) / 100
                volume = market.get("volume", 0)
                
                if volume < MIN_LIQUIDITY:
                    continue
                
                market_price = (yes_bid + yes_ask) / 2
                if market_price <= 0 or market_price >= 1:
                    continue
                
                # Parse threshold
                parsed = parse_market_threshold(ticker, title)
                if not parsed:
                    continue
                
                threshold, direction, upper = parsed
                
                # Calculate model probability
                if direction == "above":
                    model_prob = calc_probability(temps, threshold, above=True)
                elif direction == "below":
                    model_prob = calc_probability(temps, threshold, above=False)
                elif direction == "range" and upper:
                    model_prob = calc_range_probability(temps, threshold, upper)
                else:
                    continue
                
                # Calculate edge
                edge_yes = model_prob - market_price
                edge_no = (1 - model_prob) - (1 - market_price)
                
                if edge_yes >= MIN_EDGE_PCT:
                    signals.append(Signal(
                        ticker=ticker,
                        title=title,
                        city=city["name"],
                        target_date=target_date,
                        market_price=market_price,
                        model_prob=model_prob,
                        edge=edge_yes,
                        direction="YES",
                        forecast_temp=mean_temp,
                        threshold=threshold,
                        confidence=min(0.95, 0.5 + abs(edge_yes)),
                        suggested_size=kelly_size(edge_yes, model_prob)
                    ))
                elif edge_no >= MIN_EDGE_PCT:
                    signals.append(Signal(
                        ticker=ticker,
                        title=title,
                        city=city["name"],
                        target_date=target_date,
                        market_price=market_price,
                        model_prob=model_prob,
                        edge=edge_no,
                        direction="NO",
                        forecast_temp=mean_temp,
                        threshold=threshold,
                        confidence=min(0.95, 0.5 + abs(edge_no)),
                        suggested_size=kelly_size(edge_no, 1 - model_prob)
                    ))
    
    return signals


def scan_all() -> List[Signal]:
    """Scan all cities for trading signals."""
    print(f"\n{'='*60}")
    print(f"🌡️  WEATHER TRADING SCAN - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    all_signals = []
    
    for city in CITIES:
        signals = scan_city(city)
        all_signals.extend(signals)
        time.sleep(0.5)  # Rate limit between cities
    
    # Sort by edge
    all_signals.sort(key=lambda s: s.edge, reverse=True)
    
    return all_signals


def main():
    signals = scan_all()
    
    print(f"\n{'='*60}")
    print(f"📊 RESULTS")
    print(f"{'='*60}\n")
    
    if not signals:
        print("No signals meeting criteria found.")
        print(f"(Minimum edge: {MIN_EDGE_PCT*100:.0f}%)")
    else:
        for i, s in enumerate(signals[:10], 1):
            print(f"[{i}] {s.ticker}")
            print(f"    {s.title[:60]}")
            print(f"    📍 {s.city} | 📅 {s.target_date}")
            print(f"    {'📈' if s.direction == 'YES' else '📉'} {s.direction} @ {s.market_price:.0%}")
            print(f"    Edge: {s.edge*100:.1f}% | Model: {s.model_prob:.0%} | Forecast: {s.forecast_temp:.0f}°F")
            print(f"    Size: ${s.suggested_size:.0f}")
            print()
    
    print(f"Total signals: {len(signals)}")
    
    return signals


if __name__ == "__main__":
    main()
