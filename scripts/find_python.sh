#!/bin/sh
# Print the path of an interpreter that can actually run Cairn, or nothing.
#
# "Can run Cairn" means Python >= 3.7 (lib.py uses postponed annotations) with
# PyYAML importable. Both halves matter, and on an HPC login node they are
# routinely split across different interpreters: NREL Kestrel's default
# `python3` is 3.6.8 *with* PyYAML, while python3.9 has no PyYAML at all.
#
# That split is why this script exists. Probing only for `python3` and only for
# `import yaml` — which is what the pre-commit hook used to do — passes on 3.6.8
# and then dies on a SyntaxError, reporting it as "validation failed: schema
# drift". A misleading hook failure is worse than no hook, because the documented
# response to it is to fix a schema error that isn't there.
#
# Override with CAIRN_PYTHON=/path/to/python for anything exotic.
#
# `--any` drops the PyYAML half of the test. Two commands genuinely do not need
# it — `capture` and `sync` — and both are written not to import lib for that
# reason: capture must not lose a thought to a dependency error, and sync must
# still pull on a machine where something else is broken. Requiring PyYAML to
# *launch* them threw that guarantee away one layer up from where it was made.

need_yaml=1
[ "$1" = "--any" ] && { need_yaml=0; shift; }

check() {
    [ -n "$1" ] || return 1
    command -v "$1" >/dev/null 2>&1 || [ -x "$1" ] || return 1
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' \
        >/dev/null 2>&1 || return 1
    if [ "$need_yaml" -eq 1 ]; then
        "$1" -c 'import yaml' >/dev/null 2>&1 || return 1
    fi
    command -v "$1" 2>/dev/null || echo "$1"
}

# Explicit override wins, and fails loudly rather than falling through to a
# different interpreter than the one that was asked for.
if [ -n "$CAIRN_PYTHON" ]; then
    if found=$(check "$CAIRN_PYTHON"); then
        echo "$found"
        exit 0
    fi
    echo "cairn: CAIRN_PYTHON=$CAIRN_PYTHON cannot run Cairn (needs Python >= 3.7 + PyYAML)" >&2
    exit 1
fi

# `python` (no 3) and the conda *base* env were both missing here, and on a
# conda-managed macOS they are usually the interpreter that has PyYAML: `python3`
# resolves to Homebrew's, while conda's lives at `python` or <base>/bin/python.
# Probing only `python3*` reported "no usable Python" on a machine that had one.
for candidate in \
    python3 python python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 \
    "$CONDA_PREFIX/bin/python" \
    "$HOME"/miniforge3/bin/python \
    "$HOME"/miniconda3/bin/python \
    "$HOME"/anaconda3/bin/python \
    "$HOME"/.cairn/venv/bin/python \
    "$HOME"/.conda-envs/*/bin/python \
    "$HOME"/miniconda3/envs/*/bin/python \
    "$HOME"/miniforge3/envs/*/bin/python \
    "$HOME"/anaconda3/envs/*/bin/python
do
    if found=$(check "$candidate"); then
        echo "$found"
        exit 0
    fi
done

exit 1
