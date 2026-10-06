"""Plugin intégré 4tafy : transforme n'importe quel son en HARDTEKK.

Étapes :
 1. accélère le morceau vers le tempo cible (165-175 BPM typique), façon « pitch up » ou en gardant la tonalité ;
 2. retrouve la grille des temps du morceau pour caler les kicks dessus ;
 3. ajoute un kick hardtekk synthétisé (descente de fréquence + forte distorsion) sur chaque temps,
    une basse en contretemps, des hi-hats et un clap ;
 4. sidechain : le morceau d'origine « pompe » sous chaque kick, et ses basses sont nettoyées ;
 5. coupe les kicks dans les passages calmes (breaks) et limite le tout sans saturer.
"""
import numpy as np
from scipy import signal

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

PLUGIN = {
    "id": "hardtekk",
    "name": "Hardtekk",
    "version": "1.0",
    "author": "4tafy",
    "description": "Transforme un son en hardtekk : tempo accéléré (~170 BPM), gros kicks distordus sur chaque "
                   "temps, basse en contretemps, hi-hats, clap et sidechain qui fait pomper le morceau.",
    "suffix": "Hardtekk",
    "params": [
        {"key": "bpm", "label": "Tempo cible", "type": "slider", "min": 150, "max": 200, "step": 1,
         "default": 170, "unit": " BPM"},
        {"key": "keep_pitch", "label": "Garder la tonalité (sinon voix aiguës)",
         "type": "bool", "default": False},
        {"key": "kick", "label": "Volume du kick", "type": "slider", "min": 0, "max": 100, "step": 1,
         "default": 80, "unit": " %"},
        {"key": "drive", "label": "Distorsion du kick", "type": "slider", "min": 0, "max": 100, "step": 1,
         "default": 70, "unit": " %"},
        {"key": "tune", "label": "Hauteur du kick", "type": "slider", "min": 40, "max": 75, "step": 1,
         "default": 52, "unit": " Hz"},
        {"key": "bass", "label": "Basse en contretemps", "type": "slider", "min": 0, "max": 100, "step": 1,
         "default": 55, "unit": " %"},
        {"key": "bass_note", "label": "Note de la basse", "type": "choice", "choices": ["Auto"] + NOTES,
         "default": "Auto"},
        {"key": "hats", "label": "Hi-hats", "type": "slider", "min": 0, "max": 100, "step": 1,
         "default": 40, "unit": " %"},
        {"key": "clap", "label": "Clap", "type": "slider", "min": 0, "max": 100, "step": 1,
         "default": 35, "unit": " %"},
        {"key": "sidechain", "label": "Sidechain (pompage)", "type": "slider", "min": 0, "max": 100, "step": 1,
         "default": 65, "unit": " %"},
        {"key": "clean", "label": "Nettoyer les basses d'origine", "type": "slider", "min": 0, "max": 100,
         "step": 1, "default": 75, "unit": " %"},
        {"key": "breaks", "label": "Couper les kicks dans les passages calmes", "type": "bool", "default": True},
    ],
}


# --------------------------------------------------------------------------- instruments
def make_kick(sr, tune, drive, length):
    n = int(sr * length)
    t = np.arange(n) / sr
    f = tune + (230 - tune) * np.exp(-t / 0.016)              # descente rapide de fréquence
    body = np.sin(2 * np.pi * np.cumsum(f) / sr)
    amp = np.exp(-t / (length * 0.5)) * np.minimum(1, t / 0.001)
    rng = np.random.default_rng(11)
    click = signal.sosfilt(signal.butter(2, 1500, "hp", fs=sr, output="sos"), rng.normal(0, 1, n)) \
        * np.exp(-t / 0.003) * 0.6
    k = body * amp + click
    g = 1 + drive * 16                                        # la distorsion fait le son « tok » hardtekk
    k = np.tanh(k * g) / np.tanh(g)
    k = signal.sosfilt(signal.butter(2, 9000, fs=sr, output="sos"), k)
    k *= np.exp(-t / (length * 0.45))                         # la queue redescend après distorsion
    fade = min(n, int(0.006 * sr))
    k[-fade:] *= np.linspace(1, 0, fade)
    return (k / (np.abs(k).max() + 1e-9)).astype(np.float32)


