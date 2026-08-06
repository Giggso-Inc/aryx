"""Deterministic MSI quote workflow owned by the sales Streamlit app."""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from sales_streamlit.msi_client import MsiClientError, MsiStaleSelectionError

logger = logging.getLogger(__name__)

# MSI's "selections have changed, click UPDATE" response is recoverable —
# call _update then retry the same action, bounded so a genuinely stuck
# state (MSI keeps reporting stale after every update) fails loudly
# instead of looping forever.
_MAX_STALE_RETRIES = 3

MSI_STEP_NAMES = (
    "new_transaction",
    "change_customer",
    "pre_configuration_clean_save",
    "configure",
    "validate_configuration",
    "update_configuration",
    "add_configuration_to_transaction",
    "final_clean_save",
)

# Steps skipped rather than run when their precondition data is absent
# (currently only change_customer, when no customer number is configured —
# the sales-cpq CPQ session has no field for it today, so it can't be
# derived from the confirmed configData the way the other steps' inputs
# can). Skipped steps do not block the rest of the sequence.
_OPTIONAL_STEPS = frozenset({"change_customer"})


@dataclass(frozen=True, slots=True)
class MsiWorkflowRequest:
    """Confirmed Aryx payload and catalog route required by MSI."""

    confirmation_id: str
    actor_id: str
    thread_id: str
    config_data: dict[str, Any]
    product_family: str
    product_line: str
    model: str
    # Not sourced from Aryx CPQ state — set only when the caller already
    # knows the MSI customer number (e.g. from CRM context outside this
    # flow). Empty skips the change_customer step rather than guessing.
    customer_number: str = ""

    @property
    def route(self) -> dict[str, str]:
        """Return the route fields used by MSI config action URLs."""
        return {
            "product_family": self.product_family,
            "product_line": self.product_line,
            "model": self.model,
        }


