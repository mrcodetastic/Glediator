from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass
class SequencerStatus:
    playing: bool = False
    playlist_name: str = ""
    entry_index: int = -1
    preset_name: str = ""
    progress: float = 0.0


class PlaylistSequencer:
    """Timed or beat-driven preset sequencer that transitions to the inactive source."""

    def __init__(self, clock=time.monotonic, rng: random.Random | None = None) -> None:
        self._clock = clock
        self._rng = rng or random.Random()
        self.playing = False
        self.playlist: dict | None = None
        self.index = -1
        self._entry_started_at = 0.0
        self._beat_count = 0
        self._last_side = "left"

    def play(self, playlist: dict) -> dict | None:
        entries = playlist.get("entries", []) if isinstance(playlist, dict) else []
        if not entries:
            self.stop()
            return None
        self.playlist = playlist
        self.playing = True
        self.index = 0
        self._entry_started_at = self._clock()
        self._beat_count = 0
        return entries[0]

    def stop(self) -> None:
        self.playing = False
        self.index = -1
        self._beat_count = 0

    def _pick_next_index(self, step: int = 1) -> int | None:
        if not self.playlist:
            return None
        entries = self.playlist.get("entries", [])
        if not entries:
            return None
        if self.playlist.get("shuffle") and len(entries) > 1 and step > 0:
            choices = [i for i in range(len(entries)) if i != self.index]
            return self._rng.choice(choices)
        nxt = self.index + step
        if nxt >= len(entries):
            if self.playlist.get("loop", True):
                return 0
            return None
        if nxt < 0:
            return len(entries) - 1 if self.playlist.get("loop", True) else 0
        return nxt

    def advance(self, step: int = 1) -> dict | None:
        nxt = self._pick_next_index(step)
        if nxt is None:
            self.stop()
            return None
        self.index = nxt
        self._entry_started_at = self._clock()
        self._beat_count = 0
        return self.playlist["entries"][nxt]  # type: ignore[index]

    def tick(self, beat_fired: bool = False) -> dict | None:
        if not self.playing or not self.playlist:
            return None
        entries = self.playlist.get("entries", [])
        if not (0 <= self.index < len(entries)):
            self.stop()
            return None
        entry = entries[self.index]
        mode = entry.get("mode", "time")
        if mode == "beats":
            if beat_fired:
                self._beat_count += 1
            target_beats = max(1, int(entry.get("beats", 8)))
            if self._beat_count >= target_beats:
                return self.advance(1)
        else:
            duration = max(0.2, float(entry.get("duration_s", 10.0)))
            if (self._clock() - self._entry_started_at) >= duration:
                return self.advance(1)
        return None

    def status(self) -> SequencerStatus:
        if not self.playing or not self.playlist:
            return SequencerStatus()
        entries = self.playlist.get("entries", [])
        if not (0 <= self.index < len(entries)):
            return SequencerStatus()
        entry = entries[self.index]
        if entry.get("mode") == "beats":
            target = max(1, int(entry.get("beats", 8)))
            prog = min(1.0, self._beat_count / target)
        else:
            duration = max(0.2, float(entry.get("duration_s", 10.0)))
            prog = min(1.0, max(0.0, (self._clock() - self._entry_started_at) / duration))
        return SequencerStatus(
            playing=True,
            playlist_name=str(self.playlist.get("name", "")),
            entry_index=self.index,
            preset_name=str(entry.get("preset", "")),
            progress=prog,
        )
