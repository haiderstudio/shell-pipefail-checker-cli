#!/usr/bin/env python3
"""Tests for shell_pipefail_checker — stdlib unittest only."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import shell_pipefail_checker as checker

REPO = Path(__file__).resolve().parent.parent


def run_cli(argv):
    """Run main(argv), capture stdout/stderr, return (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = checker.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write(tmp, name, text, encoding="utf-8"):
    path = Path(tmp) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding=encoding)
    return str(path)


def findings_of(text):
    return checker.check_text(text)


class TestChecks(unittest.TestCase):
    def test_plain_set_o_pipefail_passes(self):
        bad = findings_of("#!/bin/bash\nset -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_cluster_set_euo_pipefail_passes(self):
        bad = findings_of("#!/bin/bash\nset -euo pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_cluster_set_eo_pipefail_passes(self):
        bad = findings_of("#!/bin/bash\nset -eo pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_pipefail_with_other_flag_after_passes(self):
        bad = findings_of("#!/bin/bash\nset -o pipefail -e\necho hi\n")
        self.assertEqual(bad, [])

    def test_other_flag_before_pipefail_passes(self):
        bad = findings_of("#!/bin/bash\nset -e -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_two_o_options_passes(self):
        bad = findings_of(
            "#!/bin/bash\nset -o errexit -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_shebang_o_pipefail_passes(self):
        bad = findings_of("#!/bin/bash -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_shebang_env_cluster_passes(self):
        bad = findings_of(
            "#!/usr/bin/env bash -euo pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_missing_guard_flagged_at_first_code_line(self):
        bad = findings_of(
            "#!/bin/bash\ncurl x | tar -xz\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 2)
        self.assertIn("set -o pipefail", bad[0]["reason"])

    def test_plus_o_pipefail_is_not_a_pass(self):
        bad = findings_of("#!/bin/bash\nset +o pipefail\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_turned_off_after_on_is_flagged(self):
        bad = findings_of(
            "#!/bin/bash\nset -o pipefail\nset +o pipefail\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_turned_on_after_off_passes(self):
        bad = findings_of(
            "#!/bin/bash\nset +o pipefail\nset -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_same_line_off_after_on_is_flagged(self):
        bad = findings_of(
            "#!/bin/bash\nset -o pipefail +o pipefail\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_wrong_option_only_is_flagged(self):
        bad = findings_of("#!/bin/bash\nset -o errexit\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_bare_set_pipefail_is_not_a_pass(self):
        bad = findings_of("#!/bin/bash\nset pipefail\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_pipefail_after_double_dash_is_flagged(self):
        bad = findings_of("#!/bin/bash\nset -- -o pipefail\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_guard_after_ten_code_lines_is_flagged(self):
        lines = ["#!/bin/bash"]
        lines += ["echo line %d" % n for n in range(1, 11)]
        lines += ["set -o pipefail", "echo done"]
        bad = findings_of("\n".join(lines) + "\n")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 2)

    def test_guard_on_tenth_code_line_passes(self):
        lines = ["#!/bin/bash"]
        lines += ["echo line %d" % n for n in range(1, 10)]
        lines += ["set -o pipefail", "echo done"]
        bad = findings_of("\n".join(lines) + "\n")
        self.assertEqual(bad, [])

    def test_long_comment_header_does_not_push_guard_out(self):
        lines = ["#!/bin/bash"]
        lines += ["# comment %d" % n for n in range(1, 30)]
        lines += ["", "set -o pipefail", "echo done"]
        bad = findings_of("\n".join(lines) + "\n")
        self.assertEqual(bad, [])

    def test_guard_with_trailing_comment_passes(self):
        bad = findings_of(
            "#!/bin/bash\nset -o pipefail # fail fast\n"
            "echo hi\n")
        self.assertEqual(bad, [])

    def test_guard_after_echo_on_one_line_passes(self):
        bad = findings_of("#!/bin/bash\necho hi; set -o pipefail\n")
        self.assertEqual(bad, [])

    def test_guard_joined_by_and_passes(self):
        bad = findings_of(
            "#!/bin/bash\ntrue && set -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_invalid_flag_letter_in_cluster_is_flagged(self):
        bad = findings_of("#!/bin/bash\nset -ezo pipefail\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_no_shebang_guard_on_first_line_passes(self):
        bad = findings_of("set -o pipefail\necho hi\n")
        self.assertEqual(bad, [])

    def test_shebang_with_e_only_is_flagged(self):
        bad = findings_of("#!/bin/bash -e\necho hi\n")
        self.assertEqual(len(bad), 1)

    def test_tabs_around_guard_passes(self):
        bad = findings_of("#!/bin/bash\n\tset\t-o\tpipefail\n")
        self.assertEqual(bad, [])

    def test_crlf_file_passes(self):
        bad = findings_of(
            "#!/bin/bash\r\nset -o pipefail\r\necho hi\r\n")
        self.assertEqual(bad, [])

    def test_guard_after_header_in_function_is_flagged(self):
        lines = ["#!/bin/bash"]
        lines += ["echo line %d" % n for n in range(1, 11)]
        lines += ["run() {", "  set -o pipefail", "}"]
        bad = findings_of("\n".join(lines) + "\n")
        self.assertEqual(len(bad), 1)

    def test_empty_file_passes(self):
        self.assertEqual(findings_of(""), [])

    def test_comment_only_file_passes(self):
        self.assertEqual(findings_of("# just a comment\n"), [])

    def test_shebang_only_file_passes(self):
        self.assertEqual(findings_of("#!/bin/bash\n"), [])


class TestCLI(unittest.TestCase):
    def test_clean_file_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "ok.sh",
                         "#!/bin/bash\nset -o pipefail\n")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 0)
            self.assertIn("OK", out)

    def test_flagged_file_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.sh", "#!/bin/bash\necho hi\n")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("FAIL %s: line 2" % path, out)
            self.assertIn("Checked 1 file(s), 1 file(s) failed.",
                          out)

    def test_folder_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.sh", "#!/bin/bash\nset -o pipefail\n")
            write(tmp, "b.sh", "#!/bin/bash\necho hi\n")
            write(tmp, "c.txt", "set -o pipefail\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)

    def test_nested_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "sub/deep.sh", "#!/bin/bash\necho hi\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 1)
            self.assertIn("deep.sh", out)

    def test_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "top.sh", "#!/bin/bash\nset -o pipefail\n")
            write(tmp, "sub/deep.sh", "#!/bin/bash\necho hi\n")
            code, out, _ = run_cli(["--no-recursive", tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_exclude_skips_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.sh", "#!/bin/bash\necho hi\n")
            write(tmp, "b.sh", "#!/bin/bash\nset -o pipefail\n")
            code, out, _ = run_cli(["--exclude", "a.sh", tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_git_folder_skipped_in_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, ".git/hooks/bad.sh", "#!/bin/bash\necho hi\n")
            write(tmp, "ok.sh", "#!/bin/bash\nset -o pipefail\n")
            code, out, _ = run_cli([tmp])
            self.assertEqual(code, 0)
            self.assertIn("1 file(s) checked", out)

    def test_direct_file_checked_whatever_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "deploy", "#!/bin/bash\necho hi\n")
            code, _, _ = run_cli([path])
            self.assertEqual(code, 1)

    def test_duplicate_paths_checked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.sh", "#!/bin/bash\necho hi\n")
            code, out, _ = run_cli([path, path])
            self.assertEqual(code, 1)
            self.assertIn("Checked 1 file(s)", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "a.sh", "#!/bin/bash\necho hi\n")
            code, out, _ = run_cli(["--json", path])
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual(data["checked"], 1)
            self.assertEqual(data["findings"], 1)
            self.assertEqual(data["files"][0]["findings"][0]["line"],
                             2)

    def test_stdin_clean(self):
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO("#!/bin/bash\nset -euo pipefail\n")
        try:
            with redirect_stdout(out):
                code = checker.main(["--stdin"])
        finally:
            sys.stdin = old
        self.assertEqual(code, 0)
        self.assertIn("OK", out.getvalue())

    def test_stdin_dirty(self):
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO("#!/bin/bash\necho hi\n")
        try:
            with redirect_stdout(out):
                code = checker.main(["--stdin"])
        finally:
            sys.stdin = old
        self.assertEqual(code, 1)
        self.assertIn("FAIL <stdin>: line 2", out.getvalue())

    def test_stdin_with_paths_is_usage_error(self):
        code, _, err = run_cli(["--stdin", "x.sh"])
        self.assertEqual(code, 2)
        self.assertIn("--stdin takes no paths", err)

    def test_no_paths_is_usage_error(self):
        code, _, err = run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("give a shell script", err)

    def test_missing_path_exit_2(self):
        code, _, err = run_cli(["/no/such/path.sh"])
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_empty_folder_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli([tmp])
            self.assertEqual(code, 2)
            self.assertIn("no shell files found", err)

    def test_bad_flag_exit_2(self):
        code, _, err = run_cli(["--nope"])
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)

    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("shell_pipefail_checker 1.0.0", out)

    def test_non_utf8_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.sh", b"\xff\xfe\n")
            code, out, _ = run_cli([path])
            self.assertEqual(code, 1)
            self.assertIn("ERROR", out)
            self.assertIn("not valid UTF-8", out)

    def test_input_files_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "#!/bin/bash\necho hi\n"
            path = write(tmp, "a.sh", text)
            run_cli([path])
            self.assertEqual(Path(path).read_text(), text)

    def test_cli_runs_from_another_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.sh", "#!/bin/bash\necho hi\n")
            result = subprocess.run(
                [sys.executable,
                 str(REPO / "src" / "shell_pipefail_checker.py"),
                 path],
                capture_output=True, text=True, cwd="/")
            self.assertEqual(result.returncode, 1)
            self.assertIn("line 2 has no set -o pipefail",
                          result.stdout)

    def test_cli_runs_under_fake_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.sh", "#!/bin/bash\necho hi\n")
            env = dict(os.environ, HOME=tmp)
            result = subprocess.run(
                [sys.executable,
                 str(REPO / "src" / "shell_pipefail_checker.py"),
                 path],
                capture_output=True, text=True, cwd=tmp, env=env)
            self.assertEqual(result.returncode, 1)

    def test_run_example_output_matches_sample(self):
        sample = (REPO / "examples" / "sample-output.md").read_text()
        result = subprocess.run(
            ["sh", str(REPO / "examples" / "run-example.sh")],
            capture_output=True, text=True, cwd=str(REPO))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), sample.strip())

    def test_readme_quotes_match_real_runs(self):
        readme = (REPO / "README.md").read_text()
        flagged = (REPO / "examples" / "flagged.sh").read_text()
        bad = checker.check_text(flagged)
        for item in bad:
            line = ("FAIL examples/flagged.sh: line %d %s"
                    % (item["line"], item["reason"]))
            self.assertIn(line, readme)


class TestExamples(unittest.TestCase):
    def test_clean_example_passes(self):
        code, _, _ = run_cli([str(REPO / "examples" / "clean.sh")])
        self.assertEqual(code, 0)

    def test_flagged_example_fails_with_one(self):
        bad = checker.check_text(
            (REPO / "examples" / "flagged.sh").read_text())
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["line"], 2)

    def test_edge_example_passes(self):
        code, _, _ = run_cli([str(REPO / "examples" / "edge.sh")])
        self.assertEqual(code, 0)


class TestHygiene(unittest.TestCase):
    def _repo_files(self, skip_tests=True):
        """Every file in the repo, minus .git and caches."""
        for path in REPO.rglob("*"):
            if path.is_dir():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix == ".pyc":
                continue
            if skip_tests and "tests" in path.parts:
                continue
            yield path

    def test_no_placeholder_text(self):
        banned = ["TODO", "coming soon", "lorem", "FIXME", "XXX"]
        hits = []
        for path in self._repo_files(skip_tests=True):
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path.name, word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in self._repo_files(skip_tests=True):
            text = path.read_text(errors="ignore")
            for marker in ("/home/", "/Users/", "C:\\", "/tmp/"):
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        import ast
        stdlib = set(sys.stdlib_module_names)
        for target in (REPO / "src" / "shell_pipefail_checker.py",
                       REPO / "tests" / "test_shell_pipefail_checker.py"):
            tree = ast.parse(target.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported - stdlib - {"shell_pipefail_checker"},
                (target.name, imported))
            self.assertNotIn("yaml", imported)

    def test_no_network_use_in_src(self):
        src = (REPO / "src" / "shell_pipefail_checker.py").read_text()
        for marker in ("urllib.request", "requests", "socket",
                       "http.client", "urlopen", "urlretrieve"):
            self.assertNotIn(marker, src, marker)

    def test_gitignore_lists_env_first(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertTrue(lines, ".gitignore is empty")
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("tests/test_shell_pipefail_checker.py", ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("3.12", ci)
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_readme_names_the_neighbouring_repos(self):
        readme = (REPO / "README.md").read_text()
        for name in ("shell-set-e-checker-cli",
                     "shell-set-u-checker-cli"):
            self.assertIn(name, readme)
        self.assertIn("ShellCheck", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
