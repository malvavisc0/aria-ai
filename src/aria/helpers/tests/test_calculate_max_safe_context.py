"""Comprehensive tests for calculate_max_safe_context function."""

from aria.helpers.nvidia import calculate_max_safe_context


class TestCalculateMaxSafeContext:
    """Test suite for calculate_max_safe_context function."""

    # ========================================================================
    # Basic Functionality Tests - LLM
    # ========================================================================

    def test_llm_4gb_tier(self):
        """Test LLM with 4GB safe memory tier."""
        # To get exactly 4GB safe: (free - 0) * 0.9 / 1024 = 4
        # free = 4 * 1024 / 0.9 = 4551.11, use 4551 to stay at or below 4GB
        # 4551 * 0.9 / 1024 = 3.999 <= 4, selects 4GB tier
        result = calculate_max_safe_context(4551, 0, False)
        assert result == 2048

    def test_llm_8gb_tier(self):
        """Test LLM with 8GB safe memory tier."""
        # To get exactly 8GB safe: free = 8 * 1024 / 0.9 = 9102.22, use 9102
        # 9102 * 0.9 / 1024 = 7.998 < 8, selects 8GB tier
        result = calculate_max_safe_context(9102, 0, False)
        assert result == 8192

    def test_llm_16gb_tier(self):
        """Test LLM with 16GB safe memory tier."""
        # To get exactly 16GB safe: free = 16 * 1024 / 0.9 = 18204.44, use 18204
        # 18204 * 0.9 / 1024 = 15.996 < 16, selects 16GB tier
        result = calculate_max_safe_context(18204, 0, False)
        assert result == 32768

    def test_llm_32gb_tier(self):
        """Test LLM with 32GB safe memory tier."""
        # To get exactly 32GB safe: free = 32 * 1024 / 0.9 = 36408.89, use 36408
        # 36408 * 0.9 / 1024 = 31.992 < 32, selects 32GB tier
        result = calculate_max_safe_context(36408, 0, False)
        assert result == 262144

    def test_llm_maximum_tier(self):
        """Test LLM with memory exceeding all tiers."""
        # 200GB free should give maximum tier (128GB threshold → 1,572,864 tokens)
        result = calculate_max_safe_context(204800, 0, False)
        assert result == 1572864

    # ========================================================================
    # Basic Functionality Tests - Embedding Models
    # ========================================================================

    def test_embedding_2gb_tier(self):
        """Test embedding model with 2GB safe memory tier."""
        # To get exactly 2GB safe: free = 2 * 1024 / 0.9 = 2275.56, use 2275
        # 2275 * 0.9 / 1024 = 1.999 < 2, selects 2GB tier (256 tokens)
        # But MIN_CONTEXT = 1024, so returns 1024
        result = calculate_max_safe_context(2275, 0, True)
        assert result == 1024

    def test_embedding_4gb_tier(self):
        """Test embedding model with 4GB safe memory tier."""
        # To get exactly 4GB safe: free = 4 * 1024 / 0.9 = 4551.11, use 4551
        # 4551 * 0.9 / 1024 = 3.999 < 4, selects 4GB tier (512 tokens)
        # But MIN_CONTEXT = 1024, so returns 1024
        result = calculate_max_safe_context(4551, 0, True)
        assert result == 1024

    def test_embedding_8gb_tier(self):
        """Test embedding model with 8GB safe memory tier."""
        # To get exactly 8GB safe: free = 8 * 1024 / 0.9 = 9102.22, use 9102
        # 9102 * 0.9 / 1024 = 7.998 < 8, selects 8GB tier
        result = calculate_max_safe_context(9102, 0, True)
        assert result == 1024

    def test_embedding_16gb_tier(self):
        """Test embedding model with 16GB safe memory tier."""
        # To get exactly 16GB safe: free = 16 * 1024 / 0.9 = 18204.44, use 18204
        # 18204 * 0.9 / 1024 = 15.996 < 16, selects 16GB tier
        result = calculate_max_safe_context(18204, 0, True)
        assert result == 2048

    def test_embedding_maximum_tier(self):
        """Test embedding model with memory exceeding all tiers."""
        # 40GB free should give maximum tier
        result = calculate_max_safe_context(40960, 0, True)
        assert result == 4096

    # ========================================================================
    # Edge Cases - Zero and Negative Values
    # ========================================================================

    def test_zero_free_vram(self):
        """Test with zero free VRAM."""
        assert calculate_max_safe_context(0, 0, False) == 0

    def test_negative_free_vram(self):
        """Test with negative free VRAM."""
        assert calculate_max_safe_context(-1000, 0, False) == 0

    def test_negative_model_size(self):
        """Test with negative model size."""
        assert calculate_max_safe_context(8192, -1000, False) == 0

    def test_model_larger_than_free_vram(self):
        """Test when model size exceeds free VRAM."""
        assert calculate_max_safe_context(8192, 10000, False) == 0

    def test_model_equals_free_vram(self):
        """Test when model size exactly equals free VRAM."""
        assert calculate_max_safe_context(8192, 8192, False) == 0

    # ========================================================================
    # Edge Cases - Below Minimum Threshold
    # ========================================================================

    def test_llm_below_minimum_threshold(self):
        """Test LLM with memory below absolute minimum (1.5GB)."""
        # 1.4GB safe memory is below absolute minimum
        # To get 1.4GB safe: free = 1.4 * 1024 / 0.9 = 1592.89
        result = calculate_max_safe_context(1592, 0, False)
        assert result == 0

    def test_embedding_below_minimum_threshold(self):
        """Test embedding with memory below absolute minimum (1.5GB)."""
        # 1.4GB safe memory is below absolute minimum
        # To get 1.4GB safe: free = 1.4 * 1024 / 0.9 = 1592.89
        result = calculate_max_safe_context(1592, 0, True)
        assert result == 0

    # ========================================================================
    # Tier Boundary Tests
    # ========================================================================

    def test_llm_just_below_8gb_tier(self):
        """Test LLM just below 8GB tier boundary."""
        # 7.9GB safe: 7.9 <= 8? Yes → selects 8GB tier
        # To get 7.9GB safe: free = 7.9 * 1024 / 0.9 = 8988.44
        result = calculate_max_safe_context(8988, 0, False)
        assert result == 8192

    def test_llm_just_above_8gb_tier(self):
        """Test LLM just above 8GB tier boundary."""
        # 8.1GB safe: 8.1 <= 8? No, 8.1 <= 10? Yes → selects 10GB tier
        # To get 8.1GB safe: free = 8.1 * 1024 / 0.9 = 9216
        result = calculate_max_safe_context(9216, 0, False)
        assert result == 12288

    def test_embedding_just_below_4gb_tier(self):
        """Test embedding just below 4GB tier boundary."""
        # 3.9GB safe: 3.9 <= 4? Yes → selects 4GB tier (512 tokens)
        # But MIN_CONTEXT = 1024, so returns 1024
        # To get 3.9GB safe: free = 3.9 * 1024 / 0.9 = 4437.33
        result = calculate_max_safe_context(4437, 0, True)
        assert result == 1024

    def test_embedding_just_above_4gb_tier(self):
        """Test embedding just above 4GB tier boundary."""
        # 4.1GB safe: 4.1 <= 4? No, 4.1 <= 6? Yes → selects 6GB tier (768 tokens)
        # But MIN_CONTEXT = 1024, so returns 1024
        # To get 4.1GB safe: free = 4.1 * 1024 / 0.9 = 4665.78
        result = calculate_max_safe_context(4666, 0, True)
        assert result == 1024

    # ========================================================================
    # Model Size Subtraction Tests
    # ========================================================================

    def test_llm_with_small_model(self):
        """Test LLM with small model size."""
        # 16GB free - 2GB model = 14GB available
        # 14GB * 0.9 = 12.6GB safe: 12.6 <= 14? Yes → selects 14GB tier
        result = calculate_max_safe_context(16384, 2048, False)
        assert result == 24576

    def test_llm_with_large_model(self):
        """Test LLM with large model size."""
        # 32GB free - 16GB model = 16GB available
        # 16GB * 0.9 = 14.4GB safe: 14.4 <= 16? Yes → selects 16GB tier
        result = calculate_max_safe_context(32768, 16384, False)
        assert result == 32768

    def test_embedding_with_model(self):
        """Test embedding model with model size."""
        # 8GB free - 1GB model = 7GB available
        # 7GB * 0.9 = 6.3GB safe: 6.3 <= 8? Yes → selects 8GB tier
        result = calculate_max_safe_context(8192, 1024, True)
        assert result == 1024

    def test_model_leaves_just_enough_memory(self):
        """Test when model leaves just enough memory for minimum tier."""
        # For LLM: need 4GB safe = 4.44GB available
        # 10GB free - 5.56GB model = 4.44GB available
        result = calculate_max_safe_context(10240, 5693, False)
        assert result == 2048

    # ========================================================================
    # Safety Margin Tests
    # ========================================================================

    def test_safety_margin_applied_llm(self):
        """Test that 10% safety margin is correctly applied for LLM."""
        # 10GB free → 9GB safe: 9 <= 10? Yes → selects 10GB tier
        result = calculate_max_safe_context(10240, 0, False)
        assert result == 12288

    def test_safety_margin_applied_embedding(self):
        """Test that 10% safety margin is correctly applied for embedding."""
        # 5GB free → 4.5GB safe: 4.5 <= 6? Yes → selects 6GB tier (768 tokens)
        # But MIN_CONTEXT = 1024, so returns 1024
        result = calculate_max_safe_context(5120, 0, True)
        assert result == 1024

    def test_safety_margin_pushes_below_threshold(self):
        """Test when safety margin pushes memory below tier threshold."""
        # 8.8GB free → 7.92GB safe: 7.92 <= 8? Yes → selects 8GB tier
        result = calculate_max_safe_context(9011, 0, False)
        assert result == 8192

    # ========================================================================
    # Input Validation Tests
    # ========================================================================

    def test_non_integer_free_vram_float(self):
        """Test with float free VRAM (should fail type check)."""
        result = calculate_max_safe_context(8192.5, 0, False)  # type: ignore
        assert result == 0

    def test_non_integer_model_size_float(self):
        """Test with float model size (should fail type check)."""
        result = calculate_max_safe_context(8192, 1024.5, False)  # type: ignore
        assert result == 0

    def test_non_integer_free_vram_string(self):
        """Test with string free VRAM (should fail type check)."""
        result = calculate_max_safe_context("8192", 0, False)  # type: ignore
        assert result == 0

    def test_non_integer_model_size_string(self):
        """Test with string model size (should fail type check)."""
        result = calculate_max_safe_context(8192, "1024", False)  # type: ignore
        assert result == 0

    def test_none_values(self):
        """Test with None values."""
        assert calculate_max_safe_context(None, 0, False) == 0  # type: ignore
        assert calculate_max_safe_context(8192, None, False) == 0  # type: ignore

    # ========================================================================
    # Realistic Scenario Tests
    # ========================================================================

    def test_realistic_consumer_gpu_llm(self):
        """Test realistic scenario: RTX 3090 (24GB) running LLM."""
        # 24GB total, assume 20GB free after OS/other processes
        # 20GB * 0.9 = 18GB safe: 18 <= 20? Yes → selects 20GB tier
        result = calculate_max_safe_context(20480, 0, False)
        assert result == 49152

    def test_realistic_consumer_gpu_with_model(self):
        """Test realistic scenario: RTX 3090 with 7B model loaded."""
        # 24GB total, 20GB free, 7B model ≈ 14GB
        # (20GB - 14GB) * 0.9 = 5.4GB safe → should get 4GB tier
        result = calculate_max_safe_context(20480, 14336, False)
        assert result == 4096

    def test_realistic_datacenter_gpu(self):
        """Test realistic scenario: A100 (80GB) running LLM."""
        # 80GB total, assume 70GB free
        # 70GB * 0.9 = 63GB safe → should get 64GB tier
        result = calculate_max_safe_context(71680, 0, False)
        assert result == 786432

    def test_realistic_embedding_model(self):
        """Test realistic scenario: Embedding model on consumer GPU."""
        # 16GB GPU, 12GB free, 1GB embedding model
        # (12GB - 1GB) * 0.9 = 9.9GB safe: 9.9 <= 12? Yes → selects 12GB tier
        result = calculate_max_safe_context(12288, 1024, True)
        assert result == 1536

    def test_realistic_low_memory_scenario(self):
        """Test realistic scenario: Low memory situation."""
        # 8GB GPU, only 2GB free, 500MB model
        # (2GB - 0.5GB) * 0.9 = 1.35GB safe → should get 0 (below 1.5GB absolute minimum)
        result = calculate_max_safe_context(2048, 512, False)
        assert result == 0

    # ========================================================================
    # Granular Tier Tests
    # ========================================================================

    def test_llm_intermediate_tiers(self):
        """Test LLM intermediate tier values."""
        # Recalculated to match actual tier selection (accounting for floating point precision)
        # 6826 * 0.9 / 1024 = 5.999 GB: 5.999 <= 6? Yes → 6GB tier = 4,096 tokens
        # 11377 * 0.9 / 1024 = 9.999 GB: 9.999 <= 10? Yes → 10GB tier = 12,288 tokens
        # 15928 * 0.9 / 1024 = 13.999 GB: 13.999 <= 14? Yes → 14GB tier = 24,576 tokens
        # 22755 * 0.9 / 1024 = 19.999 GB: 19.999 <= 20? Yes → 20GB tier = 49,152 tokens
        # 31857 * 0.9 / 1024 = 27.999 GB: 27.999 <= 28? Yes → 28GB tier = 131,072 tokens
        test_cases = [
            (6826, 4096),  # 6GB → 4,096 tokens
            (11377, 12288),  # 10GB → 12,288 tokens
            (15928, 24576),  # 14GB → 24,576 tokens
            (22755, 49152),  # 20GB → 49,152 tokens
            (31857, 131072),  # 28GB → 131,072 tokens
        ]
        for free_mb, expected_tokens in test_cases:
            result = calculate_max_safe_context(free_mb, 0, False)
            assert result == expected_tokens

    def test_embedding_intermediate_tiers(self):
        """Test embedding intermediate tier values."""
        test_cases = [
            (
                3413,
                1024,
            ),  # 3GB safe: 3 <= 3? Yes → 3GB tier = 384 tokens, but MIN_CONTEXT = 1024
            (
                6827,
                1024,
            ),  # 6GB safe: 6 <= 6? Yes → 6GB tier = 768 tokens, but MIN_CONTEXT = 1024
            (
                13653,
                1536,
            ),  # 12GB safe: 12 <= 12? Yes → 12GB tier = 1,536 tokens
            (
                27306,
                3072,
            ),  # 24GB safe: 24 <= 24? Yes → 24GB tier = 3,072 tokens
        ]
        for free_mb, expected_tokens in test_cases:
            result = calculate_max_safe_context(free_mb, 0, True)
            assert result == expected_tokens

    # ========================================================================
    # Comparison Tests - LLM vs Embedding
    # ========================================================================

    def test_same_memory_different_model_types(self):
        """Test that same memory gives different results for LLM vs embedding."""
        # 8GB safe memory
        llm_result = calculate_max_safe_context(9102, 0, False)
        embedding_result = calculate_max_safe_context(9102, 0, True)

        # LLM should get more tokens
        assert llm_result > embedding_result
        assert llm_result == 8192
        assert embedding_result == 1024

    def test_embedding_more_conservative(self):
        """Test that embedding models are more conservative across tiers."""
        # Test multiple memory sizes
        memory_sizes = [4551, 9102, 18204, 36408]

        for mem_mb in memory_sizes:
            llm_result = calculate_max_safe_context(mem_mb, 0, False)
            embedding_result = calculate_max_safe_context(mem_mb, 0, True)
            # LLM should always get more or equal tokens
            assert llm_result >= embedding_result
