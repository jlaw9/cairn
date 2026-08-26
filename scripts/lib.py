"""Cairn — parsing, serialization and validation for the research graph.

One file per node. Markdown body, YAML frontmatter. Nodes are append-only:
never delete one, change its status.

The only hard dependency is PyYAML. Everything else is stdlib, deliberately —
this has to run on a laptop and on an HPC login node without a venv dance.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

def _relaunch_under_a_usable_python() -> None:  # pragma: no cover - env path
    """Re-exec this script under the interpreter `find_python.sh` picks.

    The Makefile and the pre-commit hook both ask find_python.sh which
    interpreter can actually run Cairn. Nothing else did: every documented
    invocation is `scripts/new_node.py ...`, which runs under the shebang's
    `python3`. So on any machine where those two differ, `make` works and every
    command in the README, CLAUDE.md and /log fails — including on Kestrel,
    which is the exact split find_python.sh was written for (python3 is 3.6.8
    *with* PyYAML, python3.9 has none).

    Setting CAIRN_PYTHON was already the fix, but you had to know that from a
    traceback that only says "Cairn needs PyYAML".
    """
    if os.environ.get("CAIRN_RELAUNCHED"):
        return                                    # already tried; don't loop
    if not sys.argv or not sys.argv[0] or not Path(sys.argv[0]).is_file():
        return                                    # not a script run; nothing to re-exec
    finder = Path(__file__).resolve().parent / "find_python.sh"
    if not finder.exists():
        return

    import subprocess
    try:
        found = subprocess.run(
            [str(finder)], capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if not found or not Path(found).exists():
        return
    try:
        if Path(found).resolve() == Path(sys.executable).resolve():
            return                                # same interpreter; it would fail again
    except OSError:
        return

    os.environ["CAIRN_RELAUNCHED"] = "1"
    os.execv(found, [found, str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])


try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not a code path
    _relaunch_under_a_usable_python()             # returns only if that failed
    sys.exit(
        "Cairn needs PyYAML, and no interpreter that has it was found.\n"
        "\n"
        "  Cairn needs Python >= 3.7 with PyYAML. This ran under\n"
        f"    {sys.executable}\n"
        "  which has no yaml module, and scripts/find_python.sh found no\n"
        "  alternative. Either install it:\n"
        "\n"
        "    conda install pyyaml            # conda-managed python\n"
        "    python3 -m pip install --user pyyaml\n"
        "    python3 -m venv ~/.cairn/venv && ~/.cairn/venv/bin/pip install pyyaml\n"
        "\n"
        "  or point Cairn at an interpreter that already has it:\n"
        "\n"
        "    export CAIRN_PYTHON=/path/to/python\n"
        "\n"
        "  Then `make python` should print that interpreter.\n"
    )

#: CAIRN_ROOT lets the test suite point the whole library at a fixture graph.
REPO_ROOT = Path(os.environ.get("CAIRN_ROOT") or Path(__file__).resolve().parent.parent)

# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

# Every optional field is a field that stops getting filled in. Adding to this
# table is a real decision, not a convenience. See docs/schema.md.

COMMON_REQUIRED = ["id", "type", "title", "project", "status", "created", "updated"]
COMMON_OPTIONAL = ["parents", "relates", "refs", "history"]

#: Typed relations, mapped to how they read from the other end.
#:
#: `parents` is lineage: what this work grew out of. It is a DAG, it drives the
#: layout and the "isolate lineage" view, and it says nothing about *meaning* —
#: every arrow looks the same. `relates` is the meaning layer, and it earned its
#: place in the 2026-08 backfill, where three findings could only be connected
#: in prose: a scramble panel that contradicted an earlier one, an epitaxial
#: design that superseded a refuted H-bond hypothesis, and a task that resolves
#: an open threat to a paper's central claim. A reader scanning the map saw
#: three identical grey arrows.
#:
#: Four types, and the bar for a fifth is a real node that needs it. Relations
#: are deliberately NOT cycle-checked: two results may contradict each other
#: symmetrically, and that is a fact about the research, not a defect.
RELATIONS = {
    "supports": "supported by",
    "contradicts": "contradicted by",
    "supersedes": "superseded by",
    "resolves": "resolved by",
}

#: Keys a history entry may carry. Anything else means the writer mangled it —
#: see the flow-scalar quoting note in _scalar().
HISTORY_KEYS = {"date", "status", "note"}


@dataclass(frozen=True)
class TypeSpec:
    statuses: list[str]
    #: statuses that mean "this thread is finished, stop nagging about it"
    terminal: set[str]
    required: list[str]
    optional: list[str]
    #: What `new_node.py` uses when no --status is given. Explicit rather than
    #: statuses[0], so `statuses` can be listed in lifecycle order without the
    #: first entry silently becoming the default — adding `planned` to the front
    #: of experiment would otherwise have changed what /log creates.
    default: str = ""

    @property
    def default_status(self) -> str:
        return self.default or self.statuses[0]


TYPES: dict[str, TypeSpec] = {
    # `planned` exists so a pre-registration can be honest. README section B
    # says to open the experiment *before* the first job goes to the queue —
    # that's the whole point, since a claim written before the result is a
    # pre-registration and written after it is a story. But the only status
    # available for that was `running`, which is false on a job that hasn't
    # started, and it lies twice: the replay slider shows the experiment running
    # on a date it wasn't, and `running` is how you find what to check on today.
    # Non-terminal, so an experiment left planned keeps surfacing.
    "experiment": TypeSpec(
        statuses=["planned", "running", "worked", "dead", "parked"],
        terminal={"worked", "dead"},
        required=[],
        optional=["repo", "commit", "host", "artifacts"],
        default="running",
    ),
    "direction": TypeSpec(
        statuses=["open", "parked", "closed"],
        terminal={"closed"},
        required=[],
        optional=[],
    ),
    "seed": TypeSpec(
        statuses=["seed", "promoted", "killed"],
        terminal={"promoted", "killed"},
        required=[],
        optional=["origin", "contacts"],
    ),
    "milestone": TypeSpec(
        statuses=["planned", "submitted", "accepted", "done"],
        terminal={"accepted", "done"},
        required=[],
        optional=["venue", "date", "url"],
    ),
    "task": TypeSpec(
        statuses=["todo", "doing", "done", "dropped"],
        terminal={"done", "dropped"},
        required=[],
        optional=["due", "source"],
    ),
}

ALL_STATUSES = sorted({s for spec in TYPES.values() for s in spec.statuses})

#: Coarse buckets used for colour in the rendered graph. Every status in TYPES
#: must appear here exactly once; validate_schema_table() enforces that.
STATUS_CLASS = {
    "worked": "good", "done": "good", "accepted": "good", "promoted": "good",
    "dead": "bad", "killed": "bad", "dropped": "bad", "closed": "bad",
    "running": "active", "doing": "active", "submitted": "active",
    "open": "pending", "todo": "pending", "seed": "pending", "planned": "pending",
    "parked": "idle",
}

ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
ARTIFACT_RE = re.compile(r"^[A-Za-z0-9_.-]+:/\S*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

#: Field emission order. Anything not listed lands after these, alphabetically.
#: Stable ordering is what keeps diffs readable, which is half the point of
#: putting this in git at all.
FIELD_ORDER = [
    "id", "type", "title", "project", "status", "created", "updated",
    "repo", "commit", "host", "artifacts",
    "origin", "contacts",
    "venue", "date", "url",
    "due", "source",
    "parents", "relates", "refs", "history",
]

#: Papers are a different record with a different natural order — the DOI is the
#: identity, so it leads, the way `id` leads for a node. `bibkey` ties the page
#: to the entry Overleaf cites; `md` points at the converted full text on a
#: compute host, which is far too big to live in this repo.
PAPER_FIELD_ORDER = ["doi", "title", "authors", "year", "venue", "bibkey", "md"]


def validate_schema_table() -> None:
    """Guard against the schema table itself drifting out of sync."""
    for name, spec in TYPES.items():
        for status in spec.statuses:
            assert status in STATUS_CLASS, f"{name}.{status} missing from STATUS_CLASS"
        assert spec.terminal <= set(spec.statuses), f"{name}: bad terminal set"


validate_schema_table()


# --------------------------------------------------------------------------
# Node
# --------------------------------------------------------------------------


@dataclass
class Node:
    path: Path
    meta: dict
    body: str

    @property
    def id(self) -> str:
        return str(self.meta.get("id", self.path.stem))

    @property
    def type(self) -> str:
        return str(self.meta.get("type", ""))

    @property
    def status(self) -> str:
        return str(self.meta.get("status", ""))

    @property
    def project(self) -> str:
        return str(self.meta.get("project", ""))

    @property
    def title(self) -> str:
        return str(self.meta.get("title", self.id))

    @property
    def parents(self) -> list[str]:
        return list(self.meta.get("parents") or [])

    @property
    def relates(self) -> list[dict]:
        """Typed relations to other nodes: [{to, type, note?}, ...]."""
        return [r for r in (self.meta.get("relates") or []) if isinstance(r, dict)]

    @property
    def refs(self) -> list[str]:
        return [str(r) for r in (self.meta.get("refs") or [])]

    @property
    def history(self) -> list[dict]:
        return list(self.meta.get("history") or [])

    @property
    def created(self) -> dt.date | None:
        return as_date(self.meta.get("created"))

    @property
    def updated(self) -> dt.date | None:
        return as_date(self.meta.get("updated"))

    @property
    def spec(self) -> TypeSpec | None:
        return TYPES.get(self.type)

    # A property, like every other accessor here. As a plain method it read
    # identically at the call site and was always truthy — `if node.is_terminal:`
    # silently meant "if this bound method exists", which skipped every node in
    # the first version of the digest.
    @property
    def is_terminal(self) -> bool:
        return bool(self.spec and self.status in self.spec.terminal)

    def status_on(self, when: dt.date) -> str | None:
        """Status as of `when`, from the history log. None if not yet created.

        This is what makes replay work: check out an old commit, or just drag
        the time slider, and the graph shows what was known then.
        """
        result = None
        for entry in self.history:
            date = as_date(entry.get("date"))
            if date is not None and date <= when:
                result = entry.get("status")
        if result is None and self.created and self.created <= when:
            result = self.status
        return result

    def set_status(self, status: str, note: str = "", when: dt.date | None = None) -> None:
        """Append a history entry and move `status` in lockstep.

        Always go through this. Hand-editing `status:` without touching
        `history:` is the drift the validator exists to catch.
        """
        when = when or dt.date.today()
        if self.spec and status not in self.spec.statuses:
            raise ValueError(
                f"'{status}' is not a valid status for type '{self.type}' "
                f"(expected one of {', '.join(self.spec.statuses)})"
            )
        entry = {"date": when, "status": status}
        if note:
            entry["note"] = note
        self.meta.setdefault("history", []).append(entry)
        self.meta["status"] = status
        self.meta["updated"] = when

    def to_text(self) -> str:
        return f"---\n{dump_frontmatter(self.meta)}---\n\n{self.body.strip()}\n"

    def write(self) -> None:
        self.path.write_text(self.to_text(), encoding="utf-8")


# --------------------------------------------------------------------------
# Parsing / serialization
# --------------------------------------------------------------------------


def as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def parse_file(path: Path) -> Node:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: no YAML frontmatter (file must start with '---')")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: malformed YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    return Node(path=path, meta=meta, body=match.group(2))


def _scalar(value, flow: bool = False) -> str:
    """Emit a YAML scalar, quoting only when it would otherwise be ambiguous.

    `flow=True` means the scalar lands inside `{...}`, where the set of
    dangerous characters is strictly larger: a bare comma ends the value and
    starts a new key. A history note reading "past 1,000 systems" silently
    became `note: past 1` plus a junk key `000 systems` — parseable YAML, wrong
    data, and invisible to a validator that only looks at known keys. Round-trip
    safety is not optional here; these files *are* the database.
    """
    if isinstance(value, (dt.date, dt.datetime)):
        return as_date(value).isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "~"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    needs_quotes = (
        text == ""
        or text.strip() != text
        or text[0] in "&*!|>%@`{}[]#-?,"
        or ": " in text
        or text.endswith(":")
        or " #" in text          # starts a trailing comment mid-value
        or (flow and any(c in text for c in ",{}[]"))
        or text.lower() in {"true", "false", "null", "yes", "no", "on", "off", "~"}
    )
    if needs_quotes:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _flow_map(mapping: dict) -> str:
    inner = ", ".join(f"{k}: {_scalar(v, flow=True)}" for k, v in mapping.items())
    return "{" + inner + "}"


def dump_frontmatter(meta: dict) -> str:
    """Serialize frontmatter with stable field order and readable diffs.

    Hand-rolled rather than yaml.dump because we want history entries on one
    line each (a status change should be a one-line diff) and a field order
    that reads top-down instead of alphabetically.
    """
    # A paper page has no `id`; its DOI is its identity and should lead.
    order = PAPER_FIELD_ORDER if ("doi" in meta and "id" not in meta) else FIELD_ORDER
    keys = [k for k in order if k in meta]
    keys += sorted(k for k in meta if k not in order)

    lines: list[str] = []
    for key in keys:
        value = meta[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            if all(isinstance(item, dict) for item in value):
                lines.append(f"{key}:")
                lines.extend(f"  - {_flow_map(item)}" for item in value)
            elif key in {"parents", "refs"} and len(value) <= 4:
                lines.append(f"{key}: [" + ", ".join(_scalar(v) for v in value) + "]")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_scalar(v)}" for v in value)
        elif isinstance(value, dict):
            lines.append(f"{key}: {_flow_map(value)}")
        else:
            lines.append(f"{key}: {_scalar(value)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def node_dir(root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / "nodes"


def paper_dir(root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / "papers"


def load_nodes(root: Path | None = None) -> tuple[dict[str, Node], list[str]]:
    """Load every node. Returns (by-id map, list of parse errors)."""
    nodes: dict[str, Node] = {}
    errors: list[str] = []
    for path in sorted(node_dir(root).glob("*.md")):
        try:
            node = parse_file(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if node.id in nodes:
            errors.append(
                f"{path}: duplicate id '{node.id}' (also {nodes[node.id].path.name})"
            )
            continue
        nodes[node.id] = node
    return nodes, errors


def load_papers(root: Path | None = None) -> tuple[dict[str, Node], list[str]]:
    """Load the papers registry, keyed by canonical DOI.

    Keyed by the `doi:` field, never by un-slugging the filename — the
    `/` -> `__` slug is not reversibly unique for DOIs containing `__`.
    """
    papers: dict[str, Node] = {}
    errors: list[str] = []
    for path in sorted(paper_dir(root).glob("*.md")):
        try:
            node = parse_file(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        doi = str(node.meta.get("doi", "")).strip().lower()
        if not doi:
            errors.append(f"{path}: paper has no 'doi:' field")
            continue
        papers[doi] = node
    return papers, errors


def slug_doi(doi: str) -> str:
    """Filename slug for a DOI. Filename only — never parsed back into a DOI."""
    return doi.strip().lower().replace("/", "__")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


@dataclass
class Issue:
    level: str  # "error" | "warn"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():5s} {self.where}: {self.message}"


def _check_common(node: Node, out: list[Issue]) -> None:
    where = node.path.name
    err = lambda m: out.append(Issue("error", where, m))  # noqa: E731
    warn = lambda m: out.append(Issue("warn", where, m))  # noqa: E731

    for key in COMMON_REQUIRED:
        value = node.meta.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            err(f"missing required field '{key}'")

    if node.meta.get("id") and node.id != node.path.stem:
        err(f"id '{node.id}' does not match filename stem '{node.path.stem}'")
    if node.meta.get("id") and not ID_RE.match(node.id):
        err(f"id '{node.id}' is not a date-prefixed lowercase slug (YYYY-MM-DD-some-slug)")

    if node.type and node.type not in TYPES:
        err(f"unknown type '{node.type}' (expected one of {', '.join(sorted(TYPES))})")
        return

    spec = node.spec
    if spec and node.status and node.status not in spec.statuses:
        err(
            f"status '{node.status}' is not valid for type '{node.type}' "
            f"(expected one of {', '.join(spec.statuses)})"
        )

    created, updated = node.created, node.updated
    if node.meta.get("created") is not None and created is None:
        err(f"'created' is not an ISO date: {node.meta['created']!r}")
    if node.meta.get("updated") is not None and updated is None:
        err(f"'updated' is not an ISO date: {node.meta['updated']!r}")
    if created and updated and updated < created:
        err(f"updated ({updated}) is before created ({created})")
    if created and not node.id.startswith(created.isoformat()):
        warn(f"id date prefix disagrees with created: {created}")

    # Unknown keys are how schemas rot in silence.
    known = set(COMMON_REQUIRED) | set(COMMON_OPTIONAL)
    if spec:
        known |= set(spec.required) | set(spec.optional)
    for key in sorted(set(node.meta) - known):
        warn(f"unknown field '{key}' — add it to the schema or remove it")

    for key in (spec.required if spec else []):
        if not node.meta.get(key):
            err(f"type '{node.type}' requires field '{key}'")

    for ref in node.refs:
        if not DOI_RE.match(ref):
            err(f"ref '{ref}' is not a bare DOI (expected 10.xxxx/suffix)")


def _check_history(node: Node, out: list[Issue]) -> None:
    where = node.path.name
    history = node.history
    if not history:
        out.append(Issue("error", where, "history is empty — every node needs at least a creation entry"))
        return

    spec = node.spec
    previous: dt.date | None = None
    for index, entry in enumerate(history):
        label = f"history[{index}]"
        if not isinstance(entry, dict):
            out.append(Issue("error", where, f"{label} is not a mapping"))
            continue
        date = as_date(entry.get("date"))
        if date is None:
            out.append(Issue("error", where, f"{label} has a missing or malformed date"))
        else:
            if previous and date < previous:
                out.append(Issue("error", where, f"{label} date {date} goes backwards"))
            previous = date
        status = entry.get("status")
        if not status:
            out.append(Issue("error", where, f"{label} has no status"))
        elif spec and status not in spec.statuses:
            out.append(Issue("error", where, f"{label} status '{status}' invalid for type '{node.type}'"))

        # An unexpected key here is almost always a mangled note rather than a
        # deliberate field: an unquoted comma in flow style splits the value and
        # turns its tail into a key. Silent, and it eats the interpretation.
        for key in sorted(set(entry) - HISTORY_KEYS):
            out.append(Issue(
                "error", where,
                f"{label} has unexpected key '{key}' — a note with a comma that "
                f"wasn't quoted splits into a bogus key; rewrite via set_status()",
            ))

    last = history[-1]
    if isinstance(last, dict):
        if last.get("status") and node.status and last["status"] != node.status:
            out.append(Issue(
                "error", where,
                f"status '{node.status}' disagrees with last history entry "
                f"'{last['status']}' — use set_status(), don't hand-edit",
            ))
        last_date = as_date(last.get("date"))
        if last_date and node.updated and node.updated < last_date:
            out.append(Issue("error", where, f"updated ({node.updated}) predates last history entry ({last_date})"))


def _check_type_extras(node: Node, out: list[Issue]) -> None:
    where = node.path.name
    err = lambda m: out.append(Issue("error", where, m))  # noqa: E731
    warn = lambda m: out.append(Issue("warn", where, m))  # noqa: E731

    if node.type == "experiment":
        commit = node.meta.get("commit")
        if commit and not SHA_RE.match(str(commit).strip()):
            err(f"commit '{commit}' is not a git SHA — reference commits, never branches")
        if commit and not node.meta.get("repo"):
            warn("has a commit but no repo — the SHA is unresolvable without it")
        for artifact in node.meta.get("artifacts") or []:
            if not ARTIFACT_RE.match(str(artifact)):
                err(f"artifact '{artifact}' is not host:/absolute/path")

    elif node.type == "seed":
        for contact in node.meta.get("contacts") or []:
            if not isinstance(contact, dict) or not contact.get("name"):
                err(f"contact {contact!r} needs at least a name")

    elif node.type == "milestone":
        if node.meta.get("date") is not None and as_date(node.meta["date"]) is None:
            err(f"'date' is not an ISO date: {node.meta['date']!r}")

    elif node.type == "task":
        if node.meta.get("due") is not None and as_date(node.meta["due"]) is None:
            err(f"'due' is not an ISO date: {node.meta['due']!r}")
        if not node.meta.get("due") and node.status in {"todo", "doing"}:
            warn("open task with no due date — it will never surface in /weekly")


def _check_edges(nodes: dict[str, Node], out: list[Issue]) -> None:
    for node in nodes.values():
        for parent in node.parents:
            if parent not in nodes:
                out.append(Issue("error", node.path.name, f"dangling parent '{parent}'"))
            elif parent == node.id:
                out.append(Issue("error", node.path.name, "node is its own parent"))

    # Cycle detection. A cycle isn't just untidy — it makes the milestone
    # rollup non-terminating and silently corrupts the time axis.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(nodes, WHITE)

    def walk(start: str) -> None:
        stack = [(start, iter(nodes[start].parents))]
        colour[start] = GREY
        while stack:
            current, parents = stack[-1]
            advanced = False
            for parent in parents:
                if parent not in nodes:
                    continue
                if colour[parent] == GREY:
                    out.append(Issue(
                        "error", nodes[current].path.name,
                        f"cycle in parents: '{current}' -> '{parent}' closes a loop",
                    ))
                elif colour[parent] == WHITE:
                    colour[parent] = GREY
                    stack.append((parent, iter(nodes[parent].parents)))
                    advanced = True
                    break
            if not advanced:
                colour[current] = BLACK
                stack.pop()

    for node_id in nodes:
        if colour[node_id] == WHITE:
            walk(node_id)


def _check_relations(nodes: dict[str, Node], out: list[Issue]) -> None:
    """Typed relations. Unlike parents these are not cycle-checked — a mutual
    contradiction is a legitimate statement about two results."""
    for node in nodes.values():
        where = node.path.name
        raw = node.meta.get("relates") or []
        if raw and not isinstance(raw, list):
            out.append(Issue("error", where, "'relates' must be a list"))
            continue

        seen: set[tuple[str, str]] = set()
        for index, entry in enumerate(raw):
            label = f"relates[{index}]"
            if not isinstance(entry, dict):
                out.append(Issue("error", where, f"{label} is not a mapping (want {{to: <id>, type: <type>}})"))
                continue
            for key in sorted(set(entry) - {"to", "type", "note"}):
                out.append(Issue("error", where, f"{label} has unexpected key '{key}'"))

            target, kind = str(entry.get("to", "")).strip(), str(entry.get("type", "")).strip()
            if not target:
                out.append(Issue("error", where, f"{label} has no 'to'"))
            elif target == node.id:
                out.append(Issue("error", where, f"{label} points at itself"))
            elif target not in nodes:
                out.append(Issue("error", where, f"{label} dangling target '{target}'"))

            if not kind:
                out.append(Issue("error", where, f"{label} has no 'type'"))
            elif kind not in RELATIONS:
                out.append(Issue(
                    "error", where,
                    f"{label} unknown relation '{kind}' (expected one of {', '.join(sorted(RELATIONS))})",
                ))

            if target and kind:
                if (target, kind) in seen:
                    out.append(Issue("warn", where, f"{label} duplicates an earlier '{kind}' to '{target}'"))
                seen.add((target, kind))
                # A relation with no note is a claim with no argument. The reader
                # six months out needs the why, not just the arrow.
                if not str(entry.get("note", "")).strip():
                    out.append(Issue("warn", where, f"{label} '{kind}' has no note explaining why"))


def _check_refs(nodes: dict[str, Node], papers: dict[str, Node], out: list[Issue]) -> None:
    for node in nodes.values():
        for ref in node.refs:
            if ref.lower() not in papers:
                out.append(Issue(
                    "warn", node.path.name,
                    f"ref '{ref}' has no page in papers/ — backlinks will be thin",
                ))


#: `[[node-id]]` in a body. The renderer turns these into live links, so a
#: typo'd or since-renamed id is a dead reference — cheap to catch here, and
#: invisible otherwise until someone clicks it.
BODY_LINK = re.compile(r"\[\[\s*(\d{4}-\d{2}-\d{2}-[a-z0-9-]+?)\s*\]\]")


def _check_body_links(nodes: dict[str, Node], out: list[Issue]) -> None:
    for node in nodes.values():
        for target in dict.fromkeys(BODY_LINK.findall(node.body)):
            if target not in nodes:
                out.append(Issue(
                    "warn", node.path.name,
                    f"body links to [[{target}]], which is not a node",
                ))


def validate(root: Path | None = None) -> list[Issue]:
    """Validate the whole graph. Errors block a commit; warnings don't."""
    issues: list[Issue] = []
    nodes, node_errors = load_nodes(root)
    papers, paper_errors = load_papers(root)
    issues += [Issue("error", "nodes/", message) for message in node_errors]
    issues += [Issue("error", "papers/", message) for message in paper_errors]

    for node in nodes.values():
        _check_common(node, issues)
        _check_history(node, issues)
        _check_type_extras(node, issues)

    _check_edges(nodes, issues)
    _check_relations(nodes, issues)
    _check_refs(nodes, papers, issues)
    _check_body_links(nodes, issues)
    return issues


