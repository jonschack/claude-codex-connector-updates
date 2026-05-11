#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

python3 -m mcp_newsletter check || true
python3 -m mcp_newsletter bootstrap-github

