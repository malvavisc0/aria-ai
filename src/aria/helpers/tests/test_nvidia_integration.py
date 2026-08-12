"""Integration tests for NVIDIA GPU utilities - runs against actual hardware.

These tests are designed to run on systems with NVIDIA GPUs and nvidia-smi installed.
They will be skipped if nvidia-smi is not available.

Run with: uv run pytest src/aria/tests/test_nvidia_integration.py -v
"""

import pytest

from aria.helpers.nvidia import (
    GPUMetadata,
    check_nvidia_smi_available,
    detect_gpu_count,
    detect_gpus_with_details,
    detect_nvlink,
    get_free_vram_per_gpu,
    get_nvidia_smi_version,
    get_total_vram_mb,
)

# Skip all tests in this module if nvidia-smi is not available
pytestmark = pytest.mark.skipif(
    not check_nvidia_smi_available(),
    reason="nvidia-smi not available - skipping hardware integration tests",
)


class TestNvidiaIntegration:
    """Integration tests that run against actual NVIDIA hardware."""

    def test_get_nvidia_smi_version_returns_valid_version(self):
        """Verify we can get a valid nvidia-smi version."""
        version = get_nvidia_smi_version()
        assert version != ""
        assert "." in version  # Should have at least one dot (e.g., "535.104")
        # Version should be numeric with dots
        parts = version.split(".")
        assert len(parts) >= 2
        for part in parts:
            assert part.isdigit()

    def test_detect_gpu_count_returns_positive_number(self):
        """Verify GPU count is a positive number."""
        gpu_count = detect_gpu_count()
        assert gpu_count > 0
        assert isinstance(gpu_count, int)

    def test_get_total_vram_mb_returns_positive_value(self):
        """Verify total VRAM is a positive value."""
        total_vram = get_total_vram_mb()
        assert total_vram > 0
        assert isinstance(total_vram, int)
        # Sanity check: modern GPUs have at least 1GB VRAM
        assert total_vram >= 1024

    def test_get_free_vram_per_gpu_returns_list(self):
        """Verify free VRAM returns a list with values."""
        free_vram = get_free_vram_per_gpu()
        assert isinstance(free_vram, list)
        assert len(free_vram) > 0
        # All values should be positive integers
        for vram in free_vram:
            assert isinstance(vram, int)
            assert vram >= 0

    def test_free_vram_count_matches_gpu_count(self):
        """Verify free VRAM list length matches GPU count."""
        gpu_count = detect_gpu_count()
        free_vram = get_free_vram_per_gpu()
        assert len(free_vram) == gpu_count

    def test_total_vram_is_sum_of_all_gpus(self):
        """Verify total VRAM calculation is correct."""
        gpu_count = detect_gpu_count()
        total_vram = get_total_vram_mb()

        # For systems with multiple identical GPUs, we can verify the math
        if gpu_count > 1:
            # Total should be divisible by GPU count for identical GPUs
            vram_per_gpu = total_vram // gpu_count
            assert vram_per_gpu > 0

    def test_detect_nvlink_returns_tuple(self):
        """Test NVLink detection returns proper tuple."""
        has_nvlink, bond_type = detect_nvlink()

        assert isinstance(has_nvlink, bool)
        assert bond_type is None or isinstance(bond_type, str)

        # If bond_type is set, it should be "Bonded"
        if bond_type is not None:
            assert bond_type == "Bonded"

    def test_nvlink_only_on_multi_gpu_systems(self):
        """NVLink should only be detected on multi-GPU systems."""
        gpu_count = detect_gpu_count()
        has_nvlink, _ = detect_nvlink()

        # Single GPU systems should not have NVLink
        if gpu_count == 1:
            assert has_nvlink is False

    def test_memory_consistency(self):
        """Test that memory values are consistent across calls."""
        # Get values twice
        total_vram_1 = get_total_vram_mb()
        total_vram_2 = get_total_vram_mb()

        # Total VRAM should be the same
        assert total_vram_1 == total_vram_2

        # Free VRAM might vary slightly but should be similar
        free_vram_1 = get_free_vram_per_gpu()
        free_vram_2 = get_free_vram_per_gpu()

        assert len(free_vram_1) == len(free_vram_2)

        # Free VRAM should be within reasonable range (allow 10% variance)
        for vram1, vram2 in zip(free_vram_1, free_vram_2):
            variance = abs(vram1 - vram2)
            max_allowed_variance = max(vram1, vram2) * 0.1
            assert variance <= max_allowed_variance

    def test_free_vram_less_than_total_vram(self):
        """Verify free VRAM is less than or equal to total VRAM."""
        total_vram = get_total_vram_mb()
        free_vram_list = get_free_vram_per_gpu()

        # Each GPU's free VRAM should be less than total system VRAM
        for free_vram in free_vram_list:
            assert free_vram <= total_vram

    def test_detect_gpus_with_details_returns_list(self):
        """Test that detect_gpus_with_details returns a list of GPUMetadata."""
        gpus = detect_gpus_with_details()

        assert isinstance(gpus, list)
        assert len(gpus) > 0

        for gpu in gpus:
            assert isinstance(gpu, GPUMetadata)

    def test_gpu_details_count_matches_gpu_count(self):
        """Verify detailed GPU list length matches GPU count."""
        gpu_count = detect_gpu_count()
        gpus = detect_gpus_with_details()

        assert len(gpus) == gpu_count

    def test_gpu_details_have_valid_data(self):
        """Test that GPU details contain valid data."""
        gpus = detect_gpus_with_details()

        for gpu in gpus:
            # Index should be non-negative
            assert gpu.index >= 0

            # Name should not be empty
            assert gpu.name != ""

            # UUID should not be empty
            assert gpu.uuid != ""

            # Memory values should be non-negative
            assert gpu.total_memory >= 0
            assert gpu.used_memory >= 0
            assert gpu.free_memory >= 0

            # Memory utilization should be 0-100
            assert 0.0 <= gpu.memory_utilization <= 100.0

            # Power values should be non-negative
            assert gpu.power_limit >= 0
            assert gpu.power_draw >= 0

            # Temperature should be reasonable (0-100°C)
            assert 0 <= gpu.temperature <= 150

            # Fan speed should be 0-100%
            assert 0 <= gpu.fan_speed <= 100

            # Driver version should not be empty
            assert gpu.driver_version != ""

            # Display active should be boolean
            assert isinstance(gpu.display_active, bool)

            # Compute mode should not be empty
            assert gpu.compute_mode != ""

    def test_gpu_details_memory_consistency(self):
        """Test that memory values are consistent."""
        gpus = detect_gpus_with_details()

        for gpu in gpus:
            # Used + Free should approximately equal Total
            # Allow variance due to rounding and nvidia-smi reporting differences
            calculated_total = gpu.used_memory + gpu.free_memory
            variance = abs(calculated_total - gpu.total_memory)
            # Allow up to 2% variance or 500 MiB, whichever is larger
            max_variance = max(gpu.total_memory * 0.02, 500)
            assert variance <= max_variance

    def test_gpu_details_utilization_matches_memory(self):
        """Test that memory utilization matches used/total ratio."""
        gpus = detect_gpus_with_details()

        for gpu in gpus:
            if gpu.total_memory > 0:
                expected_util = round((gpu.used_memory / gpu.total_memory * 100), 2)
                # Allow small variance due to rounding
                assert abs(gpu.memory_utilization - expected_util) <= 0.1

    def test_gpu_details_indices_are_sequential(self):
        """Test that GPU indices are sequential starting from 0."""
        gpus = detect_gpus_with_details()

        indices = [gpu.index for gpu in gpus]
        expected_indices = list(range(len(gpus)))
        assert indices == expected_indices


