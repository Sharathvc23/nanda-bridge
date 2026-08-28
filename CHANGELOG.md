# Changelog

## [0.7.0] — 2026-08-27

Four fixes, all of the same shape: this bridge asserted things the source never
said. Three are breaking. **Upgrade is recommended for every deployment** — one
of these is a security fix.

Read the entries below before upgrading; two of them change what your registry
emits, and one changes which requests it answers.

### Fixed — claims the source never made

- **No certification block unless the source declared one.** `SimpleAgent.certification_level`
  defaulted to `"self-declared"`, so every converted agent carried a certification
  block naming this provider as issuer — including agents that never certified
  anything. The default is now `None` and no block is emitted without one.

  **Breaking** for anyone relying on the old default. The old behaviour asserted a
  trust claim on the source's behalf, indistinguishable in the output from one it
  actually made.

- **A placeholder skill is marked as synthesized.** NANDA requires `minItems: 1`,
  so a source with no skills cannot be represented without one. The placeholder
  stays — removing it would make the record schema-invalid — but the extension
  block now carries `"synthesized": ["skills"]` so a consumer can tell it from a
  skill the source declared, and the placeholder's description says what it is.

  The marker is written *after* the source's own `metadata` is merged, so a source
  cannot supply its own `synthesized` key to hide the fact.

- **`conformance_level` is computed, not asserted.** `ANSEntryConverter.to_entry`
  set `auditable` whenever a checkpoint and root keys were both non-empty strings.
  The field's own docstring says "Computed, not asserted", and
  `conformance.conformance_level` — the real predicate — was never called.

  `to_entry` now calls it. Presence of a checkpoint is not evidence that the
  checkpoint *verifies*; that needs a live check this converter does not perform.
  So the default is `basic`, and a caller that has actually verified passes
  `to_entry(checkpoint_verifies=True)`.

  **Breaking:** entries that previously reported `auditable` on presence alone now
  report `basic` until something verifies them.

### Fixed

- **A federated record keeps fields this model does not declare.** `pull_deltas`
  validates a peer's record into `SmAgentFacts` and stores it, and the gateway
  re-serves what was stored. Pydantic's default is `extra="ignore"`, so every
  undeclared field a peer sent was dropped silently — and we then re-served a
  truncated version of another registry's record as though it were complete,
  with nothing recording that anything had been lost.

  The AgentFacts record tree now inherits `SmRecord`, which sets
  `extra="allow"`. Unknown fields survive validation and round-trip through
  `model_dump`, at both the top level and inside nested objects such as `skills`.

  This is not a licence for this bridge to invent fields: our own converter
  populates only declared ones, so a record we build carries no extras, and a
  test pins that.

  The response wrappers (`SmAgentFactsIndexResponse`, `SmAgentFactsDelta`,
  `SmAgentFactsDeltaResponse`, `SmWellKnown`, `SmTool`, `SmToolsResponse`,
  `SmA2AMessage`) deliberately stay strict — they are our own output, and
  accepting undeclared fields there would let junk into our responses unnoticed.
  A test pins that boundary too.

### Fixed — security

- **An identifier naming another registry no longer resolves against this one.**
  `GET /nanda/resolve` reduced any identifier to a bare id and looked it up
  locally, so `@other-registry:ns/foo` and `did:web:other.example:agents:foo`
  both returned *this* registry's `foo`, carrying *this* registry's `proof`
  block. The caller had no way to tell the scope was ignored. `registry_id` was
  passed to the parser and never read.

  `_parse_agent_identifier` now takes `provider_url` as well and returns `None`
  for an identifier that names an authority we are not. A handle's registry is
  compared against `registry_id`; a `did:web` must be under this provider's host;
  a `urn:` names a foreign authority by construction and is refused.

  **Rejection is `400`, deliberately not `404`.** A `404` is a positive claim
  that the agent is absent. A corroborator comparing registries would read it as
  this registry asserting something about another registry's namespace, and could
  raise a false omission finding against it. A `400` carries no claim.

  Behaviour changes, both intended:
  - `ns:agent` is no longer split to `agent`. A colon is not evidence of a
    namespace — the old rule could not tell a local id from another registry's
    URN or DID, which is what made the flaw reachable.
  - `_parse_agent_identifier` is private, but its signature and return type
    changed (`str` to `str | None`, third argument added).

- **`[feed]` extra now requires `sm-feed>=0.2.0`.** `0.1.x` is incompatible with
  partial pages: `sm-feed` split the page wire version because relaxing the head
  constraint changed its verification contract. Complete pages still declare
  `feed-page/0.1` and a `0.1.x` subscriber verifies them unchanged; partial pages
  declare `feed-page/0.2`.
- **`read_delta_feed` accepts `expected_head`** and passes it to
  `sm_feed.verify_page`. This is the whole of sm-feed's rewind defence (SPEC §5
  rule 6): without it a registry can serve a validly signed head behind the history
  the puller already holds and the rewind is accepted. Optional for compatibility,
  and the docstring says plainly that it should always be passed.
- `read_delta_feed`'s fourth return value is now sm-feed's cursor object —
  `{seq, entry_hash, head, complete_to_head}`. `entry_hash` is still the next
  `expected_prev_hash`, so the existing idiom is unchanged; `head` is what to pass
  back as `expected_head`, and `complete_to_head` is `False` when the registry
  served a bounded prefix of a long backlog.
