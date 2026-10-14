#!/usr/bin/env python3
"""Tests for the Cairn schema, validator and renderer.

Runs against a throwaway fixture graph, never the real one. Every check here
corresponds to a way the graph could silently rot.

    python3 tests/test_cairn.py
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

FIXTURE = Path(tempfile.mkdtemp(prefix="cairn-test-"))
for sub in ("nodes", "papers", "datasets", "build"):
    (FIXTURE / sub).mkdir(parents=True)

# lib reads CAIRN_ROOT at import time, so this has to happen before the import.
os.environ["CAIRN_ROOT"] = str(FIXTURE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import lib  # noqa: E402
import build_graph  # noqa: E402
import export  # noqa: E402
import export_example  # noqa: E402
import new_node  # noqa: E402


def write(name: str, text: str, folder: str = "nodes") -> Path:
    path = FIXTURE / folder / name
    path.write_text(text.lstrip("\n"), encoding="utf-8")
    return path


def clear() -> None:
    for folder in ("nodes", "papers", "datasets"):
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

    def test_docs_schema_table_matches_lib_types(self):
        """docs/schema.md says lib.TYPES is authoritative and to change both.

        Nothing enforced that, so the two could drift silently — which is the
        exact failure mode the validator exists to prevent, one level up. The
        docs are what a human reads before hand-writing a status.
        """
        table = (Path(__file__).resolve().parent.parent / "docs" / "schema.md").read_text()
        documented = {}
        for row in re.finditer(r"^\|\s*`(\w+)`\s*\|([^|]*)\|([^|]*)\|", table, re.M):
            name, statuses, terminal = row.groups()
            if name not in lib.TYPES:
                continue
            documented[name] = (
                re.findall(r"`(\w+)`", statuses),
                {t.strip() for t in terminal.split(",") if t.strip()},
            )

        self.assertEqual(set(documented), set(lib.TYPES),
                         "docs/schema.md's type table does not cover lib.TYPES")
        for name, (statuses, terminal) in documented.items():
            spec = lib.TYPES[name]
            self.assertEqual(statuses, spec.statuses, f"{name}: statuses differ from docs")
            self.assertEqual(terminal, spec.terminal, f"{name}: terminal set differs from docs")


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
        self.assertFalse(nodes[CHILD_ID].is_terminal)

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

    def test_id_never_ends_on_a_function_word(self):
        """A trim that lands on "than" reads as though the id were cut off.

        Ids are permanent, so this is not cosmetic: the real one that shipped was
        `cairn-log-restart-is-cheaper-than`, and it could only be fixed because it
        had not been committed yet.
        """
        slug = new_node.shorten(
            new_node.slugify("cairn-Log-and-restart is cheaper than continuing at high context")
        )
        self.assertEqual(slug, "cairn-log-restart-is-cheaper")

    def test_no_dangling_word_survives_any_trim_point(self):
        # Sweep every prefix of a long title so the check doesn't depend on where
        # SLUG_MAX happens to fall today.
        words = "does the model that was trained on it also do what we should not".split()
        for n in range(1, len(words) + 1):
            slug = new_node.shorten(new_node.slugify("proj-" + " ".join(words[:n])))
            tail = slug.split("-")[-1]
            self.assertNotIn(tail, new_node.DANGLING, f"{slug!r} ends on a function word")

    def test_a_title_of_pure_function_words_still_yields_the_project_key(self):
        self.assertEqual(new_node.shorten(new_node.slugify("proj-is it that")), "proj")

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


class ProjectKeyGuard(unittest.TestCase):
    """`project:` is the one field whose typo validates cleanly.

    A mistyped id or status is rejected, but `photpoly` for `photopoly` passes
    every check and silently splits one project into two lanes — after which a
    missing node no longer means "not tried".
    """

    def setUp(self):
        clear()
        valid_pair()          # both nodes are project `prekd`

    def build_with(self, project, new_project=False):
        import argparse
        return new_node.build(argparse.Namespace(
            type="experiment", title="A probe", project=project, status=None,
            note="", date="2026-08-03", slug=None, parent=[], ref=[], repo=None,
            commit=None, host=None, artifact=[], origin=None, venue=None,
            url=None, due=None, source=None, new_project=new_project))

    def test_a_known_project_is_accepted(self):
        self.assertEqual(self.build_with("prekd").project, "prekd")

    def test_an_unknown_project_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.build_with("prekdd")
        self.assertIn("not a project in this graph", str(caught.exception))

    def test_the_refusal_suggests_the_key_that_was_meant(self):
        with self.assertRaises(SystemExit) as caught:
            self.build_with("prekdd")
        self.assertIn("prekd", str(caught.exception).split("did you mean")[1])

    def test_a_distant_key_gets_no_misleading_suggestion(self):
        # polyid/polymd differ by one character and are different projects, so a
        # suggestion has to be precise or it trains you to ignore it.
        with self.assertRaises(SystemExit) as caught:
            self.build_with("zzz")
        self.assertNotIn("did you mean", str(caught.exception))

    def test_new_project_flag_allows_it(self):
        self.assertEqual(self.build_with("brandnew", new_project=True).project, "brandnew")

    def test_the_first_node_in_an_empty_graph_needs_no_flag(self):
        clear()
        self.assertEqual(self.build_with("anything").project, "anything")


class PlannedExperiments(unittest.TestCase):
    """README section B says to open the experiment before the job is queued."""

    def setUp(self):
        clear()

    def test_planned_is_valid_and_not_terminal(self):
        node_id = "2026-08-03-prekd-preregistered"
        write(f"{node_id}.md", node_text(node_id, status="planned"))
        self.assertEqual(errors(), [], error_text())
        self.assertFalse(lib.parse_file(lib.node_dir() / f"{node_id}.md").is_terminal)

    def test_planned_transitions_to_running_keeping_both_in_history(self):
        node_id = "2026-08-03-prekd-preregistered"
        write(f"{node_id}.md", node_text(node_id, status="planned"))
        node = lib.parse_file(lib.node_dir() / f"{node_id}.md")
        node.set_status("running", "queued on kestrel", dt.date(2026, 8, 4))
        node.write()
        again = lib.parse_file(node.path)
        self.assertEqual(again.status, "running")
        self.assertEqual([h["status"] for h in again.history], ["planned", "running"])
        self.assertEqual(errors(), [], error_text())

    def test_the_default_status_is_still_running(self):
        # Adding `planned` to the front of the list must not change what /log
        # creates when it writes up work that already happened.
        self.assertEqual(lib.TYPES["experiment"].default_status, "running")
        self.assertEqual(lib.TYPES["experiment"].statuses[0], "planned")

    def test_every_type_has_a_default_in_its_own_status_list(self):
        for name, spec in lib.TYPES.items():
            self.assertIn(spec.default_status, spec.statuses, name)


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

    def test_wrapped_ordered_list_is_one_ol(self):
        out = build_graph.md_to_html("1. first line\n   wrapped on\n2. second\n   also wrapped\n3. third")
        self.assertEqual(out.count("<ol>"), 1)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("first line wrapped on", out)
        self.assertNotIn("<p>", out)

    def test_nested_list_stays_inside_its_item(self):
        out = build_graph.md_to_html("- a\n  - inner\n- b")
        self.assertEqual(out.count("<ul>"), 2)
        self.assertEqual(out.count("<li>"), 3)
        self.assertEqual(out.count("</ul>"), 2)

    def test_blank_line_between_numbered_items_keeps_one_list(self):
        out = build_graph.md_to_html("1. a\n\n2. b")
        self.assertEqual(out.count("<ol>"), 1)

    def test_pipe_table(self):
        out = build_graph.md_to_html("| a | b |\n|---|:-:|\n| 1 | `x` |\n| 2 | 3 |\n\nafter")
        self.assertIn('<thead><tr><th>a</th><th style="text-align:center">b</th></tr></thead>', out)
        self.assertEqual(out.count("<tr>"), 3)
        self.assertIn("<code>x</code>", out)
        self.assertIn("<p>after</p>", out)
        self.assertNotIn("|", out)

    def test_pipes_without_a_separator_row_are_a_paragraph(self):
        self.assertIn("<p>", build_graph.md_to_html("| a | b |\n| 1 | 2 |"))

    def test_empty_section_heading_is_omitted_but_filled_one_stays(self):
        body = "## Claim\n\nreal text\n\n## What I did\n\n## Result\n\n## Next\n\n- go\n\n## Open questions\n"
        out = build_graph.md_to_html(body)
        self.assertIn("<h4>Claim</h4>", out)
        self.assertIn("<h4>Next</h4>", out)
        self.assertNotIn("What I did", out)
        self.assertNotIn("Result", out)
        self.assertNotIn("Open questions", out)

    def test_heading_with_only_a_subsection_is_not_empty(self):
        out = build_graph.md_to_html("## A\n\n### B\n\ntext")
        self.assertIn("<h4>A</h4>", out)

    def test_empty_heading_omission_leaves_notes_parsing_alone(self):
        # Render-time only: lib reads the stored body, which this never touches.
        body = "## Result\n\n## Notes\n\n- **2026-08-26** (jlaw) hi\n"
        self.assertIn("<h4>Notes</h4>", build_graph.md_to_html(body))
        self.assertIn("hi", lib.body_section(body, [lib.NOTES_HEADING]))

    def test_markdown_escapes_html(self):
        self.assertIn("&lt;script&gt;", build_graph.md_to_html("<script>alert(1)</script>"))

    def test_wikilink_becomes_a_goto_link_titled_by_its_target(self):
        titles = {CHILD_ID: "The child node"}
        out = build_graph.md_to_html(f"See [[{CHILD_ID}]] for detail.", titles)
        self.assertIn(f'data-goto="{CHILD_ID}"', out)
        self.assertIn("The child node", out)
        self.assertNotIn("[[", out)

    def test_wikilink_to_a_missing_node_renders_visibly_broken(self):
        out = build_graph.md_to_html("See [[2026-01-01-nope-gone]] for detail.", {})
        self.assertIn("lnk broken", out)
        self.assertNotIn("data-goto", out)
        self.assertIn("2026-01-01-nope-gone", out)

    def test_double_brackets_that_are_not_a_node_id_are_left_alone(self):
        # Prose in double brackets is not a link, so the id shape is required.
        out = build_graph.md_to_html("A [[note to self]] here.", {})
        self.assertIn("[[note to self]]", out)

    def test_wikilink_target_titles_are_escaped(self):
        out = build_graph.md_to_html(f"[[{CHILD_ID}]]", {CHILD_ID: "<script>x</script>"})
        self.assertNotIn("<script>", out)

    def test_validate_warns_on_a_wikilink_to_a_missing_node(self):
        node_id = "2026-08-02-prekd-dangling-link"
        write(f"{node_id}.md", node_text(node_id) + "\nSee [[2026-01-01-prekd-gone]].\n")
        messages = [str(i) for i in lib.validate() if "body links" in str(i)]
        self.assertTrue(any("2026-01-01-prekd-gone" in m for m in messages), messages)
        self.assertTrue(all(i.level == "warn" for i in lib.validate()
                            if "body links" in str(i)))

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

    def test_the_payload_carries_each_types_own_fields(self):
        """The edit form renders inputs from this rather than from a second copy
        of the schema, so it has to be lib.TYPES exactly."""
        nodes, _ = lib.load_nodes()
        payload = build_graph.build_payload(nodes, {}, {}, *build_graph.compute_layout(nodes))
        fields = payload["fieldsByType"]
        self.assertEqual(set(fields), set(lib.TYPES))
        for name, spec in lib.TYPES.items():
            self.assertEqual(fields[name], {"required": spec.required,
                                            "optional": spec.optional})
        self.assertIn("artifacts", fields["experiment"]["optional"])
        self.assertIn("due", fields["task"]["optional"])

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


class PaperIngest(unittest.TestCase):
    """add_paper.py's offline parts. Network calls are not exercised here."""

    def setUp(self):
        clear()
        import add_paper
        self.add_paper = add_paper

    def test_doi_normalisation_accepts_the_forms_people_paste(self):
        for raw in ("10.1038/s41586-021-03819-2",
                    "https://doi.org/10.1038/s41586-021-03819-2",
                    "doi:10.1038/s41586-021-03819-2",
                    "  10.1038/s41586-021-03819-2 "):
            self.assertEqual(self.add_paper.normalise_doi(raw), "10.1038/s41586-021-03819-2")

    def test_bibkey_matches_better_bibtex_default_pattern(self):
        # auth + year + first non-stopword title word, so keys generated here
        # collide with what Zotero would have produced rather than diverging.
        message = {
            "author": [{"given": "John", "family": "Jumper"}],
            "issued": {"date-parts": [[2021, 7, 15]]},
            "title": ["Highly accurate protein structure prediction with AlphaFold"],
        }
        self.assertEqual(self.add_paper.derive_bibkey(message), "jumper2021highly")

    def test_bibkey_survives_missing_metadata(self):
        self.assertEqual(self.add_paper.derive_bibkey({}), "anonnd")

    def test_jats_markup_is_stripped_from_titles(self):
        # Polymer titles are full of T<sub>g</sub> and <i>cis</i>-, in raw and
        # entity-escaped form. Both have to go.
        self.assertEqual(
            self.add_paper.strip_markup("High-<i>T</i><sub>g</sub> Polymers"),
            "High-Tg Polymers")
        self.assertEqual(
            self.add_paper.strip_markup("Poly &lt;i&gt;cis&lt;/i&gt;-1,4-diene"),
            "Poly cis-1,4-diene")

    def test_bibkey_ignores_markup_tags_as_title_words(self):
        # Without stripping, the first "word" of this title is `i`, and the key
        # becomes a silent mismatch with the Zotero library.
        message = {
            "author": [{"given": "H", "family": "Lu"}],
            "issued": {"date-parts": [[2001]]},
            "title": ["<i>Exploiting</i> the Heterogeneity of Photopolymers"],
        }
        self.assertEqual(self.add_paper.derive_bibkey(message), "lu2001exploiting")

    def test_bibtex_title_is_cleaned_without_touching_the_rest(self):
        # The tags would otherwise reach references.bib and compile into the
        # manuscript as a broken citation. Everything outside title={} must be
        # left alone — an unescaped & there would break the compile instead.
        entry = r"@article{k, title={A <sub>x</sub> B}, journal={J of A \& B}, pages={1--2} }"
        out = self.add_paper.clean_bibtex_title(entry)
        self.assertIn("title={A x B}", out)
        self.assertIn(r"J of A \& B", out)
        self.assertIn("pages={1--2}", out)

    def test_bibtex_without_a_title_field_is_returned_unchanged(self):
        entry = "@misc{k, note={x} }"
        self.assertEqual(self.add_paper.clean_bibtex_title(entry), entry)

    def test_bibtex_is_rekeyed_to_match_the_registry_page(self):
        entry = "@article{Jumper_2021, title={A}, year={2021} }"
        out = re.sub(r"^@(\w+)\s*\{\s*[^,]*,", r"@\1{jumper2021highly,", entry, count=1)
        self.assertIn("@article{jumper2021highly,", out)

    def test_append_bib_is_idempotent(self):
        bib = FIXTURE / "references.bib"
        entry = "@article{jumper2021highly, title={A} }"
        self.assertEqual(self.add_paper.append_bib(bib, entry, "jumper2021highly"), "appended")
        self.assertEqual(self.add_paper.append_bib(bib, entry, "jumper2021highly"), "already present")
        self.assertEqual(bib.read_text().count("jumper2021highly"), 1)

    def test_paper_page_leads_with_the_doi(self):
        # A paper has no `id`; the DOI is its identity and must sort first.
        meta = {"title": "T", "venue": "V", "doi": "10.1234/abc",
                "authors": ["A B"], "year": 2024, "bibkey": "b2024t"}
        first = lib.dump_frontmatter(meta).splitlines()[0]
        self.assertTrue(first.startswith("doi:"), first)

    def test_registry_page_round_trips_and_backlinks(self):
        doi = "10.1234/abc"
        path = lib.paper_dir() / f"{lib.slug_doi(doi)}.md"
        lib.Node(path=path, meta={"doi": doi, "title": "T", "bibkey": "b2024t"},
                 body="why it matters").write()
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, extra=f"refs: [{doi}]\n"))

        papers, errors = lib.load_papers()
        self.assertEqual(errors, [])
        self.assertEqual(papers[doi].meta["bibkey"], "b2024t")
        self.assertEqual(lib.paper_backlinks(lib.load_nodes()[0])[doi], [CHILD_ID])
        # A ref with a registry page must not warn about thin backlinks.
        self.assertFalse(any("has no page in papers/" in i.message for i in lib.validate()))


class DatasetRegistryTest(unittest.TestCase):
    """datasets/ is the papers/ pattern for input data: a keyed lookup table
    off the DAG, joined from nodes by `data: [key]`, backlinked by the renderer.
    The load-bearing promise is that the join never silently breaks."""

    KEY = "dp18-250912"

    def setUp(self):
        clear()
        valid_pair()

    def dataset(self, key=None, **fields):
        key = key or self.KEY
        meta = {"key": key, "title": f"Dataset {key}", **fields}
        path = lib.dataset_dir() / f"{key}.md"
        lib.Node(path=path, meta=meta, body="provenance").write()
        return path

    def test_round_trip_and_backlinks(self):
        self.dataset(sha256="a" * 64, tier="review")
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, extra=f"data: [{self.KEY}]\n"))
        datasets, errors = lib.load_datasets()
        self.assertEqual(errors, [])
        self.assertEqual(datasets[self.KEY].meta["tier"], "review")
        self.assertEqual(lib.dataset_backlinks(lib.load_nodes()[0])[self.KEY], [CHILD_ID])
        self.assertFalse(any("has no page in datasets/" in i.message for i in lib.validate()))

    def test_data_key_with_no_page_warns_but_does_not_block(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, extra="data: [nowhere-250101]\n"))
        issues = lib.validate()
        self.assertFalse([i for i in issues if i.level == "error"])
        self.assertTrue(any("has no page in datasets/" in i.message for i in issues))

    def test_malformed_data_key_is_an_error(self):
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, extra='data: ["DP18 250912"]\n'))
        self.assertIn("is not a dataset key", error_text())

    def test_key_must_match_filename_stem(self):
        # Written under one name, keyed as another — the join would resolve to
        # a page git blame attributes to a different dataset.
        path = lib.dataset_dir() / "wrong-name.md"
        lib.Node(path=path, meta={"key": self.KEY, "title": "T"}, body="x").write()
        _, errors = lib.load_datasets()
        self.assertTrue(any("does not match filename stem" in e for e in errors))

    def test_page_without_a_key_is_an_error(self):
        (lib.dataset_dir() / "orphan.md").write_text("---\ntitle: T\n---\nx\n", encoding="utf-8")
        _, errors = lib.load_datasets()
        self.assertTrue(any("no 'key:' field" in e for e in errors))

    def test_bad_sha256_and_tier_warn(self):
        self.dataset(sha256="deadbeef", tier="secret")
        messages = [i.message for i in lib.validate() if i.level == "warn"]
        self.assertTrue(any("not 64 hex chars" in m for m in messages))
        self.assertTrue(any("tier 'secret'" in m for m in messages))

    def test_dangling_generated_by_and_supersedes_warn(self):
        self.dataset(generated_by="2026-01-01-prekd-nonexistent", supersedes="dp18-250801")
        messages = [i.message for i in lib.validate() if i.level == "warn"]
        self.assertTrue(any("generated_by" in m for m in messages))
        self.assertTrue(any("supersedes 'dp18-250801'" in m for m in messages))

    def test_dataset_page_leads_with_the_key(self):
        # A dataset has no `id`; the key is its identity and must sort first.
        meta = {"title": "T", "sha256": "a" * 64, "key": self.KEY, "host": "kestrel"}
        first = lib.dump_frontmatter(meta).splitlines()[0]
        self.assertTrue(first.startswith("key:"), first)

    def test_data_field_is_not_an_unknown_field(self):
        self.dataset()
        write(f"{CHILD_ID}.md", node_text(CHILD_ID, extra=f"data: [{self.KEY}]\n"))
        self.assertFalse(any("unknown field 'data'" in i.message for i in lib.validate()))

    def test_new_node_accepts_data_and_update_appends_it(self):
        self.dataset()
        import argparse
        ns = argparse.Namespace(
            type="experiment", title="Train on DP-18", project="prekd",
            status="", note="", date="2026-09-02", slug="prekd-dp18-train",
            parent=[], relate=[], ref=[], data=[self.KEY], repo=None,
            commit=None, host=None, artifact=[], origin=None, venue=None,
            url=None, due=None, source=None, new_project=False,
        )
        node = new_node.build(ns)
        self.assertEqual(node.meta["data"], [self.KEY])
        node.write()
        ns2 = argparse.Namespace(
            update=node.id, status="", note="", date="2026-09-02",
            relate=[], data=["dp18-250913"], commit=None, host=None,
            url=None, due=None, artifact=[],
        )
        updated = new_node.update(ns2)
        self.assertEqual(updated.data, [self.KEY, "dp18-250913"])
        # Appending a dataset is not a state transition: history untouched.
        self.assertEqual(len(updated.history), 1)


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

    def test_bare_python_and_conda_base_are_candidates(self):
        # `python3` is Homebrew's on a conda-managed mac while the interpreter
        # holding PyYAML is at `python` or <conda base>/bin/python. Probing only
        # python3* reported "no usable Python" on a machine that had one.
        text = self.SCRIPT.read_text()
        self.assertRegex(text, r"(?m)^\s*python3 python\b")
        for base in ("miniforge3/bin/python", "miniconda3/bin/python"):
            self.assertIn(base, text)


