"""Weather from Open-Meteo: no key, no account, one request per widget."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

API = "https://api.open-meteo.com/v1/forecast"

#: WMO weather codes grouped into the handful of conditions the card draws.
CONDITIONS: dict[int, str] = {
    0: "clear", 1: "mostly-clear", 2: "partly-cloudy", 3: "overcast",
    45: "fog", 48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "showers", 81: "showers", 82: "showers",
    85: "snow", 86: "snow",
    95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm",
}


class WeatherAdapter(Adapter):
    kind = "weather"
    label = "Weather"
    category = "basics"
    description = "Current conditions and a five-day forecast from Open-Meteo."
    icon = "open-meteo"
    beta = False
    needs_integration = False
    docs_url = "https://open-meteo.com/en/docs"
    widgets = (
        WidgetType(
            kind="current",
            label="Weather",
            description="Temperature, condition and the next days.",
            renderer="weather",
            default_size=(3, 2),
            refresh_seconds=900,
            metrics=("temperature",),
            options=(
                Field("latitude", "Latitude", type="number", required=True, placeholder="52.52"),
                Field("longitude", "Longitude", type="number", required=True, placeholder="13.41"),
                Field("place", "Place name", placeholder="Berlin"),
                Field("units", "Units", type="select", default="metric", options=(("metric", "Celsius, km/h"), ("imperial", "Fahrenheit, mph"))),
                Field("days", "Forecast days", type="number", default=5),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        try:
            latitude = float(options.get("latitude"))
            longitude = float(options.get("longitude"))
        except (TypeError, ValueError) as error:
            raise AdapterError("Latitude and longitude are missing.", code="missing_location",
                               hint="Open the widget settings and pick a place.") from error
        imperial = options.get("units") == "imperial"
        days = max(1, min(7, int(options.get("days") or 5)))
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": days,
        }
        if imperial:
            params.update({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"})
        payload = await ctx.get_json(API, params=params, cache_seconds=300)
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        unit = "°F" if imperial else "°C"
        items = []
        for index, day in enumerate(daily.get("time") or []):
            items.append({
                "date": day,
                "condition": CONDITIONS.get(int((daily.get("weather_code") or [0])[index] or 0), "overcast"),
                "high": (daily.get("temperature_2m_max") or [None])[index],
                "low": (daily.get("temperature_2m_min") or [None])[index],
                "rain": (daily.get("precipitation_probability_max") or [None])[index],
            })
        temperature = current.get("temperature_2m")
        return WidgetData(
            primary={"label": options.get("place") or "", "value": temperature, "unit": unit},
            secondary=[
                {"label": "Feels like", "value": current.get("apparent_temperature"), "unit": unit},
                {"label": "Humidity", "value": current.get("relative_humidity_2m"), "unit": "%"},
                {"label": "Wind", "value": current.get("wind_speed_10m"), "unit": "mph" if imperial else "km/h"},
            ],
            items=items,
            metrics={"temperature": float(temperature)} if isinstance(temperature, (int, float)) else {},
            meta={
                "condition": CONDITIONS.get(int(current.get("weather_code") or 0), "overcast"),
                "is_day": bool(current.get("is_day", 1)),
                "place": options.get("place") or "",
            },
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        temperature = fake.walk("weather-temp", tick, 14, 27, period=400)
        conditions = ["clear", "partly-cloudy", "overcast", "showers", "rain", "clear", "mostly-clear"]
        items = []
        for offset in range(5):
            items.append({
                "date": f"2026-09-{5 + offset:02d}",
                "condition": conditions[(offset + tick // 200) % len(conditions)],
                "high": round(temperature + 3 + offset * 0.4, 1),
                "low": round(temperature - 6 - offset * 0.3, 1),
                "rain": int(fake.walk(f"rain{offset}", tick, 0, 80, period=300)),
            })
        return WidgetData(
            primary={"label": options.get("place") or "Springfield", "value": temperature, "unit": "°C"},
            secondary=[
                {"label": "Feels like", "value": round(temperature - 1.2, 1), "unit": "°C"},
                {"label": "Humidity", "value": int(fake.walk("humidity", tick, 40, 80)), "unit": "%"},
                {"label": "Wind", "value": fake.walk("wind", tick, 4, 28), "unit": "km/h"},
            ],
            items=items,
            metrics={"temperature": temperature},
            meta={"condition": fake.pick("condition", tick, conditions, every=120), "is_day": True, "place": options.get("place") or "Springfield"},
        )


ADAPTER = WeatherAdapter()
