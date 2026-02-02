"""
SIP Handler using PJSIP/pjsua2
DEBUG VERSION - Enhanced logging for troubleshooting
"""

import logging
import threading
import time
import socket
import re
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

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
        ip = response.json()['ip']
        logger.info(f"[NET] Public IP detected: {ip}")
        return ip
    except Exception as e:
        logger.warning(f"[NET] Could not get public IP: {e}")
        return None


def get_local_ip() -> str:
    """Get local IP that can reach the internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        logger.info(f"[NET] Local IP detected: {local_ip}")
        return local_ip
    except Exception as e:
        logger.warning(f"[NET] Could not get local IP: {e}")
        return "0.0.0.0"


# Only define these classes if pjsua2 is available
if PJSUA2_AVAILABLE:
    
    class MyLogWriter(pj.LogWriter):
        """
        Custom log writer for pjsua2.
        Captures and formats PJSIP internal logs.
        """
        
        def __init__(self):
            super().__init__()
            self.sip_logger = logging.getLogger("pjsip")
        
        def write(self, entry):
            msg = entry.msg.strip()
            if not msg:
                return
            
            # Determine log level
            if entry.level <= 1:
                log_func = self.sip_logger.error
            elif entry.level == 2:
                log_func = self.sip_logger.warning
            elif entry.level == 3:
                log_func = self.sip_logger.info
            else:
                log_func = self.sip_logger.debug
            
            # Highlight SIP messages
            if "SIP/2.0" in msg or msg.startswith("INVITE") or msg.startswith("ACK") or msg.startswith("BYE"):
                # This is a SIP message - make it stand out
                self._log_sip_message(msg)
            elif "Sending" in msg or "Received" in msg:
                self.sip_logger.info(f"[PJSIP] {msg}")
            else:
                log_func(f"[PJSIP] {msg}")
        
        def _log_sip_message(self, msg: str):
            """Log SIP message with nice formatting."""
            lines = msg.split('\n')
            if not lines:
                return
            
            first_line = lines[0].strip()
            
            # Determine direction and type
            if first_line.startswith("INVITE"):
                direction = "<<< RECEIVED"
                msg_type = "INVITE"
            elif first_line.startswith("ACK"):
                direction = "<<< RECEIVED"
                msg_type = "ACK"
            elif first_line.startswith("BYE"):
                direction = "??? "
                msg_type = "BYE"
            elif first_line.startswith("CANCEL"):
                direction = "??? "
                msg_type = "CANCEL"
            elif "SIP/2.0 100" in first_line:
                direction = ">>> SENDING"
                msg_type = "100 Trying"
            elif "SIP/2.0 180" in first_line:
                direction = ">>> SENDING"
                msg_type = "180 Ringing"
            elif "SIP/2.0 183" in first_line:
                direction = ">>> SENDING"
                msg_type = "183 Session Progress"
            elif "SIP/2.0 200" in first_line:
                direction = ">>> SENDING"
                msg_type = "200 OK"
            elif "SIP/2.0 4" in first_line or "SIP/2.0 5" in first_line or "SIP/2.0 6" in first_line:
                direction = ">>> SENDING"
                msg_type = first_line.split('\r')[0]
            else:
                direction = "---"
                msg_type = first_line[:50]
            
            self.sip_logger.info(f"\n{'='*60}")
            self.sip_logger.info(f"  {direction} {msg_type}")
            self.sip_logger.info(f"{'='*60}")
            
            # Log key headers
            for line in lines[1:10]:  # First 10 header lines
                line = line.strip()
                if line and not line.startswith('v=') and not line.startswith('o='):
                    if any(h in line for h in ['From:', 'To:', 'Call-ID:', 'CSeq:', 'Contact:', 'Via:']):
                        self.sip_logger.info(f"  {line}")
            
            self.sip_logger.info(f"{'='*60}\n")
    
    
    class MyAccount(pj.Account):
        """PJSIP Account handler with enhanced logging."""
        
        def __init__(self, sip_handler: 'SIPHandlerPJSIP'):
            super().__init__()
            self.sip_handler = sip_handler
            self.calls = {}
            logger.debug("[ACCOUNT] MyAccount created")
        
        def onRegState(self, prm):
            """Called when registration state changes."""
            try:
                info = self.getInfo()
                logger.info(f"[REG] Registration state changed:")
                logger.info(f"[REG]   Status: {info.regStatus} ({info.regStatusText})")
                logger.info(f"[REG]   Expiry: {info.regExpiresSec}s")
                logger.info(f"[REG]   Online: {info.onlineStatus}")
                
                if info.regStatus == 200:
                    self.sip_handler._on_registered()
                elif info.regStatus >= 400:
                    logger.error(f"[REG] Registration FAILED: {info.regStatusText}")
                    self.sip_handler._on_reg_failed(info.regStatusText)
            except Exception as e:
                logger.error(f"[REG] onRegState error: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        def onIncomingCall(self, prm):
            """Called when there's an incoming call."""
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            logger.info(f"\n{'#'*60}")
            logger.info(f"# [{timestamp}] INCOMING CALL DETECTED")
            logger.info(f"# Call ID: {prm.callId}")
            logger.info(f"{'#'*60}")
            
            try:
                call = MyCall(self, prm.callId, self.sip_handler)
                call_info = call.getInfo()
                
                logger.info(f"[CALL] Call Info:")
                logger.info(f"[CALL]   Remote URI: {call_info.remoteUri}")
                logger.info(f"[CALL]   Remote Contact: {call_info.remoteContact}")
                logger.info(f"[CALL]   Local URI: {call_info.localUri}")
                logger.info(f"[CALL]   State: {call_info.stateText}")
                logger.info(f"[CALL]   Last Status: {call_info.lastStatusCode}")
                
                # Extract caller ID
                caller_id = self._extract_caller_id(call_info.remoteUri)
                call.caller_id = caller_id
                logger.info(f"[CALL]   Extracted Caller ID: {caller_id}")
                
                # Store call
                self.calls[prm.callId] = call
                
                # Handle call
                self.sip_handler._handle_incoming_call_sync(call, caller_id)
                
            except Exception as e:
                logger.error(f"[CALL] onIncomingCall error: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        def _extract_caller_id(self, remote_uri: str) -> str:
            """Extract phone number from SIP URI."""
            logger.debug(f"[PARSE] Extracting caller ID from: {remote_uri}")
            match = re.search(r'sip:([^@>]+)', remote_uri)
            if match:
                caller_id = match.group(1)
                logger.debug(f"[PARSE] Extracted: {caller_id}")
                return caller_id
            logger.warning(f"[PARSE] Could not extract caller ID, using raw: {remote_uri}")
            return remote_uri
    
    
    class MyCall(pj.Call):
        """PJSIP Call handler with enhanced logging."""
        
        def __init__(self, acc, call_id, sip_handler):
            super().__init__(acc, call_id)
            self.sip_handler = sip_handler
            self.caller_id = ""
            self.answered = False
            self.disconnected = False
            self.media_active = False
            self._state_history = []
            logger.debug(f"[CALL] MyCall created for call_id={call_id}")
        
        def onCallState(self, prm):
            """Called when call state changes."""
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            try:
                info = self.getInfo()
                state_name = info.stateText
                
                self._state_history.append((timestamp, state_name))
                
                logger.info(f"[CALL-STATE] [{timestamp}] State changed: {state_name} (code={info.state})")
                logger.info(f"[CALL-STATE]   Last status: {info.lastStatusCode} ({info.lastReason})")
                logger.info(f"[CALL-STATE]   Connect duration: {info.connectDuration.sec}s")
                logger.info(f"[CALL-STATE]   Total duration: {info.totalDuration.sec}s")
                
                if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                    logger.info(f"[CALL-STATE] *** CALL DISCONNECTED ***")
                    logger.info(f"[CALL-STATE] Disconnect reason: {info.lastReason}")
                    self.disconnected = True
                    
                    # Print state history
                    logger.info(f"[CALL-STATE] Call state history:")
                    for ts, state in self._state_history:
                        logger.info(f"[CALL-STATE]   {ts}: {state}")
                        
                elif info.state == pj.PJSIP_INV_STATE_CONFIRMED:
                    logger.info(f"[CALL-STATE] *** CALL CONFIRMED/CONNECTED ***")
                    
                elif info.state == pj.PJSIP_INV_STATE_EARLY:
                    logger.info(f"[CALL-STATE] *** EARLY MEDIA (180/183 sent) ***")
                    
            except Exception as e:
                logger.error(f"[CALL-STATE] onCallState error: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        def onCallMediaState(self, prm):
            """Called when media state changes."""
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            try:
                info = self.getInfo()
                logger.info(f"[MEDIA] [{timestamp}] Media state changed")
                logger.info(f"[MEDIA]   Media count: {len(info.media)}")
                
                for i, mi in enumerate(info.media):
                    type_name = "AUDIO" if mi.type == pj.PJMEDIA_TYPE_AUDIO else f"TYPE_{mi.type}"
                    
                    if mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                        status_name = "ACTIVE"
                    elif mi.status == pj.PJSUA_CALL_MEDIA_LOCAL_HOLD:
                        status_name = "LOCAL_HOLD"
                    elif mi.status == pj.PJSUA_CALL_MEDIA_REMOTE_HOLD:
                        status_name = "REMOTE_HOLD"
                    elif mi.status == pj.PJSUA_CALL_MEDIA_NONE:
                        status_name = "NONE"
                    else:
                        status_name = f"STATUS_{mi.status}"
                    
                    logger.info(f"[MEDIA]   Media[{i}]: {type_name} - {status_name}")
                    logger.info(f"[MEDIA]     Direction: {mi.dir}")
                    
                    if mi.type == pj.PJMEDIA_TYPE_AUDIO:
                        if mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                            self.media_active = True
                            logger.info(f"[MEDIA] *** AUDIO IS NOW ACTIVE ***")
                            
            except Exception as e:
                logger.error(f"[MEDIA] onCallMediaState error: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        def onCallTsxState(self, prm):
            """Called on transaction state changes - shows SIP messages."""
            try:
                # This gives us more insight into SIP transactions
                logger.debug(f"[TSX] Transaction state change")
            except:
                pass


class SIPHandlerPJSIP:
    """
    SIP client handler using PJSIP/pjsua2.
    DEBUG VERSION with enhanced logging.
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
        public_ip: Optional[str] = None,
        debug_level: int = 5  # PJSIP log level (1-6, 6=most verbose)
    ):
        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.answer_delay = answer_delay
        self.hangup_delay = hangup_delay
        self.check_number = check_number
        self.on_valid_call = on_valid_call
        self.debug_level = debug_level
        
        logger.info(f"[INIT] Creating SIP Handler")
        logger.info(f"[INIT]   Server: {server}:{port}")
        logger.info(f"[INIT]   Username: {username}")
        logger.info(f"[INIT]   Answer delay: {answer_delay}s")
        logger.info(f"[INIT]   Hangup delay: {hangup_delay}s")
        logger.info(f"[INIT]   Debug level: {debug_level}")
        
        # IP addresses
        self.local_ip = local_ip or get_local_ip()
        self.public_ip = public_ip or get_public_ip()
        
        logger.info(f"[INIT]   Local IP: {self.local_ip}")
        logger.info(f"[INIT]   Public IP: {self.public_ip}")
        
        self._endpoint = None
        self._account = None
        self._log_writer = None
        self._running = False
        self._registered = False
        self._reg_failed_reason = None
        self._call_count = 0
        self._valid_call_count = 0
        self._call_history: list = []
        
        self._pending_gpio_callbacks = []
        self._gpio_lock = threading.Lock()
        
        self.mock_mode = mock_mode or not PJSUA2_AVAILABLE
        
        if not PJSUA2_AVAILABLE and not mock_mode:
            logger.warning("[INIT] pjsua2 not available, using mock mode")
    
    def start(self) -> bool:
        """Start SIP client and register."""
        logger.info(f"\n{'='*60}")
        logger.info(f"[START] Starting PJSIP client")
        logger.info(f"{'='*60}")
        
        if self.mock_mode:
            return self._start_mock()
        
        try:
            # Create endpoint
            logger.info("[START] Creating PJSIP endpoint...")
            self._endpoint = pj.Endpoint()
            self._endpoint.libCreate()
            logger.info("[START] Endpoint created")
            
            # Configure endpoint
            ep_cfg = pj.EpConfig()
            
            # ============================================
            # ENHANCED LOGGING CONFIG
            # ============================================
            ep_cfg.logConfig.level = self.debug_level  # Library log level
            ep_cfg.logConfig.consoleLevel = self.debug_level  # Console log level
            ep_cfg.logConfig.msgLogging = 1  # Enable SIP message logging
            ep_cfg.logConfig.decor = pj.PJ_LOG_HAS_NEWLINE | pj.PJ_LOG_HAS_TIME | pj.PJ_LOG_HAS_SENDER
            
            # Custom log writer
            self._log_writer = MyLogWriter()
            ep_cfg.logConfig.writer = self._log_writer
            
            logger.info(f"[START] Log level set to {self.debug_level}")
            
            # UA config
            ep_cfg.uaConfig.userAgent = "SIPClient/1.0-DEBUG (PJSIP)"
            ep_cfg.uaConfig.maxCalls = 4
            ep_cfg.uaConfig.threadCnt = 0
            ep_cfg.uaConfig.mainThreadOnly = False
            
            # Media config
            ep_cfg.medConfig.noVad = True
            ep_cfg.medConfig.clockRate = 8000  # 8kHz for G.711
            ep_cfg.medConfig.sndClockRate = 0  # Use default
            
            # Initialize library
            logger.info("[START] Initializing PJSIP library...")
            self._endpoint.libInit(ep_cfg)
            logger.info("[START] PJSIP library initialized")
            
            # Set null audio device
            logger.info("[START] Setting null audio device...")
            try:
                self._endpoint.audDevManager().setNullDev()
                logger.info("[START] Null audio device set successfully")
            except Exception as e:
                logger.warning(f"[START] Could not set null audio device: {e}")
            
            # Create UDP transport
            logger.info("[START] Creating UDP transport...")
            tp_cfg = pj.TransportConfig()
            tp_cfg.port = 5060
            tp_cfg.boundAddress = ""
            
            if self.public_ip and self.public_ip != self.local_ip:
                tp_cfg.publicAddress = self.public_ip
                logger.info(f"[START] SIP transport public address: {self.public_ip}")
            
            self._endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
            logger.info("[START] UDP transport created on port 5060")
            
            # Start endpoint
            logger.info("[START] Starting PJSIP endpoint...")
            self._endpoint.libStart()
            logger.info("[START] PJSIP endpoint started")
            
            # Print codec list
            self._print_codecs()
            
            # Configure account
            logger.info("[START] Configuring SIP account...")
            acc_cfg = pj.AccountConfig()
            acc_cfg.idUri = f"sip:{self.username}@{self.server}"
            acc_cfg.regConfig.registrarUri = f"sip:{self.server}:{self.port}"
            acc_cfg.regConfig.timeoutSec = 120
            acc_cfg.regConfig.retryIntervalSec = 30
            acc_cfg.regConfig.firstRetryIntervalSec = 10
            
            logger.info(f"[START]   ID URI: sip:{self.username}@{self.server}")
            logger.info(f"[START]   Registrar: sip:{self.server}:{self.port}")
            
            # Credentials
            cred = pj.AuthCredInfo()
            cred.scheme = "digest"
            cred.realm = "*"
            cred.username = self.username
            cred.dataType = 0  # Plain text password
            cred.data = self.password
            acc_cfg.sipConfig.authCreds.append(cred)
            logger.info(f"[START]   Auth: digest, realm=*, user={self.username}")
            
            # NAT settings
            logger.info("[START] Configuring NAT settings...")
            acc_cfg.natConfig.contactRewriteUse = 1
            acc_cfg.natConfig.viaRewriteUse = 1
            acc_cfg.natConfig.sdpNatRewriteUse = 2  # Always rewrite
            acc_cfg.natConfig.sipOutboundUse = 0
            acc_cfg.natConfig.iceEnabled = False
            acc_cfg.natConfig.turnEnabled = False
            acc_cfg.natConfig.sipStunUse = 0
            acc_cfg.natConfig.mediaStunUse = 0
            
            logger.info(f"[START]   contactRewriteUse: 1")
            logger.info(f"[START]   sdpNatRewriteUse: 2 (always)")
            
            # RTP/Media config
            logger.info("[START] Configuring RTP/Media...")
            acc_cfg.mediaConfig.transportConfig.port = 10000
            acc_cfg.mediaConfig.transportConfig.portRange = 10000
            
            if self.public_ip:
                acc_cfg.mediaConfig.transportConfig.publicAddress = self.public_ip
                logger.info(f"[START]   RTP public address: {self.public_ip}")
            
            logger.info(f"[START]   RTP port range: 10000-20000")
            
            # Create and register account
            logger.info("[START] Creating account...")
            self._account = MyAccount(self)
            self._account.create(acc_cfg)
            logger.info("[START] Account created, sending REGISTER...")
            
            # Wait for registration
            self._running = True
            timeout = 15
            logger.info(f"[START] Waiting up to {timeout}s for registration...")
            
            while timeout > 0 and not self._registered and not self._reg_failed_reason:
                time.sleep(0.1)
                timeout -= 0.1
                self._endpoint.libHandleEvents(50)
            
            if self._registered:
                logger.info("[START] *** REGISTRATION SUCCESSFUL ***")
                self._display_registered()
                return True
            elif self._reg_failed_reason:
                logger.error(f"[START] *** REGISTRATION FAILED: {self._reg_failed_reason} ***")
                return False
            else:
                logger.warning("[START] Registration timeout - continuing anyway")
                self._display_registered()
                return True
            
        except Exception as e:
            logger.error(f"[START] PJSIP start failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            self._cleanup_pjsip()
            self.mock_mode = True
            return self._start_mock()
    
    def _print_codecs(self):
        """Print available audio codecs."""
        try:
            logger.info("[CODECS] Available audio codecs:")
            codec_mgr = self._endpoint.codecEnum2()
            for codec in codec_mgr:
                logger.info(f"[CODECS]   {codec.codecId} (priority={codec.priority})")
        except Exception as e:
            logger.debug(f"[CODECS] Could not list codecs: {e}")
    
    def _cleanup_pjsip(self):
        """Clean up PJSIP resources."""
        logger.info("[CLEANUP] Cleaning up PJSIP resources...")
        try:
            if self._account:
                try:
                    logger.debug("[CLEANUP] Shutting down account...")
                    self._account.shutdown()
                except:
                    pass
                self._account = None
            
            if self._endpoint:
                try:
                    logger.debug("[CLEANUP] Destroying endpoint...")
                    self._endpoint.libDestroy()
                except:
                    pass
                self._endpoint = None
            
            logger.info("[CLEANUP] Cleanup complete")
        except Exception as e:
            logger.error(f"[CLEANUP] Error during cleanup: {e}")
    
    def _on_registered(self):
        """Called when registration succeeds."""
        self._registered = True
        logger.info("[REG] ✓ Successfully registered with SIP server!")
    
    def _on_reg_failed(self, reason: str):
        """Called when registration fails."""
        self._reg_failed_reason = reason
        logger.error(f"[REG] ✗ Registration failed: {reason}")
    
    def _handle_incoming_call_sync(self, call, caller_id: str):
        """Handle incoming SIP call synchronously."""
        self._call_count += 1
        call_num = self._call_count
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        logger.info(f"\n{'*'*60}")
        logger.info(f"* [{timestamp}] HANDLING CALL #{call_num}")
        logger.info(f"* Caller: {caller_id}")
        logger.info(f"{'*'*60}")
        
        self._display_call_incoming(caller_id)
        
        call_info = CallInfo(
            caller_id=caller_id,
            state=CallState.RINGING,
            timestamp=time.time()
        )
        
        try:
            # ============================================
            # STEP 1: Send 180 Ringing
            # ============================================
            logger.info(f"[CALL #{call_num}] Step 1: Sending 180 Ringing...")
            ringing_prm = pj.CallOpParam()
            ringing_prm.statusCode = 180
            ringing_prm.reason = "Ringing"
            
            try:
                call.answer(ringing_prm)
                logger.info(f"[CALL #{call_num}] 180 Ringing sent successfully")
            except Exception as e:
                logger.error(f"[CALL #{call_num}] Failed to send 180: {e}")
            
            # Process events
            if self._endpoint:
                self._endpoint.libHandleEvents(100)
            
            # ============================================
            # STEP 2: Wait (simulating ring time)
            # ============================================
            logger.info(f"[CALL #{call_num}] Step 2: Waiting {self.answer_delay}s before answering...")
            delay_remaining = self.answer_delay
            while delay_remaining > 0 and not call.disconnected:
                sleep_time = min(0.1, delay_remaining)
                time.sleep(sleep_time)
                delay_remaining -= sleep_time
                if self._endpoint:
                    self._endpoint.libHandleEvents(10)
            
            if call.disconnected:
                logger.info(f"[CALL #{call_num}] Caller hung up during ringing")
                call_info.state = CallState.ENDED
                self._call_history.append(call_info)
                return
            
            # ============================================
            # STEP 3: Send 200 OK (Answer)
            # ============================================
            logger.info(f"[CALL #{call_num}] Step 3: Sending 200 OK...")
            answer_prm = pj.CallOpParam()
            answer_prm.statusCode = 200
            answer_prm.reason = "OK"
            
            # Get current call info before answering
            try:
                pre_answer_info = call.getInfo()
                logger.info(f"[CALL #{call_num}] Pre-answer state: {pre_answer_info.stateText}")
            except:
                pass
            
            try:
                call.answer(answer_prm)
                call.answered = True
                logger.info(f"[CALL #{call_num}] 200 OK sent successfully")
            except Exception as e:
                logger.error(f"[CALL #{call_num}] Failed to send 200 OK: {e}")
                raise
            
            call_info.state = CallState.ANSWERED
            self._display_call_answered()
            
            # Process events to ensure 200 OK is sent
            if self._endpoint:
                self._endpoint.libHandleEvents(200)
            
            # ============================================
            # STEP 4: Wait for media/ACK
            # ============================================
            logger.info(f"[CALL #{call_num}] Step 4: Waiting for media to become active...")
            media_timeout = 3.0
            while media_timeout > 0 and not call.media_active and not call.disconnected:
                time.sleep(0.1)
                media_timeout -= 0.1
                if self._endpoint:
                    self._endpoint.libHandleEvents(10)
                
                # Check call state
                try:
                    info = call.getInfo()
                    if info.state == pj.PJSIP_INV_STATE_CONFIRMED:
                        logger.info(f"[CALL #{call_num}] Call is now CONFIRMED")
                        break
                except:
                    pass
            
            if call.media_active:
                logger.info(f"[CALL #{call_num}] ✓ Media is ACTIVE")
            elif call.disconnected:
                logger.info(f"[CALL #{call_num}] Call disconnected before media established")
            else:
                logger.warning(f"[CALL #{call_num}] Media not active after timeout (continuing anyway)")
            
            # ============================================
            # STEP 5: Hold call for hangup_delay
            # ============================================
            logger.info(f"[CALL #{call_num}] Step 5: Call connected, waiting {self.hangup_delay}s...")
            delay_remaining = self.hangup_delay
            while delay_remaining > 0 and not call.disconnected:
                sleep_time = min(0.1, delay_remaining)
                time.sleep(sleep_time)
                delay_remaining -= sleep_time
                if self._endpoint:
                    self._endpoint.libHandleEvents(10)
            
            # ============================================
            # STEP 6: Hang up
            # ============================================
            if not call.disconnected:
                logger.info(f"[CALL #{call_num}] Step 6: Sending BYE (hanging up)...")
                hangup_prm = pj.CallOpParam()
                hangup_prm.statusCode = 200
                try:
                    call.hangup(hangup_prm)
                    logger.info(f"[CALL #{call_num}] BYE sent successfully")
                except Exception as e:
                    logger.error(f"[CALL #{call_num}] Failed to send BYE: {e}")
            else:
                logger.info(f"[CALL #{call_num}] Call already disconnected by remote")
            
            call_info.state = CallState.ENDED
            self._display_call_ended()
            
            # Process final events
            if self._endpoint:
                self._endpoint.libHandleEvents(200)
            
            # ============================================
            # STEP 7: Check caller validity
            # ============================================
            logger.info(f"[CALL #{call_num}] Step 7: Checking caller validity...")
            if self.check_number:
                is_valid, pattern = self.check_number(caller_id)
                call_info.is_valid = is_valid
                call_info.matched_pattern = pattern
                
                if is_valid:
                    self._valid_call_count += 1
                    logger.info(f"[CALL #{call_num}] ✓ VALID CALLER - matched pattern '{pattern}'")
                    self._display_valid_caller(pattern)
                    
                    if self.on_valid_call:
                        with self._gpio_lock:
                            self._pending_gpio_callbacks.append(caller_id)
                            logger.info(f"[CALL #{call_num}] GPIO callback queued")
                else:
                    logger.info(f"[CALL #{call_num}] ✗ INVALID CALLER - no matching pattern")
                    self._display_invalid_caller()
            
            logger.info(f"\n{'*'*60}")
            logger.info(f"* CALL #{call_num} COMPLETED")
            logger.info(f"{'*'*60}\n")
            
        except Exception as e:
            logger.error(f"[CALL #{call_num}] Error during call handling: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                if not call.disconnected:
                    call.hangup(pj.CallOpParam())
            except:
                pass
        finally:
            self._call_history.append(call_info)
    
    def process_pending_callbacks(self):
        """Process any pending GPIO callbacks."""
        with self._gpio_lock:
            callbacks = self._pending_gpio_callbacks[:]
            self._pending_gpio_callbacks.clear()
        
        for caller_id in callbacks:
            if self.on_valid_call:
                try:
                    logger.debug(f"[GPIO] Executing callback for {caller_id}")
                    self.on_valid_call(caller_id)
                except Exception as e:
                    logger.error(f"[GPIO] Callback error: {e}")
    
    def poll(self):
        """Poll for events."""
        if self._endpoint and not self.mock_mode:
            try:
                self._endpoint.libHandleEvents(100)
            except:
                pass
        
        self.process_pending_callbacks()
    
    def _start_mock(self) -> bool:
        """Start in mock mode."""
        logger.info("[MOCK] Starting in mock mode")
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
        print("║" + "  ✓ 200 OK SENT (Answered)".center(48) + "║")
    
    def _display_call_ended(self):
        print("║" + "  ✓ BYE SENT (Hung up)".center(48) + "║")
    
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
        print("║" + f"  Debug Level: {self.debug_level}".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("║" + "  Waiting for calls...".center(48) + "║")
        print("║" + " " * 48 + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def _display_registered_mock(self):
        print()
        print("╔" + "═" * 48 + "╗")
        print("║" + "  ⚠️  MOCK SIP CLIENT".center(48) + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def stop(self):
        """Stop SIP client."""
        logger.info("[STOP] Stopping PJSIP client...")
        self._running = False
        
        if not self.mock_mode:
            self._cleanup_pjsip()
        
        logger.info("[STOP] PJSIP client stopped")
    
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
        
        self._call_count += 1
        self._display_call_incoming(caller_id)
        
        def process():
            time.sleep(self.answer_delay)
            self._display_call_answered()
            time.sleep(self.hangup_delay)
            self._display_call_ended()
            
            if self.check_number:
                is_valid, pattern = self.check_number(caller_id)
                if is_valid:
                    self._valid_call_count += 1
                    self._display_valid_caller(pattern)
                    if self.on_valid_call:
                        self.on_valid_call(caller_id)
                else:
                    self._display_invalid_caller()
        
        threading.Thread(target=process, daemon=True).start()


# Alias
SIPHandler = SIPHandlerPJSIP


def main():
    """Test with debug logging."""
    # Setup detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Also enable PJSIP logger
    pjsip_logger = logging.getLogger("pjsip")
    pjsip_logger.setLevel(logging.DEBUG)
    
    print("=" * 70)
    print("  PJSIP DEBUG TEST")
    print("  Log level 5 (verbose) - will show SIP messages")
    print("=" * 70)
    
    print(f"\npjsua2 available: {PJSUA2_AVAILABLE}")
    
    if not PJSUA2_AVAILABLE:
        print("\n❌ pjsua2 not installed!")
        return 1
    
    def check_number(number):
        normalized = number.replace('+', '').replace(' ', '').replace('-', '')
        if normalized.startswith('0') and len(normalized) == 11:
            normalized = '44' + normalized[1:]
        if normalized.startswith("44") or normalized.startswith("216"):
            return True, "44* or 216*"
        return False, None
    
    def on_valid(caller):
        print(f"\n{'!'*60}")
        print(f"!  GPIO ACTIVATED for: {caller}")
        print(f"{'!'*60}\n")
    
    sip = SIPHandlerPJSIP(
        server="ast1.rdng.coreservers.uk",
        username="100500",
        password="xmbhret4fwet",
        port=5060,
        answer_delay=1,
        hangup_delay=2,
        check_number=check_number,
        on_valid_call=on_valid,
        debug_level=5  # Verbose logging
    )
    
    if sip.start():
        print("\n" + "=" * 70)
        print("  READY - Waiting for calls")
        print("  Call +441494851636 to test")
        print("  Press Ctrl+C to stop")
        print("=" * 70 + "\n")
        
        try:
            while True:
                sip.poll()
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\nStopping...")
        
        sip.stop()
    else:
        print("\n❌ Failed to start SIP client")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())