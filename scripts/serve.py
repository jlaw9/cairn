#!/usr/bin/env python3
"""Serve the map on localhost, and let it write back through `bin/cairn`.

    cairn serve                 # http://127.0.0.1:8787/build/graph.html
    cairn serve --port 9000 --open

The gap this fills (2026-08-27-cairn-living-view): the map is a `file://` page,
so a thought you have *while looking at it* — a doubt about a claim, a status
that is plainly wrong now — has to be retyped at a terminal, and a note you never
file is a note that does not exist.

**This is not a second store.** Every write shells out to `bin/cairn`, the same
code path `/log` and the terminal use, so the node file stays the only copy and
`status`/`history` still move together in `lib.Node.set_status`. The server has
no schema of its own and invents no policy: it reports whatever the command
said, including that `cairn note` commits and `new_node --update` does not.

The line, from the node: the view may **create** a node, append a **note**,
propose a **status change**, and **edit** a node's body and a whitelist of its
fields through `cairn edit`. It may never hand-edit frontmatter. There is no
endpoint that writes YAML, and adding one would be the bug.

**`build/graph.html` still works with the server off.** That constraint is the
reason this is an enhancement rather than a dependency — open the file directly
and the panel degrades to composing a command for the clipboard, exactly as
before. The page only offers to save when `/api/health` answers.

Why the page is served rather than left on `file://`: a `file://` page has the
opaque origin `null`, so letting it POST here would mean sending
`Access-Control-Allow-Origin: null`, which any sandboxed iframe on any website
can also claim. Serving the page makes every write same-origin, so this sends no
CORS headers at all and cross-origin writes fail in the browser before they
arrive. Together with a 127.0.0.1 bind and a `Host:` check against DNS
rebinding, that is the whole security model — which is all a localhost writer on
a machine you are already sitting at should need, and it is why there is no
auth to configure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib

#: Where the tool lives, which after the repo split is not where the graph
#: lives. Computed here rather than imported so this file works unchanged in
#: both a single-repo clone and a split one.
TOOL_ROOT = Path(__file__).resolve().parent.parent
CAIRN = TOOL_ROOT / "bin" / "cairn"

#: Top-level directories the page legitimately reaches for. `build/` is the map
#: itself; the panel links `../nodes/<id>.md` for source and `../assets/<name>`
#: for a figure, and both resolve correctly only if the document root is the
#: graph root — which is why `/` redirects to `/build/graph.html` rather than
#: serving the map at `/`.
SERVED = ("build", "nodes", "assets", "papers", "meetings", "inbox")

#: Bind address. Not configurable, and that is the point: the moment this is
#: reachable from another machine it needs auth and a review surface, and that
#: is the webapp (2026-08-05-cairn-webapp), not this.
HOST = "127.0.0.1"

LOCAL_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}

ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")

#: A project key is the first word of every id in that project, forever, so a
#: key with a capital or a space in it is a permanent scar rather than a typo.
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: One write at a time. Two requests shelling to `cairn note` at once would race
#: on `git commit`, and the loser's diagnosis would be a git lock error rather
#: than anything about Cairn.
WRITE_LOCK = threading.Lock()


class Refused(Exception):
    """A request that is wrong in a way worth naming, rather than a 500."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def run_cairn(args: list[str], stdin: str | None = None) -> dict:
    """Shell out to `bin/cairn`, and report exactly what it said.

    List form, never a shell string: a note is arbitrary human text and the
    whole reason this is safe is that it never becomes part of a command line.
    `stdin` is for text too long or too free to be an argument — a node body —
    and it goes over the pipe, never through a temp file in the repo.
    """
    try:
        done = subprocess.run(
            [str(CAIRN), *args], input=stdin,
            capture_output=True, text=True, timeout=180, cwd=str(lib.REPO_ROOT),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f"could not run bin/cairn: {exc}", 500)
    return {
        "ok": done.returncode == 0,
        "cmd": ["cairn", *args],
        "code": done.returncode,
        "out": (done.stdout + done.stderr).strip(),
    }


def want(payload: dict, key: str, pattern: re.Pattern | None = None,
         required: bool = True) -> str:
    value = str(payload.get(key, "") or "").strip()
    if not value:
        if required:
            raise Refused(f"{key} is required")
        return ""
    if pattern and not pattern.match(value):
        raise Refused(f"{key} is not in the expected form: {value!r}")
    # argparse reads a leading dash as a flag, and these all land in positions
    # where that would silently mean something else. Refuse rather than mangle.
    if value.startswith("-") and key in ("id", "type", "title", "project", "status"):
        raise Refused(f"{key} may not start with '-'")
    return value


def known_node(node_id: str) -> lib.Node:
    nodes, _ = lib.load_nodes()
    node = nodes.get(node_id)
    if node is None:
        raise Refused(f"no such node: {node_id}", 404)
    return node


