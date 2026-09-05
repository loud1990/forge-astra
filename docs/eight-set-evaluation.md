# Eight-set pipeline evaluation — 2026-09-05

The 80-card baseline completed with **27 drafts, 37 needing review, and 16 blocked**.
No card or set ended in a transport error. Independent checks found **two incorrect
accepted scripts and one invalid accepted deck**. Successful model review therefore
cannot be treated as proof that a card works. Ten focused rechecks produced five
drafts, including another incorrect version of Airbender Ascension.

## Scope and reproducibility

“Past eight sets” means the latest eight main paper expansion/core releases as of
2026-09-05, including Universes Beyond main sets and excluding supplemental products.
Release selection was checked against the [Wizards set archive](https://magic.wizards.com/en/products/card-set-archive)
and Scryfall set data. The [frozen 80-card input](../examples/evaluations/eight-sets-2026-09-05.json)
contains the exact card identities, Oracle text, faces and Scryfall source links.
This Hobbit sample contains ten different cards from the [earlier eight-card run](hobbit-evaluation.md).

Each set includes all five colors, a multicolor legend, an artifact, an enchantment,
a nonbasic land, and a planeswalker or another complex card. The sample spans simple
creatures and spells, conditions, alternate costs, multiple triggers, Vehicles,
Adventures, transforming cards and prepared cards. Specific mechanics include Recruit,
Enduring Story, Teamwork, Power-up, Infusion, Paradigm, Sneak, Blight, Airbend,
Earthbend, Web-slinging, Station and Void. It is a deliberately varied diagnostic
sample, not a random estimate of accuracy across all cards.

| Set | Release | Draft | Needs review | Blocked |
| --- | --- | ---: | ---: | ---: |
| [The Hobbit (HOB)](https://scryfall.com/sets/hob) | 2026-08-14 | 4 | 4 | 2 |
| [Marvel Super Heroes (MSH)](https://scryfall.com/sets/msh) | 2026-06-26 | 4 | 5 | 1 |
| [Secrets of Strixhaven (SOS)](https://scryfall.com/sets/sos) | 2026-04-24 | 5 | 2 | 3 |
| [Teenage Mutant Ninja Turtles (TMT)](https://scryfall.com/sets/tmt) | 2026-03-06 | 4 | 5 | 1 |
| [Lorwyn Eclipsed (ECL)](https://scryfall.com/sets/ecl) | 2026-01-23 | 5 | 5 | 0 |
| [Avatar: The Last Airbender (TLA)](https://scryfall.com/sets/tla) | 2025-11-21 | 1 | 8 | 1 |
| [Marvel's Spider-Man (SPM)](https://scryfall.com/sets/spm) | 2025-09-26 | 2 | 2 | 6 |
| [Edge of Eternities (EOE)](https://scryfall.com/sets/eoe) | 2025-08-01 | 2 | 6 | 2 |
| **Total** | | **27** | **37** | **16** |

Baseline application: `e5934d391cbba80d5e40fcb800c04f8e14b05d32`.
Forge snapshot: `89806371a4d1c5b62be45f833535e89e73a27227`.
The run lasted 60 minutes, from 21:38:38 to 22:38:45 UTC, with two set workers.
Both workers used `qwen3.8-27b-pessoa-5090` through LiteLLM, temperature 0.1,
6,000 output tokens, thinking disabled, JSON mode, a 300-second request timeout,
two allowed script revisions, and four examples per Oracle clause.
The installed workflow file's SHA-256 was checked against the baseline commit;
[the machine-readable record](evaluations/eight-sets-2026-09-05.json) preserves it.

All 80 selected identities were held out in every set worker, including face aliases.
That hid **81 upstream script files**, including the separate Rampant Growth script
used by Studious First-Year's `CopyFaceFrom`. Exclusions are connection-local and
restore automatically; the source checkout is never edited. This prevents retrieval
of the existing answers, but does not rule out the model remembering a card from its
training data. Renamed tier benchmarks remain useful for that separate concern.
Evaluation databases and artifacts are isolated from production history. All eight
manifests contain exactly ten cards from a single set. No upstream PR was opened.

## Confirmed defects and fixes

| Finding | Evidence | Change |
| --- | --- | --- |
| Kitsune's Technique accepted an illegal target | Its generated Mill ability used `ValidTgts$ Player` for “target opponent.” Forge's actual targeting API allowed the controller as a target for both normal and Sneak casting; the upstream opponent restriction rejected that target. | A narrow validator rejects unrestricted Player targeting for a single opponent-only mill instruction. The public targeting probe has both positive and negative controls. |
| Airbender Ascension's quest condition was wrong | With four QUEST counters, `Count$CardCounters.QUEST GE4` evaluated to zero. Forge interpreted `QUEST GE4` as a different counter name; the numeric QUEST count evaluated to four. | Reject comparisons appended to numeric counter expressions; require the threshold in a supported comparison construct. |
| Improvisation Capstone exported an invalid main deck | Its 60-card deck included four copies of the Scheme **When Will You Learn?**. Forge's ordinary card database did not resolve that Scheme. The other 218 distinct exported card names resolved. | Exclude supplementary card types from both support retrieval and out-of-pool name resolution. Ordinary legal-card and rejected-Scheme paths have regression tests. |
| Airbender Ascension's recheck still failed | The replacement `Count$Compare Y GE4` loaded successfully but threw `ArrayIndexOutOfBoundsException` when evaluated. Forge requires true and false result branches after the comparison. | Added a second validator check, covering missing branches and valid numeric/named branches. This was verified against the retained failed artifact; no further generation was run to chase a pass. |
| Prepared cards stopped before generation | Studious First-Year / Rampant Growth has a supported Forge `Prepare` layout, but the application did not recognize the Scryfall layout. | Support two prepared faces and preserve their metadata; regression coverage includes a renamed prepared card and a malformed single-face input. |
| Reminder text became separate required abilities | Sentence splitting detached reminder sentences from Recruit and Prepare, forcing the planner to invent separate implementations or reject the card. | Split Oracle sentences outside parentheses, with nested/unclosed reminder coverage. The real-card rechecks still encountered other planning failures. |
| Ability words were treated as missing engine keywords | Infusion and Raid could be blocked for lacking APIs with those names, despite implementations using ordinary conditions and effects. | Load Scryfall's ability-word catalog and retrieve executable examples whose Oracle text uses that label. Clauses still require valid citations, and explicit engine/PR blockers remain enforced. |

The expression behavior above follows the pinned
[Forge AbilityUtils implementation](https://github.com/Card-Forge/forge/blob/89806371a4d1c5b62be45f833535e89e73a27227/forge-game/src/main/java/forge/game/ability/AbilityUtils.java),
including its required `Compare` result branches. The narrow guards catch the observed
forms; they are not a complete interpreter or proof of semantic equivalence.

## Focused rechecks

Recheck campaign `campaign-48a2ded55c` used application `9e6acd9`, the same Forge
snapshot and model settings, and **all 80 original cards held out**, although only
ten were regenerated. It ran from 22:40:53 to 22:46:06 UTC. The later fixes in
`1d965cc` reject the malformed recheck expression and supplementary deck cards.
These selected before/after results are diagnostic; multiple changes and model
variation prevent attributing each improvement to one fix.

| Card | Baseline | Recheck |
| --- | --- | --- |
| Sound the Trumpets | needs_review | blocked |
| Tidings of War | needs_review | blocked |
| Moseo, Vein's New Dean | blocked | draft |
| Studious First-Year // Rampant Growth | blocked | needs_review |
| Kitsune's Technique | draft | needs_review |
| Rime Chill | draft | draft |
| Fire Nation Raider | blocked | draft |
| Invasion Submersible | needs_review | draft |
| Airbender Ascension | draft | draft; engine expression check failed |
| Chorale of the Void | blocked | blocked |

Moseo, Fire Nation Raider and Invasion Submersible improved to draft status; Rime
Chill remained a draft. Their scripts loaded in Forge, but complete gameplay behavior
has not been verified. Kitsune's Technique remained held for an invalid citation;
its regeneration did not establish a repaired, working card. Studious First-Year
advanced past layout handling but still failed executable-evidence validation.
Sound the Trumpets, Tidings of War and Chorale of the Void remained blocked.

## What remains unreliable

The model still invents or misquotes evidence, rejects valid adaptations of generic
Forge primitives, and sometimes places full card metadata inside ability-only output.
Unique flavor labels such as M.O.D.O.K.'s named abilities can still trigger false
“new engine mechanic” claims; the catalog fix covers recognized ability words, not
all descriptive labels. A blocked card is therefore not evidence that Forge needs
new Java support. Turtle Van's doubling effect and several other blocked cards need
better retrieval and reasoning before making that judgment.

Review can contradict itself: Tezzeret's final review repeatedly described its
implementation as correct inside a nonempty issue, leaving it in `needs_review`.
Some generated scenario plans also misstate rules or support-card behavior. For
example, the Improvisation Capstone plan calls Thrumming Stone mana ramp, and an
Enduring Story plan expects an established story to be rechecked after the qualifying
permanent count falls. Human-written expected outcomes and controlled engine
scenarios are needed to test these claims.

## Verification and limits

- **109 automated tests passed**, with lint and formatting checks. The new tests
  cover campaign isolation, prepared layouts, reminders, ability-word grounding,
  targeted mill restrictions, counter expressions and ordinary-deck support types.
- All **27 baseline drafts and five recheck drafts** constructed their cards and
  abilities in the actual pinned Forge engine. Four valid controls, including an
  Adventure with blank lines, loaded; an invented API failed. Construction does
  not evaluate every expression, choose targets, pay costs, or resolve effects.
- Separate controlled engine probes reproduced the targeting defect and both
  Airbender expression defects. These did not cast and resolve complete spells.
- All 27 baseline decks contained exactly 60 cards and eight target copies. The
  database lookup exposed the Scheme problem despite correct deck arithmetic.
- Langfuse API readback verified **80 baseline traces / 281 model calls / 6,008,700
  total tokens**, plus **10 recheck traces / 28 calls / 538,235 tokens**. Parent
  chains, model inputs/outputs, usage, completion times, tags and review scores
  were checked. All 81 excluded script paths were absent from every generation
  input and artifact evidence/support pool. Configured secret keys were absent
  from the saved trace payloads.
- Application `1d965cc` was deployed to the existing Proxmox guest's Docker worker.
  Its installed workflow hash matches the commit. The worker reported healthy
  after its 22:52:29 UTC poll, with zero errors and the original 1,209-card baseline.
  All 81 excluded scripts were visible again; the upstream checkout remained clean.

**No result here is labeled a full gameplay pass.** At least three of the baseline
accepted artifact bundles have a confirmed script or deck defect. Revalidating the
retained artifacts with the final guards detects those known forms, but the remaining
drafts still need scenario tests, especially boundary conditions, optional choices,
replacement effects, alternate costs and multiple simultaneous abilities.

To run the frozen sample on a prepared checkout:

```sh
forge-astra evaluate-sets examples/evaluations/eight-sets-2026-09-05.json --workers 2 --no-sync
```

`--no-sync` preserves the currently prepared snapshot; it does not select the recorded
commit automatically. Set workers remain limited to two. Focused Python callers can
pass the original sample as `holdout_cards` to `evaluate_sets` while regenerating a
subset. Follow the [Java probe instructions](../scripts/forge_probe/README.md) for
engine construction and opponent-targeting checks.

Raw baseline artifacts remain under `output/campaigns/campaign-59f35e4167/` and
rechecks under `output/rechecks/campaigns/campaign-48a2ded55c/` in the operator's
ignored local output and persistent container volume. Full prompts, private
observability links and credentials are not published in this report.

## All 80 selected cards

Colors below are color identity (`C` means colorless). “Draft” records the original
pipeline decision, including the false passes discussed above. Card links identify
the frozen source; linked pages may change after this run.

| Set | Card | Colors | Type / layout | Baseline result |
| --- | --- | --- | --- | --- |
| HOB | [Dwarven Provisioner](https://scryfall.com/card/hob/9/dwarven-provisioner) | W | Creature — Dwarf Citizen | draft |
| HOB | [Sound the Trumpets](https://scryfall.com/card/hob/55/sound-the-trumpets) | U | Instant | needs_review |
| HOB | [Rhovanion Rampager](https://scryfall.com/card/hob/82/rhovanion-rampager) | B | Creature — Wolf | needs_review |
| HOB | [Tidings of War](https://scryfall.com/card/hob/115/tidings-of-war) | R | Sorcery | needs_review |
| HOB | [Boughside Wanderers](https://scryfall.com/card/hob/121/boughside-wanderers) | G | Creature — Elf Scout | draft |
| HOB | [Bifur, Melodic Rider](https://scryfall.com/card/hob/147/bifur-melodic-rider) | RW | Legendary Creature — Dwarf Bard | draft |
| HOB | [Great Gilded Boat](https://scryfall.com/card/hob/42/great-gilded-boat) | U | Artifact — Vehicle | needs_review |
| HOB | [Last Light of Durin's Day](https://scryfall.com/card/hob/103/last-light-of-durins-day) | R | Enchantment | blocked |
| HOB | [Elven Passage](https://scryfall.com/card/hob/181/elven-passage) | C | Land | blocked |
| HOB | [Bofur, Reliable Guardian // Concerted Care](https://scryfall.com/card/hob/6/bofur-reliable-guardian-concerted-care) | W | Legendary Creature — Dwarf Scout / Instant — Adventure; adventure | draft |
| MSH | [Agent Phil Coulson](https://scryfall.com/card/msh/4/agent-phil-coulson) | W | Legendary Creature — Human Spy Hero | needs_review |
| MSH | [We Say Thee Nay!](https://scryfall.com/card/msh/82/we-say-thee-nay!) | U | Instant — Arcane | draft |
| MSH | [Roxxon Brutes](https://scryfall.com/card/msh/113/roxxon-brutes) | B | Creature — Human Berserker Villain | draft |
| MSH | [Repulsor Blast](https://scryfall.com/card/msh/150/repulsor-blast) | R | Sorcery | needs_review |
| MSH | [Serpent Specialist](https://scryfall.com/card/msh/186/serpent-specialist) | G | Creature — Human Snake Villain | draft |
| MSH | [The Kingpin of Crime](https://scryfall.com/card/msh/220/the-kingpin-of-crime) | BW | Legendary Creature — Human Villain | needs_review |
| MSH | [M.O.D.O.K.](https://scryfall.com/card/msh/106/modok) | B | Legendary Artifact Creature — Villain | blocked |
| MSH | [Claim the Kingdom](https://scryfall.com/card/msh/163/claim-the-kingdom) | G | Enchantment — Plan | needs_review |
| MSH | [Villainous Hideout](https://scryfall.com/card/msh/276/villainous-hideout) | C | Land | draft |
| MSH | [Tony Stark // The Invincible Iron Man](https://scryfall.com/card/msh/80/tony-stark-the-invincible-iron-man) | RU | Legendary Creature — Human Artificer Hero / Legendary Artifact Creature — Human Hero; modal_dfc | needs_review |
| SOS | [Stand Up for Yourself](https://scryfall.com/card/sos/34/stand-up-for-yourself) | W | Instant | draft |
| SOS | [Muse's Encouragement](https://scryfall.com/card/sos/61/muses-encouragement) | U | Instant | needs_review |
| SOS | [Moseo, Vein's New Dean](https://scryfall.com/card/sos/91/moseo-veins-new-dean) | B | Legendary Creature — Bird Skeleton Warlock | blocked |
| SOS | [Improvisation Capstone](https://scryfall.com/card/sos/120/improvisation-capstone) | R | Sorcery — Lesson | draft |
| SOS | [Studious First-Year // Rampant Growth](https://scryfall.com/card/sos/162/studious-first-year-rampant-growth) | G | Creature — Bear Wizard / Sorcery; prepare | blocked |
| SOS | [Quandrix, the Proof](https://scryfall.com/card/sos/218/quandrix-the-proof) | GU | Legendary Creature — Elder Dragon | draft |
| SOS | [Strixhaven Skycoach](https://scryfall.com/card/sos/252/strixhaven-skycoach) | C | Artifact — Vehicle | draft |
| SOS | [Additive Evolution](https://scryfall.com/card/sos/139/additive-evolution) | G | Enchantment | draft |
| SOS | [Great Hall of the Biblioplex](https://scryfall.com/card/sos/257/great-hall-of-the-biblioplex) | C | Land | needs_review |
| SOS | [Ral Zarek, Guest Lecturer](https://scryfall.com/card/sos/97/ral-zarek-guest-lecturer) | B | Legendary Planeswalker — Ral | blocked |
| TMT | [Grounded for Life](https://scryfall.com/card/tmt/7/grounded-for-life) | W | Instant | draft |
| TMT | [Kitsune's Technique](https://scryfall.com/card/tmt/42/kitsunes-technique) | U | Instant | draft |
| TMT | [Bebop, Warthog Warrior](https://scryfall.com/card/tmt/59/bebop-warthog-warrior) | B | Legendary Creature — Boar Mutant Warrior | draft |
| TMT | [Broadcast Takeover](https://scryfall.com/card/tmt/86/broadcast-takeover) | R | Sorcery | draft |
| TMT | [Rocksteady, Crash Courser](https://scryfall.com/card/tmt/131/rocksteady-crash-courser) | G | Legendary Creature — Rhino Mutant | needs_review |
| TMT | [Krang & Shredder](https://scryfall.com/card/tmt/153/krang-&-shredder) | BU | Legendary Creature — Utrom Human Ninja | needs_review |
| TMT | [Turtle Van](https://scryfall.com/card/tmt/181/turtle-van) | C | Artifact — Vehicle | blocked |
| TMT | [Does Machines](https://scryfall.com/card/tmt/34/does-machines) | U | Enchantment — Class; class | needs_review |
| TMT | [Northampton Farm](https://scryfall.com/card/tmt/188/northampton-farm) | C | Land | needs_review |
| TMT | [Party Dude](https://scryfall.com/card/tmt/128/party-dude) | G | Enchantment — Class; class | needs_review |
| ECL | [Wanderbrine Preacher](https://scryfall.com/card/ecl/41/wanderbrine-preacher) | W | Creature — Merfolk Cleric | draft |
| ECL | [Rime Chill](https://scryfall.com/card/ecl/64/rime-chill) | U | Instant | draft |
| ECL | [Blighted Blackthorn](https://scryfall.com/card/ecl/90/blighted-blackthorn) | B | Creature — Treefolk Warlock | needs_review |
| ECL | [Burning Curiosity](https://scryfall.com/card/ecl/129/burning-curiosity) | R | Sorcery | draft |
| ECL | [Chomping Changeling](https://scryfall.com/card/ecl/172/chomping-changeling) | G | Creature — Shapeshifter | draft |
| ECL | [High Perfect Morcant](https://scryfall.com/card/ecl/229/high-perfect-morcant) | BG | Legendary Creature — Elf Noble | needs_review |
| ECL | [Gathering Stone](https://scryfall.com/card/ecl/257/gathering-stone) | C | Artifact | draft |
| ECL | [Sapling Nursery](https://scryfall.com/card/ecl/192/sapling-nursery) | G | Enchantment | needs_review |
| ECL | [Eclipsed Realms](https://scryfall.com/card/ecl/263/eclipsed-realms) | C | Land | needs_review |
| ECL | [Oko, Lorwyn Liege // Oko, Shadowmoor Scion](https://scryfall.com/card/ecl/61/oko-lorwyn-liege-oko-shadowmoor-scion) | GU | Legendary Planeswalker — Oko / Legendary Planeswalker — Oko; transform | needs_review |
| TLA | [Water Tribe Captain](https://scryfall.com/card/tla/41/water-tribe-captain) | W | Creature — Human Soldier Ally | needs_review |
| TLA | [Accumulate Wisdom](https://scryfall.com/card/tla/44/accumulate-wisdom) | U | Instant — Lesson | needs_review |
| TLA | [Fire Nation Raider](https://scryfall.com/card/tla/135/fire-nation-raider) | R | Creature — Human Soldier | blocked |
| TLA | [Jet's Brainwashing](https://scryfall.com/card/tla/143/jets-brainwashing) | R | Sorcery | needs_review |
| TLA | [Earth Kingdom General](https://scryfall.com/card/tla/173/earth-kingdom-general) | G | Creature — Human Soldier Ally | needs_review |
| TLA | [Hama, the Bloodbender](https://scryfall.com/card/tla/224/hama-the-bloodbender) | BU | Legendary Creature — Human Warlock | needs_review |
| TLA | [Invasion Submersible](https://scryfall.com/card/tla/57/invasion-submersible) | U | Artifact — Vehicle | needs_review |
| TLA | [Airbender Ascension](https://scryfall.com/card/tla/6/airbender-ascension) | W | Enchantment | draft |
| TLA | [Ba Sing Se](https://scryfall.com/card/tla/266/ba-sing-se) | G | Land | needs_review |
| TLA | [The Legend of Kuruk // Avatar Kuruk](https://scryfall.com/card/tla/61/the-legend-of-kuruk-avatar-kuruk) | U | Enchantment — Saga / Legendary Creature — Avatar; transform | needs_review |
| SPM | [Sudden Strike](https://scryfall.com/card/spm/19/sudden-strike) | W | Instant | draft |
| SPM | [Secret Identity](https://scryfall.com/card/spm/43/secret-identity) | U | Instant | blocked |
| SPM | [Swarm, Being of Bees](https://scryfall.com/card/spm/69/swarm-being-of-bees) | B | Legendary Creature — Insect Villain | draft |
| SPM | [Heroes' Hangout](https://scryfall.com/card/spm/79/heroes-hangout) | R | Sorcery | blocked |
| SPM | [Guy in the Chair](https://scryfall.com/card/spm/102/guy-in-the-chair) | G | Creature — Human Advisor | blocked |
| SPM | [Scarlet Spider, Ben Reilly](https://scryfall.com/card/spm/142/scarlet-spider-ben-reilly) | GR | Legendary Creature — Spider Human Hero | blocked |
| SPM | [Bagel and Schmear](https://scryfall.com/card/spm/161/bagel-and-schmear) | W | Artifact — Food | blocked |
| SPM | [Web of Life and Destiny](https://scryfall.com/card/spm/122/web-of-life-and-destiny) | G | Enchantment | needs_review |
| SPM | [Oscorp Industries](https://scryfall.com/card/spm/182/oscorp-industries) | BRU | Land | needs_review |
| SPM | [Norman Osborn // Green Goblin](https://scryfall.com/card/spm/39/norman-osborn-green-goblin) | BRU | Legendary Creature — Human Scientist Villain / Legendary Creature — Goblin Human Villain; modal_dfc | blocked |
| EOE | [Beyond the Quiet](https://scryfall.com/card/eoe/7/beyond-the-quiet) | W | Sorcery | needs_review |
| EOE | [Consult the Star Charts](https://scryfall.com/card/eoe/51/consult-the-star-charts) | U | Instant | draft |
| EOE | [Perigee Beckoner](https://scryfall.com/card/eoe/112/perigee-beckoner) | B | Creature — Horror | needs_review |
| EOE | [Terminal Velocity](https://scryfall.com/card/eoe/163/terminal-velocity) | R | Sorcery | blocked |
| EOE | [Famished Worldsire](https://scryfall.com/card/eoe/182/famished-worldsire) | G | Creature — Leviathan | draft |
| EOE | [Ragost, Deft Gastronaut](https://scryfall.com/card/eoe/224/ragost-deft-gastronaut) | RW | Legendary Creature — Lobster Citizen | needs_review |
| EOE | [Infinite Guideline Station](https://scryfall.com/card/eoe/219/infinite-guideline-station) | BGRUW | Legendary Artifact — Spacecraft | needs_review |
| EOE | [Chorale of the Void](https://scryfall.com/card/eoe/91/chorale-of-the-void) | B | Enchantment — Aura | blocked |
| EOE | [Kavaron, Memorial World](https://scryfall.com/card/eoe/255/kavaron-memorial-world) | R | Land — Planet | needs_review |
| EOE | [Tezzeret, Cruel Captain](https://scryfall.com/card/eoe/2/tezzeret-cruel-captain) | C | Legendary Planeswalker — Tezzeret | needs_review |
