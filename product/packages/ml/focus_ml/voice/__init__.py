"""Audio-only voice pipeline (proof of concept).

One small interface per responsibility: preprocess, diarizer (VAD), embedder,
enroller, matcher, extractor. Nothing here looks at video or text: the pipeline
takes audio plus an enrollment. See docs/VOICE_PIPELINE.md.
"""