# --------------------------------------------------------------------------
# Notes on a node body
# --------------------------------------------------------------------------

# A note is a human sentence added to a node after the fact — a second thought, a
# doubt, a "this is the one that matters" — and it is a body edit, not a status
# change. That distinction is the whole design:
#
#   * No new field. `notes:` in the frontmatter would be a fifth list to
#     maintain and a sixth thing to validate, against the resist-new-fields
#     rule, and the body is already where prose lives.
#   * `status` and `updated` do not move. Rule 4 ties those to each other, and a
#     note is not a claim about the state of the work. Moving `updated` for a
#     note would make the replay slider show a status change that never happened.
#   * It is still findable, because the line carries its own date. `standup` and
#     `digest` read `## Next` out of bodies already; reading `## Notes` the same
#     way costs one regex and invents no bookkeeping.
#
# The shape is fixed rather than free prose because it has to parse back out:
#
#     - **2026-08-26** (jlaw) the variance looks bimodal — check the seeds
#
# Bold date first so it reads correctly in the rendered panel, in GitHub, and in
# Obsidian, none of which know anything about this format.

NOTES_HEADING = "notes"

NOTE_RE = re.compile(
    r"^-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*(?:\s+\(([^)]*)\))?\s*(.*)$"
)

#: Matches a markdown heading at any of the levels node bodies actually use.
HEADING_RE = re.compile(r"^\s{0,3}#{2,4}\s*(.+?)\s*$", re.MULTILINE)


