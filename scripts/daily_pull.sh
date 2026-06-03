#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
/usr/bin/git fetch origin main
/usr/bin/git rebase origin/main
