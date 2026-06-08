# exam/utils/exception_handler.py

"""
DRF 统一异常处理器（§4.1 统一响应格式）
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.exceptions import AuthenticationFailed, ValidationError, NotFound

logger = logging.getLogger('exam')


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        errors = response.data

        if isinstance(exc, AuthenticationFailed):
            code = 1005
        elif isinstance(exc, NotFound):
            code = 1006
        elif isinstance(exc, ValidationError):
            code = 1011
        else:
            code = 9999

        if isinstance(errors, dict):
            first_key = list(errors.keys())[0]
            first_value = errors[first_key]
            message = str(first_value[0]) if isinstance(first_value, list) else str(first_value)
        elif isinstance(errors, list):
            message = str(errors[0])
        else:
            message = str(errors)

        response.data = {'code': code, 'data': None, 'message': message}
    else:
        logger.exception('未预期的异常: %s', exc)
        from rest_framework.response import Response
        from rest_framework import status
        response = Response(
            {'code': 9999, 'data': None, 'message': '服务器内部错误'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response