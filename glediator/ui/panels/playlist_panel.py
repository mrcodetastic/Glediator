from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.core.fader import TRANSITION_KINDS
from glediator.core.sequencer import SequencerStatus


class PlaylistPanel(QWidget):
    playlists_changed = Signal()

    NO_SCENES_MSG = "Save some scenes first to continue"

    def __init__(self, engine: RenderEngine, config: EngineConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.config = config

        layout = QVBoxLayout(self)

        self.guide_label = QLabel("")
        self.guide_label.setWordWrap(True)
        self.guide_label.setStyleSheet("color:#ffb84a; font-size:9pt;")
        layout.addWidget(self.guide_label)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Playlist"))
        self.playlist_combo = QComboBox()
        self.playlist_combo.setMinimumWidth(220)
        self.playlist_combo.currentIndexChanged.connect(self._load_selected_playlist)
        self.new_btn = QPushButton("New…")
        self.new_btn.clicked.connect(self._new_playlist)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete_playlist)
        top_row.addWidget(self.playlist_combo, 1)
        top_row.addWidget(self.new_btn)
        top_row.addWidget(self.del_btn)
        layout.addLayout(top_row)

        self.entry_list = QListWidget()
        layout.addWidget(self.entry_list, 1)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Scene"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(160)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["time", "beats"])
        self.mode_combo.setToolTip("Advance after elapsed seconds (time) or audio beats (beats)")
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(1.0, 600.0)
        self.value_spin.setValue(10.0)
        self.value_spin.setToolTip("Duration in seconds or number of beats")
        self.trans_combo = QComboBox()
        self.trans_combo.addItems(list(TRANSITION_KINDS))
        self.trans_dur_spin = QSpinBox()
        self.trans_dur_spin.setRange(0, 15)
        self.trans_dur_spin.setValue(2)
        self.trans_dur_spin.setSuffix(" s")
        self.add_entry_btn = QPushButton("+ Add")
        self.add_entry_btn.clicked.connect(self._add_entry)
        self.remove_entry_btn = QPushButton("Remove")
        self.remove_entry_btn.clicked.connect(self._remove_entry)
        add_row.addWidget(self.preset_combo, 1)
        add_row.addWidget(self.mode_combo)
        add_row.addWidget(self.value_spin)
        add_row.addWidget(self.trans_combo)
        add_row.addWidget(self.trans_dur_spin)
        add_row.addWidget(self.add_entry_btn)
        add_row.addWidget(self.remove_entry_btn)
        layout.addLayout(add_row)

        opts_row = QHBoxLayout()
        self.loop_chk = QCheckBox("Loop")
        self.loop_chk.setChecked(True)
        self.loop_chk.toggled.connect(self._update_playlist_flags)
        self.shuffle_chk = QCheckBox("Shuffle")
        self.shuffle_chk.toggled.connect(self._update_playlist_flags)
        self.prev_btn = QPushButton("Prev")
        self.prev_btn.clicked.connect(self.engine.prev_playlist_entry)
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.engine.next_playlist_entry)
        opts_row.addWidget(self.loop_chk)
        opts_row.addWidget(self.shuffle_chk)
        opts_row.addStretch(1)
        opts_row.addWidget(self.prev_btn)
        opts_row.addWidget(self.play_btn)
        opts_row.addWidget(self.next_btn)
        layout.addLayout(opts_row)

        status_row = QHBoxLayout()
        self.now_playing = QLabel("Stopped")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_row.addWidget(self.now_playing)
        status_row.addWidget(self.progress, 1)
        layout.addLayout(status_row)

        self.refresh_presets()
        self.refresh_playlists()

    def refresh_presets(self) -> None:
        self.preset_combo.clear()
        if not self.config.presets:
            self.preset_combo.addItem(self.NO_SCENES_MSG)
        else:
            for preset in self.config.presets:
                self.preset_combo.addItem(str(preset["name"]))
        self._update_guidance_and_enabled()

    def refresh_playlists(self) -> None:
        self.playlist_combo.blockSignals(True)
        current = self.playlist_combo.currentText()
        self.playlist_combo.clear()
        has_scenes = bool(self.config.presets)
        named = [p for p in self.config.playlists if isinstance(p, dict) and p.get("name")]
        if not has_scenes:
            self.playlist_combo.addItem(self.NO_SCENES_MSG)
        elif not named:
            self.playlist_combo.addItem("No playlists yet — click 'New…' to create one")
        else:
            for pl in named:
                self.playlist_combo.addItem(str(pl["name"]))
            if current:
                idx = self.playlist_combo.findText(current)
                if idx >= 0:
                    self.playlist_combo.setCurrentIndex(idx)
        self.playlist_combo.blockSignals(False)
        self._load_selected_playlist()

    def _current_playlist(self) -> dict | None:
        if not self.config.presets:
            return None
        name = self.playlist_combo.currentText()
        return next((p for p in self.config.playlists if p.get("name") == name), None)

    def _update_guidance_and_enabled(self) -> None:
        has_scenes = bool(self.config.presets)
        pl = self._current_playlist()
        has_pl = pl is not None
        has_entries = bool(pl and pl.get("entries"))

        if not has_scenes:
            self.guide_label.setText(
                "Save some scenes first to continue — use 'Save as preset…' in the top bar, "
                "then click 'New…' here to build an automated playlist."
            )
            self.guide_label.setVisible(True)
        elif not has_pl:
            self.guide_label.setText("Click 'New…' to create a playlist, then add saved scenes below.")
            self.guide_label.setVisible(True)
        elif not has_entries:
            self.guide_label.setText("Pick a saved scene below and click '+ Add' to queue it into this playlist.")
            self.guide_label.setVisible(True)
        else:
            self.guide_label.setVisible(False)

        self.new_btn.setEnabled(has_scenes)
        self.del_btn.setEnabled(has_pl)
        self.preset_combo.setEnabled(has_scenes and has_pl)
        self.mode_combo.setEnabled(has_scenes and has_pl)
        self.value_spin.setEnabled(has_scenes and has_pl)
        self.trans_combo.setEnabled(has_scenes and has_pl)
        self.trans_dur_spin.setEnabled(has_scenes and has_pl)
        self.add_entry_btn.setEnabled(has_scenes and has_pl)
        self.remove_entry_btn.setEnabled(has_entries)
        self.loop_chk.setEnabled(has_pl)
        self.shuffle_chk.setEnabled(has_pl)
        self.prev_btn.setEnabled(has_entries)
        self.play_btn.setEnabled(has_entries)
        self.next_btn.setEnabled(has_entries)

    def _load_selected_playlist(self) -> None:
        self.entry_list.clear()
        pl = self._current_playlist()
        if pl:
            self.loop_chk.blockSignals(True)
            self.loop_chk.setChecked(bool(pl.get("loop", True)))
            self.loop_chk.blockSignals(False)
            self.shuffle_chk.blockSignals(True)
            self.shuffle_chk.setChecked(bool(pl.get("shuffle", False)))
            self.shuffle_chk.blockSignals(False)
            for idx, entry in enumerate(pl.get("entries", [])):
                mode = entry.get("mode", "time")
                val = (
                    f"{entry.get('beats', 8)} beats"
                    if mode == "beats"
                    else f"{entry.get('duration_s', 10.0):.1f} s"
                )
                text = (
                    f"{idx + 1}. {entry.get('preset', '')}  ·  {val}  ·  "
                    f"{entry.get('transition_kind', 'crossfade')} ({entry.get('transition_s', 1.5):.1f}s)"
                )
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, idx)
                self.entry_list.addItem(item)
        self._update_guidance_and_enabled()

    def _new_playlist(self) -> None:
        if not self.config.presets:
            return
        name, ok = QInputDialog.getText(self, "New Playlist", "Playlist name:")
        name = name.strip()
        if not ok or not name:
            return
        if not any(p.get("name") == name for p in self.config.playlists):
            self.config.playlists.append({"name": name, "entries": [], "loop": True, "shuffle": False})
        self.refresh_playlists()
        self.playlist_combo.setCurrentText(name)
        self.playlists_changed.emit()

    def _delete_playlist(self) -> None:
        pl = self._current_playlist()
        if not pl:
            return
        name = pl["name"]
        self.config.playlists = [p for p in self.config.playlists if p.get("name") != name]
        self.refresh_playlists()
        self.playlists_changed.emit()

    def _add_entry(self) -> None:
        pl = self._current_playlist()
        if not pl or not self.config.presets:
            return
        preset = self.preset_combo.currentText()
        if not preset or preset == self.NO_SCENES_MSG:
            return
        mode = self.mode_combo.currentText()
        entry = {
            "preset": preset,
            "mode": mode,
            "duration_s": float(self.value_spin.value()),
            "beats": int(self.value_spin.value()),
            "transition_kind": self.trans_combo.currentText(),
            "transition_s": float(self.trans_dur_spin.value()),
        }
        pl.setdefault("entries", []).append(entry)
        self._load_selected_playlist()
        self.playlists_changed.emit()

    def _remove_entry(self) -> None:
        pl = self._current_playlist()
        row = self.entry_list.currentRow()
        if not pl or row < 0:
            return
        entries = pl.get("entries", [])
        if 0 <= row < len(entries):
            entries.pop(row)
            self._load_selected_playlist()
            self.playlists_changed.emit()

    def _update_playlist_flags(self) -> None:
        pl = self._current_playlist()
        if not pl:
            return
        pl["loop"] = self.loop_chk.isChecked()
        pl["shuffle"] = self.shuffle_chk.isChecked()
        self.playlists_changed.emit()

    def toggle_play(self) -> None:
        st = self.engine.status().sequencer
        if st.playing:
            self.engine.stop_playlist()
            return
        pl = self._current_playlist()
        if pl:
            self.engine.play_playlist(pl)

    def sync_status(self, seq: SequencerStatus) -> None:
        self.play_btn.setText("Stop" if seq.playing else "Play")
        if seq.playing:
            self.now_playing.setText(f"{seq.playlist_name}: {seq.preset_name}")
            self.progress.setValue(round(seq.progress * 100))
        else:
            self.now_playing.setText("Stopped")
            self.progress.setValue(0)
