"""
Kalshi API client for market data and trading.
"""
import logging
import re
from datetime import datetime, date
from typing import Optional, List, Dict
import requests

from ..config import config
from ..models.weather import KalshiMarket, WeatherMetric, Location

logger = logging.getLogger(__name__)


class KalshiClient:
    """
    Kalshi Exchange API client.
    
    Handles both demo and production environments.
    """
    
    def __init__(self, use_demo: bool = None):
        self.use_demo = use_demo if use_demo is not None else config.use_demo
        self.base_url = config.kalshi_demo_url if self.use_demo else config.kalshi_api_url
        
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
    
    def authenticate(self, email: str = None, password: str = None) -> bool:
        """
        Authenticate with Kalshi API.
        
        For demo: No auth needed for read-only
        For production: Required for trading
        """
        email = email or config.kalshi_email
        password = password or config.kalshi_password
        
        if not email or not password:
            logger.warning("No credentials provided, using unauthenticated access")
            return False
        
        try:
            resp = self.session.post(
                f"{self.base_url}/login",
                json={"email": email, "password": password},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            self._token = data.get("token")
            self.session.headers["Authorization"] = f"Bearer {self._token}"
            
            logger.info("Kalshi authentication successful")
            return True
            
        except Exception as e:
            logger.error(f"Kalshi auth failed: {e}")
            return False
    
    def get_events(
        self,
        status: str = "open",
        category: str = None,
        limit: int = 100
    ) -> List[dict]:
        """Get events (groups of related markets)."""
        try:
            params = {"limit": limit, "status": status}
            if category:
                params["category"] = category
            
            resp = self.session.get(
                f"{self.base_url}/events",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            return resp.json().get("events", [])
            
        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return []
    
    def get_markets(
        self,
        event_ticker: str = None,
        status: str = "active",
        limit: int = 100
    ) -> List[KalshiMarket]:
        """Get markets with parsed weather data."""
        try:
            params = {"limit": limit, "status": status}
            if event_ticker:
                params["event_ticker"] = event_ticker
            
            resp = self.session.get(
                f"{self.base_url}/markets",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            
            markets = []
            for m in data.get("markets", []):
                market = self._parse_market(m)
                if market:
                    markets.append(market)
            
            return markets
            
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []
    
    def get_weather_markets(self) -> List[KalshiMarket]:
        """Get all active weather-related markets."""
        # First get weather events
        events = self.get_events(category="Climate and Weather")
        
        weather_markets = []
        for event in events:
            ticker = event.get("event_ticker")
            if ticker:
                markets = self.get_markets(event_ticker=ticker)
                weather_markets.extend(markets)
        
        # Also search by title patterns
        all_markets = self.get_markets(limit=500)
        for market in all_markets:
            if market.is_weather and market not in weather_markets:
                weather_markets.append(market)
        
        return weather_markets
    
    def get_market(self, ticker: str) -> Optional[KalshiMarket]:
        """Get a specific market by ticker."""
        try:
            resp = self.session.get(
                f"{self.base_url}/markets/{ticker}",
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json().get("market", {})
            return self._parse_market(data)
            
        except Exception as e:
            logger.error(f"Error fetching market {ticker}: {e}")
            return None
    
    def get_orderbook(self, ticker: str) -> Optional[dict]:
        """Get orderbook for a market."""
        try:
            resp = self.session.get(
                f"{self.base_url}/markets/{ticker}/orderbook",
                timeout=10
            )
            resp.raise_for_status()
            return resp.json().get("orderbook", {})
            
        except Exception as e:
            logger.error(f"Error fetching orderbook for {ticker}: {e}")
            return None
    
    def place_order(
        self,
        ticker: str,
        side: str,  # "yes" or "no"
        count: int,  # Number of contracts
        price: int,  # Price in cents (1-99)
        order_type: str = "limit"
    ) -> Optional[dict]:
        """
        Place an order on Kalshi.
        
        Requires authentication.
        """
        if not self._token:
            logger.error("Must be authenticated to place orders")
            return None
        
        try:
            payload = {
                "ticker": ticker,
                "action": "buy",
                "side": side,
                "count": count,
                "type": order_type,
            }
            
            if order_type == "limit":
                payload["yes_price" if side == "yes" else "no_price"] = price
            
            resp = self.session.post(
                f"{self.base_url}/portfolio/orders",
                json=payload,
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def get_positions(self) -> List[dict]:
        """Get current positions (requires auth)."""
        if not self._token:
            return []
        
        try:
            resp = self.session.get(
                f"{self.base_url}/portfolio/positions",
                timeout=10
            )
            resp.raise_for_status()
            return resp.json().get("market_positions", [])
            
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def get_balance(self) -> Optional[float]:
        """Get account balance (requires auth)."""
        if not self._token:
            return None
        
        try:
            resp = self.session.get(
                f"{self.base_url}/portfolio/balance",
                timeout=10
            )
            resp.raise_for_status()
            return resp.json().get("balance", 0) / 100  # Convert cents to dollars
            
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return None
    
    def _parse_market(self, data: dict) -> Optional[KalshiMarket]:
        """Parse raw market data into KalshiMarket object."""
        try:
            ticker = data.get("ticker", "")
            title = data.get("title", "")
            
            market = KalshiMarket(
                ticker=ticker,
                title=title,
                event_ticker=data.get("event_ticker", ""),
                category=self._infer_category(data),
                yes_bid=data.get("yes_bid", 0),
                yes_ask=data.get("yes_ask", 0),
                last_price=data.get("last_price", 0),
                volume=data.get("volume", 0),
                open_interest=data.get("open_interest", 0),
                liquidity=data.get("liquidity", 0),
                close_time=self._parse_time(data.get("close_time")),
                expiration_time=self._parse_time(data.get("expiration_time")),
                status=data.get("status", "unknown"),
                result=data.get("result"),
            )
            
            # Parse weather-specific info from title
            self._parse_weather_info(market)
            
            return market
            
        except Exception as e:
            logger.debug(f"Error parsing market: {e}")
            return None
    
    def _parse_weather_info(self, market: KalshiMarket):
        """Extract weather metric, threshold, location from market title."""
        title = market.title.lower()
        
        # Temperature patterns
        # "Will the high temperature in NYC be above 80°F on Feb 5?"
        # "NYC high temp above 75°F"
        
        temp_match = re.search(
            r'(high|low)\s*(temp|temperature).*?(\d+)\s*°?\s*f',
            title,
            re.IGNORECASE
        )
        
        if temp_match:
            temp_type = temp_match.group(1).lower()
            threshold = float(temp_match.group(3))
            
            market.metric = WeatherMetric.HIGH_TEMP if temp_type == "high" else WeatherMetric.LOW_TEMP
            market.threshold = threshold
            
            # Try to extract location
            for city in config.tracked_cities:
                if city["name"].lower() in title or city["name"][:3].lower() in title:
                    market.location = city["name"]
                    break
            
            # Try to extract date
            date_match = re.search(r'(\w+)\s+(\d{1,2})', title)
            if date_match:
                try:
                    month_str = date_match.group(1)
                    day = int(date_match.group(2))
                    # Parse month
                    months = {
                        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                        'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                        'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                    }
                    month = months.get(month_str[:3].lower())
                    if month:
                        year = datetime.now().year
                        market.target_date = date(year, month, day)
                except:
                    pass
        
        # Precipitation patterns
        precip_match = re.search(
            r'(rain|precip|precipitation|snow).*?(\d+\.?\d*)\s*(inch|in|")',
            title,
            re.IGNORECASE
        )
        
        if precip_match:
            market.metric = WeatherMetric.PRECIPITATION
            market.threshold = float(precip_match.group(2))
    
    def _infer_category(self, data: dict) -> str:
        """Infer category from market data."""
        title = data.get("title", "").lower()
        event_ticker = data.get("event_ticker", "").upper()
        
        if any(x in title for x in ["temperature", "temp", "weather", "rain", "snow", "hurricane"]):
            return "Climate and Weather"
        if any(x in event_ticker for x in ["TEMP", "WEATHER", "RAIN", "SNOW"]):
            return "Climate and Weather"
        
        return data.get("category", "Unknown")
    
    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """Parse ISO timestamp."""
        if not time_str:
            return None
        try:
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except:
            return None
