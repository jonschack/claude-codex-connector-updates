from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import CrawlIssue
from .utils import ensure_dir, fetch_text, safe_name, stable_hash, write_json, write_text


class CollectContext:
    def __init__(self, root: Path, run_date: str, skip_network: bool = False, max_details: int = 200) -> None:
        self.root = root
        self.run_date = run_date
        self.skip_network = skip_network
        self.max_details = max_details
        self.snapshot_dir = root / "data" / "snapshots" / run_date
        self.issues: List[CrawlIssue] = []
        ensure_dir(self.snapshot_dir)

    def add_issue(self, provider: str, source: str, message: str, severity: str = "warning") -> None:
        self.issues.append(CrawlIssue(provider=provider, source=source, message=message, severity=severity))

    def save_raw_text(self, provider: str, label: str, text: str, ext: str = "html") -> Path:
        path = self.snapshot_dir / provider / f"{safe_name(label)}.{ext}"
        write_text(path, text)
        return path

    def save_raw_json(self, provider: str, label: str, data: Any) -> Path:
        path = self.snapshot_dir / provider / f"{safe_name(label)}.json"
        write_json(path, data)
        return path

    def fetch(self, provider: str, url: str, label: Optional[str] = None) -> Optional[str]:
        if self.skip_network:
            self.add_issue(provider, url, "network fetch skipped by configuration")
            return None
        text, meta = fetch_text(url)
        save_label = label or url
        self.save_raw_json(provider, f"{save_label}-fetch-meta", meta)
        if text is not None:
            ext = "json" if "json" in str(meta.get("content_type", "")).lower() else "html"
            self.save_raw_text(provider, save_label, text, ext=ext)
        if meta.get("error"):
            self.add_issue(provider, url, str(meta["error"]))
        return text

    def finalize_manifest(self) -> None:
        manifest: Dict[str, Any] = {
            "run_date": self.run_date,
            "issues": [issue.to_dict() for issue in self.issues],
            "snapshot_hash": stable_hash([issue.to_dict() for issue in self.issues]),
        }
        self.save_raw_json("_run", "manifest", manifest)

