"""Unit tests for NumberMatcher."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from number_matcher import NumberMatcher


class TestNumberMatcher:
    """Tests for NumberMatcher class."""
    
    @pytest.fixture
    def matcher(self):
        """Create a fresh matcher for each test."""
        return NumberMatcher()
    
    def test_exact_match(self, matcher):
        """Test exact number matching."""
        matcher.load_patterns(["441234567890"])
        
        assert matcher.is_match("441234567890")[0] == True
        assert matcher.is_match("+441234567890")[0] == True
        assert matcher.is_match("00441234567890")[0] == True
        assert matcher.is_match("441234567891")[0] == False
    
    def test_prefix_wildcard(self, matcher):
        """Test prefix wildcard (e.g., 441234*)."""
        matcher.load_patterns(["441234*"])
        
        assert matcher.is_match("441234567890")[0] == True
        assert matcher.is_match("441234000000")[0] == True
        assert matcher.is_match("441235000000")[0] == False
    
    def test_country_wildcard(self, matcher):
        """Test country wildcard (e.g., 44*)."""
        matcher.load_patterns(["44*"])
        
        assert matcher.is_match("+441234567890")[0] == True
        assert matcher.is_match("+447700900123")[0] == True
        assert matcher.is_match("+33123456789")[0] == False
    
    def test_universal_wildcard(self, matcher):
        """Test universal wildcard (*)."""
        matcher.load_patterns(["*"])
        
        assert matcher.is_match("441234567890")[0] == True
        assert matcher.is_match("33123456789")[0] == True
        assert matcher.is_match("anything")[0] == True
    
    def test_empty_input(self, matcher):
        """Test empty or None input."""
        matcher.load_patterns(["44*"])
        
        assert matcher.is_match("")[0] == False
        assert matcher.is_match(None)[0] == False
    
    def test_normalization(self, matcher):
        """Test phone number normalization."""
        matcher.load_patterns(["441234567890"])
        
        # All should normalize to same number
        variants = [
            "441234567890",
            "+441234567890",
            "00441234567890",
            "+44 1234 567890",
            "+44-1234-567890",
        ]
        
        for v in variants:
            assert matcher.is_match(v)[0] == True, f"Failed for: {v}"


def main():
    """Run tests."""
    pytest.main([__file__, "-v"])


if __name__ == "__main__":
    main()