"""
Configuration for Kalshi Weather Trader
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    # Kalshi API (updated Feb 2026 - migrated to elections subdomain)
    kalshi_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_demo_url: str = "https://demo-api.kalshi.co/trade-api/v2"  # Demo may be deprecated
    kalshi_email: Optional[str] = None
    kalshi_password: Optional[str] = None
    kalshi_api_key: Optional[str] = None
    use_demo: bool = False  # Use production API (read-only works without auth)
    
    # Weather APIs (all free, no key needed)
    nws_api_url: str = "https://api.weather.gov"
    open_meteo_url: str = "https://api.open-meteo.com/v1"
    
    # Database
    db_path: Path = field(default_factory=lambda: Path.home() / "kalshi-weather-trader" / "data" / "weather.db")
    
    # Trading thresholds
    min_edge_pct: float = 0.08  # 8% minimum edge to trade
    min_confidence: float = 0.60  # 60% confidence minimum
    max_position_size: float = 500  # $500 max per market
    
    # Kelly sizing
    kelly_fraction: float = 0.20  # 20% Kelly (conservative)
    
    # Signal settings
    signal_cooldown_hours: int = 6  # Don't re-signal same market
    forecast_staleness_hours: int = 3  # Refetch if older
    
    # Risk management
    max_daily_loss: float = 200  # Stop if down $200/day
    max_open_positions: int = 10
    
    # Notifications
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    # Cities to track (major cities with Kalshi weather markets)
    tracked_cities: list = field(default_factory=lambda: [
        {"name": "New York", "lat": 40.7128, "lon": -74.0060, "nws_office": "OKX"},
        {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437, "nws_office": "LOX"},
        {"name": "Chicago", "lat": 41.8781, "lon": -87.6298, "nws_office": "LOT"},
        {"name": "Houston", "lat": 29.7604, "lon": -95.3698, "nws_office": "HGX"},
        {"name": "Phoenix", "lat": 33.4484, "lon": -112.0740, "nws_office": "PSR"},
        {"name": "Miami", "lat": 25.7617, "lon": -80.1918, "nws_office": "MFL"},
        {"name": "Denver", "lat": 39.7392, "lon": -104.9903, "nws_office": "BOU"},
        {"name": "Seattle", "lat": 47.6062, "lon": -122.3321, "nws_office": "SEW"},
        {"name": "Atlanta", "lat": 33.7490, "lon": -84.3880, "nws_office": "FFC"},
        {"name": "Boston", "lat": 42.3601, "lon": -71.0589, "nws_office": "BOX"},
    ])
    
    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            kalshi_email=os.getenv("KALSHI_EMAIL"),
            kalshi_password=os.getenv("KALSHI_PASSWORD"),
            kalshi_api_key=os.getenv("KALSHI_API_KEY"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            use_demo=os.getenv("KALSHI_USE_DEMO", "false").lower() == "true",
        )


config = Config.from_env()
