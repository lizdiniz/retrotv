#!/usr/bin/env python3
"""RetroTV - a 90s-style scheduled TV guide. Zero dependencies (Python stdlib only).

Run:  python3 server.py            -> http://127.0.0.1:8000  (kids TV)
                                 http://127.0.0.1:8000/parent (parent console)
For phone access on your home network:  RETROTV_HOST=0.0.0.0 python3 server.py
"""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "db.json")
MEDIA_DIR = os.path.join(ROOT, "media")
STATIC_DIR = os.path.join(ROOT, "static")

HOST = os.environ.get("RETROTV_HOST", "127.0.0.1")
PORT = int(os.environ.get("RETROTV_PORT", "8000"))

LOCK = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".ogv": "video/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".txt": "text/plain; charset=utf-8",
}


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


def now_dt():
    return datetime.now().astimezone()


def iso(dt):
    return dt.isoformat(timespec="seconds")


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def load_db():
    with LOCK:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


def save_db(db):
    with LOCK:
        tmp = DB_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
        os.replace(tmp, DB_PATH)


def seed_db():
    base = now_dt().replace(second=0, microsecond=0)

    def at(minutes):
        return iso(base + timedelta(minutes=minutes))

    library = [
        {"id": "lib-toons", "title": "Morning Cartoons", "kind": "show", "durationMinutes": 22, "src": None},
        {"id": "lib-quick", "title": "Quick Toons", "kind": "show", "durationMinutes": 11, "src": None},
        {"id": "lib-cereal", "title": "Cereal Club", "kind": "show", "durationMinutes": 30, "src": None},
        {"id": "lib-music", "title": "Retro Music Videos", "kind": "show", "durationMinutes": 45, "src": None},
        {"id": "lib-bedtime", "title": "Bedtime Story Hour", "kind": "show", "durationMinutes": 15, "src": None},
        {"id": "lib-movie", "title": "Drive-In Movie", "kind": "movie", "durationMinutes": 90, "src": None},
        {"id": "lib-movie2", "title": "Sci-Fi Double Feature", "kind": "movie", "durationMinutes": 120, "src": None},
    ]
    schedule = [
        {"id": "s1", "channelId": "ch3", "libraryId": "lib-toons", "start": at(0),
         "breaks": [{"id": "b1", "label": "Bathroom Break", "atMinutes": 10, "durationMinutes": 3}]},
        {"id": "s2", "channelId": "ch3", "libraryId": "lib-quick", "start": at(22), "breaks": []},
        {"id": "s3", "channelId": "ch3", "libraryId": "lib-cereal", "start": at(33), "breaks": []},
        {"id": "s4", "channelId": "ch4", "libraryId": "lib-movie", "start": at(0),
         "breaks": [{"id": "b2", "label": "Intermission", "atMinutes": 45, "durationMinutes": 5}]},
        {"id": "s5", "channelId": "ch4", "libraryId": "lib-movie2", "start": at(90), "breaks": []},
        {"id": "s6", "channelId": "ch5", "libraryId": "lib-music", "start": at(0),
         "breaks": [{"id": "b3", "label": "Bathroom Break", "atMinutes": 20, "durationMinutes": 3}]},
        {"id": "s7", "channelId": "ch5", "libraryId": "lib-bedtime", "start": at(45), "breaks": []},
    ]
    return {
        "pin": "1234",
        "channels": [
            {"id": "ch3", "number": 3, "name": "TOONS"},
            {"id": "ch4", "number": 4, "name": "MOVIES"},
            {"id": "ch5", "number": 5, "name": "MUSIC"},
        ],
        "library": library,
        "schedule": schedule,
    }


def ensure_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    note = os.path.join(MEDIA_DIR, "PUT-YOUR-VIDEOS-HERE.txt")
    if not os.path.exists(note):
        with open(note, "w", encoding="utf-8") as f:
            f.write("Drop .mp4/.webm/.mkv video files in this folder, then pick them in the parent view.\n")
    if not os.path.exists(DB_PATH):
        save_db(seed_db())


def find_lib(db, lib_id):
    for item in db["library"]:
        if item["id"] == lib_id:
            return item
    return None


def public_entry(db, entry):
    lib = find_lib(db, entry["libraryId"]) or {
        "title": "Unknown", "kind": "show", "durationMinutes": 0, "src": None}
    start = parse_ts(entry["start"])
    dur_s = lib["durationMinutes"] * 60
    return {
        "id": entry["id"],
        "channelId": entry["channelId"],
        "libraryId": entry["libraryId"],
        "title": lib["title"],
        "kind": lib["kind"],
        "src": lib["src"],
        "durationMinutes": lib["durationMinutes"],
        "start": entry["start"],
        "end": iso(start + timedelta(seconds=dur_s)),
        "breaks": entry.get("breaks", []),
    }