def body_section(body: str, headings) -> str:
    """The text under the first heading matching `headings`, or "".

    `headings` is a collection of lowercased heading titles. Matching is on the
    title with a trailing colon stripped, because hand-written nodes write both
    `## Next` and `## Next:`.
    """
    wanted = {h.lower() for h in headings}
    matches = list(HEADING_RE.finditer(body))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower().rstrip(":") not in wanted:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        return body[match.end():end].strip()
    return ""


def read_notes(node: Node) -> list[dict]:
    """Parsed `## Notes` entries, in the order written (oldest first).

    Lines that don't match the shape are kept as continuation text on the
    previous note rather than dropped. Someone will hand-edit this section — it
    is markdown in a text file, that is the point — and losing their sentence
    because it lacked a bold date would be the wrong trade.
    """
    section = body_section(node.body, [NOTES_HEADING])
    if not section:
        return []
    notes: list[dict] = []
    for line in section.splitlines():
        match = NOTE_RE.match(line.strip())
        if match:
            notes.append({
                "date": as_date(match.group(1)),
                "who": (match.group(2) or "").strip(),
                "text": match.group(3).strip(),
            })
        elif notes and line.strip():
            notes[-1]["text"] = (notes[-1]["text"] + " " + line.strip()).strip()
    return notes


