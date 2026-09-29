import assert from "node:assert/strict";
import test from "node:test";
import type {JsonObject} from "../../loopx/control_plane/effect_program.ts";
import {AGENT_OPERATION_REVISION, deriveAgentOperationActor, normalizeAgentOperationExecutor, planAgentOperationHandoff,
  projectAgentOperationInbox} from "../../loopx/control_plane/work_items/operation_agent_handoff.ts";

function input(): JsonObject {
  const executor = {kind: "agent_session", host_surface: "codex-app", thread_id: "original-thread",
    revision: AGENT_OPERATION_REVISION};
  const parameters = {goal_id: "test-goal", agent_id: "test-agent", executor,
    payload_digest: "payload", projection_digest: "projection", destination_account_ref: "opaque-account",
    expires_at: "2030-01-01T01:00:00Z", authorized_principals: ["opaque-principal"]};
  const operation = {...parameters, operation_id: "operation-1", executor_revision: executor.revision,
    confirmation_digest: "confirmation", lifecycle_state: "claimed",
    confirmation: {decision: "confirm", confirmation_digest: "confirmation"}, claim: {claim_id: "claim-1"}};
  return {action: "consume", now: "2030-01-01T00:00:00Z", binding_current: true, consumption_id: "attempt-1",
    actor: {goal_id: "test-goal", agent_id: "test-agent", host_surface: "codex-app", thread_id: "original-thread"},
    digests: {payload_digest: "payload", projection_digest: "projection", confirmation_digest: "confirmation",
      outcome_digest: "unknown-result-digest"},
    proposal: {action_kind: "operation.execute", proposal_id: "operation-1", status: "applying",
      normalized_parameters: parameters, operation}};
}
const operation = (value: JsonObject) => (value.proposal as JsonObject).operation as JsonObject;

test("caller selectors cannot replace missing or foreign host context", () => {
  const requested = input().actor as JsonObject;
  for (const thread_id of [null, "", "another-thread"]) {
    assert.throws(() => deriveAgentOperationActor({requested, ambient: {host_surface: "codex-app", thread_id}}));
  }
  assert.throws(() => deriveAgentOperationActor({requested,
    ambient: {host_surface: "unsupported-host", thread_id: "original-thread"}}));
  assert.deepEqual(deriveAgentOperationActor({requested,
    ambient: {host_surface: "codex-app", thread_id: "original-thread"}}), requested);
});

test("only the first consumed canonical confirmation grants the original session execution", () => {
  const value = input();
  const plan = planAgentOperationHandoff(value);
  assert.equal(plan.execution_allowed, true);
  assert.equal(plan.host_delivery, "not_attempted");
  operation(value).agent_handoff = plan.write_handoff;
  for (const consumption_id of ["attempt-1", "new-attempt"]) {
    const replay = planAgentOperationHandoff({...value, consumption_id});
    assert.equal(replay.execution_allowed, false);
    assert.equal(replay.needs_reconciliation, true);
  }
});

test("each immutable term, confirmation, route and current binding fails closed independently", () => {
  const mutate: Array<(value: JsonObject) => void> = [
    value => {operation(value).confirmation = null;},
    value => {operation(value).claim = null;},
    value => {operation(value).authorized_principals = ["other-principal"];},
    value => {operation(value).expires_at = "2030-01-01T02:00:00Z";},
    value => {operation(value).destination_account_ref = "other-account";},
    value => {(value.actor as JsonObject).thread_id = "replacement-thread";},
    value => {value.binding_current = false;},
    value => {value.now = "2030-01-01T01:00:00Z";},
  ];
  for (const change of mutate) {
    const value = input(); change(value);
    assert.throws(() => planAgentOperationHandoff(value));
  }
  assert.throws(() => normalizeAgentOperationExecutor({executor: {
    ...((input().proposal as JsonObject).normalized_parameters as JsonObject).executor as JsonObject,
    resume_prompt: "Injected instructions are not an executor binding",
  }}));
});

