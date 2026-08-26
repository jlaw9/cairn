# Tasks as GitHub Issues

`cairn sync_issues` mirrors open `task` nodes into GitHub Issues. This page is the
part that isn't obvious from `--help`: which half of the idea works today, which
half is unverified, and why the answer differs per repo.

**Only `task` nodes, and only outward.** A task has a `due`, an owner and no
scientific claim, so an issue is a faithful container for one. An `experiment` is
not: to GitHub an issue is open or closed, while the whole point of this graph is
that `dead` is not `closed`, `parked` is neither, and the status *event log* is
what makes replay work. Mirroring an experiment would discard the part worth
keeping. The graph stays the source of truth and every issue body says so.

## The github.com path — this works

```sh
gh auth login --hostname github.com

cairn sync_issues                                   # dry run; writes nothing
cairn sync_issues --only <node-id> -v               # inspect the exact body first
cairn sync_issues --only <node-id> --apply          # create exactly one
```

Dry run is the default because this writes to a service other people can see, and
a mistake there is not fixable by editing a file. `--only` exists so the first
thing ever written to a shared tracker is one reviewed issue rather than ten.

Re-running is safe. Each body carries `<!-- cairn-node: <id> -->`, and the tool
reads issues `--state all`, so a second run finds what it already made instead of
duplicating it. The marker is in the body rather than the title because people
edit titles.

The target repo is **derived** from the project's other nodes — an experiment in
the same project already carries `repo` — so nothing is stored per task. A project
whose nodes have no GitHub remote is reported and skipped, never guessed at. That
includes projects recording `repo: host:/path` because they aren't on GitHub at
all, which is a real case here, not a hypothetical.

## Where the loop closes, and where it doesn't

The interesting version of this idea is mentioning an agent on an issue and having
the task move from a phone. That works in **one** repo and not the others, and the
reason is worth knowing before you rely on it:

| issue lives in | the agent sees | can it update the graph? |
|---|---|---|
| the Cairn repo | the graph itself | **yes** — read a node, run `bin/cairn`, open a PR |
| a project repo | that project's checkout | **no** — the graph isn't there |

So in a project repo you get assignment, notification and a phone, but not the
agent round trip. That's a direct consequence of putting issues in per-project
repos, which is the right call for the humans doing the work — the issue sits next
to the code — and it costs the automation. Both halves are real; pick per project.

Closing the loop in a project repo would mean giving that repo's workflow a
checkout of the graph, i.e. a deploy key or token. Possible, not obviously worth
it, and not worth building before the section below is settled.

## Prompts worth testing with

Start read-only in the Cairn repo, which is where it is most likely to work at
all:

> `@claude` Read `nodes/<node-id>.md` and reply in a comment with a short
> checklist of what to gather before starting this. Don't change any files.

Then the one that actually closes the loop:

> `@claude` Mark this started and give it a due date, then open a PR:
> `bin/cairn new_node --update <node-id> --status doing --due YYYY-MM-DD --note "<why>"`
> then `make build`.

That tests four things at once: the trigger fires, the agent can run the tooling,
the pre-commit hook validates its work, and a PR appears.

In a **project** repo, don't ask about the graph — it can't see it. Ask about the
work, which is a fair test of the trigger and useful on its own:

> `@claude` Read `<the report>` and comment with a proposed first batch: what,
> why each one, and which is the intended negative control. Don't change files.

## Enterprise (`github.nrel.gov`) — two separate questions

These get conflated, and they have different answers:

1. **Does `sync_issues` reach an Enterprise host?** Yes. The repo parser keeps the
   hostname and sets `GH_HOST`, so `gh auth login --hostname github.nrel.gov` is
   all it needs. Tested by unit test, not yet against a live instance.
2. **Does the Claude GitHub app work on Enterprise Server?** **Unverified.** It is
   a github.com app. If it isn't available on the internal instance, the agent
   round trip only ever works for Cairn's own repo.

That second question decides most of the value here, because of where the work
lives: as of 2026-08, **35 of the 42 repo-bearing nodes are on `github.nrel.gov`
and 2 are on `github.com`** (Cairn itself). So "no Enterprise support" means the
round trip covers the tooling repo and none of the science.

If it turns out unsupported, the options are a self-hosted runner reacting to
Enterprise webhooks, or accepting that issues buy assignment and notification
without the agent round trip — still most of the value, just not the exciting
part. Either way, `sync_issues` itself is unaffected.

## Don't

- **Don't change a task's status in the issue.** It is a one-way projection and
  the next sync reconciles it. Change the node.
- **Don't mirror `experiment` or `direction` nodes**, however tempting. See the
  top of this page, and `[[2026-08-05-cairn-collaboration]]` for the argument.