def channel_now(db, ch, now):
    entries = sorted(
        (e for e in db["schedule"] if e["channelId"] == ch["id"]),
        key=lambda e: e["start"])
    head = {"channelId": ch["id"], "number": ch["number"], "name": ch["name"]}
    nxt = None
    for e in entries:
        pub = public_entry(db, e)
        start = parse_ts(e["start"])
        end = start + timedelta(seconds=pub["durationMinutes"] * 60)
        if start <= now < end:
            off = (now - start).total_seconds()
            for b in e.get("breaks", []):
                bs = b["atMinutes"] * 60
                be = bs + b["durationMinutes"] * 60
                if bs <= off < be:
                    return dict(head, state="break", entry=pub, offsetSeconds=round(off, 1),
                                brk={"id": b["id"], "label": b["label"],
                                     "remainingSeconds": round(be - off, 1),
                                     "durationSeconds": b["durationMinutes"] * 60})
            return dict(head, state="program", entry=pub, offsetSeconds=round(off, 1))
        if start > now and nxt is None:
            nxt = pub
    return dict(head, state="offair", next=nxt)


def need(body, key):
    if key not in body or body[key] in (None, ""):
        raise ApiError(400, "missing field: %s" % key)
    return body[key]


def check_pin(db, body):
    if body.get("pin") != db.get("pin"):
        raise ApiError(401, "wrong pin")


def list_media():
    try:
        return sorted(f for f in os.listdir(MEDIA_DIR)
                      if os.path.isfile(os.path.join(MEDIA_DIR, f)) and not f.endswith(".txt"))
    except FileNotFoundError:
        return []


def api_now(body, db):
    now = now_dt()
    return {"serverTime": iso(now),
            "channels": [channel_now(db, c, now) for c in db["channels"]]}


def api_login(body, db):
    check_pin(db, body)
    return {"ok": True}


def api_data(body, db):
    check_pin(db, body)
    data = {k: v for k, v in db.items() if k != "pin"}
    data["schedule"] = [public_entry(db, e) for e in db["schedule"]]
    data["mediaFiles"] = list_media()
    return data


def api_library_add(body, db):
    check_pin(db, body)
    title = str(need(body, "title")).strip()[:120]
    kind = need(body, "kind")
    if kind not in ("show", "movie"):
        raise ApiError(400, "kind must be 'show' or 'movie'")
    try:
        dur = int(need(body, "durationMinutes"))
    except (TypeError, ValueError):
        raise ApiError(400, "durationMinutes must be a number")
    if dur <= 0 or dur > 24 * 60:
        raise ApiError(400, "durationMinutes out of range")
    src = body.get("src") or None
    if src:
        src = os.path.basename(str(src))
        if src not in list_media():
            raise ApiError(400, "src must be a file in media/")
    item = {"id": "lib-" + uuid.uuid4().hex[:8], "title": title,
            "kind": kind, "durationMinutes": dur, "src": src}
    db["library"].append(item)
    return item


def api_library_delete(body, db):
    check_pin(db, body)
    item_id = need(body, "id")
    db["library"] = [i for i in db["library"] if i["id"] != item_id]
    for e in db["schedule"]:
        if e["libraryId"] == item_id:
            e["libraryId"] = None
    return {"ok": True}


def api_schedule_add(body, db):
    check_pin(db, body)
    channel_id = need(body, "channelId")
    library_id = need(body, "libraryId")
    start = need(body, "start")
    if not any(c["id"] == channel_id for c in db["channels"]):
        raise ApiError(400, "unknown channelId")
    if not find_lib(db, library_id):
        raise ApiError(400, "unknown libraryId")
    try:
        parse_ts(start)
    except ValueError:
        raise ApiError(400, "start must be an ISO datetime")
    breaks = []
    for b in body.get("breaks") or []:
        breaks.append({"id": "b-" + uuid.uuid4().hex[:8],
                       "label": str(b.get("label") or "Break")[:60],
                       "atMinutes": int(b.get("atMinutes", 0)),
                       "durationMinutes": int(b.get("durationMinutes", 1))})
    entry = {"id": "s-" + uuid.uuid4().hex[:8], "channelId": channel_id,
             "libraryId": library_id, "start": start, "breaks": breaks}
    db["schedule"].append(entry)
    return public_entry(db, entry)


def api_schedule_delete(body, db):
    check_pin(db, body)
    entry_id = need(body, "id")
    db["schedule"] = [e for e in db["schedule"] if e["id"] != entry_id]
    return {"ok": True}


def api_schedule_setstart(body, db):
    check_pin(db, body)
    entry_id = need(body, "id")
    start = need(body, "start")
    try:
        parse_ts(start)
    except ValueError:
        raise ApiError(400, "start must be an ISO datetime")
    for e in db["schedule"]:
        if e["id"] == entry_id:
            e["start"] = start
            return public_entry(db, e)
    raise ApiError(404, "schedule entry not found")


def _find_entry(db, entry_id):
    for e in db["schedule"]:
        if e["id"] == entry_id:
            return e
    raise ApiError(404, "schedule entry not found")