def do_note(payload: dict) -> dict:
    node_id = want(payload, "id", ID_RE)
    known_node(node_id)
    text = str(payload.get("text", "")).strip()
    if not text:
        raise Refused("an empty note is not a note")
    # `--` so a note that opens with a dash is text, not a flag. This is the one
    # field that is unconstrained human sentence, so it is the one that needs it.
    return run_cairn(["note", node_id, "--", text])


def do_status(payload: dict) -> dict:
    node_id = want(payload, "id", ID_RE)
    node = known_node(node_id)
    status = want(payload, "status")
    spec = lib.TYPES.get(node.type)
    if spec and status not in spec.statuses:
        raise Refused(
            f"'{status}' is not a {node.type} status: "
            f"{', '.join(spec.statuses)}")
    if status == node.status:
        raise Refused(f"{node_id} is already {status}")
    args = ["new_node", "--update", node_id, "--status", status]
    note = str(payload.get("note", "")).strip()
    if note:
        args += ["--note", note]
    return run_cairn(args)


def known_projects() -> set:
    return {n.project for n in lib.load_nodes()[0].values() if n.project}


def do_create(payload: dict) -> dict:
    node_type = want(payload, "type")
    if node_type not in lib.TYPES:
        raise Refused(f"'{node_type}' is not a node type: {', '.join(sorted(lib.TYPES))}")
    title = want(payload, "title")
    project = want(payload, "project")
    args = ["new_node", node_type, title, "--project", project]

    body = str(payload.get("body", "")).strip()
    # The one place in Cairn that prompts for structure, and the reason is
    # pre-registration: a claim written before the result is a hypothesis,
    # written after it, it is a story. Only `experiment` carries that weight, so
    # only `experiment` is refused without one.
    if node_type == "experiment" and not body:
        raise Refused("an experiment needs a claim — that is what makes it a "
                      "pre-registration rather than a title")
    if body:
        args += ["--body", body]
    status = want(payload, "status", required=False)
    if status:
        if status not in lib.TYPES[node_type].statuses:
            raise Refused(f"'{status}' is not a {node_type} status: "
                          f"{', '.join(lib.TYPES[node_type].statuses)}")
        args += ["--status", status]
    for parent in payload.get("parents") or []:
        parent = str(parent).strip()
        if not ID_RE.match(parent):
            raise Refused(f"parent is not a node id: {parent!r}")
        args += ["--parent", parent]
    # `--new-project` only where it means something. A key the graph already has
    # is not new however the form was filled in, and passing the flag anyway
    # would switch off `check_project` — the guard that catches `photpoly` for
    # `photopoly`, which is the one typo that validates cleanly and silently
    # splits a project in two.
    if payload.get("newProject") and project not in known_projects():
        if not PROJECT_RE.match(project):
            raise Refused(
                f"'{project}' will not do as a project key: it is the first word "
                f"of every id in the project, permanently. Lowercase letters, "
                f"digits and dashes.")
        args.append("--new-project")
    return run_cairn(args)


#: The payload keys `edit` takes, so a misspelt one (`relations`, `parent`) is
#: refused instead of silently doing nothing.
EDIT_KEYS = {"action", "id", "set", "clear", "parents", "refs", "artifacts",
             "relates", "body"}


