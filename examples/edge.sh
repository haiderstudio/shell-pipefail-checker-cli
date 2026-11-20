#!/bin/bash
# A long comment header, to show that comment lines
# do not count toward the ten lines the guard may
# sit in.
set -euo pipefail
curl -fsSL https://example.com/releases/app.tar.gz | tar -xz
echo "downloaded and unpacked"
