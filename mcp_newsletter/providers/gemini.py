from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..context import CollectContext
from ..mcp_discovery import discover_remote_tools
from ..models import ServerRecord
from ..utils import extract_github_repos, fetch_text, html_to_text, redact_secrets, slugify


PROVIDER = "gemini"
GALLERY_URL = "https://geminicli.com/extensions/"


def _raw_manifest_urls(repo_url: str) -> List[str]:
    match = re.match(r"https://github\.com/([^/]+)/([^/#?]+)", repo_url)
    if not match:
        return []
    owner, repo = match.groups()
    repo = repo.removesuffix(".git")
    paths = ["gemini-extension.json", ".gemini/extension.json"]
    refs = ["HEAD", "main", "master"]
    return [f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}" for ref in refs for path in paths]


def _fetch_manifest(ctx: CollectContext, repo_url: str) -> Tuple[Optional[Dict[str, Any]], str]:
    failures: List[str] = []
    for url in _raw_manifest_urls(repo_url):
        if ctx.skip_network:
            failures.append("network skipped")
            continue
        text, meta = fetch_text(url)
        ctx.save_raw_json(PROVIDER, f"{slugify(repo_url)}-{slugify(url.split('/')[-2])}-{slugify(url.split('/')[-1])}-fetch-meta", meta)
        if not text:
            failures.append(str(meta.get("error") or meta.get("status") or "empty response"))
            continue
        try:
            ctx.save_raw_text(PROVIDER, f"{slugify(repo_url)}-{slugify(url.split('/')[-2])}-{slugify(url.split('/')[-1])}", text, ext="json")
            return json.loads(text), url
        except json.JSONDecodeError:
            failures.append("invalid JSON")
            continue
    if failures:
        ctx.add_issue(PROVIDER, repo_url, "Manifest not found or invalid after probing common paths")
    return None, ""


def _iter_mcp_servers(mcp_servers: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if isinstance(mcp_servers, dict):
        for name, config in mcp_servers.items():
            if isinstance(config, dict):
                yield str(name), config
            else:
                yield str(name), {"value": config}
    elif isinstance(mcp_servers, list):
        for idx, item in enumerate(mcp_servers):
            if isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("server") or f"server-{idx + 1}"
                yield str(name), item
            else:
                yield f"server-{idx + 1}", {"value": item}


def collect_gemini(ctx: CollectContext) -> List[ServerRecord]:
    gallery_url = os.environ.get("MCP_NEWSLETTER_GEMINI_EXTENSIONS_URL", GALLERY_URL)
    gallery = ctx.fetch(PROVIDER, gallery_url, "extensions-gallery")
    if not gallery:
        return []

    repos = extract_github_repos(gallery)
    text = html_to_text(gallery)
    if not repos:
        ctx.add_issue(PROVIDER, gallery_url, "No GitHub repositories found in Gemini extension gallery")

    servers: List[ServerRecord] = []
    for repo_url in repos[: ctx.max_details]:
        manifest, manifest_url = _fetch_manifest(ctx, repo_url)
        if not manifest:
            servers.append(
                ServerRecord(
                    provider=PROVIDER,
                    server_id=slugify(repo_url),
                    native_surface="extension",
                    name=repo_url.rsplit("/", 1)[-1],
                    description="Gemini CLI extension listed in gallery; manifest was not available during crawl.",
                    source_urls=[repo_url, gallery_url],
                    metadata={"manifest_fetch": "not_found"},
                )
            )
            continue

        extension_name = manifest.get("name") or repo_url.rsplit("/", 1)[-1]
        mcp_servers = list(_iter_mcp_servers(manifest.get("mcpServers", {})))
        if not mcp_servers:
            servers.append(
                ServerRecord(
                    provider=PROVIDER,
                    server_id=slugify(extension_name),
                    native_surface="extension",
                    name=extension_name,
                    description=manifest.get("description", ""),
                    source_urls=[repo_url, manifest_url, gallery_url],
                    metadata={"manifest": redact_secrets(manifest), "gallery_text_seen": extension_name in text},
                )
            )
            continue

        for mcp_name, config in mcp_servers:
            clean_config = redact_secrets(config)
            server_id = f"{slugify(extension_name)}-{slugify(mcp_name)}"
            url = clean_config.get("url", "")
            tools = []
            discovery: Dict[str, Any] = {
                "ok": False,
                "reason": "local_or_unconfigured_mcp_discovery_deferred",
            }
            if url and not ctx.skip_network:
                tools, discovery = discover_remote_tools(PROVIDER, server_id, "extension", url)
            servers.append(
                ServerRecord(
                    provider=PROVIDER,
                    server_id=server_id,
                    native_surface="extension",
                    name=f"{extension_name}: {mcp_name}",
                    description=manifest.get("description", ""),
                    source_urls=[repo_url, manifest_url, gallery_url],
                    transport=clean_config.get("type") or ("stdio" if clean_config.get("command") else "catalog"),
                    remote_url=url,
                    tools=tools,
                    metadata={
                        "manifest": redact_secrets(manifest),
                        "mcp_server": clean_config,
                        "includeTools": manifest.get("includeTools") or clean_config.get("includeTools"),
                        "excludeTools": manifest.get("excludeTools") or clean_config.get("excludeTools"),
                        "discovery": discovery,
                    },
                )
            )
    return servers
