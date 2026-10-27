"""Weather from Open-Meteo: no key, no account, one request per widget.

A place name is enough: Open-Meteo's geocoder turns a town or a postcode into
coordinates, looked up once a day. Latitude and longitude stay available for
anyone who wants a precise spot.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

API = "https://api.open-meteo.com/v1/forecast"
GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
AIR_QUALITY = "https://air-quality-api.open-meteo.com/v1/air-quality"

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


#: Pollen kinds the air-quality API knows, in the order the card names them.
POLLEN = ("alder", "birch", "grass", "mugwort", "olive", "ragweed")


def _band(value: float, limits: tuple[float, ...], names: tuple[str, ...]) -> str:
    """The name of the first band whose upper limit the value does not pass."""
    for limit, name in zip(limits, names, strict=False):
        if value <= limit:
            return name
    return names[-1]


def aqi_level(value: float) -> str:
    """European AQI in the six bands the EEA publishes (up to 20, 40, 60, 80, 100)."""
    return _band(value, (20, 40, 60, 80, 100), ("good", "fair", "moderate", "poor", "very-poor", "extremely-poor"))


def uv_level(value: float) -> str:
    """UV index in the WHO bands: below 3 low, 3 to 5 moderate, 6 and 7 high, 8 to 10 very high, from 11 extreme."""
    return _band(value, (2.9, 5.9, 7.9, 10.9), ("low", "moderate", "high", "very-high", "extreme"))


def pollen_level(grains: float) -> str:
    """Grains per cubic metre in rough bands.

    Open-Meteo publishes no bands for pollen and each kind has its own, so
    these are one middle for all of them: they say whether to look at the
    number, not what to take it for.
    """
    if grains <= 0:
        return "none"
    return _band(grains, (9.9, 49.9, 199.9), ("low", "moderate", "high", "very-high"))


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _hours(options: dict[str, Any]) -> int:
    """12 or 24 hours of the strip, 0 for none; anything else is none."""
    try:
        hours = int(options.get("hours") or 0)
    except (TypeError, ValueError):
        return 0
    return hours if hours in (12, 24) else 0


def hourly_strip(payload: dict[str, Any], hours: int) -> dict[str, Any] | None:
    """The next ``hours`` hours with their sunrises and sunsets, on the place's own clock.

    ⚠️ The times arrive as written on the place's wall (``timezone=auto``),
    with no offset. They are cut and compared as text and never turned into
    a ``datetime``: this server's clock, or the viewer's, is not the place's.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    now = str((payload.get("current") or {}).get("time") or "")[:13]
    start = next((i for i, at in enumerate(times) if str(at)[:13] >= now), 0)
    temperatures, rain = hourly.get("temperature_2m") or [], hourly.get("precipitation_probability") or []
    day, codes = hourly.get("is_day") or [], hourly.get("weather_code") or []

    def at(series: list[Any], index: int) -> Any:
        return series[index] if index < len(series) else None

    rows = []
    for index in range(start, min(len(times), start + hours)):
        code = at(codes, index)
        rows.append({
            "at": str(times[index]),
            "temperature": _number(at(temperatures, index)),
            "rain": _number(at(rain, index)),
            "night": at(day, index) == 0,
            "condition": CONDITIONS.get(int(code), "overcast") if isinstance(code, (int, float)) else "overcast",
        })
    sun = []
    daily = payload.get("daily") or {}
    for kind in ("sunrise", "sunset"):
        for moment in daily.get(kind) or []:
            for position, row in enumerate(rows):
                if str(moment)[:13] == row["at"][:13]:
                    sun.append({"index": position, "kind": kind, "time": str(moment)[11:16]})
    sun.sort(key=lambda event: event["index"])
    return {"hours": len(rows), "items": rows, "sun": sun} if rows else None