def do_edit(payload: dict) -> dict:
    """Correct a node through `cairn edit` — body and whitelisted fields only.

    Payload, every key optional except `id`:

        {"id": ..., "set": {"title": ..., "due": "2026-11-01"}, "clear": ["due"],
         "parents": {"add": [...], "drop": [...]}, "refs": {...},
         "artifacts": {...},
         "relates": {"add": [{"type": "supports", "id": ..., "note": "why"}],
                     "drop": [{"type": ..., "id": ...}]},
         "body": "the whole markdown body"}

    This checks only shape — ids against ID_RE, field names against edit's own
    whitelist — and leaves every judgement about the node to the command, so
    there is still one answer to what an edit may do.
    """
    import edit
    node_id = want(payload, "id", ID_RE)
    known_node(node_id)
    unknown = sorted(set(payload) - EDIT_KEYS)
    if unknown:
        raise Refused(f"unknown edit key(s): {', '.join(unknown)}; expected "
                      f"{', '.join(sorted(EDIT_KEYS - {'action'}))}")

    def field_name(key) -> str:
        key = str(key)
        if key in edit.FORBIDDEN:
            raise Refused(edit.FORBIDDEN[key])
        if key not in edit.SCALARS:
            raise Refused(f"'{key}' is not a field edit can set: "
                          f"{', '.join(edit.SCALARS)}")
        return key

    def shaped(key, kind):
        value = payload.get(key)
        if value is None:
            return kind()
        if not isinstance(value, kind):
            raise Refused(f"{key} must be a JSON {'object' if kind is dict else 'list'}")
        return value

    def ops(key) -> dict:
        found = shaped(key, dict)
        for verb in sorted(set(found) - {"add", "drop"}):
            raise Refused(f"{key}.{verb}: expected add or drop")
        for verb in ("add", "drop"):
            if not isinstance(found.get(verb) or [], list):
                raise Refused(f"{key}.{verb} must be a list")
        return found

    # `--flag=value`, never `--flag value`: a value that opens with a dash is
    # then still a value, whatever it says.
    args = ["edit", node_id]
    for key, value in shaped("set", dict).items():
        key = field_name(key)
        if value is None or not str(value).strip():
            raise Refused(f"set.{key} is empty — to remove it, list it in clear")
        args.append(f"--{key}={value}")
    for key in shaped("clear", list):
        args.append(f"--clear={field_name(key)}")

    for key, flag in (("parents", "parent"), ("refs", "ref"), ("artifacts", "artifact")):
        found = ops(key)
        for verb, prefix in (("drop", "--drop-"), ("add", "--")):
            for item in found.get(verb) or []:
                item = str(item).strip()
                if key == "parents" and not ID_RE.match(item):
                    raise Refused(f"parent is not a node id: {item!r}")
                args.append(f"{prefix}{flag}={item}")

    relates = ops("relates")
    for verb in ("drop", "add"):
        for rel in relates.get(verb) or []:
            if not isinstance(rel, dict):
                raise Refused("a relation is {type, id, note}")
            kind = str(rel.get("type", "")).strip()
            target = str(rel.get("id", "")).strip()
            if kind not in lib.RELATIONS:
                raise Refused(f"'{kind}' is not a relation: "
                              f"{', '.join(sorted(lib.RELATIONS))}")
            if not ID_RE.match(target):
                raise Refused(f"relation target is not a node id: {target!r}")
            if verb == "drop":
                args.append(f"--unrelate={kind}:{target}")
                continue
            why = " ".join(str(rel.get("note", "") or "").split())
            args.append(f"--relate={kind}:{target}:{why}" if why
                        else f"--relate={kind}:{target}")

    body = payload.get("body")
    if body is not None:
        if not isinstance(body, str):
            raise Refused("body must be a string")
        args.append("--body=-")
    return run_cairn(args, stdin=body)


ACTIONS = {"note": do_note, "status": do_status, "create": do_create,
           "edit": do_edit}


def node_path(out: str) -> str:
    """The node file a command reported writing. Both `note` and `new_node`
    print it as their first line, which is what makes this derivable rather
    than a second place recording which command touched what."""
    return next((l.strip() for l in out.splitlines() if l.strip().endswith(".md")), "")


def committed(out: str) -> bool | None:
    """Did this write land in git, or is it sitting uncommitted?

    Derived by asking git about the file the command printed, rather than by
    hard-coding which commands commit — `note` does, `new_node --update` does
    not, and a table of that here would be a second copy of a fact free to
    drift. It matters to say: an uncommitted node is invisible from the other
    machine, which is the failure the sync habit exists to close.

    None when it cannot be told (no path in the output, or no git here), which
    the panel reports as nothing rather than as a guess.
    """
    rel = node_path(out)
    if not rel:
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(lib.REPO_ROOT), "status", "--porcelain", "--", rel],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return None if done.returncode != 0 else not done.stdout.strip()


def rebuild() -> dict:
    """Regenerate the map so a reload shows the write that just landed.

    Through `cairn build` rather than by importing build_graph, so there is one
    answer to "how is build/ made" and a rebuild here cannot drift from the one
    `sync` runs.
    """
    return run_cairn(["build"])


