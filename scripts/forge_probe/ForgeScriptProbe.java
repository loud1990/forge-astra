import forge.card.CardRarity;
import forge.card.CardRules;
import forge.card.CardType;
import forge.game.card.Card;
import forge.game.card.CardFactory;
import forge.item.PaperCard;
import forge.util.FileSection;
import forge.util.Lang;
import forge.util.Localizer;
import java.nio.file.Files;
import java.nio.file.Path;

/** Construct abilities in Forge without a game, player controller, or GUI. */
public class ForgeScriptProbe {
    public static void main(String[] args) throws Exception {
        Path resources = Path.of(System.getProperty("forge.resources"));
        Localizer.getInstance().initialize("en-US", resources.resolve("languages").toString());
        Lang.createInstance("en-US");
        FileSection.parseSections(Files.readAllLines(resources.resolve("lists/TypeLists.txt")))
            .forEach(CardType.Helper::parseTypes);
        boolean failed = false;
        for (String arg : args) {
            String stage = "read";
            try {
                CardRules rules = CardRules.fromScript(Files.readAllLines(Path.of(arg)));
                stage = "construct";
                // Negative IDs make Forge build a display-only card and skip its abilities.
                Card card = CardFactory.getCard(
                    new PaperCard(rules, "AST", CardRarity.Common), null, 1, null);
                System.out.println("OK\t" + arg + "\t" + card.getName() + "\t" + card.getStates());
            } catch (Exception | LinkageError error) {
                failed = true;
                StringBuilder detail = new StringBuilder();
                for (Throwable cause = error; cause != null; cause = cause.getCause()) {
                    detail.append(cause.getClass().getSimpleName()).append(": ")
                        .append(cause.getMessage()).append("; ");
                }
                System.out.println("FAIL\t" + arg + "\t" + stage + "\t"
                    + detail.toString().replace('\n', ' ').replace('\t', ' '));
            }
        }
        if (failed) System.exit(1);
    }
}
