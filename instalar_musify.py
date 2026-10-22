#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instalador de Musify.
Ejecuta: python instalar_musify.py
Crea la carpeta 'musify/' junto a este script con todo el proyecto.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent / "musify"
(BASE / "static").mkdir(parents=True, exist_ok=True)

FILES = {}

FILES["requirements.txt"] = r'''ytmusicapi
'''

FILES["render.yaml"] = r'''services:
  - type: web
    name: musify
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python server.py
'''

FILES["server.py"] = r'''import functools, json, os, urllib.parse, urllib.request, logging
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
'''

FILES["static/manifest.json"] = r'''{
  "name": "Musify",
  "short_name": "Musify",
  "description": "Reproductor de musica con busqueda en YouTube Music",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#0a0416",
  "theme_color": "#a855f7",
  "icons": [
    { "src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable" }
  ]
}
'''

FILES["static/sw.js"] = r'''const CACHE = 'musify-v3';
const ASSETS = ['/', '/index.html', '/manifest.json', '/icon.svg'];
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS).catch(()=>{})));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) return;
  e.respondWith(caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
    const copy = res.clone();
    caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
    return res;
  }).catch(() => caches.match('/index.html'))));
});
'''

FILES["static/icon.svg"] = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#a855f7"/>
      <stop offset="1" stop-color="#ec4899"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="100" fill="url(#g)"/>
  <text x="256" y="340" font-size="280" text-anchor="middle" fill="white" font-family="sans-serif">&#9834;</text>
