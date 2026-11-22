"""Discovers built-in and user plugin effect classes at application boot."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import pkgutil
from pathlib import Path

from glediator.effects.base import Effect

USER_EFFECTS_DIR = Path.home() / ".glediator" / "effects"

_EFFECT_CLASSES: dict[str, type[Effect]] = {}
_PLUGIN_WARNINGS: list[str] = []
_LOADED = False


def _collect_from_module(module, target: dict[str, type[Effect]], *, is_plugin: bool, builtin_names: set[str]) -> None:
    for _, candidate in inspect.getmembers(module, inspect.isclass):
        if candidate is Effect or not issubclass(candidate, Effect) or inspect.isabstract(candidate):
            continue
        name = getattr(candidate, "name", "")
        description = getattr(candidate, "description", "")
        if not isinstance(name, str) or not name.strip():
            continue
        if is_plugin and name in builtin_names:
            _PLUGIN_WARNINGS.append(f"Plugin effect {name!r} clashes with built-in effect and was skipped.")
            continue
        if name in target and target[name] is not candidate:
            if is_plugin:
                _PLUGIN_WARNINGS.append(f"Duplicate plugin effect {name!r} skipped.")
                continue
            raise ValueError(f"Duplicate effect name: {name}")
        if not isinstance(description, str):
            if is_plugin:
                _PLUGIN_WARNINGS.append(f"Plugin effect {name!r} has invalid description; skipped.")
                continue
            raise TypeError(f"Effect {name!r} must provide a string description")
        target[name] = candidate


def _plugin_dirs() -> list[Path]:
    dirs = [USER_EFFECTS_DIR]
    extra = os.environ.get("GLEDIATOR_EFFECTS_PATH", "")
    for raw in extra.split(os.pathsep):
        raw = raw.strip()
        if raw:
            dirs.append(Path(raw))
    return dirs


def load_effects(reload: bool = False) -> dict[str, type[Effect]]:
    """Import built-in and user plugin effect modules."""
    global _LOADED
    if _LOADED and not reload:
        return dict(_EFFECT_CLASSES)
    if reload:
        _EFFECT_CLASSES.clear()
        _PLUGIN_WARNINGS.clear()

    package = importlib.import_module("glediator.effects")
    discovered: dict[str, type[Effect]] = {}
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_") or module_info.name == "registry":
            continue
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        _collect_from_module(module, discovered, is_plugin=False, builtin_names=set())

    builtin_names = set(discovered)
    for plugin_dir in _plugin_dirs():
        if not plugin_dir.is_dir():
            continue
        for py_file in sorted(plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            mod_name = f"glediator_user_effect_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, py_file)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Cannot load spec from {py_file}")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _collect_from_module(mod, discovered, is_plugin=True, builtin_names=builtin_names)
            except Exception as exc:
                _PLUGIN_WARNINGS.append(f"Failed to load effect plugin {py_file.name}: {exc}")

    for name in sorted(discovered, key=str.casefold):
        _EFFECT_CLASSES[name] = discovered[name]
    _LOADED = True
    return dict(_EFFECT_CLASSES)


def plugin_warnings() -> list[str]:
    load_effects()
    return list(_PLUGIN_WARNINGS)


def effect_names() -> list[str]:
    return list(load_effects())


def picker_effect_names() -> list[str]:
    return [name for name in load_effects() if name != "Black"]


def effect_descriptions() -> dict[str, str]:
    return {name: cls.description for name, cls in load_effects().items()}


def effect_categories() -> dict[str, str]:
    return {name: getattr(cls, "category", "General") for name, cls in load_effects().items()}


def effect_settings(name: str) -> dict:
    effect_class = load_effects().get(name)
    if effect_class is None:
        return {}
    settings = getattr(effect_class, "settings", {})
    if isinstance(settings, dict):
        return settings
    return {}


def default_effect_parameters(name: str) -> dict:
    from glediator.generators.settings import default_parameters

    return default_parameters(name, effect_settings(name))


def sanitize_effect_parameters(name: str, values: dict | None) -> dict:
    from glediator.generators.settings import sanitize_parameters

    schema = effect_settings(name)
    if schema:
        return sanitize_parameters(name, values, schema)
    return dict(values) if isinstance(values, dict) else {}


def create_effect(name: str) -> Effect:
    effect_class = load_effects().get(name)
    if effect_class is None:
        raise ValueError(f"Unknown effect: {name}")
    instance = effect_class()
    instance.setup()
    return instance
