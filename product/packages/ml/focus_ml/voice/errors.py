"""Voice-pipeline errors reuse the ML error base (message is user-safe)."""
from ..errors import MlError, ModelUnavailableError


class EnrollmentError(MlError):
    """The enrollment sample is insufficient; the message says why."""
    code = "ENROLLMENT_REFUSED"


__all__ = ["MlError", "ModelUnavailableError", "EnrollmentError"]