class ScriptsUseTheFoundInterpreter(unittest.TestCase):
    """A documented `scripts/*.py` invocation must work wherever `make` does.

    The scripts' shebang is `python3`, which is not necessarily the interpreter
    find_python.sh picks for the Makefile and the hook. Where they differ, every
    command in the README and /log used to fail while `make` succeeded.
    """

    SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

    def setUp(self):
        # These tests validate the shared fixture graph from a subprocess, so
        # whatever the previous test class left in it is what gets validated.
        # Start from a known-good pair rather than inheriting someone's mess.
        clear()
        valid_pair()

    def yaml_less_interpreter(self):
        """A real >= 3.7 interpreter on this machine that cannot import yaml."""
        import subprocess
        for candidate in ("python3.14", "python3.13", "python3.12", "python3.11",
                          "/usr/bin/python3"):
            path = shutil.which(candidate) or (
                candidate if Path(candidate).exists() else None)
            if not path:
                continue
            probe = subprocess.run(
                [path, "-c", "import sys; assert sys.version_info >= (3, 7); import yaml"],
                capture_output=True)
            if probe.returncode != 0:
                usable = subprocess.run(
                    [path, "-c", "import sys; assert sys.version_info >= (3, 7)"],
                    capture_output=True)
                if usable.returncode == 0:
                    return path
        return None

    def test_a_yaml_less_interpreter_relaunches_instead_of_dying(self):
        import subprocess
        found = subprocess.run(
            ["sh", str(self.SCRIPTS / "find_python.sh")],
            capture_output=True, text=True, env=dict(os.environ))
        if found.returncode != 0:
            self.skipTest("no usable interpreter on this machine")
        wrong = self.yaml_less_interpreter()
        if not wrong:
            self.skipTest("every interpreter here has PyYAML; nothing to stand in")

        # Running under the wrong interpreter — exactly what the shebang does on
        # a machine where python3 is not the one with PyYAML — must still work.
        result = subprocess.run(
            [wrong, str(self.SCRIPTS / "validate.py"), "--quiet"],
            capture_output=True, text=True,
            env={k: v for k, v in os.environ.items() if k != "CAIRN_RELAUNCHED"},
        )
        self.assertNotIn("Cairn needs PyYAML", result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_relaunch_cannot_loop(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); import lib" % str(self.SCRIPTS)],
            capture_output=True, text=True,
            env=dict(os.environ, CAIRN_RELAUNCHED="1"),
        )
        # With the guard set it either imports fine (yaml present) or exits
        # once with the message — what it must never do is re-exec forever.
        self.assertIn(result.returncode, (0, 1))


class SyncIssues(unittest.TestCase):
    """Only tasks, one direction, and never a duplicate.

    This writes to a service other people can see, so the parts worth pinning are
    the ones that would be embarrassing rather than merely wrong.
    """

    def setUp(self):
        clear()
        import sync_issues
        self.sync = sync_issues

    def test_enterprise_host_survives_parsing(self):
        """26 of 27 repo-bearing nodes here are on a github.nrel.gov instance, and
        `gh` cannot reach it without the host, so losing it breaks the normal case
        while leaving the github.com case working."""
        cases = {
            "git@github.nrel.gov:jlaw/FY26_mplastic_binders.git": ("github.nrel.gov", "jlaw/FY26_mplastic_binders"),
            "git@github.com:jlaw9/Cairn-graph.git": ("github.com", "jlaw9/Cairn-graph"),
            "https://github.nrel.gov/jlaw/thing": ("github.nrel.gov", "jlaw/thing"),
            "https://github.com/o/n.git": ("github.com", "o/n"),
            "ssh://git@github.nrel.gov/jlaw/thing.git": ("github.nrel.gov", "jlaw/thing"),
            "git@github.com:jlaw9/Cairn-graph": ("github.com", "jlaw9/Cairn-graph"),
        }
        for url, want in cases.items():
            self.assertEqual(self.sync.parse_repo(url), want, url)

    def test_a_host_path_repo_is_never_turned_into_a_github_target(self):
        """The regression that matters, because it proposed a write.

        poly-lit-data records `repo: kestrel:/kfs2/.../poly_image` — a host:/path,
        because that project is not on GitHub at all. The first shorthand fallback
        accepted "any string with a slash and no scheme", so it offered
        `github.com/kestrel:/kfs2/...` as a plan. Guessing a write target is worse
        than refusing one.
        """
        bad = "kestrel:/kfs2/projects/invpoly/jlaw/projects/FY26_poly_lit_data/poly_image"
        self.assertIsNone(self.sync.parse_repo(bad))
        self.assertIsNone(self.sync.SHORTHAND_RE.match(bad))

    def test_shorthand_accepts_owner_name_and_nothing_looser(self):
        self.assertTrue(self.sync.SHORTHAND_RE.match("jlaw9/Cairn-graph"))
        self.assertTrue(self.sync.SHORTHAND_RE.match("o/n.git"))
        for bad in ("a/b/c", "host:/a/b", "a b/c", "/leading", "trailing/", "noslash"):
            self.assertIsNone(self.sync.SHORTHAND_RE.match(bad), bad)

    def test_unparseable_repo_returns_none_rather_than_guessing(self):
        for bad in ("", "not a url", "/local/path", "github.com"):
            self.assertIsNone(self.sync.parse_repo(bad), bad)

    def test_marker_round_trips_so_a_second_run_finds_its_own_issue(self):
        node_id = "2026-08-05-cairn-release-review"
        body = self.sync.MARKER.format(node_id=node_id)
        found = self.sync.MARKER_RE.search(f"blah\n{body}\n")
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), node_id)

    def test_marker_lives_in_the_body_not_the_title(self):
        """Titles get edited by people; idempotency must survive that."""
        self.assertIn("<!--", self.sync.MARKER)

    def test_repo_is_derived_from_the_project_not_stored_per_task(self):
        nodes = {}
        for i, (proj, repo) in enumerate([("p", "git@github.com:o/p.git"),
                                          ("p", "git@github.com:o/p.git"),
                                          ("q", "")]):
            nid = f"2026-06-0{i + 1}-{proj}-n"
            meta = {"id": nid, "type": "experiment", "title": nid, "project": proj,
                    "status": "running", "created": dt.date(2026, 6, 1),
                    "updated": dt.date(2026, 6, 1), "parents": [],
                    "history": [{"date": dt.date(2026, 6, 1), "status": "running", "note": "x"}]}
            if repo:
                meta["repo"] = repo
            nodes[nid] = lib.Node(path=lib.node_dir() / f"{nid}.md", meta=meta, body="")
        derived = self.sync.repo_for_project(nodes)
        self.assertEqual(derived["p"], "git@github.com:o/p.git")
        self.assertNotIn("q", derived)      # skipped, never guessed

    def test_body_states_the_graph_is_authoritative(self):
        """A projection that doesn't say so invites edits in the wrong place."""
        node = lib.Node(
            path=lib.node_dir() / "2026-06-01-p-t.md",
            meta={"id": "2026-06-01-p-t", "type": "task", "title": "t", "project": "p",
                  "status": "todo", "created": dt.date(2026, 6, 1),
                  "updated": dt.date(2026, 6, 1), "due": dt.date(2026, 7, 1), "parents": [],
                  "history": [{"date": dt.date(2026, 6, 1), "status": "todo", "note": "x"}]},
            body="## What\n\ndo it\n")
        body = self.sync.issue_body(node, "o/graph")
        self.assertIn("source of truth", body)
        self.assertIn("2026-07-01", body)          # the due date carries over
        self.assertIn("one-way", body)
        self.assertIn(self.sync.MARKER.format(node_id=node.id), body)


class Authorship(unittest.TestCase):
    """Authorship is derived from git, never stored — design decision 9.

    The case worth pinning is the one invisible on a single-author graph: a node
    drafted but not yet committed has no git author at all, and it must still
    appear on the map, because that is precisely when someone is reviewing it.
    """

    def test_an_uncommitted_node_gets_a_real_bucket_not_an_empty_string(self):
        authors = build_graph.node_authors()
        self.assertEqual(authors.get("2026-01-01-does-not-exist", build_graph.UNCOMMITTED),
                         build_graph.UNCOMMITTED)
        self.assertTrue(build_graph.UNCOMMITTED, "must be truthy or the filter drops the node")

    def test_uncommitted_sorts_last_among_authors(self):
        buckets = sorted({"Zoe Zenith", build_graph.UNCOMMITTED, "Al Aardvark"},
                         key=lambda a: (a == build_graph.UNCOMMITTED, a))
        self.assertEqual(buckets[-1], build_graph.UNCOMMITTED)

    def test_no_author_field_crept_into_the_schema(self):
        """If this ever fails, someone stored what git already knows."""
        self.assertNotIn("author", lib.COMMON_REQUIRED + lib.COMMON_OPTIONAL)
        for name, spec in lib.TYPES.items():
            self.assertNotIn("author", spec.required + spec.optional, name)


class Digest(unittest.TestCase):
    """The digest must not nag, or people learn to skip it.

    Its whole value is that everything it lists is worth reading, so the filters
    that keep things *out* are the part worth testing.
    """

    def setUp(self):
        clear()
        import digest
        self.digest = digest
        self.today = dt.date(2026, 8, 5)

    def make(self, node_id, ntype, status, updated, **meta):
        node = lib.Node(
            path=lib.node_dir() / f"{node_id}.md",
            meta=dict({
                "id": node_id, "type": ntype, "title": node_id, "project": "p",
                "status": status, "created": dt.date(2026, 6, 1), "updated": updated,
                "parents": [],
                "history": [{"date": dt.date(2026, 6, 1), "status": status, "note": "created"}],
            }, **meta),
            body="",
        )
        return node

    def gather(self, *nodes, days=7):
        return self.digest.gather(
            {n.id: n for n in nodes},
            self.today - dt.timedelta(days=days), self.today,
            self.digest.STALE_DAYS, self.digest.HORIZON_DAYS,
        )

    def test_parked_is_never_going_quiet(self):
        """`parked` means "paused, will resume" — nagging about it is a category
        error, and `terminal` alone does not filter it out."""
        parked = self.make("2026-06-01-p-parked", "experiment", "parked", dt.date(2026, 6, 1))
        self.assertEqual(self.gather(parked)["quiet"], [])

    def test_open_direction_is_never_going_quiet(self):
        """A direction is a container that is supposed to sit for months."""
        d = self.make("2026-06-01-p-dir", "direction", "open", dt.date(2026, 6, 1))
        self.assertEqual(self.gather(d)["quiet"], [])

    def test_a_running_experiment_does_go_quiet(self):
        run = self.make("2026-06-01-p-run", "experiment", "running", dt.date(2026, 6, 1))
        quiet = self.gather(run)["quiet"]
        self.assertEqual([n.id for _, n in quiet], ["2026-06-01-p-run"])
        self.assertGreaterEqual(quiet[0][0], self.digest.STALE_DAYS)

    def test_terminal_nodes_are_dropped_entirely(self):
        dead = self.make("2026-06-01-p-dead", "experiment", "dead", dt.date(2026, 6, 1))
        found = self.gather(dead)
        self.assertEqual(found["quiet"], [])
        self.assertEqual(found["deadlines"], [])

    def test_creation_is_reported_once_not_twice(self):
        """A node created in-window is "opened", not also a status change."""
        node = self.make("2026-08-04-p-new", "experiment", "running", dt.date(2026, 8, 4),
                         created=dt.date(2026, 8, 4))
        node.meta["history"] = [{"date": dt.date(2026, 8, 4), "status": "running", "note": "created"}]
        found = self.gather(node)
        self.assertEqual([n.id for n in found["opened"]], ["2026-08-04-p-new"])
        self.assertEqual(found["changed"], [])

    def test_overdue_sorts_before_upcoming_and_undated_sorts_last(self):
        undated = self.make("2026-06-01-p-t1", "task", "todo", dt.date(2026, 6, 1))
        soon = self.make("2026-06-01-p-t2", "task", "todo", dt.date(2026, 6, 1),
                         due=dt.date(2026, 8, 10))
        over = self.make("2026-06-01-p-t3", "task", "todo", dt.date(2026, 6, 1),
                         due=dt.date(2026, 8, 1))
        order = [n.id for _, n in self.gather(over, undated, soon)["deadlines"]]
        self.assertEqual(order, ["2026-06-01-p-t3", "2026-06-01-p-t2", "2026-06-01-p-t1"])

    def test_an_undated_open_task_still_surfaces(self):
        """The validator warns that an undated task never surfaces in a digest.
        That warning is only true if this is where it would have shown up."""
        t = self.make("2026-06-01-p-t", "task", "todo", dt.date(2026, 6, 1))
        self.assertEqual([n.id for _, n in self.gather(t)["deadlines"]], ["2026-06-01-p-t"])

    def test_brief_is_substantially_shorter_and_drops_the_notes(self):
        """A mailed digest competes with the map, so it has to be skimmable."""
        node = self.make("2026-08-01-p-x", "experiment", "dead", dt.date(2026, 8, 1))
        node.meta["history"] = [
            {"date": dt.date(2026, 6, 1), "status": "running", "note": "started"},
            {"date": dt.date(2026, 8, 1), "status": "dead",
             "note": "a long explanatory note that belongs in the graph, not in an inbox"},
        ]
        found = self.gather(node)
        start = self.today - dt.timedelta(days=7)
        full = self.digest.render(found, start, self.today, "", 14, False)
        brief = self.digest.render_brief(found, start, self.today, "")
        self.assertIn("belongs in the graph", full)
        self.assertNotIn("belongs in the graph", brief)
        self.assertIn(node.title, brief)
        self.assertLess(len(brief), len(full))

    def test_empty_window_says_so_rather_than_printing_nothing(self):
        text = self.digest.render(
            {"opened": [], "changed": [], "deadlines": [], "quiet": []},
            self.today - dt.timedelta(days=7), self.today, "", 14, False)
        self.assertIn("Nothing in this window", text)
        # The ambiguity matters more than the emptiness.
        self.assertIn("nothing got logged", text)


