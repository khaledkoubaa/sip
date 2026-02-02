#!/usr/bin/env python3
import socket
import time
import requests

def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        return response.json()['ip']
    except:
        return None

from debug_sip import get_local_ip
local_ip = get_local_ip()

def main():
    print("\n" + "="*60)
    print("SIP DEBUG - Using Public IP")
    print("="*60)
    
    public_ip = get_public_ip()
    print(f"\nPublic IP: {public_ip}")
    
    if not public_ip:
        print("Could not get public IP!")
        return
    
    print("\nRegistering with PUBLIC IP...")
    print("(This may or may not work depending on your NAT type)\n")
    
    try:
        from pyVoIP.VoIP import VoIPPhone, PhoneStatus
        
        call_count = [0]
        
        def call_callback(call):
            call_count[0] += 1
            print(f"\n{'='*60}")
            print(f"INCOMING CALL #{call_count[0]}!")
            print(f"{'='*60}")
            try:
                time.sleep(1)
                call.answer()
                print("Answered!")
                time.sleep(2)
                call.hangup()
                print("Hung up!")
            except Exception as e:
                print(f"Error: {e}")
        
        phone = VoIPPhone(
            "ast1.rdng.coreservers.uk",
            5060,
            "100500", 
            "xmbhret4fwet",
            callCallback=call_callback,
            myIP=public_ip,
            sipPort=5060,
            rtpPortLow=10000,
            rtpPortHigh=20000
        )
        
        phone.start()
        time.sleep(3)
        
        status = phone.get_status()
        print(f"Status: {status}")
        
        if status == PhoneStatus.REGISTERED:
            print("\n" + "="*60)
            print("REGISTERED with Public IP!")
            print(f"Server thinks we are at: {public_ip}:5060")
            print("="*60)
            print("\nCall +441494851636 now!")
            print("Press Ctrl+C to stop\n")
            
            while True:
                time.sleep(1)
        else:
            print(f"\nRegistration failed: {status}")
            
    except KeyboardInterrupt:
        print("\nStopped.")
        phone.stop()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
