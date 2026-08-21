"""Comprehensive tests for NVIDIA GPU detection and monitoring utilities."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from aria.helpers.nvidia import (
    GPUMetadata,
    calculate_gpu_memory_utilization,
    check_nvidia_smi_available,
    detect_gpu_count,
    detect_gpus_with_details,
    detect_nvlink,
    get_cuda_version,
    get_free_vram_per_gpu,
    get_nvidia_smi_version,
    get_total_vram_mb,
)

# ============================================================================
# Mock Data Constants
# ============================================================================

MOCK_GPU_LIST_SINGLE = "GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-xxx)"

MOCK_GPU_LIST_DUAL = """GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-xxx)
GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-yyy)"""

MOCK_GPU_LIST_QUAD = """GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-aaa)
GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-bbb)
GPU 2: NVIDIA GeForce RTX 3090 (UUID: GPU-ccc)
GPU 3: NVIDIA GeForce RTX 3090 (UUID: GPU-ddd)"""

MOCK_GPU_LIST_WITH_EMPTY_LINES = """GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-xxx)

GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-yyy)
"""

MOCK_VRAM_TOTAL_SINGLE = "24576"

MOCK_VRAM_TOTAL_DUAL = """24576
24576"""

MOCK_VRAM_TOTAL_QUAD = """24576
24576
24576
24576"""

MOCK_VRAM_FREE_DUAL = """20480
22528"""

MOCK_NVLINK_TOPOLOGY_WITH_NVLINK = """    GPU0    GPU1
GPU0     X      NV4
GPU1    NV4      X

Legend:

  X    = Self
  SYS  = Connection traversing PCIe as well as the SMP interconnect between NUMA nodes (e.g., QPI/UPI)
  NODE = Connection traversing PCIe as well as the interconnect between PCIe Host Bridges within a NUMA node
  PHB  = Connection traversing PCIe as well as a PCIe Host Bridge (typically the CPU)
  PXB  = Connection traversing multiple PCIe bridges (without traversing the PCIe Host Bridge)
  PIX  = Connection traversing at most a single PCIe bridge
  NV#  = Connection traversing a bonded set of # NVLinks"""

MOCK_NVLINK_TOPOLOGY_NO_NVLINK = """    GPU0    GPU1
GPU0     X      SYS
GPU1    SYS      X"""

MOCK_NVLINK_TOPOLOGY_BONDED = """    GPU0    GPU1
GPU0     X      NV2
GPU1    NV2      X

Bonded"""

MOCK_VERSION_OUTPUT = (
    """NVIDIA-SMI 535.104.05    Driver Version: 535.104.05    CUDA Version: 12.2"""
)

MOCK_VERSION_OUTPUT_ALT = """NVIDIA-SMI 525.85.12
Driver Version: 525.85.12
CUDA Version: 12.0"""

MOCK_VERSION_OUTPUT_WITH_COLON = """NVIDIA-SMI version  : 590.48.01
NVML version        : 590.48
DRIVER version      : 590.48.01
CUDA Version        : 13.1"""

MOCK_VERSION_OUTPUT_DEPRECATED = """NVIDIA-SMI version  : 610.57.04
NVML version        : 610.57
DRIVER version      : Deprecated, see "KMD version" instead
CUDA version        : Deprecated, see "CUDA UMD version" instead
KMD version         : 610.57.04
CUDA UMD version    : 13.3"""

# Mock data for detect_gpus_with_details()
MOCK_GPU_DETAILS_SINGLE = """0, NVIDIA GeForce RTX 3090, GPU-12345678-1234-1234-1234-123456789012, 24576, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, Enabled"""

MOCK_GPU_DETAILS_DUAL = """0, NVIDIA GeForce RTX 3090, GPU-12345678-1234-1234-1234-123456789012, 24576, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, Enabled
1, NVIDIA GeForce RTX 3090, GPU-87654321-4321-4321-4321-210987654321, 24576, 8192, 16384, Default, 535.104.05, 350, 250, 58, 40, Disabled"""

MOCK_GPU_DETAILS_WITH_UNITS = """0, NVIDIA GeForce RTX 3090, GPU-12345678-1234-1234-1234-123456789012, 24576, 12288, 12288, Default, 535.104.05, 350W, 280W, 65C, 45%, Enabled"""

MOCK_GPU_DETAILS_MALFORMED = """0, NVIDIA GeForce RTX 3090, GPU-12345678"""

MOCK_GPU_DETAILS_INVALID_NUMBERS = """0, NVIDIA GeForce RTX 3090, GPU-12345678-1234-1234-1234-123456789012, invalid, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, Enabled"""

MOCK_GPU_DETAILS_EMPTY_VALUES = """0, NVIDIA GeForce RTX 3090, GPU-12345678-1234-1234-1234-123456789012, , , , Default, 535.104.05, , , , , Enabled"""

