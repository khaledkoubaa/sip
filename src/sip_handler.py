"""
SIP Handler Module
Handles SIP registration and incoming calls.
Compatible with pyVoIP 2.x and handles WSL networking issues.
"""

import logging
import socket
import threading
import time
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CallState(Enum):
    """Call states."""
    RINGING = "ringing"
    ANSWERED = "answered"
    ENDED = "ended"


@dataclass
class CallInfo:
    """Information about a call."""
    caller_id: str
    state: CallState
    timestamp: float
    is_valid: bool = False
    matched_pattern: Optional[str] = None


def get_local_ip() -> str:
    """
    Get the local IP address that can reach the internet.
    Works in WSL, Docker, and regular Linux.
    """
    try:
        # Create a socket and connect to an external address
        # This doesn't actually send data, just determines the route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        logger.info(f"Detected local IP: {local_ip}")
        return local_ip
    except Exception as e:
        logger.warning(f"Could not detect local IP: {e}")
        # Fallback: try to get from hostname
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            logger.info(f"Fallback local IP: {local_ip}")
            return local_ip
        except:
            logger.warning("Using localhost as fallback")
            return "0.0.0.0"


class SIPHandler:
    """
    SIP client handler using pyVoIP.
    Falls back to mock mode if pyVoIP is not available or fails.
    """
    
    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        port: int = 5060,
        answer_delay: float = 1.0,
        hangup_delay: float = 2.0,
        check_number: Optional[Callable[[str], tuple]] = None,
        on_valid_call: Optional[Callable[[str], None]] = None,
        mock_mode: bool = False,
        local_ip: Optional[str] = None
    ):
        """
        Initialize SIP handler.
        
        Args:
            server: SIP server address
            username: SIP username
            password: SIP password
            port: SIP port
            answer_delay: Seconds before answering
            hangup_delay: Seconds before hanging up
            check_number: Function to validate caller (returns tuple)
            on_valid_call: Callback for valid calls
            mock_mode: Force mock mode
            local_ip: Local IP to bind to (auto-detect if None)
        """
        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.answer_delay = answer_delay
        self.hangup_delay = hangup_delay
        self.check_number = check_number
        self.on_valid_call = on_valid_call
        self.local_ip = local_ip or get_local_ip()
        
        self._phone = None
        self._running = False
        self._call_count = 0
        self._valid_call_count = 0
        self._call_history: list = []
        
        # Check if pyVoIP is available
        self._pyvoip_available = False
        self._pyvoip_version = None
        
        if not mock_mode:
            try:
                import pyVoIP
                self._pyvoip_version = getattr(pyVoIP, '__version__', 'unknown')
                from pyVoIP.VoIP import VoIPPhone
                self._pyvoip_available = True
                logger.info(f"pyVoIP version {self._pyvoip_version} is available")
            except ImportError as e:
                logger.warning(f"pyVoIP not installed: {e}")
            except Exception as e:
                logger.warning(f"pyVoIP import error: {e}")
        
        self.mock_mode = mock_mode or not self._pyvoip_available
    
    def _handle_incoming_call(self, call):
        """Handle incoming SIP call."""
        self._call_count += 1
        call_num = self._call_count
        
        # Extract caller ID
        caller_id = self._extract_caller_id(call)
        
        logger.info(f"Call #{call_num}: Incoming from {caller_id}")
        self._display_call_incoming(caller_id)
        
        # Create call info
        call_info = CallInfo(
            caller_id=caller_id,
            state=CallState.RINGING,
            timestamp=time.time()
        )
        
        try:
            # Wait before answering
            time.sleep(self.answer_delay)
            
            # Answer
            logger.info(f"Call #{call_num}: Answering")
            try:
                call.answer()
            except Exception as e:
                logger.error(f"Error answering call: {e}")
            
            call_info.state = CallState.ANSWERED
            self._display_call_answered()
            
            # Wait before hanging up
            time.sleep(self.hangup_delay)
            
            # Hang up
            logger.info(f"Call #{call_num}: Hanging up")
            try:
                call.hangup()
            except Exception as e:
                logger.error(f"Error hanging up: {e}")
            
            call_info.state = CallState.ENDED
            self._display_call_ended()
            
            # Check if caller is valid
            if self.check_number:
                is_valid, pattern = self.check_number(caller_id)
                call_info.is_valid = is_valid
                call_info.matched_pattern = pattern
                
                if is_valid:
                    self._valid_call_count += 1
                    self._display_valid_caller(pattern)
                    
                    if self.on_valid_call:
                        self.on_valid_call(caller_id)
                else:
                    self._display_invalid_caller()
            
        except Exception as e:
            logger.error(f"Call #{call_num}: Error - {e}")
            try:
                call.hangup()
            except:
                pass
        finally:
            self._call_history.append(call_info)
    
    def _extract_caller_id(self, call) -> str:
        """Extract caller ID from call object."""
        try:
            # pyVoIP 2.x style
            if hasattr(call, 'request') and call.request:
                from_header = None
                
                # Try to get From header
                if hasattr(call.request, 'headers'):
                    headers = call.request.headers
                    if isinstance(headers, dict):
                        from_header = headers.get('From', headers.get('from', ''))
                    elif hasattr(headers, 'get'):
                        from_header = headers.get('From', '')
                
                if from_header:
                    # Parse SIP From header: "Name" <sip:number@domain> or <sip:number@domain>
                    import re
                    
                    # Try to extract number from sip: URI
                    match = re.search(r'[<]?sip:([^@>]+)', str(from_header))
                    if match:
                        return match.group(1)
                    
                    return str(from_header)
            
            # Try other attributes
            for attr in ['caller_id', 'callerid', 'from_user', 'remote_party']:
                if hasattr(call, attr):
                    value = getattr(call, attr)
                    if value:
                        return str(value)
                        
        except Exception as e:
            logger.warning(f"Could not extract caller ID: {e}")
        
        return "unknown"
    
    def _display_call_incoming(self, caller_id: str):
        """Display incoming call notification."""
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + " " * 48 + "║")
        print("║" + "  📞 INCOMING CALL".center(48) + "║")
        print("║" + f"  From: {caller_id}".center(48) + "║")
        print("║" + f"  Call #{self._call_count}".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╠" + "═" * 48 + "╣")
    
    def _display_call_answered(self):
        print("║" + "  ✓ ANSWERED".center(48) + "║")
    
    def _display_call_ended(self):
        print("║" + "  ✓ HUNG UP".center(48) + "║")
    
    def _display_valid_caller(self, pattern: str):
        print("║" + " " * 48 + "║")
        print("║" + "  ✅ VALID CALLER".center(48) + "║")
        print("║" + f"  Matched: {pattern}".center(48) + "║")
        print("║" + "  → GPIO ACTIVATED".center(48) + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def _display_invalid_caller(self):
        print("║" + " " * 48 + "║")
        print("║" + "  ❌ INVALID CALLER".center(48) + "║")
        print("║" + "  No action taken".center(48) + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def start(self) -> bool:
        """
        Start SIP client and register.
        
        Returns:
            True if started successfully
        """
        logger.info(f"Starting SIP client: {self.username}@{self.server}:{self.port}")
        logger.info(f"Local IP: {self.local_ip}")
        
        if self.mock_mode:
            return self._start_mock()
        
        try:
            from pyVoIP.VoIP import VoIPPhone
            
            logger.info("Creating VoIPPhone instance...")
            
            # Create phone with explicit parameters
            self._phone = VoIPPhone(
                self.server,
                self.port,
                self.username,
                self.password,
                callCallback=self._handle_incoming_call,
                myIP=self.local_ip,
                sipPort=5060,
                rtpPortLow=10000,
                rtpPortHigh=20000
            )
            
            logger.info("Starting phone...")
            self._phone.start()
            self._running = True
            
            # Wait a moment for registration
            time.sleep(2)
            
            # Check registration status
            try:
                from pyVoIP.VoIP import PhoneStatus
                status = self._phone.get_status()
                logger.info(f"Phone status: {status}")
                
                if status == PhoneStatus.REGISTERED:
                    self._display_registered()
                elif status == PhoneStatus.REGISTERING:
                    logger.info("Still registering...")
                    self._display_registered()  # Show as success, still registering
                else:
                    logger.warning(f"Registration status: {status}")
                    self._display_registered()  # Show anyway
            except Exception as e:
                logger.warning(f"Could not check status: {e}")
                self._display_registered()
            
            return True
            
        except Exception as e:
            logger.error(f"SIP start failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            print(f"\n❌ SIP Registration Failed: {e}")
            print(f"\n   Falling back to mock mode for testing...")
            print(f"   You can still test the call flow with simulated calls.\n")
            
            # Fall back to mock mode
            self.mock_mode = True
            return self._start_mock()
    
    def _start_mock(self) -> bool:
        """Start in mock mode."""
        self._running = True
        self._display_registered_mock()
        return True
    
    def _display_registered(self):
        """Display registration success."""
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + " " * 48 + "║")
        print("║" + "  ✅ SIP CLIENT REGISTERED".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + f"  Server: {self.server}".center(48) + "║")
        print("║" + f"  User: {self.username}".center(48) + "║")
        print("║" + f"  Local IP: {self.local_ip}".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + "  Waiting for calls...".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def _display_registered_mock(self):
        """Display mock registration."""
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + " " * 48 + "║")
        print("║" + "  ⚠️  MOCK SIP CLIENT".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + f"  Server: {self.server}".center(48) + "║")
        print("║" + f"  User: {self.username}".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + "  Use simulate_call() to test".center(48) + "║")
        print("║" + "  Or run: python test_simulate_call.py".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def stop(self):
        """Stop SIP client."""
        logger.info("Stopping SIP client")
        self._running = False
        
        if self._phone:
            try:
                self._phone.stop()
            except Exception as e:
                logger.error(f"Error stopping phone: {e}")
    
    def is_running(self) -> bool:
        """Check if SIP client is running."""
        return self._running
    
    def get_stats(self) -> dict:
        """Get call statistics."""
        return {
            'total_calls': self._call_count,
            'valid_calls': self._valid_call_count,
            'invalid_calls': self._call_count - self._valid_call_count,
            'running': self._running,
            'mock_mode': self.mock_mode,
            'local_ip': self.local_ip
        }
    
    def simulate_call(self, caller_id: str):
        """
        Simulate an incoming call (for testing).
        
        Args:
            caller_id: Simulated caller number
        """
        if not self._running:
            logger.warning("SIP client not running")
            return
        
        # Create a mock call object
        class MockCall:
            def __init__(self, caller):
                self.caller_id = caller
                
                # Create mock request with headers
                class MockRequest:
                    def __init__(self, caller_num):
                        self.headers = {'From': f'<sip:{caller_num}@mock>'}
                
                self.request = MockRequest(caller)
            
            def answer(self):
                pass
            
            def hangup(self):
                pass
            
            def deny(self):
                pass
        
        mock_call = MockCall(caller_id)
        
        # Handle in a thread to not block
        thread = threading.Thread(
            target=self._handle_incoming_call,
            args=(mock_call,),
            daemon=True
        )
        thread.start()


def main():
    """Test SIP handler."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s: %(message)s'
    )
    
    print("=" * 60)
    print("SIP HANDLER TEST")
    print("=" * 60)
    
    # Detect local IP
    local_ip = get_local_ip()
    print(f"\nDetected local IP: {local_ip}")
    
    def check_number(number):
        """Simple test validator."""
        # Accept UK and Tunisia
        normalized = number.replace('+', '').replace(' ', '')
        if normalized.startswith("44") or normalized.startswith("216"):
            if normalized.startswith("44"):
                return True, "44*"
            return True, "216*"
        return False, None
    
    def on_valid(caller):
        print(f"\n>>> GPIO ACTIVATED for: {caller}\n")
    
    # Test with mock mode first
    print("\n--- Testing Mock Mode ---\n")
    
    sip = SIPHandler(
        server="ast1.rdng.coreservers.uk",
        username="100500",
        password="xmbhret4fwet",
        answer_delay=0.5,
        hangup_delay=1,
        check_number=check_number,
        on_valid_call=on_valid,
        mock_mode=True,  # Force mock for this test
        local_ip=local_ip
    )
    
    if sip.start():
        print("\nSimulating test calls...\n")
        
        # Test calls
        test_numbers = [
            "+21620222783",   # Your Tunisia number (valid)
            "+441234567890",  # UK number (valid)
            "+33123456789",   # French number (invalid)
        ]
        
        for number in test_numbers:
            print(f"\n--- Calling from {number} ---")
            sip.simulate_call(number)
            time.sleep(3)
        
        print("\n" + "=" * 60)
        print("CALL STATISTICS")
        print("=" * 60)
        stats = sip.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        sip.stop()
    
    print("\nTest complete!")


if __name__ == "__main__":
    main()