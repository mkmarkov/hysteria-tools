"""Hysteria Forever raid roster server.

Python standard library only. Run:  python server.py   (default port 8787)
Share with:                          ngrok http 8787
"""
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "roster.json")
BACKUPS = os.path.join(ROOT, "data", "backups")
PORT = int(os.environ.get("PORT", "8787"))
KEEP_BACKUPS = 50

CLASSES = {
    "Warrior": ["Protection", "Arms", "Fury"],
    "Warlock": ["Affliction", "Destruction", "Demonology"],
    "Mage": ["Arcane", "Fire", "Frost"],
    "Priest": ["Shadow", "Holy", "Discipline"],
    "Druid": ["Feral (Tank)", "Feral (DPS)", "Balance", "Restoration"],
    "Shaman": ["Elemental", "Enhancement", "Restoration"],
    "Paladin": ["Protection", "Retribution", "Holy"],
    "Rogue": ["Combat", "Assassination", "Subtlety"],
    "Hunter": ["Marksmanship", "Beast Mastery", "Survival"],
}

lock = threading.Lock()
changed = threading.Condition(lock)  # notified after every saved change (long-poll wake-up)
LONG_POLL_SECONDS = 25


class OpError(Exception):
    pass


def load_db():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    os.makedirs(BACKUPS, exist_ok=True)
    if os.path.exists(DATA):
        shutil.copy2(DATA, os.path.join(BACKUPS, time.strftime("roster-%Y%m%d-%H%M%S-") + str(db["version"]) + ".json"))
        old = sorted(os.listdir(BACKUPS))
        for name in old[:-KEEP_BACKUPS]:
            os.remove(os.path.join(BACKUPS, name))
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)


# ---------- state helpers ----------

def find_player(st, pid):
    for p in st["players"]:
        if p["id"] == pid:
            return p
    raise OpError("Player not found")


def find_char(p, cid):
    for c in p["chars"]:
        if c["id"] == cid:
            return c
    raise OpError("Character not found")


def find_group(st, gid):
    for g in st["groups"]:
        if g["id"] == gid:
            return g
    raise OpError("Group not found")


def find_slot(st, sid):
    for g in st["groups"]:
        for s in g["slots"]:
            if s["id"] == sid:
                return g, s
    raise OpError("Slot not found")


def new_id(st, prefix):
    st["nextId"] += 1
    return f"{prefix}{st['nextId']}"


def clean_name(name):
    name = (name or "").strip()
    if not name or len(name) > 40:
        raise OpError("Name must be 1-40 characters")
    return name


def clean_chars(p, chars, st):
    """Validate an edited character list; keep existing ids so group slots survive."""
    out, seen = [], set()
    for c in chars or []:
        cls = c.get("cls")
        if cls not in CLASSES:
            raise OpError(f"Unknown class {cls!r}")
        if cls in seen:
            raise OpError(f"{cls} listed twice for this player")
        seen.add(cls)
        specs = []  # keep the player's preferred order, valid specs only
        for s in c.get("specs") or []:
            if s in CLASSES[cls] and s not in specs:
                specs.append(s)
        if not specs:
            raise OpError(f"Pick at least one {cls} spec")
        cid = c.get("id")
        if not cid or not any(x["id"] == cid for x in p["chars"]):
            cid = new_id(st, p["id"] + "-c")
        out.append({"id": cid, "cls": cls, "specs": specs, "kind": "alt" if c.get("kind") == "alt" else "main"})
    return out


def drop_orphan_slots(st):
    valid = {(p["id"], c["id"]): c for p in st["players"] for c in p["chars"]}
    for g in st["groups"]:
        g["slots"] = [s for s in g["slots"] if (s["pid"], s["cid"]) in valid]
        for s in g["slots"]:
            c = valid[(s["pid"], s["cid"])]
            if s["spec"] not in c["specs"]:
                s["spec"] = c["specs"][0]
        if g["leader"] and not any(s["pid"] == g["leader"] for s in g["slots"]):
            g["leader"] = None


def assert_free(st, pid, cid, except_sid=None):
    for g in st["groups"]:
        for s in g["slots"]:
            if s["pid"] == pid and s["cid"] == cid and s["id"] != except_sid:
                raise OpError(f"That character is already in {g['name']}")


def assert_room(g):
    if len(g["slots"]) >= g["size"]:
        raise OpError(f"{g['name']} is full ({g['size']})")


