"""Execution adapter for dynamically registered provider agents."""

import asyncio
import time
from typing import Optional

from fastapi import HTTPException

from agents.common.azure_agent_client import AzureAgentClient
from config import settings
from services.agent_registry_service import validate_public_https_endpoint
from utils.logger import get_logger


logger = get_logger(__name__)


def _build_foundry_client(endpoint: str, provider_agent_id: str) -> AzureAgentClient:
    return AzureAgentClient(provider_agent_id, endpoint=endpoint)


async def test_registered_foundry_agent(agent: dict) -> dict:
    config = agent.get("provider_config") or {}
    endpoint = str(config.get("endpoint") or "")
    provider_agent_id = str(config.get("provider_agent_id") or "")
    if not endpoint or not provider_agent_id:
        raise HTTPException(status_code=400, detail="Registered provider configuration is incomplete")
    await validate_public_https_endpoint(endpoint)

    started = time.perf_counter()
    try:
        client = await asyncio.wait_for(
            asyncio.to_thread(_build_foundry_client, endpoint, provider_agent_id),
            timeout=settings.AGENT_REGISTRY_TEST_TIMEOUT_SECONDS,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {"provider_name": client.agent_name, "latency_ms": latency_ms}
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Foundry connection test timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Foundry connection test failed for agent %s", agent.get("agent_id"))
        raise HTTPException(status_code=502, detail="Foundry connection test failed") from exc


async def run_registered_agent(
    agent: dict,
    message: str,
    provider_thread_id: Optional[str],
) -> dict:
    if agent.get("runtime_type") != "azure_ai_foundry":
        raise HTTPException(status_code=400, detail="Registered runtime type is not supported")

    config = agent.get("provider_config") or {}
    endpoint = str(config.get("endpoint") or "")
    provider_agent_id = str(config.get("provider_agent_id") or "")
    if not endpoint or not provider_agent_id:
        raise HTTPException(status_code=503, detail="Registered provider configuration is incomplete")
    await validate_public_https_endpoint(endpoint)

    def execute() -> dict:
        client = _build_foundry_client(endpoint, provider_agent_id)
        return client.run_analysis(message, provider_thread_id)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(execute),
            timeout=settings.AGENT_REGISTRY_RUN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Registered agent timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Registered Foundry execution failed for agent %s", agent.get("agent_id"))
        raise HTTPException(status_code=502, detail="Registered agent provider failed") from exc

    if result.get("status") == "failed":
        raise HTTPException(status_code=502, detail="Registered agent provider failed")
    if not str(result.get("response") or "").strip():
        raise HTTPException(status_code=502, detail="Registered agent returned an empty response")
    return result

