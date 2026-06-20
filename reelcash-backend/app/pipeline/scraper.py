"""Step 1 — Scrape the product page.

Playwright + Chromium loads the page with a store-specific selector profile
(Amazon.in, Flipkart, generic), blocking fonts/media for speed, and extracts
title, price, rating, features and images.

When Playwright isn't installed (e.g. demo/CI), a deterministic stub returns
plausible data derived from the URL so the rest of the pipeline still runs.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ..observability import get_logger
from ..reliability.breaker import guard
from ..reliability.retry import PermanentError, TransientError, with_retry
from .affiliate import detect_network

logger = get_logger("scraper")


# Store-specific selector profiles. Markup drifts — expect to tune these live.
PROFILES = {
    "amazon": {
        "title": "#productTitle",
        "price": "span.a-price span.a-offscreen",
        "rating": "span.a-icon-alt",
        "features": "#feature-bullets li span",
        "images": "#imgTagWrapperId img, #landingImage",
    },
    "flipkart": {
        "title": "span.B_NuCI, span.VU-ZEz",
        "price": "div._30jeq3, div.Nx9bqj",
        "rating": "div._3LWZlK, div.XQDdHH",
        "features": "div._1mXcCf li, div._1133yb li",
        "images": "img._396cs4, img._0DkuPH",
    },
    "generic": {
        "title": "h1",
        "price": "[class*=price]",
        "rating": "[class*=rating]",
        "features": "li",
        "images": "img",
    },
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def clean_price(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"[₹$]\s?[\d,]+(?:\.\d+)?", value)
    return clean_text(match.group(0)) if match else clean_text(value)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PermanentError(f"not a valid product URL: {url!r}")


async def scrape(product_url: str) -> dict:
    _validate_url(product_url)
    network = detect_network(product_url)
    profile = PROFILES.get(network, PROFILES["generic"])

    async def _do() -> dict:
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError:
            logger.warning("playwright not installed — using stub scrape for %s", product_url)
            return _stub_scrape(product_url, network)
        return await _playwright_scrape(product_url, profile, network)

    return await guard("scraper").call(lambda: with_retry(_do, name="scrape"))


async def _playwright_scrape(url: str, profile: dict, network: str) -> dict:  # pragma: no cover
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            # Block fonts/media for speed.
            await page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("font", "media")
                else route.continue_(),
            )
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if resp and resp.status >= 400:
                if 400 <= resp.status < 500 and resp.status != 429:
                    raise PermanentError(f"page returned {resp.status}")
                raise TransientError(f"page returned {resp.status}")

            async def text(selector: str) -> str:
                el = await page.query_selector(selector)
                return clean_text(await el.inner_text()) if el else ""

            features = [
                clean_text(await el.inner_text())
                for el in (await page.query_selector_all(profile["features"]))[:8]
            ]
            images = [
                src for el in (await page.query_selector_all(profile["images"]))[:6]
                if (src := await el.get_attribute("src"))
            ]
            return {
                "title": await text(profile["title"]),
                "price": clean_price(await text(profile["price"])),
                "rating": clean_text(await text(profile["rating"])),
                "features": [f for f in features if f],
                "images": images,
                "network": network,
                "source_url": url,
            }
        finally:
            await browser.close()


def _stub_scrape(url: str, network: str) -> dict:
    """Deterministic placeholder data so demos run without a browser."""
    slug = urlparse(url).path.strip("/").split("/")[-1] or "product"
    title = clean_text(slug.replace("-", " ").replace("_", " ").title()) or "Sample Product"
    return {
        "title": title[:90],
        "price": "₹1,499",
        "rating": "4.3 out of 5 stars",
        "features": [
            "Premium build quality",
            "Great value for money",
            "Fast delivery across India",
            "Trusted by thousands of buyers",
        ],
        "images": [
            "https://via.placeholder.com/1080x1920.png?text=Product+1",
            "https://via.placeholder.com/1080x1920.png?text=Product+2",
        ],
        "network": network,
        "source_url": url,
        "_stub": True,
    }
