"""RetroTV product agent.

One workflow, five modes, all external effects inside activities:

- ``triage``        label + summarize untriaged open issues (comment per issue)
- ``roadmap``       rebuild ROADMAP.md from open issues, recent PRs and the README
- ``release``       draft a changelog from recent commits and open a release PR
- ``digest``        weekly digest issue: opened/closed issues, merged PRs
- ``github_event``  react to a single GitHub webhook event (new issue/PR)

GitHub access goes through the workspace ``github_app`` connector; LLM calls go
through the Mistral plugin activities. Set ``dry_run=true`` to compute everything
and write nothing.
"""

from datetime import timedelta
from typing import Any, Literal, Optional

import pydantic
import mistralai.workflows as workflows
from mistralai.workflows import Depends, workflow
from mistralai.workflows.plugins.mistralai import chat_parse_to_model
from mistralai.workflows.plugins.mistralai.connectors import (
    ToolCallClient,
    connector,
    uses_connectors,
)

github = connector("github_app")

DEFAULT_REPO = "lizdiniz/retrotv"
LLM_MODEL = "mistral-large-latest"


class ProductAgentInput(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="ignore")

    mode: Literal["triage", "roadmap", "release", "digest", "github_event"] = "triage"
    repo: str = DEFAULT_REPO
    dry_run: bool = False
    since_days: int = 7
    version: Optional[str] = None
    event: Optional[dict[str, Any]] = None

    @pydantic.model_validator(mode="before")
    @classmethod
    def _from_webhook_event(cls, values: Any) -> Any:
        if isinstance(values, dict):
            event = values.get("event")
            if not isinstance(event, dict) and ("issue" in values or "pull_request" in values):
                values = {**values, "event": values}
                event = values["event"]
            if event is not None and "mode" not in values:
                values = {**values, "mode": "github_event"}
            if isinstance(event, dict):
                full_name = (event.get("repository") or {}).get("full_name")
                if full_name and values.get("repo") in (None, "", DEFAULT_REPO):
                    values = {**values, "repo": full_name}
        return values


class TriageVerdict(pydantic.BaseModel):
    category: Literal["bug", "feature", "idea", "question", "chore"]
    priority: Literal["p0", "p1", "p2", "p3"]
    summary: str
    labels: list[str] = []
    duplicate_of: Optional[int] = None


class RoadmapPlan(pydantic.BaseModel):
    roadmap_md: str
    highlights: list[str] = []


class ReleasePlan(pydantic.BaseModel):
    version: str
    changelog_md: str
    summary: str


class DigestPlan(pydantic.BaseModel):
    digest_md: str


def _split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    return owner, name


def _issue_brief(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": issue.get("number"),
        "title": issue.get("title", ""),
        "body": (issue.get("body") or "")[:4000],
        "labels": [l.get("name") if isinstance(l, dict) else l for l in issue.get("labels", [])],
        "html_url": issue.get("html_url", ""),
        "user": (issue.get("user") or {}).get("login", ""),
    }


# ---------------------------------------------------------------------------
# GitHub activities (all network I/O lives here)
# ---------------------------------------------------------------------------


@workflows.activity(name="gh-search-issues", start_to_close_timeout=timedelta(seconds=60))
async def gh_search_issues(
    repo: str, query: str, per_page: int, client: ToolCallClient = Depends(github)
) -> list[dict[str, Any]]:
    owner, name = _split_repo(repo)
    result = await client.call_tool(
        tool_name="search_issues",
        arguments={"query": query, "owner": owner, "repo": name, "per_page": per_page},
    )
    if isinstance(result, dict):
        return list(result.get("items") or [])
    return list(result or [])


@workflows.activity(name="gh-search-prs", start_to_close_timeout=timedelta(seconds=60))
async def gh_search_prs(
    repo: str, query: str, per_page: int, client: ToolCallClient = Depends(github)
) -> list[dict[str, Any]]:
    owner, name = _split_repo(repo)
    result = await client.call_tool(
        tool_name="search_pull_requests",
        arguments={"query": query, "owner": owner, "repo": name, "per_page": per_page},
    )
    if isinstance(result, dict):
        return list(result.get("items") or [])
    return list(result or [])


