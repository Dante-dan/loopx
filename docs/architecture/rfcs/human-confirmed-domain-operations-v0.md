# RFC: Human-confirmed domain operations (v0)

- **RFC status:** Accepted
- **Supersedes / closes:** none
- **Delivery maturity:** Proposal
- **Authors / owners:** LoopX maintainers and optional domain-provider maintainers
- **Created:** 2026-09-12
- **Last normative revision:** 2026-09-30
- **Implementation baseline:** `72e557586`
- **Related contracts:** [Extensions](../../reference/extensions.md),
  [Effect interpreter](agent-loop-effect-interpreter-v0.md)
- **Language mirror:** [中文版](human-confirmed-domain-operations-v0.zh-CN.md)

The English and Chinese versions are semantic mirrors. Update both when changing
the contract; a difference in their requirements or boundaries is a defect.

Sections 1–11 define the proposed contract, not shipped commands. Section 12
records unresolved implementation choices. This document changes no runtime,
default permission, configuration or user entry point.
Section 13 describes the original-Agent continuation implementation slice;
its deployment and live acceptance remain separate from local validation.

## 1. Decision summary

Use three semantic layers, without requiring three repositories:

| Layer | Responsibility | Proposed code owner |
| --- | --- | --- |
| LoopX interaction | Authenticated human action, immutable request binding, execution claim, original-conversation return and shared presentation | Existing public typed-action, chat and Lark owners |
| Financial domain | Order intent, financial validation, aggregate exposure reservation, order/fill accounting and financial presentation | Optional public finance execution package |
| Venue adapter | Venue products, precision, account modes, API authentication, order submission and venue reconciliation | Independently installed Aqua/Hyperliquid, Futu or other adapter |

Research methods remain in research providers. A strategy proposes an order;
it does not gain execution authority by passing a research gate. Enabling a
research capability must not install credentials or enable trading.

The public finance execution package is a proposed sibling distribution under
`packages/`, not an addition to the existing value-discovery evaluator's
permissions. No new built-in finance capability or package name is registered
by this RFC. Implement the first real consumer before extracting a general
plugin framework.

## 2. Problem and invariants

An operator should receive an exact operation card, click once, and receive the
outcome in that conversation. “Forwarded to an agent” does not establish human
confirmation, execution, or a venue fill.

Invariants:

- Only the trusted interaction ingress can attest to the human click. An agent
  cannot synthesize confirmation through tool arguments or model output.
- The confirmed digest binds all effect-bearing terms, their version, the
  displayed projection, executor revision and destination account reference.
- Changing a material term creates a new request. Execution may select only
  values explicitly permitted by the confirmed bounds.
- Delivery retries cannot submit operations. Submission ambiguity requires
  reconciliation, not a fresh request or blind retry.
- Frontend and Lark read the same request and outcome projection.
- Core remains authoritative for Goal/Todo state; venue evidence remains
  authoritative for orders and fills. Neither chat prose nor a local claim
  proves a financial effect.

## 3. Scope and non-goals

First scope: one immutable, explicitly user-confirmed operation, one registered
executor, automatic receipt and terminal/ambiguous result delivery. Demonstrate
with a simulated financial adapter before real credentials are configured.

This does not turn ordinary Goal steering into a confirmation workflow. Existing
persistent permissions for reading, coordination and reporting remain separate.
No arbitrary tool-name/kwargs execution, shell command in a card, global workflow
DAG, autonomous trading loop, transfer service or cross-venue portfolio engine.

## 4. Audited current owners

| Current code | Verified boundary |
| --- | --- |
| `loopx/chat_action_store.py` | Request digest, idempotency, state-checked proposals; built-in Goal/Todo actions only; `failed` is currently retryable |
| `loopx/chat_actions.py` | Validates and applies built-in actions; local API invocation does not prove a human financial confirmation |
| `loopx/extensions/lark/event_collector.py` | Collector currently selects `im.message.receive_v1`; text readiness is not card-callback readiness |
| `loopx/capabilities/manager_context/roundtrip.py` | Original-conversation return, receipt persistence and transport retry; context delegation is not transaction authority |
| `apps/presentation/dashboard/src/data/chat.ts` | Typed-action schema paired with existing chat action details and controls |
| `packages/loopx-finance-value-discovery/extension.toml` | Optional public research evaluator, permissions empty; research presentation surface, no execution contract |

