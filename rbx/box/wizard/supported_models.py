"""Registry of supported LLM models and their settings for the wizard service."""

from agents.model_settings import ModelSettings

# Map of supported model name to its ModelSettings
SUPPORTED_MODELS: dict[str, ModelSettings] = {
    # OpenAI family
    'gpt-4o': ModelSettings(temperature=0.1),
    'gpt-4.1': ModelSettings(temperature=0.1),
    # Default ROBX choices
    'gpt-5': ModelSettings(),
    'gpt-5-mini': ModelSettings(),
}


def get_model_settings(model_name: str) -> ModelSettings:
    """Return settings for a supported model or raise a ValueError.

    Args:
        model_name: Name of the model to look up.

    Raises:
        ValueError: If the model is not supported.
    """

    try:
        return SUPPORTED_MODELS[model_name]
    except KeyError as exc:
        supported = ', '.join(sorted(SUPPORTED_MODELS.keys()))
        raise ValueError(
            f"Unsupported model '{model_name}'. Supported models: {supported}"
        ) from exc


def is_supported_model(model_name: str) -> bool:
    """Check whether a model is in the supported registry."""

    return model_name in SUPPORTED_MODELS


# Default model that routes will use unless specified otherwise.
DEFAULT_MODEL_NAME = 'gpt-4.1'
