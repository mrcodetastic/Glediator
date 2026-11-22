"""Discovers effect classes from modules in this package at application boot."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from glediator.effects.base import Effect

_EFFECT_CLASSES: dict[str, type[Effect]] = {}
_LOADED = False


def load_effects(reload: bool = False) -> dict[str, type[Effect]]:
    """Import effect modules and index their concrete Effect subclasses."""
    global _LOADED
    if _LOADED and not reload:
        return dict(_EFFECT_CLASSES)
    if reload:
        _EFFECT_CLASSES.clear()
    package = importlib.import_module("glediator.effects")
    discovered: dict[str, type[Effect]] = {}
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_") or module_info.name == "registry":
            continue
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate is Effect or not issubclass(candidate, Effect) or inspect.isabstract(candidate):
                continue
            name = getattr(candidate, "name", "")
            description = getattr(candidate, "description", "")
            if not isinstance(name, str) or not name.strip():
                continue
            if name in discovered and discovered[name] is not candidate:
                raise ValueError(f"Duplicate effect name: {name}")
            if not isinstance(description, str):
                raise TypeError(f"Effect {name!r} must provide a string description")
            discovered[name] = candidate
    for name in sorted(discovered, key=str.casefold):
        _EFFECT_CLASSES[name] = discovered[name]
    _LOADED = True
    return dict(_EFFECT_CLASSES)


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
