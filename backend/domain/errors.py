class ResearchError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int = 422, retry_after: float | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after
