import forge.card.CardRarity;
import forge.card.CardRules;
import forge.game.Game;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.card.CardFactory;
import forge.game.player.Player;
import forge.item.PaperCard;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/** Operator-supplied contract: a direct targeted mill ability must target only opponents. */
public class OpponentMillProbe {
    public static void main(String[] args) throws Exception {
        ForgeScriptProbe.initialize();
        GameRules rules = new GameRules(GameType.Constructed);
        Game game = new Game(List.of(), rules, new Match(rules, List.of(), "Astra targeting check"));
        Player self = new Player("Astra Self", game, 0);
        self.setTeam(0);
        Player opponent = new Player("Astra Opponent", game, 1);
        opponent.setTeam(1);
        game.getPlayers().add(self);
        game.getPlayers().add(opponent);
        boolean failed = false;
        for (String path : args) {
            try {
                CardRules cardRules = new CardRules.Reader().readCard(Files.readAllLines(Path.of(path)));
                Card source = CardFactory.getCard(
                    new PaperCard(cardRules, "AST", CardRarity.Common), self, 2, game);
                int checked = 0;
                for (var ability : source.getSpellAbilities()) {
                    if (ability.getApi() != ApiType.Mill || !ability.usesTargeting()) continue;
                    checked++;
                    ability.setActivatingPlayer(self);
                    boolean ownTarget = ability.canTarget(self);
                    boolean opponentTarget = ability.canTarget(opponent);
                    if (ownTarget || !opponentTarget) {
                        throw new IllegalArgumentException(
                            "Mill targeting: self=" + ownTarget + ", opponent=" + opponentTarget);
                    }
                }
                if (checked == 0) {
                    throw new IllegalArgumentException("No direct targeted Mill ability; contract is inconclusive");
                }
                System.out.println("OK\t" + path + "\t" + source.getName() + "\tchecked=" + checked);
            } catch (Exception | LinkageError error) {
                failed = true;
                System.out.println("FAIL\t" + path + "\ttargeting\t"
                    + error.getClass().getSimpleName() + ": "
                    + String.valueOf(error.getMessage()).replace('\n', ' ').replace('\t', ' '));
            }
        }
        if (failed) System.exit(1);
    }
}
