"""HTTPS Basic Auth client for the Streamlit-owned MSI CPQ sequence."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)


class MsiClientError(RuntimeError):
    """Safe MSI failure suitable for display to a salesperson."""


class MsiStaleSelectionError(MsiClientError):
    """MSI reports the cached selections changed and require _update first.

    Confirmed real MSI response (500, from a manual _addToTxn test):
    {"title": "Your selections have changed. Please click UPDATE to save
    your changes before proceeding."} — recoverable by calling _update
    then retrying the original action, not a terminal failure.
    """


_STALE_SELECTION_PHRASE = "click update"


@dataclass(frozen=True, slots=True)
class MsiSettings:
    """Environment-backed MSI connection and document lookup settings."""

    base_url: str
    username: str
    password: str
    document_id: int | None = None
    document_lookup_path: str = ""
    document_id_field: str = "documentId"
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    allow_http: bool = False

    @classmethod
    def from_env(cls) -> "MsiSettings":
        """Load settings without ever exposing secret values."""
        raw_document_id = os.environ.get("ARYX_SALES_MSI_DOCUMENT_ID", "").strip()
        settings = cls(
            base_url=os.environ.get("ARYX_SALES_MSI_BASE_URL", "").strip(),
            username=os.environ.get("ARYX_SALES_MSI_USERNAME", "").strip(),
            password=os.environ.get("ARYX_SALES_MSI_PASSWORD", ""),
            document_id=int(raw_document_id) if raw_document_id else None,
            document_lookup_path=os.environ.get(
                "ARYX_SALES_MSI_DOCUMENT_LOOKUP_PATH",
                "",
            ).strip(),
            document_id_field=os.environ.get(
                "ARYX_SALES_MSI_DOCUMENT_ID_FIELD",
                "documentId",
            ).strip(),
            timeout_seconds=float(
                os.environ.get("ARYX_SALES_MSI_TIMEOUT_SECONDS", "30")
            ),
            verify_tls=os.environ.get(
                "ARYX_SALES_MSI_VERIFY_TLS",
                "1",
            ) == "1",
            allow_http=os.environ.get(
                "ARYX_SALES_MSI_ALLOW_HTTP",
                "0",
            ) == "1",
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Fail closed on missing secrets, unsafe transport, or lookup gaps."""
        if not self.base_url or not self.username or not self.password:
            raise ValueError(
                "MSI base URL, username, and password must be configured"
            )
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("MSI base URL must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and not self.allow_http:
            raise ValueError("MSI base URL must use HTTPS")
        if not self.verify_tls and not self.allow_http:
            raise ValueError(
                "Disabling MSI TLS verification requires the explicit "
                "local-development override"
            )
        if self.document_id is None and not self.document_lookup_path:
            raise ValueError(
                "MSI documentId or a document lookup path must be configured"
            )
        lookup_url = urlparse(self.document_lookup_path)
        if lookup_url.scheme or lookup_url.netloc:
            raise ValueError("MSI document lookup path must be relative")


class MsiCpqClient:
    """Call MSI CPQ directly; this client is never exposed through MCP."""

    _TRANSACTION_PATH = (
        "/rest/v19/commerceDocumentsOraclecpqoTransaction/actions/"
        "_new_transaction"
    )

    @staticmethod
    def _transaction_action_path(bs_id: int, action: str) -> str:
        """Build a transaction-scoped MSI action path (not config-route)."""
        return (
            f"/rest/v19/commerceDocumentsOraclecpqoTransaction/{int(bs_id)}"
            f"/actions/{action}"
        )

    def __init__(
        self,
        settings: MsiSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a reusable Basic Auth HTTP client."""
        settings.validate()
        self._settings = settings
        self._client = httpx.Client(
            auth=httpx.BasicAuth(settings.username, settings.password),
            timeout=httpx.Timeout(settings.timeout_seconds),
            verify=settings.verify_tls,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        """Close pooled MSI HTTP connections."""
        self._client.close()

    def _url(self, path: str) -> str:
        """Resolve a configured relative API path against the MSI host."""
        return urljoin(self._settings.base_url.rstrip("/") + "/", path.lstrip("/"))

    @staticmethod
    def _route_path(route: dict[str, str], action: str) -> str:
        """Build an injection-safe MSI configuration action path."""
        parts = [
            str(route.get("product_family") or "").strip(),
            str(route.get("product_line") or "").strip(),
            str(route.get("model") or "").strip(),
        ]
        if not all(parts) or any(
            re.fullmatch(r"[A-Za-z0-9_]+", part) is None for part in parts
        ):
            raise MsiClientError("Aryx returned an invalid MSI product route")
        return f"/rest/v19/config{'.'.join(parts)}/actions/{action}"

    def _json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one JSON request and convert failures to safe UI errors."""
        logger.info("msi request method=%s path=%s", method, path)
        try:
            response = self._client.request(
                method,
                self._url(path),
                json=payload,
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "msi request timed out method=%s path=%s timeout=%s",
                method, path, self._settings.timeout_seconds,
            )
            raise MsiClientError(
                "MSI timed out. Check workflow status before retrying."
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "msi request failed method=%s path=%s error=%s", method, path, exc,
            )
            raise MsiClientError("MSI could not be reached.") from exc
        if response.status_code >= 400:
            message = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    # o:errorDetails carries the specific per-attribute
                    # reason (e.g. "Attribute X cannot be modified.") —
                    # the top-level title/detail is often just a generic
                    # "Invalid payload." wrapper around it.
                    error_details = body.get("o:errorDetails")
                    detail_title = ""
                    if isinstance(error_details, list) and error_details:
                        first = error_details[0]
                        if isinstance(first, dict):
                            detail_title = str(first.get("title") or "")
                    message = str(
                        detail_title
                        or body.get("message")
                        or body.get("title")
                        or body.get("detail")
                        or ""
                    )
            except ValueError:
                body = response.text
                message = ""
            logger.error(
                "msi request error method=%s path=%s status=%s body=%s",
                method, path, response.status_code, str(body)[:2000],
            )
            detail = f": {message[:300]}" if message else ""
            message_lower = message.lower()
            error_cls = (
                MsiStaleSelectionError
                if _STALE_SELECTION_PHRASE in message_lower
                else MsiClientError
            )
            raise error_cls(
                f"MSI returned HTTP {response.status_code}{detail}"
            )
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            logger.error(
                "msi non-json response method=%s path=%s body=%s",
                method, path, response.text[:2000],
            )
            raise MsiClientError("MSI returned a non-JSON response") from exc
        if not isinstance(body, dict):
            logger.error(
                "msi unexpected response shape method=%s path=%s body_type=%s",
                method, path, type(body).__name__,
            )
            raise MsiClientError("MSI returned an unexpected response shape")
        logger.info(
            "msi response ok method=%s path=%s status=%s", method, path, response.status_code,
        )
        return body

    def new_transaction(self) -> dict[str, Any]:
        """Create the quote transaction with no request body."""
        return self._json("POST", self._TRANSACTION_PATH)

    def resolve_document_id(self, bs_id: int) -> int:
        """Resolve the external dependency not returned by the six-step flow."""
        if self._settings.document_id is not None:
            return self._settings.document_id
        path = self._settings.document_lookup_path.format(
            bsId=bs_id,
            id=bs_id,
        )
        response = self._json("GET", path)
        value: Any = response
        for key in self._settings.document_id_field.split("."):
            if not isinstance(value, dict) or key not in value:
                raise MsiClientError(
                    "MSI document lookup did not return the configured field"
                )
            value = value[key]
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise MsiClientError("MSI documentId was not numeric") from exc

    def change_customer(self, bs_id: int, customer_number: str) -> dict[str, Any]:
        """Bind the transaction to a customer number.

        Request body shape is not documented anywhere in this codebase —
        the only confirmed data point is the response shape MSI dev
        returned: {"documents": {"customerNumber_t": "<value>"}}. Sending
        the same field name unwrapped at the top level as the request
        body, matching every other action call's convention in this
        client (bare fields, not "documents"-wrapped). Adjust here if MSI
        rejects this shape once exercised against a real environment.
        """
        return self._json(
            "POST",
            self._transaction_action_path(bs_id, "changeCustomer_t"),
            payload={"customerNumber_t": customer_number},
        )

    def clean_save(self, bs_id: int) -> dict[str, Any]:
        """Persist the transaction's current state — no request body."""
        return self._json(
            "POST",
            self._transaction_action_path(bs_id, "cleanSave_t"),
        )

    def configure(
        self,
        route: dict[str, str],
        bs_id: int,
        document_id: int,
        config_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Start MSI configuration with Aryx's confirmed configData."""
        return self._json(
            "POST",
            self._route_path(route, "_configure"),
            payload={
                "cacheInstanceId": "-1",
                "bsId": bs_id,
                "documentId": document_id,
                "configData": config_data,
            },
        )

    def update(
        self,
        route: dict[str, str],
        cache_instance_id: str,
    ) -> dict[str, Any]:
        """Refresh the active MSI configuration cache."""
        return self._json(
            "POST",
            self._route_path(route, "_update"),
            payload={"cacheInstanceId": cache_instance_id},
        )

    def interact(
        self,
        route: dict[str, str],
        cache_instance_id: str,
        config_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Feed one config delta (or none, for a pure validation round) via _interact."""
        return self._json(
            "POST",
            self._route_path(route, "_interact"),
            payload={
                "cacheInstanceId": cache_instance_id,
                "configData": config_data or {},
            },
        )

    def add_to_transaction(
        self,
        route: dict[str, str],
        cache_instance_id: str,
    ) -> dict[str, Any]:
        """Attach the configured product to the quote transaction."""
        return self._json(
            "POST",
            self._route_path(route, "_addToTxn"),
            payload={"cacheInstanceId": cache_instance_id},
        )
