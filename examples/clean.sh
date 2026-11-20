#!/bin/bash
set -o pipefail
curl -fsSL https://example.com/releases/app.tar.gz | tar -xz
echo "downloaded and unpacked"
