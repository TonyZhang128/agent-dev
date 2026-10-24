"""Explicit identity and first-turn context for legacy contract test scenarios."""


def request_payload(payload):
    context = {"user_id": "test-user", "session_id": "test-session"}
    if "text" in payload or "message" in payload:
        context["history"] = []
    return context | payload
