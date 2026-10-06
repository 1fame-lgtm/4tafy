"""Retrouver sur YouTube LE bon morceau correspondant à un titre Spotify.

Au lieu de prendre le 1er résultat de recherche, on récupère plusieurs candidats et on les note :
titre, artiste, durée (Spotify donne la durée exacte), chaîne officielle (« Artiste - Topic », VEVO),
et on pénalise les versions différentes (remix, live, reprise, sped up, karaoké…) sauf si le titre
Spotify en est une lui-même.
"""
import math
import re
import unicodedata
import urllib.parse
from difflib import SequenceMatcher

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# mots qui signalent une AUTRE version que l'originale
VARIANTS = [
    "remix", "rmx", "live", "acoustic", "acoustique", "cover", "reprise", "karaoke", "instrumental",
    "sped up", "speed up", "spedup", "slowed", "nightcore", "8d", "reverb", "bass boosted", "boosted",
    "extended", "radio edit", "edit", "mashup", "piano", "guitar", "violin", "1 hour", "10 hours", "1h",
    "reaction", "tutorial", "lesson", "fan made", "fanmade", "tribute", "originally performed", "parody",
    "chipmunk", "lofi", "lo fi", "remastered", "remaster", "demo", "acapella", "a cappella", "concert",
    "version", "vip", "bootleg", "tiktok", "loop", "mix", "clean", "dirty", "unplugged", "orchestral",
]
OK_WORDS = ["official audio", "audio officiel", "official music video", "official video", "clip officiel",
            "lyrics", "lyric video", "paroles", "visualizer", "audio"]

UNCERTAIN = 70  # en dessous de ce score, la correspondance est jugée douteuse


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("$", "s")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def core_title(title):
    """« Titre (feat. X) - Remastered 2011 » → « titre »."""
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", title or "")
    t = re.split(r"\s[-–—]\s", t)[0]
    t = re.split(r"\s(feat|ft|featuring)\.?\s", t, flags=re.I)[0]
    return norm(t) or norm(title)


def split_artists(artist):
    parts = re.split(r",|&|\bfeat\.?\b|\bft\.?\b|\bx\b|\bwith\b", artist or "", flags=re.I)
    return [norm(p) for p in parts if norm(p)]


def _contains_word(hay, phrase):
    return re.search(rf"(^| ){re.escape(phrase)}( |$)", hay) is not None


def score(cand, title, artist, duration):
    """Note un candidat (plus c'est haut, mieux c'est). Renvoie (score, écart de durée ou None)."""
    ct = norm(cand.get("title"))
    ch = norm(cand.get("channel") or cand.get("uploader"))
    full = norm(title)
    core = core_title(title)
    artists = split_artists(artist)
    main = artists[0] if artists else ""
    s = 0.0

    # 1) titre : tous les mots du titre doivent être présents
    words = core.split()
    found = sum(1 for w in words if _contains_word(ct, w))
    s += 45 * found / max(1, len(words))
    rest = ct
    for a in artists:
        rest = rest.replace(a, " ")
    s += 10 * SequenceMatcher(None, core, norm(rest)).ratio()

    # 2) artiste (dans le titre de la vidéo ou le nom de la chaîne)
    if main and (main in ct or main in ch):
        s += 20
    elif main:
        s -= 15
    if len(artists) > 1 and any(a in ct or a in ch for a in artists[1:]):
        s += 4

    # 3) chaîne officielle
    if ch.endswith(" topic") and main and main in ch:
        s += 18  # « Artiste - Topic » = audio officiel du label
    elif "vevo" in ch.replace(" ", "") or (main and ch == main):
        s += 8
    if any(w in ct for w in ("official audio", "audio officiel")):
        s += 5

    # 4) autres versions (remix, live, sped up…) : forte pénalité si absentes du titre Spotify
    for v in VARIANTS:
        if _contains_word(ct, v) and not _contains_word(full, v):
            s -= 30
            break

    # 5) durée : le critère le plus fiable
    diff = None
    d = cand.get("duration")
    if duration and d:
        diff = abs(float(d) - float(duration))
        if diff <= 2:
            s += 30
        elif diff <= 5:
            s += 22
        elif diff <= 10:
            s += 10
        elif diff <= 20:
            s -= 5
        elif diff <= 45:
            s -= 25
        else:
            s -= 50

    # 6) popularité (léger départage)
    views = cand.get("view_count") or 0
    s += min(6.0, math.log10(views + 1))
    return round(s, 1), diff


def _flat(url, n):
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": n,
            "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
    out = []
    for e in (info or {}).get("entries") or []:
        if e and e.get("id"):
            out.append({"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader"),
                        "duration": e.get("duration"), "view_count": e.get("view_count"),
                        "url": f"https://www.youtube.com/watch?v={e['id']}"})
    return out


def _details(cand):
    """Complète un candidat YouTube Music (chaîne, durée) en lisant sa page."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
            info = y.extract_info(cand["url"], download=False, process=False)
        cand.update(title=info.get("title") or cand["title"], channel=info.get("channel") or info.get("uploader"),
                    duration=info.get("duration"), view_count=info.get("view_count"))
    except Exception:
        pass
    return cand


def find_candidates(title, artist, duration, deep=False, n=10):
    """Liste de candidats triés du meilleur au moins bon, avec leur score."""
    if yt_dlp is None:
        raise RuntimeError("yt-dlp n'est pas installé")
    main = (split_artists(artist) or [""])[0]
    q = f"{artist} - {title}" if artist else title
    cands = {c["id"]: c for c in _flat(f"ytsearch{n}:{q}", n)}
    if deep:
        # 2e recherche plus simple + YouTube Music (versions audio officielles)
        for c in _flat(f"ytsearch{n}:{main} {core_title(title)} audio", n):
            cands.setdefault(c["id"], c)
        try:
            ytm = "https://music.youtube.com/search?q=" + urllib.parse.quote(f"{main} {title}") + "#songs"
            for c in _flat(ytm, 3):
                if c["id"] not in cands:
                    cands[c["id"]] = _details(c)
        except Exception:
            pass
    ranked = []
    for c in cands.values():
        c["score"], c["diff"] = score(c, title, artist, duration)
        ranked.append(c)
    ranked.sort(key=lambda c: c["score"], reverse=True)
    return ranked


def best_match(title, artist, duration):
    """Meilleur candidat + indicateur de confiance. Lance une recherche approfondie si besoin."""
    ranked = find_candidates(title, artist, duration)
    best = ranked[0] if ranked else None
    if best is None or best["score"] < UNCERTAIN or (best["diff"] is not None and best["diff"] > 6):
        ranked = find_candidates(title, artist, duration, deep=True)
        best = ranked[0] if ranked else None
    if best is None:
        return None, False, []
    sure = best["score"] >= UNCERTAIN and (best["diff"] is None or best["diff"] <= 10)
    return best, sure, ranked
