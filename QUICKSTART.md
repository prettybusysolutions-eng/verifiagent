# Quickstart

This path verifies the public service contract without GitHub App credentials.

```bash
git clone https://github.com/prettybusysolutions-eng/verifiagent.git
cd verifiagent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8003
```

In another terminal:

```bash
curl --fail http://127.0.0.1:8003/verify/health
curl --fail http://127.0.0.1:8003/docs >/dev/null
```

The health path does not exercise GitHub installation, persistence, billing, or
production isolation. Those remain outside the current `v0.1` claim boundary.