def api_break_add(body, db):
    check_pin(db, body)
    entry = _find_entry(db, need(body, "scheduleId"))
    label = str(need(body, "label")).strip()[:60] or "Break"
    try:
        at = int(need(body, "atMinutes"))
        dur = int(need(body, "durationMinutes"))
    except (TypeError, ValueError):
        raise ApiError(400, "atMinutes/durationMinutes must be numbers")
    if at < 0 or dur <= 0:
        raise ApiError(400, "invalid break values")
    brk = {"id": "b-" + uuid.uuid4().hex[:8], "label": label,
           "atMinutes": at, "durationMinutes": dur}
    entry.setdefault("breaks", []).append(brk)
    return brk


def api_break_delete(body, db):
    check_pin(db, body)
    entry = _find_entry(db, need(body, "scheduleId"))
    brk_id = need(body, "breakId")
    entry["breaks"] = [b for b in entry.get("breaks", []) if b["id"] != brk_id]
    return {"ok": True}


def api_channel_rename(body, db):
    check_pin(db, body)
    ch_id = need(body, "id")
    name = str(need(body, "name")).strip()[:30]
    for c in db["channels"]:
        if c["id"] == ch_id:
            c["name"] = name
            return c
    raise ApiError(404, "channel not found")


def api_pin_change(body, db):
    check_pin(db, body)
    new_pin = str(need(body, "newPin")).strip()
    if not (4 <= len(new_pin) <= 8 and new_pin.isdigit()):
        raise ApiError(400, "newPin must be 4-8 digits")
    db["pin"] = new_pin
    return {"ok": True}


POST_ROUTES = {
    "/api/parent/login": (api_login, False),
    "/api/parent/data": (api_data, False),
    "/api/parent/library/add": (api_library_add, True),
    "/api/parent/library/delete": (api_library_delete, True),
    "/api/parent/schedule/add": (api_schedule_add, True),
    "/api/parent/schedule/delete": (api_schedule_delete, True),
    "/api/parent/schedule/setstart": (api_schedule_setstart, True),
    "/api/parent/break/add": (api_break_add, True),
    "/api/parent/break/delete": (api_break_delete, True),
    "/api/parent/channel/rename": (api_channel_rename, True),
    "/api/parent/pin/change": (api_pin_change, True),
}

ROOT_ROUTES = {
    "/": "tv.html",
    "/tv": "tv.html",
    "/parent": "parent.html",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "RetroTV/0.1"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, fp, status=200, extra_headers=None, range_header=None):
        size = os.path.getsize(fp)
        ctype = MIME.get(os.path.splitext(fp)[1].lower(), "application/octet-stream")
        headers = {"Content-Type": ctype, "Accept-Ranges": "bytes"}
        if extra_headers:
            headers.update(extra_headers)
        start, end = 0, size - 1
        if range_header:
            try:
                unit, _, rng = range_header.partition("=")
                s, _, e = rng.partition("-")
                if s:
                    start = int(s)
                if e:
                    end = min(int(e), size - 1)
                if unit == "bytes" and start <= end < size:
                    status = 206
                    headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
            except ValueError:
                pass
        length = end - start + 1 if size else 0
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if self.command != "HEAD":
            with open(fp, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 10_000_000:
            raise ApiError(413, "body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            raise ApiError(400, "invalid JSON body")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/health":
                return self.send_json({"ok": True, "server": "RetroTV"})
            if path == "/api/now":
                return self.send_json(api_now({}, load_db()))
            if path in ROOT_ROUTES:
                return self.send_file(os.path.join(STATIC_DIR, ROOT_ROUTES[path]))
            if path.startswith("/static/"):
                fp = os.path.realpath(os.path.join(STATIC_DIR, path[len("/static/"):]))
                if fp.startswith(os.path.realpath(STATIC_DIR) + os.sep) and os.path.isfile(fp):
                    return self.send_file(fp)
                raise ApiError(404, "not found")
            if path.startswith("/media/"):
                name = os.path.basename(path[len("/media/"):])
                fp = os.path.join(MEDIA_DIR, name)
                if name and os.path.isfile(fp):
                    return self.send_file(fp, range_header=self.headers.get("Range"))
                raise ApiError(404, "not found")
            raise ApiError(404, "not found")
        except ApiError as e:
            self.send_json({"error": e.msg}, status=e.status)
        except BrokenPipeError:
            pass
        except Exception as e:
            self.send_json({"error": "internal: %s" % e}, status=500)

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            body = self.read_body()
            if path not in POST_ROUTES:
                raise ApiError(404, "not found")
            fn, mutates = POST_ROUTES[path]
            db = load_db()
            result = fn(body, db)
            if mutates:
                save_db(db)
            self.send_json(result)
        except ApiError as e:
            self.send_json({"error": e.msg}, status=e.status)
        except BrokenPipeError:
            pass
        except Exception as e:
            self.send_json({"error": "internal: %s" % e}, status=500)


def main():
    ensure_db()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("RetroTV running:")
    print("  kids TV      -> http://%s:%d/" % (HOST, PORT))
    print("  parent view  -> http://%s:%d/parent  (default PIN 1234)" % (HOST, PORT))
    srv.serve_forever()


if __name__ == "__main__":
    main()
