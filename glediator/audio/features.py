from __future__ import annotations

from collections import deque

import numpy as np


class AudioFeatureExtractor:
    """Extract normalized bass/mid/treble bands, beat onset, and BPM from FFT frames."""

    def __init__(self, sample_rate: int = 44100, block_size: int = 1024, spectrum_bins: int = 1024) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.spectrum_bins = spectrum_bins
        self.frame_rate = sample_rate / max(1, block_size)

        nyquist = sample_rate / 2.0
        self._bass_slice = self._freq_slice(20.0, 250.0, nyquist)
        self._mid_slice = self._freq_slice(250.0, 2000.0, nyquist)
        self._treble_slice = self._freq_slice(2000.0, 16000.0, nyquist)

        self._band_peaks = {"bass": 0.1, "mid": 0.1, "treble": 0.1}
        self._prev_bass_spec: np.ndarray | None = None
        self._flux_history: deque[float] = deque(maxlen=max(10, int(self.frame_rate)))
        self._onset_history: deque[float] = deque(maxlen=max(32, int(self.frame_rate * 8)))
        self._last_beat_time = -1.0
        self._time_s = 0.0
        self.bpm = 0.0
        self._beat_phase = 0.0
        self._frames_since_bpm = 0

    def _freq_slice(self, low_hz: float, high_hz: float, nyquist: float) -> slice:
        b0 = max(0, int(np.floor(low_hz / nyquist * self.spectrum_bins)))
        b1 = min(self.spectrum_bins, max(b0 + 1, int(np.ceil(high_hz / nyquist * self.spectrum_bins))))
        return slice(b0, b1)

    def _norm_band(self, key: str, raw: float) -> float:
        peak = max(raw, self._band_peaks[key] * 0.992, 1e-4)
        self._band_peaks[key] = peak
        return float(np.clip(raw / peak, 0.0, 1.0))

    def process(self, spectrum: np.ndarray, dt_seconds: float | None = None) -> dict[str, float | bool]:
        spec = np.asarray(spectrum, dtype=np.float32)
        if spec.size != self.spectrum_bins:
            return {
                "audio_bass": 0.0,
                "audio_mid": 0.0,
                "audio_treble": 0.0,
                "audio_beat": False,
                "audio_bpm": self.bpm,
                "audio_beat_phase": self._beat_phase,
            }

        dt = self.block_size / self.sample_rate if dt_seconds is None else max(1e-4, float(dt_seconds))
        self._time_s += dt

        bass_spec = spec[self._bass_slice]
        bass = self._norm_band("bass", float(np.mean(bass_spec)))
        mid = self._norm_band("mid", float(np.mean(spec[self._mid_slice])))
        treble = self._norm_band("treble", float(np.mean(spec[self._treble_slice])))

        if self._prev_bass_spec is None:
            flux = 0.0
        else:
            diff = np.maximum(0.0, bass_spec - self._prev_bass_spec)
            flux = float(np.sum(diff))
        self._prev_bass_spec = bass_spec.copy()
        self._flux_history.append(flux)

        flux_arr = np.asarray(self._flux_history, dtype=np.float32)
        threshold = float(np.mean(flux_arr) + 1.4 * np.std(flux_arr))
        excess = max(0.0, flux - threshold)
        self._onset_history.append(excess)

        beat = False
        if flux > threshold and flux > 1e-3 and (self._time_s - self._last_beat_time) >= 0.15:
            beat = True
            self._last_beat_time = self._time_s
            self._beat_phase = 0.0
        elif self.bpm > 0:
            self._beat_phase = (self._beat_phase + dt * (self.bpm / 60.0)) % 1.0

        self._frames_since_bpm += 1
        if self._frames_since_bpm >= 10 and len(self._onset_history) >= int(self.frame_rate * 2.0):
            self._frames_since_bpm = 0
            self.bpm = self._estimate_bpm(dt)

        return {
            "audio_bass": bass,
            "audio_mid": mid,
            "audio_treble": treble,
            "audio_beat": beat,
            "audio_bpm": float(self.bpm),
            "audio_beat_phase": float(self._beat_phase),
        }

    def _estimate_bpm(self, dt: float) -> float:
        env = np.asarray(self._onset_history, dtype=np.float32)
        if float(np.max(env)) <= 1e-5:
            return 0.0
        env = np.convolve(env, np.array([0.2, 0.6, 1.0, 0.6, 0.2], dtype=np.float32), mode="same")
        env = env - float(np.mean(env))
        min_lag = max(1, round((60.0 / 180.0) / dt))
        max_lag = min(len(env) // 2, round((60.0 / 60.0) / dt))
        if max_lag <= min_lag:
            return self.bpm
        lags = list(range(min_lag, max_lag + 1))
        corrs = [float(np.dot(env[:-lag], env[lag:])) / max(1, len(env) - lag) for lag in lags]
        best_corr = max(corrs)
        if best_corr <= 0:
            return self.bpm
        idx = next(i for i, c in enumerate(corrs) if c >= 0.85 * best_corr)
        while idx + 1 < len(corrs) and corrs[idx + 1] > corrs[idx]:
            idx += 1
        lag_f = float(lags[idx])
        if 0 < idx < len(corrs) - 1:
            y0, y1, y2 = corrs[idx - 1], corrs[idx], corrs[idx + 1]
            denom = 2.0 * (y0 - 2.0 * y1 + y2)
            if abs(denom) > 1e-9:
                lag_f += float(np.clip((y0 - y2) / denom, -0.5, 0.5))
        return float(np.clip(60.0 / (lag_f * dt), 60.0, 180.0))