@workflows.activity(name="gh-list-commits", start_to_close_timeout=timedelta(seconds=60))
async def gh_list_commits(
    repo: str, per_page: int, client: ToolCallClient = Depends(github)
) -> list[dict[str, Any]]:
    owner, name = _split_repo(repo)
    result = await client.call_tool(
        tool_name="list_commits",
        arguments={"owner": owner, "repo": name, "per_page": per_page},
    )
    return [
        {
            "sha": (c.get("sha") or "")[:10],
            "message": (c.get("commit") or {}).get("message", ""),
            "author": (c.get("commit") or {}).get("author", {}).get("name", ""),
        }
        for c in (result or [])
    ]


@workflows.activity(name="gh-get-file", start_to_close_timeout=timedelta(seconds=60))
async def gh_get_file(
    repo: str, path: str, ref: str, client: ToolCallClient = Depends(github)
) -> Optional[dict[str, Any]]:
    import base64

    owner, name = _split_repo(repo)
    try:
        result = await client.call_tool(
            tool_name="get_file_contents",
            arguments={"owner": owner, "repo": name, "path": path, "ref": ref},
        )
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    text = ""
    if isinstance(content, str):
        if result.get("encoding") == "base64":
            text = base64.b64decode(content).decode("utf-8", "replace")
        else:
            text = content
    return {"sha": result.get("sha"), "text": text}


@workflows.activity(name="gh-put-file", start_to_close_timeout=timedelta(seconds=60))
async def gh_put_file(
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str,
    sha: Optional[str],
    client: ToolCallClient = Depends(github),
) -> dict[str, Any]:
    owner, name = _split_repo(repo)
    args: dict[str, Any] = {
        "owner": owner,
        "repo": name,
        "path": path,
        "content": content,
        "message": message,
        "branch": branch,
    }
    if sha:
        args["sha"] = sha
    result = await client.call_tool(tool_name="create_or_update_file", arguments=args)
    return result if isinstance(result, dict) else {"result": result}


@workflows.activity(name="gh-add-comment", start_to_close_timeout=timedelta(seconds=60))
async def gh_add_comment(
    repo: str, issue_number: int, body: str, client: ToolCallClient = Depends(github)
) -> None:
    owner, name = _split_repo(repo)
    await client.call_tool(
        tool_name="add_issue_comment",
        arguments={"owner": owner, "repo": name, "issue_number": issue_number, "body": body},
    )


@workflows.activity(name="gh-set-labels", start_to_close_timeout=timedelta(seconds=60))
async def gh_set_labels(
    repo: str, issue_number: int, labels: list[str], client: ToolCallClient = Depends(github)
) -> None:
    owner, name = _split_repo(repo)
    await client.call_tool(
        tool_name="update_issue",
        arguments={"owner": owner, "repo": name, "issue_number": issue_number, "labels": labels},
    )


@workflows.activity(name="gh-create-issue", start_to_close_timeout=timedelta(seconds=60))
async def gh_create_issue(
    repo: str, title: str, body: str, labels: list[str], client: ToolCallClient = Depends(github)
) -> dict[str, Any]:
    owner, name = _split_repo(repo)
    result = await client.call_tool(
        tool_name="create_issue",
        arguments={"owner": owner, "repo": name, "title": title, "body": body, "labels": labels},
    )
    return result if isinstance(result, dict) else {"result": result}


@workflows.activity(name="gh-create-branch", start_to_close_timeout=timedelta(seconds=60))
async def gh_create_branch(
    repo: str, branch: str, from_branch: str, client: ToolCallClient = Depends(github)
) -> None:
    owner, name = _split_repo(repo)
    await client.call_tool(
        tool_name="create_branch",
        arguments={"owner": owner, "repo": name, "branch": branch, "from_branch": from_branch},
    )


@workflows.activity(name="gh-create-pr", start_to_close_timeout=timedelta(seconds=60))
async def gh_create_pr(
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str,
    draft: bool,
    client: ToolCallClient = Depends(github),
) -> dict[str, Any]:
    owner, name = _split_repo(repo)
    result = await client.call_tool(
        tool_name="create_pull_request",
        arguments={
            "owner": owner,
            "repo": name,
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": draft,
        },
    )
    return result if isinstance(result, dict) else {"result": result}


# ---------------------------------------------------------------------------
# LLM activities
# ---------------------------------------------------------------------------


def _request(system: str, user: str) -> Any:
    from mistralai.models import ChatCompletionRequest

    return ChatCompletionRequest(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )


