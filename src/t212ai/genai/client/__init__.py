"""GenAI client package.

Public imports remain compatible with the former ``t212ai.genai.client`` module.
"""

from .core import GenAIClient
from .diagnostics import _llm_prompt_diagnostics
from .errors import _provider_error_code, _provider_error_details
from .settings import GenAISettings, genai_settings_from_app_settings, get_genai_settings

__all__ = [
    "GenAIClient",
    "GenAISettings",
    "genai_settings_from_app_settings",
    "get_genai_settings",
    "_llm_prompt_diagnostics",
    "_provider_error_code",
    "_provider_error_details",
]
