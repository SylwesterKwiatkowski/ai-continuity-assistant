"""Approval request repository (spec §16)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from assistant.permissions.policies import ApprovalRequest


@runtime_checkable
class ApprovalRepository(Protocol):
    """Storage abstraction for ApprovalRequest objects."""

    def add(self, req: ApprovalRequest) -> None: ...

    def get(self, approval_id: str) -> ApprovalRequest | None: ...

    def pending(self) -> list[ApprovalRequest]: ...


class InMemoryApprovalRepository:
    """Non-persistent approval store for tests/MVP."""

    def __init__(self) -> None:
        self._store: dict[str, ApprovalRequest] = {}

    def add(self, req: ApprovalRequest) -> None:
        self._store[req.id] = req

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._store.get(approval_id)

    def pending(self) -> list[ApprovalRequest]:
        return [r for r in self._store.values() if r.status == "pending"]
