"""Polite fetcher: robots.txt, >=2s per-host rate limit, identifying User-Agent, disk cache."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings


class Robots:
    """Google-style robots.txt: `*` and `$` wildcards, longest matching rule wins, Allow wins ties."""

    def __init__(self, text: str, agent: str) -> None:
        token = agent.split("/")[0].strip().lower()
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        last_was_agent = False
        for line in text.splitlines():
            line = line.split("#")[0].strip()
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if not last_was_agent:
                    agents, rules = [], []
                    groups.append((agents, rules))
                agents.append(val.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if val:  # an empty Disallow allows everything
                    rules.append((key == "allow", val))
        specific = [r for a, r in groups if any(x != "*" and x in token for x in a)]
        default = [r for a, r in groups if "*" in a]
        self.rules = [x for r in (specific or default) for x in r]

    @staticmethod
    def _match_len(pattern: str, path: str) -> int:
        """Length of `pattern` if it matches the start of `path`, else -1."""
        regex = re.escape(pattern).replace(r"\*", ".*")
        if regex.endswith(r"\$"):
            regex = regex[:-2] + "$"
        return len(pattern) if re.match(regex, path) else -1

    def can_fetch(self, url: str) -> bool:
        p = urlparse(url)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best_len, allowed = -1, True
        for allow, pattern in self.rules:
            n = self._match_len(pattern, path)
            if n > best_len or (n == best_len and allow):
                best_len, allowed = n, allow
        return allowed


class PoliteFetcher:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or settings.data_dir / "jobs" / "raw"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, Robots | None] = {}
        self._client = httpx.Client(
            headers={"User-Agent": settings.scraper_user_agent}, timeout=20, follow_redirects=True
        )

    def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            try:
                self._wait(p.netloc)
                resp = self._client.get(f"{origin}/robots.txt")
                if resp.status_code == 200:
                    rp = Robots(resp.text, settings.scraper_user_agent)
                elif resp.status_code in (401, 403):
                    rp = Robots("User-agent: *\nDisallow: /", settings.scraper_user_agent)
                else:  # no robots.txt -> everything allowed
                    rp = Robots("", settings.scraper_user_agent)
                self._robots[origin] = rp
            except httpx.HTTPError:
                self._robots[origin] = None  # cannot verify -> be conservative
        rp = self._robots[origin]
        return rp is not None and rp.can_fetch(url)

    def _wait(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < settings.scraper_min_delay_s:
            time.sleep(settings.scraper_min_delay_s - elapsed)
        self._last_request[host] = time.monotonic()

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".txt")

    def get(self, url: str, use_cache: bool = True) -> str | None:
        """Return response text, or None if disallowed by robots.txt / request failed."""
        cache = self._cache_path(url)
        if use_cache and cache.exists():
            return cache.read_text(encoding="utf-8")
        if not self._allowed(url):
            return None
        self._wait(urlparse(url).netloc)
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        cache.write_text(resp.text, encoding="utf-8")
        return resp.text

    def post_json(self, url: str, payload: dict, use_cache: bool = True) -> str | None:
        """POST a JSON body (no query string needed). Same robots/delay/cache path as `get`."""
        key = url + json.dumps(payload, sort_keys=True)
        cache = self._cache_path(key)
        if use_cache and cache.exists():
            return cache.read_text(encoding="utf-8")
        if not self._allowed(url):
            return None
        self._wait(urlparse(url).netloc)
        try:
            resp = self._client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        cache.write_text(resp.text, encoding="utf-8")
        return resp.text