Reuse these owners through explicit typed extensions. Do not silently append a
financial `apply` case to a generic local HTTP endpoint, or inherit retryable
`failed` behavior for an unknown external submission.

## 5. Architecture and single ownership

### LoopX interaction layer

Core owns the operation envelope: operation ID, schema version, domain/adapter
binding, immutable payload reference and digest, projection digest, expiry,
authorized audience, source session/message/request, verified confirmation
receipt, dispatch claim and outcome reference. Financial payload semantics are
opaque to Core; a hash is binding metadata, not a replacement for displayed
terms.

Extend the typed-action owner rather than creating a second proposal database.
If its authority has migrated by implementation time, use that canonical owner;
do not introduce another Python authority beside it. Reuse envelope, identity
and journal primitives where their lifecycle fits. Goal quota/Todo admission
must never mint permission to execute a financial operation.

Core validates the registered domain contract and invokes only an admitted
executor with a fixed operation kind and schema revision. Models may prepare
proposals and read receipts. The effectful entry point accepts a consumed,
server-issued confirmation receipt; no `confirmed: true` escape hatch.

For Lark, prefer the existing bot transport with `card.action.trigger`. Verify
app/tenant provenance at the transport owner, then operator, chat, original
message, action, digest and expiry. For web, use authenticated owner identity
and origin/CSRF protection against the same authority. An opaque ID, loopback
address, forwarded card or matching display name alone is insufficient.

### Financial domain layer

The optional finance package owns the canonical financial payload and financial
outcome reducer. It does not own a competing confirmation ledger. Domain records
are keyed by the Core operation ID and immutable financial payload digest.

Order terms include venue/product/asset identity, account reference, side,
quantity and units, order type, price bounds, time-in-force, reduce-only,
margin/leverage settings, fee caps and units, optional protective orders,
expiry and evidence time. Decimal quantities must preserve precision.

Account-wide constraints require one reservation authority for all operations
using that account. Checking each card independently is insufficient: concurrent
confirmations could exceed the same remaining budget. The domain reserves
capacity atomically after a Core claim and before submission, accounts for
existing positions/open orders and rejects stale or incomplete account coverage.
Unknown submissions retain their reservation until reconciliation. A process
restart cannot reset the budget. External trades require refreshed account
observations; a local ledger cannot prevent activity through another client.

Preflight checks financial invariants against fresh venue observations. If
precision adjustment, fees, account mode or other material terms would change
outside confirmed bounds, it rejects the operation and requests a new card.
It does not silently edit the confirmed payload. Quantities are not increased
to meet a venue minimum without a new confirmation.

Domain outcomes distinguish accepted, resting, partial fill, full fill,
rejected, cancelled and unknown. Entry and protective orders have separate
results. Fees, funding, capital flows, rebates and PnL remain separate; missing
fee evidence is unknown, not zero. Research evidence can explain a proposed
order, but never substitutes for execution evidence.

### Venue adapter layer

Each adapter declares supported products/order types, minimums/precision,
fee semantics, account modes, authentication requirements, client-ID support
and reconciliation limits. It implements bounded discovery/read/preflight,
submission and reconciliation operations using the platform's official API or
SDK. It never performs a silent fallback to another venue or product.

An Aqua-facing adapter must distinguish Aqua product/builder policy from the
underlying venue protocol; “Hyperliquid supports it” does not establish Aqua
terms, fee attribution or account initialization. A Futu adapter must distinguish
quote access from trading permission, security lot rules, trading sessions,
account region and OpenD unlock requirements. Sharing a normalized contract does
not make these products interchangeable.

The adapter stores credentials in a separately configured private credential
facility. It returns normalized evidence plus bounded references to raw venue
receipts. It cannot change Core grants, user budgets or strategy decisions.
Withdrawals, deposits, key grants and leverage/account-mode changes are not
implicit side effects of an order adapter.