test("unknown submission remains a reconciliation obligation after expiry with no new execution", () => {
  const value = input();
  operation(value).agent_handoff = planAgentOperationHandoff(value).write_handoff;
  operation(value).lifecycle_state = "outcome_observed";
  operation(value).outcome = {outcome: "submission_unknown"};
  const projected = planAgentOperationHandoff({...value, action: "project", now: "2031-01-01T00:00:00Z"});
  assert.equal(projected.status, "submission_unknown");
  assert.equal(projected.needs_reconciliation, true);
  assert.equal(projected.execution_allowed, false);
  const outcome: JsonObject = {schema_version: "loopx_operation_outcome_v0", operation_id: "operation-1",
    payload_digest: "payload", confirmation_digest: "confirmation", claim_id: "claim-1",
    executor_revision: AGENT_OPERATION_REVISION, consumption_id: "attempt-1", outcome: "not_executed",
    projection_verified: true, simulation: false, external_write_performed: false,
    evidence_refs: ["receipt:fixture-original"]};
  assert.throws(() => planAgentOperationHandoff({...value, action: "report", outcome}));
  outcome.reconciles_outcome_digest = "unknown-result-digest";
  const final = planAgentOperationHandoff({...value, action: "report", now: "2031-01-01T00:00:00Z",
    binding_current: false, outcome});
  assert.equal(final.execution_allowed, false);
  assert.equal(final.write_reconciliation, true);
});

test("a currently bound replacement owns historical reconciliation, never the original consumption", () => {
  const value = input();
  operation(value).agent_handoff = planAgentOperationHandoff(value).write_handoff;
  operation(value).lifecycle_state = "outcome_observed";
  operation(value).outcome = {outcome: "submission_unknown"};
  const replacement = {...value.actor as JsonObject, thread_id: "replacement-thread"};
  const recovery = {...value, actor: replacement, binding_current: false, actor_binding_current: true,
    now: "2031-01-01T00:00:00Z"};
  const inspected = planAgentOperationHandoff({...recovery, action: "inspect"});
  assert.deepEqual(inspected.route, value.actor);
  assert.deepEqual((inspected.access as JsonObject).owner, replacement);
  assert.equal((inspected.access as JsonObject).permission, "historical_evidence_only");
  assert.equal(inspected.execution_allowed, false);
  assert.throws(() => planAgentOperationHandoff({...recovery, action: "consume", consumption_id: "attempt-2"}));
  const outcome: JsonObject = {schema_version: "loopx_operation_outcome_v0", operation_id: "operation-1",
    payload_digest: "payload", confirmation_digest: "confirmation", claim_id: "claim-1",
    executor_revision: AGENT_OPERATION_REVISION, consumption_id: "attempt-1", outcome: "not_executed",
    projection_verified: true, simulation: false, external_write_performed: false,
    evidence_refs: ["receipt:original-system-reconciliation"], reconciles_outcome_digest: "unknown-result-digest"};
  const report = planAgentOperationHandoff({...recovery, action: "report", outcome});
  assert.equal(report.execution_allowed, false);
  assert.equal(report.write_reconciliation, true);
  assert.deepEqual((report.report_provenance as JsonObject).owner, replacement);
  assert.deepEqual((report.report_provenance as JsonObject).original_route, value.actor);
  for (const rejected of [
    {...recovery, actor_binding_current: false},
    {...recovery, binding_current: true},
    {...recovery, actor: {...replacement, agent_id: "other-agent"}},
    {...recovery, actor: {...replacement, goal_id: "other-goal"}},
  ]) {
    assert.throws(() => planAgentOperationHandoff({...rejected, action: "inspect"}));
    assert.throws(() => planAgentOperationHandoff({...rejected, action: "report", outcome}));
  }
  operation(value).agent_handoff = null;
  assert.throws(() => planAgentOperationHandoff({...recovery, action: "inspect"}));
});

test("bounded inbox retains recovery first and declares overflow instead of silently discarding it", () => {
  const items = Array.from({length: 22}, (_, index) => ({operation_id: `operation-${String(index).padStart(2, "0")}`,
    needs_reconciliation: index === 21, execution_allowed: false}));
  const cursor_scope = "a".repeat(64);
  const page = projectAgentOperationInbox({items, cursor_scope});
  assert.equal((page.items as JsonObject[]).length, 20);
  assert.equal((page.items as JsonObject[])[0].operation_id, "operation-21");
  assert.equal(page.pending_count, 22);
  assert.equal((page.overflow as JsonObject).count, 2);
  assert.equal((page.overflow as JsonObject).next_operation_id, "operation-19");
  assert.equal(items[0].operation_id, "operation-00");
  const rest = projectAgentOperationInbox({items, cursor_scope, cursor: page.next_cursor});
  assert.deepEqual((rest.items as JsonObject[]).map(item => item.operation_id), ["operation-19", "operation-20"]);
  assert.equal(rest.next_cursor, null);
  assert.equal(rest.pending_count, 22);
  assert.throws(() => projectAgentOperationInbox({items, cursor_scope: "b".repeat(64), cursor: page.next_cursor}));
});
