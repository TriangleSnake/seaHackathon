ARG DETECTION_IMAGE=seahackathon-member4-real-loop-integration-detection:latest
FROM ${DETECTION_IMAGE}
USER root
# Official pinned Linux ARM64 Codex release; verify npm's published SHA-512.
RUN python - <<'PY'
import base64, hashlib, io, pathlib, tarfile, urllib.request
url = 'https://registry.npmjs.org/@openai/codex/-/codex-0.154.0-linux-arm64.tgz'
data = urllib.request.urlopen(url, timeout=120).read()
assert base64.b64encode(hashlib.sha512(data).digest()).decode() == 'KmTCB6ST484zeYlPpKP/K5P/gRaYmt6TihVD+zotoe6O9q0JSBP+FYvCz4A/zZXR7xDOHURTSjHp0sD8wWS0YQ=='
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    archive.extractall('/opt/codex', filter='data')
binary = next(p for p in pathlib.Path('/opt/codex').rglob('codex') if p.is_file())
pathlib.Path('/usr/local/bin/codex').symlink_to(binary)
PY
RUN pip install --no-cache-dir pytest==8.4.2 httpx==0.28.1
RUN mkdir /.git /.codex /.agents
ENV CODEX_HOME=/codex-home PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
WORKDIR /workspace
ENTRYPOINT []
