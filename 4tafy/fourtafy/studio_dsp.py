"""Moteur audio du Studio 4tafy (numpy + scipy).

Toutes les fonctions travaillent sur des tableaux float32 de forme (échantillons, 2) à 44,1 kHz,
avec des valeurs entre -1 et 1.
"""
import warnings
import wave
from fractions import Fraction

import numpy as np
from scipy import signal

SR = 44100

# (fréquence, nom, type de filtre, Q)
EQ_BANDS = [
    (40, "Sub-basses", "lowshelf", 0.7),
    (120, "Basses", "peak", 0.8),
    (400, "Bas-médiums", "peak", 0.9),
    (1500, "Médiums", "peak", 0.9),
    (5000, "Présence", "peak", 0.9),
    (12000, "Aigus", "highshelf", 0.7),
]

DEFAULT_PARAMS = {
    "gain": 0.0,          # dB
    "eq": [0.0] * len(EQ_BANDS),  # dB par bande
    "speed": 1.0,         # vitesse « vinyle » (tempo + tonalité)
    "pitch": 0,           # demi-tons (garde le tempo)
    "beats": 0,           # 0-100 : impact des attaques (kicks, snares)
    "punch": 0,           # 0-100 : compression
    "reverb": 0,          # 0-100
    "width": 100,         # 0-200 % largeur stéréo
    "pan8d": 0,           # 0-100 : audio 8D
    "lofi": 0,            # 0-100
    "fade_in": 0.0,       # secondes
    "fade_out": 0.0,
    "start": 0.0,         # découpe (secondes du son d'origine)
    "end": None,
    "normalize": False,
}

PRESETS = {
    "Bass Boost": {"eq": [8, 6, 0, 0, 0, 1], "gain": -2, "normalize": True},
    "Slowed + Reverb": {"speed": 0.85, "reverb": 45, "eq": [2, 1, 0, 0, -2, -3]},
    "Nightcore": {"speed": 1.25, "eq": [0, 0, 0, 0, 2, 2]},
    "Audio 8D": {"pan8d": 60, "reverb": 22},
    "Lo-fi": {"lofi": 55, "reverb": 15, "eq": [0, 2, 0, -1, -4, -6]},
    "Voix claire": {"eq": [-3, -2, -1, 3, 4, 2]},
    "Club": {"beats": 55, "punch": 40, "eq": [5, 3, -1, 0, 2, 3], "normalize": True},
}


def params_with(overrides=None):
    p = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_PARAMS.items()}
    for k, v in (overrides or {}).items():
        p[k] = list(v) if isinstance(v, list) else v
    return p


# --------------------------------------------------------------------------- égaliseur
def biquad(kind, f0, gain_db, q, sr=SR):
    """Coefficients d'un filtre biquad (formules « Audio EQ Cookbook » de R. Bristow-Johnson)."""
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    cs, sn = np.cos(w0), np.sin(w0)
    alpha = sn / (2 * q)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cs, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cs, 1 - alpha / A]
    else:
        sq = 2 * np.sqrt(A) * alpha
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cs + sq), 2 * A * ((A - 1) - (A + 1) * cs), A * ((A + 1) - (A - 1) * cs - sq)]
            a = [(A + 1) + (A - 1) * cs + sq, -2 * ((A - 1) + (A + 1) * cs), (A + 1) + (A - 1) * cs - sq]
        else:  # highshelf
            b = [A * ((A + 1) + (A - 1) * cs + sq), -2 * A * ((A - 1) + (A + 1) * cs), A * ((A + 1) + (A - 1) * cs - sq)]
            a = [(A + 1) - (A - 1) * cs + sq, 2 * ((A - 1) - (A + 1) * cs), (A + 1) - (A - 1) * cs - sq]
    return np.array(b + a) / a[0]


def eq_sos_full(gains):
    """Les 6 bandes, même à 0 dB (filtre neutre) : utile pour garder l'état en temps réel."""
    return np.array([biquad(kind, f, g, q) for (f, _, kind, q), g in zip(EQ_BANDS, gains)])


def eq_sos(gains):
    rows = [biquad(kind, f, g, q) for (f, _, kind, q), g in zip(EQ_BANDS, gains) if abs(g) > 0.05]
    return np.array(rows) if rows else None


def eq_response(gains, freqs):
    """Réponse en dB de l'égaliseur aux fréquences données (pour dessiner la courbe)."""
    sos = eq_sos(gains)
    if sos is None:
        return np.zeros_like(freqs, dtype=float)
    _, h = signal.sosfreqz(sos, worN=freqs, fs=SR)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-6))


# --------------------------------------------------------------------------- tempo / tonalité
def _resample(x, ratio):
    """Change la longueur d'un facteur `ratio` (0.5 = deux fois plus court)."""
    fr = Fraction(ratio).limit_denominator(64)
    if fr == 1:
        return x
    return signal.resample_poly(x, fr.numerator, fr.denominator, axis=0).astype(np.float32)


