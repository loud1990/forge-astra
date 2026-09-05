# Hobbit card evaluation — 2026-09-05

Eight cards from [The Hobbit on Scryfall](https://scryfall.com/sets/hob) were
evaluated through the deployed container using `qwen3.8-27b-pessoa-5090` via
LiteLLM, with Langfuse enabled. Both runs used upstream Forge snapshot
`89806371a4d1c5b62be45f833535e89e73a27227`, temperature 0.1, JSON-object mode,
a 6,000-token output limit, and at most two revisions.

## Withholding the reference scripts

All eight cards already have upstream implementations. `evaluate-cards` hides
all eight scripts together, including both faces of the Adventure, from direct
name/ID lookup, similarity search, mechanic examples, keyword examples and deck
support lookup. The database connection uses temporary exclusions; neither the
upstream checkout nor the persistent index is edited. Evaluation state and
lessons are separate from the production spoiler queue.

The model still receives the real card names and Oracle text and can reuse
other upstream cards. This evaluates generation without retrieving the target
scripts; it does not establish that the model has never encountered the cards
during training. Matching a reference script's text is neither required nor
evidence that the excluded script was retrieved.

## First run and defects found

Run `eval-b036db2f04`, application `d6c83e2`, reported **5/8 static/model passes**.
Source inspection found errors in two accepted scripts, so that automated count
must not be treated as five correct implementations.

| Card | Automated result | Inspection result |
| --- | --- | --- |
| Bilbo's Deadly Slice | Draft | Unconditional creature destruction uses the expected primitive. Some written test-plan assertions are vague or incorrect and need review. |
| Dori, Bearer of Friends | Draft | Trample and a self-entering trigger creating one Treasure are present. |
| Vow to Erebor | Draft | **False pass:** duplicate `SubAbility` keys on the spell line discard the pump link. |
| Smaug the Magnificent | Needs review | Final damage targeting omits Battles from “any target.” No installable script exported. |
| Bard, King of Dale | Draft | Draw replacement excludes the first draw in the draw step; token replacement doubles the amount. |
| Bilbo Baggins, Burglar // Take a Glance | Needs review | Planning cited Oracle reminder text for casting from exile. The checker did not offer the actual layout directive as an accepted evidence form. No script exported. |
| Thorin Oakenshield | Blocked | Generated `Ward<1>` syntax was unsupported; the reviewer incorrectly inferred that dynamic Ward itself needed engine work. Storied and dynamic Ward have upstream implementations. |
| Dwalin, Weaponmaster | Draft | **False pass:** `PutCounter` used `Defined$ Equipment.YouCtrl`, which does not enumerate the Equipment for this effect. |

The first run made 29 model calls, using 517,729 reported tokens. All eight
Langfuse traces were read back, and the eight withheld script paths were absent
from every generation input. Reports preserve the original results. A separate
`postfix-audit.json` records that the updated validator rejects Vow and Dwalin.

## Changes driven by the sample

- Reject duplicate ability parameters. Forge parses them into a map, so repeating
  `SubAbility` does not create a sequence. Successive effects need explicit links.
- Reject bare validity filters in `PutCounter`'s `Defined` parameter. A supported
  form is `Defined$ Valid Equipment.YouCtrl`; another is `PutCounterAll` with
  `ValidCards$ Equipment.YouCtrl`.
- Accept an exact, active `AlternateMode` directive matching the input layout
  as executable layout evidence. Oracle text, comments and mismatched layouts
  remain insufficient. Planning instructions now explain this option.
- Recognize `RW` and `R/W` as equivalent hybrid-cost spellings when detecting
  existing cards, while preserving the distinction from two separate `R W` shards.

The parser and effect checks were based on upstream `FileSection.parseToMap`,
`ManaCostShard.parseNonGeneric`, `CountersPutEffect` and
`AbilityUtils.getDefinedCards`, rather than exact reference-script equality.
Regression tests cover the new checks, all retrieval paths, multi-face exclusions,
restoration after exceptions and separation from production state.

## Full recheck after fixes

Run `eval-9dc3d00d72`, application `686d503`, evaluated the same eight cards with
all eight source scripts withheld again. It reported **2/8 static/model passes**,
five `needs_review` results, and one `blocked` result. The prompts and validation
rules changed between runs, so these counts are not a controlled measure of
improvement or a stable success rate.

| Card | Final pipeline result | What the report shows |
| --- | --- | --- |
| Bilbo's Deadly Slice | Needs review | Planner supplied a quotation that did not match the cited evidence; no draft generated. |
| Dori, Bearer of Friends | Draft | Passed again; script and eight-copy deck exported. |
| Vow to Erebor | Needs review | Duplicate parameter fixed. The reviewer incorrectly rejected the valid sequential effect chain and suggested comma-separated sub-abilities. |
| Smaug the Magnificent | Needs review | Draft includes Battles. Reviewer incorrectly demanded that “any target” exclude the source itself. |
| Bard, King of Dale | Draft | Passed again; script and eight-copy deck exported. |
| Bilbo Baggins, Burglar // Take a Glance | Needs review | Layout evidence passed, but the generator repeatedly emitted `AlternateMode` inside the ability-only draft; the application owns that metadata. |
| Thorin Oakenshield | Blocked | Draft used the supported `Ward:1` form. Reviewer still claimed missing engine support and objected to the intentional eight-copy test deck. This is not a confirmed missing mechanic. |
| Dwalin, Weaponmaster | Needs review | Updated validator rejected the unresolved bare Equipment selector. No installable draft exported. |

This run made 36 model calls, using 653,771 reported tokens. All eight completed
Langfuse traces were checked for connected observations, model inputs/outputs,
token usage, set/mode tags and scores. Every generation input excluded all eight
target script paths. Artifact evidence and support-card references also excluded
those paths. The two accepted decks contain exactly eight target copies in
60 cards, and all artifacts are grouped under `hob`.

Postflight checks confirmed that all eight scripts were visible again through
normal lookup, the upstream checkout was clean, and production retained its
1,209-card baseline. The container continues running with Langfuse enabled.
[CI passed all 74 tests, lint, formatting, the container build and CLI smoke check](https://github.com/loud1990/forge-astra/actions/runs/33991257113).

The sample exposed both false acceptance and false rejection by the configured
model. The new deterministic checks prevent the two observed false passes from
silently recurring in those forms. They do not make model review an authoritative
rules judge or prove that every accepted script works in Forge.

## Reproducing the sample

Save a Scryfall JSON list containing the eight cards above, then run:

```sh
forge-astra evaluate-cards hobbit-sample.json --no-sync
```

Omit `--no-sync` to refresh upstream first. The deployed worker retains the
input at `/data/evaluations/hobbit-sample.json`. Results live under
`output/evaluations/2026-09-05/<run-id>/`, grouped only under set `hob`.
Every exported deck contains eight target copies in 60 cards. Rejected cards
retain diagnostic JSON without installable scripts or decks.

These are static validation and model-review results, supplemented by source
inspection. Arbitrary card samples do not have the built-in renamed benchmarks'
independent per-card assertions. No Forge gameplay scenarios were executed;
`gameplay_tested` remains false. Written test plans also require review before
an external harness can use them as acceptance criteria.
