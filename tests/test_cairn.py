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
        for cmd in ("new_node", "validate", "build", "add_paper", "mine_sessions", "doctor"):
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


if __name__ == "__main__":
    try:
        result = unittest.main(exit=False, verbosity=2).result
    finally:
        shutil.rmtree(FIXTURE, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
