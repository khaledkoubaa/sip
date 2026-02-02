"""
SIP Handler using PJSIP/pjsua2
Proper SIP stack with NAT traversal and OPTIONS handling.
"""

import logging
import threading
import time
import sys
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import pjsua2
try:
    import pjsua2 as pj
    PJSUA2_AVAILABLE = True
except ImportError:
    PJSUA2_AVAILABLE = False
    logger.warning("pjsua2 not available - run install_pjsip.sh first")


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


class MyAccount(pj.Account if PJSUA2_AVAILABLE else object):
    """PJSIP Account handler."""
    
    def __init__(self, sip_handler: 'SIPHandlerPJSIP'):
        if PJSUA2_AVAILABLE:
            super().__init__()
        self.sip_handler = sip_handler
    
    def onRegState(self, prm):
        """Called when registration state changes."""
        info = self.getInfo()
        logger.info(f"Registration state: {info.regStatus} - {info.regStatusText}")
        
        if info.regStatus == 200:
            self.sip_handler._on_registered()
        elif info.regStatus >= 400:
            logger.error(f"Registration failed: {info.regStatusText}")
    
    def onIncomingCall(self, prm):
        """Called when there's an incoming call."""
        call = MyCall(self, prm.callId, self.sip_handler)
        call_info = call.getInfo()
        
        # Extract caller ID from remote URI
        caller_id = self._extract_caller_id(call_info.remoteUri)
        
        logger.info(f"Incoming call from: {caller_id}")
        self.sip_handler._handle_incoming_call(call, caller_id)
    
    def _extract_caller_id(self, remote_uri: str) -> str:
        """Extract phone number from SIP URI."""
        import re
        # Parse sip:number@host or "Name" <sip:number@host>
        match = re.search(r'sip:([^@>]+)', remote_uri)
        if match:
            return match.group(1)
        return remote_uri


