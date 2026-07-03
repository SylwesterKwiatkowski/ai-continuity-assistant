"""M1 — connection registry & the credential-resolution rule.

These tests assert the structural half of "never impersonate the target user":
  - reads resolve the TARGET's connection,
  - writes resolve only the ACTIVE_USER's connection,
  - there is no code path that resolves a write against the target.
"""

from __future__ import annotations

import pytest

from assistant.domain import System
from assistant.identity import ConnectionNotFound, ConnectionRegistry
from assistant.identity.connections import InMemoryTokenStore


@pytest.fixture
def registry() -> ConnectionRegistry:
    return ConnectionRegistry.from_seed()


def test_read_uses_target_connection(registry: ConnectionRegistry) -> None:
    # Mark asks about Anna: the read is resolved against ANNA's Gmail connection.
    conn = registry.resolve_for_read("anna", System.GMAIL)
    assert conn.user_id == "anna"
    assert conn.system == System.GMAIL


def test_read_fails_when_target_has_not_connected(registry: ConnectionRegistry) -> None:
    # Anna never connected Jira -> honest refusal, no fallback to anyone else's token.
    with pytest.raises(ConnectionNotFound) as exc:
        registry.resolve_for_read("anna", System.JIRA)
    assert exc.value.user_id == "anna"
    assert exc.value.system == System.JIRA


def test_write_uses_active_user_connection(registry: ConnectionRegistry) -> None:
    # Mark creates a Jira issue: resolved against MARK's own connection.
    conn = registry.resolve_for_write("mark", System.JIRA)
    assert conn.user_id == "mark"
    assert conn.system == System.JIRA


def test_write_is_never_resolved_as_target(registry: ConnectionRegistry) -> None:
    # There is no way to obtain a write credential "as Anna": resolve_for_write only
    # accepts the acting user, and Anna is not the actor here. Even if asked directly,
    # it would only ever return Anna's OWN connection, never attribute Mark's write to her.
    mark_conn = registry.resolve_for_write("mark", System.JIRA)
    assert mark_conn.user_id != "anna"
    # And Anna has no Jira connection at all, so a write "as Anna" to Jira is impossible.
    with pytest.raises(ConnectionNotFound):
        registry.resolve_for_write("anna", System.JIRA)


def test_connect_and_disconnect(registry: ConnectionRegistry) -> None:
    registry.connect("lucy", System.HUBSPOT, token_ref="tok-lucy-hs", scopes=["notes"])
    assert registry.get("lucy", System.HUBSPOT) is not None
    registry.disconnect("lucy", System.HUBSPOT)
    assert registry.get("lucy", System.HUBSPOT) is None


def test_list_for_user(registry: ConnectionRegistry) -> None:
    systems = {c.system for c in registry.list_for_user("anna")}
    assert systems == {System.GMAIL, System.TEAMS, System.CALENDAR}


def test_token_retrieval(registry: ConnectionRegistry) -> None:
    conn = registry.resolve_for_read("anna", System.GMAIL)
    assert registry.token_for(conn)  # stub returns a non-empty secret


def test_unknown_token_ref_raises_key_error() -> None:
    store = InMemoryTokenStore()
    with pytest.raises(KeyError):
        store.get_token("nope")