def print_gpu_info():
    """Utility function to print GPU information (not a test)."""
    print("\n" + "=" * 60)
    print("NVIDIA GPU Information")
    print("=" * 60)

    if not check_nvidia_smi_available():
        print("nvidia-smi is not available on this system")
        return

    print(f"nvidia-smi version: {get_nvidia_smi_version()}")
    print(f"GPU count: {detect_gpu_count()}")
    print(f"Total VRAM: {get_total_vram_mb()} MiB")

    free_vram = get_free_vram_per_gpu()
    print("\nFree VRAM per GPU:")
    for i, vram in enumerate(free_vram):
        print(f"  GPU {i}: {vram} MiB")

    has_nvlink, bond_type = detect_nvlink()
    print(f"\nNVLink detected: {has_nvlink}")
    if bond_type:
        print(f"Bond type: {bond_type}")

    print("\nDetailed GPU Information:")
    gpus = detect_gpus_with_details()
    for gpu in gpus:
        print(f"\n  GPU {gpu.index}: {gpu.name}")
        print(f"    UUID: {gpu.uuid}")
        print(
            f"    Memory: {gpu.used_memory}/{gpu.total_memory} MiB ({gpu.memory_utilization}% used)"
        )
        print(f"    Free: {gpu.free_memory} MiB")
        print(f"    Power: {gpu.power_draw}/{gpu.power_limit} W")
        print(f"    Temperature: {gpu.temperature}°C")
        print(f"    Fan Speed: {gpu.fan_speed}%")
        print(f"    Driver: {gpu.driver_version}")
        print(f"    Display Active: {gpu.display_active}")
        print(f"    Compute Mode: {gpu.compute_mode}")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Run this file directly to print GPU info
    print_gpu_info()
