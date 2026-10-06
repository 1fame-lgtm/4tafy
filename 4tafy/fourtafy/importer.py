"""Import de musique : liens (YouTube, Spotify, TikTok, SoundCloud…) et fichiers locaux.

- YouTube / TikTok / SoundCloud / Bandcamp / … : téléchargés avec yt-dlp (titres seuls ou playlists entières).
- Spotify : l'audio Spotify est protégé (DRM). 4tafy lit donc les infos du titre / de la
  playlist / de l'album sur Spotify, puis retrouve chaque morceau sur YouTube.
- Fichiers locaux : mp3, flac, wav, ogg, m4a… (+ dossiers entiers et playlists .m3u).
"""
import html
import json
import queue
import re
import shutil
import threading
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .config import AUDIO_EXTENSIONS, COVERS_DIR, MUSIC_DIR, ensure_dirs
from .matcher import best_match

try:
    import yt_dlp
except ImportError:  # l'appli reste utilisable avec des fichiers locaux
    yt_dlp = None

try:
    import mutagen
except ImportError:
    mutagen = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SOURCE_LABELS = {
    "youtube": "YouTube", "spotify": "Spotify", "tiktok": "TikTok", "soundcloud": "SoundCloud",
    "local": "Fichier local", "web": "Web", "bandcamp": "Bandcamp", "deezer": "Deezer",
}

_JUNK = re.compile(
    r"\s*[\(\[](?:official\s*)?(?:music\s*|lyric[s]?\s*|hd\s*|4k\s*|audio\s*|visuali[sz]er\s*)*"
    r"(?:video|clip|audio|lyrics?|visuali[sz]er|hd|hq|4k|clip officiel|vid[ée]o officielle|"
    r"paroles|official)[^\)\]]*[\)\]]",
    re.I)


class Cancelled(Exception):
    pass


def classify(url):
    u = url.lower()
    if "spotify.com" in u or u.startswith("spotify:"):
        return "spotify"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "tiktok.com" in u:
        return "tiktok"
    if "soundcloud.com" in u:
        return "soundcloud"
    if "bandcamp.com" in u:
        return "bandcamp"
    if "deezer.com" in u or "deezer.page.link" in u:
        return "deezer"
    return "web"


def clean_title(title):
    t = _JUNK.sub("", title or "").strip()
    return re.sub(r"\s{2,}", " ", t) or title


