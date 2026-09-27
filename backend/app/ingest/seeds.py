"""
Seed URL loader for the crawl ingest pipeline (SDD §5.1).

Reads ``seeds.yaml`` from the same directory, validates every URL's hostname
against ``settings.allowed_hosts`` (CRAWL_ALLOWLIST), and returns the mapping
ready for the crawler.

Usage::

    from app.ingest.seeds import load_seeds

    seeds = load_seeds()          # uses bundled seeds.yaml
    seeds = load_seeds(my_path)   # alternate file for tests
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)

# Canonical location of the seed config file, shipped alongside this module.
_DEFAULT_SEEDS_PATH = Path(__file__).parent / "seeds.yaml"


def load_seeds(path: Path = _DEFAULT_SEEDS_PATH) -> dict[str, list[str]]:
    """Load seed URLs from *path* and validate hostnames against the allowlist.

    Args:
        path: Path to a YAML file whose top-level key ``seeds`` maps each
              domain area name to a list of seed URL strings.

    Returns:
        ``dict[domain_area, [url, ...]]`` — a shallow copy of the YAML seeds
        section with all entries validated.

    Raises:
        FileNotFoundError: *path* does not exist.
        ValueError: Any seed URL's hostname is absent from
                    ``settings.allowed_hosts`` (CRAWL_ALLOWLIST).
    """
    with open(path) as fh:
        data = yaml.safe_load(fh)

    seeds: dict[str, list[str]] = data.get("seeds", {})

    # Validate every URL before returning — fail fast so a mis-configured seed
    # is caught at startup rather than silently crawling off-scope hosts.
    for domain, urls in seeds.items():
        for url in urls:
            host = (urlparse(url).hostname or "").lower()
            if host not in settings.allowed_hosts:
                raise ValueError(
                    f"Seed URL {url!r} (domain={domain!r}) has host {host!r} "
                    f"which is not in CRAWL_ALLOWLIST. "
                    f"Allowed hosts: {sorted(settings.allowed_hosts)}"
                )

    logger.debug(
        "Loaded %d seed URL(s) across %d domain area(s) from %s",
        sum(len(v) for v in seeds.values()),
        len(seeds),
        path,
    )
    return seeds
