#!/bin/sh
# Run the checker over each example file and show the result.
# The flagged example fails on purpose, so each run is allowed to fail.
cd "$(dirname "$0")/.."
for f in examples/clean.sh examples/flagged.sh examples/edge.sh; do
  echo "== $f =="
  python3 src/shell_pipefail_checker.py "$f" || true
  echo
done
# The folder run skips this script itself: it runs under
# plain sh, and pipefail is a bash option, so this file
# can never carry the guard it checks for.
echo "== examples/ : the whole folder =="
python3 src/shell_pipefail_checker.py --exclude run-example.sh examples/ || true