class Dispatcher(unittest.TestCase):
    """bin/cairn is the only entry point that survives a hostile `python3`.

    The scripts cannot defend themselves: `from __future__ import annotations` is
    rejected at *compile* time by Python 3.6, so a re-exec shim inside the file —
    or inside a module it imports — is unreachable. Only a non-Python launcher
    can pick the interpreter, which is why this dispatcher exists and why it is
    worth a test that runs it with a sabotaged PATH.
    """

    CAIRN = Path(__file__).resolve().parent.parent / "bin" / "cairn"

    def run_cairn(self, *args, **env):
        import subprocess
        environ = dict(os.environ, **env)
        return subprocess.run(
            [str(self.CAIRN), *args],
            capture_output=True, text=True, env=environ,
        )

    def test_it_is_executable_and_sh(self):
        self.assertTrue(os.access(self.CAIRN, os.X_OK), "bin/cairn must be executable")
        self.assertEqual(self.CAIRN.read_text().splitlines()[0], "#!/bin/sh")

    def test_help_lists_the_commands(self):
        result = self.run_cairn("help")
        self.assertEqual(result.returncode, 0)
        for cmd in ("new_node", "validate", "build", "serve", "add_paper",
                    "mine_sessions", "doctor"):
            self.assertIn(cmd, result.stderr + result.stdout)

    def test_unknown_command_is_an_error_not_a_traceback(self):
        result = self.run_cairn("nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no such command", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_lib_is_not_a_command(self):
        # scripts/lib.py exists but is a module; exposing it would be a footgun.
        self.assertEqual(self.run_cairn("lib").returncode, 2)

    def test_it_runs_under_a_python3_too_old_to_compile_the_scripts(self):
        """The actual regression. A stub `python3` that rejects the source must
        not matter, because sh never asks it anything."""
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "python3"
            stub.write_text("#!/bin/sh\necho 'SyntaxError: bogus' >&2\nexit 1\n")
            stub.chmod(0o755)
            result = self.run_cairn("validate", PATH=f"{tmp}:{os.environ['PATH']}")
        self.assertNotIn("SyntaxError", result.stderr)
        self.assertIn("node(s)", result.stdout + result.stderr)

    def test_bad_cairn_python_does_not_double_report(self):
        result = self.run_cairn("validate", CAIRN_PYTHON="/nonexistent/python")
        self.assertEqual(result.returncode, 1)
        self.assertIn("CAIRN_PYTHON", result.stderr)
        # find_python.sh already explained it; a second vaguer message would
        # send the reader looking for a different problem.
        self.assertNotIn("no usable Python found", result.stderr)


class Standup(unittest.TestCase):
    """The ordering *is* the feature.

    A survey that lists projects chronologically is a digest with extra steps.
    What makes this view worth having is that it ranks by what has lost your
    context, so the ranking is what these tests pin down.
    """

    def setUp(self):
        clear()
        import standup
        self.standup = standup
        self.today = dt.date(2026, 8, 21)

    def make(self, node_id, ntype, status, updated, project="p", body="", **meta):
        return lib.Node(
            path=lib.node_dir() / f"{node_id}.md",
            meta=dict({
                "id": node_id, "type": ntype, "title": node_id, "project": project,
                "status": status, "created": dt.date(2026, 6, 1), "updated": updated,
                "parents": [],
                "history": [{"date": updated, "status": status, "note": "a note"}],
            }, **meta),
            body=body,
        )

    def survey(self, *nodes, quiet_after=21):
        return self.standup.survey(
            {n.id: n for n in nodes}, self.today, quiet_after, 14)

    def rank_of(self, rows, project):
        return next(row["rank"] for row in rows if row["project"] == project)

    def test_last_touched_is_the_newest_node_not_the_oldest(self):
        """`age` is days *since*, so max() reported the stalest node's age as the
        project's recency. A project with a node from today and one from six weeks
        ago read as six weeks cold — on exactly the line someone uses to judge
        whether they have lost that project's context."""
        fresh = self.make("2026-08-21-p-fresh", "experiment", "running", self.today)
        stale = self.make("2026-06-10-p-stale", "experiment", "running",
                          self.today - dt.timedelta(days=60))
        row = self.survey(fresh, stale)[0]
        self.assertEqual(row["since"], 0)

    def test_quiet_project_outranks_a_project_that_moved_today(self):
        """The whole point. Recency is what a digest sorts by and it is exactly
        backwards here: the project you touched this morning is the one whose
        context you still have."""
        fresh = self.make("2026-08-21-a-live", "experiment", "running",
                          self.today, project="fresh")
        stale = self.make("2026-06-01-b-live", "experiment", "running",
                          dt.date(2026, 6, 1), project="stale")
        rows = self.survey(fresh, stale)
        self.assertEqual([row["project"] for row in rows], ["stale", "fresh"])

    def test_overdue_deadline_outranks_everything(self):
        overdue = self.make("2026-08-01-c-task", "task", "todo", dt.date(2026, 8, 1),
                            project="due", due=dt.date(2026, 8, 10))
        stale = self.make("2026-06-01-d-live", "experiment", "running",
                          dt.date(2026, 6, 1), project="stale")
        rows = self.survey(overdue, stale)
        self.assertEqual(rows[0]["project"], "due")
        self.assertEqual(self.rank_of(rows, "due"), 0)

    def test_parked_and_closed_are_not_live_threads(self):
        """Same filter `digest` needs, for the same reason: `parked` is a
        decision already made, so recommending it as work is a category error."""
        parked = self.make("2026-06-01-e-parked", "experiment", "parked",
                           dt.date(2026, 6, 1))
        closed = self.make("2026-06-01-f-dir", "direction", "closed",
                           dt.date(2026, 6, 1))
        rows = self.survey(parked, closed)
        self.assertEqual(rows[0]["live"], [])
        self.assertEqual(self.rank_of(rows, "p"), 3)

    def test_open_direction_is_context_not_work(self):
        """An open direction is a container meant to sit for months. It belongs
        in the briefing and must never be listed as a live thread."""
        direction = self.make("2026-06-01-g-dir", "direction", "open",
                              dt.date(2026, 6, 1))
        rows = self.survey(direction)
        self.assertEqual(rows[0]["live"], [])
        self.assertEqual([n.id for n in rows[0]["threads"]], ["2026-06-01-g-dir"])

    def test_next_section_is_read_back_out_of_the_body(self):
        """`## Next` was always the convention and nothing ever read it. That
        sentence is the cheapest resume there is."""
        node = self.make(
            "2026-06-01-h-live", "experiment", "running", dt.date(2026, 6, 1),
            body="## Claim\n\nSomething.\n\n## Next\n\n- Re-run at 15 seeds\n- Then plot\n")
        self.assertEqual(self.standup.next_action(node),
                         "Re-run at 15 seeds Then plot")

    def test_next_stops_at_the_following_heading(self):
        node = self.make(
            "2026-06-01-i-live", "experiment", "running", dt.date(2026, 6, 1),
            body="## Next\n\nDo the thing.\n\n## Result\n\nDo NOT include this.\n")
        self.assertNotIn("NOT", self.standup.next_action(node))

    def test_a_body_with_no_next_section_is_not_an_error(self):
        node = self.make("2026-06-01-j-live", "experiment", "running",
                         dt.date(2026, 6, 1), body="## Claim\n\nJust a claim.\n")
        self.assertEqual(self.standup.next_action(node), "")

    def test_a_long_next_section_cannot_push_other_threads_off_the_screen(self):
        """One node with a twenty-line plan would otherwise bury every other live
        thread, and then the ranking above buys nothing."""
        lines = self.standup.wrapped("next: ", "word " * 400, "    ", 88)
        self.assertLessEqual(len(lines), 4)
        self.assertTrue(lines[-1].rstrip().endswith("…"))
        self.assertTrue(all(len(line) <= 88 for line in lines), lines)

    def test_a_short_next_section_is_not_mangled(self):
        lines = self.standup.wrapped("next: ", "Re-run at 15 seeds.", "    ", 88)
        self.assertEqual(lines, ["    next: Re-run at 15 seeds."])

    def test_resume_packet_lists_what_was_already_settled(self):
        """The section that prevents re-running a refuted experiment, which is
        the most expensive mistake this view exists to stop."""
        live = self.make("2026-08-01-k-live", "experiment", "running",
                         dt.date(2026, 8, 1))
        dead = self.make("2026-07-01-l-dead", "experiment", "dead",
                         dt.date(2026, 7, 1),
                         history=[{"date": dt.date(2026, 7, 1), "status": "dead",
                                   "note": "solvation model wrong for ionics"}])
        nodes = {n.id: n for n in (live, dead)}
        row = self.survey(live, dead)[0]
        text = self.standup.render_packet(row, nodes, self.today, False, 88)
        self.assertIn("Already settled", text)
        self.assertIn("solvation model wrong for ionics", text)


class Capture(unittest.TestCase):
    """Capture has exactly one failure mode worth engineering against: not
    writing the file. Everything here is a way that could happen quietly."""

    ROOT = Path(__file__).resolve().parent.parent

    def run_capture(self, *args, stdin=None):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "capture", *args],
            capture_output=True, text=True, timeout=60, input=stdin,
            env={**os.environ, "CAIRN_ROOT": str(FIXTURE)},
        )

    def setUp(self):
        (FIXTURE / "inbox").mkdir(exist_ok=True)
        for path in (FIXTURE / "inbox").glob("*.md"):
            path.unlink()

    def files(self):
        return sorted((FIXTURE / "inbox").glob("*.md"))

    def test_it_writes_the_note(self):
        result = self.run_capture("a thought worth keeping")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.files()), 1)
        self.assertIn("a thought worth keeping", self.files()[0].read_text())

    def test_an_unrecognised_project_is_accepted(self):
        """Everywhere else in Cairn a bad project key is refused, because a typo
        silently splits a project in two. The inbox is the one place that trade
        goes the other way: asking at capture time is how capture dies."""
        result = self.run_capture("--project", "not-a-real-project-key", "note")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.files()), 1)

    def test_two_notes_in_the_same_minute_do_not_overwrite(self):
        """A burst of thoughts is the case this command is *for*, so losing the
        first one to a filename collision would be the one unforgivable bug."""
        self.run_capture("first thought")
        self.run_capture("second thought")
        bodies = "".join(p.read_text() for p in self.files())
        self.assertEqual(len(self.files()), 2)
        self.assertIn("first thought", bodies)
        self.assertIn("second thought", bodies)

    def test_stdin_is_captured(self):
        result = self.run_capture("--title", "a traceback", stdin="Traceback: boom\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Traceback: boom", self.files()[0].read_text())

    def test_an_empty_note_is_not_an_error(self):
        """You changed your mind. That is not a failure, and reporting it as one
        trains people to stop running the command."""
        result = self.run_capture(stdin="   \n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.files(), [])

    def test_it_records_where_the_note_was_written(self):
        result = self.run_capture("note")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.files()[0].read_text()
        self.assertIn("captured:", text)
        self.assertIn("cwd:", text)

    def test_it_writes_no_yaml_frontmatter(self):
        """Anything that looks like frontmatter invites a validator, and the
        entire value of inbox/ is that nothing here is ever validated."""
        self.run_capture("note")
        self.assertFalse(self.files()[0].read_text().startswith("---"))

    def test_it_does_not_commit(self):
        """Committing runs the validation hook, which can fail for reasons
        elsewhere in the graph. A capture that can fail is not a capture."""
        source = (self.ROOT / "scripts" / "capture.py").read_text()
        self.assertNotIn('"commit"', source)
        self.assertNotIn("git commit", source)

    def test_it_does_not_import_lib(self):
        """lib exits the process when PyYAML is missing. Capture must survive a
        machine where Cairn is otherwise broken — losing a thought to a
        dependency error is the exact failure this file exists to prevent."""
        source = (self.ROOT / "scripts" / "capture.py").read_text()
        self.assertFalse(re.search(r"^import lib$", source, re.MULTILINE))


class Skills(unittest.TestCase):
    """The skills are Cairn's only reach into other repos. A broken one fails
    silently, in a session that isn't this one."""

    ROOT = Path(__file__).resolve().parent.parent

    def skill_files(self):
        return sorted((self.ROOT / "skills").glob("*/SKILL.md"))

    @staticmethod
    def frontmatter(path):
        import yaml
        match = lib.FRONTMATTER_RE.match(path.read_text())
        return match, (yaml.safe_load(match.group(1)) if match else None) or {}

    def test_every_skill_has_name_and_description_frontmatter(self):
        """The format agents actually read. No frontmatter means the skill is
        invisible rather than broken, which is worse."""
        self.assertTrue(self.skill_files(), "no skills found")
        for path in self.skill_files():
            match, meta = self.frontmatter(path)
            self.assertIsNotNone(match, f"{path.name}: no frontmatter")
            for key in ("name", "description"):
                self.assertTrue(str(meta.get(key, "")).strip(),
                                f"{path.parent.name}: missing '{key}'")

    def test_skill_name_matches_its_directory(self):
        """The directory is the address. A name that disagrees with it makes the
        skill unfindable by the path someone was told to read."""
        for path in self.skill_files():
            _, meta = self.frontmatter(path)
            self.assertEqual(meta["name"], path.parent.name)


class Notes(unittest.TestCase):
    """A note is a body edit that has to stay findable, stay parseable, and stay
    out of the status log. Each test here is one of those three going wrong."""

    def note_node(self, body="## Claim\n\nBody text.\n"):
        text = node_text("2026-08-02-prekd-notes")
        head, _, _ = text.partition("---\n\n## Claim")
        return lib.Node(path=FIXTURE / "nodes" / "2026-08-02-prekd-notes.md",
                        meta={"id": "2026-08-02-prekd-notes", "type": "experiment",
                              "title": "T", "project": "prekd", "status": "running",
                              "created": dt.date(2026, 8, 2),
                              "updated": dt.date(2026, 8, 2),
                              "history": [{"date": dt.date(2026, 8, 2),
                                           "status": "running", "note": "created"}]},
                        body=body)

    def test_a_note_round_trips(self):
        node = self.note_node()
        lib.append_note(node, "the spread looks bimodal", who="jlaw",
                        when=dt.date(2026, 8, 26))
        notes = lib.read_notes(node)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["date"], dt.date(2026, 8, 26))
        self.assertEqual(notes[0]["who"], "jlaw")
        self.assertEqual(notes[0]["text"], "the spread looks bimodal")

    def test_a_note_survives_the_yaml_writer(self):
        """The frontmatter writer once mangled commas; the body must be immune,
        and a note is the first body content written by a tool rather than typed."""
        node = self.note_node()
        lib.append_note(node, "past 1,000 systems: it held", who="jlaw",
                        when=dt.date(2026, 8, 26))
        node.path.write_text(node.to_text(), encoding="utf-8")
        reread = lib.parse_file(node.path)
        self.assertEqual(lib.read_notes(reread)[0]["text"],
                         "past 1,000 systems: it held")

    def test_notes_do_not_touch_status_or_updated(self):
        """Rule 4 ties `status` and `history` together, and `updated` to both. A
        note is not a claim about the state of the work — if it moved `updated`,
        the replay slider would show a status change that never happened."""
        node = self.note_node()
        before = (node.status, node.meta["updated"], len(node.history))
        lib.append_note(node, "a thought", who="jlaw", when=dt.date(2026, 8, 26))
        self.assertEqual((node.status, node.meta["updated"], len(node.history)), before)

    def test_a_note_lands_inside_an_existing_notes_section(self):
        """Appending at the end of the file instead would leave `## Next` below a
        stray second `## Notes`, and split the notes across two places."""
        node = self.note_node(
            "## Claim\n\nBody.\n\n## Notes\n\n- **2026-08-10** (jlaw) earlier\n"
            "\n## Next\n\nRe-run at 15 seeds.\n")
        lib.append_note(node, "later", who="jlaw", when=dt.date(2026, 8, 26))
        self.assertEqual(node.body.count("## Notes"), 1)
        self.assertIn("Re-run at 15 seeds.", node.body)
        self.assertEqual([n["text"] for n in lib.read_notes(node)], ["earlier", "later"])
        self.assertEqual(lib.body_section(node.body, ["next"]), "Re-run at 15 seeds.")

    def test_a_hand_written_continuation_line_is_not_dropped(self):
        """These files are markdown someone will edit by hand. Losing a sentence
        because it lacked a bold date is the wrong trade for a capture tool."""
        node = self.note_node(
            "## Notes\n\n- **2026-08-10** (jlaw) first part\n  and the rest of it\n")
        self.assertEqual(lib.read_notes(node)[0]["text"],
                         "first part and the rest of it")

    def test_a_multiline_note_is_folded_to_one_line(self):
        """A note is one bullet. An embedded newline would end the bullet and turn
        the tail into a sibling of the list, which read back as a second note."""
        node = self.note_node()
        lib.append_note(node, "line one\nline two", who="jlaw",
                        when=dt.date(2026, 8, 26))
        self.assertEqual(len(lib.read_notes(node)), 1)
        self.assertEqual(lib.read_notes(node)[0]["text"], "line one line two")


class OpenNotes(unittest.TestCase):
    """"Unanswered" is derived, not stored: a note dated at or after the node's
    last status change is one no later work responded to."""

    def setUp(self):
        clear()
        import standup
        self.standup = standup

    def node_with(self, note_date, updated="2026-08-10"):
        write("2026-08-02-prekd-n.md", node_text(
            "2026-08-02-prekd-n", updated=updated,
            history=(f"  - {{date: 2026-08-02, status: running, note: created}}\n"
                     f"  - {{date: {updated}, status: running, note: moved}}"))
            + f"\n## Notes\n\n- **{note_date}** (jlaw) look at this\n")
        nodes, _ = lib.load_nodes()
        return nodes["2026-08-02-prekd-n"]

    def test_a_note_after_the_last_change_is_open(self):
        self.assertEqual(len(self.standup.open_notes(self.node_with("2026-08-20"))), 1)

    def test_a_note_the_work_moved_past_is_closed(self):
        """Otherwise every note ever left is reported forever, and the section
        becomes a nag list people learn to skip."""
        self.assertEqual(self.standup.open_notes(self.node_with("2026-08-01")), [])


class Sync(unittest.TestCase):
    """sync's job is to be un-scary: it must never commit a node, and it must not
    fail when the network or the interpreter is missing."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_it_never_commits_a_node(self):
        """Design decision 6. A grep, because this is a property of the whole file
        rather than of one call, and a future `git add -A` would break it."""
        text = (self.ROOT / "scripts" / "sync.py").read_text()
        for line in text.splitlines():
            if 'git("add"' in line or 'git("commit"' in line:
                self.assertTrue(
                    "build" in line or "-m" in line,
                    f"sync must only ever stage build/: {line.strip()}")

    def test_check_exits_zero_on_a_repo_with_nothing_to_say(self):
        """It is wired into a session hook, and a hook that fails gets deleted."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            for sub in ("nodes", "build"):
                (Path(tmp) / sub).mkdir()
            subprocess.run(["git", "init", "-q", tmp], timeout=30)
            result = subprocess.run(
                [str(self.ROOT / "bin" / "cairn"), "sync", "--check"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "CAIRN_ROOT": tmp})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_first_modified_node_is_not_swallowed(self):
        """The regression. `git status --porcelain` puts meaning in a leading
        space, and stripping the whole output shifted the first line's fields by
        one — so exactly one unreviewed node vanished from the report. It only
        showed up as a count that disagreed with `git status`, which is the worst
        way for this command in particular to be wrong."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nodes").mkdir()
            (root / "build").mkdir()
            for name in ("a", "b", "c"):
                (root / "nodes" / f"2026-08-02-prekd-{name}.md").write_text("x\n")
            for cmd in (["init", "-q"], ["add", "-A"],
                        ["-c", "user.email=t@t", "-c", "user.name=t",
                         "commit", "-q", "-m", "seed"]):
                subprocess.run(["git", "-C", str(root), *cmd], timeout=30,
                               capture_output=True)
            for name in ("a", "b", "c"):
                (root / "nodes" / f"2026-08-02-prekd-{name}.md").write_text("edited\n")

            result = subprocess.run(
                [str(self.ROOT / "bin" / "cairn"), "sync", "--check"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "CAIRN_ROOT": str(root)})
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("a", "b", "c"):
                self.assertIn(f"2026-08-02-prekd-{name}.md", result.stdout,
                              f"a modified node is missing from the report:\n{result.stdout}")
            self.assertIn("3 node(s) edited", result.stdout)

    def test_untracked_and_modified_are_reported_separately(self):
        """They mean different things: untracked is almost always an agent draft
        nobody has read, which is the one design decision 6 protects."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nodes").mkdir()
            (root / "build").mkdir()
            (root / "nodes" / "2026-08-02-prekd-old.md").write_text("x\n")
            for cmd in (["init", "-q"], ["add", "-A"],
                        ["-c", "user.email=t@t", "-c", "user.name=t",
                         "commit", "-q", "-m", "seed"]):
                subprocess.run(["git", "-C", str(root), *cmd], timeout=30,
                               capture_output=True)
            (root / "nodes" / "2026-08-02-prekd-old.md").write_text("edited\n")
            (root / "nodes" / "2026-08-03-prekd-new.md").write_text("draft\n")
            result = subprocess.run(
                [str(self.ROOT / "bin" / "cairn"), "sync", "--check"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "CAIRN_ROOT": str(root)})
            self.assertIn("1 node(s) never committed", result.stdout)
            self.assertIn("1 node(s) edited", result.stdout)

    @staticmethod
    def _seed(root):
        """A minimal graph clone with one commit."""
        import subprocess
        (root / "nodes").mkdir()
        (root / "build").mkdir()
        (root / "nodes" / "2026-08-02-prekd-a.md").write_text("x\n")
        for cmd in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "-m", "seed"]):
            subprocess.run(["git", "-C", str(root), *cmd], timeout=30,
                           capture_output=True)

    def _sync(self, root, *args):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "sync", "--check", *args],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CAIRN_ROOT": str(root)})

    def test_a_dead_rebase_is_reported_even_when_quiet(self):
        """The regression this class exists to prevent a second time.

        A `pull --rebase --autostash` whose rebase dies leaves .git/rebase-merge
        holding only an `autostash` file. git then reports "you are currently
        rebasing" forever and refuses every later pull, while the shelved work is
        reachable only by that SHA. sync used to notice -- and log it to a channel
        the session hook does not print, so the hook said "nothing needs you" for
        a week while no pull had succeeded. It has to come out of report(), which
        is what --quiet prints."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            (root / "draft.txt").write_text("work in progress\n")
            subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t",
                            "-c", "user.name=t", "stash", "-q", "-u"],
                           timeout=30, capture_output=True)
            sha = subprocess.run(["git", "-C", str(root), "rev-parse", "refs/stash"],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            (root / ".git" / "rebase-merge").mkdir()
            (root / ".git" / "rebase-merge" / "autostash").write_text(sha + "\n")

            for args in ((), ("--quiet",)):
                result = self._sync(root, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("dead rebase", result.stdout,
                              f"not reported with args={args}:\n{result.stdout}")
                self.assertIn(sha, result.stdout,
                              "the autostash SHA is the only handle on the stranded "
                              f"work and must be printed:\n{result.stdout}")

    def test_a_dead_rebase_without_a_stash_is_still_reported(self):
        """No stranded work, but it still blocks every pull, which is the part
        that goes unnoticed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed(root)
            (root / ".git" / "rebase-merge").mkdir()
            result = self._sync(root, "--quiet")
            self.assertIn("dead rebase", result.stdout)
            self.assertNotIn("autostash", result.stdout)

    def test_a_genuine_rebase_is_not_called_dead(self):
        """The false positive that would matter: a real conflicted rebase is a
        normal state a human is in the middle of, and telling them to rm -rf it
        would destroy the rebase. `head-name` is what git itself needs to
        --continue or --abort, so its presence is the test."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = lambda *a: subprocess.run(["git", "-C", str(root), *a],
                                            timeout=30, capture_output=True)
            self._seed(root)
            # The seed branch is whatever init.defaultBranch says on this machine
            # (master on one, main on another), so read it rather than assume it.
            base = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                                  timeout=30, capture_output=True, text=True).stdout.strip()
            git("-c", "user.email=t@t", "-c", "user.name=t", "checkout", "-q", "-b", "side")
            (root / "nodes" / "2026-08-02-prekd-a.md").write_text("side\n")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "side")
            git("checkout", "-q", base)
            (root / "nodes" / "2026-08-02-prekd-a.md").write_text("base\n")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "base")
            git("checkout", "-q", "side")
            git("-c", "user.email=t@t", "-c", "user.name=t", "rebase", base)

            self.assertTrue((root / ".git" / "rebase-merge" / "head-name").exists(),
                            "test setup failed to produce a conflicted rebase")
            result = self._sync(root, "--quiet")
            self.assertNotIn("dead rebase", result.stdout,
                             f"a genuine rebase was called dead:\n{result.stdout}")

    def test_it_does_not_need_pyyaml(self):
        """capture and sync are the two commands that must work on a machine where
        Cairn is otherwise broken, so neither may import lib."""
        text = (self.ROOT / "scripts" / "sync.py").read_text()
        self.assertNotRegex(text, r"^import lib", )
        self.assertNotIn("\nimport lib", text)


class SessionHook(unittest.TestCase):
    """The hook runs before everything else in every session on the machine. It
    has exactly one hard requirement: never hang, never fail, always valid JSON."""

    ROOT = Path(__file__).resolve().parent.parent

    def run_hook(self, *args, stdin=None):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "session_hook", *args],
            capture_output=True, text=True, timeout=90, input=stdin,
            env={**os.environ, "CAIRN_ROOT": str(FIXTURE)})

    def test_it_emits_valid_json_with_the_right_event_name(self):
        import json
        result = self.run_hook(stdin="")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        if payload:
            self.assertEqual(payload["hookSpecificOutput"]["hookEventName"],
                             "SessionStart")

    def test_it_returns_promptly_with_a_pipe_nobody_writes_to(self):
        """The regression: `isatty()` is false for any pipe, so a bare read()
        waited for an EOF that never came and every session start hung."""
        import subprocess
        result = subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "session_hook", "--dry-run"],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.PIPE, env={**os.environ, "CAIRN_ROOT": str(FIXTURE)})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_end_is_valid_json_too(self):
        import json
        result = self.run_hook("--end", stdin="")
        self.assertEqual(result.returncode, 0, result.stderr)
        json.loads(result.stdout)


class InstallContext(unittest.TestCase):
    """It edits files outside the repo that affect every session on the machine,
    so the tests are all about not destroying what it did not write."""

    ROOT = Path(__file__).resolve().parent.parent

    def run_install(self, home, *args):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "install_context", *args],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDE_CONFIG_DIR": str(home)})

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cairn-cfg-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def test_dry_run_writes_nothing(self):
        result = self.run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertFalse((self.home / "settings.json").exists())
        self.assertFalse((self.home / "CLAUDE.md").exists())

    def test_it_preserves_settings_it_did_not_write(self):
        import json
        (self.home / "settings.json").write_text(json.dumps({
            "model": "opus",
            "permissions": {"allow": ["Bash(ls)"]},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command",
                                                   "command": "echo mine"}]}]},
        }))
        self.run_install(self.home, "--apply")
        after = json.loads((self.home / "settings.json").read_text())
        self.assertEqual(after["model"], "opus")
        self.assertEqual(after["permissions"]["allow"], ["Bash(ls)"])
        self.assertIn("echo mine", json.dumps(after))
        self.assertIn("session_hook", json.dumps(after))

    def test_apply_is_idempotent(self):
        self.run_install(self.home, "--apply")
        first = (self.home / "settings.json").read_text()
        second_run = self.run_install(self.home, "--apply")
        self.assertIn("Nothing to change", second_run.stdout)
        self.assertEqual(first, (self.home / "settings.json").read_text())

    def test_remove_restores_the_original(self):
        import json
        original = {"model": "opus", "hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        (self.home / "settings.json").write_text(json.dumps(original))
        (self.home / "CLAUDE.md").write_text("# Mine\n\nKeep this.\n")
        self.run_install(self.home, "--apply")
        self.run_install(self.home, "--remove", "--apply")
        after = json.loads((self.home / "settings.json").read_text())
        self.assertNotIn("session_hook", json.dumps(after))
        self.assertIn("echo mine", json.dumps(after))
        self.assertEqual((self.home / "CLAUDE.md").read_text(), "# Mine\n\nKeep this.\n")

    def test_a_malformed_settings_file_is_reported_not_overwritten(self):
        """A broken settings.json already disables every setting in it. Silently
        replacing it would discard the lot; naming the file is the useful act."""
        (self.home / "settings.json").write_text("{ not json")
        result = self.run_install(self.home, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not valid JSON", result.stdout)
        self.assertEqual((self.home / "settings.json").read_text(), "{ not json")


class ImportNote(unittest.TestCase):
    """A meeting import writes two files on purpose: the record, and the
    obligation to read it. Collapsing them loses one or the other."""

    ROOT = Path(__file__).resolve().parent.parent

    def run_import(self, *args, stdin=None):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "import_note", *args],
            capture_output=True, text=True, timeout=60, input=stdin,
            env={**os.environ, "CAIRN_ROOT": str(FIXTURE)})

    def setUp(self):
        for sub in ("inbox", "meetings"):
            (FIXTURE / sub).mkdir(exist_ok=True)
            for path in (FIXTURE / sub).glob("*.md"):
                path.unlink()

    def test_a_meeting_writes_the_record_and_queues_a_pointer(self):
        result = self.run_import("--meeting", "--who", "dave", "--date", "2026-08-26",
                                 stdin="* decisions\n- dave owns it\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = FIXTURE / "meetings" / "2026-08-26-dave.md"
        self.assertTrue(record.exists())
        self.assertIn("dave owns it", record.read_text())
        pointers = list((FIXTURE / "inbox").glob("*.md"))
        self.assertEqual(len(pointers), 1)
        self.assertIn("meetings/2026-08-26-dave.md", pointers[0].read_text())

    def test_org_markup_lands_verbatim(self):
        """inbox/ and meetings/ have no schema, so org syntax in a .md file is not
        a problem to be solved. Converting it would lose the author's structure."""
        self.run_import("--meeting", "--who", "d", "--date", "2026-08-26",
                        stdin="** TODO [#A] thing\n:PROPERTIES:\n:ID: x\n:END:\n")
        text = (FIXTURE / "meetings" / "2026-08-26-d.md").read_text()
        self.assertIn("** TODO [#A] thing", text)
        self.assertIn(":PROPERTIES:", text)

    def test_two_meetings_with_one_person_on_one_day_do_not_overwrite(self):
        for body in ("morning notes", "afternoon notes"):
            self.run_import("--meeting", "--who", "dave", "--date", "2026-08-26",
                            stdin=body)
        bodies = "".join(p.read_text() for p in (FIXTURE / "meetings").glob("*.md"))
        self.assertEqual(len(list((FIXTURE / "meetings").glob("*.md"))), 2)
        self.assertIn("morning notes", bodies)
        self.assertIn("afternoon notes", bodies)

    def test_without_meeting_it_goes_to_the_inbox_only(self):
        self.run_import("--project", "polyid", stdin="a scrap of a thought")
        self.assertEqual(len(list((FIXTURE / "meetings").glob("*.md"))), 0)
        self.assertEqual(len(list((FIXTURE / "inbox").glob("*.md"))), 1)


