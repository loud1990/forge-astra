"""Run Forge's real card/ability constructors; this does not execute gameplay."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def check(
    forge_root: Path, scripts: list[Path], *, java: str, javac: str, contract: str = "construction"
) -> dict:
    root = forge_root.resolve()
    dependencies = (root / "forge-game/target/probe-classpath.txt").read_text().strip()
    classpath = os.pathsep.join(
        [
            str(root / "forge-core/target/classes"),
            str(root / "forge-game/target/classes"),
            dependencies,
        ]
    )
    sources = sorted((Path(__file__).parent / "forge_probe").glob("*.java"))
    with tempfile.TemporaryDirectory(prefix="astra-forge-probe-") as directory:
        subprocess.run([javac, "-cp", classpath, "-d", directory, *map(str, sources)], check=True)
        command = [
            java,
            "-Djava.awt.headless=true",
            f"-Dforge.resources={root / 'forge-gui/res'}",
            "-cp",
            directory + os.pathsep + classpath,
        ]

        def probe(paths, main="ForgeScriptProbe"):
            paths = [p.resolve() for p in paths]
            result = subprocess.run(
                [*command, main, *map(str, paths)], capture_output=True, text=True, timeout=120
            )
            rows = []
            for line in result.stdout.splitlines():
                fields = line.split("\t", 3)
                if len(fields) == 4 and fields[0] in {"OK", "FAIL"}:
                    rows.append(
                        {
                            "path": fields[1],
                            "passed": fields[0] == "OK",
                            "stage_or_name": fields[2],
                            "detail": fields[3],
                        }
                    )
            if result.returncode not in {0, 1} or [r["path"] for r in rows] != list(
                map(str, paths)
            ):
                raise RuntimeError(
                    "Forge probe did not return every result: " + result.stderr[-2000:]
                )
            return rows

        controls = [
            root / f"forge-gui/res/cardsfolder/{name[0]}/{name}.txt"
            for name in ("lightning_bolt", "murder", "llanowar_elves")
        ]
        adventure = Path(directory) / "adventure.txt"
        adventure.write_text(
            "# Exercise the same comment and blank-line handling as CardStorageReader.\n\n"
            "Name:Astra Reader Control\nManaCost:W\nTypes:Creature Scout\nPT:1/1\n"
            "K:Lifelink\nAlternateMode:Adventure\nOracle:Lifelink\n\nALTERNATE\n\n"
            "Name:Astra Reading Trip\nManaCost:1 U\nTypes:Instant Adventure\n"
            "A:SP$ Draw | NumCards$ 1\nOracle:Draw a card.\n"
        )
        controls.append(adventure)
        invalid = Path(directory) / "invalid.txt"
        invalid.write_text(
            "Name:Astra Invalid Control\nManaCost:R\nTypes:Instant\n"
            "A:SP$ NonexistentAstraApi\nOracle:Draw a card.\n"
        )
        calibration = probe([*controls, invalid])
        if not all(r["passed"] for r in calibration[:-1]) or calibration[-1]["passed"]:
            raise RuntimeError(
                "Forge loader controls failed; candidate results would be unreliable"
            )
        checks = {"valid_controls_accepted": len(controls), "invalid_api_rejected": True}
        if contract == "opponent-mill":
            variants = []
            for target in ("Opponent", "Player"):
                path = Path(directory) / (target + ".txt")
                path.write_text(
                    "Name:Astra Target Control\nManaCost:U\nTypes:Instant\n"
                    f"A:SP$ Mill | ValidTgts$ {target} | NumCards$ 3\n"
                    "Oracle:Target opponent mills three cards.\n"
                )
                variants.append(path)
            targeting = probe(variants, "OpponentMillProbe")
            if not targeting[0]["passed"] or targeting[1]["passed"]:
                raise RuntimeError("Forge opponent-targeting controls failed")
            checks["opponent_targeting_controls_passed"] = True
            rows = probe(scripts, "OpponentMillProbe")
        else:
            rows = probe(scripts)
    return {
        "validation_level": (
            "forge_opponent_mill_targeting"
            if contract == "opponent-mill"
            else "forge_card_and_ability_construction"
        ),
        "gameplay_tested": False,
        "upstream_commit": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip(),
        "calibration": checks,
        "total": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "results": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forge-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--javac", default="javac")
    parser.add_argument(
        "--contract", choices=["construction", "opponent-mill"], default="construction"
    )
    parser.add_argument("scripts", type=Path, nargs="+")
    args = parser.parse_args()
    result = check(
        args.forge_root, args.scripts, java=args.java, javac=args.javac, contract=args.contract
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"Forge {args.contract}: {result['passed']}/{result['total']} passed; resolution remains untested."
    )
    raise SystemExit(int(result["passed"] != result["total"]))
