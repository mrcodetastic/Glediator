"""Compatibility helpers for applying effect-owned parameter schemas."""

from __future__ import annotations

from glediator.generators.palettes import palette_names


def _settings_for(effect_name: str, settings: dict | None) -> dict:
    if settings is not None:
        return settings
    from glediator.effects import effect_settings

    return effect_settings(effect_name)


def default_parameters(effect_name: str, settings: dict | None = None) -> dict:
    schema = _settings_for(effect_name, settings)
    return {name: spec[1] for name, spec in schema.items()}


def sanitize_parameters(effect_name: str, values: dict | None, settings: dict | None = None) -> dict:
    schema = _settings_for(effect_name, settings)
    result = default_parameters(effect_name, schema)
    if not isinstance(values, dict):
        return result
    for name, spec in schema.items():
        if name not in values:
            continue
        kind, default, low, high, _step = spec
        try:
            if kind in ("str", "font", "color"):
                result[name] = str(values[name])[:120]
            elif kind == "file":
                result[name] = str(values[name])[:512]
            elif kind == "bool":
                result[name] = bool(values[name])
            elif kind == "choice":
                if name == "palette":
                    allowed = set(palette_names())
                    if isinstance(low, (tuple, list)):
                        allowed.update(low)
                    result[name] = values[name] if values[name] in allowed else default
                else:
                    choices = low() if callable(low) else low
                    result[name] = values[name] if values[name] in choices else default
            elif kind == "int":
                result[name] = max(low, min(high, int(values[name])))
            else:
                result[name] = max(low, min(high, float(values[name])))
        except (TypeError, ValueError):
            result[name] = default
    return result
