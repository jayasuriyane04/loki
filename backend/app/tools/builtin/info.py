"""Information tools: date/time, weather (Open-Meteo), web search (SearXNG), website reading (SSRF-safe)."""

import asyncio
import ipaddress
import socket
from datetime import datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import Field

from app.knowledge.extract import _HTMLText
from app.tools.base import ToolContext, ToolError, ToolInput, ToolResult, untrusted
from app.tools.registry import tool

UA = "LOKI-personal-assistant/0.5 (+local)"


class DateTimeIn(ToolInput):
    timezone: str | None = Field(None, description="IANA timezone, e.g. 'Europe/London'. Omit for the user's own.")


@tool("get_datetime", "Current date and time, in the user's timezone or another IANA timezone.", DateTimeIn,
      permission="read", category="information")
async def get_datetime(ctx: ToolContext, a: DateTimeIn) -> ToolResult:
    try:
        tz = ZoneInfo(a.timezone) if a.timezone else ctx.tz
    except ZoneInfoNotFoundError as e:
        raise ToolError(f"Unknown timezone {a.timezone!r}.") from e
    now = datetime.now(tz)
    text = f"{now:%A %d %B %Y, %H:%M} ({tz.key}, UTC{now:%z})"
    return ToolResult(text, f"Checked the time: {text}")


WEATHER_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog", 51: "light drizzle",
    53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "heavy freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
    81: "heavy rain showers", 82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


class WeatherIn(ToolInput):
    location: str = Field(min_length=2, max_length=100, description="City or place name, e.g. 'Chennai'")


@tool("get_weather", "Current weather and a 3-day forecast for a place (Open-Meteo).", WeatherIn,
      permission="read", category="information", timeout_s=15)
async def get_weather(ctx: ToolContext, a: WeatherIn) -> ToolResult:
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}) as c:
        geo = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                           params={"name": a.location, "count": 1, "format": "json"})).json()
        if not geo.get("results"):
            raise ToolError(f"Couldn't find a place called {a.location!r}.")
        p = geo["results"][0]
        w = (await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": p["latitude"], "longitude": p["longitude"], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
        })).json()
    cur, daily = w["current"], w["daily"]
    place = ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country")) if x)
    lines = [
        f"Weather for {place} (local time {cur['time']}):",
        f"Now: {WEATHER_CODES.get(cur['weather_code'], 'unknown')}, {cur['temperature_2m']}°C "
        f"(feels {cur['apparent_temperature']}°C), humidity {cur['relative_humidity_2m']}%, "
        f"wind {cur['wind_speed_10m']} km/h, precipitation {cur['precipitation']} mm.",
    ]
    for i, day in enumerate(daily["time"]):
        lines.append(
            f"{day}: {WEATHER_CODES.get(daily['weather_code'][i], 'unknown')}, {daily['temperature_2m_min'][i]}–"
            f"{daily['temperature_2m_max'][i]}°C, rain chance {daily['precipitation_probability_max'][i]}%, "
            f"{daily['precipitation_sum'][i]} mm"
        )
    text = "\n".join(lines)
    return ToolResult(text, f"Weather for {place}: {WEATHER_CODES.get(cur['weather_code'], '?')}, {cur['temperature_2m']}°C",
                      {"place": place, "current": cur})


class SearchIn(ToolInput):
    query: str = Field(min_length=2, max_length=300)
    max_results: int = Field(6, ge=1, le=10)


@tool("web_search", "Search the web for current information. Returns titles, URLs and snippets; use read_webpage "
      "to read a result in full.", SearchIn, permission="read", category="information", timeout_s=20)
async def web_search(ctx: ToolContext, a: SearchIn) -> ToolResult:
    base = ctx.settings.searxng_url
    if not base:
        raise ToolError("Web search is not configured.")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{base.rstrip('/')}/search", params={"q": a.query, "format": "json", "safesearch": 1})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise ToolError(f"Web search is unavailable ({type(e).__name__}). Is the searxng container running?") from e
    seen, results = set(), []
    for item in data.get("results", []):
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        results.append({"title": item.get("title", "")[:200], "url": url,
                        "snippet": (item.get("content") or "")[:400], "date": item.get("publishedDate")})
        if len(results) >= a.max_results:
            break
    if not results:
        return ToolResult(f"No web results for {a.query!r}.", f"Searched the web for “{a.query}”: no results")
    body = "\n".join(
        f"[{i}] {x['title']}\n    {x['url']}" + (f"\n    {x['date'][:10]}" if x["date"] else "") + f"\n    {x['snippet']}"
        for i, x in enumerate(results, start=1)
    )
    return ToolResult(untrusted(f"web search: {a.query}", body), f"Searched the web for “{a.query}” ({len(results)} results)",
                      {"results": results})


class ReadPageIn(ToolInput):
    url: str = Field(max_length=2000, description="http(s) URL")
    max_chars: int = Field(8000, ge=500, le=20000)


def _check_public(url: str) -> None:
    """Refuse non-http(s) URLs and anything resolving to a private/loopback/link-local address (SSRF)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ToolError("Only public http(s) URLs can be read.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ToolError(f"Couldn't resolve {p.hostname}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ToolError("That address is on a private or local network; LOKI only reads public websites.")


@tool("read_webpage", "Fetch a public web page and return its readable text.", ReadPageIn,
      permission="read", category="information", timeout_s=25)
async def read_webpage(ctx: ToolContext, a: ReadPageIn) -> ToolResult:
    url = a.url
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": UA}) as c:
        for _ in range(5):  # follow redirects manually so every hop is checked
            await asyncio.to_thread(_check_public, url)
            async with c.stream("GET", url) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise ToolError(f"The page returned HTTP {r.status_code}.")
                ctype = r.headers.get("content-type", "")
                if not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml", "text/markdown")):
                    raise ToolError(f"Not a text page ({ctype or 'unknown type'}).")
                raw = b""
                async for chunk in r.aiter_bytes():
                    raw += chunk
                    if len(raw) > 2_000_000:
                        break
                text = raw.decode(r.encoding or "utf-8", errors="replace")
                break
        else:
            raise ToolError("Too many redirects.")
    title = ""
    if "html" in ctype:
        parser = _HTMLText()
        parser.feed(text)
        title = parser.title.strip()
        text = "".join(parser.out)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    clipped = text[: a.max_chars]
    note = "" if len(text) <= a.max_chars else f"\n[truncated: {len(text) - a.max_chars} more characters]"
    return ToolResult(untrusted(url, f"{title}\n\n{clipped}{note}" if title else clipped + note),
                      f"Read {urlparse(url).hostname}" + (f": {title[:80]}" if title else ""),
                      {"url": url, "title": title, "chars": len(text)})