def format_note(text: str, who: str = "", when: dt.date | None = None) -> str:
    """One `## Notes` bullet. Newlines are folded — a note is one line."""
    when = when or dt.date.today()
    flat = " ".join(str(text).split())
    stamp = f"- **{when.isoformat()}**"
    if who:
        stamp += f" ({who})"
    return f"{stamp} {flat}".rstrip()


def append_note(node: Node, text: str, who: str = "", when: dt.date | None = None) -> str:
    """Add a note to the node's `## Notes` section, creating it if absent.

    Appends *inside* the existing section rather than at the end of the file, so
    a `## Notes` written above `## Next` stays where the author put it and notes
    stay in one place instead of accumulating stray headings.
    """
    line = format_note(text, who, when)
    body = node.body.rstrip()
    matches = list(HEADING_RE.finditer(body))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower().rstrip(":") != NOTES_HEADING:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        head, section, tail = body[:match.end()], body[match.end():end], body[end:]
        section = section.rstrip() + "\n" + line + "\n"
        node.body = (head + section + ("\n" + tail.lstrip("\n") if tail.strip() else "")).rstrip() + "\n"
        return line
    node.body = f"{body}\n\n## Notes\n\n{line}\n"
    return line


# --------------------------------------------------------------------------
# Derived views
# --------------------------------------------------------------------------


