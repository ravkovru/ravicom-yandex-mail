#!/bin/sh
set -eu

# The tunnel runtime key belongs only to tunnel-client, not to the MCP server.
unset CONTROL_PLANE_API_KEY
# Use this checkout explicitly; a globally installed launcher may point at an
# older copy of the project and therefore load the wrong .env file.
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT_DIR"
exec python3 -m ravicom_mail.server
