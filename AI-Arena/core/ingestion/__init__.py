"""
core.ingestion - the multimodal trust boundary.

User supplied content of any modality becomes prompt ready text here and only
here. This package sits below every transport (agent_run, the arena routers)
and above the modality services. It must never import a router, never perform
authentication, and never call the application over HTTP.

Layering:

    transport   core/agent_run.py, core/arena/playground/routers/*
                     |   auth, quotas, HTTP shapes, hit counters
                     v
    boundary    core/ingestion/            <- the only place bytes become text
                     |   sanitize, injection scan, size/type policy, audit
                     v
    adapters    core/services/             <- move arena/playground/services here
                     |   Azure clients that take `credentials` and return data
                     v
    providers   Azure Speech / Document Intelligence / Vision

Moving the services package:

    1. git mv core/arena/playground/services core/services
    2. Leave one-line re-export shims behind for the arena routers, e.g.
       core/arena/playground/services/speech_service.py:
           from core.services.speech_service import *  # noqa: F401,F403
    3. Change _SERVICES_PKG in core/ingestion/extractors.py to "core.services".

Nothing else in this package references arena, so that constant is the only
edit the ingestion layer needs.

Usage:

    from core.ingestion import InputNormalizer, IngestionRejected

    attachment = await InputNormalizer.normalize_file(
        data, filename, content_type, user_id=user_id, file_id=file_id
    )
    normalized = await InputNormalizer.normalize_request(query, [attachment])
    context_block = InputNormalizer.render_attachment_block(normalized["attachments"])
"""

from core.ingestion.extractors import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PARTIAL,
)
from core.ingestion.normalizer import IngestionRejected, InputNormalizer

__all__ = [
    "InputNormalizer",
    "IngestionRejected",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_EMPTY",
    "STATUS_FAILED",
]