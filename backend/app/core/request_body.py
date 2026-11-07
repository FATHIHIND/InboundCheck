"""Bounded raw-body ingestion preserving the exact bytes used for signatures."""
from fastapi import HTTPException, Request


async def read_body_with_limit(request: Request, max_bytes: int = 1_048_576) -> bytes:
    if max_bytes <= 0:
        raise ValueError("Body limit must be positive")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        # Reject invalid/negative/ambiguous declarations; never trust the declared
        # length as a substitute for counting the bytes actually received.
        if not content_length.isascii() or not content_length.isdecimal():
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")
        if len(content_length) > 20 or int(content_length) > max_bytes:
            raise HTTPException(status_code=413, detail="Payload exceeds maximum size limit")
    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            # Stop consuming immediately. In particular, do not drain an unbounded
            # chunked upload or append the over-limit chunk to our retained buffer.
            raise HTTPException(status_code=413, detail="Payload exceeds maximum size limit")
        chunks.append(chunk)
    return b"".join(chunks)
