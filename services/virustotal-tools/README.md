# VirusTotal MCP service

This service exposes one read-only MCP tool through Agent Gateway:

- `get_virustotal_reputation(indicator_type, indicator)` reads an existing VirusTotal
  v3 URL or domain report. It never submits or requests a scan.

Only the Chat investigation agent allow-lists this tool. The API credential is passed
to this container through the untracked root `.env` as `VIRUSTOTAL_API_KEY`; it is
never returned in tool output. The provider origin is fixed to
`https://www.virustotal.com/api/v3` so configuration cannot redirect the credential.

A found report returns a stable `VT-*` evidence ID and a bounded subset of reputation
fields. A 404 returns `found: false` without an evidence ID because absence from
VirusTotal is not evidence that an indicator is harmless. Same-indicator results are
cached for 15 minutes to conserve public API quota; HTTP 429 responses are not retried.

VirusTotal documents its Public API as limited to four requests per minute and 500
requests per day, and restricts it to non-commercial use. The deployment owner must
confirm that the configured key and project usage comply with the applicable license.

Run tests with:

```bash
python -m pytest -q
```