MOCK_GPU_DETAILS_DISPLAY_VARIATIONS = """0, GPU1, UUID1, 24576, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, enabled
1, GPU2, UUID2, 24576, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, ENABLED
2, GPU3, UUID3, 24576, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, Disabled
3, GPU4, UUID4, 24576, 12288, 12288, Default, 535.104.05, 350, 280, 65, 45, disabled"""


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_subprocess_success():
    """Create a mock for successful subprocess.run calls."""

    def _mock_run(cmd, **kwargs):
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        return mock_result

    return _mock_run


@pytest.fixture
def mock_subprocess_failure():
    """Create a mock that raises CalledProcessError."""

    def _mock_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, "Error")

    return _mock_run


@pytest.fixture
def mock_subprocess_not_found():
    """Create a mock that raises FileNotFoundError."""

    def _mock_run(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi not found")

    return _mock_run


# ============================================================================
# Tests for detect_gpu_count()
# ============================================================================


class TestDetectGpuCount:
    """Test suite for detect_gpu_count function."""

    def test_single_gpu(self):
        """Test detection of single GPU."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_GPU_LIST_SINGLE)
            assert detect_gpu_count() == 1

    def test_dual_gpu(self):
        """Test detection of two GPUs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_GPU_LIST_DUAL)
            assert detect_gpu_count() == 2

    def test_quad_gpu(self):
        """Test detection of four GPUs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_GPU_LIST_QUAD)
            assert detect_gpu_count() == 4

    def test_no_gpus_empty_output(self):
        """Test handling of empty output (no GPUs)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")
            assert detect_gpu_count() == 0

    def test_output_with_empty_lines(self):
        """Test that empty lines are filtered correctly."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_LIST_WITH_EMPTY_LINES
            )
            # Should still detect 2 GPUs despite empty lines
            assert detect_gpu_count() == 2

    def test_nvidia_smi_not_found(self):
        """Test handling when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            assert detect_gpu_count() == 0

    def test_nvidia_smi_fails(self):
        """Test handling when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            assert detect_gpu_count() == 0

    def test_whitespace_only_lines(self):
        """Test handling of whitespace-only lines."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="   \n\t\n  \n")
            assert detect_gpu_count() == 0


# ============================================================================
# Tests for get_total_vram_mb()
# ============================================================================


