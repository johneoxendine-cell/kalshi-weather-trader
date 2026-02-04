"""
Weather Signal Engine

Compares weather forecasts to Kalshi market prices to find trading edges.
"""
import logging
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict

from ..config import config
from ..models.weather import (
    WeatherSignal, KalshiMarket, TemperatureForecast, 
    WeatherMetric, Location
)
from ..services.weather_api import WeatherService
from ..services.kalshi_api import KalshiClient

logger = logging.getLogger(__name__)


class WeatherSignalEngine:
    """
    Generates trading signals by comparing weather models to market prices.
    
    Edge sources:
    1. NWS/ECMWF models are more accurate than retail intuition
    2. Markets overreact to recent weather
    3. Ensemble spreads give true probability distributions
    """
    
    def __init__(self):
        self.weather = WeatherService()
        self.kalshi = KalshiClient()
        
        # Signal tracking
        self._recent_signals: Dict[str, datetime] = {}
    
    def scan_for_signals(self) -> List[WeatherSignal]:
        """
        Scan all weather markets for trading opportunities.
        
        Returns list of signals meeting minimum edge criteria.
        """
        logger.info("Scanning for weather trading signals...")
        
        signals = []
        
        # Get weather markets from Kalshi
        markets = self.kalshi.get_weather_markets()
        logger.info(f"Found {len(markets)} weather markets")
        
        # Get forecasts for all tracked cities
        forecasts = self.weather.get_all_forecasts()
        logger.info(f"Got forecasts for {len(forecasts)} cities")
        
        # Match markets to forecasts and check for edges
        for market in markets:
            if not market.location or not market.metric or not market.threshold:
                continue
            
            # Check cooldown
            if self._in_cooldown(market.ticker):
                continue
            
            # Find matching forecast
            city_forecasts = forecasts.get(market.location, [])
            if not city_forecasts:
                continue
            
            # Find forecast for target date
            forecast = None
            for f in city_forecasts:
                if market.target_date and f.date == market.target_date:
                    forecast = f
                    break
            
            if not forecast:
                # Use nearest date
                if city_forecasts:
                    forecast = min(
                        city_forecasts,
                        key=lambda f: abs((f.date - (market.target_date or date.today())).days)
                    )
            
            if not forecast:
                continue
            
            # Calculate signal
            signal = self._evaluate_market(market, forecast)
            
            if signal and signal.edge_pct >= config.min_edge_pct * 100:
                signals.append(signal)
                self._recent_signals[market.ticker] = datetime.utcnow()
        
        # Sort by edge
        signals.sort(key=lambda s: s.edge_pct, reverse=True)
        
        logger.info(f"Generated {len(signals)} signals")
        return signals
    
    def _evaluate_market(
        self,
        market: KalshiMarket,
        forecast: TemperatureForecast
    ) -> Optional[WeatherSignal]:
        """
        Evaluate a single market against forecast.
        
        Calculates edge = model_probability - market_price
        """
        if not market.threshold:
            return None
        
        # Get market price (probability implied by market)
        market_price = market.yes_mid
        if market_price <= 0 or market_price >= 1:
            return None
        
        # Calculate model probability
        model_prob = self._calculate_probability(market, forecast)
        if model_prob is None:
            return None
        
        # Calculate edge
        # Positive edge = model says YES is more likely than market
        edge = model_prob - market_price
        
        # Determine which side to bet
        if edge > 0:
            recommended_side = "YES"
            effective_edge = edge
        else:
            recommended_side = "NO"
            effective_edge = -edge  # Flip sign for NO bet
        
        # Check minimum edge
        if effective_edge < config.min_edge_pct:
            return None
        
        # Calculate confidence
        confidence = self._calculate_confidence(market, forecast, effective_edge)
        
        # Calculate position size (Kelly)
        suggested_size = self._calculate_size(effective_edge, confidence, market_price)
        
        # Get forecast value for display
        if market.metric == WeatherMetric.HIGH_TEMP:
            forecast_value = forecast.high_temp
        elif market.metric == WeatherMetric.LOW_TEMP:
            forecast_value = forecast.low_temp
        else:
            forecast_value = 0
        
        return WeatherSignal(
            id=str(uuid.uuid4())[:8],
            created_at=datetime.utcnow(),
            market_ticker=market.ticker,
            market_title=market.title,
            metric=market.metric,
            threshold=market.threshold,
            direction="above" if "above" in market.title.lower() else "below",
            location=market.location,
            target_date=market.target_date or forecast.date,
            market_price=market_price,
            model_probability=model_prob,
            edge=edge,
            recommended_side=recommended_side,
            confidence=confidence,
            suggested_size=suggested_size,
            forecast_value=forecast_value,
            forecast_source=forecast.source,
            forecast_time=forecast.forecast_time,
        )
    
    def _calculate_probability(
        self,
        market: KalshiMarket,
        forecast: TemperatureForecast
    ) -> Optional[float]:
        """Calculate probability from forecast model."""
        threshold = market.threshold
        title_lower = market.title.lower()
        
        if market.metric == WeatherMetric.HIGH_TEMP:
            if "above" in title_lower or "over" in title_lower or "exceed" in title_lower:
                return forecast.probability_high_above(threshold)
            elif "below" in title_lower or "under" in title_lower:
                return forecast.probability_high_below(threshold)
            else:
                # Default to "above" for high temp markets
                return forecast.probability_high_above(threshold)
        
        elif market.metric == WeatherMetric.LOW_TEMP:
            if "above" in title_lower or "over" in title_lower:
                return forecast.probability_low_above(threshold)
            elif "below" in title_lower or "under" in title_lower:
                return forecast.probability_low_below(threshold)
            else:
                # Default to "below" for low temp markets
                return forecast.probability_low_below(threshold)
        
        return None
    
    def _calculate_confidence(
        self,
        market: KalshiMarket,
        forecast: TemperatureForecast,
        edge: float
    ) -> float:
        """
        Calculate confidence in the signal.
        
        Factors:
        - Forecast uncertainty (days out)
        - Ensemble spread
        - Market liquidity
        - Edge size
        """
        confidence = 0.5  # Base
        
        # Days until resolution (closer = more confident)
        if market.target_date:
            days_out = (market.target_date - date.today()).days
            if days_out <= 1:
                confidence += 0.20
            elif days_out <= 3:
                confidence += 0.15
            elif days_out <= 5:
                confidence += 0.10
            else:
                confidence -= 0.05
        
        # Edge size (larger edge = more confident it's real)
        if edge > 0.15:
            confidence += 0.15
        elif edge > 0.10:
            confidence += 0.10
        elif edge > 0.05:
            confidence += 0.05
        
        # Ensemble availability (have distribution = more confident)
        if forecast.high_temp_ensemble or forecast.low_temp_ensemble:
            confidence += 0.10
        
        # Market liquidity
        if market.volume > 1000:
            confidence += 0.05
        elif market.volume < 100:
            confidence -= 0.10
        
        # Spread (tight spread = efficient market)
        if market.spread > 10:
            confidence -= 0.05  # Wide spread, less efficient
        
        return min(0.95, max(0.30, confidence))
    
    def _calculate_size(
        self,
        edge: float,
        confidence: float,
        market_price: float
    ) -> float:
        """
        Calculate position size using Kelly criterion.
        
        Kelly: f* = (p*b - q) / b
        where p = probability, b = odds, q = 1-p
        """
        # Adjust probability by confidence
        if edge > 0:
            p = market_price + edge * confidence
        else:
            p = market_price + edge * confidence
        
        p = max(0.01, min(0.99, p))
        q = 1 - p
        
        # Calculate decimal odds
        if market_price > 0:
            b = (1 / market_price) - 1
        else:
            return 0
        
        # Kelly fraction
        if b > 0:
            kelly = (p * b - q) / b
        else:
            kelly = 0
        
        kelly = max(0, kelly)
        
        # Apply fractional Kelly
        size = kelly * config.kelly_fraction * 1000  # Assume $1000 base
        
        # Cap at max position
        size = min(size, config.max_position_size)
        
        return round(size, 2)
    
    def _in_cooldown(self, ticker: str) -> bool:
        """Check if market is in signal cooldown."""
        last_signal = self._recent_signals.get(ticker)
        if not last_signal:
            return False
        
        hours_since = (datetime.utcnow() - last_signal).total_seconds() / 3600
        return hours_since < config.signal_cooldown_hours
    
    def analyze_market(
        self,
        ticker: str
    ) -> Optional[Dict]:
        """Analyze a specific market in detail."""
        market = self.kalshi.get_market(ticker)
        if not market:
            return None
        
        # Get forecast
        location = None
        for city in config.tracked_cities:
            if market.location and city["name"] == market.location:
                location = Location(
                    name=city["name"],
                    lat=city["lat"],
                    lon=city["lon"],
                    nws_office=city["nws_office"],
                )
                break
        
        if not location:
            return {"market": market, "forecast": None, "signal": None}
        
        forecasts = self.weather.get_temperature_forecast(location)
        if not forecasts:
            return {"market": market, "forecast": None, "signal": None}
        
        # Find relevant forecast
        forecast = None
        for f in forecasts:
            if market.target_date and f.date == market.target_date:
                forecast = f
                break
        
        if not forecast and forecasts:
            forecast = forecasts[0]
        
        # Generate signal
        signal = self._evaluate_market(market, forecast) if forecast else None
        
        return {
            "market": market,
            "forecast": forecast,
            "signal": signal,
        }


def scan_weather_markets():
    """Quick CLI function to scan markets."""
    import json
    
    logging.basicConfig(level=logging.INFO)
    
    engine = WeatherSignalEngine()
    signals = engine.scan_for_signals()
    
    print(f"\n{'='*60}")
    print(f"WEATHER TRADING SIGNALS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")
    
    if not signals:
        print("No signals meeting criteria found.")
        return
    
    for signal in signals[:10]:
        print(signal.to_alert())
        print("-" * 40)
    
    print(f"\nTotal signals: {len(signals)}")


if __name__ == "__main__":
    scan_weather_markets()
