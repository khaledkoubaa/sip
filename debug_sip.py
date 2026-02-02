#!/usr/bin/env python3
import socket
import time
import requests

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "unknown"

def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        return response.json()['ip']
    except:
        return "unknown"

def main():
    print("\n" + "="*60)
    print("SIP DEBUG")
    print("="*60)
    
    local_ip = get_local_ip()
    public_ip = get_public_ip()
    
    print(f"\nLocal IP (WSL):  {local_ip}")
    print(f"Public IP:       {public_ip}")
    
    print("\nStarting SIP Registration...")
    
    try:
        from pyVoIP.VoIP import VoIPPhone, PhoneStatus
        
        def call_callback(call):
            print(f"\n*** INCOMING CALL! ***")
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
            myIP=local_ip,
            sipPort=5060,
            rtpPortLow=10000,
            rtpPortHigh=20000
        )
        
        phone.start()
        time.sleep(3)
        
        status = phone.get_status()
        print(f"\nStatus: {status}")
        
        if status == PhoneStatus.REGISTERED:
            print("\n*** REGISTERED! ***")
            print("Call +441494851636 now!")
            print("Press Ctrl+C to stop\n")
            
            while True:
                time.sleep(1)
                
    except KeyboardInterrupt:
        print("\nStopped.")
        phone.stop()
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