## 6. Lifecycle and failure semantics

Proposed interaction lifecycle:

`prepared → awaiting_confirmation → claimed → outcome_observed`

Cancellation and expiry may terminate an unclaimed request. After claim, Core
tracks dispatch and delivery separately from the domain's execution state.
The executor durably records a stable client order ID and attempt before network
submission. Timeout/crash after dispatch yields `submission_unknown`; reconcile
that original ID before any further effect. A local lock cannot promise exactly
one venue fill. If the venue cannot resolve ambiguity, retain unknown and report
it automatically.

The receipt contains operation ID, domain/adapter revision, confirmed digest,
attempt/client/venue IDs, evidence time, coverage and normalized outcome. The
frontend and Lark consume one versioned projection; they do not independently
recompute fill state. Intermediate updates may update the same operation card.
Return one bounded final conclusion through existing manager roundtrip; do not
overwrite its immutable conclusion for each fill. Subsequent monitoring is a
separate linked workflow.

### M1 implementation map

The first implementation must be reviewed as one cross-entrypoint slice:

- extend the canonical typed-action owner behind `loopx/chat_action_store.py`
  and `loopx/chat_actions.py` only with a provider-neutral operation envelope;
- add a separate authenticated `card.action.trigger` consumer beside the
  text-only path in `loopx/extensions/lark/event_collector.py`, preserving the
  existing WebSocket supervision and callback acknowledgement contract;
- add the operation projection to the existing chat data/details path in
  `apps/presentation/dashboard/src/data/chat.ts` and its owning view, rather
  than a second order store or a local-only page;
- put the simulated financial consumer and its order/result schemas in the
  optional finance execution distribution, with no exchange or signer calls;
- use `manager_context` only for the original-conversation result return and
  delivery retry. It must not become the confirmation or financial ledger.

M1 is incomplete if any of the frontend, Lark, simulated consumer, or receipt
recovery parts is missing. A backend-only PR must be labelled partial.

## 7. Alternatives and privacy

- A parameterized tool alone is insufficient: it lacks durable human identity,
  request binding, ambiguous-submission recovery and transport-independent
  receipts. A tool can be the proposal/readback interface to this contract.
- A venue-specific bot containing confirmation, risk and API logic duplicates
  the next platform's infrastructure. Keep transport and finance semantics apart.
- A universal Core finance engine places exchange rules and financial authority
  in the wrong owner. Generic cards consume domain-owned fields and validators.
- A separate domain database may store payloads, reservations and receipts, but
  must not store its own writable Goal progress or independent confirmation.

Reusable protocol, checks, methods and adapters can be public. Repository
visibility is independent from semantic layer. Account IDs, actual orders,
limits, personal strategies, group bindings, credentials and raw private data
remain in ignored local storage. Sharing code never grants access to an account.

## 8. Migration and rollback

Feature off by default. Existing Goal/Todo actions and read-only finance
installations retain their behavior and permissions. Mixed-version hosts reject
unsupported operation/schema revisions explicitly. Disabling an adapter blocks
new proposals/submissions while retaining readable receipts and reconciliation
for claimed operations. Uninstallation must not discard outstanding-order or
unknown-submission records. Revoke credentials only through explicit user setup;
removing a package does not cancel venue orders.

## 9. Validation and user entry points

| Claim | Required evidence | Boundary |
| --- | --- | --- |
| Exact operation | Alter each effect-bearing field, digest, expiry and executor revision | Changed requests cannot reuse confirmation |
| Authenticated click | Wrong app/tenant/operator/chat/message; forwarded card; forged local request | No execution; actionable feedback |
| One claim | Concurrent web/Lark clicks and restart replay | One claim; one original client ID |
| Aggregate limit | Two simultaneous orders both fit alone but exceed shared capacity | At most valid reserved capacity submits |
| Ambiguous submission | Venue accepts, response lost, process restarts | Read-only reconciliation, no blind resubmit |
| Financial outcome | Partial fill, protection failure, currency mismatch, duplicated fills, missing history | Explicit uncertainty and correct accounting |
| Automatic return | Lost delivery then restart | Same request receives outcome; no new execution |
| Product completeness | Existing chat detail and Lark card against same backend, desktop/mobile, packaged frontend | Status, terms, disabled controls and failures agree |
| Feature off | Existing actions and both research providers | No behavior or permission change |

