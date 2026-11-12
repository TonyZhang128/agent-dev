"""与模型提供方和 HTTP 层无关的应用错误。"""


class InvalidModelOutput(Exception):
    """模型提供方返回了不完整、被拒绝或不符合业务约定的输出。"""


class ConversationInputTooLarge(Exception):
    """固定输入无法放入预算，或未裁剪的请求超过大小上限。"""


class JournalGenerationError(Exception):
    """监理日记工作内容无法可靠生成；HTTP 层返回受控 502。"""


class JournalFrameNotFound(Exception):
    """没有找到通过监理日记模板结构核验的真实表格，不得继续OCR。"""