def air_summary(payload: dict[str, Any], *, aqi: bool, uv: bool, pollen: bool, uv_peak: float | None) -> dict[str, Any]:
    """Air quality, UV and pollen from the air-quality API's ``current`` block.

    A value the API leaves out is left out here. Pollen is modelled for Europe
    only: elsewhere every kind comes back as ``null``, and then the card has no
    pollen to show and says nothing about it. In Europe out of season they are
    all ``0.0``, which is an answer ("none"), not a gap.
    """
    current = payload.get("current") or {}
    found: dict[str, Any] = {}
    value = _number(current.get("european_aqi"))
    if aqi and value is not None:
        found["aqi"] = {"value": round(value), "level": aqi_level(value)}
    value = _number(current.get("uv_index"))
    if uv and value is not None:
        found["uv"] = {"value": round(value, 1), "level": uv_level(value), "peak": None if uv_peak is None else round(uv_peak, 1)}
    if pollen:
        known = {kind: amount for kind in POLLEN if (amount := _number(current.get(f"{kind}_pollen"))) is not None}
        if known:
            present = sorted(((kind, amount) for kind, amount in known.items() if amount > 0), key=lambda pair: -pair[1])
            found["pollen"] = {
                "level": pollen_level(present[0][1]) if present else "none",
                "items": [{"kind": kind, "value": round(amount), "level": pollen_level(amount)} for kind, amount in present[:3]],
            }
    return found


def _coordinates(options: dict[str, Any]) -> tuple[float, float] | None:
    try:
        return float(options.get("latitude")), float(options.get("longitude"))
    except (TypeError, ValueError):
        return None


