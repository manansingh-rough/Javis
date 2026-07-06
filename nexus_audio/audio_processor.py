"""
NEXUS AI v4.0 — Audio processing: silence detection, RMS calculation, normalization.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides audio preprocessing utilities for voice transcription pipeline.
Optimized for CPU-only operation on low-power hardware.
"""

import logging
import math
import struct
from typing import Optional, Tuple, List

logger = logging.getLogger("nexus.audio.processor")


SILENCE_THRESHOLD: float = 0.02
"""RMS threshold below which audio is considered silence (0.0-1.0 scale)."""

MIN_AUDIO_LENGTH_SECONDS: float = 0.3
"""Minimum audio length to process (shorter is likely noise)."""

MAX_AUDIO_LENGTH_SECONDS: float = 30.0
"""Maximum audio length to process (longer gets truncated)."""


def calculate_rms(audio_data: bytes, sample_width: int = 2) -> float:
    """
    Calculate RMS (Root Mean Square) of raw audio data.
    
    Args:
        audio_data: Raw PCM audio bytes.
        sample_width: Bytes per sample (2 for 16-bit, 1 for 8-bit).
    
    Returns:
        RMS value normalized to 0.0-1.0 range.
        0.0 means complete silence.
        1.0 means maximum amplitude.
    """
    if not audio_data:
        return 0.0
    
    if sample_width == 2:
        fmt = "<" + "h" * (len(audio_data) // 2)
        try:
            samples = struct.unpack(fmt, audio_data[:len(audio_data) - len(audio_data) % 2])
        except struct.error:
            return 0.0
    elif sample_width == 1:
        samples = [b - 128 for b in audio_data]
    else:
        return 0.0
    
    if not samples:
        return 0.0
    
    sum_squares = sum(s * s for s in samples)
    rms = math.sqrt(sum_squares / len(samples))
    
    # Normalize to 0.0-1.0 based on sample width
    max_amplitude = (2 ** (sample_width * 8 - 1)) - 1
    return min(rms / max_amplitude, 1.0)


def is_silence(audio_data: bytes, threshold: float = SILENCE_THRESHOLD) -> bool:
    """
    Detect if audio data is silence below the given threshold.
    
    Args:
        audio_data: Raw PCM audio bytes.
        threshold: RMS threshold (0.0-1.0). Default: SILENCE_THRESHOLD.
    
    Returns:
        True if RMS is below threshold.
    """
    if not audio_data or len(audio_data) < 32:
        return True
    rms = calculate_rms(audio_data)
    return rms < threshold


def detect_speech_segments(
    audio_data: bytes,
    sample_rate: int = 16000,
    sample_width: int = 2,
    silence_threshold: float = SILENCE_THRESHOLD,
    min_speech_ms: int = 200,
    min_silence_ms: int = 300,
) -> List[Tuple[int, int]]:
    """
    Detect speech segments in audio by finding regions above silence threshold.
    
    Args:
        audio_data: Raw PCM audio bytes.
        sample_rate: Audio sample rate in Hz.
        sample_width: Bytes per sample.
        silence_threshold: RMS silence threshold.
        min_speech_ms: Minimum speech duration to keep (shorter is noise).
        min_silence_ms: Minimum silence between speech segments.
    
    Returns:
        List of (start_ms, end_ms) tuples for each detected speech segment.
    """
    if not audio_data:
        return []
    
    frame_size = int(sample_rate * 0.05)  # 50ms frames
    frame_bytes = frame_size * sample_width
    min_speech_frames = min_speech_ms // 50
    min_silence_frames = min_silence_ms // 50
    
    segments = []
    in_speech = False
    speech_start = 0
    silence_frames = 0
    speech_frames = 0
    
    for i in range(0, len(audio_data), frame_bytes):
        frame = audio_data[i:i + frame_bytes]
        frame_rms = calculate_rms(frame, sample_width)
        frame_index = i // frame_bytes
        
        if frame_rms > silence_threshold:
            if not in_speech:
                speech_start = frame_index
                in_speech = True
                speech_frames = 1
            else:
                speech_frames += 1
            silence_frames = 0
        else:
            if in_speech:
                silence_frames += 1
                if silence_frames >= min_silence_frames:
                    if speech_frames >= min_speech_frames:
                        start_ms = int(speech_start * 50)
                        end_ms = int((frame_index - min_silence_frames) * 50)
                        segments.append((start_ms, end_ms))
                    in_speech = False
                    speech_frames = 0
                    silence_frames = 0
    
    # Handle trailing speech
    if in_speech and speech_frames >= min_speech_frames:
        start_ms = int(speech_start * 50)
        end_ms = int(len(audio_data) // (sample_width * sample_rate) * 1000)
        segments.append((start_ms, end_ms))
    
    return segments


def normalize_audio(audio_data: bytes, target_rms: float = 0.3) -> bytes:
    """
    Normalize audio volume to target RMS level.
    
    Args:
        audio_data: Raw PCM 16-bit audio bytes.
        target_rms: Target RMS level (0.0-1.0).
    
    Returns:
        Normalized PCM audio bytes.
    """
    if not audio_data:
        return audio_data
    
    current_rms = calculate_rms(audio_data, sample_width=2)
    if current_rms < 0.001:
        return audio_data  # Too quiet to normalize
    
    gain = target_rms / current_rms
    # Clamp gain to prevent excessive amplification
    gain = max(0.1, min(gain, 5.0))
    
    fmt = "<" + "h" * (len(audio_data) // 2)
    valid_bytes = audio_data[:len(audio_data) - len(audio_data) % 2]
    
    try:
        samples = list(struct.unpack(fmt, valid_bytes))
    except struct.error:
        return audio_data
    
    normalized = []
    for sample in samples:
        new_sample = int(sample * gain)
        new_sample = max(-32768, min(32767, new_sample))
        normalized.append(new_sample)
    
    return struct.pack(fmt, *normalized)


def trim_silence(audio_data: bytes, threshold: float = SILENCE_THRESHOLD) -> bytes:
    """
    Trim leading and trailing silence from audio.
    
    Args:
        audio_data: Raw PCM audio bytes.
        threshold: RMS silence threshold.
    
    Returns:
        Audio bytes with silence trimmed from both ends.
    """
    if not audio_data:
        return audio_data
    
    frame_size = 320  # 20ms at 16kHz 16-bit
    total_frames = len(audio_data) // frame_size
    
    if total_frames < 2:
        return audio_data
    
    # Find first non-silent frame
    start_frame = 0
    for i in range(total_frames):
        frame = audio_data[i * frame_size:(i + 1) * frame_size]
        if not is_silence(frame, threshold):
            start_frame = max(0, i - 1)  # Include one frame before for context
            break
    
    # Find last non-silent frame
    end_frame = total_frames
    for i in range(total_frames - 1, -1, -1):
        frame = audio_data[i * frame_size:(i + 1) * frame_size]
        if not is_silence(frame, threshold):
            end_frame = min(total_frames, i + 2)  # Include one frame after
            break
    
    if start_frame >= end_frame:
        return b""
    
    trimmed = audio_data[start_frame * frame_size:end_frame * frame_size]
    return trimmed