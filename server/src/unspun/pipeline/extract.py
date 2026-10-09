"""Article body extraction."""

from html.parser import HTMLParser

import trafilatura


def extract_content(html: str, url: str | None = None) -> str | None:
    return trafilatura.extract(html, url=url, include_comments=False)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_tags(html: str) -> str:
    """Fallback for feed summaries when full-page extraction fails."""
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())
