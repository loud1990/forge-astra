# Verification record — 2026-09-05

Application code checked: `a7f29e4335df1fac852759e91e65d4551b823486`.
[CI passed lint, formatting, 40 tests, container build, and packaged CLI startup](https://github.com/loud1990/forge-astra/actions/runs/33981448378).
The application is running in a Docker container inside a Proxmox guest.

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
| Langfuse observability | The installed Langfuse SDK and LangGraph callback emit connected card, graph, node and generation spans with model usage, session metadata and tags; an in-memory exporter test verifies this without sending credentials in spans. **Full live ingestion remains blocked by the existing Langfuse server's storage capacity.** The server disk change awaits operator authorization. |

The runtime acceptance record is stored in the operator's persistent output volume
under `verification/acceptance-20260905T173821Z/2026-09-05/173821-c19d73ac/acceptance.json`.
It used an isolated database, leaving production spoiler history and knowledge
unchanged. The model returned no new lessons for the simple card; the acceptance
check therefore tested explicit feedback storage rather than requiring an
invented discovery. Remote tracing was disabled for that acceptance subprocess
because of the known server capacity issue; the normal worker retains its
Langfuse configuration.

Gameplay execution remains outside this application's scope. No static check,
model review, renamed benchmark or acceptance check above is labeled a gameplay
pass. Controlled scenario execution belongs to the separate harness described
in [the testing design](testing.md).
