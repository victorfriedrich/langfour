"""
Model identifiers, in one place.

Chat traffic goes through OpenRouter, so these are OpenRouter slugs
("vendor/model"), not bare OpenAI names. Two tiers, matching how the code
already used gpt-4.1 / gpt-4.1-mini:

    MODEL_SMART   the capable one, for judgement calls and structured output
    MODEL_FAST    the cheap one, for high-volume mechanical work

Both are overridable from the environment, so trying a different model is a
config change rather than a code change:

    LLM_MODEL_SMART=deepseek/deepseek-v3.2  uvicorn app:app
"""

import os

MODEL_SMART = os.getenv("LLM_MODEL_SMART", "deepseek/deepseek-v4-pro")
MODEL_FAST = os.getenv("LLM_MODEL_FAST", "deepseek/deepseek-v4-flash")

# Audio transcription is NOT OpenRouter — it proxies chat completions only
# and has no /audio/transcriptions endpoint. Whisper runs on DeepInfra,
# which does expose an OpenAI-compatible transcriptions endpoint.
#
# turbo is ~8x faster than whisper-large-v3 at close to the same accuracy;
# swap to "openai/whisper-large-v3" if transcript quality matters more than
# throughput.
MODEL_TRANSCRIBE = os.getenv("LLM_MODEL_TRANSCRIBE", "openai/whisper-large-v3-turbo")

__all__ = ["MODEL_SMART", "MODEL_FAST", "MODEL_TRANSCRIBE"]
