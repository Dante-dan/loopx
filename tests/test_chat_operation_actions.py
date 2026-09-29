from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loopx.chat_action_store import ActionConflictError, ChatActionStore
from loopx.chat_actions import ChatActionService, ProtectedActionGate
from loopx.control_plane.collaboration.operation_handoff import agent_operation_action
from loopx.control_plane.collaboration.inbox import pending
from loopx.capabilities.manager_context import turn_start_hook


GOAL_ID = "goal-operation-fixture"
OPERATOR_ID = "ou_authorized_fixture"
EXECUTION_ACTOR = {
    "goal_id": GOAL_ID,
    "agent_id": "finance-fixture-agent",
    "host_surface": "codex-app",
    "thread_id": "thread-fixture-original",
}


def _agent_request(service: ChatActionService) -> dict[str, object]:
    registry = json.loads(service.registry_path.read_text())
    registry["goals"][0]["coordination"]["thread_agent_bindings"] = [
        {key: value for key, value in EXECUTION_ACTOR.items() if key != "goal_id"}
    ]
    service.registry_path.write_text(json.dumps(registry))
    request = _request()
    parameters = request["normalized_parameters"]
    parameters["executor"] = {
        "kind": "agent_session",
        "revision": "agent-session-handoff-v0",
        "host_surface": EXECUTION_ACTOR["host_surface"],
        "thread_id": EXECUTION_ACTOR["thread_id"],
    }
    parameters["operation_kind"] = "finance.order.execute"
    parameters["projection"]["simulated"] = False
    parameters["projection"]["warning"] = (
        "Synthetic engineering terms; no live account or venue is used."
    )
    parameters["destination_account_ref"] = "account:synthetic-fixture"
    return request


def _claim_agent_operation(service: ChatActionService, store: ChatActionStore) -> dict:
    proposal = service.preview(_agent_request(service))
    delivered = store.record_operation_delivery(
        proposal["proposal_id"], delivery=_delivery(proposal)
    )
    return store.decide_operation(
        proposal["proposal_id"],
        decision="confirm",
        confirmation=_confirmation(delivered),
    )


def _agent_result(
    proposal: dict, consumption_id: str, *, result: str = "executed"
) -> dict:
    operation = proposal["operation"]
    return {
        "schema_version": "loopx_operation_outcome_v0",
        "operation_id": proposal["proposal_id"],
        "payload_digest": operation["payload_digest"],
        "confirmation_digest": operation["confirmation_digest"],
        "claim_id": operation["claim"]["claim_id"],
        "executor_revision": operation["executor_revision"],
        "consumption_id": consumption_id,
        "outcome": result,
        "projection_verified": True,
        "simulation": False,
        "external_write_performed": result != "not_executed",
        "evidence_refs": ["receipt:synthetic-fixture-1"],
        "summary": "Synthetic recorded execution evidence.",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "future-revision"),
        ("host_surface", "unregistered-host"),
        ("thread_id", "invalid thread"),
        ("extra_authority", True),
    ],
)
def test_agent_executor_invalid_binding_is_a_bounded_validation_error(
    tmp_path: Path, field: str, value: object
) -> None:
    service, store = _service(tmp_path)
    request = _agent_request(service)
    request["normalized_parameters"]["executor"][field] = value
    before = store.path.read_bytes() if store.path.exists() else None
    with pytest.raises(ValueError):
        service.preview(request)
    assert (store.path.read_bytes() if store.path.exists() else None) == before


