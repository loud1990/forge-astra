# Forge card construction check

This optional check passes generated scripts through Forge's real card reader and
ability constructors without a GUI. It tests parsing and construction, not casting,
target selection, resolution, or game-state changes. Some behavior is evaluated only
during gameplay and cannot be checked here.

Use a separate, complete Forge checkout at the same commit as the evaluation. Build
with a JDK that supports Forge's configured Java version (17 at the tested commit):

```sh
mvn -f /path/to/forge/pom.xml -pl forge-game -am -DskipTests \
  package dependency:build-classpath -Dmdep.outputFile=target/probe-classpath.txt
python scripts/check_forge_scripts.py --forge-root /path/to/forge \
  --output output/construction.json path/to/generated-card.txt
```

The script also accepts multiple card paths and `--java` / `--javac` executable
paths. It compiles the small Java probe in a temporary directory. It does not install
generated cards into Forge or alter the checkout.

Before checking candidates, three upstream controls (Lightning Bolt, Murder, and
Llanowar Elves) plus a two-face Adventure with comments and blank lines must
construct, and an invented API must fail. The probe uses a
positive card ID: Forge's negative-ID display cards skip ability construction and
would incorrectly accept that invalid control. Environment initialization failures
must be investigated before attributing a candidate failure to its script.

JSON results retain the upstream commit and explicitly mark gameplay untested.

For a card whose direct mill ability must target only an opponent, use an independent
targeting contract:

```sh
python scripts/check_forge_scripts.py --forge-root /path/to/forge \
  --contract opponent-mill --output output/targeting.json path/to/generated-card.txt
```

This creates two players on different teams in a headless Forge game and checks
`canTarget` on every direct targeted Mill ability, including alternate casting
abilities. The controller must be rejected and the opponent accepted. Additional
positive and negative controls verify this check before candidates run. Select the
contract from the card's Oracle rules, not from its generated implementation.

The contract does not cast or resolve the spell, and an implementation that targets
through another ability needs a different contract. No direct targeted Mill ability
is reported as inconclusive, never as a pass. The eight-set evaluation used this
check to reproduce an incorrectly accepted self-target in Kitsune's Technique.
