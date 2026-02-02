"""Integration tests."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import time
import pytest
from number_matcher import NumberMatcher
from gpio_handler import GPIOHandler
from sip_handler import SIPHandler


class TestIntegration:
    """Integration tests for the SIP client."""
    
    def test_full_valid_call_flow(self):
        """Test complete flow for a valid call."""
        # Setup
        matcher = NumberMatcher()
        matcher.load_patterns(["44*"])
        
        gpio_activated = []
        
        def on_gpio(caller):
            gpio_activated.append(caller)
        
        gpio = GPIOHandler(pin=17, active_duration=0.1, mock_mode=True)
        
        sip = SIPHandler(
            server="test",
            username="test",
            password="test",
            answer_delay=0.1,
            hangup_delay=0.1,
            check_number=matcher.is_match,
            on_valid_call=on_gpio,
            mock_mode=True
        )
        
        # Run
        sip.start()
        sip.simulate_call("+441234567890")
        time.sleep(0.5)
        sip.stop()
        
        # Verify
        assert len(gpio_activated) == 1
        assert "+441234567890" in gpio_activated[0] or "441234567890" in gpio_activated[0]
        
        stats = sip.get_stats()
        assert stats['total_calls'] == 1
        assert stats['valid_calls'] == 1
    
    def test_full_invalid_call_flow(self):
        """Test complete flow for an invalid call."""
        # Setup
        matcher = NumberMatcher()
        matcher.load_patterns(["44*"])  # Only UK
        
        gpio_activated = []
        
        def on_gpio(caller):
            gpio_activated.append(caller)
        
        sip = SIPHandler(
            server="test",
            username="test",
            password="test",
            answer_delay=0.1,
            hangup_delay=0.1,
            check_number=matcher.is_match,
            on_valid_call=on_gpio,
            mock_mode=True
        )
        
        # Run
        sip.start()
        sip.simulate_call("+33123456789")  # French number
        time.sleep(0.5)
        sip.stop()
        
        # Verify - GPIO should NOT activate
        assert len(gpio_activated) == 0
        
        stats = sip.get_stats()
        assert stats['total_calls'] == 1
        assert stats['valid_calls'] == 0


def main():
    pytest.main([__file__, "-v"])


if __name__ == "__main__":
    main()