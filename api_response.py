import base64
from dataclasses import dataclass
import json
import requests
from pathlib import Path
from typing import Tuple, Union, Any
import random
import string

from retrying import retry
from loguru import logger


@dataclass
class EcpApiResponse:
    # Input data
    input: Union[bytes, str, Path]
    # Flow data
    debug: bool = False
    is_valid: bool = False
    comments: Tuple[str] = ()
    # Processing data
    input_bytes: bytes = None
    request_dict: dict = None
    raw_response: requests.Response = None
    response_dict = None
    # Output data
    signatures: dict = None
    unarchived_bytes: bytes = None

    def __post_init__(self):
        # Flow block
        if self.debug:
            return
        # Processing block
        self.input_bytes = self.get_input_bytes()
        self.request_dict = self.get_request_dict()
        self.raw_response = self.get_raw_response()
        self.response_dict = self.get_response_dict()
        if not self.response_dict:
            return

        # Output block
        self.signatures = self.response_dict.get('signatures')
        self.unarchived_bytes = self.get_unarchived_bytes()
        # Validation block
        self.is_valid, self.comments = self.validate()

    def get_input_bytes(self):
        return self.input if isinstance(self.input, bytes) else Path(self.input).read_bytes()

    def get_request_dict(self):
        file_b64 = base64.b64encode(self.input_bytes).decode('utf-8')
        filename = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10)) + '.p7s'
        return {'content_encoding': 'base64', 'file_body': file_b64, 'file_name': filename}

    def get_raw_response(self):
        url = 'http://10.20.4.39/api/values'
        data = json.dumps(self.request_dict)
        headers = {'Content-Type': 'application/json'}
        return requests.put(url=url, data=data, headers=headers)

    def get_response_dict(self):
        if not self.raw_response.ok:
            error_text = f'API СЕРВЕР ЛІГ. Напиши на сервісдеск Ярмоленку, що його потрібно воскресити'
            self.comments += (error_text,)
            logger.critical(f'{error_text}, {self.raw_response.status_code}, {self.raw_response.reason}')
            return
        return self.raw_response.json()

    def get_unarchived_bytes(self):
        file_body = self.response_dict.get('file_body')
        if file_body:
            return base64.b64decode(file_body)

    def validate(self):
        if self.response_dict['result_code'] == -1:
            self.comments += (self.response_dict['result_text'],)

        checks = [
            (self.has_correct_result_code, 'Проблеми на стороні нашого АПІ по парсингу ЕЦП'),
        ]
        return all([validation for validation, text in checks]), tuple(text for validation, text in checks if not validation)

    @property
    def has_correct_result_code(self):
        return self.response_dict['result_code'] == 0
