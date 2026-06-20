"""Append the right affiliate/associate tag per network.

Extensible: add a network detector + tagger and register it in ``NETWORKS``.
v1 ships Amazon Associates; Flipkart and a generic pass-through are stubbed.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..config import settings


def detect_network(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "amazon." in host or "amzn." in host:
        return "amazon"
    if "flipkart." in host or "fkrt." in host:
        return "flipkart"
    return "generic"


def _set_query_param(url: str, key: str, value: str) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    query[key] = value
    return urlunparse(parts._replace(query=urlencode(query)))


def tag_amazon(url: str) -> str:
    if not settings.AMAZON_ASSOCIATE_TAG:
        return url
    return _set_query_param(url, "tag", settings.AMAZON_ASSOCIATE_TAG)


def tag_flipkart(url: str) -> str:
    # Flipkart affiliate uses an `affid` param; configure via env when wired.
    return url


NETWORKS = {
    "amazon": tag_amazon,
    "flipkart": tag_flipkart,
    "generic": lambda u: u,
}


def apply_affiliate_tag(url: str) -> str:
    """Return the destination URL with the correct affiliate tag appended."""
    network = detect_network(url)
    return NETWORKS.get(network, NETWORKS["generic"])(url)
