"""Build SHA-256 envelopes using the generated reader's shape contract.

Callers own serialization and encoding; this leaf only hashes the supplied bytes.
"""
from __future__ import annotations

import hashlib

from .content_digest import ENVELOPED_SHA256_PATTERN


def enveloped_sha256(data: bytes) -> str:
    """Return the canonical envelope, failing if the recognition contract drifts."""
    value = "sha256:" + hashlib.sha256(data).hexdigest()
    if ENVELOPED_SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("SHA-256 writer output does not match the recognition contract")
    return value