class Report(unittest.TestCase):
    """The report exists to answer "how much do I trust a gap", so the number it
    reports has to mean what it says."""

    def setUp(self):
        clear()
        import report
        self.report = report

    def test_coverage_counts_dead_ends_and_settled_separately(self):
        write("a.md", node_text("2026-08-02-prekd-a", status="dead",
              history="  - {date: 2026-08-02, status: dead, note: refuted}"))
        write("b.md", node_text("2026-08-02-prekd-b", status="worked",
              history="  - {date: 2026-08-02, status: worked, note: held}"))
        write("c.md", node_text("2026-08-02-prekd-c", status="running"))
        nodes, _ = lib.load_nodes()
        row = self.report.coverage(nodes, {})[0]
        self.assertEqual((row["total"], row["settled"], row["dead"]), (3, 2, 1))

    def test_contemporaneous_share_is_none_when_git_knows_nothing(self):
        """The fixture graph has no git history. Reporting 0% there would read as
        "none of this was recorded at the time", which is a different claim from
        "we cannot tell"."""
        write("a.md", node_text("2026-08-02-prekd-a"))
        nodes, _ = lib.load_nodes()
        self.assertIsNone(self.report.coverage(nodes, {})[0]["contemporaneous"])

    def test_lag_splits_written_at_the_time_from_reconstructed(self):
        write("a.md", node_text("2026-08-02-prekd-a"))
        write("b.md", node_text("2026-08-02-prekd-b"))
        nodes, _ = lib.load_nodes()
        lag = {"2026-08-02-prekd-a": 1, "2026-08-02-prekd-b": 40}
        self.assertAlmostEqual(self.report.coverage(nodes, lag)[0]["contemporaneous"], 0.5)

    def test_cross_project_edges_are_the_ones_it_lists(self):
        write("a.md", node_text("2026-08-02-prekd-a"))
        write("b.md", node_text("2026-08-03-polyid-b", project="polyid",
                                created="2026-08-03",
                                parents="[2026-08-02-prekd-a]"))
        write("c.md", node_text("2026-08-04-prekd-c", created="2026-08-04",
                                parents="[2026-08-02-prekd-a]"))
        nodes, _ = lib.load_nodes()
        crossing = self.report.cross_project(nodes)
        self.assertEqual([(n.id, o.id) for n, _, o, _ in crossing],
                         [("2026-08-03-polyid-b", "2026-08-02-prekd-a")])

    def test_it_renders_without_git(self):
        write("a.md", node_text("2026-08-02-prekd-a"))
        nodes, _ = lib.load_nodes()
        text = self.report.build(nodes, "")
        self.assertIn("Coverage, and what a gap means", text)


