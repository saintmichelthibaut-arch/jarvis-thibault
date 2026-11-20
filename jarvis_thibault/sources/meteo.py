"""Météo du jour via Open-Meteo (gratuit, sans clé API)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Tuple

import httpx

_GEO = "https://geocoding-api.open-meteo.com/v1/search"
_PREVI = "https://api.open-meteo.com/v1/forecast"

# Codes météo WMO → (description, icône)
CODES: Dict[int, Tuple[str, str]] = {
    0: ("ciel dégagé", "☀"),
    1: ("plutôt ensoleillé", "🌤"),
    2: ("partiellement nuageux", "⛅"),
    3: ("couvert", "☁"),
    45: ("brouillard", "🌫"),
    48: ("brouillard givrant", "🌫"),
    51: ("bruine légère", "🌦"),
    53: ("bruine", "🌦"),
    55: ("bruine dense", "🌧"),
    56: ("bruine verglaçante", "🌧"),
    57: ("bruine verglaçante", "🌧"),
    61: ("pluie faible", "🌦"),
    63: ("pluie", "🌧"),
    65: ("forte pluie", "🌧"),
    66: ("pluie verglaçante", "🌧"),
    67: ("pluie verglaçante", "🌧"),
    71: ("neige faible", "🌨"),
    73: ("neige", "🌨"),
    75: ("forte neige", "❄"),
    77: ("grains de neige", "🌨"),
    80: ("averses", "🌦"),
    81: ("averses", "🌧"),
    82: ("violentes averses", "⛈"),
    85: ("averses de neige", "🌨"),
    86: ("fortes averses de neige", "❄"),
    95: ("orages", "⛈"),
    96: ("orages avec grêle", "⛈"),
    99: ("orages avec grêle", "⛈"),
}


@lru_cache(maxsize=8)
def _coordonnees(ville: str) -> Tuple[float, float, str]:
    r = httpx.get(_GEO, params={"name": ville, "count": 1, "language": "fr"}, timeout=15)
    r.raise_for_status()
    res = (r.json().get("results") or [])
    if not res:
        raise ValueError(f"Ville introuvable pour la météo : {ville!r}")
    return res[0]["latitude"], res[0]["longitude"], res[0].get("name", ville)


def meteo(cfg) -> Dict[str, Any]:
    if cfg.demo:
        from .demo import meteo_demo

        return meteo_demo()
    lat, lon, nom = _coordonnees(cfg["moi"]["ville"])
    r = httpx.get(
        _PREVI,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
            "weather_code,sunrise,sunset",
            "timezone": cfg["moi"]["fuseau"],
            "forecast_days": 1,
        },
        timeout=15,
    )
    r.raise_for_status()
    j = r.json()
    cur, day = j["current"], j["daily"]
    code = int(day["weather_code"][0])
    desc, icone = CODES.get(code, ("temps variable", "🌡"))
    return {
        "ville": nom,
        "maintenant": round(cur["temperature_2m"]),
        "ressenti": round(cur["apparent_temperature"]),
        "min": round(day["temperature_2m_min"][0]),
        "max": round(day["temperature_2m_max"][0]),
        "pluie_proba": day["precipitation_probability_max"][0],
        "vent_kmh": round(cur["wind_speed_10m"]),
        "description": desc,
        "description_actuelle": CODES.get(int(cur["weather_code"]), (desc,))[0],
        "icone": icone,
        "lever": day["sunrise"][0][-5:],
        "coucher": day["sunset"][0][-5:],
    }
