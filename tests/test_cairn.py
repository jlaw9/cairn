#!/usr/bin/env python3
"""Tests for the Cairn schema, validator and renderer.

Runs against a throwaway fixture graph, never the real one. Every check here
corresponds to a way the graph could silently rot.

    python3 tests/test_cairn.py
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

FIXTURE = Path(tempfile.mkdtemp(prefix="cairn-test-"))
for sub in ("nodes", "papers", "build"):
    (FIXTURE / sub).mkdir(parents=True)

# lib reads CAIRN_ROOT at import time, so this has to happen before the import.
os.environ["CAIRN_ROOT"] = str(FIXTURE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import lib  # noqa: E402
import build_graph  # noqa: E402
import new_node  # noqa: E402


def write(name: str, text: str, folder: str = "nodes") -> Path:
    path = FIXTURE / folder / name
    path.write_text(text.lstrip("\n"), encoding="utf-8")
    return path


def clear() -> None:
    for folder in ("nodes", "papers"):
        for path in (FIXTURE / folder).glob("*.md"):
            path.unlink()


def node_text(node_id, type_="experiment", status="running", project="prekd",
              created="2026-08-02", updated=None, parents="[]", extra="",
              history=None) -> str:
    updated = updated or created
    history = history or f"  - {{date: {created}, status: {status}, note: created}}"
    return f"""
---
id: {node_id}
type: {type_}
title: A title for {node_id}
project: {project}
status: {status}
created: {created}
updated: {updated}
{extra}parents: {parents}
history:
{history}
---

## Claim

