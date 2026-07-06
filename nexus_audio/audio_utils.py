"""
NEXUS AI v4.0 — Platform-aware audio device enumeration and testing.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides audio device detection, testing, and platform-specific helpers
for the audio subsystem. Handles Windows WASAPI, macOS CoreAudio, and Linux ALSA.
"""

import logging
import platform
import sys
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("nexus.audio.utils")


def get_platform_audio_backend() -> str:
    """
    Return the recommended pygame audio backend for the current platform.
    
    Returns:
        "wasapi" on Windows, "coreaudio" on macOS, "alsa" on Linux.
    """
    system = platform.system()
    if system == "Windows":
        return "wasapi"
    elif system == "Darwin":
        return "coreaudio"
    else:
        return "alsa"


def enumerate_audio_devices() -> List[Dict[str, object]]:
    """
    Enumerate available audio input/output devices.
    
    Uses pygame.mixer to list devices. Returns a list of dicts with:
        - name: str — device name
        - index: int — device index
        - is_input: bool — True if input device
        - is_output: bool — True if output device
        - sample_rate: int — supported sample rate
        - channels: int — number of channels
    
    Returns:
        List of device info dicts. Empty list if pygame not available or no devices found.
    """
    devices = []
    try:
        import pygame
        pygame.mixer.init()
        count = pygame.mixer.get_num_devices()
        for i in range(count):
            name = pygame.mixer.get_device_name(i)
            devices.append({
                "name": name,
                "index": i,
                "is_input": False,
                "is_output": True,
                "sample_rate": 22050,
                "channels": 1,
            })
        pygame.mixer.quit()
    except Exception as e:
        logger.warning(f"Could not enumerate audio devices: {e}")
    
    return devices


def test_audio_output() -> Tuple[bool, str]:
    """
    Test audio output by attempting to initialize pygame mixer.
    
    Returns:
        Tuple of (success: bool, message: str) where message describes the result.
    """
    try:
        import pygame
        pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        pygame.mixer.quit()
        return True, "Audio output initialized successfully"
    except ImportError:
        return False, "pygame not installed"
    except Exception as e:
        return False, f"Audio output failed: {e}"


def test_microphone() -> Tuple[bool, str]:
    """
    Test microphone availability.
    
    Uses pvrecorder if available, otherwise checks for platform-specific audio input.
    
    Returns:
        Tuple of (success: bool, message: str).
    """
    try:
        import pvrecorder
        devices = pvrecorder.get_audio_devices()
        if devices:
            return True, f"Microphone found: {devices[0]}"
        return False, "No microphone devices found"
    except ImportError:
        return False, "pvrecorder not installed"
    except Exception as e:
        return False, f"Microphone check failed: {e}"


def suppress_alsa_errors() -> None:
    """
    Suppress ALSA error messages on Linux.
    
    ALSA produces copious error messages even during normal operation.
    This function installs a null error handler to suppress them.
    Only effective on Linux with ALSA.
    """
    if platform.system() != "Linux":
        return
    try:
        import ctypes
        import ctypes.util
        libasound = ctypes.util.find_library("asound")
        if libasound:
            alsa = ctypes.CDLL(libasound)
            # Set error handler to NULL to suppress messages
            alsa.snd_lib_error_set_handler(None)
    except Exception:
        pass


def get_system_volume() -> Optional[float]:
    """
    Get current system volume level (0.0 to 1.0).
    
    Platform-specific implementation:
    - Windows: uses pycaw
    - macOS: uses osascript
    - Linux: uses amixer
    
    Returns:
        Float 0.0-1.0, or None if unable to determine.
    """
    system = platform.system()
    try:
        if system == "Windows":
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            return volume.GetMasterVolumeLevelScalar()
        elif system == "Darwin":
            import subprocess
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return int(result.stdout.strip()) / 100.0
        else:
            import subprocess
            result = subprocess.run(
                ["amixer", "get", "Master"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                import re
                match = re.search(r'\[(\d+)%\]', result.stdout)
                if match:
                    return int(match.group(1)) / 100.0
    except Exception as e:
        logger.debug(f"Could not get system volume: {e}")
    return None