def children_of(nodes: dict[str, Node]) -> dict[str, list[str]]:
    kids: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node in nodes.values():
        for parent in node.parents:
            if parent in kids:
                kids[parent].append(node.id)
    return kids


def relation_backlinks(nodes: dict[str, Node]) -> dict[str, list[dict]]:
    """Target id -> the relations pointing at it, phrased from the target's side.

    Without this a contradiction is only discoverable from whichever node
    happened to be written second, which is precisely the node a reader won't
    have found yet.
    """
    inbound: dict[str, list[dict]] = {}
    for node in nodes.values():
        for rel in node.relates:
            target, kind = str(rel.get("to", "")), str(rel.get("type", ""))
            if target not in nodes or kind not in RELATIONS:
                continue
            inbound.setdefault(target, []).append({
                "from": node.id,
                "type": kind,
                "label": RELATIONS[kind],
                "note": str(rel.get("note", "")),
            })
    return inbound


def paper_backlinks(nodes: dict[str, Node]) -> dict[str, list[str]]:
    """DOI -> node ids that cite it."""
    links: dict[str, list[str]] = {}
    for node in nodes.values():
        for ref in node.refs:
            links.setdefault(ref.lower(), []).append(node.id)
    return links


def projects(nodes: dict[str, Node]) -> list[str]:
    return sorted({node.project for node in nodes.values() if node.project})