Body text.
"""


ROOT_ID = "2026-07-20-prekd-scoping"
CHILD_ID = "2026-08-02-prekd-cosmo-baseline"


def valid_pair() -> None:
    write(f"{ROOT_ID}.md", node_text(ROOT_ID, "direction", "open", created="2026-07-20"))
    write(f"{CHILD_ID}.md", node_text(CHILD_ID, parents=f"[{ROOT_ID}]"))


def errors():
    return [i for i in lib.validate() if i.level == "error"]


def error_text() -> str:
    return " | ".join(i.message for i in errors())


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        clear()

    def test_clean_graph_has_no_errors(self):
        valid_pair()
        self.assertEqual(errors(), [], error_text())

    def test_id_must_match_filename(self):
        valid_pair()
        write("2026-08-09-wrong-name.md", node_text(CHILD_ID + "-x"))
        self.assertIn("does not match filename stem", error_text())

    def test_status_must_be_valid_for_type(self):
        write(f"{CHILD_ID}.md", node_text(
            CHILD_ID, status="promoted",
            history=f"  - {{date: 2026-08-02, status: promoted}}"))
        self.assertIn("is not valid for type 'experiment'", error_text())

    def test_status_history_drift_is_caught(self):
        # The single most likely corruption: someone edits `status:` by hand.
        write(f"{CHILD_ID}.md", node_text(
            CHILD_ID, status="dead",
            history="  - {date: 2026-08-02, status: running, note: created}"))
        self.assertIn("disagrees with last history entry", error_text())

    def test_dangling_parent(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, parents="[2026-01-01-nope]"))
        self.assertIn("dangling parent", error_text())

    def test_cycle_detection(self):
        a, b = "2026-08-01-prekd-a", "2026-08-02-prekd-b"
        write(f"{a}.md", node_text(a, created="2026-08-01", parents=f"[{b}]"))
        write(f"{b}.md", node_text(b, created="2026-08-02", parents=f"[{a}]"))
        self.assertIn("cycle in parents", error_text())

    def test_self_parent(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, parents=f"[{CHILD_ID}]"))
        self.assertIn("its own parent", error_text())

    def test_empty_history_rejected(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, history="  []").replace("history:\n  []", "history: []"))
        self.assertIn("history is empty", error_text())

    def test_history_must_not_go_backwards(self):
        write(f"{CHILD_ID}.md", node_text(
            CHILD_ID, status="dead", updated="2026-08-05",
            history="  - {date: 2026-08-05, status: running}\n"
                    "  - {date: 2026-08-02, status: dead}"))
        self.assertIn("goes backwards", error_text())

    def test_updated_before_created(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, created="2026-08-02", updated="2026-07-01"))
        self.assertIn("is before created", error_text())

    def test_malformed_doi(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, extra="refs: [not-a-doi]\n"))
        self.assertIn("is not a bare DOI", error_text())

    def test_branch_reference_rejected(self):
        # Nodes point at commits. A branch name here defeats the whole design.
        write(f"{CHILD_ID}.md", node_text(
            CHILD_ID, extra="repo: git@github.com:jlaw9/prekd.git\ncommit: main\n"))
        self.assertIn("is not a git SHA", error_text())

    def test_artifact_must_be_host_path(self):
        write(f"{CHILD_ID}.md", node_text(
            CHILD_ID, extra="artifacts:\n  - /scratch/jlaw/run-0142\n"))
        self.assertIn("is not host:/absolute/path", error_text())

    def test_unknown_field_warns_but_does_not_block(self):
        valid_pair()
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, parents=f"[{ROOT_ID}]", extra="mood: optimistic\n"))
        issues = lib.validate()
        self.assertEqual([i for i in issues if i.level == "error"], [])
        self.assertTrue(any("unknown field 'mood'" in i.message for i in issues))

    def test_duplicate_id(self):
        valid_pair()
        write("2026-08-03-prekd-dup.md", node_text(CHILD_ID))
        self.assertIn("duplicate id", error_text())

    def test_schema_table_is_self_consistent(self):
        lib.validate_schema_table()


class NodeTest(unittest.TestCase):
    def setUp(self):
        clear()
        valid_pair()

    def test_round_trip_preserves_meta(self):
        node = lib.parse_file(FIXTURE / "nodes" / f"{CHILD_ID}.md")
        node.write()
        again = lib.parse_file(node.path)
        self.assertEqual(node.meta, again.meta)
        self.assertEqual(node.body.strip(), again.body.strip())

    def test_set_status_moves_both_fields(self):
        node = lib.parse_file(FIXTURE / "nodes" / f"{CHILD_ID}.md")
        node.set_status("dead", "solvation model wrong for ionics", dt.date(2026, 8, 5))
        node.write()
        self.assertEqual(errors(), [], error_text())

        again = lib.parse_file(node.path)
        self.assertEqual(again.status, "dead")
        self.assertEqual(again.updated, dt.date(2026, 8, 5))
        self.assertEqual(len(again.history), 2)
        self.assertEqual(again.history[-1]["note"], "solvation model wrong for ionics")

    def test_set_status_rejects_wrong_vocabulary(self):
        node = lib.parse_file(FIXTURE / "nodes" / f"{CHILD_ID}.md")
        with self.assertRaises(ValueError):
            node.set_status("promoted")

    def test_status_replay(self):
        node = lib.parse_file(FIXTURE / "nodes" / f"{CHILD_ID}.md")
        node.set_status("dead", "nope", dt.date(2026, 8, 5))
        self.assertIsNone(node.status_on(dt.date(2026, 7, 1)))
        self.assertEqual(node.status_on(dt.date(2026, 8, 3)), "running")
        self.assertEqual(node.status_on(dt.date(2026, 8, 9)), "dead")

    def test_children_and_terminal(self):
        nodes, _ = lib.load_nodes()
        self.assertEqual(lib.children_of(nodes)[ROOT_ID], [CHILD_ID])
        self.assertFalse(nodes[CHILD_ID].is_terminal())

    def test_doi_slug_is_filename_only(self):
        self.assertEqual(lib.slug_doi("10.1038/s41586-024-01234-5"), "10.1038__s41586-024-01234-5")


class SlugTest(unittest.TestCase):
    def test_long_title_produces_a_short_id(self):
        slug = new_node.shorten(new_node.slugify("prekd-COSMO-RS baseline on the 40-solvent set"))
        self.assertLessEqual(len(slug), new_node.SLUG_MAX)
        self.assertTrue(slug.startswith("prekd-"))
        self.assertNotIn("-on-", slug)   # stopwords dropped

    def test_project_key_always_survives(self):
        slug = new_node.shorten(new_node.slugify("polyid-extraordinarily-verbose-title-that-runs-on"))
        self.assertTrue(slug.startswith("polyid"))

    def test_short_title_is_left_alone(self):
        self.assertEqual(new_node.shorten(new_node.slugify("prekd-GNN attempt")), "prekd-gnn-attempt")

    def test_generated_id_validates(self):
        clear()
        import argparse
        args = argparse.Namespace(
            type="experiment", title="COSMO-RS baseline on the 40-solvent set",
            project="prekd", status=None, note="", date="2026-04-20", slug=None,
            parent=[], ref=[], repo="git@github.com:jlaw9/prekd.git", commit="a3f9c21",
            host="kestrel", artifact=[], origin=None, venue=None, url=None,
            due=None, source=None)
        node = new_node.build(args)
        node.write()
        self.assertEqual(node.id, "2026-04-20-prekd-cosmo-rs-baseline-40-solvent")
        self.assertEqual(errors(), [], error_text())


class RenderTest(unittest.TestCase):
    def setUp(self):
        clear()
        valid_pair()

    def test_markdown_subset(self):
        out = build_graph.md_to_html("## Result\n\n- one\n- two\n\n`code` and **bold**")
        self.assertIn("<h4>Result</h4>", out)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<code>code</code>", out)
        self.assertIn("<strong>bold</strong>", out)

    def test_markdown_escapes_html(self):
        self.assertIn("&lt;script&gt;", build_graph.md_to_html("<script>alert(1)</script>"))

    def test_commit_url_from_ssh_and_https(self):
        self.assertEqual(
            build_graph.commit_url("git@github.com:jlaw9/prekd.git", "a3f9c21"),
            "https://github.com/jlaw9/prekd/commit/a3f9c21")
        self.assertEqual(
            build_graph.commit_url("https://github.nlr.gov/jlaw/prekd.git", "a3f9c21"),
            "https://github.nlr.gov/jlaw/prekd/commit/a3f9c21")

    def test_layout_places_every_node_in_a_lane(self):
        nodes, _ = lib.load_nodes()
        positions, lanes, ticks, width, height = build_graph.compute_layout(nodes)
        self.assertEqual(set(positions), set(nodes))
        self.assertEqual({lane["project"] for lane in lanes}, {"prekd"})
        self.assertGreater(height, 0)

    def test_layout_separates_same_day_nodes(self):
        for index in range(4):
            node_id = f"2026-08-02-prekd-same-{index}"
            write(f"{node_id}.md", node_text(node_id))
        nodes, _ = lib.load_nodes()
        positions, _, _, _, _ = build_graph.compute_layout(nodes)
        same_day = [positions[n] for n in nodes if "same-" in n]
        self.assertEqual(len({round(y) for _, y in same_day}), len(same_day))

    def test_build_writes_a_self_contained_page(self):
        self.assertEqual(build_graph.main(), 0)
        page = (FIXTURE / "build" / "graph.html").read_text(encoding="utf-8")
        self.assertIn(CHILD_ID, page)
        self.assertNotIn("/*__CAIRN_DATA__*/null", page)
        for forbidden in ("http://", "cdn.", "<script src"):
            self.assertNotIn(forbidden, page, f"page reaches out for {forbidden}")

        markdown = (FIXTURE / "build" / "graph.md").read_text(encoding="utf-8")
        self.assertIn("```mermaid", markdown)
        self.assertIn(CHILD_ID, markdown)

    def test_empty_graph_still_builds(self):
        clear()
        self.assertEqual(build_graph.main(), 0)
        self.assertIn("No nodes yet", (FIXTURE / "build" / "graph.md").read_text(encoding="utf-8"))


class FlowScalarRoundTrip(unittest.TestCase):
    """Frontmatter is the database. A value that does not survive a write/read
    cycle is silent data loss, and history notes are exactly where it bit:
    "past 1,000 systems" became `note: past 1` plus a junk key `000 systems`.
    """

    HOSTILE = [
        "past 1,000 systems",
        "lattice-matched Gln spacing, v1 vs clustered anagram",
        "a note with {braces} and [brackets]",
        "trailing # not a comment",
        "ratio 3:1 and a colon: here",
    ]

    def test_history_notes_survive_a_round_trip(self):
        clear()
        for index, note in enumerate(self.HOSTILE):
            node_id = f"2026-04-{index + 10:02d}-prekd-hostile"
            node = lib.Node(
                path=lib.node_dir() / f"{node_id}.md",
                meta={
                    "id": node_id, "type": "experiment", "title": "hostile note",
                    "project": "prekd", "status": "running",
                    "created": dt.date(2026, 4, index + 10), "updated": dt.date(2026, 4, index + 10),
                    "parents": [],
                    "history": [{"date": dt.date(2026, 4, index + 10), "status": "running", "note": note}],
                },
                body="## Claim\n\nhostile\n",
            )
            node.write()
            reread = lib.parse_file(node.path)
            self.assertEqual(reread.history[0]["note"], note, f"note mangled: {note!r}")
            self.assertEqual(set(reread.history[0]), {"date", "status", "note"})

    def test_a_mangled_history_entry_is_an_error(self):
        clear()
        write("2026-04-20-prekd-mangled.md", node_text("2026-04-20-prekd-mangled", created="2026-04-20").replace(
            "note: created}", "note: created, 000 systems}"))
        self.assertTrue(
            any("unexpected key" in i.message for i in lib.validate() if i.level == "error"),
            error_text(),
        )


class Relations(unittest.TestCase):
    """Typed relations: the meaning layer over the untyped `parents` DAG."""

    def two_nodes(self, relates):
        clear()
        write("2026-04-10-prekd-first.md", node_text("2026-04-10-prekd-first", created="2026-04-10"))
        text = node_text("2026-04-20-prekd-second", created="2026-04-20").replace(
            "parents: []", "parents: []\nrelates:\n" + relates)
        write("2026-04-20-prekd-second.md", text)

    def test_a_good_relation_validates(self):
        self.two_nodes("  - {to: 2026-04-10-prekd-first, type: contradicts, note: opposite sign}")
        self.assertEqual([i for i in lib.validate() if i.level == "error"], [], error_text())

    def test_unknown_relation_type_rejected(self):
        self.two_nodes("  - {to: 2026-04-10-prekd-first, type: vibes, note: hmm}")
        self.assertTrue(any("unknown relation" in i.message for i in lib.validate()), error_text())

    def test_dangling_relation_rejected(self):
        self.two_nodes("  - {to: 2026-01-01-prekd-ghost, type: supports, note: nope}")
        self.assertTrue(any("dangling target" in i.message for i in lib.validate()), error_text())

    def test_self_relation_rejected(self):
        self.two_nodes("  - {to: 2026-04-20-prekd-second, type: supports, note: circular}")
        self.assertTrue(any("points at itself" in i.message for i in lib.validate()), error_text())

    def test_missing_note_warns_but_does_not_block(self):
        self.two_nodes("  - {to: 2026-04-10-prekd-first, type: supports}")
        issues = lib.validate()
        self.assertEqual([i for i in issues if i.level == "error"], [], error_text())
        self.assertTrue(any("no note explaining why" in i.message for i in issues))

    def test_mutual_contradiction_is_allowed(self):
        # Unlike parents, relations are not cycle-checked: two results really can
        # contradict each other, and that is a fact rather than a defect.
        clear()
        a, b = "2026-04-10-prekd-first", "2026-04-20-prekd-second"
        for one, other in ((a, b), (b, a)):
            write(f"{one}.md", node_text(one, created=one[:10]).replace(
                "parents: []",
                f"parents: []\nrelates:\n  - {{to: {other}, type: contradicts, note: mutual}}"))
        self.assertEqual([i for i in lib.validate() if i.level == "error"], [], error_text())

    def test_backlinks_phrase_the_relation_from_the_target_side(self):
        self.two_nodes("  - {to: 2026-04-10-prekd-first, type: supersedes, note: replaced it}")
        nodes, _ = lib.load_nodes()
        inbound = lib.relation_backlinks(nodes)
        self.assertEqual(inbound["2026-04-10-prekd-first"][0]["label"], "superseded by")

    def test_cli_parses_type_id_why(self):
        entry = new_node.parse_relation("contradicts:2026-04-10-prekd-first:opposite sign")
        self.assertEqual(entry, {"to": "2026-04-10-prekd-first", "type": "contradicts",
                                 "note": "opposite sign"})


class FindPython(unittest.TestCase):
    """scripts/find_python.sh must never hand back an unusable interpreter.

    Handing one back is worse than finding nothing: the pre-commit hook runs
    whatever this prints, and a Python too old to parse lib.py fails with a
    SyntaxError that the hook reports as schema drift.
    """

    SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "find_python.sh"

    def run_finder(self, **env):
        import subprocess
        return subprocess.run(
            ["sh", str(self.SCRIPT)], capture_output=True, text=True,
            env=dict(os.environ, **env),
        )

    def test_whatever_it_finds_can_actually_run_cairn(self):
        import subprocess
        found = self.run_finder()
        if found.returncode != 0:
            self.skipTest("no usable interpreter on this machine")
        probe = subprocess.run(
            [found.stdout.strip(), "-c",
             "import sys, yaml; assert sys.version_info >= (3, 7)"],
            capture_output=True,
        )
        self.assertEqual(probe.returncode, 0, f"{found.stdout.strip()} cannot run Cairn")

    def test_an_unusable_override_fails_loudly_rather_than_falling_back(self):
        # Silently substituting a different interpreter than the one asked for
        # would make a wrong CAIRN_PYTHON impossible to debug.
        result = self.run_finder(CAIRN_PYTHON="/nonexistent/python")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("CAIRN_PYTHON", result.stderr)


if __name__ == "__main__":
    try:
        result = unittest.main(exit=False, verbosity=2).result
    finally:
        shutil.rmtree(FIXTURE, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