class Serve(unittest.TestCase):
    """`cairn serve` is a writer, so the tests that matter are the ones about
    what it refuses. The design constraint it must never lose: with the server
    off, `build/graph.html` is exactly the read-only page it always was."""

    @classmethod
    def setUpClass(cls):
        import threading
        global serve
        import serve                                    # noqa: PLW0603
        clear()
        write("2026-08-02-prekd-probe.md",
              node_text("2026-08-02-prekd-probe", project="prekd"))
        build_graph.main()
        cls.httpd = serve.serve(0, quiet=True)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=5)
        cls.httpd.server_close()

    # -- helpers ---------------------------------------------------------

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, headers=None, redirect=True):
        import urllib.error, urllib.request
        opener = urllib.request.build_opener()
        if not redirect:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            opener = urllib.request.build_opener(NoRedirect)
        req = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with opener.open(req, timeout=30) as res:
                return res.status, res.read(), res
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc

    def post(self, payload, headers=None, raw=None):
        import json as _json
        import urllib.error, urllib.request
        head = {"Content-Type": "application/json"}
        head.update(headers or {})
        body = raw if raw is not None else _json.dumps(payload).encode()
        req = urllib.request.Request(self.url("/api/write"), data=body,
                                     headers=head, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as res:
                return res.status, _json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _json.loads(exc.read())

    def node(self, node_id):
        return lib.parse_file(FIXTURE / "nodes" / f"{node_id}.md")

    # -- reads -----------------------------------------------------------

    def test_health_identifies_this_server_and_not_a_static_one(self):
        """The page probes for *this* server. `python -m http.server` over the
        same directory must not make the write controls appear."""
        code, body, _ = self.get("/api/health")
        import json as _json
        self.assertEqual(code, 200)
        info = _json.loads(body)
        self.assertEqual(info["cairn"], "serve")
        self.assertEqual(info["root"], str(lib.REPO_ROOT))
        self.assertEqual(sorted(info["actions"]), ["create", "edit", "note", "status"])

    def test_root_redirects_to_the_map_under_the_graph_root(self):
        """`/build/graph.html`, not `/`: the panel links `../nodes/<id>.md` and
        `../assets/<name>`, which only resolve if the map is one level down."""
        code, _, res = self.get("/", redirect=False)
        self.assertEqual(code, 302)
        self.assertEqual(res.headers["Location"], "/build/graph.html")

    def test_it_serves_the_map_and_a_node_source(self):
        code, body, _ = self.get("/build/graph.html")
        self.assertEqual(code, 200)
        self.assertIn(b"<title>", body)
        code, body, _ = self.get("/nodes/2026-08-02-prekd-probe.md")
        self.assertEqual(code, 200)
        self.assertIn(b"2026-08-02-prekd-probe", body)

    def test_it_serves_nothing_outside_the_allowlist(self):
        for path in ("/scripts/serve.py", "/build/../../etc/passwd",
                     "/Makefile", "/.git/config"):
            code, _, _ = self.get(path)
            self.assertEqual(code, 404, path)

    def test_no_cors_header_is_ever_sent(self):
        """Its absence is the whole reason a page you are visiting cannot read
        this graph off your own machine."""
        _, _, res = self.get("/api/health")
        self.assertIsNone(res.headers.get("Access-Control-Allow-Origin"))

    # -- writes ----------------------------------------------------------

    def test_a_note_lands_in_the_body_through_cairn_note(self):
        code, out = self.post({"action": "note", "id": "2026-08-02-prekd-probe",
                               "text": "the spread looks bimodal"})
        self.assertEqual(code, 200, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["cmd"][:2], ["cairn", "note"])
        notes = lib.read_notes(self.node("2026-08-02-prekd-probe"))
        self.assertIn("the spread looks bimodal", [n["text"] for n in notes])

    def test_a_note_that_starts_with_a_dash_is_text_and_not_a_flag(self):
        code, out = self.post({"action": "note", "id": "2026-08-02-prekd-probe",
                               "text": "-0.4 eV, not +0.4"})
        self.assertEqual(code, 200, out)
        notes = [n["text"] for n in lib.read_notes(self.node("2026-08-02-prekd-probe"))]
        self.assertIn("-0.4 eV, not +0.4", notes)

    def test_a_status_change_moves_history_with_it(self):
        """Node rule 4. The server never writes the field — it shells to
        `new_node --update`, which goes through `lib.Node.set_status`."""
        before = len(self.node("2026-08-02-prekd-probe").history)
        code, out = self.post({"action": "status", "id": "2026-08-02-prekd-probe",
                               "status": "dead", "note": "solvation model wrong"})
        self.assertEqual(code, 200, out)
        node = self.node("2026-08-02-prekd-probe")
        self.assertEqual(node.status, "dead")
        self.assertEqual(len(node.history), before + 1)
        self.assertEqual(node.history[-1]["status"], "dead")
        self.assertEqual(node.history[-1]["note"], "solvation model wrong")

    def test_a_status_the_type_does_not_have_is_refused(self):
        code, out = self.post({"action": "status", "id": "2026-08-02-prekd-probe",
                               "status": "accepted"})
        self.assertEqual(code, 400)
        self.assertIn("experiment status", out["error"])

    def test_create_goes_through_new_node(self):
        code, out = self.post({"action": "create", "type": "direction",
                               "title": "Does the view get used?",
                               "project": "prekd",
                               "parents": ["2026-08-02-prekd-probe"]})
        self.assertEqual(code, 200, out)
        made = list((FIXTURE / "nodes").glob("*-prekd-does-view-get-used.md"))
        self.assertEqual(len(made), 1, made)
        node = lib.parse_file(made[0])
        self.assertEqual(node.type, "direction")
        self.assertEqual(node.parents, ["2026-08-02-prekd-probe"])

    def test_create_writes_the_claim_into_the_body(self):
        """`--body` fills the opening section. The point is pre-registration:
        a claim written before the result, not a title standing in for one."""
        code, out = self.post({"action": "create", "type": "experiment",
                               "title": "Does the tether survive 60 ns?",
                               "project": "prekd", "status": "planned",
                               "body": "It does not; the 20 ns result was unconverged."})
        self.assertEqual(code, 200, out)
        node = lib.parse_file(FIXTURE / "nodes" / f"{out['node']}.md")
        self.assertEqual(node.status, "planned")
        self.assertIn("It does not; the 20 ns result was unconverged.", node.body)
        self.assertIn("## Claim", node.body)

    def test_an_experiment_without_a_claim_is_refused(self):
        before = len(list((FIXTURE / "nodes").glob("*.md")))
        code, out = self.post({"action": "create", "type": "experiment",
                               "title": "A title standing in for a claim",
                               "project": "prekd"})
        self.assertEqual(code, 400)
        self.assertIn("claim", out["error"])
        self.assertEqual(len(list((FIXTURE / "nodes").glob("*.md"))), before)

    def test_a_direction_needs_no_claim(self):
        """Only `experiment` carries the pre-registration argument, so only
        `experiment` is refused without one."""
        code, out = self.post({"action": "create", "type": "direction",
                               "title": "Where does this go next?",
                               "project": "prekd"})
        self.assertEqual(code, 200, out)

    def test_the_result_names_the_node_it_made(self):
        code, out = self.post({"action": "create", "type": "task",
                               "title": "Read the tether paper", "project": "prekd"})
        self.assertEqual(code, 200, out)
        self.assertTrue((FIXTURE / "nodes" / f"{out['node']}.md").exists())
        self.assertFalse(out["committed"], "a new node is a draft, not a claim yet")

    def test_a_new_project_key_that_would_scar_every_id_is_refused(self):
        """The key is the first word of every id in the project, permanently."""
        for bad in ("Poly Sol", "PolySol", "poly sol", "poly/sol", "poly_sol"):
            code, out = self.post({"action": "create", "type": "direction",
                                   "title": "A new direction", "project": bad,
                                   "newProject": True})
            self.assertEqual(code, 400, bad)
            self.assertIn("project key", out["error"])
        # A leading dash is caught earlier, by the guard against a value that
        # argparse would read as a flag. Different message, same refusal.
        code, out = self.post({"action": "create", "type": "direction",
                               "title": "A new direction", "project": "-polysol",
                               "newProject": True})
        self.assertEqual(code, 400)
        self.assertIn("may not start with", out["error"])

    def test_an_unknown_project_is_still_refused_without_the_flag(self):
        """`check_project` is the guard against the one typo that validates
        cleanly. The form must not be a way around it."""
        code, out = self.post({"action": "create", "type": "direction",
                               "title": "A new direction", "project": "prekdd"})
        self.assertEqual(code, 422, out)
        self.assertIn("not a project in this graph", out["out"])

    def test_a_new_project_can_be_started_from_the_map(self):
        code, out = self.post({"action": "create", "type": "direction",
                               "title": "Does the solvent model transfer?",
                               "project": "polysol", "newProject": True})
        self.assertEqual(code, 200, out)
        self.assertEqual(lib.parse_file(FIXTURE / "nodes" / f"{out['node']}.md").project,
                         "polysol")

    def test_claiming_a_project_is_new_when_it_is_not_does_not_disarm_the_guard(self):
        """`--new-project` is passed only where it means something; a key the
        graph already has is not new however the form was filled in."""
        code, out = self.post({"action": "create", "type": "direction",
                               "title": "An existing project, claimed as new",
                               "project": "prekd", "newProject": True})
        self.assertEqual(code, 200, out)
        self.assertNotIn("--new-project", out["cmd"])

    def test_an_unknown_node_is_a_404_not_a_new_file(self):
        code, out = self.post({"action": "note", "id": "2026-08-02-prekd-ghost",
                               "text": "x"})
        self.assertEqual(code, 404)
        self.assertFalse((FIXTURE / "nodes" / "2026-08-02-prekd-ghost.md").exists())

    def test_an_id_that_is_a_path_is_refused_before_it_reaches_a_command(self):
        for bad in ("../../etc/passwd", "2026-08-02-prekd-probe; rm -rf /",
                    "--help", ""):
            code, out = self.post({"action": "note", "id": bad, "text": "x"})
            self.assertIn(code, (400, 404), (bad, out))
            self.assertIn("error", out)

    def test_no_action_deletes_or_writes_raw_frontmatter(self):
        for bad in ("delete", "frontmatter", "yaml", ""):
            code, out = self.post({"action": bad, "id": "2026-08-02-prekd-probe"})
            self.assertEqual(code, 400)
            self.assertIn("action", out["error"])

    def test_an_empty_note_is_refused(self):
        code, out = self.post({"action": "note", "id": "2026-08-02-prekd-probe",
                               "text": "   "})
        self.assertEqual(code, 400)

    def test_an_edit_goes_through_cairn_edit(self):
        """Title, body over stdin, a relation and a parent in one request — and
        `updated`/`history` stay exactly where they were."""
        node_id = "2026-08-03-prekd-editme"
        write(f"{node_id}.md", node_text(node_id, created="2026-08-03"))
        before = self.node(node_id)
        body = ("## Claim\n\nThe tether holds.\n\n## Result\n\n-0.4 eV: it held.\n\n"
                "## Notes\n\n- **2026-08-26** (jlaw) does it track the seed?\n")
        code, out = self.post({
            "action": "edit", "id": node_id,
            "set": {"title": "--looks like a flag, is a title"},
            "parents": {"add": ["2026-08-02-prekd-probe"]},
            "relates": {"add": [{"type": "supports", "id": "2026-08-02-prekd-probe",
                                 "note": "same sign: independent route"}]},
            "body": body})
        self.assertEqual(code, 200, out)
        self.assertEqual(out["cmd"][:3], ["cairn", "edit", node_id])
        self.assertEqual(out["node"], node_id)
        node = self.node(node_id)
        self.assertEqual(node.title, "--looks like a flag, is a title")
        self.assertEqual(node.parents, ["2026-08-02-prekd-probe"])
        self.assertEqual(node.relates, [{"to": "2026-08-02-prekd-probe", "type": "supports",
                                         "note": "same sign: independent route"}])
        self.assertEqual(node.body.strip(), body.strip())
        self.assertEqual((node.meta["updated"], node.history),
                         (before.meta["updated"], before.history))

    def test_an_edit_to_a_field_outside_the_whitelist_is_refused(self):
        node_id = "2026-08-02-prekd-probe"
        before = (FIXTURE / "nodes" / f"{node_id}.md").read_bytes()
        code, out = self.post({"action": "edit", "id": node_id,
                               "set": {"colour": "red"}})
        self.assertEqual(code, 400)
        self.assertIn("not a field edit can set", out["error"])
        code, out = self.post({"action": "edit", "id": node_id,
                               "set": {"status": "dead"}})
        self.assertEqual(code, 400)
        self.assertIn("new_node --update", out["error"])
        code, out = self.post({"action": "edit", "id": node_id,
                               "relations": {"add": []}})
        self.assertEqual(code, 400)
        self.assertIn("unknown edit key", out["error"])
        self.assertEqual((FIXTURE / "nodes" / f"{node_id}.md").read_bytes(), before)

    def test_an_edit_to_a_path_like_id_is_refused(self):
        for bad in ("../../etc/passwd", "nodes/2026-08-02-prekd-probe", "--help"):
            code, out = self.post({"action": "edit", "id": bad,
                                   "set": {"title": "x"}})
            self.assertEqual(code, 400, (bad, out))
            self.assertIn("expected form", out["error"])
        code, out = self.post({"action": "edit", "id": "2026-08-02-prekd-probe",
                               "parents": {"add": ["../escape"]}})
        self.assertEqual(code, 400)
        self.assertIn("not a node id", out["error"])

    # -- the security model ----------------------------------------------

    def test_a_cross_origin_write_is_refused(self):
        """Including `Origin: null`, which is what a file:// page and any
        sandboxed iframe both send."""
        for origin in ("https://evil.example", "null",
                       "http://127.0.0.1:1", "http://localhost"):
            code, out = self.post(
                {"action": "note", "id": "2026-08-02-prekd-probe", "text": "x"},
                headers={"Origin": origin})
            self.assertEqual(code, 403, origin)
            self.assertIn("cross-origin", out["error"])

    def test_our_own_origin_is_accepted(self):
        code, out = self.post(
            {"action": "note", "id": "2026-08-02-prekd-probe", "text": "same origin"},
            headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(code, 200, out)

    def test_a_rebound_host_header_is_refused(self):
        """Binding to loopback does not stop DNS rebinding — the packets really
        do arrive on loopback. The Host header is what still names the attacker."""
        for verb in ("get", "post"):
            if verb == "get":
                code, _, _ = self.get("/api/health", headers={"Host": "evil.example"})
            else:
                code, _ = self.post({"action": "note", "id": "2026-08-02-prekd-probe",
                                     "text": "x"}, headers={"Host": "evil.example"})
            self.assertEqual(code, 403, verb)

    def test_a_plain_form_post_cannot_reach_the_writer(self):
        """Requiring JSON forces a preflight on any cross-origin attempt, and
        this server answers none."""
        code, out = self.post(None, raw=b"action=note",
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(code, 415)

    def test_write_is_the_only_endpoint(self):
        code, out = self.post({"action": "note"}, headers={})
        self.assertIn(code, (400, 404))
        import json as _json
        import urllib.error, urllib.request
        req = urllib.request.Request(self.url("/api/anything"), data=b"{}",
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                self.fail(f"expected a refusal, got {res.status}")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)

    # -- the constraint that makes the server optional --------------------

    def test_the_map_is_read_only_until_the_probe_answers(self):
        """`build/graph.html` opened as a file must be exactly the page it was
        before this feature existed. Every write control is rendered only when
        `server.up`, and `server.up` is false until /api/health answers."""
        html = (FIXTURE / "build" / "graph.html").read_text()
        self.assertIn("const server = { up: false };", html)
        self.assertIn("probeServer();", html)
        # Not merely hidden with CSS — not emitted at all.
        self.assertRegex(html, r"\(server\.up\s*\n\s*\?\s*`<div class=\"wr\"><button data-save")
        self.assertRegex(html, r"server\.up && isLive\(\) \? statusBox\(n\)")
        self.assertRegex(html, r"server\.up \? `<span data-newchild")
        # The header button ships hidden and is unhidden by the probe, never by CSS.
        self.assertRegex(html, r'<button id="newNode"[^>]*hidden>')
        self.assertIn("$('#newNode').hidden = false;", html)

    def test_the_clipboard_path_survives(self):
        """The command-composing fallback is what the file:// copy still has, so
        it must not be quietly replaced by the button."""
        html = (FIXTURE / "build" / "graph.html").read_text()
        self.assertIn("copy command", html)
        self.assertIn("function noteCommand(", html)


CHAT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "chat"

#: A fake CLI. It records its argv and cwd beside itself, takes the session id
#: from `--resume <id>` (claude) or the first positional after `--` following
#: `resume` (codex), and replays the canned capture with that id substituted.
#: CAIRN_FAKE_MODE=fail exits non-zero with a stderr line; =hang prints one line
#: and then sleeps, recording its pid, so a disconnect can be shown to kill it.
FAKE_CLI = r"""#!/bin/sh
dir=$(dirname "$0")
name=$(basename "$0")
printf '%s\n' "$@" > "$dir/$name.argv"
pwd -P > "$dir/$name.cwd"
session=@DEFAULT@
prev=
resume=
dashes=
for a in "$@"; do
  if [ "$name" = claude ] && [ "$prev" = "--resume" ]; then session=$a; fi
  if [ "$name" = codex ] && [ "$a" = resume ]; then resume=1; fi
  if [ -n "$resume" ] && [ -n "$dashes" ] && [ "$dashes" = 1 ]; then session=$a; dashes=2; fi
  if [ "$a" = "--" ] && [ -z "$dashes" ]; then dashes=1; fi
  prev=$a
done
case "${CAIRN_FAKE_MODE:-ok}" in
  fail) echo "boom: not signed in" >&2; exit 3 ;;
  hang) echo '{"type":"system","subtype":"init","session_id":"'"$session"'"}'
        echo $$ > "$dir/$name.pid"
        exec sleep 60 ;;
esac
sed "s/@SESSION@/$session/g" "@FIXTURE@"
"""


def write_fake_cli(folder: Path, name: str, default_session: str) -> Path:
    path = folder / name
    path.write_text(FAKE_CLI.replace("@DEFAULT@", default_session)
                    .replace("@FIXTURE@", str(CHAT_FIXTURES / f"{name}-turn.jsonl")))
    path.chmod(0o755)
    return path


def canned(name: str, session: str = "s-1") -> list[str]:
    return (CHAT_FIXTURES / f"{name}-turn.jsonl").read_text().replace(
        "@SESSION@", session).splitlines()


class ChatTranslation(unittest.TestCase):
    """The captures in tests/fixtures/chat are real CLI output (Claude Code
    2.1.300, trimmed; Codex 0.162.1, see docs/chat-backends.md). If either CLI
    changes its stream, this is where it shows — not as a blank panel."""

    @classmethod
    def setUpClass(cls):
        global chat_backends
        import chat_backends                            # noqa: PLW0603

    def translate(self, backend, lines):
        state, out = {}, []
        for line in lines:
            out += backend.events(line, state)
        return out

    def test_claude_text_streams_once_not_twice(self):
        """With --include-partial-messages the reply arrives as deltas *and* as
        a complete message. Printing both would double every answer."""
        out = self.translate(chat_backends.Claude, canned("claude"))
        text = "".join(e["delta"] for e in out if e["type"] == "text")
        self.assertTrue(text.startswith("The `cairn standup` command printed"))
        self.assertEqual(text.count("The `cairn standup`"), 1)

    def test_claude_tool_calls_and_refusals_are_one_liners(self):
        out = self.translate(chat_backends.Claude, canned("claude"))
        tools = [e for e in out if e["type"] == "tool"]
        self.assertEqual(tools[0], {"type": "tool", "name": "Bash",
                                    "summary": "/tool/bin/cairn standup --project x"})
        self.assertEqual(tools[1]["summary"], "ls /")
        self.assertTrue(tools[2]["denied"])

    def test_claude_result_is_done_with_the_session(self):
        out = self.translate(chat_backends.Claude, canned("claude", "abc-1"))
        self.assertEqual(out[-1], {"type": "done", "session": "abc-1", "backend": "claude"})
        self.assertFalse([e for e in out if e["type"] == "error"])

    def test_claude_unreachable_api_is_an_error_not_a_reply(self):
        """Observed with the network down: a "<synthetic>" assistant message
        carrying the error text, then a result whose subtype is "success" and
        whose is_error is true. The verdict is is_error."""
        import json as _json
        lines = [
            _json.dumps({"type": "assistant", "session_id": "s", "message": {
                "model": "<synthetic>", "id": "x", "role": "assistant",
                "content": [{"type": "text", "text": "API Error: Can't reach the API server"}]}}),
            _json.dumps({"type": "result", "subtype": "success", "is_error": True,
                         "terminal_reason": "api_error", "session_id": "s",
                         "result": "API Error: Can't reach the API server"}),
        ]
        out = self.translate(chat_backends.Claude, lines)
        self.assertEqual([e["type"] for e in out], ["error", "done"])
        self.assertIn("API Error", out[0]["message"])

    def test_codex_translation(self):
        out = self.translate(chat_backends.Codex, canned("codex", "0199-th"))
        self.assertEqual(out[0], {"type": "tool", "name": "shell", "summary":
                                  "/bin/zsh -lc '/tool/bin/cairn standup --project prekd'"})
        # Started and completed is one tool event, not two; a declined one is news.
        shells = [e for e in out if e.get("name") == "shell"]
        self.assertEqual(len(shells), 2)
        self.assertTrue(shells[1]["denied"])
        self.assertIn({"type": "tool", "name": "edit",
                       "summary": "add /graph/inbox/2026-10-14-1200.md"}, out)
        self.assertIn({"type": "text", "delta": "prekd has one open question."}, out)
        self.assertEqual(out[-1], {"type": "done", "session": "0199-th", "backend": "codex"})

    def test_codex_retries_are_not_errors(self):
        """Codex prints its own reconnect attempts as top-level `error` lines,
        and a WebSockets fallback as an error *item*. Neither is a failure."""
        out = self.translate(chat_backends.Codex, canned("codex"))
        self.assertFalse([e for e in out if e["type"] == "error"])

    def test_codex_turn_failed_is_an_error_then_done(self):
        out = self.translate(chat_backends.Codex, [
            '{"type":"thread.started","thread_id":"t-1"}',
            '{"type":"turn.failed","error":{"message":"usage limit reached"}}'])
        self.assertEqual(out, [{"type": "error", "message": "usage limit reached"},
                               {"type": "done", "session": "t-1", "backend": "codex"}])

    def test_junk_lines_are_ignored(self):
        for backend in chat_backends.BACKENDS.values():
            self.assertEqual(backend.events("Reading prompt from stdin...", {}), [])
            self.assertEqual(backend.events("[1, 2]", {}), [])


class ChatArgv(unittest.TestCase):
    """What each CLI is allowed to do is decided here, so it is asserted
    explicitly rather than trusted."""

    @classmethod
    def setUpClass(cls):
        global chat_backends
        import chat_backends                            # noqa: PLW0603

    def test_claude_bash_is_bin_cairn_only(self):
        tool = Path("/opt/cairn")
        argv = chat_backends.Claude.argv("hi", system="S", cwd=Path("/g"), tool=tool)
        start = argv.index("--allowedTools")
        self.assertEqual(argv[start + 1:argv.index("--")],
                         ["Bash(/opt/cairn/bin/cairn *)", "Read", "Grep", "Glob", "Skill"])
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1], "S")
        self.assertIn("stream-json", argv)
        self.assertIn("--verbose", argv)
        self.assertNotIn("--resume", argv)

    def test_claude_may_not_review_its_own_draft(self):
        """`cairn review` admits a draft as read by a human; the chat running it
        would forge exactly that. Deny rules beat the bin/cairn allow rule."""
        argv = chat_backends.Claude.argv("hi", tool=Path("/opt/cairn"))
        denied = argv[argv.index("--disallowedTools") + 1:argv.index("--allowedTools")]
        for sub in ("review", "discard", "edit", "policy", "sync"):
            self.assertIn(f"Bash(/opt/cairn/bin/cairn {sub})", denied)
            self.assertIn(f"Bash(/opt/cairn/bin/cairn {sub} *)", denied)
        self.assertNotIn("Bash(/opt/cairn/bin/cairn note *)", denied)
        self.assertIn("cairn review|", chat_backends.system_prompt(Path("/g"), Path("/t")))

    def test_claude_prompt_is_last_and_cannot_be_a_flag(self):
        argv = chat_backends.Claude.argv("--dangerously-skip-permissions", session="s-1")
        self.assertEqual(argv[-2:], ["--", "--dangerously-skip-permissions"])
        self.assertEqual(argv[argv.index("--resume") + 1], "s-1")
        self.assertNotIn("--dangerously-skip-permissions", argv[:-1])

    def test_codex_writes_only_in_the_graph_root_and_asks_nobody(self):
        argv = chat_backends.Codex.argv("hi", system="S", cwd=Path("/graph"))
        self.assertEqual(argv[:3], ["codex", "exec", "--json"])
        self.assertEqual(argv[argv.index("-C") + 1], "/graph")
        self.assertIn('sandbox_mode="workspace-write"', argv)
        self.assertIn('approval_policy="never"', argv)
        self.assertIn('developer_instructions="S"', argv)
        self.assertEqual(argv[-2:], ["--", "hi"])
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)

    def test_codex_resume_keeps_the_same_policy(self):
        """`codex exec resume` takes neither -s nor -C, so the policy rides on
        -c and the working directory on the process — never dropped."""
        argv = chat_backends.Codex.argv("hi", session="t-1", cwd=Path("/graph"))
        self.assertEqual(argv[:4], ["codex", "exec", "resume", "--json"])
        self.assertIn('sandbox_mode="workspace-write"', argv)
        self.assertEqual(argv[-3:], ["--", "t-1", "hi"])

    def test_system_prompt_names_the_root_and_the_only_writer(self):
        text = chat_backends.system_prompt(Path("/graph"), Path("/opt/cairn"))
        self.assertIn("/graph", text)
        self.assertIn("/opt/cairn/bin/cairn", text)
        self.assertIn("git commit", text)
        self.assertIn("standup --project", text)
        self.assertNotIn(".git read-only", text)
        self.assertIn(".git read-only",
                      chat_backends.system_prompt(Path("/g"), Path("/t"), "codex"))

    def test_the_open_node_rides_on_the_turn_not_the_system_prompt(self):
        """Claude Code reuses a conversation's first system prompt on every
        --resume, so a node named there would go stale on the next click."""
        prompt = chat_backends.turn_prompt("why dead?", ("2026-08-02-prekd-probe", "Probe"))
        self.assertIn("2026-08-02-prekd-probe", prompt)
        self.assertIn('"Probe"', prompt)
        self.assertTrue(prompt.endswith("why dead?"))
        self.assertEqual(chat_backends.turn_prompt("hi"), "hi")