def test_agent_handoff_requires_confirmation_and_original_session(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    proposal = service.preview(_agent_request(service))
    runtime = store.root.parent.parent
    args = dict(proposal_id=proposal["proposal_id"], actor=EXECUTION_ACTOR)
    preview = agent_operation_action(
        runtime, service.registry_path, action="inspect", **args
    )
    assert (
        preview["status"] == "awaiting_confirmation"
        and preview["execution_allowed"] is False
    )
    with pytest.raises(ActionConflictError, match="authenticated confirmation"):
        agent_operation_action(
            runtime,
            service.registry_path,
            action="consume",
            consumption_id="attempt-1",
            **args,
        )
    delivered = store.record_operation_delivery(
        proposal["proposal_id"], delivery=_delivery(proposal)
    )
    claimed = store.decide_operation(
        proposal["proposal_id"],
        decision="confirm",
        confirmation=_confirmation(delivered),
    )
    with pytest.raises(ActionConflictError, match="original bound session"):
        agent_operation_action(
            runtime,
            service.registry_path,
            action="consume",
            consumption_id="attempt-1",
            **{**args, "actor": {**EXECUTION_ACTOR, "thread_id": "thread-other"}},
        )
    with pytest.raises(ActionConflictError, match="not been consumed"):
        store.observe_operation_outcome(
            proposal["proposal_id"],
            outcome=_agent_result(claimed, "attempt-1"),
            agent_actor=EXECUTION_ACTOR,
            agent_binding_current=True,
        )
    assert not store.load(proposal["proposal_id"])["operation"].get("agent_handoff")


def test_agent_handoff_one_shot_consumption_survives_concurrent_retry_and_restart(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    proposal = _claim_agent_operation(service, store)
    runtime = store.root.parent.parent
    inbox = pending(runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"])
    assert len(inbox["operation_handoffs"]) == 1
    assert inbox["operation_handoffs"][0]["host_delivery"] == "not_attempted"
    assert inbox["operation_handoffs"][0]["execution_allowed"] is False
    assert "operation_handoffs" not in pending(runtime, GOAL_ID, "different-agent")

    def consume(index: int) -> dict:
        return agent_operation_action(
            runtime,
            service.registry_path,
            proposal_id=proposal["proposal_id"],
            actor=EXECUTION_ACTOR,
            action="consume",
            consumption_id=f"attempt-{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as workers:
        receipts = list(workers.map(consume, range(4)))
    first = [r for r in receipts if r["execution_allowed"]]
    assert len(first) == 1
    assert all(
        r["status"] == "already_consumed"
        for r in receipts
        if not r["execution_allowed"]
    )
    restarted = ChatActionStore(store.root)
    handoff = restarted.load(proposal["proposal_id"])["operation"]["agent_handoff"]
    assert consume(99)["execution_allowed"] is False
    assert (
        restarted.load(proposal["proposal_id"])["operation"]["agent_handoff"] == handoff
    )
    assert pending(runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"])["operation_handoffs"][
        0
    ]["needs_reconciliation"]
    result = _agent_result(proposal, first[0]["consumption_id"])
    observed = agent_operation_action(
        runtime,
        service.registry_path,
        proposal_id=proposal["proposal_id"],
        actor=EXECUTION_ACTOR,
        action="report",
        outcome=result,
    )
    assert observed["execution_allowed"] is False and observed["outcome"] == result
    assert "operation_handoffs" not in pending(
        runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"]
    )
    assert consume(99)["execution_allowed"] is False


@pytest.mark.parametrize("change", ["expires", "rebound", "stopped", "payload"])
def test_agent_handoff_fails_closed_on_expiry_binding_activation_or_terms_drift(
    tmp_path: Path, change: str
) -> None:
    service, store = _service(tmp_path)
    proposal = _claim_agent_operation(service, store)
    if change in {"rebound", "stopped"}:
        registry = json.loads(service.registry_path.read_text())
        if change == "rebound":
            registry["goals"][0]["coordination"]["thread_agent_bindings"][0][
                "thread_id"
            ] = "thread-replacement"
        else:
            registry["goals"][0]["activation_state"] = "stopped"
        service.registry_path.write_text(json.dumps(registry))
    else:
        data = json.loads(store.path.read_text())
        stored = data["proposals"][proposal["proposal_id"]]
        if change == "expires":
            stored["operation"]["expires_at"] = "2000-01-01T00:00:00Z"
        else:
            stored["normalized_parameters"]["payload"]["quantity"] = "2.00"
        store.path.write_text(json.dumps(data))
    before = store.path.read_bytes()
    with pytest.raises(ActionConflictError):
        agent_operation_action(
            store.root.parent.parent,
            service.registry_path,
            proposal_id=proposal["proposal_id"],
            actor=EXECUTION_ACTOR,
            action="consume",
            consumption_id="attempt-1",
        )
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("consumption_id", "different-attempt"),
        ("payload_digest", "0" * 64),
        ("confirmation_digest", "0" * 64),
        ("claim_id", "different-claim"),
        ("executor_revision", "future-revision"),
        ("simulation", True),
        ("evidence_refs", []),
        ("external_write_performed", False),
    ],
)
def test_agent_result_is_bound_to_one_consumed_operation(
    tmp_path: Path, field: str, value: object
) -> None:
    service, store = _service(tmp_path)
    proposal = _claim_agent_operation(service, store)
    runtime = store.root.parent.parent
    args = dict(proposal_id=proposal["proposal_id"], actor=EXECUTION_ACTOR)
    consumed = agent_operation_action(
        runtime,
        service.registry_path,
        action="consume",
        consumption_id="attempt-1",
        **args,
    )
    outcome = {**_agent_result(proposal, consumed["consumption_id"]), field: value}
    before = store.path.read_bytes()
    with pytest.raises(ActionConflictError):
        agent_operation_action(
            runtime, service.registry_path, action="report", outcome=outcome, **args
        )
    assert store.path.read_bytes() == before


def test_unknown_result_never_grants_resubmission_and_late_evidence_does_not_require_active_goal(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    proposal = _claim_agent_operation(service, store)
    runtime = store.root.parent.parent
    args = dict(proposal_id=proposal["proposal_id"], actor=EXECUTION_ACTOR)
    agent_operation_action(
        runtime,
        service.registry_path,
        action="consume",
        consumption_id="attempt-1",
        **args,
    )
    registry = json.loads(service.registry_path.read_text())
    registry["goals"][0]["activation_state"] = "stopped"
    registry["goals"][0]["coordination"]["thread_agent_bindings"][0]["thread_id"] = (
        "thread-replacement"
    )
    service.registry_path.write_text(json.dumps(registry))
    outcome = _agent_result(proposal, "attempt-1", result="submission_unknown")
    reported = agent_operation_action(
        runtime, service.registry_path, action="report", outcome=outcome, **args
    )
    assert reported["outcome"] == outcome
    readback = agent_operation_action(
        runtime, service.registry_path, action="inspect", **args
    )
    assert readback["needs_reconciliation"] and not readback["execution_allowed"]
    assert not readback["binding_current"]
    from loopx.control_plane.collaboration.goal_instance_scope import (
        collaboration_goal_scope,
    )

    with collaboration_goal_scope(
        service.registry_path,
        goal_id=GOAL_ID,
        agents=(EXECUTION_ACTOR["agent_id"],),
        require_active=False,
    ) as scope:
        inbox = pending(runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"], scope=scope)
    assert inbox["operation_handoffs"][0]["needs_reconciliation"]
    assert inbox["operation_handoffs"][0]["binding_current"] is False


def test_unknown_result_stays_in_original_inbox_past_expiry_until_bound_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store = _service(tmp_path)
    proposal = _claim_agent_operation(service, store)
    runtime = store.root.parent.parent
    args = dict(proposal_id=proposal["proposal_id"], actor=EXECUTION_ACTOR)
    agent_operation_action(
        runtime,
        service.registry_path,
        action="consume",
        consumption_id="attempt-1",
        **args,
    )
    unknown = _agent_result(proposal, "attempt-1", result="submission_unknown")
    report = agent_operation_action(
        runtime, service.registry_path, action="report", outcome=unknown, **args
    )
    assert report["status"] == "submission_unknown" and report["needs_reconciliation"]
    assert agent_operation_action(
        runtime,
        service.registry_path,
        action="consume",
        consumption_id="attempt-1",
        **args,
    )["needs_reconciliation"]
    for _ in range(2):
        assert (
            pending(runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"])[
                "operation_handoffs"
            ][0]["status"]
            == "submission_unknown"
        )
    after_expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    monkeypatch.setattr("loopx.chat_action_store._utc_now", lambda: after_expiry)
    projected = pending(runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"])[
        "operation_handoffs"
    ][0]
    assert projected["needs_reconciliation"] and not projected["execution_allowed"]
    hook = turn_start_hook(
        runtime, service.registry_path, GOAL_ID, EXECUTION_ACTOR["agent_id"]
    ).producer()
    assert hook["agent_read_required"] and hook["observation_count"] == 1
    final = _agent_result(proposal, "attempt-1", result="not_executed")
    with pytest.raises(ActionConflictError, match="exact original unknown result"):
        agent_operation_action(
            runtime, service.registry_path, action="report", outcome=final, **args
        )
    final["reconciles_outcome_digest"] = _digest(unknown)
    settled = agent_operation_action(
        runtime, service.registry_path, action="report", outcome=final, **args
    )
    assert settled["outcome"] == final and not settled["needs_reconciliation"]
    assert settled["execution_allowed"] is False
    updated = store.load(proposal["proposal_id"])
    assert updated["operation"]["outcome"] == unknown
    assert updated["operation"]["reconciliation"] == final
    assert "operation_handoffs" not in pending(
        runtime, GOAL_ID, EXECUTION_ACTOR["agent_id"]
    )
    assert not agent_operation_action(
        runtime,
        service.registry_path,
        action="consume",
        consumption_id="attempt-2",
        **args,
    )["execution_allowed"]


def test_lifecycle_only_source_profile_cannot_acquire_new_operation_authority(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    registry = json.loads(service.registry_path.read_text())
    registry.update(
        profile_id="source_session_v1",
        session_bindings=[],
        session_receipts=[],
        lifetime_receipts=[],
    )
    first_instance = "ginst_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    registry["goals"][0]["goal_instance_id"] = first_instance
    service.registry_path.write_text(json.dumps(registry))
    request = _agent_request(service)
    before = store.path.read_bytes() if store.path.exists() else None
    with pytest.raises(ValueError, match="lifecycle-only profile"):
        service.preview(request)
    assert (store.path.read_bytes() if store.path.exists() else None) == before


def test_inbox_uses_shared_recovery_priority_and_explicit_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from copy import deepcopy

    service, store = _service(tmp_path)
    original = _claim_agent_operation(service, store)
    proposals = []
    for index in range(22):
        projected = deepcopy(original)
        projected["proposal_id"] = projected["operation"]["operation_id"] = (
            f"operation-{index:02}"
        )
        if index == 21:
            projected["operation"].update(
                lifecycle_state="outcome_observed",
                agent_handoff={"consumption_id": "attempt-1"},
                outcome={"outcome": "submission_unknown"},
            )
        proposals.append(projected)
    monkeypatch.setattr(ChatActionStore, "list", lambda *args, **kwargs: proposals)
    inbox = pending(store.root.parent.parent, GOAL_ID, EXECUTION_ACTOR["agent_id"])
    assert len(inbox["operation_handoffs"]) == 20
    assert inbox["operation_handoffs"][0]["operation_id"] == "operation-21"
    assert inbox["operation_handoff_pending_count"] == 22
    assert inbox["operation_handoff_overflow"] == {
        "reason": "attention_page_capacity",
        "count": 2,
        "next_operation_id": "operation-19",
        "instruction": "Inspect the next original operation by id; do not treat this page as the entire inbox.",
    }


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _service(tmp_path: Path) -> tuple[ChatActionService, ChatActionStore]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "ACTIVE_GOAL_STATE.md").write_text(
        f"---\ngoal_id: {GOAL_ID}\n---\n\n## User Todo\n\n## Agent Todo\n",
        encoding="utf-8",
    )
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(project),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "coordination": {
                            "registered_agents": ["finance-fixture-agent"]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = ChatActionStore(tmp_path / "runtime" / "chat" / "actions")
    return ChatActionService(store=store, registry_path=registry), store


def _request(*, payload: dict[str, object] | None = None) -> dict[str, object]:
    operation_payload = payload or {
        "schema_version": "finance_order_intent_v0",
        "side": "buy",
        "asset": "SYNTH",
        "quantity": "1.00",
        "order_type": "limit",
        "limit_price": "10.00",
        "time_in_force": "GTC",
        "reduce_only": False,
    }
    return {
        "action_kind": "operation.execute",
        "summary": "Confirm one simulated finance order",
        "idempotency_key": "operation-fixture-v1",
        "context": {"kind": "goal", "goal_id": GOAL_ID},
        "normalized_parameters": {
            "schema_version": "loopx_operation_request_v0",
            "goal_id": GOAL_ID,
            "agent_id": "finance-fixture-agent",
            "domain": "finance",
            "operation_kind": "finance.order.simulate",
            "operation_schema": "finance_order_intent_v0",
            "payload_ref": "finance-order:synthetic-1",
            "payload": operation_payload,
            "payload_digest": _digest(operation_payload),
            "projection": {
                "schema_version": "loopx_operation_projection_v0",
                "title": "Simulated trade request",
                "subtitle": "Synthetic fixture · no venue call",
                "focus": "BUY 1.00 SYNTH @ 10.00",
                "fields": [
                    {"label": "Order type", "value": "Limit · GTC"},
                    {"label": "Maximum notional", "value": "10.00 TEST"},
                ],
                "warning": "Simulation only. This cannot submit, sign, or transfer.",
                "simulated": True,
            },
            "destination_account_ref": "account:simulation",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "authorized_principals": [f"lark:{OPERATOR_ID}"],
            "executor": {
                "extension_id": "loopx-finance-execution",
                "protocol": "finance_operation_executor_v0",
                "permission": "finance.operation.simulate",
                "revision": "simulator-v0",
            },
        },
    }


def _delivery(proposal: dict[str, object]) -> dict[str, str]:
    operation = proposal["operation"]
    assert isinstance(operation, dict)
    return {
        "provider": "lark",
        "message_id": "om_operation_fixture",
        "chat_id": "oc_operation_fixture",
        "app_id": "cli_operation_fixture",
        "binding_digest": "a" * 64,
        "card_digest": "b" * 64,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }


def _confirmation(
    proposal: dict[str, object], *, event_id: str = "evt-operation-1"
) -> dict[str, str]:
    operation = proposal["operation"]
    assert isinstance(operation, dict)
    delivery = operation["delivery"]
    assert isinstance(delivery, dict)
    return {
        "provider": "lark",
        "event_id": event_id,
        "principal": f"lark:{OPERATOR_ID}",
        "message_id": str(delivery["message_id"]),
        "chat_id": str(delivery["chat_id"]),
        "app_id": str(delivery["app_id"]),
        "surface_kind": "group_message_card",
        "interaction_kind": "button_callback",
        "confirmation_digest": str(operation["confirmation_digest"]),
        "card_digest": str(delivery["card_digest"]),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_operation_preview_arms_one_canonical_gate_and_local_apply_cannot_claim(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)

    proposal = service.preview(_request())

    assert proposal["status"] == "gated"
    assert proposal["available_transitions"] == ["cancel"]
    assert proposal["operation"]["lifecycle_state"] == "awaiting_confirmation"
    assert proposal["gate"]["kind"] == "human_operation_confirmation"
    with pytest.raises(ProtectedActionGate, match="local apply"):
        service.apply(str(proposal["proposal_id"]))
    assert store.load(str(proposal["proposal_id"]))["status"] == "gated"


def test_operation_digest_change_cannot_reuse_idempotency_key(tmp_path: Path) -> None:
    service, _store = _service(tmp_path)
    service.preview(_request())
    changed = _request(
        payload={
            "schema_version": "finance_order_intent_v0",
            "side": "buy",
            "asset": "SYNTH",
            "quantity": "2.00",
        }
    )

    with pytest.raises(ActionConflictError, match="idempotency key"):
        service.preview(changed)


def test_operation_rejects_non_finite_payload_numbers(tmp_path: Path) -> None:
    service, _store = _service(tmp_path)
    request = _request(payload={"schema_version": "fixture", "price": float("nan")})

    with pytest.raises(ValueError, match="JSON"):
        service.preview(request)


def test_lark_decision_claims_once_and_restart_preserves_outcome(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    proposal = service.preview(_request())
    proposal_id = str(proposal["proposal_id"])
    delivered = store.record_operation_delivery(
        proposal_id, delivery=_delivery(proposal)
    )
    confirmation = _confirmation(delivered)

    forged = {**confirmation, "principal": "lark:ou_untrusted_fixture"}
    with pytest.raises(ActionConflictError, match="not authorized"):
        store.decide_operation(proposal_id, decision="confirm", confirmation=forged)

    claimed = store.decide_operation(
        proposal_id, decision="confirm", confirmation=confirmation
    )
    replay = store.decide_operation(
        proposal_id, decision="confirm", confirmation=confirmation
    )
    assert claimed["operation"]["lifecycle_state"] == "claimed"
    assert replay["operation"]["claim"] == claimed["operation"]["claim"]
    with pytest.raises(ActionConflictError, match="already consumed"):
        store.decide_operation(
            proposal_id,
            decision="confirm",
            confirmation={**confirmation, "event_id": "evt-operation-2"},
        )

    outcome = {
        "schema_version": "loopx_operation_outcome_v0",
        "outcome": "simulated_filled",
        "projection_verified": True,
        "operation_id": proposal_id,
        "payload_digest": claimed["operation"]["payload_digest"],
        "summary": "Simulation completed without an external write.",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "external_write_performed": False,
    }
    observed = store.observe_operation_outcome(proposal_id, outcome=outcome)
    restarted = ChatActionStore(store.root)

    assert observed["status"] == "applied"
    assert restarted.load(proposal_id)["operation"]["outcome"] == outcome
    assert restarted.observe_operation_outcome(proposal_id, outcome=outcome) == observed


def test_reject_is_terminal_without_executor_claim(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    proposal = service.preview(_request())
    proposal_id = str(proposal["proposal_id"])
    delivered = store.record_operation_delivery(
        proposal_id, delivery=_delivery(proposal)
    )

    rejected = store.decide_operation(
        proposal_id,
        decision="reject",
        confirmation=_confirmation(delivered),
    )

    assert rejected["status"] == "rejected"
    assert rejected["operation"]["claim"] is None
    assert rejected["operation"]["outcome"]["outcome"] == "rejected_by_operator"
