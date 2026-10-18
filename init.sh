#!/bin/bash
# Startup path: install, then the full verification pipeline. Fails fast.
set -e

echo "=== make setup ==="
make setup

echo "=== make check ==="
make check

echo ""
echo "Next steps:"
echo "1. Read HANDOFF.md and feature_list.json"
echo "2. Work on the one active feature, or activate exactly one"
echo "3. Finish with: make verify-feature F=<id>"
