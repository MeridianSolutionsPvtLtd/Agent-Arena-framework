import re
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def repair_json(json_str: str) -> str:
    """Semi-robustly repair a truncated JSON string by closing open braces and brackets."""
    json_str = json_str.strip()
    if not json_str:
        return "{}"
    
    # Remove trailing commas or colons which break parsing
    json_str = re.sub(r'[,\:]\s*$', '', json_str)
    
    stack = []
    is_in_string = False
    is_escaped = False
    
    # Track nesting
    for i, char in enumerate(json_str):
        if is_escaped:
            is_escaped = False
            continue
        if char == '\\':
            is_escaped = True
            continue
        if char == '"':
            is_in_string = not is_in_string
            continue
        if is_in_string:
            continue
        if char == '{':
            stack.append('}')
        elif char == '[':
            stack.append(']')
        elif char == '}':
            if stack and stack[-1] == '}':
                stack.pop()
        elif char == ']':
            if stack and stack[-1] == ']':
                stack.pop()
    
    # If we are in a string at the end, close it
    if is_in_string:
        json_str += '"'
    
    # Close all remaining open blocks in reverse order
    while stack:
        json_str += stack.pop()
        
    return json_str

def extract_json_from_response(raw_content: str, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Robustly extract JSON from an LLM response.
    Tries multiple extraction methods and attempts to repair truncated JSON.
    """
    safe_fallback = fallback if fallback is not None else {"error": "Failed to parse analysis results"}
    
    # Ensure raw_content is a string
    if not isinstance(raw_content, str):
        logger.error(f"raw_content is not a string: {type(raw_content)}")
        return safe_fallback

    # 1. Try JSON code blocks
    block_matches = list(re.finditer(r"```json\s*([\s\S]*?)\s*```", raw_content))
    for match in block_matches:
        content = match.group(1).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                repaired = repair_json(content)
                return json.loads(repaired)
            except Exception:
                continue

    # 2. Try any code blocks
    block_matches = list(re.finditer(r"```\s*([\s\S]*?)\s*```", raw_content))
    for match in block_matches:
        content = match.group(1).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                repaired = repair_json(content)
                return json.loads(repaired)
            except Exception:
                continue

    # 3. Try direct JSON parse
    try:
        return json.loads(raw_content.strip())
    except json.JSONDecodeError:
        pass

    # 4. Try to find the first '{' and last '}'
    start_idx = raw_content.find('{')
    if start_idx != -1:
        # Search for the last '}'
        end_idx = raw_content.rfind('}')
        if end_idx != -1 and end_idx > start_idx:
            content = raw_content[start_idx:end_idx+1]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                try:
                    repaired = repair_json(content)
                    return json.loads(repaired)
                except Exception:
                    pass
        else:
            # Only opening brace found, likely truncated
            content = raw_content[start_idx:]
            try:
                repaired = repair_json(content)
                return json.loads(repaired)
            except Exception:
                pass

    logger.error(f"Could not extract JSON from response. Raw: {raw_content[:500]}...")
    return safe_fallback
