from urllib.error import HTTPError

from tools.windows_worker import failure_code


def test_http_status_is_not_sent_as_provider_code():
    assert failure_code(HTTPError('http://localhost', 400, 'bad request', {}, None)) == 'PROCESSING_FAILED'


def test_provider_code_is_preserved():
    exc = RuntimeError('model unavailable')
    exc.code = 'MODEL_UNAVAILABLE'
    assert failure_code(exc) == 'MODEL_UNAVAILABLE'


def test_plain_exception_gets_generic_code():
    assert failure_code(RuntimeError()) == 'PROCESSING_FAILED'
