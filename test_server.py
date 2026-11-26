#!/usr/bin/env python3
"""Smoke tests for the RetroTV API. Run: python3 test_server.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(path):
    with urllib.request.urlopen(BASE + path) as r:
        return r.status, json.loads(r.read())


def main():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"), tmp)
    env = dict(os.environ, RETROTV_PORT=str(PORT))
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=tmp, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                get("/api/health")
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise SystemExit("server did not start")

        s, d = post("/api/parent/data", {"pin": "1234"})
        assert s == 200, d
        assert "pin" not in d
        assert isinstance(d["mediaFiles"], list)
        for e in d["schedule"]:
            for key in ("id", "channelId", "title", "kind", "durationMinutes", "start", "end", "breaks"):
                assert key in e, f"schedule entry missing {key}: {e}"
        s, now = get("/api/now")
        assert s == 200 and len(now["channels"]) == 3
        assert now["channels"][0]["state"] in ("program", "break", "offair")
        s, d = post("/api/parent/login", {"pin": "0000"})
        assert s == 401
        print("test_server: all assertions passed")
    finally:
        proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
