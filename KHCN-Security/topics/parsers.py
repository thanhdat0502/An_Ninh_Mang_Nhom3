from io import BytesIO

from rest_framework.exceptions import APIException
from rest_framework.parsers import JSONParser


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = "Nội dung yêu cầu vượt giới hạn 64 KiB."


class BoundedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        content = stream.read(65537)
        if len(content) > 65536:
            raise PayloadTooLarge()
        return super().parse(BytesIO(content), media_type, parser_context)