@workflows.activity(name="llm-triage", start_to_close_timeout=timedelta(seconds=120))
async def llm_triage(issue: dict[str, Any]) -> dict[str, Any]:
    verdict = await chat_parse_to_model(
        TriageVerdict,
        _request(
            "You triage issues for RetroTV, a 90s-style scheduled family TV app. "
            "Classify the issue and propose labels. Reply only with the structured verdict.",
            f"Issue #{issue.get('number')} by {issue.get('user')}: {issue.get('title')}\n\n"
            f"{issue.get('body', '')}\n\nExisting labels: {issue.get('labels', [])}",
        ),
    )
    return verdict.model_dump()


@workflows.activity(name="llm-roadmap", start_to_close_timeout=timedelta(seconds=180))
async def llm_roadmap(context: dict[str, Any]) -> dict[str, Any]:
    import json

    plan = await chat_parse_to_model(
        RoadmapPlan,
        _request(
            "You maintain the roadmap of RetroTV (90s nostalgia scheduled TV for families). "
            "Write a prioritized ROADMAP.md (Now / Next / Later sections) from the open issues, "
            "recent merged PRs and README. Keep it short and concrete.",
            json.dumps(context, indent=2)[:12000],
        ),
    )
    return plan.model_dump()


@workflows.activity(name="llm-release", start_to_close_timeout=timedelta(seconds=180))
async def llm_release(context: dict[str, Any]) -> dict[str, Any]:
    import json

    plan = await chat_parse_to_model(
        ReleasePlan,
        _request(
            "You write release notes for RetroTV. Given recent commits and the current version, "
            "propose the next semver version and a full CHANGELOG.md entry (Keep a Changelog style).",
            json.dumps(context, indent=2)[:12000],
        ),
    )
    return plan.model_dump()


@workflows.activity(name="llm-digest", start_to_close_timeout=timedelta(seconds=180))
async def llm_digest(context: dict[str, Any]) -> dict[str, Any]:
    import json

    plan = await chat_parse_to_model(
        DigestPlan,
        _request(
            "You write a weekly project digest for RetroTV from GitHub activity. "
            "Markdown with Highlights / Opened / Closed / Merged PRs / Suggested focus.",
            json.dumps(context, indent=2)[:12000],
        ),
    )
    return plan.model_dump()


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

TRIAGE_SYSTEM_NOTE = (
    "🤖 RetroTV product agent triage: category={category}, priority={priority}. {summary}"
)


