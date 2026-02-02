#!/usr/bin/env python3
"""
SIP Client for Raspberry Pi
Main application entry point.
"""

import configparser
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Add src to path if running directly
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))

from number_matcher import NumberMatcher
from gpio_handler import GPIOHandler
from api_client import APIClient
from sip_handler import SIPHandler


class SIPClientApp:
    """Main application class."""
    
    def __init__(self, config_path: str = "config.ini"):
        self.config_path = config_path
        self.config = None
        self.logger = None
        
        self.number_matcher = None
        self.gpio_handler = None
        self.api_client = None
        self.sip_handler = None
        
        self._shutdown = False
    
    def setup_logging(self):
        """Configure logging."""
        level = self.config.get('LOGGING', 'level', fallback='INFO')
        log_file = self.config.get('LOGGING', 'file', fallback='')
        
        handlers = [logging.StreamHandler()]
        if log_file:
            try:
                handlers.append(logging.FileHandler(log_file))
            except Exception as e:
                print(f"Warning: Could not create log file: {e}")
        
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
        
        self.logger = logging.getLogger(__name__)
    
    def load_config(self) -> bool:
        """Load configuration file."""
        self.config = configparser.ConfigParser()
        
        # Check multiple locations
        paths = [
            self.config_path,
            Path(__file__).parent.parent / "config.ini",
            Path.home() / ".sip-client" / "config.ini",
        ]
        
        for path in paths:
            if Path(path).exists():
                self.config.read(path)
                print(f"Loaded config from: {path}")
                return True
        
        # Create default config
        print(f"Config not found, using defaults")
        self._set_default_config()
        return True
    
    def _set_default_config(self):
        """Set default configuration."""
        self.config['SIP'] = {
            'server': 'localhost',
            'username': 'test',
            'password': 'test',
            'port': '5060',
            'answer_delay_seconds': '1',
            'hangup_delay_seconds': '2'
        }
        self.config['API'] = {
            'url': 'http://localhost:5000/numbers',
            'auth_token': '',
            'refresh_interval_seconds': '3600'
        }
        self.config['GPIO'] = {
            'pin': '17',
            'active_duration_seconds': '5',
            'mode': 'mock'
        }
        self.config['CACHE'] = {
            'cache_file': '/tmp/valid_numbers_cache.json',
            'use_cache_on_api_failure': 'true'
        }
        self.config['LOGGING'] = {
            'level': 'INFO',
            'file': ''
        }
    
    def initialize_components(self):
        """Initialize all components."""
        self.logger.info("Initializing components...")
        
        # Number Matcher
        self.number_matcher = NumberMatcher()
        
        # GPIO Handler
        gpio_pin = self.config.getint('GPIO', 'pin', fallback=17)
        gpio_duration = self.config.getfloat('GPIO', 'active_duration_seconds', fallback=5)
        gpio_mode = self.config.get('GPIO', 'mode', fallback='mock')
        
        self.gpio_handler = GPIOHandler(
            pin=gpio_pin,
            active_duration=gpio_duration,
            mock_mode=(gpio_mode.lower() == 'mock')
        )
        
        # API Client
        self.api_client = APIClient(
            api_url=self.config.get('API', 'url', fallback='http://localhost:5000/numbers'),
            auth_token=self.config.get('API', 'auth_token', fallback=''),
            auth_header_name=self.config.get('API', 'auth_header_name', fallback='api_token'),
            http_method=self.config.get('API', 'http_method', fallback='POST'),
            response_data_key=self.config.get('API', 'response_data_key', fallback='data'),
            refresh_interval=self.config.getint('API', 'refresh_interval_seconds', fallback=3600),
            cache_file=self.config.get('CACHE', 'cache_file', fallback='/tmp/valid_numbers_cache.json'),
            use_cache_on_failure=self.config.getboolean('CACHE', 'use_cache_on_api_failure', fallback=True),
            on_update=self._on_numbers_updated
        )
        # SIP Handler
        mock_sip = '--mock-sip' in sys.argv
        
        self.sip_handler = SIPHandler(
            server=self.config.get('SIP', 'server', fallback='localhost'),
            username=self.config.get('SIP', 'username', fallback='test'),
            password=self.config.get('SIP', 'password', fallback='test'),
            port=self.config.getint('SIP', 'port', fallback=5060),
            answer_delay=self.config.getfloat('SIP', 'answer_delay_seconds', fallback=1),
            hangup_delay=self.config.getfloat('SIP', 'hangup_delay_seconds', fallback=2),
            check_number=self._check_number,
            on_valid_call=self._on_valid_call,
            mock_mode=mock_sip
        )
    
    def _on_numbers_updated(self, numbers):
        """Callback when phone numbers are updated."""
        self.number_matcher.load_patterns(numbers)
        self.logger.info(f"Updated number patterns: {len(numbers)}")
    
    def _check_number(self, caller_id: str) -> tuple:
        """Check if caller number is valid."""
        return self.number_matcher.is_match(caller_id)
    
    def _on_valid_call(self, caller_id: str):
        """Callback for valid calls."""
        self.logger.info(f"Valid call from {caller_id}, activating GPIO")
        self.gpio_handler.activate()
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\n\nShutdown requested...")
        self._shutdown = True
    
    def run(self) -> int:
        """
        Run the application.
        
        Returns:
            Exit code
        """
        # Load config
        if not self.load_config():
            return 1
        
        # Setup logging
        self.setup_logging()
        
        # Display banner
        self._display_banner()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Initialize components
        self.initialize_components()
        
        # Start API client
        self.logger.info("Starting API client...")
        if not self.api_client.start():
            self.logger.warning("API client failed to fetch initial data")
        
        time.sleep(1)  # Give time for initial fetch
        
        # Show loaded patterns
        patterns = self.number_matcher.get_patterns()
        print(f"\n📋 Loaded {len(patterns)} phone patterns:")
        for p in patterns[:5]:
            print(f"   • {p}")
        if len(patterns) > 5:
            print(f"   ... and {len(patterns) - 5} more")
        print()
        
        # Start SIP client
        self.logger.info("Starting SIP client...")
        if not self.sip_handler.start():
            self.logger.error("Failed to start SIP client")
            self.api_client.stop()
            return 1
        
        # Display ready message
        self._display_ready()
        
        # Main loop
        try:
            while not self._shutdown:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        
        # Shutdown
        self._shutdown_components()
        
        return 0
    
    def _display_banner(self):
        """Display application banner."""
        print()
        print("╔" + "═" * 58 + "╗")
        print("║" + " " * 58 + "║")
        print("║" + "  SIP CLIENT FOR RASPBERRY PI".center(58) + "║")
        print("║" + "  Version 1.0.0".center(58) + "║")
        print("║" + " " * 58 + "║")
        print("╚" + "═" * 58 + "╝")
        print()
    
    def _display_ready(self):
        """Display ready message."""
        print()
        print("╔" + "═" * 58 + "╗")
        print("║" + "  ✅ SYSTEM READY".center(58) + "║")
        print("╠" + "═" * 58 + "╣")
        print("║" + "  Waiting for incoming calls...".center(58) + "║")
        print("║" + "  Press Ctrl+C to stop".center(58) + "║")
        print("╚" + "═" * 58 + "╝")
        print()
    
    def _shutdown_components(self):
        """Shutdown all components."""
        print("\nShutting down...")
        
        if self.sip_handler:
            self.sip_handler.stop()
        
        if self.api_client:
            self.api_client.stop()
        
        if self.gpio_handler:
            self.gpio_handler.cleanup()
        
        print("Goodbye! 👋")


def main():
    """Entry point."""
    # Parse arguments
    config_path = "config.ini"
    
    for arg in sys.argv[1:]:
        if arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]
        elif arg == "--help":
            print("Usage: python main.py [options]")
            print()
            print("Options:")
            print("  --config=PATH   Path to config file")
            print("  --mock-sip      Use mock SIP (no real registration)")
            print("  --help          Show this help")
            return 0
    
    # Run app
    app = SIPClientApp(config_path)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())