def _time_stretch(x, factor, n_fft=2048, hop=512):
    """Allonge (factor > 1) ou raccourcit le son sans changer la tonalité (vocodeur de phase)."""
    out = []
    omega = 2 * np.pi * np.arange(n_fft // 2 + 1) * hop / n_fft
    for ch in range(x.shape[1]):
        _, _, Z = signal.stft(x[:, ch], nperseg=n_fft, noverlap=n_fft - hop, boundary=None, padded=True)
        Z = Z.astype(np.complex64)
        steps = np.arange(0, Z.shape[1] - 1, 1 / factor)
        i = steps.astype(int)
        frac = (steps - i).astype(np.float32)[None, :]
        mag = (1 - frac) * np.abs(Z[:, i]) + frac * np.abs(Z[:, i + 1])
        dphi = np.angle(Z[:, i + 1]) - np.angle(Z[:, i]) - omega[:, None]
        dphi = dphi - 2 * np.pi * np.round(dphi / (2 * np.pi)) + omega[:, None]
        phase = np.angle(Z[:, :1]) + np.concatenate([np.zeros((Z.shape[0], 1)), np.cumsum(dphi[:, :-1], axis=1)], axis=1)
        Y = (mag * np.exp(1j * phase)).astype(np.complex64)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _, y = signal.istft(Y, nperseg=n_fft, noverlap=n_fft - hop, boundary=False)
        out.append(y.astype(np.float32))
    n = min(len(o) for o in out)
    return np.stack([o[:n] for o in out], axis=1)


def pitch_shift(x, semitones):
    if not semitones:
        return x
    r = 2 ** (semitones / 12)
    return _resample(_time_stretch(x, r), 1 / r)


# --------------------------------------------------------------------------- dynamique
def _envelope(mono, ms):
    a = np.exp(-1.0 / (SR * ms / 1000))
    return signal.lfilter([1 - a], [1, -a], np.abs(mono)).astype(np.float32)


def transient_boost(x, amount):
    """Fait ressortir les attaques (beats) : enveloppe rapide - enveloppe lente."""
    if amount <= 0:
        return x
    mono = x.mean(axis=1)
    fast, slow = _envelope(mono, 4), _envelope(mono, 70)
    attack = np.clip((fast - slow) / (slow + 1e-4), 0, 3)
    gain = 1 + (amount / 100) * 1.6 * attack
    return x * gain[:, None]


def compress(x, amount):
    if amount <= 0:
        return x
    thr_db = -6 - 24 * amount / 100
    ratio = 2 + 4 * amount / 100
    env = _envelope(x.mean(axis=1), 15)
    env_db = 20 * np.log10(env + 1e-6)
    gr = np.minimum(0, (thr_db - env_db) * (1 - 1 / ratio))
    makeup = -thr_db * (1 - 1 / ratio) * 0.5
    return x * (10 ** ((gr + makeup) / 20))[:, None].astype(np.float32)


# --------------------------------------------------------------------------- effets
def lofi(x, amount):
    if amount <= 0:
        return x
    a = amount / 100
    cutoff = 16000 * (1 - a) + 2800 * a
    sos = signal.butter(4, cutoff, fs=SR, output="sos")
    y = signal.sosfilt(sos, x, axis=0).astype(np.float32)
    bits = 16 - 9 * a
    q = 2 ** bits
    y = np.round(y * q) / q
    rng = np.random.default_rng(4)
    crackle = (rng.random(len(y)) > 0.9997) * rng.normal(0, 0.08 * a, len(y))
    hiss = rng.normal(0, 0.004 * a, len(y))
    return (y + (crackle + hiss)[:, None]).astype(np.float32)


def stereo_width(x, width):
    if width == 100:
        return x
    m = (x[:, 0] + x[:, 1]) / 2
    s = (x[:, 0] - x[:, 1]) / 2 * (width / 100)
    return np.stack([m + s, m - s], axis=1).astype(np.float32)


def audio_8d(x, amount):
    """Le son tourne autour de la tête (panoramique automatique)."""
    if amount <= 0:
        return x
    a = amount / 100
    rate = 0.06 + 0.14 * a
    t = np.arange(len(x)) / SR
    theta = (np.sin(2 * np.pi * rate * t) + 1) * np.pi / 4
    m = x.mean(axis=1)
    moving = np.stack([m * np.cos(theta), m * np.sin(theta)], axis=1) * np.sqrt(2)
    return ((1 - a) * x + a * moving).astype(np.float32)


def reverb_ir(amount):
    """Réponse impulsionnelle stéréo de la réverbe (bruit qui décroît, aigus amortis)."""
    a = amount / 100
    decay = 1.2 + 2.6 * a
    n = int(SR * decay)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    sos = signal.butter(2, 6500, fs=SR, output="sos")
    irs = []
    for _ch in range(2):
        ir = rng.normal(0, 1, n) * np.exp(-6.9 * t / decay)
        ir[: int(0.02 * SR)] = 0  # pré-délai
        ir = signal.sosfilt(sos, ir)
        irs.append(ir / np.sqrt(np.sum(ir ** 2)))
    return np.stack(irs, axis=1).astype(np.float32)


def reverb_mix(dry, wet, amount):
    a = amount / 100
    return ((1 - 0.35 * a) * dry + 0.55 * a * wet).astype(np.float32)


def reverb(x, amount):
    if amount <= 0:
        return x
    ir = reverb_ir(amount)
    wet = np.stack([signal.oaconvolve(x[:, ch], ir[:, ch])[: len(x)] for ch in range(2)], axis=1)
    return reverb_mix(x, wet, amount)


def fades(x, fade_in, fade_out):
    n = len(x)
    if fade_in > 0:
        k = min(n, int(fade_in * SR))
        x[:k] *= (np.sin(np.linspace(0, np.pi / 2, k)) ** 2)[:, None]
    if fade_out > 0:
        k = min(n, int(fade_out * SR))
        x[n - k:] *= (np.cos(np.linspace(0, np.pi / 2, k)) ** 2)[:, None]
    return x


# --------------------------------------------------------------------------- rendu complet
def render(audio, p, cache=None):
    """Applique tous les réglages ; renvoie (son, infos).

    `cache` (dict) garde le résultat de l'étape lente (découpe + tonalité) entre deux rendus.
    """
    start = int(max(0.0, p["start"]) * SR)
    end = int(p["end"] * SR) if p["end"] else len(audio)
    key = (start, end, p["pitch"], id(audio))
    if cache is not None and cache.get("key") == key:
        x = cache["data"].copy()
    else:
        x = audio[start:max(start + SR // 10, end)].astype(np.float32, copy=True)
        x = pitch_shift(x, p["pitch"])
        if cache is not None:
            cache["key"], cache["data"] = key, x.copy()
    if abs(p["speed"] - 1) > 1e-3:
        x = _resample(x, 1 / p["speed"])
    sos = eq_sos(p["eq"])
    if sos is not None:
        x = signal.sosfilt(sos, x, axis=0).astype(np.float32)
    x = transient_boost(x, p["beats"])
    x = compress(x, p["punch"])
    x = lofi(x, p["lofi"])
    x = stereo_width(x, p["width"])
    x = audio_8d(x, p["pan8d"])
    x = reverb(x, p["reverb"])
    if p["gain"]:
        x *= 10 ** (p["gain"] / 20)
    x = fades(x, p["fade_in"], p["fade_out"])
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    limited = False
    norm_gain = 1.0
    if p["normalize"] and peak > 0:
        norm_gain = 0.891 / peak  # -1 dBFS
        x *= norm_gain
        peak = 0.891
    elif peak > 1.0:  # protection contre la saturation
        x /= peak * 1.0001
        limited = True
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    info = {"duration": len(x) / SR, "peak_db": 20 * np.log10(max(peak, 1e-6)),
            "rms_db": 20 * np.log10(max(rms, 1e-6)), "limited": limited, "norm_gain": norm_gain}
    return x, info


# --------------------------------------------------------------------------- analyse
def estimate_bpm(audio):
    """Tempo approximatif (BPM) : flux spectral des attaques + autocorrélation en peigne."""
    mono = audio[SR * 5: SR * 95].mean(axis=1)
    if len(mono) < SR * 8:
        mono = audio.mean(axis=1)
    if len(mono) < SR * 4:
        return 0
    mono = signal.resample_poly(mono, 1, 4)  # 11 kHz suffisent
    sr, n_fft, hop = SR / 4, 1024, 128
    _, _, Z = signal.stft(mono, nperseg=n_fft, noverlap=n_fft - hop)
    mag = np.log1p(1000 * np.abs(Z))
    flux = np.maximum(0, np.diff(mag, axis=1)).sum(axis=0)
    flux = np.maximum(flux - signal.medfilt(flux, 15), 0)
    fps = sr / hop
    ac = signal.correlate(flux, flux, mode="full", method="fft")[len(flux) - 1:]
    if ac[0] <= 0:
        return 0
    ac /= ac[0]
    best, best_score = 0, -1.0
    for bpm in np.arange(60, 200, 0.5):
        lag = fps * 60 / bpm
        score = 0.0
        for k, w in ((1, 1.0), (2, 0.5), (3, 0.33), (4, 0.25)):
            L = lag * k
            i = int(L)
            if i + 1 < len(ac):
                fr = L - i
                score += w * ((1 - fr) * ac[i] + fr * ac[i + 1])
        score *= np.exp(-0.5 * (np.log2(bpm / 120) / 0.5) ** 2)  # préférence autour de 120
        if score > best_score:
            best_score, best = score, bpm
    return int(round(best))


def onset_envelope(audio, hop=512):
    """Force des attaques (flux spectral), normalisée. Renvoie (enveloppe, images par seconde)."""
    mono = audio.mean(axis=1)
    _, _, Z = signal.stft(mono, nperseg=2048, noverlap=2048 - hop, boundary=None, padded=False)
    mag = np.log1p(100 * np.abs(Z))
    flux = np.maximum(0, np.diff(mag, axis=1)).mean(axis=0)
    flux = np.maximum(flux - np.convolve(flux, np.ones(43) / 43, "same"), 0)
    return flux / (flux.std() + 1e-9), SR / hop


def beat_period(beats):
    """Durée d'un temps (s), mesurée par régression sur tous les temps : précision bien
    meilleure que la résolution d'analyse (les intervalles un par un sont arrondis)."""
    if len(beats) < 4:
        return 0.0
    return float(np.polyfit(np.arange(len(beats)), beats, 1)[0])


def beat_track(audio, bpm, tightness=100):
    """Instants (secondes) de chaque temps du morceau.

    Suivi par programmation dynamique (D. Ellis, 2007) : suit les petites variations de tempo
    au lieu d'une grille rigide, puis vérifie que les temps tombent sur les kicks et pas sur les contretemps.
    """
    if not bpm:
        return np.array([])
    o, fps = onset_envelope(audio)
    period = 60 * fps / bpm
    g = signal.windows.gaussian(max(3, int(period)), period / 16)
    o = np.convolve(o, g / g.sum() * 4, "same")
    n = len(o)
    if n < 4 * period:
        return np.arange(0, len(audio) / SR, 60 / bpm)
    taus = np.arange(int(period / 2), int(2 * period) + 1)
    pen = -tightness * np.log(taus / period) ** 2
    score = o.copy()
    back = np.full(n, -1)
    for t in range(taus[0], n):
        c = t - taus
        v = c >= 0
        vals = score[c[v]] + pen[v]
        k = int(np.argmax(vals))
        if vals[k] > 0:
            score[t] = o[t] + vals[k]
            back[t] = c[v][k]
    last = n - int(period) + int(np.argmax(score[n - int(period):]))
    beats = []
    while last >= 0:
        beats.append(last)
        last = back[last]
    beats = np.array(beats[::-1], dtype=float) / fps
    # temps sur les attaques graves (kick) et pas sur les contretemps
    low = signal.sosfilt(signal.butter(2, 100, fs=SR, output="sos"), audio.mean(axis=1))
    hop = 512
    m = len(low) // hop
    env = np.sqrt(np.mean(low[: m * hop].reshape(m, hop) ** 2, axis=1))
    att = np.maximum(0, np.diff(env, prepend=env[0]))
    half = float(np.median(np.diff(beats))) / 2 if len(beats) > 2 else 30 / bpm

    def strength(times):
        idx = np.clip(np.round(times * fps).astype(int), 0, m - 3)
        return float(np.mean([att[i: i + 3].max() for i in idx])) if len(idx) else 0.0

    if strength(beats + half) > 1.3 * strength(beats):
        beats = beats + half
    # on prolonge la grille jusqu'au début et à la fin du morceau (pas = tempo moyen précis)
    step = beat_period(beats) or 60 / bpm
    dur = len(audio) / SR
    before = np.arange(beats[0] - step, -1e-9, -step)[::-1] if len(beats) else np.array([])
    after = np.arange(beats[-1] + step, dur, step) if len(beats) else np.arange(0, dur, step)
    return np.concatenate([before, beats, after])


def peaks(audio, buckets=1400):
    mono = np.abs(audio).max(axis=1) if audio.ndim == 2 else np.abs(audio)
    n = len(mono) // buckets
    if n < 1:
        return mono
    return mono[: n * buckets].reshape(buckets, n).max(axis=1)


# --------------------------------------------------------------------------- export
def to_int16(x):
    return (np.clip(x, -1, 1) * 32767).astype("<i2")


def write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(to_int16(x).tobytes())


def mp3_available():
    try:
        import lameenc  # noqa: F401
        return True
    except ImportError:
        return False


def write_mp3(path, x, kbps=256):
    import lameenc
    enc = lameenc.Encoder()
    enc.set_bit_rate(kbps)
    enc.set_in_sample_rate(SR)
    enc.set_channels(2)
    enc.set_quality(5)  # qualité standard de LAME : ~2× plus rapide, inaudible à 256 kbps
    data = enc.encode(to_int16(x).tobytes()) + enc.flush()
    with open(path, "wb") as f:
        f.write(data)
