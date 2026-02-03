#!/usr/bin/env python3
"""
Setup script for LiveKit SIP Trunk configuration.

This script creates the necessary SIP inbound trunk and dispatch rules
for Twilio integration. Run this after docker-compose is up.

Usage:
    python scripts/setup_sip.py
"""
import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def setup_sip_trunk():
    """Create SIP inbound trunk and dispatch rules."""
    try:
        from livekit.api import LiveKitAPI, CreateSIPInboundTrunkRequest, CreateSIPDispatchRuleRequest
        from livekit.api import SIPInboundTrunkInfo, SIPDispatchRule, SIPDispatchRuleIndividual
    except ImportError:
        print("ERROR: livekit-api package not installed.")
        print("Install with: pip install livekit-api")
        sys.exit(1)

    # Configuration
    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    livekit_url = os.getenv("LIVEKIT_URL", "http://localhost:7880")

    # Convert ws:// to http:// for API calls
    if livekit_url.startswith("ws://"):
        livekit_url = livekit_url.replace("ws://", "http://")
    elif livekit_url.startswith("wss://"):
        livekit_url = livekit_url.replace("wss://", "https://")

    sip_username = os.getenv("LIVEKIT_SIP_TRUNK_USERNAME", "twilio_trunk")
    sip_password = os.getenv("LIVEKIT_SIP_TRUNK_PASSWORD", "secure_password_123")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER", "")

    print(f"Connecting to LiveKit at {livekit_url}...")
    print(f"API Key: {api_key}")
    print(f"SIP Username: {sip_username}")
    print(f"Twilio Number: {twilio_number or '(not set)'}")
    print()

    # Create LiveKit API client
    lk = LiveKitAPI(livekit_url, api_key, api_secret)

    try:
        # Step 1: Create Inbound Trunk
        print("Creating SIP Inbound Trunk...")

        trunk_info = SIPInboundTrunkInfo(
            name="Twilio Customer Service Bridge",
            numbers=[twilio_number] if twilio_number else [],
            auth_username=sip_username,
            auth_password=sip_password,
            allowed_addresses=[],  # Allow from any IP (Twilio's IPs are dynamic)
            metadata="twilio-customer-service"
        )

        try:
            trunk = await lk.sip.create_sip_inbound_trunk(
                CreateSIPInboundTrunkRequest(trunk=trunk_info)
            )
            print(f"[OK] Created inbound trunk: {trunk.sip_trunk_id}")
            print(f"  Name: {trunk.name}")
            print(f"  Numbers: {trunk.numbers}")
        except Exception as e:
            error_str = str(e).lower()
            if "already exists" in error_str or "duplicate" in error_str:
                print(f"[WARN] Trunk may already exist: {e}")
            else:
                print(f"[FAIL] Failed to create trunk: {e}")

        # Step 2: Create Dispatch Rule
        print("\nCreating SIP Dispatch Rule...")

        # SIPDispatchRule only contains the rule type (individual/direct/callee)
        # Room prefix matches session IDs which start with "sess_"
        dispatch_rule = SIPDispatchRule(
            dispatch_rule_individual=SIPDispatchRuleIndividual(
                room_prefix="sess_"  # Routes sip:sess_xxx to room "sess_xxx"
            )
        )

        try:
            dispatch = await lk.sip.create_sip_dispatch_rule(
                CreateSIPDispatchRuleRequest(
                    rule=dispatch_rule,
                    name="Twilio to Room Router",
                    trunk_ids=[],  # Empty = apply to all trunks
                    hide_phone_number=False,
                    metadata="twilio-dispatch"
                )
            )
            print(f"[OK] Created dispatch rule: {dispatch.sip_dispatch_rule_id}")
        except Exception as e:
            error_str = str(e).lower()
            if "already exists" in error_str or "duplicate" in error_str:
                print(f"[WARN] Dispatch rule may already exist: {e}")
            else:
                print(f"[FAIL] Failed to create dispatch rule: {e}")

        # Step 3: List current configuration
        print("\n" + "="*50)
        print("Current SIP Configuration:")
        print("="*50)

        try:
            from livekit.api import ListSIPInboundTrunkRequest, ListSIPDispatchRuleRequest

            trunks = await lk.sip.list_sip_inbound_trunk(ListSIPInboundTrunkRequest())
            print(f"\nInbound Trunks ({len(trunks.items)}):")
            for t in trunks.items:
                print(f"  - {t.sip_trunk_id}: {t.name}")
                print(f"    Numbers: {t.numbers}")
                print(f"    Username: {t.auth_username}")
        except Exception as e:
            print(f"  Could not list trunks: {e}")

        try:
            rules = await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())
            print(f"\nDispatch Rules ({len(rules.items)}):")
            for r in rules.items:
                rule_name = r.name if hasattr(r, 'name') and r.name else 'unnamed'
                print(f"  - {r.sip_dispatch_rule_id}: {rule_name}")
        except Exception as e:
            print(f"  Could not list rules: {e}")

        print("\n" + "="*50)
        print("SIP Setup Complete!")
        print("="*50)

        sip_host = os.getenv("LIVEKIT_SIP_HOST", "your-public-ip:5060")
        print(f"""
Next steps:

1. Ensure your .env has:
   LIVEKIT_SIP_HOST={sip_host}
   LIVEKIT_SIP_TRUNK_USERNAME={sip_username}
   LIVEKIT_SIP_TRUNK_PASSWORD={sip_password}

2. Twilio will dial:
   sip:room_{{session_id}}@{sip_host}

3. Make sure UDP ports 5060 and 10000-10100 are open in your firewall

4. Test by triggering a customer service escalation!
""")

    finally:
        await lk.aclose()


async def delete_sip_config():
    """Delete all SIP configuration (for cleanup)."""
    try:
        from livekit.api import LiveKitAPI, ListSIPInboundTrunkRequest, ListSIPDispatchRuleRequest
        from livekit.api import DeleteSIPTrunkRequest, DeleteSIPDispatchRuleRequest
    except ImportError:
        print("ERROR: livekit-api package not installed.")
        sys.exit(1)

    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    livekit_url = os.getenv("LIVEKIT_URL", "http://localhost:7880")

    if livekit_url.startswith("ws://"):
        livekit_url = livekit_url.replace("ws://", "http://")

    lk = LiveKitAPI(livekit_url, api_key, api_secret)

    print("Deleting SIP configuration...")

    try:
        # Delete dispatch rules
        try:
            rules = await lk.sip.list_sip_dispatch_rule(ListSIPDispatchRuleRequest())
            for r in rules.items:
                await lk.sip.delete_sip_dispatch_rule(
                    DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=r.sip_dispatch_rule_id)
                )
                print(f"  Deleted dispatch rule: {r.sip_dispatch_rule_id}")
        except Exception as e:
            print(f"  Error deleting dispatch rules: {e}")

        # Delete trunks
        try:
            trunks = await lk.sip.list_sip_inbound_trunk(ListSIPInboundTrunkRequest())
            for t in trunks.items:
                await lk.sip.delete_sip_inbound_trunk(
                    DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id)
                )
                print(f"  Deleted trunk: {t.sip_trunk_id}")
        except Exception as e:
            print(f"  Error deleting trunks: {e}")

        print("Done!")
    finally:
        await lk.aclose()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--delete":
        asyncio.run(delete_sip_config())
    else:
        asyncio.run(setup_sip_trunk())
