import base64, functools, hmac, json, os, urllib.parse, urllib.request, logging
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from ytmusicapi import YTMusic

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('musify')

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT = "https://pipedapi.kavin.rocks,https://pipedapi.adminforge.de,https://api.piped.private.coffee"
INSTANCES = [i.strip().rstrip("/") for i in os.environ.get("PIPED_INSTANCES", DEFAULT).split(",") if i.strip()]
yt = YTMusic()

class APIError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg); self.code = code

def piped_get(path):
    err = None
    for base in INSTANCES:
        try:
            req = urllib.request.Request(base + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.load(r)
        except Exception as e:
            err = e; log.warning(f"Piped {base} fallo: {e}")
    raise APIError(f"Ninguna instancia de Piped respondio: {err}", 502)

def search_ytm(q):
    try:
        results = yt.search(q, filter="songs", limit=20)
    except Exception as e:
        raise APIError(f"Error en ytmusicapi: {e}", 502)
    out = []
    for r in results:
        if r.get("videoId"):
            out.append({"id": r["videoId"], "t": r["title"],
                        "a": ", ".join(a["name"] for a in r.get("artists") or []),
                        "img": (r.get("thumbnails") or [{}])[-1].get("url", ""),
                        "dur": r.get("duration_seconds") or 0})
    return out

def search_piped(q):
    d = piped_get("/search?q=" + urllib.parse.quote(q) + "&filter=music_songs")
    out = []
    for x in d.get("items", []):
        url = x.get("url", "")
        if "v=" in url:
            try: vid = url.split("v=")[1].split("&")[0]
            except IndexError: continue
            out.append({"id": vid, "t": x.get("title", ""),
                        "a": x.get("uploaderName", ""),
                        "img": x.get("thumbnail", ""),
                        "dur": x.get("duration", 0)})
    return out

def stream_piped(vid):
    streams = piped_get("/streams/" + urllib.parse.quote(vid)).get("audioStreams") or []
    if not streams:
        raise APIError("Sin audio disponible para este video", 404)
    best = max(streams, key=lambda s: s.get("bitrate", 0))
    return {"url": best["url"], "bitrate": best.get("bitrate", 0), "mimeType": best.get("mimeType", "")}

def radio(vid):
    try:
        d = yt.get_watch_playlist(videoId=vid, radio=True, limit=25)
    except Exception as e:
        raise APIError(f"Error en radio: {e}", 502)
    out = []
    for r in d.get("tracks", []):
        if r.get("videoId") and r["videoId"] != vid:
            out.append({"id": r["videoId"], "t": r["title"],
                        "a": ", ".join(a["name"] for a in r.get("artists") or []),
                        "img": (r.get("thumbnail") or [{}])[-1].get("url", "")})
    return out

def lrclib(path):
    req = urllib.request.Request("https://lrclib.net/api" + path, headers={"User-Agent": "Musify/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

def lyrics(artist, title):
    j = None
    try:
        j = lrclib("/get?" + urllib.parse.urlencode({"artist_name": artist, "track_name": title}))
    except Exception: pass
    if not j or not (j.get("syncedLyrics") or j.get("plainLyrics")):
        try:
            res = lrclib("/search?" + urllib.parse.urlencode({"q": (artist + " " + title).strip()}))
        except Exception: res = []
        if isinstance(res, dict): res = [res]
        j = next((x for x in res if x.get("syncedLyrics")), None) or next((x for x in res if x.get("plainLyrics")), {}) or {}
    return {"synced": j.get("syncedLyrics") or "", "plain": j.get("plainLyrics") or ""}

def lyric_search(q):
    seen, out = set(), []
    for x in search_ytm(q) + search_ytm(q + " letra lyrics"):
        if x["id"] not in seen:
            seen.add(x["id"]); out.append(x)
    return out

class Handler(SimpleHTTPRequestHandler):
    def _authorized(self):
        expected_user = os.environ.get("MUSIFY_TEST_USER")
        expected_password = os.environ.get("MUSIFY_TEST_PASSWORD")
        if not expected_user or not expected_password:
            self.send_error(503, "Private test access is not configured")
            return False
        try:
            scheme, token = self.headers.get("Authorization", "").split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError("Unsupported authorization scheme")
            supplied = base64.b64decode(token, validate=True).decode("utf-8")
            username, password = supplied.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            username, password = "", ""
        if not (hmac.compare_digest(username, expected_user) and
                hmac.compare_digest(password, expected_password)):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Musify test", charset="UTF-8"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    def do_HEAD(self):
        if self._authorized():
            return super().do_HEAD()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()
    @staticmethod
    def _first(params, key):
        if key not in params or not params[key]:
            raise APIError(f"Falta el parametro '{key}'", 400)
        return params[key][0]
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if not self._authorized():
            return
        u = urllib.parse.urlparse(self.path)
        p = urllib.parse.parse_qs(u.query)
        routes = {
            "/api/health": lambda: {"status": "ok", "instances": len(INSTANCES)},
            "/api/search": lambda: search_ytm(self._first(p, "q")),
            "/api/radio": lambda: radio(self._first(p, "id")),
            "/api/lyrics": lambda: lyrics(p.get("artist", [""])[0], self._first(p, "title")),
            "/api/lyricsearch": lambda: lyric_search(self._first(p, "q")),
            "/api/piped/search": lambda: search_piped(self._first(p, "q")),
            "/api/piped/stream": lambda: stream_piped(self._first(p, "id")),
        }
        if u.path in routes:
            try: return self._json(200, routes[u.path]())
            except APIError as e: return self._json(e.code, {"error": str(e)})
            except Exception as e:
                log.exception("Error interno")
                return self._json(500, {"error": f"Error interno: {e}"})
        if u.path.startswith("/api/"):
            return self._json(404, {"error": "Endpoint no encontrado"})
        full = os.path.join(ROOT, u.path.lstrip("/"))
        exts = (".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".json", ".webmanifest", ".ico", ".woff", ".woff2", ".txt")
        if not os.path.exists(full) and not u.path.endswith(exts):
            self.path = "/index.html"
        return super().do_GET()
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Musify en http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), functools.partial(Handler, directory=ROOT)).serve_forever()
