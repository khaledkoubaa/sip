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
                # Match anything non-empty
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
        - 07xxx... (UK mobile) → 447xxx...
        - 01xxx... (UK landline) → 441xxx...
        - Spaces, dashes, dots removed
        
        Args:
            number: Raw phone number
            
        Returns:
            Normalized number (digits only, international format)
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
        
        # Handle UK domestic format: 0... → 44...
        # UK numbers starting with 0 followed by 1-9 are domestic
        if number.startswith('0') and len(number) >= 10:
            # Check it's a valid UK domestic number (not 00 which we handled above)
            if len(number) == 11 and number[1] in '123456789':
                # UK domestic: 01onal, 02london, 03, 07mobile, 08, 09
                number = '44' + number[1:]
                logger.debug(f"Converted UK domestic: {original} → {number}")
            elif len(number) == 10 and number[1] in '123456789':
                # Some UK numbers are 10 digits
                number = '44' + number[1:]
                logger.debug(f"Converted UK domestic (10 digit): {original} → {number}")
        
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
                logger.info(f"✓ Match: {caller_number} (normalized: {normalized}) → pattern '{pattern}'")
                return True, pattern
        
        logger.info(f"✗ No match: {caller_number} (normalized: {normalized})")
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
    
    # Test patterns (from the real API)
    patterns = [
        "441234567890",  # Exact
        "441234*",       # Area code
        "441844220022",  # Client's test number
        "21620222783",   # Your Tunisia number
        "216*",          # Tunisia country
    ]
    
    matcher.load_patterns(patterns)
    print(f"\nLoaded patterns: {patterns}\n")
    
    # Test cases including the problematic one
    test_cases = [
        ("01844220022", True, "UK domestic → should match 441844220022"),
        ("+441844220022", True, "International format"),
        ("441844220022", True, "Already international"),
        ("+441234567890", True, "Exact match"),
        ("01onal number", True, "UK domestic 01234..."),
        ("+447700900123", False, "UK mobile not in list"),
        ("+21620222783", True, "Tunisia number"),
        ("+33123456789", False, "French number"),
        ("", False, "Empty"),
    ]
    
    # Fix test case
    test_cases = [
        ("01844220022", True, "UK domestic → should match 441844220022"),
        ("+441844220022", True, "International format"),
        ("441844220022", True, "Already international"),
        ("+441234567890", True, "Exact match"),
        ("01234567890", True, "UK domestic 01234..."),
        ("+447700900123", False, "UK mobile not in list"),
        ("+21620222783", True, "Tunisia number"),
        ("+33123456789", False, "French number"),
        ("", False, "Empty"),
    ]
    
    print("-" * 70)
    print(f"{'NUMBER':<20} {'EXPECTED':<10} {'RESULT':<10} {'NOTE'}")
    print("-" * 70)
    
    all_passed = True
    for number, expected, note in test_cases:
        is_match, pattern = matcher.is_match(number)
        passed = is_match == expected
        all_passed = all_passed and passed
        
        status = "✓" if passed else "✗ FAIL"
        display_num = number if number else "(empty)"
        matched = f"→{pattern}" if pattern else ""
        print(f"{display_num:<20} {str(expected):<10} {str(is_match):<10} {note} {status} {matched}")
    
    print("-" * 70)
    print(f"\nResult: {'ALL TESTS PASSED ✓' if all_passed else 'SOME TESTS FAILED ✗'}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())