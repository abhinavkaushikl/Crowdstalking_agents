"""
Loads config/settings.yaml once and exposes it through a dotted-path get().

Deliberately separate from secrets: API keys/credentials live in .env and are
read via os.environ (python-dotenv), never here. This file is only for
non-secret, human-tunable numbers (timeouts, limits, model names) so they
don't end up as magic numbers scattered across the codebase.
"""
import os
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_PATH = os.path.join(os.path.dirname(_HERE), "config", "settings.yaml")

_settings = None


def _load():
    global _settings
    if _settings is None:
        with open(_SETTINGS_PATH) as f:
            _settings = yaml.safe_load(f) or {}
    return _settings


def get(dotted_path, default=None):
    """e.g. get('groq.default_model') looks up settings['groq']['default_model']."""
    node = _load()
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