def make_bass(sr, freq, length):
    n = int(sr * length)
    t = np.arange(n) / sr
    saw = 2 * ((freq * t) % 1.0) - 1
    sub = np.sin(2 * np.pi * freq * t)
    b = 0.55 * saw + 0.8 * sub
    b = signal.sosfilt(signal.butter(2, 320, fs=sr, output="sos"), b)
    env = np.minimum(1, t / 0.004) * np.exp(-t / (length * 0.45))
    b = np.tanh(b * env * 2.2)
    fade = min(n, int(0.008 * sr))
    b[-fade:] *= np.linspace(1, 0, fade)
    return (b / (np.abs(b).max() + 1e-9)).astype(np.float32)


def make_hat(sr):
    n = int(sr * 0.06)
    t = np.arange(n) / sr
    h = np.random.default_rng(5).normal(0, 1, n)
    h = signal.sosfilt(signal.butter(4, 7500, "hp", fs=sr, output="sos"), h) * np.exp(-t / 0.012)
    return (h / (np.abs(h).max() + 1e-9)).astype(np.float32)


def make_clap(sr):
    n = int(sr * 0.25)
    t = np.arange(n) / sr
    noise = signal.sosfilt(signal.butter(2, [900, 3200], "bp", fs=sr, output="sos"),
                           np.random.default_rng(9).normal(0, 1, n))
    env = np.zeros(n)
    for d in (0.0, 0.011, 0.022):  # trois claquements rapprochés = clap
        k = int(d * sr)
        env[k:] = np.maximum(env[k:], np.exp(-(t[: n - k]) / 0.006))
    env = np.maximum(env, 0.6 * np.exp(-np.maximum(t - 0.022, 0) / 0.09) * (t >= 0.022))
    c = noise * env
    return (c / (np.abs(c).max() + 1e-9)).astype(np.float32)


# --------------------------------------------------------------------------- analyse
def root_freq(x, sr):
    """Note grave dominante du morceau, ramenée entre 41 et 82 Hz."""
    mono = x[: sr * 90].mean(axis=1)
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1 / sr)
    chroma = np.zeros(12)
    band = (freqs > 40) & (freqs < 260)
    for f, m in zip(freqs[band], spec[band]):
        chroma[int(round(12 * np.log2(f / 440) + 9)) % 12] += m
    return 41.2 * 2 ** (((int(np.argmax(chroma)) - 4) % 12) / 12)  # E1 = 41,2 Hz


def place(events, sample, n):
    """Pose un échantillon à chaque instant (en échantillons) d'une liste."""
    train = np.zeros(n + len(sample), np.float32)
    for i, g in events:
        if 0 <= i < n:
            train[i] += g
    return signal.oaconvolve(train, sample)[:n].astype(np.float32)


