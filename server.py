# Servidor de Musify: sirve la web (carpeta static), busca con ytmusicapi
# y obtiene audio de Piped probando varias instancias hasta que una responda.
import functools, json, os, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from ytmusicapi import YTMusic

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT = "https://pipedapi.kavin.rocks,https://pipedapi.adminforge.de,https://api.piped.private.coffee"
INSTANCES = [i.strip().rstrip("/") for i in os.environ.get("PIPED_INSTANCES", DEFAULT).split(",") if i.strip()]
yt = YTMusic()

def piped_get(path):
    err = None
    for base in INSTANCES:
        try:
            req = urllib.request.Request(base + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                return json.load(r)
        except Exception as e:
            err = e
    raise RuntimeError(f"Ninguna instancia respondió: {err}")

def search_ytm(q):
    out = []
    for r in yt.search(q, filter="songs", limit=20):
        if r.get("videoId"):
            out.append({"id": r["videoId"], "t": r["title"],
                        "a": ", ".join(a["name"] for a in r.get("artists") or []),
                        "img": (r.get("thumbnails") or [{}])[-1].get("url", "")})
    return out

def search_piped(q):
    d = piped_get("/search?q=" + urllib.parse.quote(q) + "&filter=music_songs")
    return [{"id": x["url"].split("v=")[1], "t": x["title"], "a": x.get("uploaderName", ""), "img": x.get("thumbnail", "")}
            for x in d.get("items", []) if "v=" in x.get("url", "")]

def stream_piped(vid):
    streams = piped_get("/streams/" + urllib.parse.quote(vid)).get("audioStreams") or []
    if not streams:
        raise RuntimeError("Sin audio disponible")
    return {"url": max(streams, key=lambda s: s.get("bitrate", 0))["url"]}

def radio(vid):
    d = yt.get_watch_playlist(videoId=vid, radio=True, limit=25)
    out = []
    for r in d.get("tracks", []):
        if r.get("videoId") and r["videoId"] != vid:
            out.append({"id": r["videoId"], "t": r["title"],
                        "a": ", ".join(a["name"] for a in r.get("artists") or []),
                        "img": (r.get("thumbnail") or [{}])[-1].get("url", "")})
    return out

def lrclib(path):
    req = urllib.request.Request("https://lrclib.net/api" + path, headers={"User-Agent": "Musify/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r)

def lyrics(artist, title):
    j = None
    try:
        j = lrclib("/get?" + urllib.parse.urlencode({"artist_name": artist, "track_name": title}))
    except Exception:
        pass
    if not j or not (j.get("syncedLyrics") or j.get("plainLyrics")):
        try:
            res = lrclib("/search?" + urllib.parse.urlencode({"q": (artist + " " + title).strip()}))
        except Exception:
            res = []
        j = next((x for x in res if x.get("syncedLyrics")), None) or next((x for x in res if x.get("plainLyrics")), {})
    return {"synced": j.get("syncedLyrics") or "", "plain": j.get("plainLyrics") or ""}

def lyric_search(q):
    seen, out = set(), []
    for x in search_ytm(q) + search_ytm(q + " letra lyrics"):
        if x["id"] not in seen:
            seen.add(x["id"])
            out.append(x)
    return out

class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = urllib.parse.parse_qs(u.query)
        routes = {"/api/search": lambda: search_ytm(p["q"][0]),
                  "/api/radio": lambda: radio(p["id"][0]),
                  "/api/lyrics": lambda: lyrics(p.get("artist", [""])[0], p.get("title", [""])[0]),
                  "/api/lyricsearch": lambda: lyric_search(p["q"][0]),
                  "/api/piped/search": lambda: search_piped(p["q"][0]),
                  "/api/piped/stream": lambda: stream_piped(p["id"][0])}
        if u.path not in routes:
            return super().do_GET()
        try:
            body, code = json.dumps(routes[u.path]()).encode(), 200
        except Exception as e:
            body, code = json.dumps({"error": str(e)}).encode(), 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Musify en http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), functools.partial(H, directory=ROOT)).serve_forever()
