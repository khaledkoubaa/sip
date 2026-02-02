#!/usr/bin/env python3
"""
Test script to simulate incoming calls.
Run the main app first, then run this script in another terminal.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from number_matcher import NumberMatcher
from gpio_handler import GPIOHandler
from sip_handler import SIPHandler


def main():
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + "  CALL SIMULATION TEST".center(58) + "║")
    print("╚" + "═" * 58 + "╝")
    print()
    
    # Setup components
    matcher = NumberMatcher()
    matcher.load_patterns([
        "441234567890",
        "441234*", 
        "21620222783",
        "216*"
    ])
    
    gpio = GPIOHandler(pin=17, active_duration=3, mock_mode=True)
    
    def check_number(caller_id):
        return matcher.is_match(caller_id)
    
    def on_valid_call(caller_id):
        gpio.activate()
    
    sip = SIPHandler(
        server="ast1.rdng.coreservers.uk",
        username="100500",
        password="test",
        answer_delay=1,
        hangup_delay=2,
        check_number=check_number,
        on_valid_call=on_valid_call,
        mock_mode=True  # Always mock for simulation
    )
    
    sip.start()
    
    print("\nTest Scenarios:")
    print("1. Your Tunisia number (+21620222783) - Should ACTIVATE GPIO")
    print("2. UK number (+441234567890) - Should ACTIVATE GPIO")
    print("3. French number (+33123456789) - Should NOT activate GPIO")
    print()
    
    test_cases = [
        ("+21620222783", "Your Tunisia mobile"),
        ("+441234567890", "UK number (exact match)"),
        ("+441234999999", "UK number (wildcard match)"),
        ("+447700900123", "UK mobile"),
        ("+33123456789", "French number (should reject)"),
    ]
    
    for number, description in test_cases:
        print(f"\n{'='*60}")
        print(f"TEST: {description}")
        print(f"Number: {number}")
        print('='*60)
        
        sip.simulate_call(number)
        time.sleep(5)  # Wait for call to complete + GPIO
    
    print("\n" + "="*60)
    print("FINAL STATISTICS")
    print("="*60)
    stats = sip.get_stats()
    print(f"  Total calls: {stats['total_calls']}")
    print(f"  Valid calls (GPIO activated): {stats['valid_calls']}")
    print(f"  Invalid calls (rejected): {stats['invalid_calls']}")
    print(f"  GPIO activations: {gpio.get_activation_count()}")
    print()
    
    sip.stop()
    gpio.cleanup()


if __name__ == "__main__":
    main()