class ChatServe(unittest.TestCase):
    """`/api/chat` end to end, against fake `claude` and `codex` executables
    first on PATH. The real CLIs are never run by the suite."""

    @classmethod
    def setUpClass(cls):
        import threading
        global serve
        import serve                                    # noqa: PLW0603
        clear()
        write("2026-08-02-prekd-probe.md",
              node_text("2026-08-02-prekd-probe", project="prekd"))
        build_graph.main()
        cls.bin = Path(tempfile.mkdtemp(prefix="cairn-fakecli-"))
        write_fake_cli(cls.bin, "claude", "11111111-2222-4333-8444-555555555555")
        write_fake_cli(cls.bin, "codex", "0199e0aa-0000-7000-8000-000000000001")
        cls.old_path = os.environ["PATH"]
        os.environ["PATH"] = f"{cls.bin}{os.pathsep}{cls.old_path}"
        cls.servers = []
        cls.port = cls.start(chat=True)
        cls.off_port = cls.start(chat=False)

    @classmethod
    def start(cls, chat):
        import threading
        httpd = serve.serve(0, quiet=True, chat=chat)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        cls.servers.append((httpd, thread))
        return httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        os.environ["PATH"] = cls.old_path
        os.environ.pop("CAIRN_FAKE_MODE", None)
        for httpd, thread in cls.servers:
            httpd.shutdown()
            thread.join(timeout=5)
            httpd.server_close()
        shutil.rmtree(cls.bin, ignore_errors=True)

    def tearDown(self):
        os.environ.pop("CAIRN_FAKE_MODE", None)

    def chat(self, payload, headers=None, port=None, raw=None):
        """(status, content-type, [events]) — events parsed line by line."""
        import json as _json
        import urllib.error, urllib.request
        head = {"Content-Type": "application/json"}
        head.update(headers or {})
        body = raw if raw is not None else _json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port or self.port}/api/chat", data=body,
            headers=head, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                lines = [l for l in res.read().decode().splitlines() if l.strip()]
                return res.status, res.headers, [_json.loads(l) for l in lines]
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, [_json.loads(exc.read())]

    def argv(self, name):
        return (self.bin / f"{name}.argv").read_text().splitlines()

    # -- the stream ------------------------------------------------------

    def test_claude_turn_streams_as_ndjson_and_ends_with_done(self):
        code, headers, events = self.chat({"backend": "claude", "message": "what is open?"})
        self.assertEqual(code, 200, events)
        self.assertEqual(headers["Content-Type"], "application/x-ndjson")
        self.assertEqual(headers["Transfer-Encoding"], "chunked")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        kinds = [e["type"] for e in events]
        self.assertIn("text", kinds)
        self.assertIn("tool", kinds)
        self.assertEqual(kinds.count("done"), 1)
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["backend"], "claude")
        self.assertEqual(done["session"], "11111111-2222-4333-8444-555555555555")
        self.assertTrue(done["ok"])
        self.assertTrue(done["rebuilt"], "a clean exit rebuilds the map")

    def test_the_cli_runs_in_the_graph_root_against_this_graph(self):
        self.chat({"backend": "claude", "message": "hi"})
        self.assertEqual((self.bin / "claude.cwd").read_text().strip(),
                         str(FIXTURE.resolve()))
        argv = self.argv("claude")
        self.assertIn(f"Bash({serve.TOOL_ROOT}/bin/cairn *)", argv)

    def test_session_round_trips(self):
        code, _, events = self.chat({"backend": "claude", "message": "and then?",
                                     "session": "aaaa-bbbb"})
        self.assertEqual(code, 200, events)
        self.assertEqual(events[-1]["session"], "aaaa-bbbb")
        argv = self.argv("claude")
        self.assertEqual(argv[argv.index("--resume") + 1], "aaaa-bbbb")

    def test_codex_turn_and_resume(self):
        code, _, events = self.chat({"backend": "codex", "message": "hi"})
        self.assertEqual(code, 200, events)
        self.assertEqual(events[-1]["session"], "0199e0aa-0000-7000-8000-000000000001")
        self.assertIn({"type": "text", "delta": "prekd has one open question."}, events)
        code, _, events = self.chat({"backend": "codex", "message": "more",
                                     "session": "0199e0aa-0000-7000-8000-00000000beef"})
        self.assertEqual(events[-1]["session"], "0199e0aa-0000-7000-8000-00000000beef")
        self.assertIn("resume", self.argv("codex"))

    def test_the_open_node_reaches_the_prompt_by_id_and_title(self):
        code, _, events = self.chat({"backend": "claude", "message": "why?",
                                     "node": "2026-08-02-prekd-probe"})
        self.assertEqual(code, 200, events)
        # The prompt is the last argument; it spans lines, so read it whole.
        argv = (self.bin / "claude.argv").read_text()
        prompt = argv.rsplit("\n--\n", 1)[1]
        self.assertIn("2026-08-02-prekd-probe", prompt)
        self.assertIn("why?", prompt)

    def test_an_unknown_node_is_404_before_anything_runs(self):
        code, _, out = self.chat({"backend": "claude", "message": "x",
                                  "node": "2026-08-02-prekd-ghost"})
        self.assertEqual(code, 404)

    def test_a_failed_turn_says_why_and_does_not_rebuild(self):
        os.environ["CAIRN_FAKE_MODE"] = "fail"
        code, _, events = self.chat({"backend": "claude", "message": "hi"})
        self.assertEqual(code, 200)
        errors = [e for e in events if e["type"] == "error"]
        self.assertTrue(errors and "not signed in" in errors[0]["message"], events)
        self.assertFalse(events[-1]["ok"])
        self.assertFalse(events[-1]["rebuilt"])

    def test_a_closed_tab_stops_the_cli(self):
        """The CLI must not keep thinking — and spending — after the browser
        has gone. The fake sleeps; the disconnect has to kill it."""
        import socket, time
        os.environ["CAIRN_FAKE_MODE"] = "hang"
        pidfile = self.bin / "claude.pid"
        if pidfile.exists():
            pidfile.unlink()
        body = b'{"backend":"claude","message":"hi"}'
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=30)
        sock.sendall(b"POST /api/chat HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                     b"Content-Type: application/json\r\n"
                     b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
        self.assertIn(b"200", sock.recv(4096))
        deadline = time.time() + 15
        while not pidfile.exists() and time.time() < deadline:
            time.sleep(0.1)
        pid = int(pidfile.read_text())
        sock.close()
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.2)
        self.fail("the CLI was still running after the client hung up")

    # -- refusals --------------------------------------------------------

    def test_unknown_backend_is_400(self):
        code, _, out = self.chat({"backend": "gpt", "message": "hi"})
        self.assertEqual(code, 400)
        self.assertIn("claude", out[0]["error"])

    def test_empty_message_and_flag_shaped_session_are_400(self):
        self.assertEqual(self.chat({"backend": "claude", "message": " "})[0], 400)
        self.assertEqual(self.chat({"backend": "claude", "message": "x",
                                    "session": "--help"})[0], 400)

    def test_a_missing_cli_is_503_and_names_the_install_step(self):
        os.environ["PATH"] = "/usr/bin:/bin"
        try:
            for name, hint in (("claude", "sign in"), ("codex", "codex login")):
                code, _, out = self.chat({"backend": name, "message": "hi"})
                self.assertEqual(code, 503, name)
                self.assertIn(hint, out[0]["error"])
        finally:
            os.environ["PATH"] = f"{self.bin}{os.pathsep}{self.old_path}"

    def test_cross_origin_and_form_posts_are_refused(self):
        for origin in ("https://evil.example", "null"):
            code, _, out = self.chat({"backend": "claude", "message": "hi"},
                                     headers={"Origin": origin})
            self.assertEqual(code, 403, origin)
        code, _, _ = self.chat(None, raw=b"backend=claude",
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(code, 415)
        code, _, _ = self.chat({"backend": "claude", "message": "hi"},
                               headers={"Host": "evil.example"})
        self.assertEqual(code, 403)

    # -- health and --no-chat --------------------------------------------

    def health(self, port):
        import json as _json
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=30) as res:
            return _json.loads(res.read())

    def test_health_reports_which_clis_are_on_path(self):
        chat = self.health(self.port)["chat"]
        self.assertEqual(chat, {"claude": str(self.bin / "claude"),
                                "codex": str(self.bin / "codex")})

    def test_no_chat_hides_both_and_refuses_the_endpoint(self):
        self.assertEqual(self.health(self.off_port)["chat"], {})
        code, _, out = self.chat({"backend": "claude", "message": "hi"}, port=self.off_port)
        self.assertEqual(code, 404)
        self.assertIn("--no-chat", out[0]["error"])


class InstallCodex(unittest.TestCase):
    """`install_context --codex` writes into $HOME and into the graph repo, so
    the tests are about idempotence and about not touching what it did not write."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cairn-home-"))
        self.graph = Path(tempfile.mkdtemp(prefix="cairn-graph-"))
        (self.graph / "nodes").mkdir()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.graph, ignore_errors=True)
        self.skills = self.home / ".agents" / "skills"

    def run_install(self, *args):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "install_context", "--codex", *args],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": str(self.home), "CAIRN_ROOT": str(self.graph),
                 "CAIRN_PYTHON": sys.executable})

    def test_dry_run_writes_nothing(self):
        for args in ((), ("--dry-run",), ("--dry-run", "--apply")):
            result = self.run_install(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Dry run", result.stdout)
            self.assertFalse(self.skills.exists(), args)
            self.assertFalse((self.graph / "AGENTS.md").exists(), args)

    def test_apply_links_every_skill_and_writes_the_pointer(self):
        result = self.run_install("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for skill in ("cairn-capture", "cairn-log", "cairn-resume"):
            link = self.skills / skill
            self.assertTrue(link.is_symlink(), skill)
            self.assertEqual(link.resolve(), (self.ROOT / "skills" / skill).resolve())
        self.assertIn("CLAUDE.md", (self.graph / "AGENTS.md").read_text())

    def test_apply_is_idempotent_and_keeps_an_existing_agents_md(self):
        (self.graph / "AGENTS.md").write_text("# Ours\n\nKeep this.\n")
        self.run_install("--apply")
        first = (self.graph / "AGENTS.md").read_text()
        self.assertTrue(first.startswith("# Ours\n\nKeep this.\n"))
        again = self.run_install("--apply")
        self.assertIn("Nothing to change", again.stdout)
        self.assertEqual(first, (self.graph / "AGENTS.md").read_text())

    def test_remove_takes_back_exactly_what_it_wrote(self):
        (self.graph / "AGENTS.md").write_text("# Ours\n")
        self.run_install("--apply")
        self.run_install("--remove", "--apply")
        self.assertEqual((self.graph / "AGENTS.md").read_text(), "# Ours\n")
        self.assertEqual(list(self.skills.iterdir()), [])

    def test_codex_is_user_scoped_only(self):
        """Codex has no untracked per-project file like CLAUDE.local.md, so a
        project-scoped install would put this machine's paths into a checkout."""
        project = Path(tempfile.mkdtemp(prefix="cairn-proj-"))
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        result = self.run_install("--project", str(project), "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("user-scoped", result.stderr)
        self.assertEqual(list(project.iterdir()), [])

    def test_a_real_skill_directory_of_the_same_name_is_left_alone(self):
        mine = self.skills / "cairn-log"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("mine")
        result = self.run_install("--apply")
        self.assertIn("CONFLICT", result.stdout)
        self.assertEqual((mine / "SKILL.md").read_text(), "mine")
        self.assertTrue((self.skills / "cairn-capture").is_symlink())


class Edit(unittest.TestCase):
    """`cairn edit` is the one sanctioned way to change a node after the fact, so
    the tests that matter are the refusals: every one is a way a correction could
    quietly become a status change, a rename, or a broken graph. Run through the
    dispatcher, against a throwaway graph that is a real git repo, because the
    commit is half of what the command does."""

    CAIRN = Path(__file__).resolve().parent.parent / "bin" / "cairn"
    ROOT_ID = "2026-08-01-demo-root"
    RUN_ID = "2026-08-02-demo-run"
    TASK_ID = "2026-08-03-demo-task"
    NOTES = "## Notes\n\n- **2026-08-26** (jlaw) does it track the seed?\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cairn-edit-"))
        (self.tmp / "nodes").mkdir()
        self.git("init", "-q", ".")
        self.git("config", "user.email", "jlaw@example.gov")
        self.git("config", "user.name", "Jeff Law")
        self.put(self.ROOT_ID, node_text(self.ROOT_ID, "direction", "open",
                                         project="demo", created="2026-08-01"))
        self.put(self.RUN_ID, node_text(
            self.RUN_ID, project="demo", parents=f"[{self.ROOT_ID}]",
            updated="2026-08-05",
            history="  - {date: 2026-08-02, status: planned, note: created}\n"
                    "  - {date: 2026-08-05, status: running, note: queued}",
        ).rstrip("\n") + "\n\n" + self.NOTES)
        self.put(self.TASK_ID, node_text(self.TASK_ID, "task", "todo", project="demo",
                                         created="2026-08-03", extra="due: 2026-09-01\n"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "seed")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", str(self.tmp), *args],
                              capture_output=True, text=True, timeout=30)

    def put(self, node_id, text):
        (self.tmp / "nodes" / f"{node_id}.md").write_text(text.lstrip("\n"))

    def path(self, node_id):
        return self.tmp / "nodes" / f"{node_id}.md"

    def node(self, node_id):
        return lib.parse_file(self.path(node_id))

    def edit(self, *args, stdin=None):
        import subprocess
        return subprocess.run(
            [str(self.CAIRN), "edit", *args], input=stdin,
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ, CAIRN_ROOT=str(self.tmp)))

    def refused(self, node_id, *args, says="", stdin=None):
        """Assert a refusal that names its reason and leaves the file untouched."""
        before = self.path(node_id).read_bytes()
        done = self.edit(node_id, *args, stdin=stdin)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        if says:
            self.assertIn(says, done.stderr)
        self.assertEqual(self.path(node_id).read_bytes(), before,
                         "a refused edit wrote to the file")
        return done

    # -- what lands -------------------------------------------------------

    def test_an_edit_commits_and_prints_the_path_first(self):
        """serve.py derives `committed` from the first line, as for `note`."""
        done = self.edit(self.RUN_ID, "--title", "A better title",
                         "--parent", self.TASK_ID)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines()[0], f"nodes/{self.RUN_ID}.md")
        self.assertEqual(self.node(self.RUN_ID).title, "A better title")
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")
        message = self.git("log", "-1", "--format=%B").stdout
        self.assertIn(f"edit {self.RUN_ID}: title, +parent {self.TASK_ID}", message)
        self.assertIn(lib.review_trailer("jlaw", self.RUN_ID), message)

    def test_an_edit_moves_neither_updated_nor_history(self):
        """An edit is a correction, not a claim about the state of the work. If it
        moved `updated`, the replay slider would show a change that never happened."""
        before = self.node(self.RUN_ID)
        self.assertEqual(self.edit(self.RUN_ID, "--title", "Retitled",
                                   "--host", "kestrel").returncode, 0)
        after = self.node(self.RUN_ID)
        self.assertEqual(after.meta["updated"], before.meta["updated"])
        self.assertEqual(after.history, before.history)
        self.assertEqual(after.status, before.status)

    def test_a_body_sent_back_unchanged_round_trips_notes(self):
        """The map sends the whole body back. `## Notes` lives there, and must
        come out byte for byte what went in."""
        before = self.node(self.RUN_ID)
        done = self.edit(self.RUN_ID, "--title", "T2", "--body", "-", stdin=before.body)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("body", done.stdout.splitlines()[1])
        after = self.node(self.RUN_ID)
        self.assertEqual(after.body, before.body)
        self.assertEqual(lib.read_notes(after), lib.read_notes(before))

    def test_a_replaced_body_lands_verbatim(self):
        body = ("## Claim\n\nThe tether holds.\n\n## Result\n\n"
                "| run | MAE |\n|---|---|\n| a | 1.4 |\n\n" + self.NOTES)
        src = self.tmp / "body.txt"
        src.write_text(body)
        self.assertEqual(self.edit(self.RUN_ID, "--body", str(src)).returncode, 0)
        after = self.node(self.RUN_ID)
        self.assertEqual(after.body.strip(), body.strip())
        self.assertEqual([n["text"] for n in lib.read_notes(after)],
                         ["does it track the seed?"])

    def test_relations_can_be_added_and_dropped(self):
        done = self.edit(self.RUN_ID, "--relate",
                         f"supports:{self.TASK_ID}:same sign, independent route")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.node(self.RUN_ID).relates,
                         [{"to": self.TASK_ID, "type": "supports",
                           "note": "same sign, independent route"}])
        self.assertEqual(self.edit(self.RUN_ID, "--unrelate",
                                   f"supports:{self.TASK_ID}").returncode, 0)
        self.assertNotIn("relates", self.node(self.RUN_ID).meta)

    def test_an_optional_scalar_can_be_cleared(self):
        self.assertEqual(self.edit(self.TASK_ID, "--clear", "due").returncode, 0)
        self.assertNotIn("due", self.node(self.TASK_ID).meta)

    def test_an_all_digit_sha_stays_a_string(self):
        """`commit: 1234567` reads back as an integer. The serializer has to quote
        it, and the round-trip check is what would have caught it if not."""
        self.assertEqual(self.edit(self.RUN_ID, "--repo", "git@x:y.git",
                                   "--commit", "1234567").returncode, 0)
        self.assertEqual(self.node(self.RUN_ID).meta["commit"], "1234567")
        self.assertEqual([str(i) for i in lib.validate(self.tmp) if i.level == "error"], [])

    def test_a_dry_run_shows_the_diff_and_writes_nothing(self):
        before = self.path(self.RUN_ID).read_bytes()
        done = self.edit(self.RUN_ID, "--title", "Dry", "--dry-run")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("+title: Dry", done.stdout)
        self.assertIn("-title: A title for", done.stdout)
        self.assertEqual(self.path(self.RUN_ID).read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

    def test_no_commit_leaves_it_on_disk(self):
        self.assertEqual(self.edit(self.RUN_ID, "--title", "Draft fix",
                                   "--no-commit").returncode, 0)
        self.assertIn(self.RUN_ID, self.git("status", "--porcelain").stdout)

    # -- what is refused, with nothing written ---------------------------

    def test_the_fields_that_move_with_history_are_refused_by_name(self):
        for field, value in (("status", "dead"), ("updated", "2026-09-01"),
                             ("history", "x"), ("id", "2026-08-02-demo-x"),
                             ("type", "task"), ("created", "2026-08-01")):
            done = self.refused(self.RUN_ID, f"--{field}", value, says=field)
            if field in ("status", "updated", "history"):
                self.assertIn("new_node --update", done.stderr)
            self.refused(self.RUN_ID, "--clear", field, says=field)

    def test_a_field_the_type_does_not_carry_is_refused(self):
        self.refused(self.RUN_ID, "--due", "2026-11-01", says="experiment has no 'due'")
        self.refused(self.ROOT_ID, "--artifact", "kestrel:/x", says="direction has no")
        self.refused(self.TASK_ID, "--clear", "contacts", says="contacts")

    def test_a_required_field_cannot_be_cleared(self):
        self.refused(self.RUN_ID, "--clear", "title", says="required")
        self.refused(self.RUN_ID, "--clear", "project", says="required")

    def test_an_edit_that_changes_nothing_is_refused(self):
        title = self.node(self.RUN_ID).title
        self.refused(self.RUN_ID, "--title", title, says="nothing would change")
        self.refused(self.RUN_ID, "--body", "-", stdin=self.node(self.RUN_ID).body,
                     says="nothing would change")
        self.refused(self.RUN_ID, says="nothing would change")

    def test_a_list_operation_that_would_do_nothing_is_refused(self):
        """It means the caller's picture of the node is out of date."""
        self.refused(self.RUN_ID, "--parent", self.ROOT_ID, says="already a parent")
        self.refused(self.RUN_ID, "--drop-ref", "10.1021/nope", says="not a ref")
        self.refused(self.RUN_ID, "--unrelate", f"supports:{self.ROOT_ID}",
                     says="no 'supports' relation")

    def test_a_parent_that_closes_a_cycle_is_refused_with_nothing_written(self):
        self.refused(self.ROOT_ID, "--parent", self.RUN_ID, says="cycle")
        self.refused(self.RUN_ID, "--parent", self.RUN_ID, says="own parent")

    def test_a_target_that_does_not_exist_is_refused(self):
        self.refused(self.RUN_ID, "--parent", "2026-08-09-demo-ghost", says="dangling")
        self.refused(self.RUN_ID, "--relate", "contradicts:2026-08-09-demo-ghost:x",
                     says="dangling")

    def test_the_validators_field_rules_hold(self):
        self.refused(self.RUN_ID, "--commit", "main", says="not a git SHA")
        self.refused(self.RUN_ID, "--artifact", "results.json", says="host:/")
        self.refused(self.RUN_ID, "--ref", "doi.org/10.1/x", says="bare DOI")
        self.refused(self.TASK_ID, "--due", "next week", says="ISO date")
        self.refused(self.RUN_ID, "--title", "two\nlines", says="one line")

    def test_an_unknown_project_is_refused_without_offering_a_new_one(self):
        """Moving a node into a project the graph has never seen is a creation-time
        decision; the refusal must not suggest a flag edit does not have."""
        done = self.refused(self.RUN_ID, "--project", "demoo", says="did you mean: demo")
        self.assertNotIn("--new-project", done.stderr)

    def test_an_empty_body_is_refused(self):
        self.refused(self.RUN_ID, "--body", "-", stdin="  \n", says="never deleted")

    def test_an_id_must_be_exact(self):
        """`note` accepts a fragment because a note is capture; an edit rewrites
        a node, so a fragment that happens to match is not good enough."""
        done = self.edit("demo-run", "--title", "x")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no such node", done.stderr)


class DocumentedCommands(unittest.TestCase):
    """Docs must not tell anyone to run scripts/*.py directly — it fails on the
    machine most likely to be reading them."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_no_doc_invokes_a_script_directly(self):
        offenders = []
        for rel in ("README.md", "CLAUDE.md"):
            offenders += [
                f"{rel}:{i}" for i, line in enumerate(
                    (self.ROOT / rel).read_text().splitlines(), 1)
                if re.search(r"(?<!lib\.)\bscripts/[a-z_]+\.py", line)
                and "find_python" not in line
            ]
        # skills/ counts double here: those files are read by agents in *other*
        # repos, where a wrong invocation fails in a session nobody is watching.
        for path in list((self.ROOT / "docs").rglob("*.md")) + \
                    list((self.ROOT / ".claude" / "commands").glob("*.md")) + \
                    list((self.ROOT / "skills").rglob("*.md")):
            offenders += [
                f"{path.relative_to(self.ROOT)}:{i}" for i, line in enumerate(
                    path.read_text().splitlines(), 1)
                if re.search(r"\bscripts/[a-z_]+\.py", line)
                and "find_python" not in line
            ]
        self.assertEqual(offenders, [], f"use `bin/cairn <cmd>` instead: {offenders}")


class Review(unittest.TestCase):
    """`reviewed` is derived from git, so every check here is about what the log
    can and cannot honestly say. The failure mode to guard is a derivation that
    reports "reviewed" for work nobody read — which is what the *old* signal
    (`Co-Authored-By`) would have done, since under decision 6 a node only ever
    reached a commit after a human had looked at it."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cairn-review-"))
        (self.tmp / "nodes").mkdir()
        (self.tmp / "build").mkdir()
        self.git("init", "-q", ".")
        self.git("config", "user.email", "jlaw@example.gov")
        self.git("config", "user.name", "Jeff Law")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", str(self.tmp), *args],
                              capture_output=True, text=True, timeout=30)

    def node(self, name, body="x"):
        path = self.tmp / "nodes" / f"{name}.md"
        path.write_text(node_text(name, project="demo").lstrip("\n") + f"\n{body}\n")
        return path

    def commit(self, message, add=True):
        if add:
            self.git("add", "-A")
        return self.git("commit", "-q", "--allow-empty", "-m", message)

    def states(self):
        return {k: v["state"] for k, v in lib.review_state(self.tmp).items()}

    # -- the derivation ---------------------------------------------------

    def test_without_the_convention_nothing_is_classified(self):
        """Day one, and the honest answer for the 125 nodes already in the real
        graph: git has no opinion, and saying "unreviewed" would be a claim the
        record cannot support."""
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.assertEqual(self.states(), {"2026-08-01-demo-a": "unclassified"})

    def test_a_stamp_marks_the_node_read(self):
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.commit(f"review\n\n{lib.review_trailer('jlaw', '2026-08-01-demo-a')}",
                    add=False)
        self.assertEqual(self.states()["2026-08-01-demo-a"], "reviewed")

    def test_a_write_after_a_review_re_arms_the_node(self):
        """The unit is "touched since the last write", not a boolean. An agent
        appending a result to a node someone read last week has produced a claim
        nobody has read."""
        path = self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.commit(f"review\n\n{lib.review_trailer('jlaw', '2026-08-01-demo-a')}",
                    add=False)
        path.write_text(path.read_text() + "\n## Result\n\nworked\n")
        self.commit("agent appends a result")
        self.assertEqual(self.states()["2026-08-01-demo-a"], "unreviewed")

    def test_a_note_and_its_stamp_in_one_commit_count_as_read(self):
        """`cairn note` writes the body and stamps the trailer in a single
        commit, so the write and the review share a position. Equal has to mean
        reviewed or a note would never count as one."""
        path = self.node("2026-08-01-demo-a")
        self.commit("seed")
        path.write_text(path.read_text() + "\n- **2026-08-27** (jlaw) hm\n")
        self.commit(f"note on it\n\n{lib.review_trailer('jlaw', '2026-08-01-demo-a')}")
        self.assertEqual(self.states()["2026-08-01-demo-a"], "reviewed")

    def test_a_node_older_than_the_convention_stays_unclassified(self):
        """The epoch is derived — the oldest commit carrying a stamp — so no
        date has to be stored anywhere. Work that predates it is not a miss."""
        self.node("2026-08-01-demo-old")
        self.commit("seed")
        self.node("2026-08-02-demo-new")
        self.commit("second node")
        self.commit(f"review\n\n{lib.review_trailer('jlaw', '2026-08-02-demo-new')}",
                    add=False)
        states = self.states()
        self.assertEqual(states["2026-08-02-demo-new"], "reviewed")
        self.assertEqual(states["2026-08-01-demo-old"], "unclassified")

    def test_an_uncommitted_draft_is_not_reviewed(self):
        """The case decision 6 exists for. It is `uncommitted` rather than
        `unreviewed` because the two need different actions."""
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.node("2026-08-02-demo-draft")
        nodes, _ = lib.load_nodes(self.tmp)
        states = lib.review_states(nodes, self.tmp)
        self.assertEqual(states["2026-08-02-demo-draft"]["state"], "uncommitted")

    def test_a_stamp_for_a_node_git_never_saw_is_ignored(self):
        """A typo'd id must not invent a node. The commit-msg hook is what stops
        it being written; this is the belt to that pair of braces."""
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.commit(f"review\n\n{lib.review_trailer('jlaw', '2026-08-01-demo-nope')}",
                    add=False)
        self.assertNotIn("2026-08-01-demo-nope", self.states())

    def test_it_survives_a_repo_with_no_git_at_all(self):
        """Same contract as node_authors: no git is not an error, it is silence."""
        with tempfile.TemporaryDirectory() as bare:
            (Path(bare) / "nodes").mkdir()
            self.assertEqual(lib.review_state(Path(bare)), {})

    # -- the command ------------------------------------------------------

    def test_review_admits_an_untracked_draft(self):
        """`git commit --only` refuses a path git has never seen, which is
        exactly the draft case. Reviewing one has to stage it first, or the
        queue this command exists to drain cannot drain."""
        import subprocess
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.node("2026-08-02-demo-draft")
        done = subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "review", "demo-draft", "keep it"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CAIRN_ROOT": str(self.tmp)})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.states()["2026-08-02-demo-draft"], "reviewed")
        self.assertNotIn("demo-draft", self.git("status", "--porcelain").stdout)

    def test_review_with_nothing_to_add_is_an_empty_commit(self):
        """"I read it and had nothing to say" is a real outcome, and the whole
        reason the trailer carries the node id rather than relying on the diff."""
        import subprocess
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        done = subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "review", "demo-a"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CAIRN_ROOT": str(self.tmp)})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.states()["2026-08-01-demo-a"], "reviewed")
        touched = self.git("show", "--name-only", "--format=", "HEAD").stdout
        self.assertEqual(touched.strip(), "", "a review with no note wrote a file")

    # -- the hook ---------------------------------------------------------

    def test_the_hook_blocks_a_stamp_aimed_at_nothing(self):
        """The one failure this derivation has is silent: a mistyped id matches
        nothing, the commit succeeds, and the node stays unread forever."""
        self.node("2026-08-01-demo-a")
        self.commit("seed")
        self.git("config", "core.hooksPath", str(self.ROOT / ".githooks"))
        before = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.commit(
            f"review\n\n{lib.review_trailer('jlaw', '2026-08-01-demo-typo')}",
            add=False)
        self.assertNotEqual(done.returncode, 0, "a bad stamp was allowed through")
        self.assertIn("no such node", done.stdout + done.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before)

    def test_the_hook_is_silent_when_there_is_no_stamp(self):
        """Most commits carry no trailer. The convention marks the human act, not
        the agent one, so an ordinary commit must not need anything."""
        self.node("2026-08-01-demo-a")
        self.git("config", "core.hooksPath", str(self.ROOT / ".githooks"))
        done = self.commit("an ordinary commit")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class Export(unittest.TestCase):
    """cairn export — one project's view, written into that project's repo.

    The behaviour worth protecting is not that it writes files. It is that a
    filtered view never makes a hidden edge look like an absent one, because
    absence meaning something is the whole premise of the graph.
    """

    def setUp(self):
        clear()
        self.dest = Path(tempfile.mkdtemp(prefix="cairn-export-"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)

    def load(self):
        nodes, errors = lib.load_nodes()
        self.assertEqual(errors, [])
        return nodes

    def test_outbound_edge_is_reported_not_dropped(self):
        write("2026-08-01-alpha-root.md", node_text(
            "2026-08-01-alpha-root", project="alpha", type_="direction", status="open"))
        write("2026-08-02-beta-thing.md", node_text(
            "2026-08-02-beta-thing", project="beta", created="2026-08-02"))
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03",
            parents="[2026-08-01-alpha-root]") + "\nMentions [[2026-08-02-beta-thing]].\n")

        nodes = self.load()
        selected = {i: n for i, n in nodes.items() if n.project == "alpha"}
        edges = export.outbound_edges(selected, nodes)

        self.assertEqual(len(edges), 1, edges)
        source, kind, target, project = edges[0]
        self.assertEqual(source, "2026-08-03-alpha-child")
        self.assertEqual(kind, "mentions")
        self.assertEqual(target, "2026-08-02-beta-thing")
        self.assertEqual(project, "beta")

        # ...and the in-project parent is not reported as leaving.
        self.assertNotIn("2026-08-01-alpha-root", [e[2] for e in edges])

    def test_one_edge_per_target_even_when_related_and_mentioned(self):
        """A node that both relates to another and names it in prose is one edge.

        The renderer already collapses a doubled edge, styling it by the more
        specific claim; reporting it twice here was noise in the first version.
        """
        write("2026-08-02-beta-thing.md", node_text(
            "2026-08-02-beta-thing", project="beta", created="2026-08-02"))
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03",
            extra="relates:\n  - {to: 2026-08-02-beta-thing, type: supports, note: why}\n",
        ) + "\nAlso mentions [[2026-08-02-beta-thing]].\n")

        nodes = self.load()
        selected = {i: n for i, n in nodes.items() if n.project == "alpha"}
        edges = export.outbound_edges(selected, nodes)

        self.assertEqual(len(edges), 1, edges)
        self.assertEqual(edges[0][1], "supports")  # the typed claim wins the label

    def test_prose_wikilink_is_not_read_as_an_edge(self):
        """`[[wikilinks]]` in prose about the syntax is not a reference to a node."""
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03",
        ) + "\nRefer to another node as [[wikilinks]] in the body.\n")
        nodes = self.load()
        self.assertEqual(export.outbound_edges(nodes, nodes), [])

    def test_next_line_is_a_whole_sentence(self):
        """Regression: bodies are hand-wrapped, so the first *line* is half a sentence.

        The first version emitted "...rather than a pretraining target.** The raw
        value already" — an unclosed bold marker and a cut mid-sentence, which
        reads as a typo and undermines the index it appears in.
        """
        section = ("- **Try density as an input feature** rather than a\n"
                   "  pretraining target. The raw value already exists.\n"
                   "- A second item that must not be included.\n")
        self.assertEqual(
            export.first_sentence(section),
            "Try density as an input feature rather than a pretraining target.")

    def test_next_line_drops_wikilink_brackets_but_keeps_the_id(self):
        section = "Needs the fix in [[2026-08-11-polyid-md-fix-label-audit]] first.\n"
        self.assertEqual(
            export.first_sentence(section),
            "Needs the fix in `2026-08-11-polyid-md-fix-label-audit` first.")

    def test_writes_three_files_each_carrying_the_marker(self):
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03"))
        argv = sys.argv
        sys.argv = ["cairn export", "--project", "alpha", "--dest", str(self.dest)]
        try:
            self.assertEqual(export.main(), 0)
        finally:
            sys.argv = argv
        for name in ("graph.html", "graph.md", "README.md"):
            path = self.dest / name
            self.assertTrue(path.exists(), name)
            self.assertIn(export.MARKER, path.read_text(encoding="utf-8"), name)

    def test_refuses_to_overwrite_a_file_it_did_not_write(self):
        """Hand-written documentation is not something a generator should replace."""
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03"))
        mine = self.dest / "README.md"
        mine.write_text("# My own notes, written by a person\n", encoding="utf-8")

        argv = sys.argv
        sys.argv = ["cairn export", "--project", "alpha", "--dest", str(self.dest)]
        try:
            self.assertEqual(export.main(), 1)
        finally:
            sys.argv = argv
        self.assertEqual(mine.read_text(encoding="utf-8"),
                         "# My own notes, written by a person\n")
        self.assertFalse((self.dest / "graph.html").exists())

    def test_unknown_project_is_refused_with_the_known_keys(self):
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03"))
        argv = sys.argv
        sys.argv = ["cairn export", "--project", "alpah", "--dest", str(self.dest)]
        try:
            self.assertEqual(export.main(), 2)
        finally:
            sys.argv = argv



