"""focus_eval: offline error-metric tool for FOCUS isolation runs.

It scores outputs that already exist (isolated audio and hypothesis transcripts)
against a human-curated dataset. It never runs the engine, a GPU or an ASR model.
"""
SCHEMA_VERSION = 1
