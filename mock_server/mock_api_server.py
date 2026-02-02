#!/usr/bin/env python3
"""
Mock API Server for Testing
Simulates the client's phone number API.
"""

from flask import Flask, jsonify, request
import logging
import sys

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simulated valid phone numbers
VALID_NUMBERS = [
    "441234567890",    # Specific number
    "441234*",         # Area code wildcard  
    "44*",             # UK country wildcard
]


@app.route('/')
def index():
    """API information."""
    return jsonify({
        "name": "Mock Phone Number API",
        "version": "1.0",
        "endpoints": {
            "GET /numbers": "Get valid phone numbers (array)",
            "GET /numbers/detailed": "Get numbers with metadata",
            "GET /health": "Health check",
            "POST /numbers": "Update numbers (for testing)"
        }
    })


@app.route('/numbers', methods=['GET'])
def get_numbers():
    """Return list of valid phone numbers."""
    auth = request.headers.get('Authorization', '')
    logger.info(f"GET /numbers - Auth: {auth[:30]}..." if auth else "GET /numbers - No auth")
    
    return jsonify(VALID_NUMBERS)


@app.route('/numbers/detailed', methods=['GET'])
def get_numbers_detailed():
    """Return numbers with metadata."""
    return jsonify({
        "status": "success",
        "count": len(VALID_NUMBERS),
        "numbers": VALID_NUMBERS
    })


@app.route('/numbers', methods=['POST'])
def update_numbers():
    """Update the valid numbers (for testing)."""
    global VALID_NUMBERS
    
    data = request.get_json()
    if data and isinstance(data, list):
        VALID_NUMBERS = data
        logger.info(f"Updated numbers to: {VALID_NUMBERS}")
        return jsonify({"status": "updated", "numbers": VALID_NUMBERS})
    
    return jsonify({"error": "Expected JSON array"}), 400


@app.route('/health', methods=['GET'])
def health():
    """Health check."""
    return jsonify({"status": "healthy"})


def main():
    host = '0.0.0.0'
    port = 5000
    
    # Parse arguments
    for arg in sys.argv[1:]:
        if arg.startswith('--port='):
            port = int(arg.split('=')[1])
    
    print()
    print("╔" + "═" * 48 + "╗")
    print("║" + "  MOCK API SERVER".center(48) + "║")
    print("╠" + "═" * 48 + "╣")
    print("║" + f"  Running on http://localhost:{port}".center(48) + "║")
    print("║" + " " * 48 + "║")
    print("║" + "  Endpoints:".ljust(48) + "║")
    print("║" + f"    GET  http://localhost:{port}/numbers".ljust(48) + "║")
    print("║" + f"    GET  http://localhost:{port}/health".ljust(48) + "║")
    print("║" + " " * 48 + "║")
    print("║" + f"  Current patterns: {VALID_NUMBERS}".ljust(48)[:48] + "║")
    print("║" + " " * 48 + "║")
    print("║" + "  Press Ctrl+C to stop".center(48) + "║")
    print("╚" + "═" * 48 + "╝")
    print()
    
    app.run(host=host, port=port, debug=True)


if __name__ == '__main__':
    main()