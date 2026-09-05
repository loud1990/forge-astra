import pytest

from forge_astra.corpus import Corpus
from forge_astra.upstream import CARDS, DOCS, GAME, TOKENS


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "forge"
    contents = {
        f"{GAME}/ability/ApiType.java": "    DealDamage(DamageEffect.class),\n    Draw(DrawEffect.class),\n    Mana(ManaEffect.class),",
        f"{GAME}/ability/AbilityFactory.java": 'public static final List<String> additionalAbilityKeys = Lists.newArrayList("ChosenPile", "UnchosenPile");',
        f"{GAME}/trigger/TriggerType.java": "    ChangesZone(TriggerChangesZone.class),",
        f"{GAME}/replacement/ReplacementType.java": "    Moved(ReplaceMoved.class),",
        f"{GAME}/keyword/Keyword.java": '    FLYING("Flying", SimpleKeyword.class),',
        f"{DOCS}/Card-scripting-API.md": "# Forge\nUse proven abilities.\n# Damage\nA:SP$ DealDamage | NumDmg$ 3",
        f"{CARDS}/l/lightning_bolt.txt": "Name:Lightning Bolt\nManaCost:R\nTypes:Instant\nA:SP$ DealDamage | ValidTgts$ Any | NumDmg$ 3 | SpellDescription$ CARDNAME deals 3 damage to any target.\nOracle:Lightning Bolt deals 3 damage to any target.\n",
        f"{CARDS}/b/bird.txt": "Name:Bird\nManaCost:U\nTypes:Creature Bird\nPT:1/1\nK:Flying\nOracle:Flying\n",
        f"{CARDS}/f/fake.txt": "Name:Unsupported\nManaCost:R\nTypes:Creature Bird\nPT:1/1\n# K:Novelty\nOracle:Novelty\n",
        f"{TOKENS}/bird.txt": "Name:Bird Token\nTypes:Creature Bird\nPT:1/1\nK:Flying\n",
    }
    for path, content in contents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    index = Corpus(tmp_path / "corpus.db")
    index.index(root, "a" * 40)
    yield index
    index.close()