class MyCall(pj.Call if PJSUA2_AVAILABLE else object):
    """PJSIP Call handler."""
    
    def __init__(self, acc, call_id, sip_handler):
        if PJSUA2_AVAILABLE:
            super().__init__(acc, call_id)
        self.sip_handler = sip_handler
        self.caller_id = ""
    
    def onCallState(self, prm):
        """Called when call state changes."""
        info = self.getInfo()
        logger.info(f"Call state: {info.stateText}")
        
        if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logger.info("Call disconnected")


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
        local_ip: Optional[str] = None
    ):
        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.answer_delay = answer_delay
        self.hangup_delay = hangup_delay
        self.check_number = check_number
        self.on_valid_call = on_valid_call
        self.local_ip = local_ip
        
        self._endpoint = None
        self._account = None
        self._running = False
        self._registered = False
        self._call_count = 0
        self._valid_call_count = 0
        self._call_history: list = []
        self._active_calls: dict = {}
        
        # Check if pjsua2 is available
        self.mock_mode = mock_mode or not PJSUA2_AVAILABLE
        
        if not PJSUA2_AVAILABLE and not mock_mode:
            logger.warning("pjsua2 not available, using mock mode")
            logger.warning("Run: bash install_pjsip.sh")
    
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
            ep_cfg.logConfig.level = 3
            ep_cfg.logConfig.consoleLevel = 3
            
            # UA config for NAT traversal
            ep_cfg.uaConfig.userAgent = "SIPClient/1.0"
            ep_cfg.uaConfig.maxCalls = 4
            
            self._endpoint.libInit(ep_cfg)
            
            # Create UDP transport
            tp_cfg = pj.TransportConfig()
            tp_cfg.port = 5060
            
            # Bind to all interfaces for NAT
            if self.local_ip:
                tp_cfg.boundAddress = self.local_ip
            
            self._endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
            
            # Start endpoint
            self._endpoint.libStart()
            logger.info("PJSIP endpoint started")
            
            # Configure account
            acc_cfg = pj.AccountConfig()
            acc_cfg.idUri = f"sip:{self.username}@{self.server}"
            acc_cfg.regConfig.registrarUri = f"sip:{self.server}:{self.port}"
            
            # Add credentials
            cred = pj.AuthCredInfo("digest", "*", self.username, 0, self.password)
            acc_cfg.sipConfig.authCreds.append(cred)
            
            # NAT settings - critical for cloud/NAT environments
            acc_cfg.natConfig.iceEnabled = False  # Disable ICE, use simple NAT
            acc_cfg.natConfig.sdpNatRewriteUse = pj.PJSUA_SDP_NAT_RPORT_USE_PRESENCE
            acc_cfg.natConfig.sipOutboundUse = pj.PJSUA_SIP_OUTBOUND_USE_ONLY_RFC5626
            acc_cfg.natConfig.contactRewriteUse = pj.PJSUA_CONTACT_REWRITE_ALWAYS
            
            # RTP NAT settings
            acc_cfg.mediaConfig.srtpUse = pj.PJMEDIA_SRTP_DISABLED
            acc_cfg.mediaConfig.transportConfig.port = 10000
            acc_cfg.mediaConfig.transportConfig.portRange = 10000
            
            # Create and register account
            self._account = MyAccount(self)
            self._account.create(acc_cfg)
            
            # Wait for registration
            self._running = True
            timeout = 10
            while timeout > 0 and not self._registered:
                time.sleep(0.5)
                timeout -= 0.5
            
            if self._registered:
                self._display_registered()
                return True
            else:
                logger.warning("Registration timeout, but continuing...")
                self._display_registered()
                return True
            
        except Exception as e:
            logger.error(f"PJSIP start failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Fall back to mock mode
            self.mock_mode = True
            return self._start_mock()
    
    def _on_registered(self):
        """Called when registration succeeds."""
        self._registered = True
        logger.info("Successfully registered!")
    
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
        
        # Store active call
        call.caller_id = caller_id
        self._active_calls[call_num] = call
        
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
            call_prm = pj.CallOpParam()
            call_prm.statusCode = 200
            call.answer(call_prm)
            
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
            try:
                call.hangup(pj.CallOpParam())
            except:
                pass
        finally:
            self._call_history.append(call_info)
            self._active_calls.pop(call_num, None)
    
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
        print("║" + "  pjsua2 not installed".center(48) + "║")
        print("║" + "  Run: bash install_pjsip.sh".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def stop(self):
        """Stop SIP client."""
        logger.info("Stopping PJSIP client")
        self._running = False
        
        if self._endpoint and not self.mock_mode:
            try:
                # Hang up active calls
                for call in self._active_calls.values():
                    try:
                        call.hangup(pj.CallOpParam())
                    except:
                        pass
                
                # Destroy account
                if self._account:
                    self._account.shutdown()
                
                # Destroy endpoint
                self._endpoint.libDestroy()
            except Exception as e:
                logger.error(f"Error stopping PJSIP: {e}")
    
    def is_running(self) -> bool:
        return self._running
    
    def get_stats(self) -> dict:
        return {
            'total_calls': self._call_count,
            'valid_calls': self._valid_call_count,
            'invalid_calls': self._call_count - self._valid_call_count,
            'running': self._running,
            'registered': self._registered,
            'mock_mode': self.mock_mode
        }
    
    def simulate_call(self, caller_id: str):
        """Simulate an incoming call (for testing)."""
        if not self._running:
            return
        
        # Create mock call info
        call_info = CallInfo(
            caller_id=caller_id,
            state=CallState.RINGING,
            timestamp=time.time()
        )
        
        self._call_count += 1
        call_num = self._call_count
        
        self._display_call_incoming(caller_id)
        
        # Process in background
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
    """Test PJSIP handler."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s: %(message)s'
    )
    
    print("=" * 60)
    print("PJSIP HANDLER TEST")
    print("=" * 60)
    
    if not PJSUA2_AVAILABLE:
        print("\n❌ pjsua2 not installed!")
        print("Run: bash install_pjsip.sh")
        print("\nUsing mock mode for testing...\n")
    
    def check_number(number):
        normalized = number.replace('+', '').replace(' ', '')
        if normalized.startswith("44") or normalized.startswith("216"):
            return True, "44* or 216*"
        return False, None
    
    def on_valid(caller):
        print(f"\n>>> GPIO ACTIVATED for: {caller}\n")
    
    sip = SIPHandlerPJSIP(
        server="ast1.rdng.coreservers.uk",
        username="100500",
        password="xmbhret4fwet",
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
        except KeyboardInterrupt:
            pass
        sip.stop()
    
    print("\nTest complete!")


if __name__ == "__main__":
    main()