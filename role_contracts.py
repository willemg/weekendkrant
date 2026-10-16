"""Bounded creation-time input, never an execution-time configuration lookup."""
import hashlib

MAX_CONTRACT_BYTES = 65536


def load_contract(path):
    """Return SHA-256 ref and exact UTF-8 content, preserving CRLF and whitespace.

    Read at most one byte beyond the limit. Callers snapshot this result before
    dispatch; bind/recovery/replay must never call this loader.
    """
    with path.open("rb") as source:
        data = source.read(MAX_CONTRACT_BYTES + 1)
    if len(data) > MAX_CONTRACT_BYTES:
        raise ValueError("Runtime contract byte budget exceeded")
    content = data.decode("utf-8")
    if not content.strip():
        raise ValueError("Expected nonempty runtime contract")
    return "sha256:" + hashlib.sha256(data).hexdigest(), content
