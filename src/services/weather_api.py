"""
Weather API clients for forecast data.

Sources:
1. NWS (National Weather Service) - Free, official US forecasts
2. Open-Meteo - Free, global ensemble forecasts
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
import requests
import statistics

from ..config import config
from ..models.weather import (
    Location, TemperatureForecast, PrecipitationForecast, WeatherMetric
)

logger = logging.getLogger(__name__)


class NWSClient:
    """
    National Weather Service API client.
    
    Free, no API key needed. Rate limit: ~10 req/sec.
    Docs: https://www.weather.gov/documentation/services-web-api
    """
    
    def __init__(self):
        self.base_url = config.nws_api_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "(KalshiWeatherTrader, contact@example.com)",
            "Accept": "application/geo+json"
        })
        
        # Cache for grid points
        self._grid_cache: Dict[str, dict] = {}
    
    def get_forecast(self, location: Location) -> Optional[List[TemperatureForecast]]:
        """Get 7-day temperature forecast for a location."""
        try:
            # Get grid point
            grid = self._get_grid_point(location)
            if not grid:
                return None
            
            # Fetch forecast
            forecast_url = grid["properties"]["forecast"]
            resp = self.session.get(forecast_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # Parse periods into daily forecasts
            forecasts = []
            periods = data.get("properties", {}).get("periods", [])
            
            # Group by date
            daily = {}
            for period in periods:
                start = datetime.fromisoformat(period["startTime"].replace("Z", "+00:00"))
                day = start.date()
                
                if day not in daily:
                    daily[day] = {"highs": [], "lows": []}
                
                temp = period.get("temperature")
                is_day = period.get("isDaytime", True)
                
                if temp is not None:
                    if is_day:
                        daily[day]["highs"].append(temp)
                    else:
                        daily[day]["lows"].append(temp)
            
            # Create forecast objects
            for day, temps in sorted(daily.items()):
                high = max(temps["highs"]) if temps["highs"] else None
                low = min(temps["lows"]) if temps["lows"] else None
                
                if high is not None and low is not None:
                    forecasts.append(TemperatureForecast(
                        location=location.name,
                        date=day,
                        high_temp=high,
                        low_temp=low,
                        forecast_time=datetime.utcnow(),
                        source="NWS",
                    ))
            
            return forecasts
            
        except Exception as e:
            logger.error(f"NWS forecast error for {location.name}: {e}")
            return None
    
    def _get_grid_point(self, location: Location) -> Optional[dict]:
        """Get NWS grid point for a location."""
        cache_key = f"{location.lat},{location.lon}"
        
        if cache_key in self._grid_cache:
            return self._grid_cache[cache_key]
        
        try:
            url = f"{self.base_url}/points/{location.lat},{location.lon}"
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            self._grid_cache[cache_key] = data
            return data
            
        except Exception as e:
            logger.error(f"NWS grid point error: {e}")
            return None


class OpenMeteoClient:
    """
    Open-Meteo API client for ensemble forecasts.
    
    Free, no API key. Provides ensemble data for probability calculations.
    Docs: https://open-meteo.com/en/docs
    """
    
    def __init__(self):
        self.base_url = config.open_meteo_url
        self.ensemble_url = "https://ensemble-api.open-meteo.com/v1/ensemble"
        self.session = requests.Session()
    
    def get_ensemble_forecast(
        self, 
        location: Location,
        days: int = 7
    ) -> Optional[List[TemperatureForecast]]:
        """
        Get ensemble temperature forecasts.
        
        Uses 51-member ensemble for probability distribution.
        """
        try:
            params = {
                "latitude": location.lat,
                "longitude": location.lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "forecast_days": days,
                "models": "gfs_seamless",  # GFS ensemble
            }
            
            # Try ensemble API first
            resp = self.session.get(self.ensemble_url, params=params, timeout=15)
            
            if resp.status_code != 200:
                # Fall back to regular forecast
                return self._get_regular_forecast(location, days)
            
            data = resp.json()
            daily = data.get("daily", {})
            
            forecasts = []
            dates = daily.get("time", [])
            highs = daily.get("temperature_2m_max", [])
            lows = daily.get("temperature_2m_min", [])
            
            for i, date_str in enumerate(dates):
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
                
                # Handle ensemble (list of lists) or single values
                if isinstance(highs[i], list):
                    high_ensemble = highs[i]
                    low_ensemble = lows[i]
                    high = statistics.mean(high_ensemble)
                    low = statistics.mean(low_ensemble)
                else:
                    high = highs[i]
                    low = lows[i]
                    high_ensemble = []
                    low_ensemble = []
                
                forecasts.append(TemperatureForecast(
                    location=location.name,
                    date=day,
                    high_temp=high,
                    low_temp=low,
                    high_temp_ensemble=high_ensemble,
                    low_temp_ensemble=low_ensemble,
                    forecast_time=datetime.utcnow(),
                    source="Open-Meteo",
                ))
            
            return forecasts
            
        except Exception as e:
            logger.error(f"Open-Meteo error for {location.name}: {e}")
            return None
    
    def _get_regular_forecast(
        self, 
        location: Location, 
        days: int
    ) -> Optional[List[TemperatureForecast]]:
        """Fallback to regular (non-ensemble) forecast."""
        try:
            params = {
                "latitude": location.lat,
                "longitude": location.lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "timezone": "auto",
                "forecast_days": days,
            }
            
            resp = self.session.get(f"{self.base_url}/forecast", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            daily = data.get("daily", {})
            forecasts = []
            
            dates = daily.get("time", [])
            highs = daily.get("temperature_2m_max", [])
            lows = daily.get("temperature_2m_min", [])
            
            for i, date_str in enumerate(dates):
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
                
                forecasts.append(TemperatureForecast(
                    location=location.name,
                    date=day,
                    high_temp=highs[i] if i < len(highs) else 0,
                    low_temp=lows[i] if i < len(lows) else 0,
                    forecast_time=datetime.utcnow(),
                    source="Open-Meteo",
                ))
            
            return forecasts
            
        except Exception as e:
            logger.error(f"Open-Meteo regular forecast error: {e}")
            return None
    
    def get_precipitation_forecast(
        self,
        location: Location,
        days: int = 7
    ) -> Optional[List[PrecipitationForecast]]:
        """Get precipitation forecast."""
        try:
            params = {
                "latitude": location.lat,
                "longitude": location.lon,
                "daily": "precipitation_sum,precipitation_probability_max",
                "precipitation_unit": "inch",
                "timezone": "auto",
                "forecast_days": days,
            }
            
            resp = self.session.get(f"{self.base_url}/forecast", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            daily = data.get("daily", {})
            forecasts = []
            
            dates = daily.get("time", [])
            precip = daily.get("precipitation_sum", [])
            prob = daily.get("precipitation_probability_max", [])
            
            for i, date_str in enumerate(dates):
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
                
                forecasts.append(PrecipitationForecast(
                    location=location.name,
                    date=day,
                    total_inches=precip[i] if i < len(precip) else 0,
                    probability_of_precip=(prob[i] / 100) if i < len(prob) else 0,
                    forecast_time=datetime.utcnow(),
                    source="Open-Meteo",
                ))
            
            return forecasts
            
        except Exception as e:
            logger.error(f"Open-Meteo precip error: {e}")
            return None


class WeatherService:
    """
    Unified weather service combining multiple sources.
    
    Uses NWS as primary (official), Open-Meteo for ensemble data.
    """
    
    def __init__(self):
        self.nws = NWSClient()
        self.open_meteo = OpenMeteoClient()
        self._forecast_cache: Dict[str, tuple] = {}  # (data, timestamp)
    
    def get_temperature_forecast(
        self, 
        location: Location,
        use_ensemble: bool = True
    ) -> Optional[List[TemperatureForecast]]:
        """
        Get temperature forecast, preferring ensemble data.
        """
        cache_key = f"temp_{location.name}"
        
        # Check cache
        if cache_key in self._forecast_cache:
            data, timestamp = self._forecast_cache[cache_key]
            age_hours = (datetime.utcnow() - timestamp).total_seconds() / 3600
            if age_hours < config.forecast_staleness_hours:
                return data
        
        # Try Open-Meteo ensemble first (better for probabilities)
        if use_ensemble:
            forecasts = self.open_meteo.get_ensemble_forecast(location)
            if forecasts:
                self._forecast_cache[cache_key] = (forecasts, datetime.utcnow())
                return forecasts
        
        # Fall back to NWS
        forecasts = self.nws.get_forecast(location)
        if forecasts:
            self._forecast_cache[cache_key] = (forecasts, datetime.utcnow())
        
        return forecasts
    
    def get_precipitation_forecast(
        self,
        location: Location
    ) -> Optional[List[PrecipitationForecast]]:
        """Get precipitation forecast."""
        return self.open_meteo.get_precipitation_forecast(location)
    
    def get_all_forecasts(self) -> Dict[str, List[TemperatureForecast]]:
        """Get forecasts for all tracked cities."""
        results = {}
        
        for city_config in config.tracked_cities:
            location = Location(
                name=city_config["name"],
                lat=city_config["lat"],
                lon=city_config["lon"],
                nws_office=city_config["nws_office"],
            )
            
            forecast = self.get_temperature_forecast(location)
            if forecast:
                results[location.name] = forecast
        
        return results
