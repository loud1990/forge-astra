import re
import subprocess
from pathlib import Path

from forge_astra.http import JsonHTTP

REPOSITORY = "Card-Forge/forge"
UPSTREAM_URL = f"https://github.com/{REPOSITORY}.git"
CARDS = "forge-gui/res/cardsfolder"
TOKENS = "forge-gui/res/tokenscripts"
DOCS = "docs/Card-scripting-API"
GAME = "forge-game/src/main/java/forge/game"
SPARSE_PATHS = [CARDS, TOKENS, DOCS, GAME, "forge-core/src/main/java/forge/card"]


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=300, check=False
    )
    if result.returncode:
        # No repository credentials or environment values in errors.
        raise RuntimeError(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout.strip()


class GitHub:
    def __init__(self, token: str = "", http: JsonHTTP | None = None):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ForgeAstra/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        self.http = http or JsonHTTP("https://api.github.com", headers, interval=0.15)
        self.cache = {}

    def default_branch(self) -> str:
        if "branch" not in self.cache:
            self.cache["branch"] = self.http.request("GET", f"/repos/{REPOSITORY}")[
                "default_branch"
            ]
        return self.cache["branch"]

    def pull(self, number: int) -> dict:
        key = f"pr:{number}"
        if key not in self.cache:
            self.cache[key] = self.http.request("GET", f"/repos/{REPOSITORY}/pulls/{number}")
        return self.cache[key]

    def implementation_prs(self, mechanic: str) -> list[dict]:
        phrase = re.sub(r"[^\w -]", "", mechanic)[:100]
        key = "search:" + phrase
        if key not in self.cache:
            result = self.http.request(
                "GET",
                "/search/issues",
                params={
                    "q": f'repo:{REPOSITORY} is:pr in:title "{phrase}"',
                    "per_page": 10,
                    "sort": "updated",
                    "order": "desc",
                },
            )
            self.cache[key] = [
                {
                    "number": r["number"],
                    "title": r["title"],
                    "url": r["html_url"],
                    "state": r["state"],
                }
                for r in result["items"]
            ]
        return self.cache[key]

    def contains(self, ancestor: str, commit: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{40}", ancestor) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            return False
        if ancestor == commit:
            return True
        key = f"compare:{ancestor}:{commit}"
        if key not in self.cache:
            value = self.http.request("GET", f"/repos/{REPOSITORY}/compare/{ancestor}...{commit}")
            self.cache[key] = value["status"] in {"ahead", "identical"}
        return self.cache[key]

    def merged_in_snapshot(self, number: int, commit: str) -> tuple[bool, str]:
        pr = self.pull(number)
        if not pr.get("merged_at") or not pr.get("merged"):
            return False, f"PR #{number} is not merged (state: {pr.get('state')})"
        base = pr["base"]
        if base["repo"]["full_name"] != REPOSITORY or base["ref"] != self.default_branch():
            return False, f"PR #{number} did not merge into the upstream default branch"
        if not self.contains(pr.get("merge_commit_sha", ""), commit):
            return False, f"PR #{number} merge is not included in snapshot {commit[:12]}"
        return True, f"PR #{number} merged and included in {commit[:12]}"


class Snapshot:
    def __init__(self, path: Path, github: GitHub):
        self.path = path
        self.github = github
        self.commit = ""

    def sync(self, seed: Path | None = None) -> str:
        branch = self.github.default_branch()
        if not (self.path / ".git").exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            args = [
                "git",
                "clone",
                "--filter=blob:none",
                "--depth=1",
                "--sparse",
                "--single-branch",
                "--branch",
                branch,
            ]
            if seed and (seed / ".git").exists():
                args += ["--reference-if-able", str(seed.resolve()), "--dissociate"]
            subprocess.run(
                [*args, UPSTREAM_URL, str(self.path)],
                check=True,
                timeout=300,
                stdout=subprocess.DEVNULL,
            )
            git(self.path, "sparse-checkout", "set", *SPARSE_PATHS)
        if git(self.path, "remote", "get-url", "origin") != UPSTREAM_URL:
            raise RuntimeError("Managed snapshot origin is not Card-Forge/forge")
        if git(self.path, "status", "--porcelain"):
            raise RuntimeError("Managed upstream snapshot has local changes; refusing to overwrite")
        git(self.path, "fetch", "--depth=1", "origin", f"refs/heads/{branch}")
        git(self.path, "checkout", "--detach", "FETCH_HEAD")
        self.commit = git(self.path, "rev-parse", "HEAD")
        return self.commit
