"""Robots.txt helper."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsChecker:
    def __init__(self, user_agent: str = "apprscan-jobs"):
        self.user_agent = user_agent
        self.cache: dict[str, RobotFileParser] = {}

    def _fetch_parser(self, domain: str) -> RobotFileParser:
        robots_url = f"https://{domain}/robots.txt"
        parser = RobotFileParser()
        try:
            parser.set_url(robots_url)
            parser.read()
        except Exception:
            parser = RobotFileParser()
            parser.parse([])  # allow all
        return parser

    def get_parser(self, domain: str) -> RobotFileParser:
        if domain not in self.cache:
            self.cache[domain] = self._fetch_parser(domain)
        return self.cache[domain]

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        parser = self.get_parser(parsed.netloc)
        return parser.can_fetch(self.user_agent, url)

    def can_fetch_detail(self, url: str) -> tuple[bool, str | None]:
        parsed = urlparse(url)
        parser = self.get_parser(parsed.netloc)
        disallow_all = getattr(parser, "disallow_all", False)
        if disallow_all:
            return False, "Disallow: /"
        allowed = parser.can_fetch(self.user_agent, url)
        if not allowed:
            return False, "blocked_by_robots"
        return True, None
