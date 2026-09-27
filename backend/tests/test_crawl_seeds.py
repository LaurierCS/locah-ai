"""Tests for the crawl seed URL config (issue #36).

Acceptance criteria (SDD §5.1 / issue #36):
  - Seed file is checked in with ≥1 URL per SDD domain area.
  - Loader validates hostnames against settings.allowed_hosts.
  - Loader rejects off-allowlist URLs with ValueError.
"""

import textwrap
from pathlib import Path

import pytest

from app.core.config import settings
from app.ingest.seeds import load_seeds

# The eight domain areas mandated by SDD §5.1.
_REQUIRED_DOMAINS = {
    "advising",
    "academic_calendar",
    "coop",
    "important_dates",
    "registrar",
    "wellness",
    "accessible_learning",
    "financial_aid",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_seeds_yaml(tmp_path: Path, content: str) -> Path:
    """Write a temporary seeds.yaml and return its path."""
    p = tmp_path / "seeds.yaml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_seed_file_loads() -> None:
    """load_seeds() with the shipped seeds.yaml returns a non-empty dict."""
    seeds = load_seeds()

    assert isinstance(seeds, dict), "load_seeds() must return a dict"
    assert seeds, "seeds dict must not be empty"


def test_all_domain_areas_present() -> None:
    """Shipped seeds.yaml contains every SDD §5.1 domain area with ≥1 URL."""
    seeds = load_seeds()

    missing = _REQUIRED_DOMAINS - seeds.keys()
    assert not missing, f"Missing domain area(s) in seeds.yaml: {sorted(missing)}"

    empty = {domain for domain, urls in seeds.items() if not urls}
    assert not empty, f"Domain area(s) with no seed URLs: {sorted(empty)}"


def test_all_urls_on_allowlist() -> None:
    """Every URL in the shipped seeds.yaml is on an allowlisted hostname."""
    # load_seeds() itself raises ValueError on violation, so a clean load is
    # the primary assertion — but we also verify hostnames explicitly so the
    # failure message is actionable.
    seeds = load_seeds()

    offsite = []
    for domain, urls in seeds.items():
        for url in urls:
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            if host not in settings.allowed_hosts:
                offsite.append((domain, url, host))

    assert not offsite, (
        "Off-allowlist seed URLs found:\n"
        + "\n".join(f"  [{domain}] {url!r} → host={host!r}" for domain, url, host in offsite)
        + f"\nAllowed hosts: {sorted(settings.allowed_hosts)}"
    )


def test_loader_rejects_off_allowlist(tmp_path: Path) -> None:
    """load_seeds() raises ValueError when a seed URL is not on the allowlist."""
    bad_yaml = _write_seeds_yaml(
        tmp_path,
        """
        seeds:
          advising:
            - https://evil.com/trick
        """,
    )

    with pytest.raises(ValueError, match="CRAWL_ALLOWLIST"):
        load_seeds(bad_yaml)


def test_loader_rejects_partially_off_allowlist(tmp_path: Path) -> None:
    """load_seeds() raises ValueError even if only one URL is off-allowlist."""
    # Mix one valid URL with one invalid URL in the same domain area.
    mixed_yaml = _write_seeds_yaml(
        tmp_path,
        """
        seeds:
          advising:
            - https://www.wlu.ca/student-advising/
            - https://external-site.org/advising
        """,
    )

    with pytest.raises(ValueError, match="CRAWL_ALLOWLIST"):
        load_seeds(mixed_yaml)


def test_loader_accepts_all_allowlisted_hosts(tmp_path: Path) -> None:
    """load_seeds() accepts URLs on every host in the default allowlist."""
    # Build a YAML seeds file with one URL per allowlisted host.
    hosts = sorted(settings.allowed_hosts)
    url_lines = "".join(f"\n    - https://{h}/page" for h in hosts)
    yaml_text = f"seeds:\n  advising:{url_lines}\n"
    p = tmp_path / "seeds.yaml"
    p.write_text(yaml_text)

    seeds = load_seeds(p)
    assert len(seeds["advising"]) == len(hosts)
