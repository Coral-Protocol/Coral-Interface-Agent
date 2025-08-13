import os
import logging
import json
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def parse_mentions_response(response: str) -> List[Dict[str, str]]:
    """
    Parse the XML-like mentions response into a list of message dictionaries.
    """
    try:
        if not response or not isinstance(response, str):
            logger.info("Empty or non-string mentions response")
            return []
        
        root = ET.fromstring(response)
        messages = []
        
        for msg in root.findall(".//ResolvedMessage"):
            message = {
                "threadId": msg.get("threadId"),
                "senderId": msg.get("senderId"),
                "content": msg.get("content")
            }
            if all(message.values()):
                messages.append(message)
        
        # logger.info(f"Parsed {len(messages)} messages")
        return messages
    except ET.ParseError as e:
        return []
    except Exception as e:
        logger.error(f"Unexpected parsing error: {str(e)}")
        return []

def mcp_resources_details(resources):
    results = []
    for i, resource in enumerate(resources, 1):
        # logger.info(f"Resource {i}:")
        try:
            resource_details = {
                "data": getattr(resource, "data", None)
            }
            results.append({"resource": i, "details": resource_details, "status": "success"})
        except Exception as e:
            logger.info(f"Resource raw: {str(resource)}")
            logger.error(f"Failed to parse resource details: {str(e)}")
            results.append({"resource": i, "error": str(e), "status": "failed"})

    # logger.info(f"Coral Server Resources: {results}")
    return results