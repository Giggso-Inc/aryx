"""Tests for the shared SSRF guard (aryx.api.ssrf_guard) — the single source
of truth for outbound-URL/header validation used by both the REST API ingest
form and the CPQ share-config route."""
import pytest

from aryx.api.ssrf_guard import check_outbound_headers, check_outbound_url


@pytest.mark.parametrize("url", [
    "http://localhost/steal",
    "http://127.0.0.1/steal",
    "http://[::1]/steal",
    "http://0.0.0.0/steal",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://169.254.169.254/latest/meta-data/",   # AWS/OCI IMDS
    "http://169.254.170.2/v2/credentials",         # ECS task credentials
    "http://10.0.0.5/internal",
    "http://172.16.0.5/internal",
    "http://192.168.1.5/internal",
])
def test_blocks_private_and_metadata_addresses(url):
    with pytest.raises(ValueError):
        check_outbound_url(url)


@pytest.mark.parametrize("url", ["ftp://example.com/file", "file:///etc/passwd", "example.com/no-scheme"])
def test_blocks_non_http_schemes(url):
    with pytest.raises(ValueError):
        check_outbound_url(url)


def test_allows_ordinary_https_url():
    assert check_outbound_url("https://api.example.com/v1/customers") == "https://api.example.com/v1/customers"


def test_allows_hostname_that_is_not_a_literal_ip():
    # DNS resolution happens at request time, not validation time — a hostname
    # that merely LOOKS fine here (but could resolve to a private IP later)
    # is intentionally out of scope for this check, same as rest_ingest_api.
    assert check_outbound_url("https://internal-tool.example.com/api") == "https://internal-tool.example.com/api"


def test_blocks_host_header_override():
    with pytest.raises(ValueError):
        check_outbound_headers({"Host": "evil.example.com"})


def test_blocks_connection_header():
    with pytest.raises(ValueError):
        check_outbound_headers({"Connection": "close"})


def test_allows_ordinary_headers():
    headers = {"x-tenant": "acme", "Authorization": "Bearer token"}
    assert check_outbound_headers(headers) == headers
