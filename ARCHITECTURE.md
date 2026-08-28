# Architecture

This package does two jobs, and they sit on opposite sides of a trust boundary.

## Reach

Getting an answer out of a source that speaks a different substrate, and knowing
what that answer is worth.

`trust/` (six verification profiles), `switchboard`, `onboarding` (entry-mode
delegation).

This is the half the corroboration stack consumes. `sm-divergence` can resolve a
NANDA Index, a `did:web` document or an HTTP registry on its own; it cannot
verify an ANS SCITT receipt or a DNSSEC chain without these profiles.

`ProofResult` — `profile / method / status / verified_at / evidence_ref /
failure_reason` — is the type that makes it work. An ANS receipt, a DNSSEC chain
and an ed25519 agent card all land in it without either substrate's grammar
dominating.

## Serve

Being a NANDA-compatible registry: converting internal agents to AgentFacts,
serving them, tracking deltas, federating from peers, projecting to AI-Catalog
and A2A.

`router`, `gateway`, `converter`, `store`, `federation`, `feed`, `cli`.

**This half is a registry — a thing the corroboration stack audits, not a
consumer of it.** Every fault fixed in 0.7.0 was here: answering for an
identifier scoped to another registry, dropping fields from a peer's record,
emitting claims the source never made. `tests/test_corroborates_itself.py` points
the auditor at this half in CI, and `provenance` (0.8.0) makes the conversion
declare what it supplied.

That the reach half is rigorously tested and the serve half is where the bugs
were is not a coincidence. `ProofResult` is substrate-neutral by design.
`SmAgentFacts` is NANDA AgentFacts under an `Sm*` prefix, with required fields a
source may not have — a mandatory frame will fill what it is missing.

## The rule

**Reach must not depend on serve.** `tests/test_layer_boundary.py` enforces it,
and proves itself non-vacuous by also asserting that serve *does* depend on
reach.

At runtime the arrow is already one-way. There is one type-level back-reference:
`trust/base.py` and `trust/ans_scitt.py` reference `SmAgentFacts` under
`if TYPE_CHECKING`, while `models.py` imports `ProofResult` for real. Type-only,
so it costs nothing at runtime and is broken by a Protocol or a forward
reference — but it is the one thing standing between here and a clean separation.

## If the halves are ever separated

The seam is where it is because of the rule above, not because of a plan. Nothing
here commits to separating them. If it happens, the order is: break the
type-level back-reference, then move `trust/` + `switchboard` + `onboarding`,
then leave the serving half to depend on the new package.

The naming is not decided and should not be guessed at: both halves are published
and people import from `sm_bridge` today.
