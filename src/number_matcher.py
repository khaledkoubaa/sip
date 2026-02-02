"""
Number Matcher Module
Handles wildcard pattern matching for phone numbers.

Patterns:
- 441234567890  → Exact match
- 441234*       → Prefix match (all numbers starting with 441234)
- 44*           → All UK numbers
- *             → Allow all callers
"""

import re
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class NumberMatcher:
    """Matches phone numbers against wildcard patterns."""
    
    def __init__(self):
        self.patterns: List[str] = []
        self._compiled: List[Tuple[str, re.Pattern]] = []
    
    def load_patterns(self, pattern_list: List[str]) -> int:
        """
        Load a list of patterns.
        
        Args:
            pattern_list: List of patterns (can include * wildcard)
            
        Returns:
            Number of patterns loaded
        """
        self.patterns = []
        self._compiled = []
        
        for pattern in pattern_list:
            if pattern is None:
                continue
            pattern = str(pattern).strip()
            if not pattern:
                continue
            
            self.patterns.append(pattern)
            
            # Convert wildcard pattern to regex
            if pattern == '*':
                # Match anything (including empty)
                regex = re.compile(r'^.+$')
            elif '*' in pattern:
                # Escape special regex chars, then replace \* with .*
                escaped = re.escape(pattern)
                regex_pattern = escaped.replace(r'\*', '.*')
                regex = re.compile(f'^{regex_pattern}$')
            else:
                # Exact match only
                regex = re.compile(f'^{re.escape(pattern)}$')
            
            self._compiled.append((pattern, regex))
        
        logger.info(f"Loaded {len(self.patterns)} patterns")
        logger.debug(f"Patterns: {self.patterns}")
        
        return len(self.patterns)
    
    def normalize_number(self, number: str) -> str:
        """
        Normalize phone number for consistent matching.
        
        Handles:
        - +44... → 44...
        - 0044... → 44...
        - Spaces, dashes, dots removed
        
        Args:
            number: Raw phone number
            
        Returns:
            Normalized number (digits only)
        """
        if not number:
            return ""
        
        original = number
        
        # Remove all non-digit characters except leading +
        number = re.sub(r'[^\d+]', '', str(number))
        
        # Remove leading +
        if number.startswith('+'):
            number = number[1:]
        
        # Remove leading 00 (international prefix)
        if number.startswith('00'):
            number = number[2:]
        
        logger.debug(f"Normalized: {original} → {number}")
        return number
    
    def is_match(self, caller_number: str) -> Tuple[bool, Optional[str]]:
        """
        Check if caller number matches any pattern.
        
        Args:
            caller_number: The caller's phone number
            
        Returns:
            Tuple of (is_match, matched_pattern or None)
        """
        if not caller_number:
            logger.debug("Empty caller number")
            return False, None
        
        normalized = self.normalize_number(caller_number)
        
        if not normalized:
            logger.warning(f"Could not normalize: {caller_number}")
            return False, None
        
        # Check against each pattern
        for pattern, regex in self._compiled:
            if regex.match(normalized):
                logger.info(f"✓ Match: {caller_number} → pattern '{pattern}'")
                return True, pattern
        
        logger.info(f"✗ No match: {caller_number}")
        return False, None
    
    def get_patterns(self) -> List[str]:
        """Get current list of patterns."""
        return self.patterns.copy()
    
    def __len__(self) -> int:
        return len(self.patterns)
    
    def __repr__(self) -> str:
        return f"NumberMatcher(patterns={len(self.patterns)})"


def main():
    """Test the number matcher."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)s: %(message)s'
    )
    
    print("=" * 60)
    print("NUMBER MATCHER TEST")
    print("=" * 60)
    
    matcher = NumberMatcher()
    
    # Test patterns
    patterns = [
        "441234567890",  # Exact
        "441234*",       # Area code
        "44*",           # Country
    ]
    
    matcher.load_patterns(patterns)
    print(f"\nLoaded patterns: {patterns}\n")
    
    # Test cases
    test_cases = [
        ("+441234567890", True, "Exact match"),
        ("441234567890", True, "Exact match no +"),
        ("00441234567890", True, "With 00 prefix"),
        ("+44 1234 567890", True, "With spaces"),
        ("+441234999999", True, "Area code match"),
        ("+447700900123", True, "UK mobile"),
        ("+33123456789", False, "French number"),
        ("+1234567890", False, "US number"),
        ("", False, "Empty"),
        ("anonymous", False, "Anonymous"),
    ]
    
    print("-" * 60)
    print(f"{'NUMBER':<25} {'EXPECTED':<10} {'RESULT':<10} {'NOTE'}")
    print("-" * 60)
    
    all_passed = True
    for number, expected, note in test_cases:
        is_match, pattern = matcher.is_match(number)
        passed = is_match == expected
        all_passed = all_passed and passed
        
        status = "✓" if passed else "✗ FAIL"
        display_num = number if number else "(empty)"
        print(f"{display_num:<25} {str(expected):<10} {str(is_match):<10} {note} {status}")
    
    print("-" * 60)
    print(f"\nResult: {'ALL TESTS PASSED ✓' if all_passed else 'SOME TESTS FAILED ✗'}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())