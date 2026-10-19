"""One error type with stable codes and idiomatic English messages for API clients."""

MESSAGES = {
    "bad_request": "The request could not be understood. Send a JSON object with a short search phrase.",
    "bad_json": "The request body must be valid JSON.",
    "payload_too_large": "That request is too large.",
    "unsupported_media_type": "Requests must use Content-Type: application/json.",
    "forbidden_origin": "This request came from a different origin and was refused.",
    "not_found": "That page or resource does not exist.",
    "method_not_allowed": "That method is not allowed here.",
    "unknown_artwork": "That artwork is not in the gallery.",
    "unknown_topic": "That topic is not available for this artwork.",
    "session_not_found": "That research session has expired or does not exist.",
    "research_disabled": "The Research Guide is turned off on this server.",
    "rate_limited": "Too many searches in a short time. Please wait a moment and try again.",
    "internal_error": "Something went wrong on the server. Please try again.",
    "url_rejected": "That address is not on the list of allowed reference sites.",
    "ip_literal_rejected": "IP addresses are not allowed as source hosts.",
    "non_public_address": "That host resolves to a non-public address and was blocked.",
    "dns_failed": "A source site could not be reached (DNS lookup failed).",
    "fetch_failed": "A source site could not be read.",
    "oversize": "A source response was larger than the allowed limit.",
    "provider_error": "A source site returned an error.",
    "nebius_key_unavailable": "NEBIUS_API_KEY is not set on the server, so the Nemotron writer is unavailable.",
    "nebius_input_limit": "The evidence was too large to send to the model.",
    "nebius_http_401": "Nebius rejected the API key (HTTP 401).",
    "nebius_http_403": "Nebius refused the request (HTTP 403).",
    "nebius_http_404": "Nebius could not find the requested model or endpoint (HTTP 404).",
    "nebius_http_429": "Nebius rate-limited the request (HTTP 429). Try again shortly.",
    "nebius_oversize": "The model response was larger than the allowed limit.",
    "nebius_model_mismatch": "Nebius answered with a different model than the one requested.",
    "nebius_incomplete": "The model response was cut off or used a tool call.",
    "nebius_schema": "The model response did not match the required format.",
    "nebius_timeout": "The model took too long to answer.",
    "nebius_unavailable": "The Nebius Token Factory could not be reached.",
    "ungrounded": "The model's draft could not be tied to the fetched sources.",
    "cancelled": "The search was cancelled.",
}


class ResearchError(RuntimeError):
    def __init__(self, code, detail=""):
        super().__init__(detail or code)
        self.code = code


class ApiError(Exception):
    """An HTTP-level API failure rendered as {"ok": false, "error": {...}}."""

    def __init__(self, status, code, message=None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message or MESSAGES.get(code, MESSAGES["internal_error"])


def message_for(code):
    if code in MESSAGES:
        return MESSAGES[code]
    if isinstance(code, str) and code.startswith("nebius_http_"):
        return "Nebius returned an unexpected error (HTTP %s)." % code.rsplit("_", 1)[-1]
    return MESSAGES["internal_error"]
