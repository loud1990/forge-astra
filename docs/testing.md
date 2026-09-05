# Controlled card tests

Astra currently generates scripts, eight-copy decks, and written test plans.
It does not launch Forge, load an exact game state, or execute an assertion.
The separate gameplay harness remains responsible for those actions.

## What the Forge engine can support

The inspected upstream snapshot is
`ee65ee561739a1c021e7214a38b99e43cf3d5c75`.
Its [testMarkedDamage example](https://github.com/Card-Forge/forge/blob/ee65ee561739a1c021e7214a38b99e43cf3d5c75/forge-gui-desktop/src/test/java/forge/ai/simulation/GameSimulationTest.java#L654)
creates a 3/3 Hill Giant, a Mountain, and Shock in hand; sets the active player
and main phase; simulates a targeted spell; and asserts damage in the copied game.
This is engine-level testing with controlled state, without having to draw into
the desired situation during an ordinary match.

The adapter must distinguish resolving an effect from legally casting a spell.
Forge's `CastSpellFromHandAction` test helper explicitly lists mana payment and
timing compliance as unfinished work. Passing a test through a helper that places
a spell directly on the stack would not prove that mana costs are enforced.
`GameSimulator.simulateSpellAbility` instead calls
`ComputerUtil.handlePlayingSpellAbility`; the harness should test both successful
and rejected casts before relying on this path for legality assertions.

## Proposed Astra Ember Lance scenarios

For a renamed Lightning Bolt, start with the generated script loaded in an
isolated Forge test profile. Put Astra Ember Lance in player A's hand, give A
priority in a specified phase, and place an ordinary creature on B's battlefield.
Explicitly fix all other state so protection, prior damage, counters, or other
effects cannot accidentally change the expected result.

| Scenario | Setup and action | Expected engine result |
| --- | --- | --- |
| Lethal damage | Opponent controls a vanilla 3/3; A has one red mana in the pool; cast Lance at the creature | Red mana is spent, Lance leaves the hand and resolves into the graveyard, target moves to the graveyard after state-based actions |
| Surviving target | Same setup with a vanilla 4/4 | Creature remains on the battlefield with exactly 3 damage marked before cleanup |
| Mana activation | Replace floating mana with an untapped Mountain; activate its mana ability and cast Lance | Mountain becomes tapped, generated red mana is spent, spell resolves |
| No red mana | A has no mana and no usable source; attempt to cast Lance | Casting is rejected, Lance remains in hand, game state is unchanged |
| Player target | Cast Lance at a player starting at 20 life | Target player ends at 17 life |
| Indestructible | Target an indestructible 3/3 with no other effects | It stays on the battlefield with 3 damage marked |

These are specifications, not an implemented scenario file format. A future
adapter should accept initial zones, card identities, mana or mana sources,
active player, phase and priority, deterministic actions and choices, and
post-resolution assertions. Capture the Forge commit, generated script hash,
scenario version, action log, and relevant state in each result.

## Passing criteria

Use separate outcomes for source/DSL validation, model review, and engine
scenario execution. Static checks catch unknown abilities, missing references,
metadata mistakes, and common semantic mismatches. They cannot establish the
behavior of the full engine, interacting effects, or player choices.

A functional pass means the expected game state and events are observed for
every required scenario. Script text need not match a reference implementation.
For renamed copies, an additional differential test can run the original and
generated card in equivalent states and compare their outcomes. Independent
rules assertions still matter because an upstream implementation may have bugs.
Scenario coverage should grow with card complexity: both branches and threshold
values for conditions, each loyalty ability and activation limit for planeswalkers,
and interactions between abilities, zones, and replacement effects for higher tiers.

Even a complete scenario suite establishes correctness only for its tested
cases. Astra's current `gameplay_tested: false` remains truthful until the
external harness provides execution results.

## Recorded live generation check, 2026-09-05

The LiteLLM model `qwen3.8-27b-pessoa-5090` was tested against all 14 renamed
benchmark cards using the upstream snapshot above. The full run
`eval-b1c745dc32` passed 12 of 14 cases. Murder exhausted structured-output
repairs; Bonecrusher Giant selected a valid support card outside the initial
deck candidate pool.

After resolving additional support choices against upstream, individual rechecks
passed Murder (`eval-9975b487ed`) and Bonecrusher Giant (`eval-ed764792da`).
Both rechecks enabled the endpoint's optional JSON-object mode. The request used
temperature 0.1, a 6,000-token limit, and `enable_thinking: false` inside
`chat_template_kwargs`. Those are model-specific settings, not requirements for
other OpenAI-compatible endpoints.

Thus each case has a passing static/model-review result across these runs;
this is not a claim of a single 14/14 run, measured reliability over repeated
trials, or functional gameplay verification. The invented unsupported mechanic
passed by remaining blocked, as intended. Detailed artifacts stay under the
operator's ignored `output/evaluations/` directory.
