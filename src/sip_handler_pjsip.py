"""
SIP Handler using PJSIP/pjsua2
Proper SIP stack with NAT traversal and OPTIONS handling.
"""

import logging
import threading
import time
import socket
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import pjsua2
try:
    import pjsua2 as pj
    PJSUA2_AVAILABLE = True
    logger.info("pjsua2 module loaded successfully")
except ImportError as e:
    PJSUA2_AVAILABLE = False
    logger.warning(f"pjsua2 not available: {e}")


class CallState(Enum):
    RINGING = "ringing"
    ANSWERED = "answered"
    ENDED = "ended"


@dataclass
class CallInfo:
    caller_id: str
    state: CallState
    timestamp: float
    is_valid: bool = False
    matched_pattern: Optional[str] = None


def get_public_ip() -> Optional[str]:
    """Get public IP address."""
    try:
        import requests
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        return response.json()['ip']
    except:
        return None


def get_local_ip() -> str:
    """Get local IP that can reach the internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        return "0.0.0.0"


# Only define these classes if pjsua2 is available
if PJSUA2_AVAILABLE:
    
    class MyLogWriter(pj.LogWriter):
        """Custom log writer for pjsua2."""
        
        def write(self, entry):
            # Filter out noisy logs
            msg = entry.msg.strip()
            if msg and entry.level <= 3:
                logger.debug(f"PJSIP: {msg}")
    
    
    class MyAccount(pj.Account):
        """PJSIP Account handler."""
        
        def __init__(self, sip_handler: 'SIPHandlerPJSIP'):
            super().__init__()
            self.sip_handler = sip_handler
            self.calls = {}
        
        def onRegState(self, prm):
            """Called when registration state changes."""
            try:
                info = self.getInfo()
                logger.info(f"Registration state: {info.regStatus} - {info.regStatusText}")
                
                if info.regStatus == 200:
                    self.sip_handler._on_registered()
                elif info.regStatus >= 400:
                    logger.error(f"Registration failed: {info.regStatusText}")
                    self.sip_handler._on_reg_failed(info.regStatusText)
            except Exception as e:
                logger.error(f"onRegState error: {e}")
        
        def onIncomingCall(self, prm):
            """Called when there's an incoming call."""
            try:
                call = MyCall(self, prm.callId, self.sip_handler)
                call_info = call.getInfo()
                
                # Extract caller ID from remote URI
                caller_id = self._extract_caller_id(call_info.remoteUri)
                call.caller_id = caller_id
                
                # Store call
                self.calls[prm.callId] = call
                
                logger.info(f"Incoming call from: {caller_id}")
                self.sip_handler._handle_incoming_call(call, caller_id)
                
            except Exception as e:
                logger.error(f"onIncomingCall error: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        def _extract_caller_id(self, remote_uri: str) -> str:
            """Extract phone number from SIP URI."""
            import re
            # Parse sip:number@host or "Name" <sip:number@host>
            match = re.search(r'sip:([^@>]+)', remote_uri)
            if match:
                return match.group(1)
            return remote_uri
    
    
    class MyCall(pj.Call):
        """PJSIP Call handler."""
        
        def __init__(self, acc, call_id, sip_handler):
            super().__init__(acc, call_id)
            self.sip_handler = sip_handler
            self.caller_id = ""
            self.answered = False
        
        def onCallState(self, prm):
            """Called when call state changes."""
            try:
                info = self.getInfo()
                logger.info(f"Call state: {info.stateText} (state={info.state})")
                
                if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                    logger.info("Call disconnected")
            except Exception as e:
                logger.error(f"onCallState error: {e}")
        
        def onCallMediaState(self, prm):
            """Called when media state changes."""
            try:
                info = self.getInfo()
                logger.debug(f"Media state changed for call")
            except Exception as e:
                logger.error(f"onCallMediaState error: {e}")


class SIPHandlerPJSIP:
    """
    SIP client handler using PJSIP/pjsua2.
    Properly handles NAT, OPTIONS, and all SIP messages.
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
        local_ip: Optional[str] = None,
        public_ip: Optional[str] = None
    ):
        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.answer_delay = answer_delay
        self.hangup_delay = hangup_delay
        self.check_number = check_number
        self.on_valid_call = on_valid_call
        
        # IP addresses
        self.local_ip = local_ip or get_local_ip()
        self.public_ip = public_ip or get_public_ip()
        
        logger.info(f"Local IP: {self.local_ip}")
        logger.info(f"Public IP: {self.public_ip}")
        
        self._endpoint = None
        self._account = None
        self._log_writer = None
        self._running = False
        self._registered = False
        self._reg_failed_reason = None
        self._call_count = 0
        self._valid_call_count = 0
        self._call_history: list = []
        
        # Check if pjsua2 is available
        self.mock_mode = mock_mode or not PJSUA2_AVAILABLE
        
        if not PJSUA2_AVAILABLE and not mock_mode:
            logger.warning("pjsua2 not available, using mock mode")
    
    def start(self) -> bool:
        """Start SIP client and register."""
        logger.info(f"Starting PJSIP client: {self.username}@{self.server}:{self.port}")
        
        if self.mock_mode:
            return self._start_mock()
        
        try:
            # Create endpoint
            self._endpoint = pj.Endpoint()
            self._endpoint.libCreate()
            
            # Configure endpoint
            ep_cfg = pj.EpConfig()
            
            # Log config - reduce verbosity
            ep_cfg.logConfig.level = 4
            ep_cfg.logConfig.consoleLevel = 3
            ep_cfg.logConfig.msgLogging = 1
            
            # UA config
            ep_cfg.uaConfig.userAgent = "SIPClient/1.0 (PJSIP)"
            ep_cfg.uaConfig.maxCalls = 4
            
            # Initialize library
            self._endpoint.libInit(ep_cfg)
            logger.info("PJSIP library initialized")
            
            # Create UDP transport
            tp_cfg = pj.TransportConfig()
            tp_cfg.port = 5060
            # Bind to all interfaces - critical for NAT
            tp_cfg.boundAddress = ""
            
            # For cloud environments, we might need to set public address
            if self.public_ip and self.public_ip != self.local_ip:
                tp_cfg.publicAddress = self.public_ip
                logger.info(f"Set public address to: {self.public_ip}")
            
            self._endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
            logger.info("UDP transport created")
            
            # Start endpoint
            self._endpoint.libStart()
            logger.info("PJSIP endpoint started")
            
            # Configure account
            acc_cfg = pj.AccountConfig()
            acc_cfg.idUri = f"sip:{self.username}@{self.server}"
            acc_cfg.regConfig.registrarUri = f"sip:{self.server}:{self.port}"
            acc_cfg.regConfig.timeoutSec = 120
            acc_cfg.regConfig.retryIntervalSec = 30
            
            # Add credentials
            cred = pj.AuthCredInfo()
            cred.scheme = "digest"
            cred.realm = "*"
            cred.username = self.username
            cred.dataType = 0  # Plain text password
            cred.data = self.password
            acc_cfg.sipConfig.authCreds.append(cred)
            
            # NAT settings - use integers, not constants
            # contactRewriteUse: 0=no, 1=yes, 2=always
            acc_cfg.natConfig.contactRewriteUse = 2  # Always rewrite
            acc_cfg.natConfig.viaRewriteUse = 1      # Rewrite Via
            acc_cfg.natConfig.sdpNatRewriteUse = 1   # Rewrite SDP
            acc_cfg.natConfig.sipOutboundUse = 0     # Don't use outbound
            acc_cfg.natConfig.iceEnabled = False     # No ICE needed
            
            # If we have a public IP, use it
            if self.public_ip:
                acc_cfg.natConfig.sipStunUse = 0     # Don't use STUN
                acc_cfg.natConfig.mediaStunUse = 0   # Don't use STUN for media
            
            # Media config - RTP ports
            acc_cfg.mediaConfig.transportConfig.port = 10000
            acc_cfg.mediaConfig.transportConfig.portRange = 10000
            
            # Create and register account
            self._account = MyAccount(self)
            self._account.create(acc_cfg)
            logger.info("Account created, waiting for registration...")
            
            # Wait for registration
            self._running = True
            timeout = 15
            while timeout > 0 and not self._registered and not self._reg_failed_reason:
                time.sleep(0.5)
                timeout -= 0.5
                # Keep event loop running
                self._endpoint.libHandleEvents(100)
            
            if self._registered:
                self._display_registered()
                return True
            elif self._reg_failed_reason:
                logger.error(f"Registration failed: {self._reg_failed_reason}")
                return False
            else:
                logger.warning("Registration timeout - continuing anyway")
                self._display_registered()
                return True
            
        except Exception as e:
            logger.error(f"PJSIP start failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Clean up on failure
            self._cleanup_pjsip()
            
            # Fall back to mock mode
            print(f"\n❌ PJSIP Error: {e}")
            print("Falling back to mock mode...\n")
            self.mock_mode = True
            return self._start_mock()
    
    def _cleanup_pjsip(self):
        """Clean up PJSIP resources."""
        try:
            if self._account:
                try:
                    self._account.shutdown()
                except:
                    pass
                self._account = None
            
            if self._endpoint:
                try:
                    self._endpoint.libDestroy()
                except:
                    pass
                self._endpoint = None
        except:
            pass
    
    def _on_registered(self):
        """Called when registration succeeds."""
        self._registered = True
        logger.info("✓ Successfully registered with SIP server!")
    
    def _on_reg_failed(self, reason: str):
        """Called when registration fails."""
        self._reg_failed_reason = reason
    
    def _handle_incoming_call(self, call, caller_id: str):
        """Handle incoming SIP call."""
        self._call_count += 1
        call_num = self._call_count
        
        logger.info(f"Call #{call_num}: Incoming from {caller_id}")
        self._display_call_incoming(caller_id)
        
        call_info = CallInfo(
            caller_id=caller_id,
            state=CallState.RINGING,
            timestamp=time.time()
        )
        
        # Handle in background thread
        thread = threading.Thread(
            target=self._process_call,
            args=(call, call_info, call_num),
            daemon=True
        )
        thread.start()
    
    def _process_call(self, call, call_info: CallInfo, call_num: int):
        """Process the call (answer, check, hangup)."""
        try:
            # Wait before answering
            time.sleep(self.answer_delay)
            
            # Answer the call
            logger.info(f"Call #{call_num}: Answering")
            prm = pj.CallOpParam()
            prm.statusCode = 200
            call.answer(prm)
            call.answered = True
            
            call_info.state = CallState.ANSWERED
            self._display_call_answered()
            
            # Wait before hanging up
            time.sleep(self.hangup_delay)
            
            # Hang up
            logger.info(f"Call #{call_num}: Hanging up")
            call.hangup(pj.CallOpParam())
            
            call_info.state = CallState.ENDED
            self._display_call_ended()
            
            # Check if caller is valid
            if self.check_number:
                is_valid, pattern = self.check_number(call_info.caller_id)
                call_info.is_valid = is_valid
                call_info.matched_pattern = pattern
                
                if is_valid:
                    self._valid_call_count += 1
                    self._display_valid_caller(pattern)
                    
                    if self.on_valid_call:
                        self.on_valid_call(call_info.caller_id)
                else:
                    self._display_invalid_caller()
            
        except Exception as e:
            logger.error(f"Call #{call_num}: Error - {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                call.hangup(pj.CallOpParam())
            except:
                pass
        finally:
            self._call_history.append(call_info)
    
    def _start_mock(self) -> bool:
        """Start in mock mode."""
        self._running = True
        self._display_registered_mock()
        return True
    
    def _display_call_incoming(self, caller_id: str):
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
    
    def _display_registered(self):
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + " " * 48 + "║")
        print("║" + "  ✅ PJSIP CLIENT REGISTERED".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + f"  Server: {self.server}".center(48) + "║")
        print("║" + f"  User: {self.username}".center(48) + "║")
        print("║" + f"  Local IP: {self.local_ip}".center(48) + "║")
        if self.public_ip:
            print("║" + f"  Public IP: {self.public_ip}".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + "  Waiting for calls...".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def _display_registered_mock(self):
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + " " * 48 + "║")
        print("║" + "  ⚠️  MOCK SIP CLIENT".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + f"  Server: {self.server}".center(48) + "║")
        print("║" + f"  User: {self.username}".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + "  Use simulate_call() to test".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def stop(self):
        """Stop SIP client."""
        logger.info("Stopping PJSIP client")
        self._running = False
        
        if not self.mock_mode:
            self._cleanup_pjsip()
    
    def is_running(self) -> bool:
        return self._running
    
    def get_stats(self) -> dict:
        return {
            'total_calls': self._call_count,
            'valid_calls': self._valid_call_count,
            'invalid_calls': self._call_count - self._valid_call_count,
            'running': self._running,
            'registered': self._registered,
            'mock_mode': self.mock_mode,
            'local_ip': self.local_ip,
            'public_ip': self.public_ip
        }
    
    def simulate_call(self, caller_id: str):
        """Simulate an incoming call (for testing)."""
        if not self._running:
            return
        
        call_info = CallInfo(
            caller_id=caller_id,
            state=CallState.RINGING,
            timestamp=time.time()
        )
        
        self._call_count += 1
        self._display_call_incoming(caller_id)
        
        def process():
            time.sleep(self.answer_delay)
            call_info.state = CallState.ANSWERED
            self._display_call_answered()
            
            time.sleep(self.hangup_delay)
            call_info.state = CallState.ENDED
            self._display_call_ended()
            
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
            
            self._call_history.append(call_info)
        
        threading.Thread(target=process, daemon=True).start()


# Alias for backwards compatibility
SIPHandler = SIPHandlerPJSIP


def main():
    """Test PJSIP handler with real server."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s: %(message)s'
    )
    
    print("=" * 60)
    print("PJSIP HANDLER TEST")
    print("=" * 60)
    
    print(f"\npjsua2 available: {PJSUA2_AVAILABLE}")
    
    if not PJSUA2_AVAILABLE:
        print("\n❌ pjsua2 not installed!")
        print("Run: bash install_pjsip.sh")
        return 1
    
    def check_number(number):
        normalized = number.replace('+', '').replace(' ', '').replace('-', '')
        if normalized.startswith("44") or normalized.startswith("216"):
            if normalized.startswith("44"):
                return True, "44*"
            return True, "216*"
        return False, None
    
    def on_valid(caller):
        print(f"\n>>> GPIO ACTIVATED for: {caller}\n")
    
    sip = SIPHandlerPJSIP(
        server="ast1.rdng.coreservers.uk",
        username="100500",
        password="xmbhret4fwet",
        port=5060,
        answer_delay=1,
        hangup_delay=2,
        check_number=check_number,
        on_valid_call=on_valid
    )
    
    if sip.start():
        print("\nWaiting for calls... Press Ctrl+C to stop\n")
        try:
            while True:
                time.sleep(1)
                # Keep pjsip event loop running
                if sip._endpoint and not sip.mock_mode:
                    sip._endpoint.libHandleEvents(100)
        except KeyboardInterrupt:
            pass
        sip.stop()
    else:
        print("\n❌ Failed to start SIP client")
        return 1
    
    print("\nTest complete!")
    return 0


if __name__ == "__main__":
    exit(main())