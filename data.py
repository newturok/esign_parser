from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import requests
from typing import Tuple, Union
from time import sleep

from loguru import logger

from utils.ecp.api_response import EcpApiResponse
from utils.ecp.chrome_data import ChromeEcpData, ChromeSignature


@dataclass
class Signature:
    input: dict
    skip_init: bool = False
    date: datetime = None
    edrpou: str = None
    rnokpp: str = None
    pib: str = None
    position: str = None
    organization: str = None
    is_seal: bool = None
    is_fo: bool = None

    def __post_init__(self):
        if self.skip_init:
            return

        self.date = self.get_date()
        if self.date is None:
            return
        self.edrpou = self.input['subjEDRPOUCode']
        self.rnokpp = self.input['subjDRFOCode']
        self.pib = self.input['subjFullName']
        self.position = self.input['subjTitle']
        self.organization = self.input['subjOrg']
        self.check_seal()
        self.check_fo()

    def get_date(self):
        ecp_time = self.input['time']
        if self.input['time']['wYear'] == 0:
            return
        remove_w_ecp_time_dict = {k[1:]: v for k, v in ecp_time.items()}
        ecp_time_dict = {k.lower(): v for k, v in remove_w_ecp_time_dict.items() if
                         k not in ['DayOfWeek', 'Milliseconds']}
        return datetime(**ecp_time_dict)

    def check_seal(self):
        empty_pib = self.pib.strip() == ''
        position_is_seal = 'печатка' in self.position.lower()
        self.is_seal = any([empty_pib, position_is_seal])

    def check_fo(self):
        self.is_fo = self.organization.lower() == 'фізична особа'


@dataclass
class EcpData:
    # Input data
    input: Union[bytes, str, Path]
    # Flow data
    is_valid: bool = False
    comments: Tuple[str] = ()
    # Processing data
    ecp_api_response: EcpApiResponse = None
    # Output data
    signatures: Tuple[Signature] = ()
    unarchived_bytes: bytes = None

    def __post_init__(self):
        # Processing block
        self.get_ecp_api_response()
        if not self.ecp_api_response or not self.ecp_api_response.is_valid:
            if self.ecp_api_response:
                self.comments += self.ecp_api_response.comments
        # Output block
        self.get_signatures_and_bytes()
        # Validation block
        self.is_valid = self.validate()

    def get_ecp_api_response(self):
        try:
            self.ecp_api_response = EcpApiResponse(self.input)
        except:
            return

    def get_signatures_and_bytes(self):
        # Якщо наше АПІ не справляється з підписом, то переключаємося на селеніум
        if not self.ecp_api_response or not self.ecp_api_response.response_dict or self.ecp_api_response.response_dict['result_code'] in [
            82, 83, 85, 50, 33
        ]:
            logger.warning('CHROME PARSING')
            chrome_ecp_data = ChromeEcpData(self.input)
            self.signatures = tuple(compose_signature_from_chrome_signature(sign) for sign in chrome_ecp_data.signatures)
            self.unarchived_bytes = chrome_ecp_data.unarchived_bytes
            return

        if self.ecp_api_response.response_dict['result_code'] in [1]:
            logger.warning('Loop api requests until library is initialized')
            sleep(15)
            self.__post_init__()
            return

        # Якщо ми відправили АПІ не підпис, то виходимо
        if self.ecp_api_response.response_dict['result_code'] in [2, -1]:
            self.comments += ('Не подібно на те, що даний файл є підписаним контентом',)
            return

        self.signatures = tuple(Signature(signature) for signature in self.ecp_api_response.signatures)
        self.unarchived_bytes = self.ecp_api_response.unarchived_bytes

    def validate(self):
        checks = [
            (self.has_signatures, 'Не вдалося визначити ні одного підпису на файлі'),
            (self.no_fo, 'Накладено підпис фізичної особи'),
        ]

        return all([validation for validation, text in checks])

    @property
    def has_exactly_one_signature(self):
        return len(self.signatures) == 1

    @property
    def has_more_than_one_signature(self):
        return len(self.signatures) > 1

    @property
    def has_signatures(self):
        return len(self.signatures) > 0

    @property
    def no_fo(self):
        return len([x for x in self.signatures if x.is_fo]) == 0


def compose_signature_from_chrome_signature(chrome_signature: ChromeSignature) -> Signature:
    return Signature(
        input=chrome_signature.input_dict,
        skip_init=True,
        date=chrome_signature.date,
        edrpou=chrome_signature.edrpou,
        rnokpp=chrome_signature.rnokpp,
        pib=chrome_signature.pib,
        position=chrome_signature.position,
        organization=chrome_signature.organization,
        is_seal=chrome_signature.is_seal,
    )