@workflows.workflow.define(name="retrotv-product-agent", on_behalf_of=True)
@uses_connectors(github)
class ProductAgentWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, data: ProductAgentInput) -> dict[str, Any]:
        if data.mode == "github_event":
            return await self._handle_event(data)
        if data.mode == "triage":
            return await self._triage(data)
        if data.mode == "roadmap":
            return await self._roadmap(data)
        if data.mode == "release":
            return await self._release(data)
        if data.mode == "digest":
            return await self._digest(data)
        raise workflows.WorkflowError(f"unknown mode: {data.mode}")

    async def _apply_verdict(self, repo: str, brief: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        verdict = await llm_triage(brief)
        labels = sorted(
            set(brief["labels"]) | set(verdict.get("labels", [])) | {"triaged", verdict["category"], verdict["priority"]}
        )
        comment = TRIAGE_SYSTEM_NOTE.format(
            category=verdict["category"], priority=verdict["priority"], summary=verdict["summary"]
        )
        if verdict.get("duplicate_of"):
            comment += f"\n\nPossible duplicate of #{verdict['duplicate_of']}."
        if not dry_run:
            await gh_set_labels(repo, brief["number"], labels)
            await gh_add_comment(repo, brief["number"], comment)
        return {"number": brief["number"], "title": brief["title"], "verdict": verdict, "labels": labels}

    async def _triage_issue(self, repo: str, issue: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        return await self._apply_verdict(repo, _issue_brief(issue), dry_run)

    async def _triage(self, data: ProductAgentInput) -> dict[str, Any]:
        issues = await gh_search_issues(
            data.repo, f"repo:{data.repo} is:issue is:open -label:triaged", 50
        )
        results = [await self._triage_issue(data.repo, i, data.dry_run) for i in issues]
        return {"mode": "triage", "repo": data.repo, "dry_run": data.dry_run,
                "triaged": len(results), "results": results}

    async def _roadmap(self, data: ProductAgentInput) -> dict[str, Any]:
        issues = await gh_search_issues(data.repo, f"repo:{data.repo} is:issue is:open", 100)
        prs = await gh_search_prs(
            data.repo, f"repo:{data.repo} is:pr is:merged", 30
        )
        readme = await gh_get_file(data.repo, "README.md", "main")
        plan = await llm_roadmap(
            {
                "repo": data.repo,
                "open_issues": [_issue_brief(i) for i in issues],
                "recent_merged_prs": [
                    {"number": p.get("number"), "title": p.get("title"), "html_url": p.get("html_url")}
                    for p in prs
                ],
                "readme": (readme or {}).get("text", "")[:6000],
            }
        )
        written = False
        if not data.dry_run:
            existing = await gh_get_file(data.repo, "ROADMAP.md", "main")
            await gh_put_file(
                data.repo, "ROADMAP.md", plan["roadmap_md"],
                "docs: update ROADMAP.md [product-agent]", "main", (existing or {}).get("sha"),
            )
            written = True
        return {"mode": "roadmap", "repo": data.repo, "dry_run": data.dry_run,
                "written": written, "highlights": plan["highlights"], "roadmap_md": plan["roadmap_md"]}

    async def _release(self, data: ProductAgentInput) -> dict[str, Any]:
        commits = await gh_list_commits(data.repo, 100)
        current = await gh_get_file(data.repo, "CHANGELOG.md", "main")
        plan = await llm_release(
            {
                "repo": data.repo,
                "requested_version": data.version,
                "commits": commits,
                "existing_changelog": (current or {}).get("text", "")[:6000],
            }
        )
        version = data.version or plan["version"]
        branch = f"release/{version}"
        pr_url = None
        if not data.dry_run:
            await gh_create_branch(data.repo, branch, "main")
            existing = await gh_get_file(data.repo, "CHANGELOG.md", branch)
            await gh_put_file(
                data.repo, "CHANGELOG.md", plan["changelog_md"],
                f"chore(release): {version} [product-agent]", branch, (existing or {}).get("sha"),
            )
            pr = await gh_create_pr(
                data.repo, f"Release {version}", branch, "main", plan["summary"], True
            )
            pr_url = pr.get("html_url") if isinstance(pr, dict) else None
        return {"mode": "release", "repo": data.repo, "dry_run": data.dry_run,
                "version": version, "branch": branch, "pr_url": pr_url, "summary": plan["summary"]}

    async def _digest(self, data: ProductAgentInput) -> dict[str, Any]:
        now = workflow.now()
        since = (now - timedelta(days=data.since_days)).isoformat()
        opened = await gh_search_issues(
            data.repo, f"repo:{data.repo} is:issue created:>{since}", 100
        )
        closed = await gh_search_issues(
            data.repo, f"repo:{data.repo} is:issue closed:>{since}", 100
        )
        merged = await gh_search_prs(
            data.repo, f"repo:{data.repo} is:pr is:merged updated:>{since}", 50
        )
        plan = await llm_digest(
            {
                "repo": data.repo,
                "since": since,
                "until": now.isoformat(),
                "opened": [_issue_brief(i) for i in opened],
                "closed": [_issue_brief(i) for i in closed],
                "merged_prs": [
                    {"number": p.get("number"), "title": p.get("title"), "html_url": p.get("html_url")}
                    for p in merged
                ],
            }
        )
        issue_url = None
        if not data.dry_run:
            title = f"📋 Digest {data.repo} — last {data.since_days}d ({now.date().isoformat()})"
            issue = await gh_create_issue(data.repo, title, plan["digest_md"], ["digest"])
            issue_url = issue.get("html_url") if isinstance(issue, dict) else None
        return {"mode": "digest", "repo": data.repo, "dry_run": data.dry_run,
                "issue_url": issue_url, "digest_md": plan["digest_md"]}

    async def _handle_event(self, data: ProductAgentInput) -> dict[str, Any]:
        event = data.event or {}
        item = event.get("issue") or event.get("pull_request") or {}
        if not item:
            return {"mode": "github_event", "handled": False, "reason": "no issue/pull_request in event"}
        result = await self._apply_verdict(data.repo, _issue_brief(item), data.dry_run)
        return {"mode": "github_event", "handled": True, "action": event.get("action"), "result": result}
