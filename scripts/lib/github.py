"""GitHub search for last30days skill.

Uses GitHub REST API v3 for repository and issue discovery.
Requires GITHUB_TOKEN (Personal Access Token) for higher rate limits.
Free tier: 60 requests/hour (unauthenticated)
With token: 5,000 requests/hour
"""

import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from . import http
from .query import extract_core_subject
from .relevance import token_overlap_relevance

GITHUB_API_URL = "https://api.github.com"
GITHUB_SEARCH_URL = "https://api.github.com/search"

DEPTH_CONFIG = {
    "quick": 15,
    "default": 30,
    "deep": 60,
}


def _log(msg: str):
    if sys.stderr.isatty():
        sys.stderr.write(f"[GitHub] {msg}\n")
        sys.stderr.flush()


def _get_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": http.USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def search_github(
    topic: str,
    from_date: str,
    to_date: str,
    depth: str = "default",
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Search GitHub for repositories and issues.

    Args:
        topic: Search topic
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        depth: 'quick', 'default', or 'deep'
        token: GitHub Personal Access Token (optional)

    Returns:
        Dict with 'repositories' and 'issues' lists
    """
    count = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["default"])
    core = extract_core_subject(topic)

    _log(f"Searching for '{core}' ({from_date} to {to_date})")

    headers = _get_headers(token)
    results = {"repositories": [], "issues": [], "trending": []}

    try:
        repo_params = {
            "q": f"{core} created:{from_date}..{to_date}",
            "sort": "stars",
            "per_page": str(min(count, 100)),
        }
        repo_url = f"{GITHUB_SEARCH_URL}/repositories?{urlencode(repo_params)}"
        repo_response = http.request("GET", repo_url, headers=headers, timeout=30)
        results["repositories"] = repo_response.get("items", [])
        _log(f"Found {len(results['repositories'])} repositories")

    except http.HTTPError as e:
        _log(f"Repository search failed: {e}")
        results["repo_error"] = str(e)
    except Exception as e:
        _log(f"Repository search failed: {e}")
        results["repo_error"] = str(e)

    try:
        issue_params = {
            "q": f"{core} created:{from_date}..{to_date}",
            "sort": "comments",
            "per_page": str(min(count, 100)),
            "type": "issue",
        }
        issue_url = f"{GITHUB_SEARCH_URL}/issues?{urlencode(issue_params)}"
        issue_response = http.request("GET", issue_url, headers=headers, timeout=30)
        results["issues"] = issue_response.get("items", [])
        _log(f"Found {len(results['issues'])} issues")

    except http.HTTPError as e:
        _log(f"Issue search failed: {e}")
        results["issue_error"] = str(e)
    except Exception as e:
        _log(f"Issue search failed: {e}")
        results["issue_error"] = str(e)

    try:
        trending_params = {
            "q": f"{core}",
            "created": f">{from_date}",
            "sort": "stars",
            "order": "desc",
            "per_page": str(min(count // 2, 50)),
        }
        trending_url = f"{GITHUB_SEARCH_URL}/repositories?{urlencode(trending_params)}"
        trending_response = http.request("GET", trending_url, headers=headers, timeout=30)
        results["trending"] = trending_response.get("items", [])
        _log(f"Found {len(results['trending'])} trending repos")

    except http.HTTPError as e:
        _log(f"Trending search failed: {e}")
    except Exception as e:
        _log(f"Trending search failed: {e}")

    return results


def parse_github_response(response: Dict[str, Any], query: str = "") -> List[Dict[str, Any]]:
    """Parse GitHub API response into normalized item dicts.

    Args:
        response: GitHub API response with 'repositories', 'issues', 'trending'
        query: Original search query for relevance scoring

    Returns:
        List of item dicts ready for normalization
    """
    items = []
    seen_urls = set()

    for i, repo in enumerate(response.get("repositories", [])):
        url = repo.get("html_url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)

        relevance = token_overlap_relevance(query, repo.get("description", ""))
        relevance = min(1.0, relevance + 0.1)

        items.append({
            "type": "repository",
            "id": f"GH{len(items) + 1}",
            "full_name": repo.get("full_name", ""),
            "description": repo.get("description", "") or "",
            "url": url,
            "stars": stars,
            "forks": forks,
            "language": repo.get("language", ""),
            "topics": repo.get("topics", []),
            "engagement": {
                "stars": stars,
                "forks": forks,
            },
            "relevance": round(relevance, 2),
            "why_relevant": f"GitHub repo: {repo.get('full_name', '')} ({stars} stars)",
        })

    offset = len(items)
    for j, issue in enumerate(response.get("issues", [])):
        url = issue.get("html_url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        comments = issue.get("comments", 0)
        repo_url = issue.get("repository_url", "")
        repo_name = "/".join(repo_url.split("/")[-2:]) if repo_url else ""

        relevance = token_overlap_relevance(query, issue.get("title", ""))
        relevance = min(1.0, relevance + 0.05)

        items.append({
            "type": "issue",
            "id": f"GH{offset + j + 1}",
            "title": issue.get("title", ""),
            "body": (issue.get("body", "") or "")[:500],
            "url": url,
            "repository": repo_name,
            "state": issue.get("state", "open"),
            "comments": comments,
            "engagement": {
                "comments": comments,
            },
            "relevance": round(relevance, 2),
            "why_relevant": f"GitHub issue: {issue.get('title', '')[:60]}",
        })

    for k, repo in enumerate(response.get("trending", [])):
        url = repo.get("html_url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)

        relevance = token_overlap_relevance(query, repo.get("description", ""))
        relevance = min(1.0, relevance + 0.15)

        items.append({
            "type": "trending",
            "id": f"GH{len(items) + 1}",
            "full_name": repo.get("full_name", ""),
            "description": repo.get("description", "") or "",
            "url": url,
            "stars": stars,
            "forks": forks,
            "language": repo.get("language", ""),
            "topics": repo.get("topics", []),
            "engagement": {
                "stars": stars,
                "forks": forks,
            },
            "relevance": round(relevance, 2),
            "why_relevant": f"Trending GitHub repo: {repo.get('full_name', '')} ({stars} stars)",
        })

    return items