- Documentation links to the Verifiable Agent Feed now point at the published
  specification (https://verifeed.ai) instead of a repository that is not public.

## [0.6.0] — Verifiable Agent Feed extra

- **`[feed]` extra (additive, non-breaking):** `sm_bridge.feed.build_delta_feed` projects the
  delta log as a signed, hash-chained Verifiable Agent Feed (`sm-feed`); `read_delta_feed`
  verifies a page for authenticity + completeness and returns the verified deltas. Served
  **alongside** `/nanda/deltas` — no change to the existing endpoint, the delta store, or any
  core import. Opt in with `pip install 'sm-bridge[feed]'`.
- Fixed `sm_bridge.__version__` (was pinned at `0.4.1`) to track the release.

## [0.5.0] — authenticated delegated binding write

- Release the registry-side write surface merged in #4: `BindingStore`,
  `RequestAuthenticator`, and `create_binding_write_router` — a delegate applies an
  authenticated, signed binding change through it. These were on `main` but not in a
  published release; 0.5.0 puts them on PyPI (consumed by nanda-connect).

## [0.4.1] — docs

- README rewritten to lead with what the bridge is and does (commercial + OSS tone); removed a
  dead `agentfacts-format` link and trimmed the reference sections into the docs. No code changes.

## [0.4.0] — universal registry onboarding + verification

The v0.4 line turns sm-bridge from a NANDA publication layer into the **universal on-ramp for
the NANDA Index quilt**: any source onboards through one library and emerges with a
normalized, verifiable proof block, while the Index stays strictly pointer-only.

### Added

- **Trust-profile spine** (`sm_bridge.trust`): `ProofResult` (VERIFIED / FAILED /
  NOT_VERIFIED, with the cryptographic-honesty invariant enforced at construction — no
  VERIFIED without a real `evidence_ref`), the `TrustProfile` protocol, and `TrustRegistry`.
- **Six trust-profile adapters** (`[trust]` extra, lazy crypto imports):
  - `ed25519-agentcard` — the NANDA Index agent-card signing contract (JCS + ed25519).
  - `ans-scitt` — the ANS SCITT receipt contract (COSE_Sign1 + RFC 9162 Merkle + issuer binding).
  - `ans-txt` — the ANS `ANS_TXT` DNS discovery profile (split-horizon aware).
  - `dns-aid` — **consumes the upstream `dns-aid` package** (SVCB + DNSSEC + DANE).
  - `jws-catalog` — signed AI-Catalog verification (ES256 detached JWS over the JCS entries;
    catalog-hijack detection).
  - `nanda-delegation` — did:key delegation chains over **ES256 / P-256** detached JWS
    (scope containment, freshness, revocation).
- **Cross-registry switchboard** (`sm_bridge.switchboard`): one resolve surfaces agents from
  heterogeneous registries through a uniform result — entry-mode registries delegate,
  hosting-mode registries resolve locally with a verified proof. One entry per registry.
- **`sm-bridge verify` CLI**: verify a receipt / signed catalog / agent card / DNS-AID record /
  delegation from the terminal (exit 0 = VERIFIED, 1 = FAILED, 2 = NOT_VERIFIED).
- **Runnable demos** (`examples/`): the cross-registry switchboard and domainless-delegation
  scenarios, offline and self-contained.
- **Bidirectional ANS interop, verified against the real reference binaries**: a receipt sm-bridge
  produces is accepted by `ans-verify`, and a receipt the real `ans-tl` transparency log produces
  is verified by the `ans-scitt` profile (baked in as a fixture that runs without a Go toolchain).
- **Dual onboarding modes** (`sm_bridge.onboarding`): `RegistryEntry`, the `EntryModeConverter`
  protocol (no agent-iteration — quilt invariant enforced structurally), `ANSEntryConverter`,
  and `/nanda/registries` + entry-mode delegation-resolve router surface. `reliability_receipts`
  pass-through (attester identity mandatory, no grading).
- **Transparency-log extra** (`[tlog]`): RFC 6962 Merkle over the delta log, signed checkpoint,
  inclusion + consistency proofs (refused below treeSize 3), and `sm_bridge.conformance` — the
  Demo 3 auditor self-test (checkpoint signature, root recomputation, append-only, tamper
  detection). Computed `conformanceLevel`.
- ai-catalog spec alignment: `/.well-known/ai-catalog.json` now emits `{specVersion, host,
  entries}` per the Agent-Card/ai-catalog standard.

### Changed

- `SmAgentFacts.proof` is now a typed `ProofResult | None`. A pre-v0.4 opaque `proof` dict is
  accepted for back-compat but **downgraded to `NOT_VERIFIED(legacy-unverified)`** — it can no
  longer masquerade as verified. `SimpleAgentConverter` emits `ProofResult.legacy()` (it holds
  no cryptographic evidence) rather than a fabricated sha256 placeholder.
- `/nanda/resolve` is now `async` and carries a normalized proof block when a `TrustRegistry`
  is injected and the converter supplies `trust_evidence`.

### Compatibility

- The FastAPI + pydantic core never imports a crypto library (verified in CI); all verifiers
  live in `[trust]` / `[tlog]` and import lazily.
- All v0.3.x endpoints and shapes are preserved. The 51 pre-v0.4 tests pass unchanged except
  one that asserted the old opaque-proof shape (updated to the honest downgrade).

## [0.3.1]

NANDA AgentFacts converter, registry endpoints (`/nanda/*`), AI-Catalog + A2A gateway,
Quilt-style deltas, federation sync.
