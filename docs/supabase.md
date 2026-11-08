# A read-only mirror in Supabase

`cairn export_supabase` copies the published part of the graph into a Supabase
(Postgres) project, so agents that cannot reach the machine holding the graph
can still read it — through Crello's MCP server, from a phone, or from an agent
working in another repo.

It exists for one situation: **nothing may reach in to the machine where the
graph lives** — remote control of the HPC or the laptop is not allowed — but
you still want to ask an agent, from anywhere, "how is this going, and did we
already try that?". The answer to "how does a cloud agent see the graph" is
then not a tunnel into the machine but a copy kept outside it, written by
something that already leaves: a push to GitHub.

```sh
cairn export_supabase                   # dry run: counts, what is held back, hidden edges
cairn export_supabase --dump out.json   # the exact payload, to read before sending
cairn export_supabase --apply           # send it (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
```

## The rule

**Git stays the source of truth; Supabase holds a projection of it.** That is
the line [[2026-08-05-cairn-webapp]] drew, and it is what keeps two copies from
disagreeing. The exporter only writes. Nothing reads Supabase back into the
graph, and every export overwrites what the previous one wrote.

Writes from Crello — a note left on a node from a phone, a status change — are
a different path when they arrive: a queue of *requests* that an agent pulls at
the start of a session and carries out through `bin/cairn`, so validation,
`check_project` and the commit policy still apply. They never become rows that
get merged.

## What is published

Only projects listed in `published-projects.txt` at the graph root:

```
# one project key per line; `*` publishes every project
cairn
prekd
```

No file, or an empty one, publishes nothing — and an `--apply` with nothing
published *empties* the mirror, so deleting the file is how you take everything
down. An unknown key is reported with its near-matches. The file's git history
is the record of what was shared and when.

Inside a published project:

| table | holds |
|---|---|
| `cairn_nodes` | each committed node: frontmatter (`meta`), `history`, `body`, plus git-derived `author` and `review_state`; full-text index over title and body |
| `cairn_edges` | lineage, typed relations, `[[mentions]]` |
| `cairn_views` | `standup`, `digest:7d`, `report` — overall and per project — and `coverage` as data |
| `cairn_exports` | one row per finished run: graph commit, projects, counts |

**A hidden edge is kept, not dropped.** An edge into an unpublished project is a
row with `target_state = 'hidden'` and `target = null`. Without it, a missing
edge and a hidden one would look the same, and absence could no longer be
trusted to mean "no connection".

**A hidden node's id is redacted everywhere** — wikilinks, bare ids in prose,
history notes, relation notes, the rendered views — because an id is a date and
a slug that says what the work is. `parents` and `relates` are left out of
`meta` for the same reason; they live in `cairn_edges`, which knows how to hide
a target. Prose that names another project in words is *not* scrubbed: this is a
view for whoever can read the Supabase project, the same audience as
`cairn export`. Publishing to the world is `export_example`'s job.

**Only committed state crosses.** `--apply` refuses while `nodes/` has
uncommitted changes, and drafts git has never seen are left out and listed. A
node nobody has read should not reach other agents before it reaches git.

**The views are Cairn's own.** `standup`'s ranking, `digest`'s filters and
`report`'s coverage table are rendered by the same code as the terminal and
stored as markdown, so an MCP tool serves them as they are, without
reimplementing them in SQL where they would drift. `coverage` is also stored as
data — total nodes, share recorded within a week of the work — because it is the
number an agent needs before it may read a missing node as "not tried".

## Setting it up

1. **Create the tables.** Run [`supabase.sql`](supabase.sql) in the project's
   SQL editor. Row-level security is on with no policies, so the anon key reads
   nothing; only the service role can. Add read policies, keyed on `project`,
   once Crello has accounts and board membership.
2. **List what to publish** in `published-projects.txt` in the graph repo, and
   commit it.
3. **Add two repository secrets** to the graph repo on GitHub:
   `SUPABASE_URL` (`https://<ref>.supabase.co`) and `SUPABASE_SERVICE_ROLE_KEY`.
   If this tool repo is private, also `CAIRN_TOOL_TOKEN`: a fine-grained token
   with read access to it, so the workflow can check it out.
4. **Add the workflow** below to the graph repo as
   `.github/workflows/supabase-mirror.yml`. Every push to `main` then refreshes
   the mirror. The machine you work on talks to GitHub, as it already does, and
   to nothing new.

Without the secrets the workflow runs as a dry run and says so, so adding the
file first is harmless.

```yaml
name: Supabase mirror

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

# One export at a time, in push order. A cancelled half-export is repaired by the
# next one, but there is no reason to cause it.
concurrency:
  group: supabase-mirror
  cancel-in-progress: false

jobs:
  mirror:
    runs-on: ubuntu-latest
    env:
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
    steps:
      - uses: actions/checkout@v4
        with:
          path: graph
          fetch-depth: 0          # authorship, review state and coverage come from history

      - uses: actions/checkout@v4
        with:
          repository: jlaw9/cairn
          path: tool
          token: ${{ secrets.CAIRN_TOOL_TOKEN || github.token }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install pyyaml

      - name: Export
        env:
          CAIRN_ROOT: ${{ github.workspace }}/graph
        run: |
          if [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_SERVICE_ROLE_KEY" ]; then
            tool/bin/cairn export_supabase --graph "${GITHUB_REPOSITORY#*/}" --apply
          else
            echo "::notice::SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — dry run only"
            tool/bin/cairn export_supabase --graph "${GITHUB_REPOSITORY#*/}"
          fi
```

## Not yet verified

The payload, the redaction and the request sequence are tested against a stub
HTTP server, and a dry run over a real graph has been checked for leaked ids.
**It has not been run against a live Supabase project.** The requests follow
PostgREST's documented upsert (`on_conflict` plus
`Prefer: resolution=merge-duplicates`) and filtered delete; the first real run
is the test of that.

## What comes next

In order, each useful on its own:

1. **Read-only MCP tools in Crello** over these tables — `search` on `fts`,
   `get_node` with its edges, `standup`/`digest`/`report` straight from
   `cairn_views`, and `coverage` returned beside any "was this tried?" answer.
2. **A request queue** in Crello (note, status, capture), pulled by `cairn sync`
   at session start and applied through `bin/cairn`, each request carrying the
   node's last history entry so a stale one is refused, not applied.