class Handler(BaseHTTPRequestHandler):
    server_version = "cairn-serve"
    protocol_version = "HTTP/1.1"

    # ---- plumbing -------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:      # noqa: A003
        if self.server.quiet:                            # type: ignore[attr-defined]
            return
        sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # No Access-Control-Allow-Origin, ever. Its absence is what stops a page
        # you are visiting from reading this graph off your own machine.
        self.end_headers()
        self.wfile.write(body)

    def host_is_local(self) -> bool:
        """Reject a request that reached us under someone else's hostname.

        DNS rebinding: a site can point its own name at 127.0.0.1 and then talk
        to whatever is listening. Binding to loopback does not stop that — the
        packets really are from loopback — but the `Host:` header still carries
        the attacker's name, so this does.
        """
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip()
        return host in LOCAL_NAMES or not host

    def origin_is_ours(self) -> bool:
        """Same-origin writes only; no CORS, so this is belt to the browser's braces.

        A `file://` page sends `Origin: null` and is refused here — which is the
        intended degradation, not an oversight. Open the served URL to write.
        A missing Origin is allowed so `curl` and the test suite work; a browser
        cannot forge that.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlparse(origin)
        return (parsed.scheme == "http"
                and (parsed.hostname or "") in LOCAL_NAMES
                and (parsed.port or 80) == self.server.server_address[1])

    # ---- reads ----------------------------------------------------------

    def do_GET(self) -> None:                            # noqa: N802
        if not self.host_is_local():
            return self.send_json({"error": "not a local Host header"}, 403)

        path = unquote(urlparse(self.path).path)
        if path == "/api/health":
            return self.send_json({
                "cairn": "serve",
                "root": str(lib.REPO_ROOT),
                "actions": sorted(ACTIONS),
            })
        if path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/build/graph.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        target = self.resolve(path)
        if target is None:
            return self.send_json({"error": f"not served: {path}"}, 404)
        try:
            body = target.read_bytes()
        except OSError as exc:
            return self.send_json({"error": str(exc)}, 404)
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(target.suffix.lower(),
                                                   "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        # The map is regenerated under the client's feet on every write, so a
        # cached copy is a map that disagrees with the graph.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def resolve(self, path: str) -> Path | None:
        """Map a URL path to a file under the graph root, or refuse.

        Refusing is by allowlisted top-level directory *after* resolving, so
        `..`, a symlink out of the repo, and an absolute path all fail the same
        way rather than each needing its own check.
        """
        parts = [p for p in path.split("/") if p not in ("", ".")]
        if not parts or parts[0] not in SERVED:
            return None
        try:
            target = (lib.REPO_ROOT / Path(*parts)).resolve()
            root = lib.REPO_ROOT.resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            return None
        if target.parts[len(root.parts)] not in SERVED or not target.is_file():
            return None
        return target

    # ---- the one write endpoint ----------------------------------------

    def do_POST(self) -> None:                           # noqa: N802
        if not self.host_is_local():
            return self.send_json({"error": "not a local Host header"}, 403)
        if not self.origin_is_ours():
            return self.send_json(
                {"error": "cross-origin writes are refused — open the served "
                          "page at this port rather than the file:// copy"}, 403)
        if unquote(urlparse(self.path).path) != "/api/write":
            return self.send_json({"error": "the only write endpoint is /api/write"}, 404)
        # Requiring JSON forces a preflight on any cross-origin attempt, which
        # this server never answers. A plain HTML form cannot reach here.
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self.send_json({"error": "Content-Type must be application/json"}, 415)

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 1 << 20:
            return self.send_json({"error": "empty or oversized body"}, 400)

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self.send_json({"error": f"bad JSON: {exc}"}, 400)
        if not isinstance(payload, dict):
            return self.send_json({"error": "body must be a JSON object"}, 400)

        action = str(payload.get("action", "")).strip()
        if action not in ACTIONS:
            return self.send_json(
                {"error": f"unknown action {action!r}; "
                          f"expected one of {', '.join(sorted(ACTIONS))}"}, 400)

        try:
            with WRITE_LOCK:
                result = ACTIONS[action](payload)
                if result["ok"]:
                    result["committed"] = committed(result["out"])
                    result["node"] = Path(node_path(result["out"])).stem
                # Only rebuild on success. A failed write leaves build/ alone,
                # so a reload shows the graph as it actually still is.
                result["rebuilt"] = bool(result["ok"] and rebuild()["ok"])
        except Refused as exc:
            return self.send_json({"error": str(exc)}, exc.code)
        except Exception as exc:                          # noqa: BLE001
            return self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        return self.send_json(result, 200 if result["ok"] else 422)


def serve(port: int, quiet: bool = False) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    httpd.quiet = quiet                                   # type: ignore[attr-defined]
    return httpd


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cairn serve", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8787,
                        help="localhost port (default 8787; 0 picks a free one)")
    parser.add_argument("--open", action="store_true",
                        help="open the map in a browser once the server is up")
    parser.add_argument("--quiet", action="store_true", help="no request log")
    args = parser.parse_args()

    page = lib.REPO_ROOT / "build" / "graph.html"
    if not page.exists():
        print("cairn: build/graph.html does not exist yet — run `cairn build`",
              file=sys.stderr)
        return 1

    try:
        httpd = serve(args.port, args.quiet)
    except OSError as exc:
        print(f"cairn: cannot listen on {HOST}:{args.port} ({exc})\n"
              f"  another `cairn serve` may already be running — try --port",
              file=sys.stderr)
        return 1

    url = f"http://{HOST}:{httpd.server_address[1]}/build/graph.html"
    print(f"cairn serve — {lib.REPO_ROOT}\n"
          f"  {url}\n"
          f"  the panel can now leave a note and move a status; both shell to "
          f"bin/cairn.\n"
          f"  Ctrl-C to stop. The file:// copy keeps working read-only.")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\ncairn: stopped. `cairn sync --push` to send today's writes on.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
