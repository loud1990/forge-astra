# Verification record — 2026-09-05

Application code checked: `6fc345946b78c6366f07cc7f8f4140a44309503f`.
[CI passed lint, formatting, 51 tests, container build, and packaged CLI startup](https://github.com/loud1990/forge-astra/actions/runs/33982744372).
The application is running in a Docker container inside a Proxmox guest.
This snapshot includes queue draining, interruption recovery, progress health
checks, and CLI commands for listing cards and inspecting review results.
Live Langfuse tracing was re-enabled and verified after the operator restored
the server; the worker is healthy with tracing enabled.

| Requirement | Evidence and result |
| --- | --- |
| LangGraph with an OpenAI-compatible endpoint | `Workflow.build` uses actual conditional graph edges. HTTP contract tests cover minimal chat requests, JSON repairs, custom endpoint paths and credential aliases. Live generation succeeded through the configured LiteLLM/Qwen endpoint. Other providers have not all been individually tested. |
| Autonomous spoiler discovery | The deployed worker completed a poll with 1,209 baselined cards and no new or changed cards. Discovery tests cover pagination, current-day previews, first-seen cards, late preview metadata, corrections, deduplication and schema upgrades. Scryfall does not supply a reliable preview date for every card; the documented baseline/first-seen behavior applies. |
| Search each Oracle clause and reuse upstream scripts/docs | Research records Scryfall queries, resolved cardsfolder entries and documentation from the pinned upstream checkout. Live benchmark reports contain that evidence. The managed source is Card-Forge/forge, not the operator's fork. |
| Block unsupported mechanics and respect implementation PRs | Tests reject prose-only evidence, omitted or unsupported implementations and unmerged/wrong-branch/non-ancestor PRs. A tracked mechanic unblocks after a verified merge plus executable support. The live invented-mechanic benchmark remained blocked. Automatically found PRs are candidates until explicitly associated; new upstream examples can also establish support. |
| Seed, accumulate and reuse knowledge | The packaged seed is present in the container. Integration tests persist model lessons as unverified, retain them across reopening, record reviewed feedback, retrieve it for another generation and export Markdown. The deployed acceptance check separately verified feedback persistence and export. |
| Eight-copy test decks and iteration | Integration tests export 60-card decks containing eight target copies, support cards and lands. Bounded plan/script repairs and explicit feedback/retry are tested. A deployed live acceptance run generated Astra Ember Lance with an eight-copy deck through three real model calls. |
| One set per potential PR | A service-level test discovers cards from two sets together and verifies separate set manifests and exports. Rejected/error candidates do not become installable script/deck files. The application contains no upstream push or PR-creation path. |
| Tiered renamed-card tests | Fourteen live cases span five tiers. The full run passed 12; both failed cases subsequently passed individual rechecks. See [the recorded benchmark](testing.md#recorded-live-generation-check-2026-09-05) for limitations and model settings. |
| Public application repository and Conventional Commits | Published at `loud1990/forge-astra`; implementation, fixes and tests have separate Conventional Commits. The pre-existing Forge checkout remains clean. |
| Container operation on Proxmox | The rebuilt worker starts, preserves its existing history, polls successfully and reports healthy. Runtime acceptance checked installed package resources, real model generation, artifacts and feedback using a separate verification database. |
| Langfuse observability | An in-memory exporter test verifies connected card, graph, node and generation observations. Live API reads after server restoration verified persisted observations, inputs/outputs, token usage, session metadata, tier tags and scores for both passing and review-required benchmarks. Configured model and Langfuse secret keys were absent from both saved trace payloads. |

The runtime acceptance record is stored in the operator's persistent output volume
under `verification/acceptance-20260905T173821Z/2026-09-05/173821-c19d73ac/acceptance.json`.
It used an isolated database, leaving production spoiler history and knowledge
unchanged. The model returned no new lessons for the simple card; the acceptance
check therefore tested explicit feedback storage rather than requiring an
invented discovery. Remote tracing was disabled for that earlier acceptance
subprocess because of the server capacity issue. The live checks below supersede
that observability limitation.

## Live Langfuse verification after restoration

Both checks ran inside the deployed worker using
`qwen3.8-27b-pessoa-5090` through LiteLLM, with tracing enabled and upstream
snapshot `89806371a4d1c5b62be45f833535e89e73a27227`. Evidence was read back
through the Langfuse API after each benchmark completed, rather than relying
only on successful authentication or local export calls.

| Renamed benchmark | Run ID | Result | Observations | Model calls | Total tokens | `script-contract` score |
| --- | --- | --- | --- | --- | --- | --- |
| Astra Ember Lance (Lightning Bolt, tier 1) | `eval-1c9ed0bc00` | Passed static checks and model review; draft script and deck exported | 15 | 3 | 39,434 | 1 |
| Astra Quiet Removal (Fatal Push, tier 2) | `eval-08d4166f11` | Reached the two-revision limit; retained as `needs_review` | 29 | 7 | 101,840 | 0 |

For each trace, verification checked that every observation's parent chain
reached the single benchmark root, all expected graph stages were present,
and each model generation had its configured model, input, output, end time
and nonzero token usage. Session IDs, tier tags, scores and private trace
visibility were checked, and neither configured secret key appeared in the
trace payload. The second result demonstrates that revisions and a failed
benchmark score are recorded; it is not a passing card-generation result.
Its reviewer claimed the upstream Fatal Push script contains
`ConditionCheckSVar$ X`, but inspection of the pinned source showed no such
parameter. This is an observed model-review error, not evidence of a gameplay
failure; the candidate remains held for review.

Reports and benchmark summaries remain in the persistent output volume under
`evaluations/2026-09-05/<run-id>/`. These runs used isolated evaluation storage.
The production worker retained its 1,209-card baseline and reported an idle,
healthy poll with zero errors after tracing was enabled.

Gameplay execution remains outside this application's scope. No static check,
model review, renamed benchmark or acceptance check above is labeled a gameplay
pass. Controlled scenario execution belongs to the separate harness described
in [the testing design](testing.md).
