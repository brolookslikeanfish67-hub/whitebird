import os
import sys
import logging
from json import dumps
from pathlib import Path
from typing import Dict, Any, List, Union
from urllib.parse import urlencode

# Standard path resolution using Path objects
SRC_ROOT = Path(__file__).resolve().parents / "src"
sys.path.append(str(SRC_ROOT))

from ..utils.http_client import do_sync_request
from ..utils.log import logError
from ..utils.parse import extractMetadata

# Centralized App Identity Parameter Keys
IG_WEB_APP_ID = "936619743392459"
IG_RECOVERY_APP_ID = "124024574287414"

# Modular Data Schemas
PROFILE_SCHEMA = [
    {"schema": "JSON", "type": "String", "name": "User ID", "path": ["user", "pk_id"]},
    {"schema": "JSON", "type": "String", "name": "Full Name", "path": ["user", "full_name"]},
    {"schema": "JSON", "type": "String", "name": "Biography", "path": ["user", "biography"]},
    {"schema": "JSON", "type": "String", "name": "Follower Count", "path": ["user", "follower_count"]},
    {"schema": "JSON", "type": "String", "name": "Following Count", "path": ["user", "following_count"]},
    {"schema": "JSON", "type": "String", "name": "External URL", "path": ["user", "external_url"]},
    {"schema": "JSON", "type": "String", "name": "Category", "path": ["user", "category"]},
    {"schema": "JSON", "type": "String", "name": "Is Verified", "path": ["user", "is_verified"]},
]

RECOVERY_SCHEMA = [
    {"schema": "JSON", "type": "String", "name": "Email Sent", "path": ["email_sent"]},
    {"schema": "JSON", "type": "String", "name": "SMS Sent", "path": ["sms_sent"]},
    {"schema": "JSON", "type": "String", "name": "WhatsApp Sent", "path": ["wa_sent"]},
    {"schema": "JSON", "type": "String", "name": "Obfuscated Email", "path": ["obfuscated_email"]},
    {"schema": "JSON", "type": "String", "name": "Obfuscated Phone", "path": ["obfuscated_phone"]},
    {"schema": "JSON", "type": "String", "name": "Is Private", "path": ["user", "is_private"]},
    {"schema": "JSON", "type": "String", "name": "Has Valid Phone", "path": ["has_valid_phone"]},
    {"schema": "JSON", "type": "String", "name": "Can Email Reset", "path": ["can_email_reset"]},
    {"schema": "JSON", "type": "String", "name": "Can SMS Reset", "path": ["can_sms_reset"]},
    {"schema": "JSON", "type": "String", "name": "Can WhatsApp Reset", "path": ["can_wa_reset"]},
    {"schema": "JSON", "type": "String", "name": "Facebook Login Option", "path": ["fb_login_option"]},
    {"schema": "JSON", "type": "String", "name": "Status", "path": ["status"]},
]


def create_safe_response_wrapper(raw_response: Any) -> Dict[str, Any]:
    """Generates structural interface mocks containing safety parameter fields.
    
    Prevents downstream extraction routines from triggering missing key failures.
    """
    if not raw_response:
        return {"json": {}, "content": "", "status_code": 0, "url": ""}
        
    try:
        json_payload = raw_response.json() if hasattr(raw_response, "json") else {}
    except Exception:
        json_payload = {}

    return {
        "json": json_payload,
        "content": getattr(raw_response, "text", ""),
        "status_code": getattr(raw_response, "status_code", 200),
        "url": getattr(raw_response, "url", "")
    }


def get_user_id(username: str, session_id: str, config: Any) -> Union[str, bool]:
    """Queries Instagram's front-end JSON profile endpoints for underlying object IDs."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X)",
            "X-IG-App-ID": IG_WEB_APP_ID
        }
        cookies = {"sessionid": session_id}
        endpoint = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"

        response = do_sync_request(
            method="GET",
            url=endpoint,
            config=config,
            data=None,
            customHeaders=headers,
            cookies=cookies,
        )
        
        if not response:
            return False

        data = response.json()
        user_id = data.get("data", {}).get("user", {}).get("id")
        
        if user_id:
            if getattr(config, "verbose", False):
                config.console.print(f"[bold green][Instagram][/bold green] Acquired target ID for: {username}")
            return str(user_id)
            
        return False
        
    except Exception as network_fault:
        logError(network_fault, f"[Instagram] ID collection pass failed for: {username}", config)
        return False


def get_instagram_account_info(username: str, session_id: str, config: Any) -> List[Dict[str, Any]]:
    """Gathers profile state parameters and recovery account signatures."""
    extracted_metadata: List[Dict[str, Any]] = []
    cookies = {"sessionid": session_id}

    try:
        # Phase 1: Establish Target Identity Footings
        user_id = get_user_id(username, session_id, config)
        if not user_id:
            return extracted_metadata

        # Phase 2: Structural Profile Metadata Processing
        profile_url = f"https://i.instagram.com/api/v1/users/{user_id}/info/"
        headers_profile = {"User-Agent": "Instagram 55.0.0.00.0 (Android; 23)"}
        
        response_profile = do_sync_request(
            method="GET",
            url=profile_url,
            config=config,
            data=None,
            customHeaders=headers_profile,
            cookies=cookies,
        )
        
        wrapped_profile = create_safe_response_wrapper(response_profile)
        if wrapped_profile["json"]:
            meta_profile = extractMetadata(PROFILE_SCHEMA, wrapped_profile, "Instagram", config)
            if meta_profile:
                extracted_metadata.extend(meta_profile)

        # Phase 3: Obfuscated Endpoint Recovery Lookup Processing
        json_body = dumps({"q": username, "skip_recovery": "1"}, separators=(",", ":"))
        
        # Simulates Instagram's standard signed body encryption structure pattern safely
        encoded_payload = urlencode({"signed_body": f"SIGNATURE.{json_body}"})
        
        headers_recovery = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-IG-App-ID": IG_RECOVERY_APP_ID,
            "User-Agent": "Instagram 103.0.0.0.1 (Android; 25)",
        }

        response_recovery = do_sync_request(
            method="POST",
            url="https://i.instagram.com/api/v1/users/lookup/",
            config=config,
            data=encoded_payload,
            customHeaders=headers_recovery,
            cookies=cookies
        )
        
        wrapped_recovery = create_safe_response_wrapper(response_recovery)
        if wrapped_recovery["json"]:
            meta_recovery = extractMetadata(RECOVERY_SCHEMA, wrapped_recovery, "Instagram", config)
            if meta_recovery:
                extracted_metadata.extend(meta_recovery)

        return extracted_metadata

    except Exception as pipeline_fault:
        logError(pipeline_fault, f"[Instagram] Fault during structural asset compilation for: {username}", config)
        return extracted_metadata
