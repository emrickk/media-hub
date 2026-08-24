"""Acceptance checks for the zero-instruction clone-to-recommend journey."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_codex_and_claude_discover_one_shared_entrypoint():
    agents = ROOT / "AGENTS.md"
    claude = ROOT / "CLAUDE.md"

    assert agents.is_file(), "Codex needs a root AGENTS.md after cloning"
    assert claude.is_file(), "Claude Code needs a root CLAUDE.md after cloning"
    assert claude.read_text("utf-8").strip() == "@AGENTS.md"


def test_short_install_request_routes_to_a_finished_recommendation():
    entrypoint = (ROOT / "AGENTS.md").read_text("utf-8").lower()
    skill = (ROOT / "skills/media-taste/SKILL.md").read_text("utf-8").lower()

    assert "install and recommend" in entrypoint
    assert "skills/media-taste/skill.md" in entrypoint
    assert "recommend/out/latest.html" in entrypoint
    assert "do not stop" in entrypoint

    assert "current conversation" in skill
    assert "permission" in skill
    assert "default intention" in skill
    assert "definition of done" in skill
