import httpx
import pytest

from forge_astra.http import JsonHTTP
from forge_astra.upstream import GitHub


@pytest.mark.parametrize(
    "merged,base,status,expected",
    [
        (False, "master", "ahead", False),
        (True, "feature", "ahead", False),
        (True, "master", "diverged", False),
        (True, "master", "behind", False),
        (True, "master", "ahead", True),
    ],
)
def test_pr_requires_merge_default_branch_and_snapshot_ancestry(merged, base, status, expected):
    def handler(request):
        path = request.url.path
        if "/pulls/" in path:
            return httpx.Response(
                200,
                json={
                    "merged": merged,
                    "merged_at": "today" if merged else None,
                    "state": "closed",
                    "base": {"ref": base, "repo": {"full_name": "Card-Forge/forge"}},
                    "merge_commit_sha": "b" * 40,
                },
            )
        if "/compare/" in path:
            return httpx.Response(200, json={"status": status})
        return httpx.Response(200, json={"default_branch": "master"})

    http = JsonHTTP("https://api.github.com", transport=httpx.MockTransport(handler))
    assert GitHub(http=http).merged_in_snapshot(123, "a" * 40)[0] is expected
    http.close()


def test_oracle_comments_do_not_prove_mechanic_support(corpus):
    assert corpus.mechanic_examples("Flying")[0]["name"] == "Bird"
    assert corpus.mechanic_examples("Novelty") == []
    assert corpus.search("deals 3 damage to any target")[0]["name"] == "Lightning Bolt"
    assert corpus.named("lightning bolt")[0]["path"].endswith("lightning_bolt.txt")
    assert "DealDamage" in corpus.capabilities["api"]
    assert "InventedDamage" not in corpus.capabilities["api"]