Simulated results must be visibly marked on every surface. Passing simulation
does not establish platform callback configuration, credential readiness or live
trade acceptance. Live acceptance requires an actual human click and matched
venue evidence; the development agent must not manufacture either.

## 10. Operations

Expose callback health separately from text-listener health. Distinguish pending
confirmation, expired, dispatch unknown, receipt pending and delivery failed.
Do not expose callback tokens, signer data or raw sensitive errors in groups.
Surface unsupported product/mode and incomplete account coverage before offering
an executable confirmation. Keep a bounded reconciliation and delivery worker;
reuse existing supervision instead of a dedicated business automation prompt.

## 11. Delivery plan

| Milestone | Cohesive delivery | Exit evidence |
| --- | --- | --- |
| M1 | Extend generic typed-action owner, authenticated Lark callback and existing frontend details with one simulated finance consumer | Same request confirmed once across both entries; result auto-return; feature-off parity |
| M2 | Public finance contract/reducer/reservation owner plus isolated Aqua adapter; live still disabled | Precision/cost/mode and concurrent-budget checks; installed conformance and read-only account qualification |
| M3 | User configures credentials and confirms one exact order | Matched real submission/fill/reconciliation/return evidence; no mock claimed as live |
| M4 | Second venue adapter only when a real caller needs it | Same conformance contract, documented unsupported features and platform-specific checks |

M1 spans UI and backend; do not split it into a completed backend PR and forgotten
frontend work. Keep draft cross-repository PR dependencies explicit. First
extract the actual shared seam, not a speculative adapter framework.

## 12. Open implementation decisions

1. **Canonical action owner:** re-audit typed authority at implementation time;
   extend its existing storage/transaction owner. Maintainer-owned M1 decision.
2. **Public finance package identity:** recommend a separate optional execution
   distribution to keep research installation read-only. Confirm naming and
   admission only with the M1/M2 real caller; no registry entry in this RFC.
3. **Venue distribution:** a collaboration repository may host adapters in
   independent packages. Verify license, permission isolation and installation;
   do not append signing to an existing quote collector. Adapter maintainer M2.
4. **Deployment qualification:** verify the actual Lark app callback and
   authenticated web-owner mechanism. A healthy event process alone is not
   evidence that either user path works. Required before M1 acceptance.

## 13. Original-Agent continuation slice

For an existing, user-authorized Agent that already owns a domain's browser or
adapter workflow, do not require a new API credential path just to return an
exact human confirmation to that Agent. This is an alternative execution seam,
not a relaxation of the financial preflight, account-wide constraints or
original-source evidence requirements above. Core does not interpret a price,
choose a venue, resume a browser, sign or submit an order.

### Owners and entry points

- The original `operation.execute` proposal in `chat/actions/actions.json`
  remains the only confirmation, claim, consumption and outcome store.
- The explicit executor shape is `{kind: "agent_session", host_surface,
  thread_id, revision: "agent-session-handoff-v0"}`. Preparation checks the
  original registry's exact Goal/registered-Agent/session binding and rejects
  simulation masquerading as real execution. The lifecycle-only
  `source_session_v1` registry currently rejects business-operation preparation;
  this slice does not bypass that owner or enable a replacement instance.
- `operation_agent_handoff.ts` owns admission, one-shot consumption,
  reconciliation binding and bounded Inbox attention. Python supplies locked
  canonical storage, original-registry facts and existing lifecycle guards;
  it is not another decision owner.
- Existing Lark prepare/deliver and authenticated callback handling are reused.
  A successful confirmation leaves the original proposal claimed, with no
  external result. Callback replay, simulator and card-delivery recovery must
  never invoke this Agent's browser or adapter.