class WeatherAdapter(Adapter):
    kind = "weather"
    label = "Weather"
    category = "basics"
    description = "Current conditions and a five-day forecast from Open-Meteo."
    icon = "lucide:cloud-sun"
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
                Field("place", "Place", placeholder="Berlin", help="A town, a postcode or a place name; the coordinates are looked up. Fill in latitude and longitude instead to be exact."),
                Field("latitude", "Latitude", type="number", placeholder="52.52"),
                Field("longitude", "Longitude", type="number", placeholder="13.41"),
                Field("units", "Units", type="select", default="metric", options=(("metric", "Celsius, km/h"), ("imperial", "Fahrenheit, mph"))),
                Field("days", "Forecast days", type="number", default=5),
                Field("hours", "Hourly strip", type="select", default="0", options=(("0", "Off"), ("12", "Next 12 hours"), ("24", "Next 24 hours")),
                      help="Temperature, chance of rain, night hours, sunrise and sunset, hour by hour. Give the card more height."),
                Field("aqi", "Air quality", type="bool", default=False, help="The European air quality index of the place."),
                Field("uv", "UV index", type="bool", default=False, help="The UV index now and the peak of the day."),
                Field("pollen", "Pollen", type="bool", default=False, help="Only for places in Europe; elsewhere nothing is shown."),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def _geocode(self, place: str, ctx: Context) -> tuple[float, float]:
        payload = await ctx.get_json(GEOCODING, params={"name": place, "count": 1, "language": "en", "format": "json"}, cache_seconds=86400)
        results = payload.get("results") or []
        if not results:
            raise AdapterError(
                f"The place {place!r} could not be found.", code="place_not_found",
                hint="Try the town name alone, or fill in latitude and longitude.",
            )
        return float(results[0]["latitude"]), float(results[0]["longitude"])

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        place = str(options.get("place") or "").strip()
        coordinates = _coordinates(options)
        if coordinates is None:
            if not place:
                raise AdapterError("A place or coordinates are missing.", code="missing_location",
                                   hint="Open the widget settings and enter a town, or latitude and longitude.")
            coordinates = await self._geocode(place, ctx)
        latitude, longitude = coordinates
        imperial = options.get("units") == "imperial"
        days = max(1, min(7, int(options.get("days") or 5)))
        strip = _hours(options)
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": days,
        }
        # ⚠️ Only what a card asks for is added, so a card without the new options sends the request it always sent.
        if strip:
            # 24 hours from now can reach into tomorrow but never past it: two days cover it.
            params["forecast_days"] = max(days, 2)
            params["forecast_hours"] = strip
            params["hourly"] = "temperature_2m,precipitation_probability,is_day,weather_code"
            params["daily"] += ",sunrise,sunset"
        if options.get("uv"):
            params["daily"] += ",uv_index_max"
        if imperial:
            params.update({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"})
        payload = await ctx.get_json(API, params=params, cache_seconds=300)
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        unit = "°F" if imperial else "°C"
        items = []
        for index, day in enumerate((daily.get("time") or [])[:days]):
            items.append({
                "date": day,
                "condition": CONDITIONS.get(int((daily.get("weather_code") or [0])[index] or 0), "overcast"),
                "high": (daily.get("temperature_2m_max") or [None])[index],
                "low": (daily.get("temperature_2m_min") or [None])[index],
                "rain": (daily.get("precipitation_probability_max") or [None])[index],
            })
        temperature = current.get("temperature_2m")
        meta: dict[str, Any] = {
            "condition": CONDITIONS.get(int(current.get("weather_code") or 0), "overcast"),
            "is_day": bool(current.get("is_day", 1)),
            "place": place,
        }
        if strip and (hourly := hourly_strip(payload, strip)):
            meta["hourly"] = hourly
        if any(options.get(name) for name in ("aqi", "uv", "pollen")):
            meta.update(await self._air(options, latitude, longitude, (daily.get("uv_index_max") or [None])[0], ctx))
        return WidgetData(
            primary={"label": place, "value": temperature, "unit": unit},
            secondary=[
                {"label": "Feels like", "value": current.get("apparent_temperature"), "unit": unit},
                {"label": "Humidity", "value": current.get("relative_humidity_2m"), "unit": "%"},
                {"label": "Wind", "value": current.get("wind_speed_10m"), "unit": "mph" if imperial else "km/h"},
            ],
            items=items,
            metrics={"temperature": float(temperature)} if isinstance(temperature, (int, float)) else {},
            meta=meta,
        )

    async def _air(self, options: dict[str, Any], latitude: float, longitude: float, uv_peak: Any, ctx: Context) -> dict[str, Any]:
        """The air-quality extras. A second service that fails must not take the weather down with it."""
        asked = [name for name in ("aqi", "uv", "pollen") if options.get(name)]
        fields = [{"aqi": "european_aqi", "uv": "uv_index"}[name] for name in asked if name != "pollen"]
        if "pollen" in asked:
            fields += [f"{kind}_pollen" for kind in POLLEN]
        try:
            payload = await ctx.get_json(AIR_QUALITY, params={"latitude": latitude, "longitude": longitude, "current": ",".join(fields), "timezone": "auto"}, cache_seconds=1800)
        except AdapterError:
            return {"air": {}, "air_unavailable": True}
        return {"air": air_summary(payload, aqi="aqi" in asked, uv="uv" in asked, pollen="pollen" in asked, uv_peak=_number(uv_peak))}

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
            meta=self._demo_meta(options, tick, temperature, conditions),
        )

    def _demo_meta(self, options: dict[str, Any], tick: int, temperature: float, conditions: list[str]) -> dict[str, Any]:
        meta: dict[str, Any] = {"condition": fake.pick("condition", tick, conditions, every=120), "is_day": True, "place": options.get("place") or "Springfield"}
        strip = _hours(options)
        if strip:
            # The sun comes up at seven and goes down at six in the evening, whatever the date.
            first = datetime.now().replace(minute=0, second=0, microsecond=0)
            rows, sun = [], []
            for position in range(strip):
                moment = first + timedelta(hours=position)
                swing = math.cos((moment.hour - 15) / 24 * math.tau)
                rain = int(fake.walk(f"rain-hour{moment.hour}", tick // 50, 0, 90, period=6))
                rows.append({
                    "at": moment.strftime("%Y-%m-%dT%H:00"),
                    "temperature": round(temperature - 1.5 + swing * 4.5, 1),
                    "rain": rain,
                    "night": not 7 <= moment.hour < 18,
                    "condition": "rain" if rain > 60 else "overcast" if rain > 30 else "partly-cloudy",
                })
                if moment.hour == 7:
                    sun.append({"index": position, "kind": "sunrise", "time": "07:12"})
                if moment.hour == 18:
                    sun.append({"index": position, "kind": "sunset", "time": "18:04"})
            meta["hourly"] = {"hours": strip, "items": rows, "sun": sun}
        air: dict[str, Any] = {}
        if options.get("aqi"):
            value = int(fake.walk("aqi", tick, 12, 58, period=500))
            air["aqi"] = {"value": value, "level": aqi_level(value)}
        if options.get("uv"):
            value = round(fake.walk("uv", tick, 0.5, 7.5, period=500), 1)
            air["uv"] = {"value": value, "level": uv_level(value), "peak": 6.8}
        if options.get("pollen"):
            grains = {"birch": int(fake.walk("birch", tick, 4, 180, period=500)), "grass": int(fake.walk("grass", tick, 2, 60, period=500)), "alder": int(fake.walk("alder", tick, 0, 20, period=500))}
            ranked = sorted(grains.items(), key=lambda pair: -pair[1])
            air["pollen"] = {"level": pollen_level(ranked[0][1]), "items": [{"kind": kind, "value": amount, "level": pollen_level(amount)} for kind, amount in ranked if amount > 0]}
        if air:
            meta["air"] = air
        return meta


ADAPTER = WeatherAdapter()
