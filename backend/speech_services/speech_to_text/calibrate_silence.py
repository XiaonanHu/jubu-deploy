#!/usr/bin/env python
"""
Utility script for calibrating silence detection thresholds.
This helps find the optimal silence threshold for your specific microphone and environment.
"""

import argparse
import sys
import time
from typing import Optional

import numpy as np
import sounddevice as sd


def monitor_audio_levels(duration: int = 20, update_interval: float = 0.1):
    """
    Monitor audio levels for the specified duration and show a visual indicator.

    Args:
        duration: Monitoring duration in seconds
        update_interval: Update interval in seconds
    """
    # Audio parameters
    sample_rate = 16000
    channels = 1

    # Chunk size for processing
    chunk_duration = update_interval  # seconds per chunk
    chunk_size = int(sample_rate * chunk_duration)

    # Initialize variables
    audio_data = []
    max_volume = 0.001
    min_volume = 1.0

    print("\n=== Audio Level Calibration Tool ===")
    print(
        "This will help you determine the right silence threshold for your environment."
    )
    print(f"Recording for {duration} seconds to analyze audio levels...")
    print("Please perform these actions during the recording:")
    print("1. Be completely silent for a few seconds (background noise level)")
    print("2. Speak normally as you would during a conversation")
    print("3. Be silent again for a few seconds\n")
    print("Press Enter to start recording...")
    input()

    print("Recording... Monitoring audio levels")
    print("Volume: |----------| 0.0000")

    # Start time
    start_time = time.time()

    # Record and process audio
    with sd.InputStream(
        samplerate=sample_rate, channels=channels, blocksize=chunk_size
    ) as stream:
        while time.time() - start_time < duration:
            # Read audio chunk
            data, _ = stream.read(chunk_size)

            # Calculate volume
            volume_norm = np.linalg.norm(data) / np.sqrt(len(data))
            audio_data.append(volume_norm)

            # Update min/max
            max_volume = max(max_volume, volume_norm)
            min_volume = min(min_volume, volume_norm)

            # Create visual indicator
            bar_length = 10
            filled_length = int(bar_length * volume_norm / max(0.2, max_volume))
            filled_length = min(
                bar_length, filled_length
            )  # Ensure it doesn't exceed bar length
            bar = "|" + "#" * filled_length + "-" * (bar_length - filled_length) + "|"

            # Clear the previous line and print the new one
            sys.stdout.write("\r" + " " * 80)  # Clear line
            sys.stdout.write(f"\rVolume: {bar} {volume_norm:.4f}")
            sys.stdout.flush()

            # Sleep for remaining time to maintain update interval
            elapsed = time.time() - start_time
            remaining = update_interval - (elapsed % update_interval)
            if remaining < update_interval:
                time.sleep(remaining)

    # Clear the last line and move to next line
    sys.stdout.write("\r" + " " * 80)
    sys.stdout.write("\r")
    sys.stdout.flush()

    # Calculate statistics
    audio_data = np.array(audio_data)
    mean_volume = np.mean(audio_data)
    median_volume = np.median(audio_data)
    percentile_25 = np.percentile(audio_data, 25)
    percentile_75 = np.percentile(audio_data, 75)

    # Print results
    print("\n=== Results ===")
    print(f"Minimum volume detected: {min_volume:.6f}")
    print(f"Maximum volume detected: {max_volume:.6f}")
    print(f"Mean volume: {mean_volume:.6f}")
    print(f"Median volume: {median_volume:.6f}")
    print(f"25th percentile: {percentile_25:.6f}")
    print(f"75th percentile: {percentile_75:.6f}")

    # Recommend thresholds
    print("\n=== Recommended Silence Thresholds ===")
    print(f"Conservative (less likely to cut off): {min_volume * 1.5:.6f}")
    print(f"Moderate (balanced): {percentile_25 * 1.2:.6f}")
    print(f"Aggressive (may cut off sooner): {median_volume * 0.8:.6f}")

    print("\n=== How to use ===")
    print("To use one of these thresholds, run the KidsChat CLI with:")
    print(
        f"python -m jubu_chat.chat_cli --use-stt --continuous-stt --silence-threshold VALUE"
    )
    print("Replace VALUE with one of the recommended thresholds above.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calibrate silence detection thresholds"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=20,
        help="Recording duration in seconds (default: 20)",
    )
    args = parser.parse_args()

    try:
        monitor_audio_levels(duration=args.duration)
    except KeyboardInterrupt:
        print("\nCalibration interrupted.")
    except Exception as e:
        print(f"\nError during calibration: {e}")