</svg>
'''

FILES["static/index.html"] = r'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#a855f7">
<title>Musify</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<style>
:root{--bg:#0a0416;--bg2:#150a28;--bg3:#1f0f3a;--card:rgba(255,255,255,.06);--card-2:rgba(255,255,255,.10);--border:rgba(255,255,255,.08);--text:#f5f3ff;--text-dim:#9ca3af;--accent:#a855f7;--accent-2:#ec4899;--accent-rgb:168,85,247;--shadow:0 10px 40px rgba(0,0,0,.5);}
[data-theme="amoled"]{--bg:#000;--bg2:#050505;--bg3:#0a0a0a;--card:rgba(255,255,255,.04);}
[data-theme="light"]{--bg:#f5f3ff;--bg2:#fff;--bg3:#ede9fe;--card:rgba(0,0,0,.04);--card-2:rgba(0,0,0,.08);--border:rgba(0,0,0,.08);--text:#1e1b4b;--text-dim:#6b7280;}
[data-accent="pink"]{--accent:#ec4899;--accent-2:#f43f5e;--accent-rgb:236,72,153;}
[data-accent="cyan"]{--accent:#06b6d4;--accent-2:#3b82f6;--accent-rgb:6,182,212;}
[data-accent="green"]{--accent:#10b981;--accent-2:#06b6d4;--accent-rgb:16,185,129;}
[data-accent="orange"]{--accent:#f97316;--accent-2:#ef4444;--accent-rgb:249,115,22;}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;}
html,body{height:100%;overflow:hidden;}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:15px;line-height:1.4;display:flex;flex-direction:column;}
.bg-gradient{position:fixed;inset:0;z-index:-1;transition:background .5s;background:radial-gradient(circle at 20% 0%,rgba(var(--accent-rgb),.25),transparent 45%),radial-gradient(circle at 80% 100%,rgba(var(--accent-rgb),.15),transparent 45%),linear-gradient(180deg,var(--bg) 0%,var(--bg2) 100%);}
header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px 8px;flex-shrink:0;}
.logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:22px;letter-spacing:-.5px;}
.logo-icon{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent-2));display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 20px rgba(var(--accent-rgb),.4);}
.logo-text span{color:var(--accent);}
.icon-btn{width:40px;height:40px;border-radius:50%;border:none;background:var(--card);color:var(--text);font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .2s;}
.icon-btn:hover{background:var(--card-2);transform:scale(1.05);}
.search-wrap{padding:8px 20px;flex-shrink:0;}
.search-box{position:relative;display:flex;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:0 8px 0 16px;transition:all .2s;}
.search-box:focus-within{border-color:var(--accent);box-shadow:0 0 0 4px rgba(var(--accent-rgb),.15);}
.search-box input{flex:1;background:transparent;border:none;color:var(--text);font-size:16px;padding:14px 0;outline:none;}
.search-box input::placeholder{color:var(--text-dim);}
.search-box .search-btn{background:linear-gradient(135deg,var(--accent),var(--accent-2));border:none;color:#fff;width:40px;height:40px;border-radius:12px;font-size:18px;cursor:pointer;transition:transform .15s;}
.search-box .search-btn:active{transform:scale(.95);}
.tabs{display:flex;gap:6px;padding:8px 20px;flex-shrink:0;overflow-x:auto;scrollbar-width:none;}
.tabs::-webkit-scrollbar{display:none;}
.tab{flex-shrink:0;padding:10px 18px;border-radius:12px;background:transparent;border:1px solid var(--border);color:var(--text-dim);font-weight:600;font-size:14px;cursor:pointer;transition:all .2s;}
.tab.active{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;border-color:transparent;box-shadow:0 4px 20px rgba(var(--accent-rgb),.4);}
main{flex:1;overflow-y:auto;overflow-x:hidden;padding:8px 16px 160px;scrollbar-width:thin;scrollbar-color:var(--accent) transparent;}
main::-webkit-scrollbar{width:6px;}
main::-webkit-scrollbar-thumb{background:var(--accent);border-radius:3px;}
.section{display:none;}
.section.active{display:block;animation:fadeIn .3s;}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:none;}}
.section-title{font-size:18px;font-weight:700;margin:16px 4px 12px;display:flex;align-items:center;justify-content:space-between;}
.section-title small{font-size:12px;color:var(--text-dim);font-weight:500;}
.song-list{display:flex;flex-direction:column;gap:4px;}
.song-item{display:flex;align-items:center;gap:12px;padding:8px;border-radius:12px;cursor:pointer;transition:background .15s;}
.song-item:hover{background:var(--card);}
.song-item.playing{background:linear-gradient(90deg,rgba(var(--accent-rgb),.2),transparent);border-left:3px solid var(--accent);padding-left:5px;}
.song-cover{width:52px;height:52px;border-radius:10px;object-fit:cover;background:var(--card);flex-shrink:0;}
.song-info{flex:1;min-width:0;}
.song-title{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.song-artist{font-size:13px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.song-actions{display:flex;gap:4px;flex-shrink:0;}
.mini-btn{width:34px;height:34px;border-radius:50%;border:none;background:var(--card);color:var(--text);font-size:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;}
.mini-btn:hover{background:var(--accent);color:#fff;transform:scale(1.1);}
.empty{text-align:center;padding:48px 20px;color:var(--text-dim);}
.empty-icon{font-size:64px;margin-bottom:16px;opacity:.5;}
.empty h3{font-size:18px;color:var(--text);margin-bottom:8px;}
.empty p{font-size:14px;}
.playlist-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:16px;}
.playlist-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;cursor:pointer;transition:all .2s;overflow:hidden;}
.playlist-card:hover{transform:translateY(-3px);box-shadow:var(--shadow);border-color:var(--accent);}
.playlist-card .pl-icon{width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--accent-2));display:flex;align-items:center;justify-content:center;font-size:24px;margin-bottom:12px;}
.playlist-card .pl-name{font-weight:700;font-size:15px;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.playlist-card .pl-count{font-size:12px;color:var(--text-dim);}
.player{position:fixed;left:0;right:0;bottom:0;background:linear-gradient(180deg,var(--bg2),var(--bg));border-top:1px solid var(--border);padding:8px 12px 12px;z-index:100;transform:translateY(100%);transition:transform .3s ease;backdrop-filter:blur(20px);box-shadow:0 -8px 40px rgba(0,0,0,.4);}
.player.active{transform:translateY(0);}
.player-progress{height:4px;background:var(--card-2);border-radius:2px;margin-bottom:8px;cursor:pointer;position:relative;overflow:hidden;}
.player-progress-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2));width:0%;transition:width .1s linear;border-radius:2px;}
.player-main{display:flex;align-items:center;gap:10px;}
.player-cover{width:48px;height:48px;border-radius:10px;object-fit:cover;background:var(--card);flex-shrink:0;cursor:pointer;}
.player-info{flex:1;min-width:0;}
.player-title{font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.player-artist{font-size:12px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.player-controls{display:flex;gap:4px;align-items:center;}
.play-btn{width:44px;height:44px;border-radius:50%;border:none;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;font-size:18px;cursor:pointer;box-shadow:0 4px 20px rgba(var(--accent-rgb),.4);display:flex;align-items:center;justify-content:center;transition:transform .15s;}
.play-btn:active{transform:scale(.92);}
.skip-btn{width:36px;height:36px;border-radius:50%;border:none;background:var(--card);color:var(--text);font-size:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;}
.skip-btn:hover{background:var(--card-2);}
.player-times{display:flex;justify-content:space-between;font-size:11px;color:var(--text-dim);margin-top:4px;padding:0 2px;}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);display:none;align-items:flex-end;justify-content:center;z-index:200;animation:fadeIn .2s;}
.modal-overlay.active{display:flex;}
.modal{background:var(--bg2);border-top-left-radius:24px;border-top-right-radius:24px;padding:20px;width:100%;max-width:500px;max-height:85vh;overflow-y:auto;animation:slideUp .3s;border-top:1px solid var(--border);}
@keyframes slideUp{from{transform:translateY(100%);}to{transform:none;}}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;}
.modal-title{font-size:20px;font-weight:700;}
.modal-close{width:36px;height:36px;border-radius:50%;border:none;background:var(--card);color:var(--text);font-size:18px;cursor:pointer;}
.modal-section{margin-bottom:24px;}
.modal-label{font-size:13px;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;}
.theme-grid,.color-grid{display:flex;gap:8px;flex-wrap:wrap;}
.theme-option{padding:10px 16px;border-radius:12px;border:2px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:14px;font-weight:600;transition:all .2s;}
.theme-option.active{border-color:var(--accent);background:rgba(var(--accent-rgb),.15);}
.color-option{width:44px;height:44px;border-radius:50%;padding:0;border-width:3px;cursor:pointer;border:2px solid var(--border);transition:transform .15s;}
.color-option.active{transform:scale(1.15);border-color:#fff;}
.color-option[data-c="purple"]{background:#a855f7;}
.color-option[data-c="pink"]{background:#ec4899;}
.color-option[data-c="cyan"]{background:#06b6d4;}
.color-option[data-c="green"]{background:#10b981;}
.color-option[data-c="orange"]{background:#f97316;}
.toast{position:fixed;bottom:110px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--bg3);color:var(--text);padding:12px 20px;border-radius:12px;border:1px solid var(--accent);box-shadow:var(--shadow);font-size:14px;opacity:0;pointer-events:none;transition:all .3s;z-index:300;max-width:90%;text-align:center;}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0);}
.lyrics-panel{position:fixed;inset:0;background:linear-gradient(180deg,var(--bg2),var(--bg));z-index:250;padding:20px;display:none;flex-direction:column;overflow-y:auto;}
.lyrics-panel.active{display:flex;}
.lyrics-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;}
.lyrics-content{flex:1;text-align:center;padding:20px 0 200px;overflow-y:auto;}
.lyric-line{font-size:18px;font-weight:600;padding:12px 8px;color:var(--text-dim);transition:all .3s;line-height:1.4;}
.lyric-line.active{color:var(--accent);font-size:22px;transform:scale(1.05);text-shadow:0 0 20px rgba(var(--accent-rgb),.5);}
.spinner{width:40px;height:40px;border:4px solid var(--card-2);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:40px auto;}
@keyframes spin{to{transform:rotate(360deg);}}
.fab{position:fixed;right:20px;bottom:110px;width:56px;height:56px;border-radius:50%;border:none;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;font-size:24px;cursor:pointer;box-shadow:0 8px 30px rgba(var(--accent-rgb),.5);z-index:90;display:none;align-items:center;justify-content:center;transition:transform .15s;}
.fab:active{transform:scale(.9);}
.fab.visible{display:flex;}
</style>
</head>
<body data-theme="dark" data-accent="purple">
<div class="bg-gradient"></div>
<header>
  <div class="logo"><div class="logo-icon">&#9834;</div><div class="logo-text">Mus<span>ify</span></div></div>
  <button class="icon-btn" id="settings-btn" title="Ajustes">&#9881;</button>
</header>
<div class="search-wrap">
  <div class="search-box">
    <input type="text" id="search-input" placeholder="Buscar canciones, artistas..." autocomplete="off">
    <button class="search-btn" id="search-btn">&#128269;</button>
  </div>
</div>
<nav class="tabs">
  <button class="tab active" data-tab="home">Inicio</button>
  <button class="tab" data-tab="search">Resultados</button>
  <button class="tab" data-tab="library">Biblioteca</button>
</nav>
<main>
  <section class="section active" id="sec-home">
    <div class="section-title">Bienvenido a Musify <small>Tu musica con color</small></div>
    <div class="empty" id="home-empty">
      <div class="empty-icon">&#127925;</div>
      <h3>Busca tu musica favorita</h3>
      <p>Escribe arriba y presiona buscar para empezar.</p>
    </div>
    <div class="section-title" id="recent-home-title" style="display:none">Escuchado recientemente</div>
    <div class="song-list" id="recent-home-list"></div>
  </section>
  <section class="section" id="sec-search">
    <div class="section-title">Resultados <small id="search-count"></small></div>
    <div class="song-list" id="search-results"></div>
  </section>
  <section class="section" id="sec-library">
    <div class="section-title">Playlists</div>
    <div class="playlist-grid" id="playlists-grid"></div>
    <div class="section-title">Historial reciente</div>
    <div class="song-list" id="recent-list"></div>
  </section>
</main>
<button class="fab" id="fab">&#65291;</button>
<div class="player" id="player">
  <div class="player-progress" id="player-progress"><div class="player-progress-fill" id="player-fill"></div></div>
  <div class="player-main">
    <img class="player-cover" id="player-cover" src="" alt="">
    <div class="player-info">
      <div class="player-title" id="player-title">-</div>
      <div class="player-artist" id="player-artist">-</div>
    </div>
    <div class="player-controls">
      <button class="skip-btn" id="prev-btn">&#9198;</button>
      <button class="play-btn" id="play-btn">&#9654;</button>
      <button class="skip-btn" id="next-btn">&#9197;</button>
    </div>
  </div>
  <div class="player-times"><span id="current-time">0:00</span><span id="total-time">0:00</span></div>
</div>
<audio id="audio" preload="metadata"></audio>
<div class="modal-overlay" id="settings-modal">
  <div class="modal">
    <div class="modal-header"><div class="modal-title">&#9881; Ajustes</div><button class="modal-close" id="settings-close">&#10005;</button></div>
    <div class="modal-section">
      <div class="modal-label">Tema</div>
      <div class="theme-grid">
        <button class="theme-option active" data-theme="dark">Oscuro</button>
        <button class="theme-option" data-theme="amoled">AMOLED</button>
        <button class="theme-option" data-theme="light">Claro</button>
      </div>
    </div>
    <div class="modal-section">
      <div class="modal-label">Color de acento</div>
      <div class="color-grid">
        <button class="color-option active" data-c="purple" title="Morado"></button>
        <button class="color-option" data-c="pink" title="Rosa"></button>
        <button class="color-option" data-c="cyan" title="Cian"></button>
        <button class="color-option" data-c="green" title="Verde"></button>
        <button class="color-option" data-c="orange" title="Naranja"></button>
      </div>
    </div>
    <div class="modal-section">
      <div class="modal-label">Reproduccion</div>
      <label style="display:flex;align-items:center;gap:10px;padding:12px;background:var(--card);border-radius:12px;cursor:pointer;">
        <input type="checkbox" id="autoplay-radio" checked>
        <span style="flex:1;">Radio automatica al terminar la cola</span>
      </label>
    </div>
    <div class="modal-section">
      <div class="modal-label">Info</div>
      <div style="font-size:13px;color:var(--text-dim);line-height:1.6;padding:12px;background:var(--card);border-radius:12px;">
        <p><strong>Musify v3</strong></p>
        <p>Busqueda en YouTube Music - Streaming via Piped</p>
        <p style="margin-top:8px;">Historial y playlists se guardan en este dispositivo.</p>
      </div>
    </div>
  </div>
</div>
<div class="lyrics-panel" id="lyrics-panel">
  <div class="lyrics-header">
    <div><div class="modal-title" id="lyrics-title">Letra</div><div style="font-size:13px;color:var(--text-dim);" id="lyrics-artist"></div></div>
    <button class="modal-close" id="lyrics-close">&#10005;</button>
  </div>
  <div class="lyrics-content" id="lyrics-content"></div>
</div>
<div class="toast" id="toast"></div>
<script>
'use strict';
const $=s=>document.querySelector(s),$$=s=>document.querySelectorAll(s);
const audio=$('#audio');
const FALLBACK_ICON='data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="%23a855f7"/><stop offset="1" stop-color="%23ec4899"/></linearGradient></defs><rect fill="url(%23g)" width="100" height="100"/><text x="50" y="65" font-size="40" text-anchor="middle" fill="white">&#9834;</text></svg>';
const state={query:'',results:[],queue:[],queueIndex:-1,playing:false,currentSong:null,recent:JSON.parse(localStorage.getItem('musify_recent')||'[]'),playlists:JSON.parse(localStorage.getItem('musify_playlists')||'{}'),theme:localStorage.getItem('musify_theme')||'dark',accent:localStorage.getItem('musify_accent')||'purple',autoplayRadio:localStorage.getItem('musify_radio')!=='0',loading:false,lyricsLines:[]};
function saveState(){localStorage.setItem('musify_recent',JSON.stringify(state.recent.slice(0,100)));localStorage.setItem('musify_playlists',JSON.stringify(state.playlists));localStorage.setItem('musify_theme',state.theme);localStorage.setItem('musify_accent',state.accent);localStorage.setItem('musify_radio',state.autoplayRadio?'1':'0');}
function applyTheme(){document.body.dataset.theme=state.theme;document.body.dataset.accent=state.accent;$$('.theme-option').forEach(b=>b.classList.toggle('active',b.dataset.theme===state.theme));$$('.color-option').forEach(b=>b.classList.toggle('active',b.dataset.c===state.accent));}
let toastTimer;
function toast(msg,d=2500){const el=$('#toast');el.textContent=msg;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),d);}
async function api(path){const res=await fetch(path);if(!res.ok){let msg=`Error ${res.status}`;try{const j=await res.json();if(j.error)msg=j.error;}catch(_){} throw new Error(msg);} return res.json();}
async function getStreamUrl(id){const r=await api('/api/piped/stream?id='+encodeURIComponent(id));if(!r||!r.url)throw new Error('Sin URL de audio');return r.url;}
async function searchSongs(q){return api('/api/search?q='+encodeURIComponent(q));}
async function getRadio(id){return api('/api/radio?id='+encodeURIComponent(id));}
async function getLyrics(a,t){return api('/api/lyrics?artist='+encodeURIComponent(a)+'&title='+encodeURIComponent(t));}
function cover(src){return src||FALLBACK_ICON;}
function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function renderSongList(container,songs,emptyMsg){
  if(!songs||songs.length===0){container.innerHTML='<div class="empty"><div class="empty-icon">&#127925;</div><h3>'+escapeHtml(emptyMsg||'Sin canciones')+'</h3></div>';return;}
  container.innerHTML='';
  songs.forEach((song,idx)=>{
    const item=document.createElement('div');item.className='song-item';
    if(state.currentSong&&state.currentSong.id===song.id)item.classList.add('playing');
    item.innerHTML='<img class="song-cover" src="'+cover(song.img)+'" alt="" loading="lazy"><div class="song-info"><div class="song-title">'+escapeHtml(song.t||'Sin titulo')+'</div><div class="song-artist">'+escapeHtml(song.a||'Desconocido')+'</div></div><div class="song-actions"><button class="mini-btn" data-act="play" title="Reproducir">&#9654;</button><button class="mini-btn" data-act="add" title="Agregar a playlist">&#65291;</button></div>';
    item.querySelector('[data-act="play"]').addEventListener('click',e=>{e.stopPropagation();playFromList(songs,idx);});
    item.querySelector('[data-act="add"]').addEventListener('click',e=>{e.stopPropagation();openPlaylistPicker(song);});
    item.addEventListener('click',()=>playFromList(songs,idx));
    container.appendChild(item);
  });
}
function renderSearchResults(){renderSongList($('#search-results'),state.results,'No hay resultados. Prueba con otra busqueda.');$('#search-count').textContent=state.results.length?state.results.length+' canciones':'';}
function renderRecent(){renderSongList($('#recent-list'),state.recent.slice(0,20),'Aun no has escuchado nada');const title=$('#recent-home-title'),list=$('#recent-home-list');if(state.recent.length>0){title.style.display='block';renderSongList(list,state.recent.slice(0,8),'');$('#home-empty').style.display='none';}else{title.style.display='none';list.innerHTML='';$('#home-empty').style.display='block';}}
function renderPlaylists(){const grid=$('#playlists-grid');const names=Object.keys(state.playlists);if(names.length===0){grid.innerHTML='<div class="empty" style="grid-column:1/-1;"><div class="empty-icon">&#128218;</div><h3>No tienes playlists</h3><p>Toca el boton + para crear una.</p></div>';return;}grid.innerHTML='';names.forEach(name=>{const card=document.createElement('div');card.className='playlist-card';card.innerHTML='<div class="pl-icon">&#128193;</div><div class="pl-name">'+escapeHtml(name)+'</div><div class="pl-count">'+state.playlists[name].length+' canciones</div>';card.addEventListener('click',()=>openPlaylist(name));grid.appendChild(card);});}
function openPlaylist(name){
  const songs=state.playlists[name]||[];
  const container=$('#sec-library');
  container.innerHTML='<div class="section-title"><button class="icon-btn" id="pl-back" style="width:auto;padding:0 12px;border-radius:12px;font-size:14px;">Volver</button><span>'+escapeHtml(name)+'</span><button class="icon-btn" id="pl-del" style="width:auto;padding:0 12px;border-radius:12px;font-size:14px;">Borrar</button></div><div class="song-list" id="pl-songs"></div>';
  renderSongList($('#pl-songs'),songs,'Esta playlist esta vacia');
  $('#pl-back').addEventListener('click',()=>{container.innerHTML='<div class="section-title">Playlists</div><div class="playlist-grid" id="playlists-grid"></div><div class="section-title">Historial reciente</div><div class="song-list" id="recent-list"></div>';renderPlaylists();renderRecent();});
  $('#pl-del').addEventListener('click',()=>{if(confirm('Eliminar la playlist "'+name+'"?')){delete state.playlists[name];saveState();container.innerHTML='<div class="section-title">Playlists</div><div class="playlist-grid" id="playlists-grid"></div><div class="section-title">Historial reciente</div><div class="song-list" id="recent-list"></div>';renderPlaylists();renderRecent();toast('Playlist eliminada');}});
}
function switchTab(tab){$$('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===tab));$$('.section').forEach(s=>s.classList.remove('active'));const t=$('#sec-'+tab);if(t)t.classList.add('active');const fab=$('#fab');if(tab==='library'){fab.classList.add('visible');fab.onclick=createPlaylist;}else fab.classList.remove('visible');}
function createPlaylist(){const name=prompt('Nombre de la nueva playlist:');if(name&&name.trim()){const n=name.trim();if(state.playlists[n]){toast('Ya existe esa playlist');return;}state.playlists[n]=[];saveState();renderPlaylists();toast('Playlist "'+n+'" creada');}}
async function playFromList(songs,idx){state.queue=songs.slice();state.queueIndex=idx;await playCurrent();}
async function playCurrent(){
  const song=state.queue[state.queueIndex];if(!song){toast('No hay cancion');return;}
  state.currentSong=song;
  $('#player-title').textContent=song.t||'Cargando...';
  $('#player-artist').textContent=song.a||'...';
  const coverEl=$('#player-cover');coverEl.src=cover(song.img);coverEl.onerror=()=>{coverEl.src=FALLBACK_ICON;};
  $('#player').classList.add('active');
  try{const url=await getStreamUrl(song.id);audio.src=url;audio.load();await audio.play();state.playing=true;$('#play-btn').innerHTML='&#10074;&#10074;';addToRecent(song);fetchLyricsFor(song);}
  catch(e){console.error(e);toast(e.message||'No se pudo reproducir');$('#play-btn').innerHTML='&#9654;';}
  renderRecent();if($('#sec-search').classList.contains('active'))renderSearchResults();
}
function addToRecent(song){state.recent=state.recent.filter(s=>s.id!==song.id);state.recent.unshift({id:song.id,t:song.t,a:song.a,img:song.img,playedAt:Date.now()});saveState();}
function togglePlay(){if(!state.currentSong){toast('Elige una cancion primero');return;}if(audio.paused){audio.play().then(()=>{state.playing=true;$('#play-btn').innerHTML='&#10074;&#10074;';}).catch(e=>toast('No se pudo reproducir: '+e.message));}else{audio.pause();state.playing=false;$('#play-btn').innerHTML='&#9654;';}}
function nextSong(userTriggered){if(state.queue.length===0)return;if(state.queueIndex<state.queue.length-1){state.queueIndex++;playCurrent();}else if(state.autoplayRadio&&state.currentSong){loadRadioAndPlay();}else{toast('Fin de la cola');if(userTriggered){state.queueIndex=0;playCurrent();}}}
async function loadRadioAndPlay(){toast('Cargando radio...');try{const list=await getRadio(state.currentSong.id);if(!list||list.length===0){toast('No hay radio disponible');return;}const start=state.queue.length;state.queue.push(...list);state.queueIndex=start;playCurrent();}catch(e){toast('Radio fallo: '+e.message);}}
function prevSong(){if(audio.currentTime>3){audio.currentTime=0;return;}if(state.queueIndex>0){state.queueIndex--;playCurrent();}else audio.currentTime=0;}
function formatTime(s){if(!s||isNaN(s))return '0:00';const m=Math.floor(s/60),sec=Math.floor(s%60);return m+':'+sec.toString().padStart(2,'0');}
audio.addEventListener('timeupdate',()=>{if(!audio.duration||isNaN(audio.duration))return;const pct=(audio.currentTime/audio.duration)*100;$('#player-fill').style.width=pct+'%';$('#current-time').textContent=formatTime(audio.currentTime);$('#total-time').textContent=formatTime(audio.duration);updateActiveLyric(audio.currentTime);});
audio.addEventListener('loadedmetadata',()=>{$('#total-time').textContent=formatTime(audio.duration||0);});
audio.addEventListener('ended',()=>nextSong(false));
audio.addEventListener('error',()=>{if(state.currentSong){toast('Error de reproduccion, saltando...');setTimeout(()=>nextSong(false),1200);}});
$('#player-progress').addEventListener('click',e=>{if(!audio.duration)return;const r=e.currentTarget.getBoundingClientRect();audio.currentTime=((e.clientX-r.left)/r.width)*audio.duration;});
async function fetchLyricsFor(song){state.lyricsLines=[];try{const r=await getLyrics(song.a||'',song.t||'');let lines=[];if(r.synced){const re=/\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)/g;let m;while((m=re.exec(r.synced))!==null){const t=+m[1]*60+ +m[2]+parseInt(m[3].padEnd(3,'0'),10)/1000;const txt=m[4].trim();if(txt)lines.push({time:t,text:txt});}lines.sort((a,b)=>a.time-b.time);}else if(r.plain){lines=r.plain.split('\n').map(t=>({time:0,text:t}));}state.lyricsLines=lines;}catch(_){}}
function openLyrics(){if(!state.currentSong){toast('Reproduce una cancion primero');return;}$('#lyrics-title').textContent=state.currentSong.t||'Letra';$('#lyrics-artist').textContent=state.currentSong.a||'';const c=$('#lyrics-content');if(state.lyricsLines.length===0){c.innerHTML='<div class="empty"><div class="empty-icon">&#127908;</div><h3>Sin letra disponible</h3></div>';}else{c.innerHTML=state.lyricsLines.map((l,i)=>'<div class="lyric-line" data-idx="'+i+'">'+escapeHtml(l.text)+'</div>').join('');}$('#lyrics-panel').classList.add('active');}
function updateActiveLyric(cur){const lines=state.lyricsLines;if(!lines.length)return;let idx=-1;for(let i=0;i<lines.length;i++){if(lines[i].time<=cur)idx=i;else break;}if(idx<0)return;const els=$$('.lyric-line');els.forEach((el,i)=>el.classList.toggle('active',i===idx));const el=els[idx];if(el){const panel=$('#lyrics-content');const off=el.offsetTop-panel.clientHeight/2;if(Math.abs(panel.scrollTop-off)>40){panel.scrollTo({top:off,behavior:'smooth'});}}}
function openPlaylistPicker(song){
  const names=Object.keys(state.playlists);
  const opts=names.length?names.map(n=>'<button class="theme-option" data-pl="'+escapeHtml(n)+'" style="width:100%;text-align:left;margin-bottom:6px;">'+escapeHtml(n)+'</button>').join(''):'<p style="color:var(--text-dim);padding:8px;">Crea una playlist primero.</p>';
  const modal=document.createElement('div');modal.className='modal-overlay active';
  modal.innerHTML='<div class="modal"><div class="modal-header"><div class="modal-title">Agregar a playlist</div><button class="modal-close" data-close>&#10005;</button></div><div class="modal-section"><div style="padding:12px;background:var(--card);border-radius:12px;margin-bottom:16px;"><strong>'+escapeHtml(song.t||'')+'</strong><br><small style="color:var(--text-dim);">'+escapeHtml(song.a||'')+'</small></div><div class="modal-label">Elige una playlist</div>'+opts+'<button class="theme-option" id="pl-new-btn" style="width:100%;margin-top:8px;border-color:var(--accent);color:var(--accent);">+ Crear nueva</button></div></div>';
  document.body.appendChild(modal);
  modal.addEventListener('click',e=>{if(e.target===modal||e.target.closest('[data-close]'))modal.remove();});
  modal.querySelectorAll('[data-pl]').forEach(btn=>{btn.addEventListener('click',()=>{const name=btn.dataset.pl;if(!state.playlists[name])state.playlists[name]=[];if(state.playlists[name].some(s=>s.id===song.id))toast('Ya esta en esa playlist');else{state.playlists[name].push(song);saveState();toast('Agregada a "'+name+'"');}modal.remove();renderPlaylists();});});
  const newBtn=modal.querySelector('#pl-new-btn');
  newBtn.addEventListener('click',()=>{const name=prompt('Nombre de la nueva playlist:');if(name&&name.trim()){const n=name.trim();if(!state.playlists[n])state.playlists[n]=[];if(!state.playlists[n].some(s=>s.id===song.id)){state.playlists[n].push(song);saveState();toast('Agregada a "'+n+'"');}modal.remove();renderPlaylists();}});
}
async function doSearch(){
  const q=$('#search-input').value.trim();if(!q){toast('Escribe algo');return;}
  switchTab('search');
  $('#search-results').innerHTML='<div class="spinner"></div>';
  $('#search-count').textContent='Buscando...';
  try{state.results=await searchSongs(q);renderSearchResults();if(state.results.length===0)toast('Sin resultados');}
  catch(e){$('#search-results').innerHTML='<div class="empty"><div class="empty-icon">&#9888;</div><h3>Error de busqueda</h3><p>'+escapeHtml(e.message)+'</p></div>';$('#search-count').textContent='';}
}
function bindEvents(){
  $('#search-btn').addEventListener('click',doSearch);
  $('#search-input').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
  $$('.tab').forEach(t=>t.addEventListener('click',()=>switchTab(t.dataset.tab)));
  $('#play-btn').addEventListener('click',togglePlay);
  $('#next-btn').addEventListener('click',()=>nextSong(true));
  $('#prev-btn').addEventListener('click',prevSong);
  $('#player-cover').addEventListener('dblclick',openLyrics);
  $('#settings-btn').addEventListener('click',()=>{applyTheme();$('#settings-modal').classList.add('active');});
  $('#settings-close').addEventListener('click',()=>$('#settings-modal').classList.remove('active'));
  $('#settings-modal').addEventListener('click',e=>{if(e.target.id==='settings-modal')$('#settings-modal').classList.remove('active');});
  $$('.theme-option[data-theme]').forEach(b=>{b.addEventListener('click',()=>{state.theme=b.dataset.theme;applyTheme();saveState();});});
  $$('.color-option').forEach(b=>{b.addEventListener('click',()=>{state.accent=b.dataset.c;applyTheme();saveState();});});
  $('#autoplay-radio').addEventListener('change',e=>{state.autoplayRadio=e.target.checked;saveState();});
  $('#lyrics-close').addEventListener('click',()=>$('#lyrics-panel').classList.remove('active'));
  document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.code==='Space'){e.preventDefault();togglePlay();}});
}
function init(){
  applyTheme();
  $('#autoplay-radio').checked=state.autoplayRadio;
  bindEvents();
  renderPlaylists();
  renderRecent();
  if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{});}
}
document.addEventListener('DOMContentLoaded',init);
</script>
</body>
</html>
'''

# --- Escribir todos los archivos ---
print()
print("Creando Musify en:", BASE)
print()
for nombre, contenido in FILES.items():
    ruta = BASE / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    print("  OK  " + nombre)

print()
print("=" * 55)
print("LISTO. Carpeta creada:")
print("  " + str(BASE))
print()
print("Para arrancar:")
print('  cd "' + str(BASE) + '"')
print("  pip install -r requirements.txt")
print("  python server.py")
print()
print("Luego abre: http://localhost:8000")
print("=" * 55)