def _http(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_image(url, dest):
    try:
        data = _http(url)
        if len(data) > 500:
            Path(dest).write_bytes(data)
            return str(dest)
    except Exception:
        pass
    return ""


# --------------------------------------------------------------------------- Spotify
def spotify_parse(url):
    m = re.search(r"spotify:(track|album|playlist|artist):([A-Za-z0-9]+)", url)
    if not m:
        m = re.search(r"open\.spotify\.com/(?:intl-[a-z]+/)?(?:embed/)?(track|album|playlist|artist)/([A-Za-z0-9]+)", url)
    if not m:
        raise ValueError("Lien Spotify non reconnu")
    return m.group(1), m.group(2)


def spotify_fetch(url):
    """Retourne {'kind','name','tracks':[{'title','artist','duration','uri'}],'cover'} sans clé API."""
    if "spotify.link" in url or "spotify.app.link" in url:  # liens courts de l'appli mobile
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            url = r.geturl()
    kind, sid = spotify_parse(url)
    page = _http(f"https://open.spotify.com/embed/{kind}/{sid}").decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError("Impossible de lire la page Spotify (lien privé ?)")
    page_props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    entity = ((page_props.get("state") or {}).get("data") or {}).get("entity")
    if not entity:
        status = page_props.get("status")
        if status == 404:
            raise RuntimeError("Spotify ne trouve pas ce lien : la playlist est sûrement PRIVÉE (ou supprimée, "
                               "ou le lien est incomplet). Sur Spotify : … → « Rendre public », puis recopie le lien.")
        if status == 403:
            raise RuntimeError("ce contenu Spotify n'est pas disponible dans ta région")
        raise RuntimeError(f"Spotify a renvoyé une page inattendue (statut {status or 'inconnu'}) — réessaie plus tard")
    img = re.search(r"https://i\.scdn\.co/image/[A-Za-z0-9]+", page)
    cover = spotify_track_cover(f"spotify:{kind}:{sid}") or (img.group(0) if img else "")
    out = {"kind": kind, "name": entity.get("name") or entity.get("title") or "Spotify",
           "cover": cover, "tracks": []}
    if kind == "track":
        artists = ", ".join(a.get("name", "") for a in entity.get("artists", []))
        out["tracks"].append({"title": entity.get("name", ""), "artist": artists,
                              "duration": (entity.get("duration") or 0) / 1000, "uri": entity.get("uri", "")})
    else:
        for t in entity.get("trackList", []):
            out["tracks"].append({"title": t.get("title", ""),
                                  "artist": (t.get("subtitle") or "").replace(" ", " "),
                                  "duration": (t.get("duration") or 0) / 1000, "uri": t.get("uri", "")})
    return out


def spotify_track_cover(uri):
    """Pochette carrée officielle d'un titre Spotify via l'oEmbed public."""
    try:
        data = json.loads(_http("https://open.spotify.com/oembed?url=" + urllib.parse.quote(uri, safe="")))
        return data.get("thumbnail_url", "")
    except Exception:
        return ""


# --------------------------------------------------------------------------- fichiers locaux
def read_local_meta(path):
    p = Path(path)
    meta = {"title": p.stem, "artist": "", "album": "", "duration": 0, "cover_bytes": None}
    if mutagen is not None:
        try:
            f = mutagen.File(str(p))
            if f is not None:
                meta["duration"] = float(getattr(f.info, "length", 0) or 0)
                tags = f.tags
                if tags is not None:
                    if hasattr(tags, "getall"):           # ID3 (mp3)
                        apic = tags.getall("APIC")
                        if apic:
                            meta["cover_bytes"] = apic[0].data
                    elif "covr" in tags:                  # MP4 / m4a
                        meta["cover_bytes"] = bytes(tags["covr"][0])
                if getattr(f, "pictures", None):          # FLAC
                    meta["cover_bytes"] = f.pictures[0].data
            easy = mutagen.File(str(p), easy=True)
            if easy is not None and easy.tags:
                for key in ("title", "artist", "album"):
                    val = easy.tags.get(key)
                    if val:
                        meta[key] = str(val[0])
        except Exception:
            pass
    if not meta["artist"] and " - " in meta["title"]:
        meta["artist"], meta["title"] = [s.strip() for s in meta["title"].split(" - ", 1)]
    return meta


def expand_paths(paths):
    """Fichiers + contenus de dossiers (récursif) ; renvoie (audios, playlists_m3u)."""
    audio, m3u = [], []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix.lower() in AUDIO_EXTENSIONS:
                    audio.append(f)
        elif p.suffix.lower() in (".m3u", ".m3u8"):
            m3u.append(p)
        elif p.suffix.lower() in AUDIO_EXTENSIONS:
            audio.append(p)
    return audio, m3u


def parse_m3u(path):
    out = []
    base = Path(path).parent
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            f = Path(line) if Path(line).is_absolute() else base / line
            if f.exists():
                out.append(f)
    return out


# --------------------------------------------------------------------------- worker
class ImportWorker(QThread):
    """Thread unique qui traite la file d'imports l'un après l'autre."""
    log = Signal(str, str)               # message, niveau (info/ok/err)
    status = Signal(str)                 # élément en cours
    progress = Signal(float)             # % de l'élément en cours
    overall = Signal(int, int)           # fait, total (lot en cours)
    library_changed = Signal()
    busy = Signal(bool)

    def __init__(self, library, settings):
        super().__init__()
        self.lib = library
        self.settings = settings
        self.jobs = queue.Queue()
        self._cancel = threading.Event()
        self._stop = False
        self.done = 0
        self.total = 0

    # API appelée depuis l'interface
    def add_urls(self, urls, target="auto"):
        for u in urls:
            self.total += 1
            self.jobs.put({"kind": "url", "url": u.strip(), "target": target})
        self.overall.emit(self.done, self.total)

    def add_files(self, paths, target="none"):
        self.total += 1
        self.jobs.put({"kind": "files", "paths": [str(p) for p in paths], "target": target})
        self.overall.emit(self.done, self.total)

    def add_replace(self, tid, url):
        """Remplace l'audio d'un titre (mauvaise correspondance) par un autre lien."""
        self.total += 1
        self.jobs.put({"kind": "replace", "tid": tid, "url": url})
        self.overall.emit(self.done, self.total)

    def cancel(self):
        self._cancel.set()
        while not self.jobs.empty():
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self._stop = True
        self.cancel()
        self.jobs.put(None)

    # boucle
    def run(self):
        ensure_dirs()
        while not self._stop:
            job = self.jobs.get()
            if job is None:
                break
            self._cancel.clear()
            self.busy.emit(True)
            try:
                if job["kind"] == "url":
                    self._import_url(job["url"], job["target"])
                elif job["kind"] == "replace":
                    self._replace(job["tid"], job["url"])
                else:
                    self._import_files(job["paths"], job["target"])
            except Cancelled:
                self.log.emit("Import annulé.", "err")
            except Exception as e:
                self.log.emit(f"Erreur : {self._short(e)}", "err")
                traceback.print_exc()
            self.done += 1
            self.overall.emit(self.done, self.total)
            self.library_changed.emit()
            if self.jobs.empty():
                self.done = self.total = 0
                self.busy.emit(False)
                self.status.emit("")

    @staticmethod
    def _short(e):
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
        return msg.replace("ERROR: ", "")[:220]

    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def _attach(self, state, tid):
        """Ajoute un titre à la playlist cible ; la playlist « auto » n'est créée qu'au 1er succès."""
        target = state["target"]
        if target == "none" or (target == "auto" and not state["collection"]):
            return
        if state.get("pid") is None:
            if target == "auto":
                pl = self.lib.create_playlist(state["name"])
                state["pid"] = pl["id"]
                if state.get("cover"):
                    c = download_image(state["cover"], COVERS_DIR / f"pl_{pl['id']}.jpg")
                    if c:
                        self.lib.update_playlist(pl["id"], cover=c)
            else:
                state["pid"] = target
        self.lib.add_to_playlist(state["pid"], [tid])

    # ---------------------------------------------------------------- liens
    def _import_url(self, url, target):
        if not url:
            return
        src = classify(url)
        self.log.emit(f"Analyse du lien {SOURCE_LABELS.get(src, src)} : {url}", "info")
        if src == "spotify":
            return self._import_spotify(url, target)
        if yt_dlp is None:
            raise RuntimeError("yt-dlp n'est pas installé (pip install yt-dlp)")

        self.status.emit("Lecture des informations…")
        opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True}
        if "list=RD" in url or "start_radio" in url:  # « mix » YouTube infini → juste le titre
            opts["noplaylist"] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        self._check()

        entries = info.get("entries") if info else None
        if entries is not None:
            entries = [e for e in entries if e]
            name = info.get("title") or "Playlist importée"
            state = {"target": target, "name": name, "collection": True}
            self.log.emit(f"Playlist « {name} » : {len(entries)} titres", "info")
            ok = 0
            for i, e in enumerate(entries, 1):
                self._check()
                eurl = e.get("url") or e.get("webpage_url")
                if eurl and not eurl.startswith("http") and e.get("ie_key") == "Youtube":
                    eurl = f"https://www.youtube.com/watch?v={eurl}"
                if not eurl:
                    continue
                self.status.emit(f"[{i}/{len(entries)}] {e.get('title') or eurl}")
                tr = self._safe_download(eurl, src)
                if tr:
                    ok += 1
                    self._attach(state, tr["id"])
                    self.library_changed.emit()
            self.log.emit(f"« {name} » importée : {ok}/{len(entries)} titres.", "ok")
        else:
            tr = self._safe_download(url, src)
            if tr:
                self._attach({"target": target, "name": "", "collection": False}, tr["id"])

    def _safe_download(self, url, src, override=None):
        try:
            return self._download(url, src, override)
        except Cancelled:
            raise
        except Exception as e:
            label = override["title"] if override else url
            self.log.emit(f"Échec : {label} — {self._short(e)}", "err")
            return None

    def _download(self, url, src, override=None, replace=None):
        """Télécharge un seul média. `replace` = titre existant dont on remplace seulement l'audio."""
        def hook(d):
            if self._cancel.is_set():
                raise Cancelled()
            if d.get("status") == "downloading":
                tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if tot:
                    self.progress.emit(100.0 * d.get("downloaded_bytes", 0) / tot)
            elif d.get("status") == "finished":
                self.progress.emit(100.0)

        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
            "outtmpl": str(MUSIC_DIR / "%(extractor_key)s_%(id)s.%(ext)s"),
            "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True,
            "progress_hooks": [hook], "retries": 3, "fragment_retries": 3,
            "restrictfilenames": True, "windowsfilenames": True,
        }
        if shutil.which("ffmpeg"):  # si ffmpeg est dispo, on convertit en vrai mp3
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                       "preferredquality": "192"}]
        self.progress.emit(0)
        # YouTube refuse parfois un « client » de lecture (erreur 403) : on réessaie avec d'autres
        # (client, format, pause avant l'essai) — le 403 de YouTube est souvent passager
        clients = [(None, None, 0), (None, None, 2.0), (None, "bestaudio/best", 3.0),
                   (["tv", "web_safari"], "bestaudio/best", 1.0), (["mweb"], "best", 1.0),
                   (["android_vr", "ios"], "bestaudio/best", 1.0)]
        last_error = None
        for attempt, (client, fmt, pause) in enumerate(clients):
            run_opts = dict(opts)
            if attempt and pause:
                time.sleep(pause)
                self._check()
            if client:
                run_opts["extractor_args"] = {"youtube": {"player_client": client}}
            if fmt:
                run_opts["format"] = fmt
            try:
                with yt_dlp.YoutubeDL(run_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info and info.get("entries") is not None:
                        entries = [e for e in info["entries"] if e]
                        if not entries:
                            raise RuntimeError("aucun résultat trouvé")
                        info = entries[0]
                    self._check()
                    source_id = f"{info.get('extractor_key', src)}:{info.get('id')}"
                    if override and override.get("uri"):
                        source_id = override["uri"]
                    existing = None if replace else self.lib.find_by_source(source_id)
                    if existing and Path(existing["path"]).exists():
                        self.log.emit(f"Déjà dans la bibliothèque : {existing['title']}", "info")
                        return existing
                    info = ydl.process_ie_result(info, download=True)
                    path = ""
                    for d in info.get("requested_downloads") or []:
                        path = d.get("filepath") or path
                    path = path or info.get("filepath") or ydl.prepare_filename(info)
                break
            except Cancelled:
                raise
            except Exception as e:
                last_error = e
                text = str(e)
                youtube = "youtu" in url or src in ("youtube", "spotify") or url.startswith("ytsearch")
                blocked = attempt > 0 or "403" in text or "Forbidden" in text or "reload" in text
                if youtube and blocked and attempt + 1 < len(clients) and "aucun résultat" not in text:
                    self.log.emit(f"YouTube a refusé ce téléchargement, nouvel essai avec un autre client… "
                                  f"({attempt + 1}/{len(clients) - 1})", "info")
                    continue
                raise
        else:
            raise last_error
        self._check()
        if not Path(path).exists():
            raise RuntimeError("fichier introuvable après téléchargement")

        if replace:
            old = replace.get("path", "")
            self.lib.update_track(replace["id"], path=str(path), url=info.get("webpage_url") or url,
                                  duration=float(info.get("duration") or replace["duration"] or 0),
                                  match="ok", yt_title=info.get("title", ""))
            try:  # on supprime l'ancien fichier téléchargé par 4tafy
                if old and Path(old).resolve() != Path(path).resolve() and \
                        Path(old).resolve().is_relative_to(MUSIC_DIR.resolve()):
                    Path(old).unlink(missing_ok=True)
            except OSError:
                pass
            self.log.emit(f"Son corrigé : {replace['title']} → {info.get('title', '')}", "ok")
            return self.lib.get(replace["id"])
        if override:
            title, artist, album = override["title"], override["artist"], override.get("album", "")
        else:
            title = info.get("track") or info.get("title") or "Sans titre"
            artist = info.get("artist") or info.get("creator") or ""
            if src == "tiktok":  # le « son » TikTok est souvent « original sound » : on garde la description
                title = re.sub(r"\s*#\S+", "", info.get("title") or "").strip() or title
                artist = info.get("uploader") or info.get("channel") or artist
            album = info.get("album") or ""
            if not artist and " - " in title and src in ("youtube", "web", "soundcloud"):
                artist, title = [s.strip() for s in title.split(" - ", 1)]
            if not artist:
                artist = (info.get("uploader") or info.get("channel") or "").replace(" - Topic", "")
            if self.settings["clean_titles"]:
                title = clean_title(title)
            if src == "tiktok" and len(title) > 80:
                title = title[:77] + "…"
        real_src = src if src != "web" else (info.get("extractor_key") or "web").lower()
        tr = self.lib.add_track(
            title=html.unescape(title), artist=artist, album=album,
            duration=float(info.get("duration") or (override or {}).get("duration") or 0),
            path=str(path), source=real_src, source_id=source_id,
            url=info.get("webpage_url") or url,
            match=(override or {}).get("match", ""), yt_title=info.get("title", "") if override else "",
            query={"title": override["title"], "artist": override["artist"],
                   "duration": override.get("duration", 0)} if override else None)
        cover_url = (override or {}).get("cover") or info.get("thumbnail") or ""
        if cover_url:
            c = download_image(cover_url, COVERS_DIR / f"{tr['id']}.jpg")
            if c:
                self.lib.update_track(tr["id"], cover=c)
        self.log.emit(f"Ajouté : {artist + ' — ' if artist else ''}{title}", "ok")
        return tr

    # ---------------------------------------------------------------- Spotify
    def _import_spotify(self, url, target):
        if yt_dlp is None:
            raise RuntimeError("yt-dlp n'est pas installé (pip install yt-dlp)")
        self.status.emit("Lecture des infos Spotify…")
        data = spotify_fetch(url)
        tracks = data["tracks"]
        if not tracks:
            raise RuntimeError("aucun titre trouvé sur ce lien Spotify")
        state = {"target": target, "name": data["name"], "cover": data.get("cover", ""),
                 "collection": data["kind"] in ("playlist", "album", "artist")}
        self.log.emit(f"Spotify « {data['name']} » : {len(tracks)} titres → recherche sur YouTube", "info")
        ok = 0
        for i, t in enumerate(tracks, 1):
            self._check()
            label = f"{t['artist']} - {t['title']}"
            self.status.emit(f"[{i}/{len(tracks)}] {label}")
            existing = self.lib.find_by_source(t["uri"])
            if existing and Path(existing["path"]).exists():
                tr = existing
            else:
                override = dict(t)
                if data["kind"] == "album":
                    override["album"] = data["name"]
                    override["cover"] = data.get("cover", "")
                elif t.get("uri"):
                    override["cover"] = spotify_track_cover(t["uri"])
                self.status.emit(f"[{i}/{len(tracks)}] Recherche de la bonne version : {label}")
                try:
                    best, sure, _ranked = best_match(t["title"], t["artist"], t["duration"])
                except Exception as e:
                    best, sure = None, False
                    self.log.emit(f"Recherche impossible pour {label} : {self._short(e)}", "err")
                if best is None:
                    self.log.emit(f"Introuvable sur YouTube : {label}", "err")
                    continue
                self._check()
                override["match"] = "ok" if sure else "uncertain"
                self.status.emit(f"[{i}/{len(tracks)}] {label}")
                tr = self._safe_download(best["url"], "spotify", override)
                if tr and not sure:
                    self.log.emit(f"⚠ À vérifier : « {label} » → « {best['title']} » "
                                  "(clic droit sur le titre → Corriger le son)", "err")
            if tr:
                ok += 1
                self._attach(state, tr["id"])
                self.library_changed.emit()
        self.log.emit(f"Spotify « {data['name']} » : {ok}/{len(tracks)} titres importés.", "ok")

    def _replace(self, tid, url):
        t = self.lib.get(tid)
        if not t:
            return
        if yt_dlp is None:
            raise RuntimeError("yt-dlp n'est pas installé (pip install yt-dlp)")
        self.status.emit(f"Correction : {t['title']}")
        self._download(url, classify(url), replace=t)

    # ---------------------------------------------------------------- fichiers
    def _import_files(self, paths, target):
        audio, m3u = expand_paths(paths)
        pid = target if target not in ("auto", "none") else None
        ids = self._add_local(audio)
        if pid:
            self.lib.add_to_playlist(pid, ids)
        for pl_file in m3u:
            files = parse_m3u(pl_file)
            new_pid = self.lib.create_playlist(pl_file.stem)["id"]
            self.lib.add_to_playlist(new_pid, self._add_local(files))
            self.log.emit(f"Playlist « {pl_file.stem} » importée ({len(files)} titres).", "ok")
        self.log.emit(f"{len(ids)} fichier(s) audio importé(s).", "ok")

    def _add_local(self, files):
        ids = []
        for i, f in enumerate(files, 1):
            self._check()
            self.status.emit(f"[{i}/{len(files)}] {f.name}")
            self.progress.emit(100.0 * i / max(1, len(files)))
            existing = self.lib.find_by_path(f)
            if existing:
                ids.append(existing["id"])
                continue
            meta = read_local_meta(f)
            tr = self.lib.add_track(title=meta["title"], artist=meta["artist"], album=meta["album"],
                                    duration=meta["duration"], path=str(f), source="local",
                                    url=f.as_uri())
            if meta["cover_bytes"]:
                dest = COVERS_DIR / f"{tr['id']}.jpg"
                try:
                    dest.write_bytes(meta["cover_bytes"])
                    self.lib.update_track(tr["id"], cover=str(dest))
                except OSError:
                    pass
            ids.append(tr["id"])
            if i % 25 == 0:
                self.library_changed.emit()
        return ids
