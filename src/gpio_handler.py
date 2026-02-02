"""
GPIO Handler Module
Controls Raspberry Pi GPIO pins with mock mode for development.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class GPIOHandler:
    """Handles GPIO pin control with mock support."""
    
    def __init__(
        self,
        pin: int,
        active_duration: float,
        mock_mode: bool = True
    ):
        """
        Initialize GPIO handler.
        
        Args:
            pin: GPIO pin number (BCM numbering)
            active_duration: Seconds to keep pin active
            mock_mode: True for simulation, False for real GPIO
        """
        self.pin = pin
        self.active_duration = active_duration
        self.mock_mode = mock_mode
        
        self._device = None
        self._lock = threading.Lock()
        self._is_active = False
        self._activation_count = 0
        
        self._setup()
    
    def _setup(self):
        """Initialize GPIO or mock mode."""
        if self.mock_mode:
            logger.info(f"GPIO: Mock mode enabled (pin {self.pin})")
            return
        
        try:
            from gpiozero import LED
            self._device = LED(self.pin)
            logger.info(f"GPIO: Initialized real GPIO on pin {self.pin}")
        except ImportError:
            logger.warning("gpiozero not available, using mock mode")
            self.mock_mode = True
        except Exception as e:
            logger.error(f"GPIO init failed: {e}, using mock mode")
            self.mock_mode = True
    
    def activate(self) -> bool:
        """
        Activate GPIO pin for configured duration.
        
        Returns:
            True if activation started, False if already active
        """
        with self._lock:
            if self._is_active:
                logger.debug("GPIO already active, skipping")
                return False
            self._is_active = True
            self._activation_count += 1
        
        # Run in background thread
        thread = threading.Thread(
            target=self._activation_worker,
            name=f"GPIO-{self._activation_count}",
            daemon=True
        )
        thread.start()
        return True
    
    def _activation_worker(self):
        """Background worker for GPIO activation."""
        activation_id = self._activation_count
        
        try:
            # Activate
            logger.info(f"GPIO pin {self.pin}: ACTIVATED")
            
            if self.mock_mode:
                self._mock_display_on()
            else:
                self._device.on()
            
            # Hold for duration
            time.sleep(self.active_duration)
            
            # Deactivate
            logger.info(f"GPIO pin {self.pin}: DEACTIVATED")
            
            if self.mock_mode:
                self._mock_display_off()
            else:
                self._device.off()
                
        except Exception as e:
            logger.error(f"GPIO activation error: {e}")
        finally:
            with self._lock:
                self._is_active = False
    
    def _mock_display_on(self):
        """Display mock GPIO activation."""
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + " " * 48 + "║")
        print("║" + "  🔔 GPIO PIN {} ACTIVATED".format(self.pin).center(48) + "║")
        print("║" + "  Duration: {} seconds".format(self.active_duration).center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def _mock_display_off(self):
        """Display mock GPIO deactivation."""
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + "  🔕 GPIO PIN {} DEACTIVATED".format(self.pin).center(48) + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def is_active(self) -> bool:
        """Check if GPIO is currently active."""
        with self._lock:
            return self._is_active
    
    def get_activation_count(self) -> int:
        """Get total number of activations."""
        return self._activation_count
    
    def cleanup(self):
        """Clean up GPIO resources."""
        if self._device and not self.mock_mode:
            try:
                self._device.off()
                self._device.close()
                logger.info("GPIO cleaned up")
            except Exception as e:
                logger.error(f"GPIO cleanup error: {e}")


def main():
    """Test GPIO handler in mock mode."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)s: %(message)s'
    )
    
    print("=" * 60)
    print("GPIO HANDLER TEST (Mock Mode)")
    print("=" * 60)
    
    gpio = GPIOHandler(pin=17, active_duration=3, mock_mode=True)
    
    print("\nTest 1: Single activation")
    gpio.activate()
    time.sleep(4)
    
    print("\nTest 2: Rapid activations (should skip second)")
    gpio.activate()
    time.sleep(0.5)
    result = gpio.activate()
    print(f"Second activation returned: {result} (expected: False)")
    time.sleep(3)
    
    print(f"\nTotal activations: {gpio.get_activation_count()}")
    
    gpio.cleanup()
    print("\nTest complete!")


if __name__ == "__main__":
    main()