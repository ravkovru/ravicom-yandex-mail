#!/bin/sh
set -eu

# The tunnel runtime key belongs only to tunnel-client, not to the MCP server.
unset CONTROL_PLANE_API_KEY
exec ravicom-yandex-mail
