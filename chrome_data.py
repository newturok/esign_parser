from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
from time import sleep
from typing import Tuple, Union

from bots.shared.utils.selenium import Chrome
import selenium
from retrying import retry


@dataclass
class ChromeSignature:
    input: str
    input_dict: dict = None
    date: datetime = None
    edrpou: str = None
    rnokpp: str = None
    pib: str = None
    position: str = None
    organization: str = None
    is_seal: bool = None
    is_fo: bool = None

    def __post_init__(self):
        self.get_input_dict()
        self.get_edrpou()
        self.get_rnokpp()
        self.get_organization()
        self.get_pib()
        self.get_position()
        self.get_date()
        self.check_seal()
        self.check_fo()

    def get_input_dict(self):
        raw_dict = {line.split(': </b>')[0].replace('"><b>', ''): line.split(': </b>')[1].split('</font>')[0]
                    for line in self.input.split('black') if ': </b>' in line}
        self.input_dict = raw_dict

    def get_edrpou(self):
        self.edrpou = self.input_dict.get('Код ЄДРПОУ', '')

    def get_rnokpp(self):
        self.rnokpp = self.input_dict.get('РНОКПП', 'НЕВІДОМО')

    def get_organization(self):
        org_keys = [x for x in self.input_dict if 'організація' in x.lower()]
        if org_keys:
            self.organization = self.input_dict.get(org_keys[0])
        else:
            self.organization = 'ФОП'

    def get_pib(self):
        pib_keys = [x for x in self.input_dict if 'підписувач' in x.lower()]
        self.pib = self.input_dict.get(pib_keys[0]) if pib_keys else ''

    def get_position(self):
        keys = [x for x in self.input_dict if 'Посада' in x]
        self.position = self.input_dict.get(keys[0]) if keys else None

    def get_date(self):
        key = [x for x in self.input_dict if 'Час' in x][0]
        self.date = datetime.strptime(self.input_dict[key], '%H:%M:%S %d.%m.%Y')

    def check_seal(self):
        sign_keys = [x for x in self.input_dict if 'печатка' in x.lower()]
        self.is_seal = any([
            any(sign_keys),
            self.pib is None
        ])

    def check_fo(self):
        self.is_fo = self.organization.lower() == 'фізична особа'


@dataclass
class ChromeEcpData:
    input: Union[bytes, str, Path]
    chrome: Chrome = None
    chrome_temp: Path = None
    is_valid: bool = False
    comments: Tuple[str] = ()
    input_path: Path = None
    signatures_html: str = None
    file_path: Path = None
    signatures: Tuple[ChromeSignature] = ()
    unarchived_bytes: bytes = None

    @retry(stop_max_attempt_number=2)
    def __post_init__(self):
        self.get_input_path()
        self.get_chrome()
        self.get_signatures_html()
        self.quit_chrome()
        if not self.signatures_html:
            return
        self.get_signatures()
        self.get_unarchived_bytes()

    def get_input_path(self):
        self.chrome_temp = Path.home() / 'chrome_temp'
        self.chrome_temp.mkdir(parents=True, exist_ok=True)

        if isinstance(self.input, bytes):
            with tempfile.NamedTemporaryFile(dir=self.chrome_temp, delete=False) as temp_file:
                temp_file.write(self.input)
                self.input_path = self.chrome_temp / temp_file.name
                return

        if isinstance(self.input, str):
            self.input_path = Path(self.input)
            return

        if isinstance(self.input, Path):
            self.input_path = self.input
            return

    def get_chrome(self):
        self.chrome = Chrome(download_directory=str(self.chrome_temp))

    def get_signatures_html(self):
        self.chrome.go('https://id.gov.ua/verify-widget/v20200519/?address=https://czo.gov.ua')
        self.chrome.get_by_xpath('//input[@id="chooseFilesInput"]').send_keys(str(self.input_path))
        self.chrome.wait_until_invisible('//div[@id="DimmerViewMessage"]')
        try:
            download_button = self.chrome.wait_until_xpath('//a[@id="saveDataFileButton"]', timeout=20)
        # TODO catch only invalid files а не любий таймаут по відстутності кнопки завантаження
        except selenium.common.exceptions.TimeoutException:
            return
        self.signatures_html = self.chrome.html_by_xpath('//div[@id="signResults"]')
        self.process_filename()
        download_button.click()
        sleep(3)
        assert self.file_path.exists()

    def quit_chrome(self):
        self.chrome.driver.quit()

    def process_filename(self):
        filename = self.signatures_html.split('Назва файлу без підпису: </b>')[1].split('</font>')[0]
        self.file_path = self.chrome_temp / filename
        # Видаляємо файл з директорії скачування хрома, щоб не читати звідти стару версію файла
        if self.file_path.exists():
            self.file_path.unlink()

    def get_signatures(self):
        self.signatures = tuple(ChromeSignature(sign) for sign in self.signatures_html.split('Тип') if 'ЄДРПОУ' in sign or 'РНОКПП' in sign)

    def get_unarchived_bytes(self):
        self.unarchived_bytes = self.file_path.read_bytes()
