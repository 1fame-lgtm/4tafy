"""Moteur de rendu du Studio — le même pour la pré-écoute en direct ET pour l'enregistrement,
donc le fichier enregistré est exactement ce que tu entends.

Qualité :
- calcul dans un fil (thread) dédié avec une petite réserve d'avance → pas de craquements quand
  l'interface est occupée ;
- tous les réglages « continus » (volume, réverbe, 8D, largeur…) glissent en douceur d'un bloc à
  l'autre → pas de clics quand on bouge un curseur ;
- vitesse lue avec une interpolation cubique (Hermite) → son net ;
- vrai limiteur avec anticipation (lookahead) au lieu d'une saturation ;
- micro-fondu après un saut (déplacement, Original/Modifié, changement de tonalité).
"""
import collections
import threading
import time

import numpy as np
from scipy.ndimage import maximum_filter1d
from PySide6.QtCore import QIODevice, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices
from scipy import signal

from . import studio_dsp as dsp

SR = dsp.SR
LIVE_BLOCK = 1024     # ≈ 23 ms
AHEAD_BLOCKS = 6      # réserve d'avance du fil de calcul (≈ 140 ms)
CEILING = 0.97        # plafond du limiteur (≈ -0,3 dBFS)


# =========================================================================== briques DSP à état
class PartitionedConvolver:
    """Convolution longue en temps réel (overlap-save, partitions uniformes)."""

    def __init__(self, ir, block):
        self.B = block
        L = len(ir)
        P = max(1, -(-L // block))
        pad = np.zeros((P * block, 2), np.float32)
        pad[:L] = ir
        self.H = np.fft.rfft(pad.reshape(P, block, 2), n=2 * block, axis=1).transpose(2, 0, 1).astype(np.complex64)
        self.fdl = np.zeros_like(self.H)
        self.prev = np.zeros((block, 2), np.float32)

    def adopt(self, other):
        """Reprend l'historique d'entrée d'une autre réverbe (pour enchaîner sans trou)."""
        P = min(self.fdl.shape[1], other.fdl.shape[1])
        self.fdl[:, :P] = other.fdl[:, :P]
        self.prev = other.prev.copy()

    def process(self, x):
        B = self.B
        buf = np.concatenate([self.prev, x])
        self.prev = x.copy()
        X = np.fft.rfft(buf, axis=0).T.astype(np.complex64)
        self.fdl = np.roll(self.fdl, 1, axis=1)
        self.fdl[:, 0] = X
        Y = np.einsum("cpk,cpk->ck", self.fdl, self.H)
        return np.fft.irfft(Y, n=2 * B, axis=1)[:, B:].T.astype(np.float32)


class Limiter:
    """Limiteur à anticipation : la baisse de gain commence ~1,5 ms avant le pic et remonte en douceur.
    Retard introduit : 2 × LOOK échantillons."""
    LOOK = 64

    def __init__(self, ceiling=CEILING, release_ms=120):
        L = self.LOOK
        self.ceiling = ceiling
        self.a = np.exp(-1 / (SR * release_ms / 1000))
        self.r_hist = np.zeros(3 * L)
        self.x_hist = np.zeros((2 * L, 2), np.float32)
        self.zi = np.zeros(1)
        self.engaged = 0

    def process(self, x):
        L = self.LOOK
        n = len(x)
        peak = np.abs(x).max(axis=1)
        r_new = 1 - np.minimum(1.0, self.ceiling / np.maximum(peak, 1e-9))
        R = np.concatenate([self.r_hist, r_new])
        rmax = maximum_filter1d(R, size=2 * L + 1, origin=-L)[: len(R) - 2 * L]  # maximum à venir (2L)
        c = np.concatenate([[0.0], np.cumsum(rmax)])
        need = (c[L + 1: L + 1 + n] - c[1: 1 + n]) / L                  # rampe d'attaque (moyenne sur L)
        rel, self.zi = signal.lfilter([1 - self.a], [1, -self.a], need, zi=self.zi)
        r = np.maximum(need, rel)                                       # relâchement progressif
        X = np.concatenate([self.x_hist, x])
        out = X[:n] * (1 - r)[:, None]
        self.r_hist, self.x_hist = R[-3 * L:], X[-2 * L:]
        if r.max() > 1e-3:
            self.engaged += 1
        return np.clip(out, -1, 1).astype(np.float32)


# =========================================================================== moteur
class Engine:
    """Applique tous les réglages bloc par bloc, en gardant l'état des filtres."""

    def __init__(self, block=LIVE_BLOCK, limiter=True):
        self.B = block
        self.use_limiter = limiter
        self.orig = None
        self.src = None
        self.p = dsp.params_with()
        self.pos = 0.0            # position (échantillons, dans le temps du son d'origine)
        self.bypass = False
        self.norm_gain = 1.0
        self.ended = False
        self.reset_states()

    # ------------------------------------------------------------------ état
    def reset_states(self):
        n = len(dsp.EQ_BANDS)
        self._eq_key, self._eq_sos, self._eq_zi = None, None, np.zeros((n, 2, 2))
        self._zi_fast, self._zi_slow, self._zi_comp = np.zeros(1), np.zeros(1), np.zeros(1)
        self._lofi_key, self._lofi_sos, self._lofi_zi = None, None, np.zeros((2, 2, 2))
        self._rev_key, self._rev = None, None
        self._ramps = {}
        self._rng = np.random.default_rng(3)
        self._declick = True
        self.limiter = Limiter()

    def set_audio(self, audio):
        self.orig = audio
        self.src = audio
        self.pos = 0.0
        self.ended = False
        self.reset_states()

    def set_source(self, data):
        self.src = data if data is not None else self.orig

    def set_params(self, p):
        self.p = p

    @property
    def t(self):
        return self.pos / SR

    def end_time(self):
        if self.orig is None:
            return 0.0
        full = len(self.orig) / SR
        return full if self.bypass or not self.p["end"] else min(full, self.p["end"])

    def seek(self, t_orig):
        lo = 0.0 if self.bypass else self.p["start"]
        self.pos = max(lo, min(t_orig, self.end_time() - 0.05)) * SR
        self.ended = False
        self._declick = True

    def speed(self):
        return 1.0 if self.bypass else self.p["speed"]

    # ------------------------------------------------------------------ outils
    def _ramp(self, key, value):
        """Valeur qui glisse de l'ancienne à la nouvelle sur un bloc (évite les clics)."""
        prev = self._ramps.get(key, value)
        self._ramps[key] = value
        if abs(prev - value) < 1e-9:
            return value
        return np.linspace(prev, value, self.B, endpoint=False, dtype=np.float32)

    def _read(self, src, speed):
        """Lecture à vitesse variable, interpolation cubique d'Hermite."""
        B = self.B
        pos = self.pos + np.arange(B) * speed
        end = self.end_time() * SR - 2
        valid = pos < end
        i = np.floor(pos).astype(np.int64)
        f = (pos - i).astype(np.float32)[:, None]
        n = len(src)
        xm1, x0 = src[np.clip(i - 1, 0, n - 1)], src[np.clip(i, 0, n - 1)]
        x1, x2 = src[np.clip(i + 1, 0, n - 1)], src[np.clip(i + 2, 0, n - 1)]
        c1 = 0.5 * (x1 - xm1)
        c2 = xm1 - 2.5 * x0 + 2 * x1 - 0.5 * x2
        c3 = 0.5 * (x2 - xm1) + 1.5 * (x0 - x1)
        x = ((c3 * f + c2) * f + c1) * f + x0
        x[~valid] = 0
        self.pos += B * speed
        if not valid.any():
            self.ended = True
        return x.astype(np.float32)

    # ------------------------------------------------------------------ un bloc
    def process_block(self):
        B = self.B
        if self.orig is None or self.ended:
            return np.zeros((B, 2), np.float32)
        p = self.p
        if self.bypass:
            x = self._read(self.orig, 1.0)
            return self._finish(x, limiter=False)
        speed = p["speed"]
        t_out0 = (self.pos / SR - p["start"]) / speed
        x = self._read(self.src, speed)

        # égaliseur
        key = tuple(p["eq"])
        if key != self._eq_key:
            self._eq_key, self._eq_sos = key, dsp.eq_sos_full(p["eq"])
        if any(abs(g) > 0.05 for g in p["eq"]) or np.abs(self._eq_zi).max() > 1e-7:
            x, self._eq_zi = signal.sosfilt(self._eq_sos, x, axis=0, zi=self._eq_zi)

        # impact des beats
        amt = self._ramp("beats", p["beats"] / 100)
        if np.max(amt) > 0:
            mono = np.abs(x.mean(axis=1))
            af, aslow = np.exp(-1 / (SR * 0.004)), np.exp(-1 / (SR * 0.070))
            fast, self._zi_fast = signal.lfilter([1 - af], [1, -af], mono, zi=self._zi_fast)
            slow, self._zi_slow = signal.lfilter([1 - aslow], [1, -aslow], mono, zi=self._zi_slow)
            attack = np.clip((fast - slow) / (slow + 1e-4), 0, 3)
            x = x * (1 + amt * 1.6 * attack)[:, None]

        # compression
        amt = self._ramp("punch", p["punch"] / 100)
        if np.max(amt) > 0:
            thr, ratio = -6 - 24 * amt, 2 + 4 * amt
            ac = np.exp(-1 / (SR * 0.015))
            env, self._zi_comp = signal.lfilter([1 - ac], [1, -ac], np.abs(x.mean(axis=1)), zi=self._zi_comp)
            gr = np.minimum(0, (thr - 20 * np.log10(env + 1e-6)) * (1 - 1 / ratio))
            x = x * (10 ** ((gr - thr * (1 - 1 / ratio) * 0.5) / 20))[:, None]

        # lo-fi
        amt = self._ramp("lofi", p["lofi"] / 100)
        if np.max(amt) > 0:
            a = float(p["lofi"]) / 100
            k = int(p["lofi"])
            if k != self._lofi_key:
                self._lofi_key = k
                self._lofi_sos = signal.butter(4, 16000 * (1 - a) + 2800 * a, fs=SR, output="sos")
            wet, self._lofi_zi = signal.sosfilt(self._lofi_sos, x, axis=0, zi=self._lofi_zi)
            q = 2 ** (16 - 9 * a)
            wet = np.round(wet * q) / q
            noise = (self._rng.random(B) > 0.9997) * self._rng.normal(0, 0.08 * a, B) + self._rng.normal(0, 0.004 * a, B)
            wet = wet + noise[:, None]
            m = amt if np.isscalar(amt) else amt[:, None]
            x = (1 - m) * x + m * wet

        # largeur stéréo
        w = self._ramp("width", p["width"] / 100)
        if not (np.isscalar(w) and w == 1.0):
            mid = (x[:, 0] + x[:, 1]) / 2
            side = (x[:, 0] - x[:, 1]) / 2 * w
            x = np.stack([mid + side, mid - side], axis=1)

        # audio 8D
        a = self._ramp("pan8d", p["pan8d"] / 100)
        if np.max(a) > 0:
            rate = 0.06 + 0.14 * float(p["pan8d"]) / 100
            t = t_out0 + np.arange(B) / SR
            theta = (np.sin(2 * np.pi * rate * t) + 1) * np.pi / 4
            mid = x.mean(axis=1)
            moving = np.stack([mid * np.cos(theta), mid * np.sin(theta)], axis=1) * np.sqrt(2)
            m = a if np.isscalar(a) else a[:, None]
            x = (1 - m) * x + m * moving

        # réverbération (fondu enchaîné quand on change la taille de la salle)
        a = self._ramp("reverb", p["reverb"] / 100)
        if np.max(a) > 0 or self._rev is not None:
            k = int(p["reverb"] // 4)
            if p["reverb"] > 0 and k != self._rev_key:
                old = self._rev
                new = PartitionedConvolver(dsp.reverb_ir(max(1, k * 4)), B)
                if old is not None:
                    new.adopt(old)
                    xf = np.linspace(0, 1, B, dtype=np.float32)[:, None]
                    wet = (1 - xf) * old.process(x) + xf * new.process(x)
                else:
                    wet = new.process(x)
                self._rev, self._rev_key = new, k
            else:
                wet = self._rev.process(x) if self._rev is not None else np.zeros_like(x)
            m = a if np.isscalar(a) else a[:, None]
            x = (1 - 0.35 * m) * x + 0.55 * m * wet
            if p["reverb"] == 0 and np.isscalar(a):
                self._rev, self._rev_key = None, None

        # volume (+ normalisation) en douceur
        g = self._ramp("gain", 10 ** (p["gain"] / 20) * (self.norm_gain if p["normalize"] else 1.0))
        x = x * (g if np.isscalar(g) else g[:, None])

        # fondus
        if p["fade_in"] > 0 or p["fade_out"] > 0:
            t = t_out0 + np.arange(B) / SR
            env = np.ones(B)
            if p["fade_in"] > 0:
                env *= np.sin(np.clip(t / p["fade_in"], 0, 1) * np.pi / 2) ** 2
            if p["fade_out"] > 0:
                remaining = (self.end_time() - p["start"]) / speed - t
                env *= np.sin(np.clip(remaining / p["fade_out"], 0, 1) * np.pi / 2) ** 2
            x = x * env[:, None]
        return self._finish(x.astype(np.float32), limiter=self.use_limiter)

    def _finish(self, x, limiter):
        if self._declick:  # micro-fondu de 6 ms après un saut
            k = min(len(x), 256)
            x[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
            self._declick = False
        if limiter:
            return self.limiter.process(x)
        return np.clip(x, -1, 1).astype(np.float32) if self.use_limiter else x


# =========================================================================== rendu complet (enregistrement)
def render_offline(audio, params, pitched=None, progress=None):
    """Rend le son complet avec le MÊME moteur que la pré-écoute. Renvoie (son, infos)."""
    p = dsp.params_with(params)
    if p["pitch"] and pitched is None:
        pitched = dsp.pitch_shift(audio, int(p["pitch"]))
        n = len(audio)
        pitched = pitched[:n] if len(pitched) >= n else np.pad(pitched, ((0, n - len(pitched)), (0, 0)))
    end = p["end"] or len(audio) / SR
    n_out = int((end - p["start"]) * SR / p["speed"])

    def run(pp, limiter, norm_gain):
        e = Engine(block=4096, limiter=limiter)
        e.set_audio(audio)
        e.set_source(pitched if pp["pitch"] else None)
        e.set_params(pp)
        e.norm_gain = norm_gain
        e.seek(pp["start"])
        e._declick = False
        delay = 2 * Limiter.LOOK if limiter else 0
        chunks, total = [], 0
        while total < n_out + delay:
            blk = e.process_block()
            chunks.append(blk)
            total += len(blk)
            if progress:
                progress(min(1.0, total / max(1, n_out)))
        y = np.concatenate(chunks)[delay: delay + n_out]
        return y, e

    norm_gain = 1.0
    if p["normalize"]:  # 1re passe : mesure du pic sans limiteur
        raw, _ = run(dict(p, normalize=False), limiter=False, norm_gain=1.0)
        peak = float(np.max(np.abs(raw))) if len(raw) else 0.0
        norm_gain = 0.891 / peak if peak > 0 else 1.0
        del raw
    y, e = run(p, limiter=True, norm_gain=norm_gain)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    rms = float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) if len(y) else 0.0
    info = {"duration": len(y) / SR, "peak_db": 20 * np.log10(max(peak, 1e-6)),
            "rms_db": 20 * np.log10(max(rms, 1e-6)), "limited": e.limiter.engaged > 0, "norm_gain": norm_gain}
    return y, info


# =========================================================================== lecture en direct
class _RingDevice(QIODevice):
    """La carte son vient piocher ici : on ne fait que copier des données déjà calculées."""

    def __init__(self, player):
        super().__init__(player)
        self.pl = player

    def readData(self, maxlen):
        return self.pl._consume(max(0, maxlen // 4))

    def writeData(self, data):
        return 0

    def bytesAvailable(self):
        return 1 << 20

    def isSequential(self):
        return True


class LivePlayer(QObject):
    """Pré-écoute temps réel : un fil calcule les blocs un peu en avance, la carte son les lit."""
    state_changed = Signal(bool)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = Engine(LIVE_BLOCK)
        self.lock = threading.RLock()
        self.ring = collections.deque()   # (bloc, position de départ, vitesse, est_le_dernier)
        self.ring_frames = 0
        self._offset = 0                  # échantillons déjà lus du 1er bloc
        self.play_pos = 0.0               # position réellement entendue (échantillons, temps d'origine)
        self.peak = np.zeros(2, np.float32)
        self.playing = False
        self.underruns = 0
        self._started = False
        self._stop = False
        self.device = _RingDevice(self)
        self.device.open(QIODevice.ReadOnly)
        fmt = QAudioFormat()
        fmt.setSampleRate(SR)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self.sink.setBufferSize(LIVE_BLOCK * 4 * 4)  # ≈ 93 ms
        self._thread = threading.Thread(target=self._producer, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ fil de calcul
    def _producer(self):
        while not self._stop:
            if self.playing and self.ring_frames < AHEAD_BLOCKS * LIVE_BLOCK:
                with self.lock:
                    e = self.engine
                    start, sp = e.pos, e.speed()
                    was_ended = e.ended
                    blk = e.process_block()
                    last = e.ended and not was_ended
                    self.ring.append((blk, start, sp, last))
                    self.ring_frames += len(blk)
            else:
                time.sleep(0.004)

    def _consume(self, frames):
        out = np.zeros((frames, 2), np.float32)
        if not self.playing:  # en pause : la carte son tourne mais reçoit du silence
            return out.astype("<i2").tobytes()
        filled = 0
        ended = False
        with self.lock:
            while filled < frames and self.ring:
                blk, start, sp, last = self.ring[0]
                take = min(frames - filled, len(blk) - self._offset)
                out[filled: filled + take] = blk[self._offset: self._offset + take]
                self._offset += take
                filled += take
                self.play_pos = start + self._offset * sp
                if self._offset >= len(blk):
                    self.ring.popleft()
                    self.ring_frames -= len(blk)
                    self._offset = 0
                    ended = ended or last
        if self.playing and filled < frames:
            self.underruns += 1
        if filled:
            self.peak = np.maximum(self.peak * 0.8, np.abs(out[:filled]).max(axis=0))
        if ended:
            QTimer.singleShot(0, self._on_end)
        return (out * 32767).astype("<i2").tobytes()

    def _flush(self):
        """Vide la réserve et repart de la position entendue (changement instantané)."""
        with self.lock:
            self.ring.clear()
            self.ring_frames = 0
            self._offset = 0

    # ------------------------------------------------------------------ API
    def set_audio(self, audio):
        with self.lock:
            self.engine.set_audio(audio)
            self._flush()
            self.play_pos = 0.0

    def set_params(self, p):
        self.engine.set_params(p)

    def set_source(self, data):
        with self.lock:
            if self.engine.src is (data if data is not None else self.engine.orig):
                return
            self.engine.set_source(data)
            self.resync()

    def set_bypass(self, on):
        with self.lock:
            if self.engine.bypass == on:
                return
            self.engine.bypass = on
            self.resync()

    def resync(self):
        """Applique immédiatement un changement (A/B, tonalité, préréglage) depuis la position entendue."""
        with self.lock:
            pos = self.play_pos / SR if (self.ring or self.playing) else self.engine.t
            self._flush()
            self.engine.seek(pos)
            self.play_pos = self.engine.pos

    def seek(self, t_orig):
        with self.lock:
            self._flush()
            self.engine.seek(t_orig)
            self.play_pos = self.engine.pos

    def position(self):
        """Temps (secondes, son d'origine) de ce qu'on entend."""
        return (self.play_pos if (self.ring or self.playing) else self.engine.pos) / SR

    def output_time(self):
        e = self.engine
        t = self.position()
        if e.bypass:
            return t, e.end_time()
        sp = e.p["speed"]
        return (t - e.p["start"]) / sp, (e.end_time() - e.p["start"]) / sp

    def set_volume(self, v):
        self.sink.setVolume(v)

    def play(self):
        if self.engine.orig is None:
            return
        if self.engine.ended:
            self.seek(0 if self.engine.bypass else self.engine.p["start"])
        # NB : on ne suspend jamais la carte son (resume() de Qt ne repart pas sous Windows) ;
        # en pause elle reçoit du silence, et la lecture reprend exactement où on s'était arrêté.
        if not self._started or self.sink.state() in (QAudio.StoppedState, QAudio.SuspendedState):
            if self._started:
                self.sink.stop()
            self.sink.start(self.device)
            self._started = True
        self.playing = True
        self.state_changed.emit(True)

    def pause(self):
        if self.playing:
            with self.lock:
                self.playing = False
                heard = self.play_pos / SR  # la reprise se fera depuis ce qu'on entendait
                self._flush()
                self.engine.seek(heard)
                self.play_pos = self.engine.pos
        self.state_changed.emit(False)

    def stop(self):
        self._stop = True
        if self._started:
            self.sink.stop()
            self._started = False
        self.playing = False
        self.state_changed.emit(False)

    def _on_end(self):
        self.pause()
        self.seek(0 if self.engine.bypass else self.engine.p["start"])
        self.finished.emit()
