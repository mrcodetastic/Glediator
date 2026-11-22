from __future__ import annotations

import copy
import time
from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from glediator.core.engine import RenderEngine


class RestoreSceneCommand(QUndoCommand):
    def __init__(
        self,
        engine: RenderEngine,
        side: str,
        before: dict,
        after: dict,
        text: str,
        on_sync: Callable[[], None],
    ) -> None:
        super().__init__(text)
        self.engine = engine
        self.side = side
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.on_sync = on_sync
        self._first = True

    def redo(self) -> None:
        if self._first:
            self._first = False
            return
        self.engine.load_scene_state(self.side, self.after)
        self.on_sync()

    def undo(self) -> None:
        self.engine.load_scene_state(self.side, self.before)
        self.on_sync()


class SetParametersCommand(QUndoCommand):
    def __init__(
        self,
        engine: RenderEngine,
        side: str,
        layer_index: int,
        before: dict,
        after: dict,
        on_sync: Callable[[], None],
    ) -> None:
        super().__init__(f"Edit parameters ({side} L{layer_index + 1})")
        self.engine = engine
        self.side = side
        self.layer_index = layer_index
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.on_sync = on_sync
        self._first = True
        self._timestamp = time.monotonic()

    def id(self) -> int:
        return 1001

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetParametersCommand):
            return False
        if (
            other.side != self.side
            or other.layer_index != self.layer_index
            or (other._timestamp - self._timestamp) > 0.5
        ):
            return False
        self.after = copy.deepcopy(other.after)
        self._timestamp = other._timestamp
        return True

    def redo(self) -> None:
        if self._first:
            self._first = False
            return
        self.engine.set_generator_parameters(self.side, self.layer_index, self.after)
        self.on_sync()

    def undo(self) -> None:
        self.engine.set_generator_parameters(self.side, self.layer_index, self.before)
        self.on_sync()


class RestoreProjectStateCommand(QUndoCommand):
    def __init__(
        self,
        engine: RenderEngine,
        before: dict,
        after: dict,
        text: str,
        on_sync: Callable[[], None],
    ) -> None:
        super().__init__(text)
        self.engine = engine
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.on_sync = on_sync
        self._first = True

    def redo(self) -> None:
        if self._first:
            self._first = False
            return
        self.engine.restore_state(self.after)
        self.on_sync()

    def undo(self) -> None:
        self.engine.restore_state(self.before)
        self.on_sync()