class ExportExampleExclude(unittest.TestCase):
    """cairn export_example --exclude — holding a node back from publication.

    The behaviour worth protecting is the pair of refusals. Excluding a node is
    a publication decision, and the two ways to get it silently wrong are a
    typo (which would publish the node you meant to hold back) and excluding a
    node something else depends on (which would emit a graph that lies).
    """

    def setUp(self):
        clear()
        self.dest = Path(tempfile.mkdtemp(prefix="cairn-exex-"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)

    def run_export(self, *args):
        argv = sys.argv
        sys.argv = ["cairn export_example", "--project", "alpha",
                    "--dest", str(self.dest)] + list(args)
        try:
            return export_example.main()
        finally:
            sys.argv = argv

    def test_a_mistyped_exclusion_is_refused_rather_than_ignored(self):
        """The dangerous failure: a typo that silently excludes nothing, so the
        node you meant to hold back gets published."""
        write("2026-08-02-alpha-one.md", node_text(
            "2026-08-02-alpha-one", project="alpha", created="2026-08-02"))
        self.assertEqual(self.run_export("--exclude", "2026-08-02-alpha-typo"), 2)

    def test_excluding_a_node_from_another_project_is_refused(self):
        write("2026-08-02-alpha-one.md", node_text(
            "2026-08-02-alpha-one", project="alpha", created="2026-08-02"))
        write("2026-08-02-beta-one.md", node_text(
            "2026-08-02-beta-one", project="beta", created="2026-08-02"))
        self.assertEqual(self.run_export("--exclude", "2026-08-02-beta-one"), 2)

    def test_cannot_exclude_a_node_a_kept_node_calls_parent(self):
        """A dangling `parents` edge is a validation error, so the export would
        be a graph that cannot even load."""
        write("2026-08-02-alpha-root.md", node_text(
            "2026-08-02-alpha-root", project="alpha", created="2026-08-02"))
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03",
            parents="[2026-08-02-alpha-root]"))
        self.assertEqual(
            self.run_export("--exclude", "2026-08-02-alpha-root",
                            "--acknowledge-review"), 2)
        self.assertFalse((self.dest / "nodes").exists())

    def test_cannot_exclude_the_target_of_a_typed_relation(self):
        """Dropping a typed edge drops a claim — the reason `relates` exists."""
        write("2026-08-02-alpha-root.md", node_text(
            "2026-08-02-alpha-root", project="alpha", created="2026-08-02"))
        write("2026-08-03-alpha-child.md", node_text(
            "2026-08-03-alpha-child", project="alpha", created="2026-08-03"
            ).replace("parents: []",
                      "parents: []\nrelates:\n  - {to: 2026-08-02-alpha-root, "
                      "type: contradicts, note: opposite sign}"))
        self.assertEqual(
            self.run_export("--exclude", "2026-08-02-alpha-root",
                            "--acknowledge-review"), 2)

    def test_an_excluded_node_is_named_in_the_readme_not_silently_dropped(self):
        """A missing node and a hidden node must not look the same — the same
        rule the `[[link]]` stubs exist for."""
        write("2026-08-02-alpha-one.md", node_text(
            "2026-08-02-alpha-one", project="alpha", created="2026-08-02"))
        write("2026-08-03-alpha-secret.md", node_text(
            "2026-08-03-alpha-secret", project="alpha", created="2026-08-03"))
        self.assertEqual(
            self.run_export("--exclude", "2026-08-03-alpha-secret",
                            "--acknowledge-review"), 0)

        self.assertTrue((self.dest / "nodes" / "2026-08-02-alpha-one.md").exists())
        self.assertFalse((self.dest / "nodes" / "2026-08-03-alpha-secret.md").exists())

        readme = (self.dest / "README.md").read_text()
        self.assertIn("withheld", readme)
        self.assertIn("2026-08-03-alpha-secret", readme)

    def test_a_prose_link_to_an_excluded_node_becomes_a_visible_stub(self):
        write("2026-08-02-alpha-secret.md", node_text(
            "2026-08-02-alpha-secret", project="alpha", created="2026-08-02"))
        write("2026-08-03-alpha-one.md", node_text(
            "2026-08-03-alpha-one", project="alpha", created="2026-08-03")
            + "\nSee [[2026-08-02-alpha-secret]] for why.\n")
        self.assertEqual(
            self.run_export("--exclude", "2026-08-02-alpha-secret",
                            "--acknowledge-review"), 0)
        body = (self.dest / "nodes" / "2026-08-03-alpha-one.md").read_text()
        self.assertNotIn("[[2026-08-02-alpha-secret]]", body)
        self.assertIn("not published here", body)


class OnboardingFixes(unittest.TestCase):
    """Things a collaborator with their own graph, outside the tool clone, hits first."""

    TOOL = Path(__file__).resolve().parent.parent

    def graph(self, committed=False):
        """A throwaway git graph that is NOT the tool repo."""
        import subprocess
        root = Path(tempfile.mkdtemp(prefix="cairn-graph-"))
        self.addCleanup(shutil.rmtree, root, True)
        for sub in ("nodes", "papers"):
            (root / sub).mkdir()
        node_id = "2026-08-02-demo-first"
        (root / "nodes" / f"{node_id}.md").write_text(
            node_text(node_id, "direction", "open", project="demo").lstrip("\n"))
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
        if committed:
            subprocess.run(["git", "-C", str(root), "add", "nodes"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "first",
                            "--no-verify"], check=True, env=env)
        return root, node_id

    def cairn(self, root, *args):
        import subprocess
        return subprocess.run(
            [str(self.TOOL / "bin" / "cairn"), *args], capture_output=True, text=True,
            env=dict(os.environ, CAIRN_ROOT=str(root)), cwd=str(root))

    # -- sync ---------------------------------------------------------------

    def test_sync_regenerates_build_for_a_graph_outside_the_tool(self):
        import importlib
        root, _ = self.graph()
        old = os.environ.get("CAIRN_ROOT")
        os.environ["CAIRN_ROOT"] = str(root)
        try:
            import sync
            importlib.reload(sync)
            self.assertEqual(sync.REPO_ROOT, root)
            self.assertTrue((sync.TOOL_ROOT / "bin" / "cairn").exists())
            self.assertTrue(sync.regenerate())
        finally:
            if old is None:
                del os.environ["CAIRN_ROOT"]
            else:
                os.environ["CAIRN_ROOT"] = old
        self.assertTrue((root / "build" / "graph.html").exists())

    def test_sync_counts_node_files_not_directories(self):
        import importlib
        root, _ = self.graph()
        second = "2026-08-03-demo-second"
        (root / "nodes" / f"{second}.md").write_text(
            node_text(second, "direction", "open", project="demo", created="2026-08-03").lstrip("\n"))
        old = os.environ.get("CAIRN_ROOT")
        os.environ["CAIRN_ROOT"] = str(root)
        try:
            import sync
            importlib.reload(sync)
            changed, new = sync.unreviewed()
        finally:
            if old is None:
                del os.environ["CAIRN_ROOT"]
            else:
                os.environ["CAIRN_ROOT"] = old
        self.assertEqual(new, [f"nodes/2026-08-02-demo-first.md", f"nodes/{second}.md"])

    # -- note ---------------------------------------------------------------

    def test_note_on_an_untracked_node_says_what_to_do_and_exits_nonzero(self):
        root, node_id = self.graph(committed=False)
        result = self.cairn(root, "note", node_id, "looks odd")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not committed yet", result.stdout)
        self.assertIn(f"git add nodes/{node_id}.md", result.stdout)
        self.assertNotIn("pathspec", result.stdout + result.stderr)
        # capture wins: the note is on disk regardless
        self.assertIn("looks odd", (root / "nodes" / f"{node_id}.md").read_text())

    def test_note_on_a_committed_node_commits_and_exits_zero(self):
        root, node_id = self.graph(committed=True)
        result = self.cairn(root, "note", node_id, "looks odd")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("committed", result.stdout)

    # -- new_node dates -----------------------------------------------------

    def args(self, type_, **kw):
        import argparse
        base = dict(type=type_, title="A probe", project="prekd", status=None, note="",
                    date="2026-08-03", slug=None, parent=[], ref=[], repo=None,
                    commit=None, host=None, artifact=[], origin=None, venue=None,
                    url=None, due=None, source=None, when=None, new_project=True)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_an_invalid_due_is_refused_on_create(self):
        with self.assertRaises(SystemExit) as caught:
            new_node.build(self.args("task", due="next-friday"))
        self.assertIn("--due: not an ISO date: next-friday", str(caught.exception))

    def test_a_valid_due_is_stored_as_a_date(self):
        node = new_node.build(self.args("task", due="2026-10-30"))
        self.assertEqual(node.meta["due"], dt.date(2026, 10, 30))

    def test_when_sets_a_milestones_date_field(self):
        clear()
        node = new_node.build(self.args("milestone", when="2026-11-15"))
        node.write()
        self.assertEqual(node.meta["date"], dt.date(2026, 11, 15))
        self.assertNotIn("due", node.meta)
        self.assertEqual(errors(), [], error_text())

    def test_an_invalid_when_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            new_node.build(self.args("milestone", when="soon"))
        self.assertIn("--when: not an ISO date", str(caught.exception))

    def test_due_on_a_milestone_is_refused_and_names_when(self):
        with self.assertRaises(SystemExit) as caught:
            new_node.build(self.args("milestone", due="2026-11-15"))
        self.assertIn("--when", str(caught.exception))

    def test_when_on_a_task_is_refused_and_names_due(self):
        with self.assertRaises(SystemExit) as caught:
            new_node.build(self.args("task", when="2026-11-15"))
        self.assertIn("--due", str(caught.exception))

    def test_due_on_an_experiment_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            new_node.build(self.args("experiment", due="2026-11-15"))
        self.assertIn("no 'due' field", str(caught.exception))

    # -- --update without a status ------------------------------------------

    def upd(self, node_id, **kw):
        import argparse
        base = dict(update=node_id, status=None, note="", date=None, relate=[],
                    parent=[], artifact=[], commit=None, host=None, url=None,
                    due=None, when=None)
        base.update(kw)
        return new_node.update(argparse.Namespace(**base))

    def two_tasks(self):
        clear()
        write("2026-08-02-prekd-a.md", node_text(
            "2026-08-02-prekd-a", "task", "todo", extra="due: 2026-09-01\n"))
        write("2026-08-03-prekd-b.md", node_text(
            "2026-08-03-prekd-b", "task", "todo", created="2026-08-03"))

    def test_a_due_date_can_move_without_a_status_change(self):
        self.two_tasks()
        node = self.upd("2026-08-02-prekd-a", due="2026-10-01")
        self.assertEqual(node.meta["due"], dt.date(2026, 10, 1))
        self.assertEqual(len(node.history), 1)
        self.assertEqual(node.meta["updated"], dt.date(2026, 8, 2))

    def test_a_milestones_date_can_move_without_a_status_change(self):
        clear()
        write("2026-08-02-prekd-m.md", node_text(
            "2026-08-02-prekd-m", "milestone", "planned", extra="date: 2026-09-01\n"))
        node = self.upd("2026-08-02-prekd-m", when="2026-12-01")
        self.assertEqual(node.meta["date"], dt.date(2026, 12, 1))
        self.assertEqual(len(node.history), 1)

    def test_update_with_nothing_to_do_still_refuses(self):
        self.two_tasks()
        with self.assertRaises(SystemExit):
            self.upd("2026-08-02-prekd-a")

    def test_update_appends_a_parent_without_history(self):
        self.two_tasks()
        node = self.upd("2026-08-03-prekd-b", parent=["2026-08-02-prekd-a"])
        self.assertEqual(node.meta["parents"], ["2026-08-02-prekd-a"])
        self.assertEqual(len(node.history), 1)
        node.write()
        self.assertEqual(errors(), [], error_text())

    def test_update_refuses_a_missing_parent(self):
        self.two_tasks()
        with self.assertRaises(SystemExit) as caught:
            self.upd("2026-08-03-prekd-b", parent=["2026-01-01-prekd-ghost"])
        self.assertIn("no such node", str(caught.exception))

    def test_update_refuses_a_parent_that_closes_a_loop(self):
        self.two_tasks()
        self.upd("2026-08-03-prekd-b", parent=["2026-08-02-prekd-a"]).write()
        with self.assertRaises(SystemExit) as caught:
            self.upd("2026-08-02-prekd-a", parent=["2026-08-03-prekd-b"])
        self.assertIn("loop", str(caught.exception))


