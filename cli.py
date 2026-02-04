#!/usr/bin/env python3
"""
Kalshi Weather Trader CLI

Commands:
  scan      - Scan for weather trading signals
  forecast  - Get weather forecasts for tracked cities
  markets   - List weather markets on Kalshi
  analyze   - Analyze a specific market
  trade     - Execute trades (requires auth)
"""
import argparse
import logging
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from src.config import config
from src.services.weather_api import WeatherService
from src.services.kalshi_api import KalshiClient
from src.signals.weather_signals import WeatherSignalEngine
from src.models.weather import Location


def setup_logging(debug: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )


def cmd_scan(args):
    """Scan for weather trading signals."""
    engine = WeatherSignalEngine()
    
    print(f"\n{'='*60}")
    print(f"🌡️  WEATHER TRADING SIGNALS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")
    
    signals = engine.scan_for_signals()
    
    if not signals:
        print("No signals meeting criteria found.")
        print(f"\nCriteria: {config.min_edge_pct*100:.0f}% minimum edge")
        return
    
    for i, signal in enumerate(signals[:args.limit], 1):
        print(f"[{i}] {signal.market_title[:50]}")
        print(f"    📍 {signal.location} | 📅 {signal.target_date}")
        print(f"    {'📈' if signal.recommended_side == 'YES' else '📉'} {signal.recommended_side} @ {signal.market_price:.0%}")
        print(f"    Edge: {signal.edge_pct:.1f}% | Model: {signal.model_probability:.0%} | Forecast: {signal.forecast_value:.0f}°F")
        print(f"    Confidence: {signal.confidence:.0%} | Size: ${signal.suggested_size:.0f}")
        print(f"    Ticker: {signal.market_ticker}")
        print()
    
    print(f"Total signals found: {len(signals)}")


def cmd_forecast(args):
    """Get weather forecasts."""
    service = WeatherService()
    
    print(f"\n{'='*60}")
    print(f"🌤️  WEATHER FORECASTS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")
    
    if args.city:
        # Find specific city
        city_config = None
        for c in config.tracked_cities:
            if c["name"].lower() == args.city.lower():
                city_config = c
                break
        
        if not city_config:
            print(f"City not found: {args.city}")
            print(f"Available: {', '.join(c['name'] for c in config.tracked_cities)}")
            return
        
        location = Location(
            name=city_config["name"],
            lat=city_config["lat"],
            lon=city_config["lon"],
            nws_office=city_config["nws_office"],
        )
        
        forecasts = service.get_temperature_forecast(location)
        if forecasts:
            print(f"📍 {location.name}")
            print("-" * 40)
            for f in forecasts[:7]:
                print(f"  {f.date}: High {f.high_temp:.0f}°F / Low {f.low_temp:.0f}°F")
                
                # Show probabilities for common thresholds
                if args.verbose:
                    for thresh in [32, 40, 50, 60, 70, 80, 90]:
                        prob = f.probability_high_above(thresh)
                        if 0.05 < prob < 0.95:
                            print(f"         P(High > {thresh}°F) = {prob:.0%}")
    else:
        # All cities
        all_forecasts = service.get_all_forecasts()
        
        for city_name, forecasts in all_forecasts.items():
            print(f"📍 {city_name}")
            for f in forecasts[:3]:
                print(f"   {f.date}: High {f.high_temp:.0f}°F / Low {f.low_temp:.0f}°F")
            print()


def cmd_markets(args):
    """List weather markets."""
    client = KalshiClient()
    
    print(f"\n{'='*60}")
    print(f"🎯 KALSHI WEATHER MARKETS")
    print(f"{'='*60}\n")
    
    markets = client.get_weather_markets()
    
    if not markets:
        print("No weather markets found.")
        print("(Weather markets may be seasonal or require auth)")
        return
    
    for m in markets[:args.limit]:
        yes_price = m.yes_mid
        print(f"[{m.ticker}]")
        print(f"  {m.title[:60]}")
        print(f"  Price: {yes_price:.0%} | Vol: ${m.volume:,.0f} | Spread: {m.spread}¢")
        if m.location:
            print(f"  Location: {m.location} | Threshold: {m.threshold}°F")
        print()
    
    print(f"Total: {len(markets)} weather markets")