class TestGetTotalVramMb:
    """Test suite for get_total_vram_mb function."""

    def test_single_gpu_vram(self):
        """Test VRAM calculation for single GPU."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VRAM_TOTAL_SINGLE)
            assert get_total_vram_mb() == 24576

    def test_dual_gpu_vram(self):
        """Test VRAM calculation for two GPUs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VRAM_TOTAL_DUAL)
            assert get_total_vram_mb() == 49152  # 24576 * 2

    def test_quad_gpu_vram(self):
        """Test VRAM calculation for four GPUs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VRAM_TOTAL_QUAD)
            assert get_total_vram_mb() == 98304  # 24576 * 4

    def test_empty_output(self):
        """Test handling of empty output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")
            assert get_total_vram_mb() == 0

    def test_nvidia_smi_not_found(self):
        """Test handling when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            assert get_total_vram_mb() == 0

    def test_nvidia_smi_fails(self):
        """Test handling when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            assert get_total_vram_mb() == 0

    def test_invalid_vram_values(self):
        """Test handling of non-numeric VRAM values."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="invalid\ndata")
            assert get_total_vram_mb() == 0

    def test_mixed_valid_invalid_values(self):
        """Test handling of mixed valid and invalid values."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="24576\ninvalid\n16384")
            # Should fail on first invalid value
            assert get_total_vram_mb() == 0

    def test_vram_with_empty_lines(self):
        """Test that empty lines are filtered correctly."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="24576\n\n24576\n")
            assert get_total_vram_mb() == 49152


# ============================================================================
# Tests for get_free_vram_per_gpu()
# ============================================================================


class TestGetFreeVramPerGpu:
    """Test suite for get_free_vram_per_gpu function."""

    def test_dual_gpu_free_vram(self):
        """Test free VRAM for two GPUs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VRAM_FREE_DUAL)
            result = get_free_vram_per_gpu()
            assert result == [20480, 22528]

    def test_single_gpu_free_vram(self):
        """Test free VRAM for single GPU."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="20480")
            result = get_free_vram_per_gpu()
            assert result == [20480]

    def test_empty_output(self):
        """Test handling of empty output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")
            assert get_free_vram_per_gpu() == []

    def test_output_with_empty_lines(self):
        """Test that empty lines are filtered correctly."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="20480\n\n22528\n")
            result = get_free_vram_per_gpu()
            assert result == [20480, 22528]

    def test_nvidia_smi_not_found(self):
        """Test handling when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            assert get_free_vram_per_gpu() == []

    def test_nvidia_smi_fails(self):
        """Test handling when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            assert get_free_vram_per_gpu() == []

    def test_invalid_vram_values(self):
        """Test handling of non-numeric VRAM values."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="invalid\ndata")
            assert get_free_vram_per_gpu() == []

    def test_quad_gpu_free_vram(self):
        """Test free VRAM for four GPUs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout="20480\n22528\n18432\n21504"
            )
            result = get_free_vram_per_gpu()
            assert result == [20480, 22528, 18432, 21504]
            assert len(result) == 4


# ============================================================================
# Tests for detect_nvlink()
# ============================================================================


class TestDetectNvlink:
    """Test suite for detect_nvlink function."""

    def test_nvlink_detected(self):
        """Test detection of NVLink connectivity."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_NVLINK_TOPOLOGY_WITH_NVLINK
            )
            has_nvlink, bond_type = detect_nvlink()
            assert has_nvlink is True
            assert bond_type is None  # No "Bonded" keyword in this output

    def test_nvlink_with_bonding(self):
        """Test detection of NVLink with bonding."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_NVLINK_TOPOLOGY_BONDED
            )
            has_nvlink, bond_type = detect_nvlink()
            assert has_nvlink is True
            assert bond_type == "Bonded"

    def test_no_nvlink(self):
        """Test when no NVLink is present (PCIe only)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_NVLINK_TOPOLOGY_NO_NVLINK
            )
            has_nvlink, bond_type = detect_nvlink()
            assert has_nvlink is False
            assert bond_type is None

    def test_empty_topology_output(self):
        """Test handling of empty topology output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")
            has_nvlink, bond_type = detect_nvlink()
            assert has_nvlink is False
            assert bond_type is None

    def test_nvidia_smi_not_found(self):
        """Test handling when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            has_nvlink, bond_type = detect_nvlink()
            assert has_nvlink is False
            assert bond_type is None

    def test_nvidia_smi_fails(self):
        """Test handling when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            has_nvlink, bond_type = detect_nvlink()
            assert has_nvlink is False
            assert bond_type is None

    def test_nvlink_different_versions(self):
        """Test detection of different NVLink versions."""
        topologies = [
            "GPU0  X  NV1\nGPU1 NV1  X",
            "GPU0  X  NV2\nGPU1 NV2  X",
            "GPU0  X  NV4\nGPU1 NV4  X",
            "GPU0  X  NV8\nGPU1 NV8  X",
        ]
        for topology in topologies:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=topology)
                has_nvlink, _ = detect_nvlink()
                assert has_nvlink is True


# ============================================================================
# Tests for check_nvidia_smi_available()
# ============================================================================


class TestCheckNvidiaSmiAvailable:
    """Test suite for check_nvidia_smi_available function."""

    def test_nvidia_smi_available(self):
        """Test when nvidia-smi is available."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VERSION_OUTPUT)
            assert check_nvidia_smi_available() is True

    def test_nvidia_smi_not_found(self):
        """Test when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            assert check_nvidia_smi_available() is False

    def test_nvidia_smi_fails(self):
        """Test when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            assert check_nvidia_smi_available() is False

    def test_nvidia_smi_permission_denied(self):
        """Test when nvidia-smi exists but permission is denied."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                126, "nvidia-smi", "Permission denied"
            )
            assert check_nvidia_smi_available() is False


# ============================================================================
# Tests for get_cuda_version()
# ============================================================================


class TestGetCudaVersion:
    """Test suite for get_cuda_version function."""

    def test_classic_format(self):
        """Classic 'CUDA Version: 12.2' single-line format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VERSION_OUTPUT)
            assert get_cuda_version() == "12.2"

    def test_colon_format(self):
        """Multi-line 'CUDA Version        : 13.1' format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_VERSION_OUTPUT_WITH_COLON
            )
            assert get_cuda_version() == "13.1"

    def test_deprecated_format(self):
        """Driver >= 610 deprecates 'CUDA version' in favour of 'CUDA UMD version'.

        The deprecated line's value is the literal word 'Deprecated', not a
        version — the regex must skip it and match the UMD line instead.
        """
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_VERSION_OUTPUT_DEPRECATED
            )
            assert get_cuda_version() == "13.3"

    def test_nvidia_smi_not_found(self):
        """Empty string when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            assert get_cuda_version() == ""

    def test_nvidia_smi_fails(self):
        """Empty string when nvidia-smi exits non-zero."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            assert get_cuda_version() == ""

    def test_unparseable_output(self):
        """Empty string when no CUDA version line is present."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="unexpected output")
            assert get_cuda_version() == ""


# ============================================================================
# Tests for get_nvidia_smi_version()
# ============================================================================


