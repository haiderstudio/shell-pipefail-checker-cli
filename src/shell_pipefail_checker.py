#!/usr/bin/env python3
"""Check shell scripts opt into failing on pipeline errors.

Run: python3 src/shell_pipefail_checker.py deploy.sh
     python3 src/shell_pipefail_checker.py scripts/
     python3 src/shell_pipefail_checker.py --stdin < deploy.sh

A pipeline's exit status is its LAST command's, so
`curl ... | tar ...` can fail at curl and tar still
exits 0 — and CI goes green on a broken download.
`set -o pipefail` makes the pipeline fail when ANY
part of it fails. This tool reads each shell script,
looks for `set -o pipefail` near the top of the
script, after the shebang, and reports each script
missing it, with the file and the line where the
script starts doing work. It exits 1 when any script
is missing the guard, so it can fail a CI run. A
script with the guard exits 0.

"Near the top" means the first 10 lines of code
after the shebang — blank lines and comment lines
do not count toward the 10, so a long comment header
does not push the guard out of reach. A shebang that
passes pipefail to the shell itself (for example
`#!/bin/bash -o pipefail`) counts too: the script
does fail on pipeline errors, and there is nothing
to add.

Combined flag clusters count as well: `set -euo
pipefail` turns pipefail on, because the `o` in the
cluster takes `pipefail` as its option name — the
same rule the shell itself uses. `set +o pipefail`
turns it back off, so a script that switches it off
after switching it on is reported: the last setting
in the header is the one that counts.

A file given directly on the command line is always
checked, whatever its name. A folder is walked for
files ending in .sh, .bash, or .zsh only,
recursively by default (--no-recursive stops at the
top level). .git folders are never walked, and
directory links are never followed. An extensionless
script is checked by pointing at the file directly.

It never rewrites a file, never touches the network,
and reads only the files and folders you point it at.
"""

import argparse
import fnmatch
import json
import os
import re
import sys

VERSION = "1.0.0"
EXTENSIONS = (".sh", ".bash", ".zsh")
HEADER_LINES = 10

FLAG_LETTERS = set("abefhkmnoptuvxC")


def _scan_option_tokens(tokens):
    """Scan set/shebang option tokens for a pipefail setting.

    Returns (saw, enabled): saw is True when any -o/+o
    pipefail setting appeared, enabled is the state the
    last such setting left — True when pipefail ends up
    on, False when it ends up off. A lone `-o` or `+o`
    takes the next token as the option name, and an `o`
    inside a flag cluster such as `-euo` does the same:
    `set -euo pipefail` turns pipefail on. Anything
    after `--` is a positional argument, not a flag,
    and a bare `pipefail` on its own is a positional
    argument too — `set pipefail` does not turn the
    option on.
    """
    saw = False
    enabled = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            break
        if token in ("-o", "+o"):
            if index + 1 >= len(tokens):
                break
            if tokens[index + 1] == "pipefail":
                saw = True
                enabled = token == "-o"
            index += 2
            continue
        if (token.startswith("-") or token.startswith("+")) \
                and len(token) > 1:
            flags = token[1:]
            if all(c in FLAG_LETTERS for c in flags) \
                    and "o" in flags:
                if index + 1 >= len(tokens):
                    break
                if tokens[index + 1] == "pipefail":
                    saw = True
                    enabled = token.startswith("-")
                index += 2
                continue
            index += 1
            continue
        index += 1
    return saw, enabled


def _set_line_pipefail(line):
    """Return (saw, enabled) for one line holding set commands.

    A line can hold several commands joined by `;`, `&&`,
    or `||`, so each part is checked on its own and the
    last pipefail setting on the line is the one that
    counts.
    """
    code = line.split(" #", 1)[0]
    saw = False
    enabled = False
    for segment in re.split(r";|&&|\|\|", code):
        tokens = segment.split()
        if not tokens or tokens[0] != "set":
            continue
        part_saw, part_enabled = _scan_option_tokens(tokens[1:])
        if part_saw:
            saw = True
            enabled = part_enabled
    return saw, enabled


def _shebang_enables_pipefail(line):
    """True when the shebang itself passes pipefail to the shell.

    Covers `#!/bin/bash -o pipefail`,
    `#!/bin/bash -euo pipefail`, and
    `#!/usr/bin/env bash -o pipefail`.
    """
    tokens = line[2:].split()
    saw, enabled = _scan_option_tokens(tokens)
    return saw and enabled


def _code_lines(text):
    """Yield (line_number, line) for lines that are code.

    Blank lines and comment-only lines are skipped.
    The shebang line is yielded as code too — the
    caller decides what to do with it.
    """
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        yield number, line


