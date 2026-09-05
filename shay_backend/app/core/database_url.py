"""
Pure URL-normalization helpers for app/core/database.py.

Extracted verbatim (no behavior change) so the module-level engine/session
setup in database.py can stay untouched — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md
for why database.py itself keeps a stated-exception on further splitting.
"""

from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse, urlunparse


def _ensure_async_postgres_driver(url: str) -> str:
    """
    Normalize PostgreSQL URLs for async SQLAlchemy usage.

    Shay boot uses ``create_async_engine`` for PostgreSQL, so plain
    ``postgresql://`` (or psycopg2-flavoured) URLs must be promoted to
    ``postgresql+asyncpg://`` to avoid loading a synchronous driver.
    """
    if not url:
        return url

    raw = url.strip()
    lowered = raw.lower()
    if lowered.startswith("postgresql+asyncpg://"):
        return raw
    if lowered.startswith(("postgresql://", "postgres://", "postgresql+psycopg2://", "postgres+psycopg2://")):
        return f"postgresql+asyncpg://{raw.split('://', 1)[1]}"
    return raw


def _normalize_postgres_url(url: str) -> str:
    """
    Return a PostgreSQL URL safe for drivers: encode password so special chars (@, !, :, etc.) work.
    Leaves non-PostgreSQL and already-valid URLs unchanged. Only applied for postgresql/postgres schemes.
    """
    if not url or not url.strip().lower().startswith(("postgresql", "postgres+")):
        return url
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or ""
        at_last = netloc.rfind("@")
        if at_last == -1:
            return url
        userinfo, hostport = netloc[:at_last], netloc[at_last + 1 :]
        colon_first = userinfo.find(":")
        if colon_first == -1:
            return url
        user, password = userinfo[:colon_first], userinfo[colon_first + 1 :]
        encoded_password = quote_plus(password, safe="")
        new_netloc = f"{user}:{encoded_password}@{hostport}"
        return urlunparse((parsed.scheme, new_netloc, parsed.path or "", parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return url


def _extract_oracle_dsn(oracle_url: str) -> tuple[str, str | None]:
    """
    Extract a JDBC-style TNS descriptor or a ``?dsn=`` query param from an
    Oracle SQLAlchemy URL, returning ``(possibly-rewritten url, dsn or None)``.

    Handles two shapes:
    - ``oracle+oracledb://user@localhost/`` with the TNS descriptor
      (``(description=...)`` or URL-encoded equivalent) placed after ``@``
      instead of a normal host, in which case it's replaced with a
      ``localhost`` placeholder and the descriptor is returned as the dsn.
    - ``oracle+oracledb://user@host/?dsn=...`` where the descriptor is a
      query parameter, which is stripped from the URL and returned as the dsn.

    Identical logic previously existed twice in this module (async engine
    creation and get_sync_engine) — extracted verbatim here, no behavior
    change. urlparse rejects '_' in scheme names (oracle+oracledb_async), so
    this uses plain string ops rather than urlparse.
    """
    oracle_dsn = None
    if "//" in oracle_url and "@" in oracle_url:
        _after_slash = oracle_url.split("//", 1)[1]
        if "@" in _after_slash:
            _user_part, _host_part = _after_slash.split("@", 1)
            _host_stripped = _host_part.split("/")[0].split("?")[0].strip()
            if _host_stripped.startswith("(description"):
                # JDBC-style: TNS descriptor after @
                oracle_dsn = _host_stripped
                _scheme = oracle_url.split("//", 1)[0]
                oracle_url = f"{_scheme}//{_user_part}@localhost/"
            elif _host_stripped.startswith("%28description%3D") or _host_stripped.startswith("%28description%20%3D"):
                oracle_dsn = unquote(_host_stripped)
                _scheme = oracle_url.split("//", 1)[0]
                oracle_url = f"{_scheme}//{_user_part}@localhost/"
    if not oracle_dsn:
        _q_idx = oracle_url.find("?")
        if _q_idx != -1:
            qs = parse_qs(oracle_url[_q_idx + 1 :], keep_blank_values=True)
            if "dsn" in qs and qs["dsn"]:
                oracle_dsn = qs["dsn"][0].strip()
                qs_clean = {k: v for k, v in qs.items() if k != "dsn"}
                oracle_url = oracle_url[:_q_idx] + ("?" + urlencode(qs_clean, doseq=True) if qs_clean else "")
    return oracle_url, oracle_dsn
