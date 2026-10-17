"""Application errors independent of the model provider and HTTP layer."""


class InvalidModelOutput(Exception):
    """The provider returned incomplete, refused, or invalid business output."""
