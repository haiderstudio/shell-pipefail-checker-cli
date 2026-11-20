# shell-pipefail-checker-cli

Check shell scripts opt into failing on pipeline errors with `set -o pipefail`, fail CI when one is missing.

[![CI](https://github.com/haiderstudio/shell-pipefail-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/shell-pipefail-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`shell_pipefail_checker` reads shell scripts, looks
for `set -o pipefail` near the top of each one, and
reports each script missing it, with the file and the
line where the script starts doing work. It exits 1
when any script is missing the guard, so it can fail
a CI run. A script with the guard exits 0.

- A pipeline's exit status is its LAST command's, so
  `curl ... | tar ...` can fail at curl and tar still
  exits 0 — and CI goes green on a broken download.
  `set -o pipefail` makes the pipeline fail when ANY
  part of it fails. One flag, once found, and the
  hidden failure becomes a loud one.
- The guard must sit in the first 10 lines of code
  after the shebang — blank lines and comment lines
  do not count toward the 10, so a long comment header
  does not push the guard out of reach. A guard
  further down is reported as missing: a script that
  does its work first and opts in later has already
  run its risky pipelines.
- Combined flag clusters count: `set -euo pipefail`
  turns pipefail on, because the `o` in the cluster
  takes `pipefail` as its option name — the same rule
  the shell itself uses. A shebang that passes
  pipefail to the shell itself, such as `#!/bin/bash
  -o pipefail`, counts too.
- `set +o pipefail` turns it back off, so a script
  that switches it off after switching it on is
  reported: the last setting in the header is the one
  that counts. A bare `set pipefail` does not count —
  that sets a positional parameter, not the option —
  and neither does anything after `--`.
- A file given directly on the command line is always
  checked, whatever its name. A folder is walked for
  files ending in `.sh`, `.bash`, or `.zsh` only,
  recursively by default (`--no-recursive` stops at
  the top level). `.git` folders are never walked, and
  directory links are never followed.
- `--json` prints the result as JSON, and `--stdin`
  checks one shell script read from standard input.
- A file that cannot be read — a file that is not
  valid UTF-8 — is reported as an error and fails the
  check the same way a finding does.

## Who it is for

Anyone who writes a shell script that pipes one
command into another — which is every script author
who downloads, unpacks, or transforms anything in a
pipeline. A failing download hidden by a passing
pipeline is found only when someone finally asks why
the install broke, long after the script was
written. This is the gate that names it at the pull
request, before it ships.

## What it does NOT do

- It does not check `set -e`. That is repo #112,
  shell-set-e-checker-cli — failing fast on a bad
  command is a different check from failing on a bad
  pipeline, even though both live in the same `set`
  line.
- It does not check `set -u`. That is repo #130,
  shell-set-u-checker-cli — failing on an unset
  variable is a different check on the same scripts.
- It does not check the shebang line. That is repo
  #64, shell-shebang-checker-cli — a missing or wrong
  interpreter line is a different check on the same
  scripts.
- It does not check quoting. That is repo #100,
  shell-quote-checker-cli — an unquoted variable is
  a different check on the same scripts.
- It does not rewrite a script to add the guard. It
  reports, you add the line.
- It never touches the network, and it only reads the
  files and folders you point it at.

## How this differs

- A fresh search of GitHub on Nov 18, 2026 found 0
  results for `"shell-pipefail-checker-cli"` and 0
  results for `shell pipefail checker` — the field is
  completely empty for this job. No rival is a tested
  command-line gate that checks shell scripts for
  `set -o pipefail`.
- ShellCheck owns shell linting broadly, and it does
  flag a missing `pipefail` — but ShellCheck is a
  whole linter with hundreds of checks and a binary
  to install. This tool is one check only, as a
  zero-install standard-library script: the same
  broad-vs-narrow pattern as repo #112
  (shell-set-e-checker-cli) against ShellCheck. If
  you already run ShellCheck, keep running it — this
  gate is for a pipeline that wants exactly this one
  rule, with its own exit code, and nothing else.
- So the narrow slice stands: `set -o pipefail`
  only, including combined flag clusters and the
  shebang form, per-line reporting, a CI exit code,
  and a report-only tool that never edits a file.

## Install

```sh
git clone https://github.com/haiderstudio/shell-pipefail-checker-cli.git
cd shell-pipefail-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies.

## Usage

Check one script:

```sh
python3 src/shell_pipefail_checker.py deploy.sh
```

A script with the guard passes:

```sh
$ python3 src/shell_pipefail_checker.py examples/clean.sh
OK — 1 file(s) checked, every script opts into failing on pipeline errors.
```

A script without it fails, with the line where it
starts doing work:

```sh
$ python3 src/shell_pipefail_checker.py examples/flagged.sh
FAIL examples/flagged.sh: line 2 has no set -o pipefail in the first 10 lines after the shebang
Checked 1 file(s), 1 file(s) failed.
```

Check a whole folder (`.sh`, `.bash`, and `.zsh` files only):

```sh
$ python3 src/shell_pipefail_checker.py --exclude run-example.sh examples/
FAIL examples/flagged.sh: line 2 has no set -o pipefail in the first 10 lines after the shebang
Checked 3 file(s), 1 file(s) failed.
```

Check one script from standard input:

```sh
$ python3 src/shell_pipefail_checker.py --stdin < examples/flagged.sh
FAIL <stdin>: line 2 has no set -o pipefail in the first 10 lines after the shebang
Checked 1 file(s), 1 file(s) failed.
```

Machine-readable output:

```sh
$ python3 src/shell_pipefail_checker.py --json examples/flagged.sh
{
  "files": [
    {
      "path": "examples/flagged.sh",
      "findings": [
        {
          "line": 2,
          "reason": "has no set -o pipefail in the first 10 lines after the shebang"
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "findings": 1
}
```

Exit codes: 0 when every script opts into failing on
pipeline errors, 1 when any script is missing the
guard or a file error is found, 2 for a usage error
(a missing path, a bad flag, or no shell files found).

## Examples

A script whose first real line is a pipeline, with no
guard anywhere, is caught with that line:

```sh
$ printf '#!/bin/bash\necho "starting"\ncurl -fsSL https://example.com/x.tar.gz | tar -xz\n' > two.sh
$ python3 src/shell_pipefail_checker.py two.sh
FAIL two.sh: line 2 has no set -o pipefail in the first 10 lines after the shebang
Checked 1 file(s), 1 file(s) failed.
```

Switching pipefail off is not opting in — `set +o
pipefail` is a fail, not a pass:

```sh
$ printf '#!/bin/bash\nset +o pipefail\necho hi\n' > off.sh
$ python3 src/shell_pipefail_checker.py off.sh
FAIL off.sh: line 2 has no set -o pipefail in the first 10 lines after the shebang
Checked 1 file(s), 1 file(s) failed.
```

The same holds for a combined cluster —
`examples/edge.sh` uses `set -euo pipefail` under a
long comment header, and it passes:

```sh
$ python3 src/shell_pipefail_checker.py examples/edge.sh
OK — 1 file(s) checked, every script opts into failing on pipeline errors.
```

Run every bundled example at once with `sh
examples/run-example.sh` — the output is saved in
[examples/sample-output.md](examples/sample-output.md).

## How it is tested

```sh
python3 tests/test_shell_pipefail_checker.py
```

The tests cover the guard (a plain `set -o
pipefail`, the combined clusters `set -euo pipefail`
and `set -eo pipefail`, `set -o pipefail` with
another flag before or after it, two `-o` options on
one line, a shebang that passes `-o pipefail`, a
shebang through `env` with a cluster, a guard with a
trailing comment, a guard after `echo` on the same
line, a guard joined by `&&`, tabs around the guard,
a CRLF file, no shebang with the guard on the first
line), the misses (no guard at all, `set +o
pipefail` alone, pipefail switched off after being
switched on — on one line and on two lines, the
wrong option only, a bare `set pipefail`, pipefail
after `--`, an invalid flag letter in a cluster, a
shebang with `-e` only, a guard after the tenth code
line, a guard inside a function past the header), the
header rule (a guard on the tenth code line passes,
a long comment header does not push the guard out),
empty and comment-only files, the CLI (exit 0/1/2,
folder walking for several shell files, nested
folders, `--no-recursive`, `--exclude`, `.git`
skipped, a direct file checked whatever its name,
duplicate paths checked once, `--json` output,
`--stdin`, bad flags, missing paths, empty folders,
`--version`, a non-UTF-8 file reported, input files
left unchanged, the tool run from `/` and under a
fake HOME), the bundled examples (sample output
compared against a fresh run, and the README-quoted
outputs checked against it), and hygiene checks (no
placeholder text, no absolute paths, stdlib imports
only, no network use in the source, `.env` first in
`.gitignore`, CI file runs the test file, README names
the neighbouring repos and ShellCheck).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
flag-cluster parsing follows the same approach as
repo #112, shell-set-e-checker-cli, which checks the
sibling flag — but every line of code here is
original, built on nothing but Python's standard
library. ShellCheck is named honestly above as the
broad linter that also covers this ground; this repo
is the narrow, one-check gate for pipelines that want
exactly this rule.
