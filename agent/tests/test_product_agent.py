"""Tests for the RetroTV product agent.

External effects (GitHub connector tools, LLM calls) are replaced by fake
activities registered under the same activity names, so the workflow logic is
exercised end-to-end without network access.
"""

import asyncio
import json

import pytest
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows.testing import create_test_worker

from worker.workflows.product_agent import ProductAgentWorkflow

EXECUTION_TIMEOUT = timedelta(seconds=30)

CALLS: list[tuple[str, tuple, dict]] = []


def record(name: str, *args) -> None:
    CALLS.append((name, args, {}))


@workflows.activity(name="gh-search-issues")
async def fake_gh_search_issues(repo: str, query: str, per_page: int) -> list:
    record("gh-search-issues", repo, query, per_page)
    if "closed:>" in query:
        return [{"number": 3, "title": "Old bug", "body": "crashes", "labels": [{"name": "bug"}], "user": {"login": "kid"}}]
    if "created:>" in query:
        return [{"number": 7, "title": "New feature", "body": "add channel 6", "labels": [], "user": {"login": "parent"}}]
    return [
        {"number": 1, "title": "Crash on channel switch", "body": "it crashes", "labels": [], "user": {"login": "a"}},
        {"number": 2, "title": "Add bedtime timer", "body": "please", "labels": [{"name": "enhancement"}], "user": {"login": "b"}},
    ]


@workflows.activity(name="gh-search-prs")
async def fake_gh_search_prs(repo: str, query: str, per_page: int) -> list:
    record("gh-search-prs", repo, query, per_page)
    return [{"number": 9, "title": "Fix playback sync", "html_url": "https://example/pr/9"}]


@workflows.activity(name="gh-list-commits")
async def fake_gh_list_commits(repo: str, per_page: int) -> list:
    record("gh-list-commits", repo, per_page)
    return [
        {"sha": "abc1234567", "message": "feat: add bathroom breaks", "author": "liz"},
        {"sha": "def7654321", "message": "fix: off-air static", "author": "liz"},
    ]


@workflows.activity(name="gh-get-file")
async def fake_gh_get_file(repo: str, path: str, ref: str) -> dict | None:
    record("gh-get-file", repo, path, ref)
    if path == "README.md":
        return {"sha": "sha-readme", "text": "# RetroTV\n\n90s TV guide."}
    return None


@workflows.activity(name="gh-put-file")
async def fake_gh_put_file(repo: str, path: str, content: str, message: str, branch: str, sha: "str | None") -> dict:
    record("gh-put-file", repo, path, content, message, branch, sha)
    return {"commit": {"sha": "newsha"}}


@workflows.activity(name="gh-add-comment")
async def fake_gh_add_comment(repo: str, issue_number: int, body: str) -> None:
    record("gh-add-comment", repo, issue_number, body)


@workflows.activity(name="gh-set-labels")
async def fake_gh_set_labels(repo: str, issue_number: int, labels: list) -> None:
    record("gh-set-labels", repo, issue_number, labels)


@workflows.activity(name="gh-create-issue")
async def fake_gh_create_issue(repo: str, title: str, body: str, labels: list) -> dict:
    record("gh-create-issue", repo, title, body, labels)
    return {"html_url": "https://example/issue/42", "number": 42}


@workflows.activity(name="gh-create-branch")
async def fake_gh_create_branch(repo: str, branch: str, from_branch: str) -> None:
    record("gh-create-branch", repo, branch, from_branch)


@workflows.activity(name="gh-create-pr")
async def fake_gh_create_pr(repo: str, title: str, head: str, base: str, body: str, draft: bool) -> dict:
    record("gh-create-pr", repo, title, head, base, body, draft)
    return {"html_url": "https://example/pr/100"}


@workflows.activity(name="llm-triage")
async def fake_llm_triage(issue: dict) -> dict:
    record("llm-triage", issue)
    title = issue.get("title", "")
    category = "bug" if "crash" in title.lower() else "feature"
    return {"category": category, "priority": "p1", "summary": f"Triaged: {title}",
            "labels": [category], "duplicate_of": None}


@workflows.activity(name="llm-roadmap")
async def fake_llm_roadmap(context: dict) -> dict:
    record("llm-roadmap", context)
    return {"roadmap_md": "# Roadmap\n\n## Now\n- fix crash", "highlights": ["fix crash"]}


@workflows.activity(name="llm-release")
async def fake_llm_release(context: dict) -> dict:
    record("llm-release", context)
    return {"version": "0.2.0", "changelog_md": "# 0.2.0\n\n- breaks", "summary": "Release 0.2.0"}


@workflows.activity(name="llm-digest")
async def fake_llm_digest(context: dict) -> dict:
    record("llm-digest", context)
    return {"digest_md": "# Digest\n\n1 opened, 1 closed, 1 merged"}