# --------------------------------------------------------------------------- traitement
def process(audio, sr, params, ctx):
    p = params
    target = float(p["bpm"])
    orig = ctx.bpm or ctx.estimate_bpm(audio) or 128
    # morceau lent (ex. 85 BPM) : on considère le double tempo pour ne pas trop accélérer
    m = min((0.5, 1.0, 2.0), key=lambda k: abs(np.log(target / (orig * k)) - np.log(1.25)))
    ctx.progress(0.03, "Suivi des temps du morceau…")

    # 1) temps du morceau d'origine (suivi précis) → tempo réel, pas l'estimation arrondie
    src_beats = ctx.dsp.beat_track(audio, orig * m)
    period = ctx.dsp.beat_period(src_beats)
    precise = 60 / period if period > 0 else orig * m
    factor = target / precise
    ctx.progress(0.12, f"Tempo : {precise:.1f} BPM → {target:.0f} BPM (×{factor:.3f})")

    # 2) accélération
    if p["keep_pitch"]:
        y = ctx.dsp._time_stretch(audio, 1 / factor)
    else:
        from fractions import Fraction
        fr = Fraction(1 / factor).limit_denominator(400)
        y = signal.resample_poly(audio, fr.numerator, fr.denominator, axis=0).astype(np.float32)
    n = len(y)

    # 3) les temps suivis sont reportés sur la version accélérée : les kicks restent calés
    #    du début à la fin, même si le tempo du morceau varie un peu
    times = src_beats * (n / len(audio))
    times = times[(times >= 0) & (times < n / sr)]
    beat = ctx.dsp.beat_period(times) or 60 / target
    beats = (times * sr).astype(int)

    # passages calmes : pas de kick
    keep = np.ones(len(beats), bool)
    if p["breaks"] and len(beats) > 8:
        mono = np.abs(y.mean(axis=1))
        bl = int(beat * sr)
        rms = np.array([np.sqrt(np.mean(mono[b: b + bl] ** 2) + 1e-12) for b in beats])
        smooth = np.convolve(rms, np.ones(4) / 4, mode="same")
        keep = smooth > 0.45 * np.median(rms)
    ctx.progress(0.45, "Synthèse des kicks et de la basse…")

    # 3) instruments
    kick = make_kick(sr, float(p["tune"]), p["drive"] / 100, min(0.34, beat * 0.92))
    freq = root_freq(y, sr) if p["bass_note"] == "Auto" else 41.2 * 2 ** (((NOTES.index(p["bass_note"]) - 4) % 12) / 12)
    bass = make_bass(sr, freq, beat * 0.48)
    half = int(beat * sr / 2)
    kicks = place([(b, 1.0) for b, k in zip(beats, keep) if k], kick, n)
    basses = place([(b + half, 1.0) for b, k in zip(beats, keep) if k], bass, n)
    hats = place([(b + half, 1.0) for b, k in zip(beats, keep) if k], make_hat(sr), n)
    claps = place([(b, 1.0) for i, (b, k) in enumerate(zip(beats, keep)) if k and i % 2 == 1], make_clap(sr), n)
    ctx.progress(0.7, "Sidechain et mixage…")

    # 4) morceau d'origine : basses nettoyées + sidechain
    clean = p["clean"] / 100
    if clean > 0:
        hp = signal.sosfilt(signal.butter(2, 150, "hp", fs=sr, output="sos"), y, axis=0).astype(np.float32)
        y = (1 - clean) * y + clean * hp
    depth = p["sidechain"] / 100
    if depth > 0:
        t = np.arange(int(beat * sr)) / sr
        curve = (np.exp(-t / (beat * 0.22))).astype(np.float32)
        duck = place([(b, 1.0) for b, k in zip(beats, keep) if k], curve, n)
        y = y * (1 - depth * np.clip(duck, 0, 1))[:, None]

    def st(mono, gain):
        return np.repeat((mono * gain)[:, None], 2, axis=1)

    out = (0.85 * y
           + st(kicks, 0.95 * p["kick"] / 100)
           + st(basses, 0.55 * p["bass"] / 100)
           + st(claps, 0.35 * p["clap"] / 100))
    # hi-hats légèrement écartés en stéréo
    hgain = 0.22 * p["hats"] / 100
    out[:, 0] += hats * hgain * 0.8
    out[:, 1] += np.roll(hats, int(0.004 * sr)) * hgain
    ctx.progress(0.88, "Limiteur…")

    # 5) niveau final
    peak = float(np.max(np.abs(out))) or 1.0
    out = out * (1.25 / peak)          # on pousse un peu : le limiteur rattrape les crêtes
    out = ctx.limit(out.astype(np.float32))
    ctx.progress(1.0, "Terminé")
    return out