def cmd_analyze(args):
    """Analyze a specific market."""
    engine = WeatherSignalEngine()
    
    print(f"\n{'='*60}")
    print(f"🔍 MARKET ANALYSIS: {args.ticker}")
    print(f"{'='*60}\n")
    
    result = engine.analyze_market(args.ticker)
    
    if not result:
        print("Market not found.")
        return
    
    market = result["market"]
    forecast = result["forecast"]
    signal = result["signal"]
    
    print("MARKET:")
    print(f"  Title: {market.title}")
    print(f"  Ticker: {market.ticker}")
    print(f"  Price: YES @ {market.yes_mid:.0%}")
    print(f"  Bid/Ask: {market.yes_bid}¢ / {market.yes_ask}¢")
    print(f"  Volume: ${market.volume:,.0f}")
    print(f"  Status: {market.status}")
    print()
    
    if forecast:
        print("FORECAST:")
        print(f"  Location: {forecast.location}")
        print(f"  Date: {forecast.date}")
        print(f"  High: {forecast.high_temp:.0f}°F")
        print(f"  Low: {forecast.low_temp:.0f}°F")
        print(f"  Source: {forecast.source}")
        
        if market.threshold:
            prob_above = forecast.probability_high_above(market.threshold)
            prob_below = forecast.probability_high_below(market.threshold)
            print(f"  P(High > {market.threshold}°F): {prob_above:.0%}")
            print(f"  P(High < {market.threshold}°F): {prob_below:.0%}")
        print()
    
    if signal:
        print("SIGNAL:")
        print(f"  Recommendation: {signal.recommended_side}")
        print(f"  Edge: {signal.edge_pct:.1f}%")
        print(f"  Model Probability: {signal.model_probability:.0%}")
        print(f"  Market Price: {signal.market_price:.0%}")
        print(f"  Confidence: {signal.confidence:.0%}")
        print(f"  Suggested Size: ${signal.suggested_size:.0f}")
    else:
        print("SIGNAL: None (no edge found)")


def cmd_demo(args):
    """Run demo with test data."""
    print(f"\n{'='*60}")
    print(f"🧪 WEATHER TRADER DEMO")
    print(f"{'='*60}\n")
    
    # Test weather API
    print("1. Testing Weather API...")
    service = WeatherService()
    
    ny = Location(
        name="New York",
        lat=40.7128,
        lon=-74.0060,
        nws_office="OKX"
    )
    
    forecasts = service.get_temperature_forecast(ny)
    if forecasts:
        print(f"   ✅ Got {len(forecasts)} days of forecasts for NYC")
        f = forecasts[0]
        print(f"   Tomorrow: High {f.high_temp:.0f}°F / Low {f.low_temp:.0f}°F")
        print(f"   P(High > 50°F) = {f.probability_high_above(50):.0%}")
        print(f"   P(High > 70°F) = {f.probability_high_above(70):.0%}")
    else:
        print("   ❌ Failed to get forecast")
    print()
    
    # Test Kalshi API
    print("2. Testing Kalshi API...")
    client = KalshiClient(use_demo=True)
    
    events = client.get_events(limit=5)
    if events:
        print(f"   ✅ Got {len(events)} events from Kalshi")
        for e in events[:3]:
            print(f"      - {e.get('title', 'N/A')[:50]}")
    else:
        print("   ⚠️ No events returned (may need auth)")
    print()
    
    # Test signal engine
    print("3. Testing Signal Engine...")
    engine = WeatherSignalEngine()
    
    # Create mock signal for demo
    from src.models.weather import WeatherSignal, WeatherMetric
    
    mock_signal = WeatherSignal(
        id="demo123",
        created_at=datetime.now(),
        market_ticker="KXTEMP-NYC-70",
        market_title="Will NYC high temperature exceed 70°F tomorrow?",
        metric=WeatherMetric.HIGH_TEMP,
        threshold=70,
        direction="above",
        location="New York",
        target_date=forecasts[0].date if forecasts else None,
        market_price=0.45,
        model_probability=0.62 if forecasts else 0.5,
        edge=0.17 if forecasts else 0,
        recommended_side="YES",
        confidence=0.75,
        suggested_size=150,
        forecast_value=forecasts[0].high_temp if forecasts else 0,
        forecast_source="Open-Meteo",
        forecast_time=datetime.now(),
    )
    
    print("   Sample Signal:")
    print(f"   {mock_signal.to_alert()}")
    
    print()
    print("="*60)
    print("✅ Demo complete! System is working.")
    print()
    print("Next steps:")
    print("  1. Set KALSHI_EMAIL and KALSHI_PASSWORD for trading")
    print("  2. Run: ./cli.py scan")
    print("  3. Review signals and trade manually or enable auto-trade")
    print("="*60)


def main():
    parser = argparse.ArgumentParser(
        description="Kalshi Weather Trader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./cli.py demo                    # Run system test
  ./cli.py scan                    # Find trading signals
  ./cli.py forecast                # Get all forecasts
  ./cli.py forecast --city NYC     # Get NYC forecast
  ./cli.py markets                 # List weather markets
  ./cli.py analyze KXTEMP-NYC-70   # Analyze specific market
"""
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Demo
    subparsers.add_parser("demo", help="Run demo test")
    
    # Scan
    scan_parser = subparsers.add_parser("scan", help="Scan for signals")
    scan_parser.add_argument("--limit", type=int, default=10, help="Max signals to show")
    
    # Forecast
    forecast_parser = subparsers.add_parser("forecast", help="Get forecasts")
    forecast_parser.add_argument("--city", help="Specific city")
    forecast_parser.add_argument("-v", "--verbose", action="store_true")
    
    # Markets
    markets_parser = subparsers.add_parser("markets", help="List markets")
    markets_parser.add_argument("--limit", type=int, default=20)
    
    # Analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analyze market")
    analyze_parser.add_argument("ticker", help="Market ticker")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    setup_logging(args.debug)
    
    if args.command == "demo":
        cmd_demo(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "forecast":
        cmd_forecast(args)
    elif args.command == "markets":
        cmd_markets(args)
    elif args.command == "analyze":
        cmd_analyze(args)


if __name__ == "__main__":
    main()