def check_text(text):
    """Check one shell script given as text.

    Returns a list of finding dicts: empty when the
    script opts into failing on pipeline errors, one
    entry when it does not. The finding names the line
    where the script starts doing work without the
    guard.
    """
    lines = text.splitlines()
    start = 0
    if lines and lines[0].startswith("#!"):
        if _shebang_enables_pipefail(lines[0]):
            return []
        start = 1
    code = [(n, line) for n, line in _code_lines(text)
            if n > start]
    if not code:
        return []
    saw = False
    enabled = False
    for number, line in code[:HEADER_LINES]:
        part_saw, part_enabled = _set_line_pipefail(line)
        if part_saw:
            saw = True
            enabled = part_enabled
    if saw and enabled:
        return []
    first_number = code[0][0]
    return [{
        "line": first_number,
        "reason": (
            "has no set -o pipefail in the first %d lines "
            "after the shebang" % HEADER_LINES
        ),
    }]


def check_file(path):
    """Check one file. Return (findings, error).

    error is a string when the file cannot be read or
    is not valid UTF-8, else None.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        return [], "cannot read file: %s" % exc.strerror
    except UnicodeDecodeError:
        return [], "not valid UTF-8"
    return check_text(text), None


def collect_files(paths, recursive, exclude):
    """Expand command-line paths into a sorted file list.

    Files are checked in the order given, each path
    once. Folders contribute their .sh, .bash, and
    .zsh files only. Returns (files, error): error
    names the first problem (a missing path, or no
    shell files found).
    """
    files = []
    seen = set()
    for path in paths:
        if os.path.isfile(path):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                files.append(path)
        elif os.path.isdir(path):
            for root, dirs, names in os.walk(path,
                                            followlinks=False):
                dirs[:] = sorted(
                    d for d in dirs if d != ".git")
                if not recursive:
                    dirs[:] = []
                for name in sorted(names):
                    if not name.lower().endswith(EXTENSIONS):
                        continue
                    if any(fnmatch.fnmatch(name, pattern)
                           for pattern in exclude):
                        continue
                    full = os.path.join(root, name)
                    real = os.path.realpath(full)
                    if real not in seen:
                        seen.add(real)
                        files.append(full)
        else:
            return [], "no such file or folder: %s" % path
    if not files:
        return [], "no shell files found"
    return files, None


def report_text(results, checked, findings):
    """Build the plain-text report for a run."""
    lines = []
    for result in results:
        path = result["path"]
        if result["error"]:
            lines.append("ERROR %s: %s" % (path, result["error"]))
        for finding in result["findings"]:
            lines.append("FAIL %s: line %d %s"
                         % (path, finding["line"],
                            finding["reason"]))
    bad = sum(1 for r in results
              if r["findings"] or r["error"])
    if bad:
        lines.append(
            "Checked %d file(s), %d file(s) failed."
            % (checked, bad))
    else:
        lines.append(
            "OK \u2014 %d file(s) checked, every script opts "
            "into failing on pipeline errors." % checked)
    return "\n".join(lines) + "\n"


def report_json(results, checked, findings):
    """Build the JSON report for a run."""
    return json.dumps({
        "files": results,
        "checked": checked,
        "findings": findings,
    }, indent=2) + "\n"


def main(argv=None):
    """Entry point. Returns an exit code (0, 1, or 2)."""
    parser = argparse.ArgumentParser(
        prog="shell_pipefail_checker",
        description="Check shell scripts opt into failing "
                    "on pipeline errors with set -o pipefail.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="shell script or folder to check")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append",
                        default=[],
                        metavar="PATTERN",
                        help="skip files matching this glob pattern "
                             "(repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--stdin", action="store_true",
                        help="check one shell script from stdin")
    parser.add_argument("--version", action="version",
                        version="shell_pipefail_checker " + VERSION)
    args = parser.parse_args(argv)

    if args.stdin:
        if args.paths:
            print("error: --stdin takes no paths",
                  file=sys.stderr)
            return 2
        text = sys.stdin.read()
        findings_list = check_text(text)
        results = [{"path": "<stdin>",
                    "findings": findings_list,
                    "error": None}]
        checked = 1
        findings = len(findings_list)
        bad = findings
    else:
        if not args.paths:
            print("error: give a shell script or folder to check",
                  file=sys.stderr)
            return 2
        files, error = collect_files(
            args.paths, not args.no_recursive, args.exclude)
        if error:
            print("error: %s" % error, file=sys.stderr)
            return 2
        results = []
        findings = 0
        bad = 0
        for path in files:
            found, err = check_file(path)
            if found or err:
                bad += 1
            findings += len(found)
            results.append({"path": path, "findings": found,
                            "error": err})
        checked = len(files)

    if args.json:
        sys.stdout.write(report_json(results, checked, findings))
    else:
        sys.stdout.write(report_text(results, checked, findings))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
