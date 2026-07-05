from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; CompetitorSnapshot/1.0; +https://github.com)"
SUBPAGE_KEYWORDS = ("pricing", "prices", "plans", "features", "product")
MAX_CHARS = 8000


class ScrapeError(Exception):
    pass


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status()
    return resp.text


def extract_text(html: str) -> str:
    return trafilatura.extract(html, include_comments=False, include_tables=True) or ""


def find_subpages(html: str, base_url: str, limit: int = 2) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(base_url).netloc
    picked: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base_url, href.split("#")[0])
        if urlparse(full).netloc != domain or full.rstrip("/") == base_url.rstrip("/"):
            continue
        haystack = f"{href.lower()} {a.get_text(' ', strip=True).lower()}"
        for kw in SUBPAGE_KEYWORDS:
            if kw in haystack:
                picked.setdefault(kw, full)
                break
    ordered: list[str] = []
    for group in (("pricing", "prices", "plans"), ("features", "product")):
        for kw in group:
            if kw in picked and picked[kw] not in ordered:
                ordered.append(picked[kw])
                break
    return ordered[:limit]


def scrape_site(url: str) -> dict:
    try:
        home_html = fetch(url)
    except Exception as err:
        raise ScrapeError(f"{url}: could not fetch homepage ({err})") from err

    texts, pages = [extract_text(home_html)], [url]
    for sub in find_subpages(home_html, url):
        try:
            texts.append(extract_text(fetch(sub)))
            pages.append(sub)
        except Exception:
            continue

    combined = "\n\n".join(t for t in texts if t).strip()
    if len(combined) < 200:
        raise ScrapeError(
            f"{url}: extracted only {len(combined)} chars — the site is likely "
            "JavaScript-rendered or blocking scrapers"
        )
    return {"url": url, "pages": pages, "text": combined[:MAX_CHARS]}
