from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Extend DRF's default handler to surface the error code and Retry-After.

    Adds a top-level ``"code"`` key to every API error response so clients
    can distinguish e.g. ``budget_exceeded`` from generic ``throttled``
    without parsing the human-readable ``detail`` string.

    Also copies ``exc.wait`` (seconds) into the ``Retry-After`` response
    header for any exception that carries it (DRF's Throttled and our
    GenerationBudgetExceeded both do).
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return response

    # Lift the error code out of ErrorDetail so clients can key on it.
    detail = response.data.get("detail") if isinstance(response.data, dict) else None
    if hasattr(detail, "code"):
        response.data["code"] = detail.code

    # Set Retry-After header whenever the exception knows how long to wait.
    wait = getattr(exc, "wait", None)
    if wait is not None:
        response["Retry-After"] = str(int(wait))

    return response