def apply_op(st, op):
    kind = op.get("op")
    if kind == "addPlayer":
        pid = new_id(st, "p")
        p = {"id": pid, "name": clean_name(op.get("name")), "note": (op.get("note") or "")[:200], "chars": []}
        if any(x["name"].lower() == p["name"].lower() for x in st["players"]):
            raise OpError("A player with that name already exists")
        p["chars"] = clean_chars(p, op.get("chars"), st)
        if not p["chars"]:
            raise OpError("Add at least one class")
        st["players"].append(p)
    elif kind == "updatePlayer":
        p = find_player(st, op.get("pid"))
        name = clean_name(op.get("name"))
        if any(x["name"].lower() == name.lower() and x["id"] != p["id"] for x in st["players"]):
            raise OpError("A player with that name already exists")
        chars = clean_chars(p, op.get("chars"), st)
        if not chars:
            raise OpError("Add at least one class")
        p["name"], p["note"], p["chars"] = name, (op.get("note") or "")[:200], chars
        drop_orphan_slots(st)
    elif kind == "deletePlayer":
        p = find_player(st, op.get("pid"))
        st["players"].remove(p)
        drop_orphan_slots(st)
    elif kind == "assign":
        p = find_player(st, op.get("pid"))
        c = find_char(p, op.get("cid"))
        g = find_group(st, op.get("gid"))
        assert_free(st, p["id"], c["id"])
        assert_room(g)
        spec = op.get("spec") if op.get("spec") in c["specs"] else c["specs"][0]
        g["slots"].append({"id": new_id(st, "s"), "pid": p["id"], "cid": c["id"], "spec": spec})
    elif kind == "move":
        src, s = find_slot(st, op.get("sid"))
        dst = find_group(st, op.get("gid"))
        if src is dst:
            return
        assert_room(dst)
        src["slots"].remove(s)
        dst["slots"].append(s)
        drop_orphan_slots(st)
    elif kind == "unassign":
        g, s = find_slot(st, op.get("sid"))
        g["slots"].remove(s)
        drop_orphan_slots(st)
    elif kind == "setSpec":
        # Change what a drafted player brings to this raid: any class/spec. The class is
        # added to the player's profile (as an alt) and the spec to that class if new.
        g, s = find_slot(st, op.get("sid"))
        p = find_player(st, s["pid"])
        cls = op.get("cls") or find_char(p, s["cid"])["cls"]
        spec = op.get("spec")
        if cls not in CLASSES or spec not in CLASSES[cls]:
            raise OpError("Unknown class/spec")
        c = next((c for c in p["chars"] if c["cls"] == cls), None)
        if c is None:
            c = {"id": new_id(st, p["id"] + "-c"), "cls": cls, "specs": [], "kind": "alt"}
            p["chars"].append(c)
        elif c["id"] != s["cid"]:
            assert_free(st, p["id"], c["id"])
        if spec not in c["specs"]:
            c["specs"].append(spec)
        s["cid"], s["spec"] = c["id"], spec
    elif kind == "setLeader":
        g = find_group(st, op.get("gid"))
        pid = op.get("pid")
        if pid:
            find_player(st, pid)
            if not any(s["pid"] == pid for s in g["slots"]):
                raise OpError("The leader has to be in the group")
            for other in st["groups"]:
                if other is not g and other["leader"] == pid:
                    raise OpError(f"Already leading {other['name']}")
        g["leader"] = pid or None
    elif kind == "updateGroup":
        g = find_group(st, op.get("gid"))
        if "name" in op:
            g["name"] = clean_name(op["name"])
        if "size" in op:
            size = int(op["size"])
            if size < len(g["slots"]) or not 1 <= size <= 40:
                raise OpError(f"Size must be between {max(1, len(g['slots']))} and 40")
            g["size"] = size
    elif kind == "clearGroup":
        g = find_group(st, op.get("gid"))
        g["slots"], g["leader"] = [], None
    else:
        raise OpError("Unknown operation")


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "Roster/1.0"

    def log_message(self, fmt, *args):
        if "/api/state" not in (args[0] if args else ""):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/state":
            qs = parse_qs(url.query)
            since = qs.get("since", [None])[0]
            with lock:
                db = load_db()
                if since and "wait" in qs and since == str(db["version"]):
                    # Long poll: hold the request until something changes (keeps ngrok request count low)
                    changed.wait(LONG_POLL_SECONDS)
                    db = load_db()
            if since and since == str(db["version"]):
                self.send_json(200, {"version": db["version"], "unchanged": True})
            else:
                self.send_json(200, {"version": db["version"], "state": db["state"], "classes": CLASSES})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 100_000:
            return self.send_json(413, {"error": "Request too large"})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "Bad JSON"})
        if url.path != "/api/op":
            return self.send_json(404, {"error": "Not found"})
        with lock:
            db = load_db()
            try:
                apply_op(db["state"], payload)
            except OpError as e:
                return self.send_json(400, {"error": str(e)})
            except (TypeError, ValueError, KeyError):
                return self.send_json(400, {"error": "Invalid request"})
            db["version"] += 1
            save_db(db)
            changed.notify_all()
        self.send_json(200, {"version": db["version"], "state": db["state"], "classes": CLASSES})


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Roster running at http://localhost:{PORT}  (share with: ngrok http {PORT})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
