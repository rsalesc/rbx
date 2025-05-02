import datetime
import hashlib
import os
import pathlib
import re
import typing
from typing import Any, NoReturn, Optional, Tuple

import dateparser
import mechanize
import typer
from bs4 import BeautifulSoup

from rbx import console
from rbx.box import naming

ALERT_REGEX = re.compile(r'\<script[^\>]*\>\s*alert\(\'([^\']+)\'\);?\s*\<\/script\>')
UPLOAD_LOG_REGEX = re.compile(r'Problem (\d+) \([^\)]+\) updated')


def _parse_env_var(var: str, override: Optional[str]) -> str:
    if override is not None:
        return override
    value = os.environ.get(var)
    if value is None:
        console.console.print(
            f'[error][item]{var}[/item] is not set. Set it as an environment variable.[/error]'
        )
        raise typer.Exit(1)
    return value


class BocaUploader:
    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = _parse_env_var('BOCA_BASE_URL', base_url)
        self.username = _parse_env_var('BOCA_USERNAME', username)
        self.password = _parse_env_var('BOCA_PASSWORD', password)

        self.br = mechanize.Browser()
        self.br.set_handle_robots(False)
        self.br.addheaders = [  # type: ignore
            (
                'User-agent',
                'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1',
            )
        ]

    def error(self, message: str) -> NoReturn:
        console.console.print(
            f'[error]{message} (at [item]{self.base_url}[/item])[/error]',
        )
        raise typer.Exit(1)

    def raw_error(self, message: str) -> NoReturn:
        console.console.print(f'[error]{message}[/error]')
        raise typer.Exit(1)

    def log_response_alert(self, response: Any, message: str) -> Tuple[Any, str]:
        if response is None:
            self.raw_error(
                f'{message} ([item]{self.base_url}[/item]):\nNo response received.'
            )
        html = response.read().decode()
        alert = ALERT_REGEX.search(html)
        if alert:
            self.raw_error(
                f'{message} ([item]{self.base_url}[/item]):\n{alert.group(1)}'
            )
        return response, html

    def check_logs_for_update(self, problem_id: int) -> bool:
        _, html = self.open(
            f'{self.base_url}/admin/log.php',
            error_msg='Error while checking whether package upload was successful',
        )

        soup = BeautifulSoup(html, 'html.parser')
        table = soup.select_one('table:nth-of-type(3)')
        if table is None:
            self.raw_error(
                'Error while checking whether package upload was successful:\nNo logs table found.'
            )
        rows = table.select('tr:not(:first-child)')
        for row in rows:
            # Check whether the log line is recent.
            date_cell = row.select('td:nth-of-type(5)')
            if date_cell is None:
                continue
            date = date_cell[0].text.strip()

            parsed_date = dateparser.parse(date)
            if parsed_date is None:
                console.console.print(
                    f'Error while checking whether package upload was successful:\nCould not parse date [item]{date}[/item].'
                )
                raise typer.Exit(1)
            if parsed_date < datetime.datetime.now(
                datetime.timezone.utc
            ) - datetime.timedelta(minutes=1):
                continue

            # Check if the log line contains the problem id.
            log_cell = row.select('td:nth-of-type(6)')
            if log_cell is None:
                continue
            log_line = log_cell[0].text.strip()
            match = UPLOAD_LOG_REGEX.match(log_line)
            if match is None:
                continue
            found_id = int(match.group(1))
            if found_id == problem_id:
                return True
        return False

    def check_submit(self, response: Any, problem_id: int) -> bool:
        if response is None:
            self.raw_error(
                'Error while submitting problem to BOCA website:\nNo response received.'
            )
        html = response.read().decode()
        alert = ALERT_REGEX.search(html)
        if alert:
            msg = alert.group(1)
            if 'Violation' in msg:
                return False
            self.raw_error(
                f'Error while submitting problem to BOCA website:\n{alert.group(1)}'
            )
        return self.check_logs_for_update(problem_id)

    def open(self, url: str, error_msg: Optional[str] = None):
        if error_msg is None:
            error_msg = f'Error while opening [item]{url}[/item]'
        response = self.br.open(url)
        return self.log_response_alert(response, error_msg)

    def login(self):
        _, html = self.open(
            f'{self.base_url}', error_msg='Error while opening BOCA login page'
        )

        needle = "js_myhash(document.form1.password.value)+'"
        start = html.index(needle)
        start_salt = start + len(needle)
        end_salt = html.index("'", start_salt)
        salt = html[start_salt:end_salt]
        console.console.print(f'Using salt [item]{salt}[/item]')

        pwd_hash = hashlib.sha256(self.password.encode()).hexdigest()
        pwd_hash = hashlib.sha256((pwd_hash + salt).encode()).hexdigest()

        login_url = f'{self.base_url}?name={self.username}&password={pwd_hash}'
        self.open(login_url, error_msg='Error while logging in to BOCA')

    def upload(self, file: pathlib.Path) -> bool:
        self.open(
            f'{self.base_url}/admin/problem.php',
            error_msg='Error while opening BOCA problem upload page',
        )
        try:
            form = self.br.select_form(name='form1')
        except mechanize.FormNotFoundError:
            self.error(
                'Problem upload form not found in BOCA website. This might happen when the login failed.'
            )

        form = typing.cast(mechanize.HTMLForm, self.br.form)
        form.set_all_readonly(False)

        problem_index = naming.get_problem_index()
        if problem_index is None:
            console.console.print(
                'It seems this problem is not part of a contest. Cannot upload it to BOCA.'
            )
            raise typer.Exit(1)

        problem_shortname = naming.get_problem_shortname()
        assert problem_shortname is not None
        entry = naming.get_problem_entry_in_contest()
        assert entry is not None
        _, problem_entry = entry

        hex_color = problem_entry.hex_color
        if hex_color is None:
            form['colorname'] = 'black'
            form['color'] = '000000'
        else:
            assert problem_entry.color_name is not None
            form['colorname'] = problem_entry.color_name.lower()
            form['color'] = hex_color[1:]

        form['problemnumber'] = f'{problem_index + 1}'
        form['problemname'] = problem_shortname
        form['confirmation'] = 'confirm'
        form['autojudge_new_sel'] = ['all']
        form['Submit3'] = 'Send'

        with file.open('rb') as f:
            form.add_file(
                f,
                filename=file.name,
                name='probleminput',
                content_type='application/zip',
            )
            response = self.br.submit()

        return self.check_submit(response, problem_index + 1)

    def login_and_upload(self, file: pathlib.Path):
        RETRIES = 3

        tries = 0
        ok = False
        while tries < RETRIES:
            tries += 1

            console.console.print('Logging in to BOCA...')
            self.login()
            console.console.print('Uploading problem to BOCA...')
            if not self.upload(file):
                console.console.print(
                    f'[warning]Potentially transient error while uploading problem to BOCA. Retrying ({tries}/{RETRIES})...[/warning]'
                )
                continue

            ok = True
            console.console.print(
                '[success]Problem sent to BOCA. [item]rbx[/item] cannot determine the upload succeeded, check the website to be sure.[/success]'
            )
            break

        if not ok:
            console.console.print(
                '[error]Persistent error while uploading problem to BOCA website.[/error]'
            )
            console.console.print(
                '[warning]This might be caused by PHP max upload size limit (which usually defaults to 2MBF).[/warning]'
            )
            console.console.print(
                '[warning]Check [item]https://www.php.net/manual/en/ini.core.php#ini.sect.file-uploads[/item] for more information.[/warning]'
            )
            raise typer.Exit(1)
