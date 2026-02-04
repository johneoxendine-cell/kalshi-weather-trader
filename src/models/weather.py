"""
Weather data models and forecast structures.
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List
from enum import Enum


class WeatherMetric(Enum):
    """Types of weather measurements Kalshi trades."""
    HIGH_TEMP = "high_temp"
    LOW_TEMP = "low_temp"
    PRECIPITATION = "precipitation"
    SNOWFALL = "snowfall"
    WIND_SPEED = "wind_speed"
    HURRICANE = "hurricane"


class TemperatureUnit(Enum):
    FAHRENHEIT = "F"
    CELSIUS = "C"


@dataclass
class Location:
    """Geographic location for weather forecasting."""
    name: str
    lat: float
    lon: float
    nws_office: str  # NWS forecast office code
    timezone: str = "America/New_York"
    
    @property
    def nws_point_url(self) -> str:
        return f"https://api.weather.gov/points/{self.lat},{self.lon}"


@dataclass 
class TemperatureForecast:
    """Temperature forecast for a specific date."""
    location: str
    date: date
    
    # Point estimates
    high_temp: float  # Fahrenheit
    low_temp: float
    
    # Ensemble distribution (from multiple model runs)
    high_temp_ensemble: List[float] = field(default_factory=list)
    low_temp_ensemble: List[float] = field(default_factory=list)
    
    # Calculated probabilities
    prob_high_above: dict = field(default_factory=dict)  # {threshold: probability}
    prob_high_below: dict = field(default_factory=dict)
    prob_low_above: dict = field(default_factory=dict)
    prob_low_below: dict = field(default_factory=dict)
    
    # Metadata
    forecast_time: Optional[datetime] = None
    source: str = "NWS"
    confidence: float = 0.8  # Model confidence
    
    def probability_high_above(self, threshold: float) -> float:
        """Probability that high temp exceeds threshold."""
        if not self.high_temp_ensemble:
            # Use point estimate with assumed standard deviation
            import math
            std_dev = 3.0  # Typical forecast uncertainty
            z = (threshold - self.high_temp) / std_dev
            # CDF approximation
            return 0.5 * (1 - math.erf(z / math.sqrt(2)))
        
        # Use ensemble
        above = sum(1 for t in self.high_temp_ensemble if t > threshold)
        return above / len(self.high_temp_ensemble)
    
    def probability_high_below(self, threshold: float) -> float:
        """Probability that high temp is below threshold."""
        return 1 - self.probability_high_above(threshold)
    
    def probability_low_above(self, threshold: float) -> float:
        """Probability that low temp exceeds threshold."""
        if not self.low_temp_ensemble:
            import math
            std_dev = 2.5
            z = (threshold - self.low_temp) / std_dev
            return 0.5 * (1 - math.erf(z / math.sqrt(2)))
        
        above = sum(1 for t in self.low_temp_ensemble if t > threshold)
        return above / len(self.low_temp_ensemble)
    
    def probability_low_below(self, threshold: float) -> float:
        """Probability that low temp is below threshold."""
        return 1 - self.probability_low_above(threshold)


@dataclass
class PrecipitationForecast:
    """Precipitation forecast for a specific date."""
    location: str
    date: date
    
    # Point estimates
    total_inches: float
    probability_of_precip: float  # 0-1
    
    # Ensemble
    precip_ensemble: List[float] = field(default_factory=list)
    
    # Probabilities
    prob_above: dict = field(default_factory=dict)  # {threshold: probability}
    
    forecast_time: Optional[datetime] = None
    source: str = "NWS"
    
    def probability_above_threshold(self, threshold: float) -> float:
        """Probability precip exceeds threshold."""
        if not self.precip_ensemble:
            # Rough estimate using exponential distribution
            if threshold <= 0:
                return self.probability_of_precip
            import math
            # Mean precip given precip occurs
            mean_if_precip = max(0.1, self.total_inches / self.probability_of_precip) if self.probability_of_precip > 0 else 0.1
            return self.probability_of_precip * math.exp(-threshold / mean_if_precip)
        
        above = sum(1 for p in self.precip_ensemble if p > threshold)
        return above / len(self.precip_ensemble)


@dataclass
class WeatherSignal:
    """Trading signal generated from weather forecast vs market price."""
    id: str
    created_at: datetime
    
    # Market info
    market_ticker: str
    market_title: str
    metric: WeatherMetric
    threshold: float
    direction: str  # "above" or "below"
    
    # Location/Time
    location: str
    target_date: date
    
    # Pricing
    market_price: float  # Current Kalshi price (0-1)
    model_probability: float  # Our calculated probability
    edge: float  # model_prob - market_price (if betting YES)
    
    # Recommendation
    recommended_side: str  # "YES" or "NO"
    confidence: float
    suggested_size: float
    
    # Forecast details
    forecast_value: float  # Point estimate
    forecast_source: str
    forecast_time: datetime
    
    @property
    def edge_pct(self) -> float:
        return abs(self.edge) * 100
    
    def to_alert(self) -> str:
        emoji = "🌡️" if "temp" in self.metric.value else "🌧️"
        direction_emoji = "📈" if self.recommended_side == "YES" else "📉"
        
        return f"""{emoji} **WEATHER SIGNAL**

**{self.market_title}**
📍 {self.location} | 📅 {self.target_date}

{direction_emoji} **{self.recommended_side}** @ {self.market_price:.0%}

**Edge:** {self.edge_pct:.1f}%
• Model says: {self.model_probability:.0%}
• Market says: {self.market_price:.0%}
• Forecast: {self.forecast_value:.0f}°F (threshold: {self.threshold:.0f}°F)

**Confidence:** {self.confidence:.0%}
**Suggested size:** ${self.suggested_size:.0f}

Ticker: `{self.market_ticker}`"""


@dataclass
class KalshiMarket:
    """Kalshi market data structure."""
    ticker: str
    title: str
    event_ticker: str
    category: str
    
    # Pricing
    yes_bid: float  # Best bid for YES (0-100 cents)
    yes_ask: float  # Best ask for YES
    last_price: float
    
    # Liquidity
    volume: float
    open_interest: float
    liquidity: float
    
    # Timing
    close_time: datetime
    expiration_time: datetime
    
    # Status
    status: str  # active, closed, settled
    result: Optional[str] = None
    
    # Parsed weather info
    location: Optional[str] = None
    metric: Optional[WeatherMetric] = None
    threshold: Optional[float] = None
    target_date: Optional[date] = None
    
    @property
    def yes_mid(self) -> float:
        """Mid price for YES in probability (0-1)."""
        if self.yes_bid and self.yes_ask:
            return (self.yes_bid + self.yes_ask) / 200
        return self.last_price / 100
    
    @property
    def spread(self) -> float:
        """Bid-ask spread in cents."""
        if self.yes_bid and self.yes_ask:
            return self.yes_ask - self.yes_bid
        return 0
    
    @property
    def is_weather(self) -> bool:
        return self.category in ["Climate and Weather", "Weather"]
