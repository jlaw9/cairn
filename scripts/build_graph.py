#!/usr/bin/env python3
"""Render the graph to build/graph.html (and build/graph.md).

Self-contained: no CDN, no server, no bundler. Open the file.

Layout is time-ordered rather than force-directed — x is the creation date,
y is a project lane. Research history has a real time axis and a force layout
throws it away. It also means positions are stable between builds, so the map
stays memorable, and the replay slider falls out of `history` for free.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import lib

# Layout constants (px)
X_PAD = 150
Y_PAD = 60
ROW_H = 46
NODE_R = 13
LANE_GAP = 30
ROW_MARGIN = 16      # clear space required between a label and the next glyph
CHAR_PX = 5.9        # width of one char at the 11px label font
MAX_LABEL = 42       # chars before a title is elided
PX_PER_NODE = 130    # how much horizontal room the graph gets per node
MIN_WIDTH = 900
MAX_WIDTH = 5200

TYPE_SHAPE = {
    "experiment": "circle",
    "direction": "rect",
    "seed": "diamond",
    "milestone": "hex",
    "task": "square",
}


# --------------------------------------------------------------------------
# Minimal markdown -> HTML
# --------------------------------------------------------------------------

def md_inline(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", out)
    return out


def md_to_html(text: str) -> str:
    """A deliberately small markdown subset: headings, lists, code, quotes.

    Node bodies are notes, not documents. Pulling in a markdown dependency for
    this would be the first crack in "runs anywhere without a venv".
    """
    lines = text.strip().splitlines()
    out: list[str] = []
    list_stack: list[str] = []
    in_code = False
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{md_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    for raw in lines:
        line = raw.rstrip()

        if line.startswith("```"):
            flush_paragraph()
            close_lists()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(raw))
            continue

        if not line.strip():
            flush_paragraph()
            close_lists()
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_lists()
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f"<h{level}>{md_inline(heading.group(2))}</h{level}>")
            continue

        if re.match(r"^(---|\*\*\*|___)\s*$", line):
            flush_paragraph()
            close_lists()
            out.append("<hr>")
            continue

        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        number = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if bullet or number:
            flush_paragraph()
            want = "ul" if bullet else "ol"
            if list_stack and list_stack[-1] != want:
                close_lists()
            if not list_stack:
                list_stack.append(want)
                out.append(f"<{want}>")
            out.append(f"<li>{md_inline((bullet or number).group(1))}</li>")
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            close_lists()
            out.append(f"<blockquote>{md_inline(quote.group(1))}</blockquote>")
            continue

        close_lists()
        paragraph.append(line.strip())

    flush_paragraph()
    close_lists()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

def elide(title: str) -> str:
    return title if len(title) <= MAX_LABEL else title[: MAX_LABEL - 1].rstrip() + "…"


def label_extent(title: str) -> float:
    """Horizontal space a node needs: its glyph plus its label."""
    return NODE_R + 7 + len(elide(title)) * CHAR_PX


def compute_layout(nodes: dict[str, lib.Node]):
    """Assign every node an (x, y). Returns (positions, lanes, ticks, width, height).

    x is the creation date. Rows within a project lane are packed greedily,
    and a node only joins an existing row if its *label* also clears the one
    before it — labels are the whole point of the map, so they get reserved
    space rather than being truncated to fit.
    """
    dated = [n for n in nodes.values() if n.created]
    if not dated:
        return {}, [], [], MIN_WIDTH, 300

    first = min(n.created for n in dated)
    last = max(n.created for n in dated)
    span_days = max((last - first).days, 1)

    # Width is driven by node count, not by the calendar: two nodes four years
    # apart don't need a four-year-wide canvas. Positions stay date-true.
    width = int(min(MAX_WIDTH, max(MIN_WIDTH, X_PAD * 2 + len(nodes) * PX_PER_NODE)))
    usable = width - X_PAD * 2

    def x_of(date: dt.date) -> float:
        return X_PAD + (date - first).days / span_days * usable

    by_project: dict[str, list[lib.Node]] = defaultdict(list)
    for node in nodes.values():
        by_project[node.project or "(unassigned)"].append(node)

    positions: dict[str, tuple[float, float]] = {}
    lanes: list[dict] = []
    cursor_y = Y_PAD
    right_edge = float(width)

    for project in sorted(by_project):
        members = sorted(by_project[project], key=lambda n: (n.created or first, n.type, n.id))

        row_free_x: list[float] = []   # first free x on each row
        rows: dict[str, int] = {}
        for node in members:
            x = x_of(node.created or first)
            row = next((r for r, free in enumerate(row_free_x) if x >= free), None)
            if row is None:
                row_free_x.append(0.0)
                row = len(row_free_x) - 1
            row_free_x[row] = x + label_extent(node.title) + ROW_MARGIN
            rows[node.id] = row
            right_edge = max(right_edge, row_free_x[row])

        lane_top = cursor_y
        for node in members:
            positions[node.id] = (x_of(node.created or first), lane_top + rows[node.id] * ROW_H)
        lane_height = max(len(row_free_x), 1) * ROW_H
        lanes.append({
            "project": project,
            "top": lane_top - ROW_H / 2,
            "height": lane_height,
            "count": len(members),
        })
        cursor_y = lane_top + lane_height + LANE_GAP

    ticks = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        point = dt.date(year, month, 1)
        if point >= first:
            ticks.append({"x": round(x_of(point), 1), "label": point.strftime("%b %Y")})
        month += 1
        if month > 12:
            month, year = 1, year + 1

    return positions, lanes, ticks, int(right_edge + 40), int(cursor_y + Y_PAD - LANE_GAP)


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------

def commit_url(repo: str, sha: str) -> str | None:
    if not repo or not sha:
        return None
    match = re.match(r"^(?:git@([^:]+):|https?://([^/]+)/)(.+?)(?:\.git)?$", repo.strip())
    if not match:
        return None
    host = match.group(1) or match.group(2)
    return f"https://{host}/{match.group(3)}/commit/{sha}"


def build_payload(nodes, papers, positions, lanes, ticks, width, height) -> dict:
    kids = lib.children_of(nodes)
    backlinks = lib.paper_backlinks(nodes)

    payload_nodes = []
    for node in nodes.values():
        x, y = positions.get(node.id, (X_PAD, Y_PAD))
        history = [
            {"date": (lib.as_date(e.get("date")) or node.created).isoformat(),
             "status": e.get("status", ""),
             "note": e.get("note", "")}
            for e in node.history
            if lib.as_date(e.get("date")) or node.created
        ]
        refs = []
        for ref in node.refs:
            paper = papers.get(ref.lower())
            refs.append({
                "doi": ref,
                "title": paper.title if paper else "",
                "cocited": [i for i in backlinks.get(ref.lower(), []) if i != node.id],
            })

        payload_nodes.append({
            "id": node.id,
            "type": node.type,
            "title": node.title,
            "label": elide(node.title),
            "project": node.project or "(unassigned)",
            "status": node.status,
            "cls": lib.STATUS_CLASS.get(node.status, "idle"),
            "created": node.created.isoformat() if node.created else "",
            "updated": node.updated.isoformat() if node.updated else "",
            "parents": [p for p in node.parents if p in nodes],
            "children": sorted(kids.get(node.id, [])),
            "refs": refs,
            "history": history,
            "x": round(x, 1),
            "y": round(y, 1),
            "shape": TYPE_SHAPE.get(node.type, "circle"),
            "body": md_to_html(node.body),
            "extra": {
                key: (lib.as_date(value).isoformat() if isinstance(value, (dt.date, dt.datetime)) else value)
                for key, value in node.meta.items()
                if key not in set(lib.COMMON_REQUIRED) | set(lib.COMMON_OPTIONAL)
            },
            "commitUrl": commit_url(str(node.meta.get("repo", "")), str(node.meta.get("commit", ""))),
            "terminal": node.is_terminal(),
        })

    all_dates = sorted({d for n in payload_nodes for d in [n["created"]] + [h["date"] for h in n["history"]] if d})

    return {
        "nodes": sorted(payload_nodes, key=lambda n: n["created"]),
        "lanes": lanes,
        "ticks": ticks,
        "width": width,
        "height": height,
        "dates": all_dates,
        "types": sorted(lib.TYPES),
        "statuses": lib.ALL_STATUSES,
        "generated": dt.date.today().isoformat(),
    }


# --------------------------------------------------------------------------
# Mermaid (Phase 0 fallback — renders on GitHub, in a terminal, in an editor)
# --------------------------------------------------------------------------

MERMAID_CLASS = {
    "good": "fill:#1f7a4d,stroke:#0d3d26,color:#fff",
    "bad": "fill:#8c2f2f,stroke:#4d1616,color:#fff",
    "active": "fill:#1f5f9e,stroke:#0d2f4d,color:#fff",
    "pending": "fill:#9e7318,stroke:#4d380a,color:#fff",
    "idle": "fill:#5c5f66,stroke:#2e3033,color:#fff",
}


def render_mermaid(nodes: dict[str, lib.Node]) -> str:
    lines = ["```mermaid", "graph LR"]
    for cls, style in MERMAID_CLASS.items():
        lines.append(f"  classDef {cls} {style};")

    safe = {node_id: "n" + re.sub(r"[^A-Za-z0-9]", "_", node_id) for node_id in nodes}
    by_project: dict[str, list[lib.Node]] = defaultdict(list)
    for node in nodes.values():
        by_project[node.project or "unassigned"].append(node)

    for project in sorted(by_project):
        lines.append(f'  subgraph {re.sub(r"[^A-Za-z0-9]", "_", project)}["{project}"]')
        for node in sorted(by_project[project], key=lambda n: n.id):
            label = node.title.replace('"', "'")
            if len(label) > 46:
                label = label[:43] + "..."
            open_b, close_b = {
                "experiment": ("([", "])"),
                "direction": ("[", "]"),
                "seed": ("{{", "}}"),
                "milestone": ("[/", "/]"),
                "task": ("[[", "]]"),
            }.get(node.type, ("(", ")"))
            lines.append(f'    {safe[node.id]}{open_b}"{label}"{close_b}')
        lines.append("  end")

    for node in nodes.values():
        for parent in node.parents:
            if parent in safe:
                lines.append(f"  {safe[parent]} --> {safe[node.id]}")

    for node in nodes.values():
        lines.append(f"  class {safe[node.id]} {lib.STATUS_CLASS.get(node.status, 'idle')};")

    lines.append("```")
    return "\n".join(lines)


def render_markdown(nodes: dict[str, lib.Node]) -> str:
    if not nodes:
        return "# Cairn\n\nNo nodes yet.\n"

    parts = [
        "# Cairn",
        "",
        f"_Generated {dt.date.today().isoformat()} — {len(nodes)} nodes. Do not edit; run `make build`._",
        "",
        render_mermaid(nodes),
        "",
        "## Nodes",
        "",
        "| id | type | status | project | title |",
        "| --- | --- | --- | --- | --- |",
    ]
    for node in sorted(nodes.values(), key=lambda n: (n.project, n.created or dt.date.min)):
        parts.append(
            f"| [`{node.id}`](../nodes/{node.id}.md) | {node.type} | **{node.status}** "
            f"| {node.project} | {node.title} |"
        )
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def render_html(payload: dict) -> str:
    template = (Path(__file__).parent / "graph_template.html").read_text(encoding="utf-8")
    data = json.dumps(payload, separators=(",", ":"))
    # </script> inside data would close the tag early.
    data = data.replace("</", "<\\/")
    return template.replace("/*__CAIRN_DATA__*/null", data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if validation reports errors")
    args = parser.parse_args()

    issues = lib.validate()
    errors = [i for i in issues if i.level == "error"]
    for issue in errors:
        print(issue, file=sys.stderr)
    if errors and args.check:
        return 1
    if errors:
        print(f"warning: rendering anyway with {len(errors)} validation error(s)", file=sys.stderr)

    nodes, _ = lib.load_nodes()
    papers, _ = lib.load_papers()

    positions, lanes, ticks, width, height = compute_layout(nodes)
    payload = build_payload(nodes, papers, positions, lanes, ticks, width, height)

    build = lib.REPO_ROOT / "build"
    build.mkdir(exist_ok=True)
    (build / "graph.html").write_text(render_html(payload), encoding="utf-8")
    (build / "graph.md").write_text(render_markdown(nodes), encoding="utf-8")

    print(f"build/graph.html  ({len(nodes)} nodes, {len(lanes)} projects)")
    print("build/graph.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
