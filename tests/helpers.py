"""为既有契约测试场景提供明确的身份和首轮上下文。"""


def request_payload(payload):
    context = {"user_id": "test-user", "session_id": "test-session"}
    if "text" in payload or "message" in payload:
        context["history"] = []
    return context | payload
