#!/bin/sh
set -eu

gateway_url="${AGENTGATEWAY_URL:-http://localhost:3000/mcp}"
headers="Content-Type: application/json"
accept="Accept: application/json, text/event-stream"

initialize_response="$(curl --retry 10 --retry-connrefused --retry-delay 1 -fsS "$gateway_url" \
  -H "$headers" \
  -H "$accept" \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-test","version":"1.0"}}}')"

tools_response="$(curl -fsS "$gateway_url" \
  -H "$headers" \
  -H "$accept" \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')"

health_response="$(curl -fsS "$gateway_url" \
  -H "$headers" \
  -H "$accept" \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"database_health","arguments":{}}}')"

printf '%s\n' "$initialize_response" | grep -q 'fraud-intelligence-system-tools'
printf '%s\n' "$tools_response" | grep -q 'find_shared_ip_accounts'
printf '%s\n' "$tools_response" | grep -q 'get_patrol_overview'
printf '%s\n' "$tools_response" | grep -q 'find_high_density_ips'
printf '%s\n' "$tools_response" | grep -q 'find_new_account_bursts'
printf '%s\n' "$tools_response" | grep -q 'get_evidence_records'
printf '%s\n' "$health_response" | grep -q '"ok":true'

printf 'MCP gateway smoke test passed: %s\n' "$gateway_url"
