#!/bin/bash
ver="$(
  uvx --from packaging python - <<'PY'
import json, urllib.request
from packaging.version import Version
name="rbx.cp"
data=json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json"))
versions=sorted((Version(v) for v in data["releases"]), reverse=True)
for v in versions:
    if v.is_prerelease:
        print(v); break
PY
)"; \
echo "Installing rbx.cp==$ver"; \
uv tool install "rbx.cp==$ver"