class Discard(unittest.TestCase):
    """`cairn discard` deletes only what git has never seen."""

    ROOT = Path(__file__).resolve().parent.parent
    TRACKED = "2026-08-01-demo-kept"
    DRAFT = "2026-08-02-demo-draft"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cairn-discard-"))
        (self.tmp / "nodes").mkdir()
        self.git("init", "-q", ".")
        self.git("config", "user.email", "jlaw@example.gov")
        self.git("config", "user.name", "Jeff Law")
        self.node(self.TRACKED)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "seed")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", str(self.tmp), *args],
                              capture_output=True, text=True, timeout=30)

    def node(self, name, **kw):
        path = self.tmp / "nodes" / f"{name}.md"
        path.write_text(node_text(name, project="demo", **kw).lstrip("\n"))
        return path

    def discard(self, *args):
        import subprocess
        return subprocess.run([str(self.ROOT / "bin" / "cairn"), "discard", *args],
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, "CAIRN_ROOT": str(self.tmp)})

    def test_an_untracked_draft_is_deleted_with_its_untracked_asset(self):
        path = self.node(self.DRAFT)
        (self.tmp / "assets").mkdir()
        asset = self.tmp / "assets" / f"{self.DRAFT}.png"
        asset.write_bytes(b"x")
        done = self.discard(self.DRAFT)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(path.exists())
        self.assertFalse(asset.exists())
        self.assertIn(f"nodes/{self.DRAFT}.md", done.stdout)

    def test_a_tracked_node_is_refused(self):
        done = self.discard(self.TRACKED)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("tracked", done.stderr)
        self.assertTrue((self.tmp / "nodes" / f"{self.TRACKED}.md").exists())

    def test_a_modified_tracked_node_is_refused(self):
        path = self.tmp / "nodes" / f"{self.TRACKED}.md"
        path.write_text(path.read_text() + "\nmore\n")
        self.assertNotEqual(self.discard(self.TRACKED).returncode, 0)
        self.assertTrue(path.exists())

    def test_a_draft_that_is_someones_parent_is_refused_and_named(self):
        path = self.node(self.DRAFT)
        self.node("2026-08-03-demo-child", parents=f"[{self.DRAFT}]")
        done = self.discard(self.DRAFT)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("2026-08-03-demo-child (parent)", done.stderr)
        self.assertTrue(path.exists())

    def test_a_draft_listed_in_relates_is_refused(self):
        path = self.node(self.DRAFT)
        self.node("2026-08-03-demo-other",
                  extra=f"relates:\n  - {{to: {self.DRAFT}, type: supports, note: why}}\n")
        done = self.discard(self.DRAFT)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("(relates)", done.stderr)
        self.assertTrue(path.exists())

    def test_anything_that_is_not_a_bare_node_id_is_refused(self):
        outside = self.tmp / "keep.md"
        outside.write_text("x")
        for bad in ("../keep", "nodes/" + self.DRAFT, self.DRAFT + ".md", "demo-draft"):
            self.node(self.DRAFT)
            done = self.discard(bad)
            self.assertNotEqual(done.returncode, 0, bad)
            self.assertIn("bare node id", done.stderr)
        self.assertTrue(outside.exists())
        self.assertTrue((self.tmp / "nodes" / f"{self.DRAFT}.md").exists())

    def test_a_graph_that_is_not_a_git_repo_is_refused(self):
        plain = Path(tempfile.mkdtemp(prefix="cairn-discard-plain-"))
        try:
            (plain / "nodes").mkdir()
            path = plain / "nodes" / f"{self.DRAFT}.md"
            path.write_text(node_text(self.DRAFT, project="demo").lstrip("\n"))
            import subprocess
            done = subprocess.run([str(self.ROOT / "bin" / "cairn"), "discard", self.DRAFT],
                                  capture_output=True, text=True, timeout=60,
                                  env={**os.environ, "CAIRN_ROOT": str(plain),
                                       "GIT_CEILING_DIRECTORIES": str(plain.parent)})
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("not a git repo", done.stderr)
            self.assertTrue(path.exists())
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_dry_run_prints_and_removes_nothing(self):
        path = self.node(self.DRAFT)
        done = self.discard(self.DRAFT, "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f"would remove nodes/{self.DRAFT}.md", done.stdout)
        self.assertTrue(path.exists())


class CommitPolicy(unittest.TestCase):
    """The commit policy is one line in the graph's CLAUDE.md — not a dotfile,
    not a config. The failure to prevent is a policy that silently reads as the
    wrong mode: unset, malformed or mentioned-in-passing must all mean `ask`."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        sys.path.insert(0, str(self.ROOT / "scripts"))
        import policy
        self.policy = policy
        self.graph = Path(tempfile.mkdtemp(prefix="cairn-policy-"))
        (self.graph / "nodes").mkdir()
        self.addCleanup(shutil.rmtree, self.graph, ignore_errors=True)

    def test_default_is_ask_when_nothing_is_stated(self):
        self.assertEqual(self.policy.read_commit_mode(self.graph), "ask")
        (self.graph / "CLAUDE.md").write_text("# A graph\n\nNo policy here.\n")
        self.assertEqual(self.policy.read_commit_mode(self.graph), "ask")

    def test_a_mention_in_prose_is_not_the_setting(self):
        (self.graph / "CLAUDE.md").write_text(
            "# A graph\n\nSwitch with `commit_mode: auto` if you like.\n")
        self.assertEqual(self.policy.read_commit_mode(self.graph), "ask")

    def test_write_appends_a_section_then_replaces_in_place(self):
        (self.graph / "CLAUDE.md").write_text("# A graph\n\nKeep this.\n")
        self.policy.write_commit_mode("auto", self.graph)
        text = (self.graph / "CLAUDE.md").read_text()
        self.assertIn("Keep this.", text)
        self.assertIn("## Commit policy", text)
        self.assertEqual(self.policy.read_commit_mode(self.graph), "auto")
        self.policy.write_commit_mode("ask", self.graph)
        text2 = (self.graph / "CLAUDE.md").read_text()
        self.assertEqual(text2.count("## Commit policy"), 1)
        self.assertEqual(text2.count("commit_mode:"), 1)
        self.assertEqual(self.policy.read_commit_mode(self.graph), "ask")
        # A toggle is a one-word diff: the blank line after the setting survives.
        self.assertEqual(text2.replace("commit_mode: ask", "commit_mode: auto"), text)
        self.assertIn("commit_mode: ask\n\n", text2)

    def test_a_non_utf8_claude_md_reads_as_ask_not_a_traceback(self):
        (self.graph / "CLAUDE.md").write_bytes(b"# A graph\n\xff\xfe\n")
        self.assertEqual(self.policy.read_commit_mode(self.graph), "ask")

    def test_malformed_value_is_refused(self):
        with self.assertRaises(ValueError):
            self.policy.write_commit_mode("yolo", self.graph)

    def test_the_command_reads_and_sets_it(self):
        import subprocess
        env = {**os.environ, "CAIRN_ROOT": str(self.graph)}
        cairn = str(self.ROOT / "bin" / "cairn")
        out = subprocess.run([cairn, "policy", "--quiet"], capture_output=True, text=True, env=env)
        self.assertEqual(out.stdout.strip(), "ask")
        subprocess.run([cairn, "policy", "auto"], capture_output=True, text=True, env=env)
        out = subprocess.run([cairn, "policy", "--quiet"], capture_output=True, text=True, env=env)
        self.assertEqual(out.stdout.strip(), "auto")

    def test_the_session_hook_states_the_policy(self):
        """An agent in some other repo learns the policy from the session-start
        context, not from a file it would have to go and read."""
        import subprocess
        self.policy.write_commit_mode("auto", self.graph)
        out = subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "session_hook", "--dry-run"],
            capture_output=True, text=True, timeout=90, stdin=subprocess.PIPE,
            env={**os.environ, "CAIRN_ROOT": str(self.graph)})
        self.assertIn("Commit policy is `auto`", out.stdout)
        self.assertNotIn("Jeff", out.stdout)

    def test_init_writes_the_policy_and_refuses_a_nested_graph(self):
        import subprocess
        cairn = str(self.ROOT / "bin" / "cairn")
        fresh = self.graph / "fresh"
        subprocess.run(["git", "init", "-q", str(self.graph)], check=True)
        # self.graph is now a git repo, so a graph inside it is nested.
        refused = subprocess.run([cairn, "init", str(fresh), "--commit-mode", "auto"],
                                 capture_output=True, text=True)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn("inside the git repo", refused.stderr)
        self.assertFalse(fresh.exists())
        # Two missing levels deep is still nested.
        deep = subprocess.run([cairn, "init", str(self.graph / "a" / "b" / "graph")],
                              capture_output=True, text=True)
        self.assertEqual(deep.returncode, 2, deep.stderr)
        self.assertFalse((self.graph / "a").exists())
        allowed = subprocess.run([cairn, "init", str(fresh), "--commit-mode", "auto",
                                  "--allow-nested", "--no-git"],
                                 capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(self.policy.read_commit_mode(fresh), "auto")


class InstallContextScope(unittest.TestCase):
    """`--project` puts the same three installs inside one project and touches
    nothing machine-wide. Scope is where the files landed, not a setting."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cairn-cfg-"))
        self.project = Path(tempfile.mkdtemp(prefix="cairn-proj-"))
        for d in (self.home, self.project):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)

    def run_install(self, *args):
        import subprocess
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "install_context", *args],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "CAIRN_ROOT": str(FIXTURE)})

    def test_project_scope_lands_in_the_project_and_nowhere_else(self):
        import json
        (self.project / "CLAUDE.md").write_text("# Project\n\nTheirs.\n")
        result = self.run_install("--project", str(self.project), "--apply")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        # The shared CLAUDE.md is left alone; the block (with this machine's
        # absolute paths) goes to CLAUDE.local.md, which git convention ignores.
        self.assertEqual((self.project / "CLAUDE.md").read_text(), "# Project\n\nTheirs.\n")
        self.assertIn("cairn:begin", (self.project / "CLAUDE.local.md").read_text())
        local = self.project / ".claude" / "settings.local.json"
        self.assertTrue(local.exists(), "hooks belong in settings.local.json, not settings.json")
        self.assertIn("session_hook", json.dumps(json.loads(local.read_text())))
        self.assertFalse((self.project / ".claude" / "settings.json").exists())
        self.assertTrue((self.project / ".claude" / "commands" / "log.md").is_symlink())
        # Machine-wide files are untouched.
        self.assertFalse((self.home / "settings.json").exists())
        self.assertFalse((self.home / "CLAUDE.md").exists())
        self.assertFalse((self.home / "commands").exists())

    def test_the_tool_itself_is_refused_as_a_project(self):
        """Pointing --project at the Cairn clone would make each command's link
        target the source file itself: unlink it, and the command is gone."""
        result = self.run_install("--project", str(self.ROOT), "--apply")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("tool itself", result.stderr)
        for cmd in (self.ROOT / ".claude" / "commands").glob("*.md"):
            self.assertFalse(cmd.is_symlink(), f"{cmd.name} was turned into a link")
            self.assertTrue(cmd.read_text().startswith("---"))

    def test_project_scope_removes_cleanly(self):
        (self.project / "CLAUDE.local.md").write_text("# Local\n\nTheirs.\n")
        self.run_install("--project", str(self.project), "--apply")
        self.run_install("--project", str(self.project), "--remove", "--apply")
        self.assertEqual((self.project / "CLAUDE.local.md").read_text(), "# Local\n\nTheirs.\n")
        local = self.project / ".claude" / "settings.local.json"
        self.assertNotIn("session_hook", local.read_text() if local.exists() else "")

    def test_a_missing_project_directory_is_an_error(self):
        result = self.run_install("--project", str(self.project / "nope"))
        self.assertEqual(result.returncode, 2)


class Onboard(unittest.TestCase):
    """Onboarding asks three questions whose answers become facts on disk, and
    it must be drivable without a terminal — the first run on a cluster login
    node is often through an agent."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="cairn-onboard-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = self.base / "cfg"
        self.project = self.base / "proj"
        self.project.mkdir()

    def run_onboard(self, *args, env_extra=None):
        import subprocess
        env = {k: v for k, v in os.environ.items() if k not in ("CAIRN_ROOT", "CAIRN_PATH")}
        env["CLAUDE_CONFIG_DIR"] = str(self.home)
        env.update(env_extra or {})
        # Never let a test reach a real OpenViking server: every run says no.
        if "--openviking" not in args:
            args = (*args, "--openviking", "no")
        return subprocess.run(
            [str(self.ROOT / "bin" / "cairn"), "onboard", *args],
            capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL, env=env)

    def test_without_a_terminal_it_asks_for_flags_instead_of_hanging(self):
        result = self.run_onboard("--graph", str(self.base / "g"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--yes", result.stderr)
        self.assertFalse((self.base / "g").exists())

    def test_flags_answer_every_question_and_the_facts_land_on_disk(self):
        import json
        sys.path.insert(0, str(self.ROOT / "scripts"))
        import policy
        graph = self.base / "g"
        result = self.run_onboard("--graph", str(graph), "--commit-mode", "auto",
                                  "--scope", f"project={self.project}", "--openviking", "no",
                                  "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((graph / "nodes").is_dir())
        self.assertEqual(policy.read_commit_mode(graph), "auto")
        local = self.project / ".claude" / "settings.local.json"
        self.assertIn("session_hook", json.dumps(json.loads(local.read_text())))
        self.assertFalse((self.home / "settings.json").exists())
        # It explains where nodes live rather than asking.
        self.assertIn("Nodes stay in the one graph", result.stdout)
        self.assertIn("cairn doctor", result.stdout)

    def test_machine_scope_uses_the_config_dir(self):
        graph = self.base / "g"
        result = self.run_onboard("--graph", str(graph), "--scope", "machine", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("session_hook", (self.home / "settings.json").read_text())
        import policy
        self.assertEqual(policy.read_commit_mode(graph), "ask")

    def test_an_existing_graph_is_kept_and_its_policy_switched(self):
        import subprocess, policy
        graph = self.base / "g"
        subprocess.run([str(self.ROOT / "bin" / "cairn"), "init", str(graph)], check=True,
                       capture_output=True)
        (graph / "nodes" / "keep.md").write_text("x")
        result = self.run_onboard("--graph", str(graph), "--commit-mode", "auto",
                                  "--scope", f"project={self.project}", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((graph / "nodes" / "keep.md").exists())
        self.assertEqual(policy.read_commit_mode(graph), "auto")


class OpenViking(unittest.TestCase):
    """OpenViking is optional and arm's-length: no import, a dry run by default,
    and `ov` missing is a sentence, never a traceback."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="cairn-ov-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.graph = self.base / "graph"
        (self.graph / "nodes").mkdir(parents=True)
        (self.graph / "nodes" / "2026-08-02-prekd-a.md").write_text("---\nid: x\n---\n")
        (self.graph / "build").mkdir()
        (self.graph / "build" / "graph.md").write_text("graph\n")
        self.fakebin = self.base / "bin"
        self.fakebin.mkdir()
        self.log = self.base / "ov.log"
        fake = self.fakebin / "ov"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> '" + str(self.log) + "'\n"
                        "[ \"$1\" = status ] && echo 'server ok'\nexit 0\n")
        fake.chmod(0o755)

    def run_ov(self, *args, with_ov: bool):
        import subprocess
        # Without `ov`: a PATH holding only the system tools the dispatcher needs
        # (dirname, sh) and a real `ov`-free directory — never an empty PATH,
        # which breaks the dispatcher itself and tests nothing about this script.
        system = [d for d in os.environ.get("PATH", "").split(os.pathsep)
                  if d.startswith(("/usr/bin", "/bin", "/usr/local/bin"))
                  and not (Path(d) / "ov").exists()]
        path = os.pathsep.join(([str(self.fakebin)] if with_ov else []) + system)
        env = {**os.environ, "CAIRN_ROOT": str(self.graph), "PATH": path}
        return subprocess.run([str(self.ROOT / "bin" / "cairn"), "openviking", *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_it_does_not_import_openviking_or_lib(self):
        text = (self.ROOT / "scripts" / "openviking.py").read_text()
        self.assertNotRegex(text, r"(?m)^\s*(import|from)\s+(openviking|lib)\b")

    def test_missing_ov_is_a_sentence(self):
        status = self.run_ov("status", with_ov=False)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("optional", status.stdout)
        push = self.run_ov("push", "--apply", with_ov=False)
        self.assertEqual(push.returncode, 1)
        self.assertIn("optional", push.stderr)
        self.assertNotIn("Traceback", push.stderr)

    def test_dry_run_runs_nothing(self):
        result = self.run_ov("push", with_ov=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertFalse(self.log.exists())

    def test_apply_registers_what_exists_and_skips_what_does_not(self):
        result = self.run_ov("push", "--apply", with_ov=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = self.log.read_text().splitlines()
        self.assertEqual(len(calls), 2, calls)          # nodes + graph.md; report.md absent
        self.assertIn("--to viking://resources/cairn/graph/nodes", calls[0])
        self.assertIn("add-resource", calls[1])
        self.assertIn("report.md", result.stdout)
        self.assertIn("skip", result.stdout)


if __name__ == "__main__":
    try:
        result = unittest.main(exit=False, verbosity=2).result
    finally:
        shutil.rmtree(FIXTURE, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
