#!/usr/bin/env python3
"""Sync curated resources into the local reference guide only."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "tools/agents_resource_index.json"
REPO_AGENTS_PATH = REPO_ROOT / "docs/LEGACY_WORKBENCH_GUIDE.md"

START_MARKER = "<!-- RESOURCES:START -->"
END_MARKER = "<!-- RESOURCES:END -->"
SECTION_HEADER = "## 资料索引（同步生成）"
MAINTENANCE_LINE = (
    "维护方式：修改 `tools/agents_resource_index.json` 后执行 "
    "`python3 tools/sync_agents_resources.py`。"
)

TARGETS = (
    {
        "path": REPO_AGENTS_PATH,
        "anchor_after": "## 学习进度与笔记（强约束）",
    },
)


def render_item(item: dict) -> str:
    target = item.get("path") or item.get("url")
    label = item["name"]
    note = item.get("note", "").strip()
    line = f"- `{label}`: `{target}`"
    if note:
        line += f"  \n  说明：{note}"
    return line


def render_block(catalog: dict) -> str:
    lines = [
        SECTION_HEADER,
        "",
        MAINTENANCE_LINE,
        START_MARKER,
    ]

    for category in catalog["categories"]:
        lines.append("")
        lines.append(f"### {category['title']}")
        lines.append("")
        for item in category["items"]:
            lines.append(render_item(item))

    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def replace_section(text: str, new_block: str, anchor_after: str) -> str:
    if SECTION_HEADER in text and START_MARKER in text and END_MARKER in text:
        section_start = text.index(SECTION_HEADER)
        section_end = text.index(END_MARKER) + len(END_MARKER)
        return text[:section_start] + new_block.rstrip() + "\n" + text[section_end:]
    anchor_index = text.index(anchor_after)
    next_header = text.index("\n##", anchor_index + len(anchor_after))
    return text[:next_header] + "\n\n" + new_block.rstrip() + "\n" + text[next_header:]


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    new_block = render_block(catalog)
    for target in TARGETS:
        if not target["path"].exists():
            print(f"Skipped missing {target['path']}")
            continue
        agents_text = target["path"].read_text(encoding="utf-8")
        updated = replace_section(agents_text, new_block, target["anchor_after"])
        target["path"].write_text(updated, encoding="utf-8")
        print(f"Updated {target['path']}")


if __name__ == "__main__":
    main()
