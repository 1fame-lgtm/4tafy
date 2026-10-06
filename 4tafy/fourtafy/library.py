"""Bibliothèque musicale : titres + playlists, sauvegardés dans un simple fichier JSON."""
import json
import os
import threading
import time
import uuid
from pathlib import Path

from .config import LIBRARY_FILE, MUSIC_DIR, COVERS_DIR, ensure_dirs

TRACK_DEFAULTS = {
    "title": "Sans titre",
    "artist": "",
    "album": "",
    "duration": 0,        # secondes
    "path": "",           # fichier audio local
    "cover": "",          # image de pochette
    "source": "local",    # youtube / spotify / tiktok / soundcloud / local / web
    "source_id": "",      # identifiant unique côté source (anti-doublons)
    "url": "",
    "added": 0,
    "liked": False,
    "plays": 0,
}


class Library:
    def __init__(self, path=LIBRARY_FILE):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.tracks = {}
        self.playlists = []
        self.load()

    # ------------------------------------------------------------------ persistance
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for t in data.get("tracks", []):
            tr = dict(TRACK_DEFAULTS, **t)
            self.tracks[tr["id"]] = tr
        self.playlists = data.get("playlists", [])

    def save(self):
        with self.lock:
            ensure_dirs()
            data = {"version": 1, "tracks": list(self.tracks.values()), "playlists": self.playlists}
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------ titres
    def add_track(self, **fields):
        with self.lock:
            tr = dict(TRACK_DEFAULTS, **fields)
            tr["id"] = uuid.uuid4().hex[:12]
            tr["added"] = tr["added"] or time.time()
            self.tracks[tr["id"]] = tr
            self.save()
            return tr

    def get(self, tid):
        return self.tracks.get(tid)

    def find_by_source(self, source_id):
        if not source_id:
            return None
        with self.lock:
            return next((t for t in self.tracks.values() if t["source_id"] == source_id), None)

    def find_by_path(self, path):
        norm = os.path.normcase(os.path.abspath(path))
        with self.lock:
            return next((t for t in self.tracks.values()
                         if t["path"] and os.path.normcase(os.path.abspath(t["path"])) == norm), None)

    def update_track(self, tid, **fields):
        with self.lock:
            if tid in self.tracks:
                self.tracks[tid].update(fields)
                self.save()

    def toggle_like(self, tid):
        with self.lock:
            t = self.tracks.get(tid)
            if t:
                t["liked"] = not t["liked"]
                self.save()
                return t["liked"]
        return False

    def remove_tracks(self, tids, delete_files=False):
        with self.lock:
            for tid in tids:
                t = self.tracks.pop(tid, None)
                if not t:
                    continue
                if delete_files:
                    # on ne supprime que ce que 4tafy a lui-même téléchargé
                    for key, folder in (("path", MUSIC_DIR), ("cover", COVERS_DIR)):
                        f = t.get(key)
                        try:
                            if f and Path(f).resolve().is_relative_to(folder.resolve()):
                                Path(f).unlink(missing_ok=True)
                        except OSError:
                            pass
            for pl in self.playlists:
                pl["tracks"] = [x for x in pl["tracks"] if x in self.tracks]
            self.save()

    def all_tracks(self):
        with self.lock:
            return sorted(self.tracks.values(), key=lambda t: t["added"], reverse=True)

    def liked_tracks(self):
        return [t for t in self.all_tracks() if t["liked"]]

    # ------------------------------------------------------------------ playlists
    def create_playlist(self, name, description=""):
        with self.lock:
            pl = {"id": uuid.uuid4().hex[:12], "name": name or "Nouvelle playlist",
                  "description": description, "cover": "", "tracks": [], "created": time.time()}
            self.playlists.append(pl)
            self.save()
            return pl

    def get_playlist(self, pid):
        return next((p for p in self.playlists if p["id"] == pid), None)

    def update_playlist(self, pid, **fields):
        with self.lock:
            pl = self.get_playlist(pid)
            if pl:
                pl.update(fields)
                self.save()

    def delete_playlist(self, pid):
        with self.lock:
            self.playlists = [p for p in self.playlists if p["id"] != pid]
            self.save()

    def add_to_playlist(self, pid, tids):
        with self.lock:
            pl = self.get_playlist(pid)
            if not pl:
                return 0
            n = 0
            for tid in tids:
                if tid in self.tracks and tid not in pl["tracks"]:
                    pl["tracks"].append(tid)
                    n += 1
            self.save()
            return n

    def remove_from_playlist(self, pid, tids):
        with self.lock:
            pl = self.get_playlist(pid)
            if pl:
                pl["tracks"] = [t for t in pl["tracks"] if t not in set(tids)]
                self.save()

    def move_in_playlist(self, pid, tid, delta):
        with self.lock:
            pl = self.get_playlist(pid)
            if not pl or tid not in pl["tracks"]:
                return
            i = pl["tracks"].index(tid)
            j = max(0, min(len(pl["tracks"]) - 1, i + delta))
            pl["tracks"].insert(j, pl["tracks"].pop(i))
            self.save()

    def playlist_tracks(self, pid):
        pl = self.get_playlist(pid)
        if not pl:
            return []
        return [self.tracks[t] for t in pl["tracks"] if t in self.tracks]

    def playlist_cover_track(self, pid):
        return next((t for t in self.playlist_tracks(pid) if t.get("cover")), None)

    def export_m3u(self, pid, dest):
        pl = self.get_playlist(pid)
        with open(dest, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            f.write(f"#PLAYLIST:{pl['name']}\n")
            for t in self.playlist_tracks(pid):
                f.write(f"#EXTINF:{int(t['duration'])},{t['artist']} - {t['title']}\n{t['path']}\n")
