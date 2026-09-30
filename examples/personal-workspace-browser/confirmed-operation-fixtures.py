"""Isolated canonical-store fixtures; never contact a real channel or executor."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import test_chat_operation_actions as fixtures  # noqa: E402


def main() -> None:
    fixtures.GOAL_ID = "product-release"
    with TemporaryDirectory(prefix="loopx-operation-ui-") as root:
        service, store = fixtures._service(Path(root))
        handler = fixtures._managed_handler(service, store)
        native = {
            "thread_id": "owned-managed-thread",
            "host_turn_id": "fixture-native-turn",
        }
        request = fixtures._request()
        terms = request["normalized_parameters"]
        terms.pop("executor")
        terms["projection"].update(
            title="Synthetic managed operation",
            subtitle="Isolated backend fixture; no real account",
            warning="Engineering fixture only. No real channel, financial effect or automatic wakeup.",
            simulated=False,
        )
        proposal = handler(
            "loopx_operation", {"action": "prepare", "request": request}, native
        )["proposal"]
        delivered = store.record_operation_delivery(
            proposal["proposal_id"], delivery=fixtures._delivery(proposal)
        )
        confirmed = store.decide_operation(
            proposal["proposal_id"],
            decision="confirm",
            confirmation=fixtures._confirmation(delivered),
        )
        consumed = handler(
            "loopx_operation",
            {
                "action": "consume",
                "proposal_id": proposal["proposal_id"],
                "consumption_id": "fixture-attempt",
            },
            native,
        )
        assert consumed["execution_allowed"] is True
        waiting = store.load(proposal["proposal_id"])
        unknown = fixtures._agent_result(
            confirmed, "fixture-attempt", result="submission_unknown"
        )
        reported = handler(
            "loopx_operation",
            {
                "action": "report",
                "proposal_id": proposal["proposal_id"],
                "outcome": unknown,
            },
            native,
        )
        assert reported["ok"] is True
        ambiguous = store.load(proposal["proposal_id"])
        final = {
            **unknown,
            "outcome": "not_executed",
            "external_write_performed": False,
            "reconciles_outcome_digest": reported["outcome_digest"],
        }
        recovered = handler(
            "loopx_operation",
            {
                "action": "report",
                "proposal_id": proposal["proposal_id"],
                "outcome": final,
            },
            native,
        )
        assert recovered["ok"] is True
        reconciled = store.load(proposal["proposal_id"])
        print(
            json.dumps(
                {
                    "confirmed": confirmed,
                    "waiting": waiting,
                    "unknown": ambiguous,
                    "reconciled": reconciled,
                }
            )
        )


if __name__ == "__main__":
    main()
