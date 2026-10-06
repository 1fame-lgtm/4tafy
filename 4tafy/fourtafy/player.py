"""Lecteur audio basé sur QtMultimedia (backend FFmpeg : mp3, m4a, webm, flac, ogg, wav…)."""
import random
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


class Player(QObject):
    track_changed = Signal(object)      # dict du titre ou None
    playing_changed = Signal(bool)
    position_changed = Signal(int)      # ms
    duration_changed = Signal(int)      # ms
    queue_changed = Signal()
    error = Signal(str)

    def __init__(self, library):
        super().__init__()
        self.lib = library
        self.mp = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.mp.setAudioOutput(self.out)
        self.queue = []        # ids dans l'ordre de lecture
        self.original = []     # ordre d'origine (pour désactiver l'aléatoire)
        self.index = -1
        self.shuffle = False
        self.repeat = REPEAT_OFF
        self._errors_in_row = 0
        self._token = 0
        self._want_play = False
        self.mp.mediaStatusChanged.connect(self._on_status)
        self.mp.playbackStateChanged.connect(
            lambda s: self.playing_changed.emit(s == QMediaPlayer.PlayingState))
        self.mp.positionChanged.connect(lambda ms: self.position_changed.emit(int(ms)))
        self.mp.durationChanged.connect(lambda ms: self.duration_changed.emit(int(ms)))
        self.mp.errorOccurred.connect(self._on_error)

    # ------------------------------------------------------------------ état
    @property
    def current_id(self):
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    @property
    def current(self):
        return self.lib.get(self.current_id) if self.current_id else None

    def is_playing(self):
        return self.mp.playbackState() == QMediaPlayer.PlayingState

    def upcoming(self):
        return self.queue[self.index + 1:] if self.index >= 0 else list(self.queue)

    # ------------------------------------------------------------------ commandes
    def play_list(self, ids, start=0):
        ids = [i for i in ids if self.lib.get(i)]
        if not ids:
            return
        start = max(0, min(start, len(ids) - 1))
        self.original = list(ids)
        if self.shuffle:
            first = ids[start]
            rest = ids[:start] + ids[start + 1:]
            random.shuffle(rest)
            self.queue = [first] + rest
            self._play_index(0)
        else:
            self.queue = list(ids)
            self._play_index(start)
        self.queue_changed.emit()

    def play_shuffled(self, ids):
        self.set_shuffle(True)
        if ids:
            self.play_list(ids, random.randrange(len(ids)))

    def _play_index(self, i):
        if not (0 <= i < len(self.queue)):
            return
        self.index = i
        t = self.current
        if not t or not t.get("path") or not Path(t["path"]).exists():
            self.error.emit(f"Fichier introuvable : {t['title'] if t else '?'}")
            self._errors_in_row += 1
            if self._errors_in_row < len(self.queue):
                self.next(auto=True)
            return
        self._token += 1              # identifie le titre chargé (ignore les signaux de l'ancien)
        self.mp.stop()
        self.mp.setSource(QUrl.fromLocalFile(t["path"]))
        self._want_play = True        # relancé dès que le titre est chargé (voir _on_status)
        self.mp.play()
        t["plays"] = t.get("plays", 0) + 1
        self.track_changed.emit(t)
        self.queue_changed.emit()

    def toggle(self):
        if self.current_id is None:
            return False
        if self.is_playing() or self._want_play:
            self._want_play = False
            self.mp.pause()
        else:
            self.mp.play()
        return True

    def next(self, auto=False):
        if not self.queue:
            return
        if self.index + 1 < len(self.queue):
            self._play_index(self.index + 1)
        elif self.repeat == REPEAT_ALL or not auto:
            self._play_index(0)
        else:
            self.mp.stop()
            self.mp.setPosition(0)

    def prev(self):
        if self.mp.position() > 3000 or self.index <= 0:
            self.mp.setPosition(0)
        else:
            self._play_index(self.index - 1)

    def seek(self, ms):
        self.mp.setPosition(int(ms))

    def set_volume(self, v):
        self.out.setVolume((max(0, min(100, v)) / 100.0) ** 1.6)  # courbe plus naturelle

    def set_muted(self, m):
        self.out.setMuted(m)

    def set_shuffle(self, on):
        if on == self.shuffle:
            return
        self.shuffle = on
        cur = self.current_id
        if on:
            self.original = list(self.queue)
            rest = self.upcoming()
            random.shuffle(rest)
            self.queue = self.queue[:self.index + 1] + rest
        elif self.original:
            self.queue = list(self.original)
            self.index = self.queue.index(cur) if cur in self.queue else -1
        self.queue_changed.emit()

    def cycle_repeat(self):
        self.repeat = (self.repeat + 1) % 3
        return self.repeat

    def enqueue(self, ids, play_next=False):
        ids = [i for i in ids if self.lib.get(i)]
        if not ids:
            return
        if not self.queue:
            self.play_list(ids)
            return
        pos = self.index + 1 if play_next else len(self.queue)
        self.queue[pos:pos] = ids
        self.original += ids
        self.queue_changed.emit()

    def remove_from_queue(self, positions):
        for pos in sorted(positions, reverse=True):
            if 0 <= pos < len(self.queue) and pos != self.index:
                del self.queue[pos]
                if pos < self.index:
                    self.index -= 1
        self.queue_changed.emit()

    def jump_to(self, pos):
        self._play_index(pos)

    def forget(self, tids):
        """Retire des titres supprimés de la bibliothèque."""
        cur = self.current_id
        if cur in tids:
            self.mp.stop()
            self.mp.setSource(QUrl())
            cur = None
        self.queue = [t for t in self.queue if t not in tids]
        self.original = [t for t in self.original if t not in tids]
        self.index = self.queue.index(cur) if cur in self.queue else -1
        if cur is None:
            self.track_changed.emit(None)
        self.queue_changed.emit()

    # ------------------------------------------------------------------ évènements
    def _on_status(self, status):
        if status == QMediaPlayer.BufferedMedia or status == QMediaPlayer.LoadedMedia:
            self._errors_in_row = 0
            # après un changement de titre, le lecteur Qt ignore parfois play() tant que le fichier
            # n'est pas chargé : on relance la lecture à ce moment-là
            if self._want_play:
                self._want_play = False
                if self.mp.playbackState() != QMediaPlayer.PlayingState:
                    self.mp.play()
        if status == QMediaPlayer.EndOfMedia:
            # On enchaîne APRÈS ce signal (relancer le lecteur pendant son propre signal de fin
            # provoquait un 2e « fin » fantôme qui arrêtait la playlist sur le titre suivant).
            QTimer.singleShot(0, lambda tok=self._token: self._on_end(tok))

    def _on_end(self, token):
        if token != self._token:
            return  # signal d'un titre précédent : on l'ignore
        d = self.mp.duration()
        if d > 0 and self.mp.position() < d - 2000 and self.mp.position() > 0:
            return  # « fin » parasite alors que le titre n'est pas terminé
        if self.repeat == REPEAT_ONE:
            self.mp.setPosition(0)
            self.mp.play()
        else:
            self.next(auto=True)

    def _on_error(self, _err, msg):
        t = self.current
        self.error.emit(f"Lecture impossible ({t['title'] if t else '?'}) : {msg}")
        self._errors_in_row += 1
        if self._errors_in_row < max(2, len(self.queue)):
            self.next(auto=True)