class TestGetNvidiaSmiVersion:
    """Test suite for get_nvidia_smi_version function."""

    def test_version_standard_format(self):
        """Test parsing of standard version format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VERSION_OUTPUT)
            version = get_nvidia_smi_version()
            assert version == "535.104.05"

    def test_version_alternative_format(self):
        """Test parsing of alternative version format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_VERSION_OUTPUT_ALT)
            version = get_nvidia_smi_version()
            assert version == "525.85.12"

    def test_version_two_part(self):
        """Test parsing of two-part version number."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="NVIDIA-SMI 535.104")
            version = get_nvidia_smi_version()
            assert version == "535.104"

    def test_nvidia_smi_not_found(self):
        """Test handling when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            assert get_nvidia_smi_version() == ""

    def test_nvidia_smi_fails(self):
        """Test handling when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            assert get_nvidia_smi_version() == ""

    def test_unexpected_output_format(self):
        """Test handling of unexpected output format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout="Unexpected output format"
            )
            assert get_nvidia_smi_version() == ""

    def test_empty_output(self):
        """Test handling of empty output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")
            assert get_nvidia_smi_version() == ""

    def test_version_with_extra_text(self):
        """Test parsing version with extra text around it."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Some text\nNVIDIA-SMI 470.129.06\nMore text",
            )
            version = get_nvidia_smi_version()
            assert version == "470.129.06"

    def test_version_with_colon_format(self):
        """Test parsing version with 'version  :' format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_VERSION_OUTPUT_WITH_COLON
            )
            version = get_nvidia_smi_version()
            assert version == "590.48.01"


# ============================================================================
# Tests for detect_gpus_with_details()
# ============================================================================


class TestDetectGpusWithDetails:
    """Test suite for detect_gpus_with_details function."""

    def test_single_gpu_with_details(self):
        """Test detection of single GPU with full details."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_GPU_DETAILS_SINGLE)
            gpus = detect_gpus_with_details()

            assert len(gpus) == 1
            gpu = gpus[0]

            assert isinstance(gpu, GPUMetadata)
            assert gpu.index == 0
            assert gpu.name == "NVIDIA GeForce RTX 3090"
            assert gpu.uuid == "GPU-12345678-1234-1234-1234-123456789012"
            assert gpu.total_memory == 24576
            assert gpu.used_memory == 12288
            assert gpu.free_memory == 12288
            assert gpu.memory_utilization == 50.0
            assert gpu.power_limit == 350
            assert gpu.power_draw == 280
            assert gpu.temperature == 65
            assert gpu.fan_speed == 45
            assert gpu.driver_version == "535.104.05"
            assert gpu.display_active is True
            assert gpu.compute_mode == "Default"

    def test_dual_gpu_with_details(self):
        """Test detection of two GPUs with different states."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=MOCK_GPU_DETAILS_DUAL)
            gpus = detect_gpus_with_details()

            assert len(gpus) == 2

            # First GPU
            assert gpus[0].index == 0
            assert gpus[0].memory_utilization == 50.0
            assert gpus[0].display_active is True

            # Second GPU
            assert gpus[1].index == 1
            assert gpus[1].used_memory == 8192
            assert gpus[1].free_memory == 16384
            assert gpus[1].memory_utilization == 33.33
            assert gpus[1].power_draw == 250
            assert gpus[1].temperature == 58
            assert gpus[1].fan_speed == 40
            assert gpus[1].display_active is False

    def test_gpu_with_unit_suffixes(self):
        """Test parsing values with unit suffixes (W, C, %)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_DETAILS_WITH_UNITS
            )
            gpus = detect_gpus_with_details()

            assert len(gpus) == 1
            gpu = gpus[0]

            # Should correctly parse values with units
            assert gpu.power_limit == 350
            assert gpu.power_draw == 280
            assert gpu.temperature == 65
            assert gpu.fan_speed == 45

    def test_empty_output(self):
        """Test handling of empty output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="")
            gpus = detect_gpus_with_details()
            assert gpus == []

    def test_malformed_csv_line(self):
        """Test handling of malformed CSV with insufficient columns."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_DETAILS_MALFORMED
            )
            gpus = detect_gpus_with_details()
            # Should skip malformed lines
            assert gpus == []

    def test_invalid_numeric_values(self):
        """Test handling of invalid numeric values in memory fields."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_DETAILS_INVALID_NUMBERS
            )
            gpus = detect_gpus_with_details()
            # Should skip lines with invalid numbers
            assert gpus == []

    def test_empty_field_values(self):
        """Test handling of empty field values."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_DETAILS_EMPTY_VALUES
            )
            gpus = detect_gpus_with_details()

            assert len(gpus) == 1
            gpu = gpus[0]

            # Empty values should default to 0
            assert gpu.total_memory == 0
            assert gpu.used_memory == 0
            assert gpu.free_memory == 0
            assert gpu.memory_utilization == 0.0
            assert gpu.power_limit == 0
            assert gpu.power_draw == 0
            assert gpu.temperature == 0
            assert gpu.fan_speed == 0

    def test_display_active_variations(self):
        """Test different variations of display_active field."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_DETAILS_DISPLAY_VARIATIONS
            )
            gpus = detect_gpus_with_details()

            assert len(gpus) == 4
            # "enabled" (lowercase)
            assert gpus[0].display_active is True
            # "ENABLED" (uppercase)
            assert gpus[1].display_active is True
            # "Disabled"
            assert gpus[2].display_active is False
            # "disabled"
            assert gpus[3].display_active is False

    def test_nvidia_smi_not_found(self):
        """Test handling when nvidia-smi is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")
            gpus = detect_gpus_with_details()
            assert gpus == []

    def test_nvidia_smi_fails(self):
        """Test handling when nvidia-smi command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "nvidia-smi", "Error"
            )
            gpus = detect_gpus_with_details()
            assert gpus == []

    def test_output_with_empty_lines(self):
        """Test that empty lines are filtered correctly."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0, stdout=MOCK_GPU_DETAILS_SINGLE + "\n\n\n"
            )
            gpus = detect_gpus_with_details()
            assert len(gpus) == 1

    def test_zero_total_memory(self):
        """Test handling of zero total memory (edge case)."""
        mock_data = (
            """0, GPU, UUID, 0, 0, 0, Default, 535.104.05, 350, 280, 65, 45, Enabled"""
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=mock_data)
            gpus = detect_gpus_with_details()

            assert len(gpus) == 1
            assert gpus[0].memory_utilization == 0.0

    def test_float_values_in_memory(self):
        """Test handling of float values in memory fields."""
        mock_data = """0, GPU, UUID, 24576.5, 12288.3, 12288.2, Default, 535.104.05, 350, 280, 65, 45, Enabled"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=mock_data)
            gpus = detect_gpus_with_details()

            assert len(gpus) == 1
            # Should convert floats to ints
            assert gpus[0].total_memory == 24576
            assert gpus[0].used_memory == 12288
            assert gpus[0].free_memory == 12288


# ============================================================================
# Tests for calculate_gpu_memory_utilization()
# ============================================================================


class TestCalculateGpuMemoryUtilization:
    """Test suite for calculate_gpu_memory_utilization function (fallback path).

    When config.json is unavailable, the function uses a heuristic fallback:
        kv_cache = model_size × (context_size / 32768) × kv_dtype_factor
        needed   = (model_weights + kv_cache + overhead + headroom) × safety
        utilization = needed / total_vram

    When config.json IS available, the architecture-aware path computes:
        kv_cache = 2 × layers × kv_heads × head_dim × ctx × bytes_per_elem
    See TestArchitectureAwareKvEstimation for those tests.
    """

    def test_8gb_gpu_small_context(self):
        """Test 8 GB GPU, default model (4096 MiB), 32k context, auto KV.

        model=4096, kv=4096×1.0×1.0=4096, overhead=1536, headroom=1024
        raw=10752, needed=10752×1.2=12902
        utilization=12902/8192 → clamped to 0.95
        """
        result = calculate_gpu_memory_utilization(8192, context_size=32768)
        assert 0.95 <= result <= 0.95

    def test_8gb_gpu_large_context_fp8(self):
        """Test 8 GB GPU, default model, 128k context, fp8 KV.

        model=4096, kv=4096×4×0.5=8192, overhead=1536, headroom=1024
        raw=14848, needed=14848×1.2=17818
        utilization=17818/8192 → clamped to 0.95
        """
        result = calculate_gpu_memory_utilization(
            8192, context_size=131072, kv_cache_dtype="fp8"
        )
        assert 0.95 <= result <= 0.95

    def test_33gb_gpu_128k_fp8(self):
        """Test 33 GB GPU, default model, 128k context, fp8 KV.

        model=4096, kv=4096×4×0.5=8192, overhead=1536, cudagraph=0.22×34120≈7506,
        headroom=1024
        raw=18937, needed=18937×1.2=22724
        utilization=22724/34120 ≈ 0.67
        """
        result = calculate_gpu_memory_utilization(
            34120, context_size=131072, kv_cache_dtype="fp8"
        )
        assert 0.60 <= result <= 0.72

    def test_33gb_gpu_32k_fp8(self):
        """Test 33 GB GPU, default model, 32k context, fp8 KV.

        model=4096, kv=4096×1×0.5=2048, overhead=1536, cudagraph≈7506, headroom=1024
        raw=12793, needed=12793×1.2=15351
        utilization=15351/34120 ≈ 0.45 → clamped to 0.50
        """
        result = calculate_gpu_memory_utilization(
            34120, context_size=32768, kv_cache_dtype="fp8"
        )
        assert result == 0.50

    def test_24gb_gpu_128k_fp8(self):
        """Test 24 GB GPU, default model, 128k context, fp8 KV.

        model=4096, kv=4096×4×0.5=8192, overhead=1536, cudagraph=0.22×24576≈5406,
        headroom=1024
        raw=17657, needed=17657×1.2=21188
        utilization=21188/24576 ≈ 0.86
        """
        result = calculate_gpu_memory_utilization(
            24576, context_size=131072, kv_cache_dtype="fp8"
        )
        assert 0.80 <= result <= 0.92

    def test_large_gpu_low_utilization(self):
        """Test that a large GPU with a small model gets low utilization.

        48 GB GPU, 32k context, fp8 KV:
        model=4096, kv=2048, overhead=1536, headroom=1024
        raw=8704, needed=10445
        utilization=10445/49152 ≈ 0.21 → clamped to 0.50
        """
        result = calculate_gpu_memory_utilization(
            49152, context_size=32768, kv_cache_dtype="fp8"
        )
        assert result == 0.50

    def test_custom_safety_factor(self):
        """Test with a custom safety factor (1.50 = 50% margin)."""
        result = calculate_gpu_memory_utilization(
            34120,
            context_size=131072,
            kv_cache_dtype="fp8",
            safety_factor=1.50,
        )
        # raw=18937 (incl. cudagraph≈3889), needed=18937×1.5=28405
        # utilization=28405/34120 ≈ 0.83
        assert 0.78 <= result <= 0.88

    def test_custom_overhead(self):
        """Test with a custom vLLM overhead."""
        result = calculate_gpu_memory_utilization(
            34120,
            context_size=131072,
            kv_cache_dtype="fp8",
            vllm_overhead_mb=2048,
        )
        # model=4096, kv=8192, overhead=2048, cudagraph≈3889, headroom=1024
        # raw=19449, needed=19449×1.2=23338
        # utilization=23338/34120 ≈ 0.68
        assert 0.62 <= result <= 0.74

    def test_fp8_halves_kv_cache(self):
        """Test that fp8 KV cache produces lower utilization than auto."""
        result_fp8 = calculate_gpu_memory_utilization(
            24576, context_size=65536, kv_cache_dtype="fp8"
        )
        result_auto = calculate_gpu_memory_utilization(
            24576, context_size=65536, kv_cache_dtype="auto"
        )
        assert result_fp8 < result_auto

    def test_larger_context_increases_utilization(self):
        """Test that larger context size increases utilization."""
        result_32k = calculate_gpu_memory_utilization(
            24576, context_size=32768, kv_cache_dtype="fp8"
        )
        result_128k = calculate_gpu_memory_utilization(
            24576, context_size=131072, kv_cache_dtype="fp8"
        )
        assert result_128k > result_32k

    def test_zero_vram_returns_fallback(self):
        """Test that zero VRAM returns the fallback value."""
        result = calculate_gpu_memory_utilization(0)
        assert result == 0.85

    def test_negative_vram_returns_fallback(self):
        """Test that negative VRAM returns the fallback value."""
        result = calculate_gpu_memory_utilization(-1000)
        assert result == 0.85

    def test_tiny_gpu_clamped_to_maximum(self):
        """Test that a tiny GPU with a large model is clamped to max utilization.

        The default model (4096 MiB) is larger than the GPU (1024 MiB),
        so utilization exceeds 1.0 and clamps to 0.88.
        """
        result = calculate_gpu_memory_utilization(
            1024, context_size=32768, kv_cache_dtype="fp8"
        )
        assert result == 0.95

    def test_huge_gpu_with_huge_context(self):
        """Test 96 GB GPU with 512k context — should fit comfortably.

        model=4096, kv=4096×16×0.5=32768, overhead=1536,
        cudagraph=0.114×98304≈11206, headroom=1024
        raw=50630, needed=50630×1.2=60756
        utilization=60756/98304 ≈ 0.62
        """
        result = calculate_gpu_memory_utilization(
            98304, context_size=524288, kv_cache_dtype="fp8"
        )
        assert 0.56 <= result <= 0.68

    def test_no_model_path_uses_default(self):
        """Test that missing model path uses default 4096 MiB estimate."""
        result = calculate_gpu_memory_utilization(
            8192, model_path="", context_size=32768
        )
        # Should still produce a valid result using 4096 MiB default
        assert 0.50 <= result <= 0.95


class TestArchitectureAwareKvEstimation:
    """Tests for the config.json-based KV cache estimation path.

    Verifies that when a model directory contains a config.json with
    architecture info, the function produces accurate KV estimates instead
    of falling back to the model-size heuristic.

    Uses mock for get_model_file_size to avoid writing multi-GB test files.
    """

    def _make_model_dir(self, tmp_path, config: dict):
        """Create a model directory with only config.json (no large files)."""
        import json

        model_dir = tmp_path / "test-model"
        model_dir.mkdir(exist_ok=True)
        (model_dir / "config.json").write_text(json.dumps(config))
        return str(model_dir)

    @pytest.fixture()
    def qwen_9b_config(self):
        """Typical 9B GQA config (Qwen-style)."""
        return {
            "num_hidden_layers": 40,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "hidden_size": 4096,
        }

    def test_9b_gqa_model_128k_fp8(self, tmp_path, qwen_9b_config):
        """9B GQA model (40 layers, 8 KV heads, head_dim=128) at 128k fp8.

        KV = 2 × 40 × 8 × 128 × 131072 × 1 byte = 10,240 MiB
        raw = 5000 + 10240 + 1536 + cudagraph(0.114×33400≈3807) + 1024 = 21,607
        needed = 21607 × 1.2 = 25,928
        On 33 GiB GPU: util ≈ 25928/33400 ≈ 0.78
        """
        model_path = self._make_model_dir(tmp_path, qwen_9b_config)
        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        assert 0.72 <= result <= 0.84

    def test_9b_gqa_model_128k_fp16(self, tmp_path, qwen_9b_config):
        """fp16 KV doubles the KV estimate → should use more VRAM.

        KV = 2 × 40 × 8 × 128 × 131072 × 2 = 20,480 MiB
        raw = 5000 + 20480 + 1536 = 27,016
        needed = 27016 × 1.2 = 32,419 → clamped to 0.95
        """
        model_path = self._make_model_dir(tmp_path, qwen_9b_config)
        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="auto",
            )
        assert result >= 0.95

    def test_7b_mha_model_32k_fp8(self, tmp_path):
        """7B MHA model (32 layers, 32 KV heads, head_dim=128) at 32k fp8.

        KV = 2 × 32 × 32 × 128 × 32768 × 1 = 8,192 MiB
        raw = 4000 + 8192 + 1536 + cudagraph(0.114×24576≈2801) + 1024 = 17,553
        needed = 17553 × 1.2 = 21,063
        On 24 GiB GPU: util ≈ 21063/24576 ≈ 0.86
        """
        model_path = self._make_model_dir(
            tmp_path,
            {
                "num_hidden_layers": 32,
                "num_attention_heads": 32,
                "num_key_value_heads": 32,
                "hidden_size": 4096,
            },
        )
        with patch("aria.helpers.memory.get_model_file_size", return_value=4000):
            result = calculate_gpu_memory_utilization(
                24576,
                model_path=model_path,
                context_size=32768,
                kv_cache_dtype="fp8",
            )
        assert 0.80 <= result <= 0.92

    def test_config_with_explicit_head_dim(self, tmp_path):
        """Model config that specifies head_dim directly."""
        model_path = self._make_model_dir(
            tmp_path,
            {
                "num_hidden_layers": 40,
                "num_attention_heads": 32,
                "num_key_value_heads": 8,
                "head_dim": 128,
                "hidden_size": 4096,
            },
        )
        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        assert 0.72 <= result <= 0.84

    def test_missing_config_falls_back_to_heuristic(self, tmp_path):
        """Without config.json, should use the fallback heuristic."""
        model_dir = tmp_path / "no-config-model"
        model_dir.mkdir()
        # No config.json — only model weights

        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=str(model_dir),
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        # Heuristic fallback: kv = 5000 * 4 * 0.5 = 10000
        # raw = 5000 + 10000 + 1536 + cudagraph≈3807 + 1024 = 21367,
        # needed = 25640, util = 25640/33400 ≈ 0.77
        assert 0.70 <= result <= 0.83

    def test_fp8_vs_auto_with_config(self, tmp_path, qwen_9b_config):
        """fp8 KV should produce lower utilization than auto/fp16."""
        model_path = self._make_model_dir(tmp_path, qwen_9b_config)

        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result_fp8 = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
            result_auto = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="auto",
            )
        assert result_fp8 < result_auto

    def test_small_gpu_with_config_clamps_to_max(self, tmp_path, qwen_9b_config):
        """8 GiB GPU with large model + context should clamp to 0.88."""
        model_path = self._make_model_dir(tmp_path, qwen_9b_config)

        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                8192,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        assert result == 0.95

    # ------------------------------------------------------------------
    # Multimodal / text_config nesting regression tests
    # ------------------------------------------------------------------

    def _make_multimodal_model_dir(self, tmp_path, text_config: dict):
        """Create a multimodal model directory with text_config nesting.

        Mimics models like Mistral3/Pixtral/LLaVA where the LLM architecture
        parameters live inside a nested ``text_config`` key rather than at
        the top level of config.json.
        """
        import json

        model_dir = tmp_path / "multimodal-model"
        model_dir.mkdir(exist_ok=True)
        config = {
            "model_type": "mistral3",
            "architectures": ["Mistral3ForConditionalGeneration"],
            "text_config": text_config,
            "vision_config": {
                "model_type": "pixtral",
                "num_hidden_layers": 24,
                "hidden_size": 1024,
            },
        }
        (model_dir / "config.json").write_text(json.dumps(config))
        return str(model_dir)

    def test_multimodal_text_config_kv_estimation(self, tmp_path):
        """Mistral3 multimodal model: architecture params in text_config.

        text_config: 34 layers, 8 KV heads, head_dim=128, 196608 ctx, auto (fp16)
        KV = 2 × 34 × 8 × 128 × 196608 × 2 = 27,262,976 B ≈ 26,000 MiB
        raw = 6490 + 26000 + 512 + 1024 = 34026
        needed = 34026 × 1.2 = 40831
        On 32 GB GPU (32768 MiB): util ≈ 40831/32768 → clamped to 0.95
        """
        text_config = {
            "num_hidden_layers": 34,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "head_dim": 128,
            "hidden_size": 4096,
            "max_position_embeddings": 262144,
        }
        model_path = self._make_multimodal_model_dir(tmp_path, text_config)
        with patch("aria.helpers.memory.get_model_file_size", return_value=6490):
            result = calculate_gpu_memory_utilization(
                32768,
                model_path=model_path,
                context_size=196608,
                kv_cache_dtype="auto",
            )
        assert result >= 0.95

    def test_multimodal_text_config_fp8_lower_than_auto(self, tmp_path):
        """fp8 KV in text_config model should produce lower utilization."""
        text_config = {
            "num_hidden_layers": 34,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "head_dim": 128,
            "hidden_size": 4096,
        }
        model_path = self._make_multimodal_model_dir(tmp_path, text_config)
        with patch("aria.helpers.memory.get_model_file_size", return_value=6490):
            result_fp8 = calculate_gpu_memory_utilization(
                32768,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
            result_auto = calculate_gpu_memory_utilization(
                32768,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="auto",
            )
        assert result_fp8 < result_auto

    def test_multimodal_text_config_estimates_correctly(self, tmp_path):
        """Verify exact KV estimate from text_config params.

        34 layers, 8 kv_heads, head_dim=128, 131072 ctx, fp8
        KV = 2 × 34 × 8 × 128 × 131072 × 1 = 9,113,600,000 B ≈ 8,691 MiB
        raw = 5000 + 8691 + 1536 + cudagraph(0.114×33400≈3807) + 1024 = 20,058
        needed = 20058 × 1.2 = 24,069
        On 33 GB GPU: util ≈ 24069/33400 ≈ 0.72
        """
        text_config = {
            "num_hidden_layers": 34,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "head_dim": 128,
            "hidden_size": 4096,
        }
        model_path = self._make_multimodal_model_dir(tmp_path, text_config)
        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        assert 0.66 <= result <= 0.78

    def test_multimodal_with_only_hidden_size_and_heads(self, tmp_path):
        """text_config with no head_dim (derived from hidden_size / num_heads)."""
        text_config = {
            "num_hidden_layers": 40,
            "num_attention_heads": 32,
            "num_key_value_heads": 8,
            "hidden_size": 4096,
            # head_dim = 4096 / 32 = 128
        }
        model_path = self._make_multimodal_model_dir(tmp_path, text_config)
        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        # Same KV as qwen_9b_config: 2×40×8×128×131072×1 = 10240 MiB
        # raw = 5000 + 10240 + 1536 + cudagraph≈3807 + 1024 = 21607,
        # needed = 25928, util = 25928/33400 ≈ 0.78
        assert 0.72 <= result <= 0.84

    def test_top_level_params_take_precedence_over_text_config(self, tmp_path):
        """When both top-level and text_config have params, top-level wins."""
        import json

        model_dir = tmp_path / "both-levels-model"
        model_dir.mkdir(exist_ok=True)
        config = {
            "num_hidden_layers": 20,
            "num_key_value_heads": 4,
            "head_dim": 64,
            "text_config": {
                "num_hidden_layers": 40,
                "num_key_value_heads": 8,
                "head_dim": 128,
            },
        }
        (model_dir / "config.json").write_text(json.dumps(config))
        model_path = str(model_dir)

        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        # Top-level: KV = 2×20×4×64×131072×1 = 2,684,354,560 B ≈ 2560 MiB
        # raw = 5000 + 2560 + 1536 + cudagraph≈3807 + 1024 = 13927,
        # needed = 16712, util = 16712/33400 ≈ 0.50
        assert result == 0.50

    def test_multimodal_empty_text_config_uses_fallback(self, tmp_path):
        """Empty text_config should trigger heuristic fallback."""
        import json

        model_dir = tmp_path / "empty-text-config-model"
        model_dir.mkdir(exist_ok=True)
        config = {
            "model_type": "some_model",
            "text_config": {},
        }
        (model_dir / "config.json").write_text(json.dumps(config))
        model_path = str(model_dir)

        with patch("aria.helpers.memory.get_model_file_size", return_value=5000):
            result = calculate_gpu_memory_utilization(
                33400,
                model_path=model_path,
                context_size=131072,
                kv_cache_dtype="fp8",
            )
        # Heuristic fallback: kv = 5000 × 4 × 0.5 = 10000
        # raw = 5000 + 10000 + 1536 + cudagraph≈3807 + 1024 = 21367 → util ≈ 0.77
        assert 0.70 <= result <= 0.83


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for nvidia module functions."""

    def test_availability_check_before_operations(self):
        """Test checking availability before performing operations."""
        with patch("subprocess.run") as mock_run:
            # First call: check availability
            # Subsequent calls: actual operations
            mock_run.side_effect = [
                Mock(returncode=0, stdout=MOCK_VERSION_OUTPUT),  # available
                Mock(returncode=0, stdout=MOCK_GPU_LIST_DUAL),  # gpu count
                Mock(returncode=0, stdout=MOCK_VRAM_TOTAL_DUAL),  # total vram
            ]

            # Check if nvidia-smi is available first
            if check_nvidia_smi_available():
                gpu_count = detect_gpu_count()
                total_vram = get_total_vram_mb()

                assert gpu_count == 2
                assert total_vram == 49152

    def test_graceful_degradation_when_unavailable(self):
        """Test that all functions degrade gracefully when nvidia-smi is unavailable."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")

            # All functions should return safe defaults
            assert check_nvidia_smi_available() is False
            assert detect_gpu_count() == 0
            assert get_total_vram_mb() == 0
            assert get_free_vram_per_gpu() == []
            assert detect_nvlink() == (False, None)
            assert get_nvidia_smi_version() == ""