FAKES = [
    fake_gh_search_issues, fake_gh_search_prs, fake_gh_list_commits, fake_gh_get_file,
    fake_gh_put_file, fake_gh_add_comment, fake_gh_set_labels, fake_gh_create_issue,
    fake_gh_create_branch, fake_gh_create_pr,
    fake_llm_triage, fake_llm_roadmap, fake_llm_release, fake_llm_digest,
]


async def run_agent(temporal_env, payload: dict, run_id: str) -> dict:
    async with create_test_worker(temporal_env, workflows=[ProductAgentWorkflow], activities=FAKES):
        handle = await temporal_env.client.start_workflow(
            "retrotv-product-agent",
            payload,
            id=run_id,
            task_queue="test-task-queue",
            execution_timeout=EXECUTION_TIMEOUT,
        )
        raw = await asyncio.wait_for(handle.result(), timeout=25)
        return raw.get("result", raw) if isinstance(raw, dict) else raw


async def test_triage_labels_and_comments(temporal_env):
    CALLS.clear()
    result = await run_agent(temporal_env, {"mode": "triage", "repo": "acme/retrotv"}, "t-triage")
    assert result["mode"] == "triage"
    assert result["triaged"] == 2
    labels_calls = [c for c in CALLS if c[0] == "gh-set-labels"]
    comment_calls = [c for c in CALLS if c[0] == "gh-add-comment"]
    assert len(labels_calls) == 2 and len(comment_calls) == 2
    assert all("triaged" in c[1][2] for c in labels_calls)
    assert any(c[1][1] == 1 and "bug" in c[1][2] for c in labels_calls)


async def test_triage_dry_run_writes_nothing(temporal_env):
    CALLS.clear()
    result = await run_agent(
        temporal_env, {"mode": "triage", "repo": "acme/retrotv", "dry_run": True}, "t-triage-dry"
    )
    assert result["triaged"] == 2
    assert not [c for c in CALLS if c[0] in ("gh-set-labels", "gh-add-comment")]


async def test_roadmap_writes_file(temporal_env):
    CALLS.clear()
    result = await run_agent(temporal_env, {"mode": "roadmap", "repo": "acme/retrotv"}, "t-roadmap")
    assert result["written"] is True
    put_calls = [c for c in CALLS if c[0] == "gh-put-file"]
    assert len(put_calls) == 1
    assert put_calls[0][1][1] == "ROADMAP.md"
    assert "# Roadmap" in put_calls[0][1][2]


async def test_release_opens_draft_pr(temporal_env):
    CALLS.clear()
    result = await run_agent(temporal_env, {"mode": "release", "repo": "acme/retrotv"}, "t-release")
    assert result["version"] == "0.2.0"
    assert result["branch"] == "release/0.2.0"
    assert result["pr_url"] == "https://example/pr/100"
    names = [c[0] for c in CALLS]
    assert names.index("gh-create-branch") < names.index("gh-put-file") < names.index("gh-create-pr")


async def test_digest_creates_issue(temporal_env):
    CALLS.clear()
    result = await run_agent(
        temporal_env, {"mode": "digest", "repo": "acme/retrotv", "since_days": 7}, "t-digest"
    )
    assert result["issue_url"] == "https://example/issue/42"
    create_calls = [c for c in CALLS if c[0] == "gh-create-issue"]
    assert len(create_calls) == 1
    assert "Digest" in create_calls[0][1][2]


async def test_github_event_triages_single_issue(temporal_env):
    CALLS.clear()
    event = {"action": "opened", "issue": {"number": 5, "title": "Crash in parent view", "body": "boom", "labels": [], "user": {"login": "x"}}}
    result = await run_agent(
        temporal_env, {"mode": "github_event", "repo": "acme/retrotv", "event": event}, "t-event"
    )
    assert result["handled"] is True
    assert result["result"]["number"] == 5
    assert result["result"]["verdict"]["category"] == "bug"


async def test_github_event_without_issue_is_noop(temporal_env):
    CALLS.clear()
    result = await run_agent(
        temporal_env, {"mode": "github_event", "repo": "acme/retrotv", "event": {"action": "ping"}}, "t-ping"
    )
    assert result["handled"] is False
    assert CALLS == []


async def test_gh_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from worker.workflows.product_agent import _gh

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        await _gh("GET", "/search/issues", params={"q": "x"})


def test_llm_request_builder_importable():
    from worker.workflows.product_agent import LLM_MODEL, _request

    req = _request("system", "user")
    assert req.model == LLM_MODEL
    assert req.messages[0].role == "system"


async def test_webhook_envelope_defaults_to_event_mode_and_repo(temporal_env):
    CALLS.clear()
    envelope = {
        "action": "opened",
        "repository": {"full_name": "acme/retrotv"},
        "issue": {"number": 8, "title": "Crash", "body": "x", "labels": [], "user": {"login": "y"}},
    }
    result = await run_agent(temporal_env, envelope, "t-envelope")
    assert result["mode"] == "github_event"
    assert result["handled"] is True
    assert result["result"]["number"] == 8