- The existing manager Inbox projects locators directly from canonical
  operations, without a copied approval record. Turn-start hooks include them
  in `agent_read_required`. Consumed/unknown obligations sort before unconsumed
  tickets; a 20-item page reports total count, typed overflow reason and next
  operation ID rather than silently dropping work. Inspect that ID directly.
- Dashboard details and the original Lark card use the shared operation frame:
  confirmed/waiting for the original Agent; consumed/waiting for real evidence;
  unknown/reconcile without resubmitting; and a separately verified result.
  The Dashboard remains read-only for human operation confirmation. There is
  no new configuration owner: the original request chooses the executor and
  the existing channel/binding owner remains authoritative.

### Original-runtime CLI

Use the original registry and runtime, not a copied session or another home's
records. These local continuation commands do not require Lark to be installed
or reachable. Preparing/delivering new cards remains subject to its normal
extension and authenticated-ingress checks.

```sh
loopx --registry REGISTRY --runtime-root RUNTIME goal-channel inspect-operation \
  --goal-id GOAL --agent-id AGENT --proposal-id OPERATION \
  --host-surface HOST --thread-id ORIGINAL_THREAD
loopx --registry REGISTRY --runtime-root RUNTIME goal-channel consume-operation \
  --goal-id GOAL --agent-id AGENT --proposal-id OPERATION \
  --host-surface HOST --thread-id ORIGINAL_THREAD \
  --consumption-id STABLE_ATTEMPT --execute
loopx --registry REGISTRY --runtime-root RUNTIME goal-channel report-operation \
  --goal-id GOAL --agent-id AGENT --proposal-id OPERATION \
  --host-surface HOST --thread-id ORIGINAL_THREAD --outcome-json OUTCOME --execute
```

`inspect-operation` and a command without `--execute` never consume authority.
Only the first successful atomic consumption returns `execution_allowed: true`.
It verifies authenticated confirmation, immutable terms, the current original
session, active Goal and expiry, then persists consumption before any browser
effect. Every retry, including the same attempt after a lost response or
restart, returns no execution permission. This intentionally does not promise
exactly-once venue execution: ambiguity requires original-venue reconciliation.

The original Agent reports `loopx_operation_outcome_v0` with the exact operation,
payload and confirmation digests, claim, executor revision, consumption ID,
`projection_verified: true`, `simulation: false`, bounded original evidence
references and separate `external_write_performed`. Outcomes are `executed`,
`not_executed` or `submission_unknown`. Unknown conservatively reports a possible
external effect; a transport success cannot certify a trade or protection order.
References must be safe opaque receipt identifiers, not credentials or private
absolute paths. Domain evidence and private trading journals retain detail.

### Recovery, delivery and remaining acceptance

Consumed or unknown operations remain recovery obligations after expiry and
session rebinding; those changes cannot grant a new execution. Evidence-only
reporting may continue for a stopped/historical Goal through existing lifecycle
guards. Existing exact-instance lifecycle guards remain in place, not an
implicit migration into lifecycle-only registries or another home. Missing
original Goal/Agent registration or an unsupported registry profile is an
explicit error, not permission to transplant the operation.

An unknown original outcome is immutable. A definitive report appends
`operation.reconciliation` and binds `reconciles_outcome_digest` to the exact
original unknown result. Only that evidence closes the recovery obligation.
The original result card is updated by existing delivery recovery; an earlier
unknown-result delivery cannot certify the reconciled result. Its readback must
match the current `initial` or `reconciled` stage. None of these paths resubmits.

The slice does **not** implement immediate host wakeup. Inbox visibility reports
`host_delivery: "not_attempted"`; existing Turn/heartbeat reads are not a host
delivery receipt. Host wakeup must later reuse the original host transport and
publish truthful attempt/readback evidence, without starting a parallel resumed
session. Local synthetic callback, CLI, concurrency, expiry, reconciliation and
packaged-UI checks establish protocol behavior only. Installation, a genuine
group click, original-Agent receipt consumption, real venue/protection evidence
and original-card readback are still required before claiming a live minimum
loop. No synthetic engineering card is sent to a live group for acceptance.
