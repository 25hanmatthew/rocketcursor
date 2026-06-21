"""memory.llm: PDF/document to validated config, plus a measured context compressor.

The config generator pulls in the root solver (CoolProp) and the Anthropic SDK,
so it is imported lazily. The light submodules (compress, prefilter, tokens) can
be imported directly without that stack.
"""

__all__ = ["generate_config_from_pdf"]


def __getattr__(name):
    if name == "generate_config_from_pdf":
        from memory.llm.pdf_config_generator import generate_config_from_pdf

        return generate_config_from_pdf
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
