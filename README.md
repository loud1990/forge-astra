# Forge Astra

An evidence-grounded LangGraph application for discovering Magic: The Gathering
spoilers, researching their Oracle text against upstream Forge card scripts, and
preparing reviewable script batches and eight-copy test decks.

Under active development. Generated cards are drafts; gameplay testing belongs
to a separate harness. This application does not publish Forge pull requests.

The Python application lives in `src/forge_astra`. The optional local `forge-1/`
checkout is ignored by this repository and is used only as a read-only clone seed.

Development setup: `uv sync --dev`.
