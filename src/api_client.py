"""
API Client Module
Fetches valid phone numbers from remote REST API.
"""

import json
import logging
import os
import threading
import time
from typing import List, Optional, Callable
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class APIClient:
    """Fetches and caches phone number patterns from API."""
    
    def __init__(
        self,
        api_url: str,
        auth_token: str = "",
        auth_header_name: str = "api_token",
        http_method: str = "POST",
        response_data_key: str = "data",
        refresh_interval: int = 3600,
        cache_file: str = "/tmp/valid_numbers_cache.json",
        use_cache_on_failure: bool = True,
        on_update: Optional[Callable[[List[str]], None]] = None
    ):
        """
        Initialize API client.
        
        Args:
            api_url: URL to fetch phone numbers
            auth_token: API token for authentication
            auth_header_name: Header name for auth token (default: api_token)
            http_method: HTTP method - GET or POST (default: POST)
            response_data_key: Key in response containing numbers (default: data)
            refresh_interval: Seconds between refreshes
            cache_file: Path for persistent cache
            use_cache_on_failure: Use cache when API fails
            on_update: Callback when numbers are updated
        """
        self.api_url = api_url
        self.auth_token = auth_token
        self.auth_header_name = auth_header_name
        self.http_method = http_method.upper()
        self.response_data_key = response_data_key
        self.refresh_interval = refresh_interval
        self.cache_file = cache_file
        self.use_cache_on_failure = use_cache_on_failure
        self.on_update = on_update
        
        self._numbers: List[str] = []
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        self._last_fetch: Optional[float] = None
        self._last_success: bool = False
        self._fetch_count: int = 0
        self._error_count: int = 0
    
    def start(self) -> bool:
        """
        Start the API client.
        
        Returns:
            True if initial fetch succeeded
        """
        logger.info(f"Starting API client: {self.api_url}")
        logger.info(f"  Method: {self.http_method}")
        logger.info(f"  Auth header: {self.auth_header_name}")
        
        # Try initial fetch
        success = self._fetch()
        
        # If failed, try loading cache
        if not success and self.use_cache_on_failure:
            cached = self._load_cache()
            if cached:
                with self._lock:
                    self._numbers = cached
                logger.info(f"Loaded {len(cached)} numbers from cache")
        
        # Start background refresh thread
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._refresh_loop,
            name="APIClient-Refresh",
            daemon=True
        )
        self._thread.start()
        
        return success or len(self._numbers) > 0
    
    def stop(self):
        """Stop the API client."""
        logger.info("Stopping API client")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
    
    def _refresh_loop(self):
        """Background refresh loop."""
        while not self._stop_event.is_set():
            # Wait for interval
            if self._stop_event.wait(timeout=self.refresh_interval):
                break  # Stop event was set
            
            # Refresh
            self._fetch()
    
    def _fetch(self) -> bool:
        """
        Fetch numbers from API.
        
        Returns:
            True if successful
        """
        self._fetch_count += 1
        logger.info(f"Fetching numbers from API (attempt #{self._fetch_count})")
        
        try:
            # Build headers
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Add auth token with custom header name
            if self.auth_token:
                headers[self.auth_header_name] = self.auth_token
            
            # Make request (POST or GET)
            if self.http_method == "POST":
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json={},  # Empty body for POST
                    timeout=30
                )
            else:
                response = requests.get(
                    self.api_url,
                    headers=headers,
                    timeout=30
                )
            
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"API response: {data}")
            
            # Extract numbers from response
            numbers = self._extract_numbers(data)
            
            # Clean up numbers
            numbers = [str(n).strip() for n in numbers if n]
            
            # Update state
            with self._lock:
                old_count = len(self._numbers)
                self._numbers = numbers
                self._last_fetch = time.time()
                self._last_success = True
            
            # Save to cache
            self._save_cache(numbers)
            
            # Notify callback
            if self.on_update:
                self.on_update(numbers)
            
            logger.info(f"✓ Fetched {len(numbers)} numbers (was {old_count})")
            return True
            
        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            self._error_count += 1
            self._last_success = False
            return False
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse response: {e}")
            self._error_count += 1
            self._last_success = False
            return False
    
    def _extract_numbers(self, data) -> List[str]:
        """Extract numbers from API response."""
        # If response is already a list
        if isinstance(data, list):
            return data
        
        # If response is a dict
        if isinstance(data, dict):
            # Check status
            status = data.get('status', '')
            if status and status != 'success':
                logger.warning(f"API returned status: {status}")
            
            # Try the configured key first
            if self.response_data_key in data:
                result = data[self.response_data_key]
                if isinstance(result, list):
                    return result
            
            # Try common keys
            for key in ['data', 'numbers', 'valid_numbers', 'patterns']:
                if key in data and isinstance(data[key], list):
                    return data[key]
        
        raise ValueError(f"Could not extract numbers from response: {type(data)}")
    
    def _save_cache(self, numbers: List[str]):
        """Save numbers to cache file."""
        try:
            cache_path = Path(self.cache_file)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(cache_path, 'w') as f:
                json.dump({
                    'numbers': numbers,
                    'timestamp': time.time(),
                    'source': self.api_url
                }, f, indent=2)
            
            logger.debug(f"Saved {len(numbers)} numbers to cache")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def _load_cache(self) -> Optional[List[str]]:
        """Load numbers from cache file."""
        try:
            cache_path = Path(self.cache_file)
            if cache_path.exists():
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                return data.get('numbers', [])
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
        return None
    
    def get_numbers(self) -> List[str]:
        """Get current list of valid numbers."""
        with self._lock:
            return self._numbers.copy()
    
    def get_status(self) -> dict:
        """Get client status."""
        with self._lock:
            return {
                'numbers_count': len(self._numbers),
                'last_fetch': self._last_fetch,
                'last_success': self._last_success,
                'fetch_count': self._fetch_count,
                'error_count': self._error_count,
                'api_url': self.api_url
            }
    
    def force_refresh(self) -> bool:
        """Force an immediate refresh."""
        return self._fetch()


def main():
    """Test API client with real API."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s: %(message)s'
    )
    
    print("=" * 60)
    print("API CLIENT TEST - REAL API")
    print("=" * 60)
    
    def on_update(numbers):
        print(f"\n📥 Received {len(numbers)} patterns:")
        for n in numbers:
            print(f"   • {n}")
        print()
    
    # Use real API settings
    client = APIClient(
        api_url="https://smsgw.uk/api/v2/",
        auth_token="gdPw3bcDadQPC7g4",
        auth_header_name="api_token",
        http_method="POST",
        response_data_key="data",
        refresh_interval=3600,
        cache_file="/tmp/sip_client_cache.json",
        on_update=on_update
    )
    
    if client.start():
        print("✓ API client started successfully")
        print(f"\nNumbers loaded: {client.get_numbers()}")
    else:
        print("✗ API client failed to start")
        return 1
    
    client.stop()
    print("\nTest complete!")
    return 0


if __name__ == "__main__":
    exit(main())