class MsiClient(Protocol):
    """MSI operations used by the workflow runner."""

    def new_transaction(self) -> dict[str, Any]:
        """Create an MSI transaction."""

    def resolve_document_id(self, bs_id: int) -> int:
        """Resolve the MSI document identifier for a transaction."""

    def change_customer(self, bs_id: int, customer_number: str) -> dict[str, Any]:
        """Bind the transaction to a customer number."""

    def clean_save(self, bs_id: int) -> dict[str, Any]:
        """Persist the transaction's current state."""

    def configure(
        self,
        route: dict[str, str],
        bs_id: int,
        document_id: int,
        config_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Start MSI configuration with the confirmed Aryx payload."""

    def update(
        self,
        route: dict[str, str],
        cache_instance_id: str,
    ) -> dict[str, Any]:
        """Refresh the active MSI configuration."""

    def interact(
        self,
        route: dict[str, str],
        cache_instance_id: str,
        config_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Feed one config delta (or none) into the active MSI configuration."""

    def add_to_transaction(
        self,
        route: dict[str, str],
        cache_instance_id: str,
    ) -> dict[str, Any]:
        """Attach the active configuration to its transaction."""


class WorkflowStore(Protocol):
    """Durable workflow persistence contract."""

    def get_by_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        """Load a workflow by its unique confirmation message."""

    def create(self, request: MsiWorkflowRequest) -> dict[str, Any]:
        """Create an initial workflow unless the confirmation already exists."""

    def save(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Persist a workflow state transition."""


class MemoryWorkflowStore:
    """In-memory store for unit tests and explicit local development only."""

    def __init__(self) -> None:
        """Initialize an empty local workflow map."""
        self._by_confirmation: dict[str, dict[str, Any]] = {}

    def get_by_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        """Return an isolated copy of a workflow, if present."""
        row = self._by_confirmation.get(confirmation_id)
        return copy.deepcopy(row) if row else None

    def create(self, request: MsiWorkflowRequest) -> dict[str, Any]:
        """Create or return a workflow for the confirmation."""
        existing = self.get_by_confirmation(request.confirmation_id)
        if existing:
            return existing
        workflow = new_workflow_record(request)
        self._by_confirmation[request.confirmation_id] = copy.deepcopy(workflow)
        return workflow

    def save(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Save and return an isolated workflow copy."""
        workflow["updated_at"] = datetime.now(UTC).isoformat()
        self._by_confirmation[workflow["confirmation_id"]] = copy.deepcopy(workflow)
        return copy.deepcopy(workflow)


def new_workflow_record(request: MsiWorkflowRequest) -> dict[str, Any]:
    """Build the initial persisted representation for a confirmed payload."""
    now = datetime.now(UTC).isoformat()
    return {
        "workflow_id": str(uuid.uuid4()),
        "confirmation_id": request.confirmation_id,
        "actor_id": request.actor_id,
        "thread_id": request.thread_id,
        "status": "running",
        "current_step": MSI_STEP_NAMES[0],
        "identifiers": {},
        "steps": [
            {"name": name, "status": "pending", "message": ""}
            for name in MSI_STEP_NAMES
        ],
        "request": asdict(request),
        "error_message": "",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "replayed": False,
    }


def _identifier(response: dict[str, Any], key: str) -> Any:
    """Read an identifier from the response root or documents object."""
    value = response.get(key)
    if value is None and isinstance(response.get("documents"), dict):
        value = response["documents"].get(key)
    return value


def _safe_message(response: dict[str, Any]) -> str:
    """Return a bounded, non-secret status message for the UI."""
    for key in ("message", "status", "result"):
        value = response.get(key)
        if isinstance(value, (str, int, float, bool)):
            return str(value)[:500]
    return "Completed"


class MsiWorkflowRunner:
    """Execute and persist the six required MSI actions exactly once."""

    def __init__(self, client: MsiClient, store: WorkflowStore) -> None:
        """Bind an MSI client and workflow persistence adapter."""
        self._client = client
        self._store = store

    def run(
        self,
        request: MsiWorkflowRequest,
        on_step: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run the workflow or replay the existing confirmation result."""
        existing = self._store.get_by_confirmation(request.confirmation_id)
        if existing:
            existing["replayed"] = True
            return existing

        workflow = self._store.create(request)
        if workflow.get("replayed"):
            return workflow
        state = {"cache_instance_id": ""}
        for index, name in enumerate(MSI_STEP_NAMES):
            step = workflow["steps"][index]
            if name in _OPTIONAL_STEPS and not self._has_precondition(name, request):
                step.update({
                    "status": "skipped",
                    "message": "No customer number configured for this quote",
                })
                self._store.save(workflow)
                if on_step:
                    on_step(copy.deepcopy(workflow))
                continue
            workflow["current_step"] = name
            step["status"] = "running"
            self._store.save(workflow)
            if on_step:
                on_step(copy.deepcopy(workflow))
            try:
                response = self._execute(name, request, workflow, state)
            except Exception as exc:  # noqa: BLE001
                # Confirmed via real testing: _addToTxn failures — not just
                # the "click UPDATE" stale-selection message, but also the
                # generic "Configuration is incomplete" one — can resolve
                # after an _update + retry cycle. Broader than the
                # stale-selection phrase match alone, but scoped to this
                # one step so other steps' real failures still fail fast.
                should_retry = isinstance(exc, MsiStaleSelectionError) or (
                    name == "add_configuration_to_transaction"
                    and isinstance(exc, MsiClientError)
                )
                if not should_retry:
                    return self._fail(workflow, index, name, exc, on_step)
                try:
                    response = self._retry_after_stale_selection(
                        name, request, workflow, state,
                    )
                except Exception as retry_exc:  # noqa: BLE001
                    return self._fail(workflow, index, name, retry_exc, on_step)
            step.update({"status": "success", "message": _safe_message(response)})
            self._store.save(workflow)
            if on_step:
                on_step(copy.deepcopy(workflow))

        workflow["status"] = "success"
        workflow["current_step"] = ""
        return self._store.save(workflow)

    @staticmethod
    def _has_precondition(name: str, request: MsiWorkflowRequest) -> bool:
        """Return whether an optional step's required input is present."""
        if name == "change_customer":
            return bool(request.customer_number)
        return True

    def _execute(
        self,
        name: str,
        request: MsiWorkflowRequest,
        workflow: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one named MSI step and update derived identifiers."""
        route = request.route
        if name == "new_transaction":
            response = self._client.new_transaction()
            bs_id = _identifier(response, "_id")
            if bs_id is None:
                raise ValueError("New transaction response did not contain _id")
            bs_id = int(bs_id)
            workflow["identifiers"].update(
                {
                    "bs_id": bs_id,
                    "document_id": int(self._client.resolve_document_id(bs_id)),
                }
            )
            return response
        if name == "change_customer":
            return self._client.change_customer(
                int(workflow["identifiers"]["bs_id"]), request.customer_number,
            )
        if name in {"pre_configuration_clean_save", "final_clean_save"}:
            return self._client.clean_save(int(workflow["identifiers"]["bs_id"]))
        if name == "configure":
            response = self._client.configure(
                route,
                int(workflow["identifiers"]["bs_id"]),
                int(workflow["identifiers"]["document_id"]),
                request.config_data,
            )
        elif name == "validate_configuration":
            response = self._client.interact(route, state["cache_instance_id"])
        elif name == "update_configuration":
            response = self._client.update(route, state["cache_instance_id"])
        else:
            response = self._client.add_to_transaction(
                route,
                state["cache_instance_id"],
            )
        new_cache = str(_identifier(response, "cacheInstanceId") or "")
        if name == "configure" and not new_cache:
            raise ValueError("Configure response did not contain cacheInstanceId")
        if new_cache:
            state["cache_instance_id"] = new_cache
            workflow["identifiers"]["cache_instance_id"] = new_cache
        return response

    def _retry_after_stale_selection(
        self,
        name: str,
        request: MsiWorkflowRequest,
        workflow: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Call _update then retry one action, bounded to a few attempts."""
        route = request.route
        for attempt in range(_MAX_STALE_RETRIES):
            update_response = self._client.update(route, state["cache_instance_id"])
            new_cache = str(_identifier(update_response, "cacheInstanceId") or "")
            if new_cache:
                state["cache_instance_id"] = new_cache
                workflow["identifiers"]["cache_instance_id"] = new_cache
            try:
                return self._execute(name, request, workflow, state)
            except MsiClientError:  # covers MsiStaleSelectionError too
                if attempt == _MAX_STALE_RETRIES - 1:
                    raise

    def _fail(
        self,
        workflow: dict[str, Any],
        index: int,
        name: str,
        exc: Exception,
        on_step: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        """Persist an error and mark all dependent steps skipped."""
        logger.error(
            "msi workflow step failed step=%s confirmation_id=%s thread_id=%s "
            "actor_id=%s error=%s",
            name,
            workflow.get("confirmation_id"),
            workflow.get("thread_id"),
            workflow.get("actor_id"),
            exc,
        )
        workflow["steps"][index].update(
            {"status": "error", "message": str(exc)[:500]}
        )
        for pending in workflow["steps"][index + 1 :]:
            pending["status"] = "skipped"
            pending["message"] = "Skipped after an earlier step failed"
        workflow["status"] = "error"
        workflow["current_step"] = name
        saved = self._store.save(workflow)
        if on_step:
            on_step(copy.deepcopy(saved))
        return saved
