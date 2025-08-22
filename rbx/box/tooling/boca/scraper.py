import datetime
import functools
import hashlib
import os
import pathlib
import re
import shutil
import time
import typing
from typing import Any, Callable, List, NoReturn, Optional, Tuple, Union

import dateparser
import mechanize
import typer
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel
from throttlex import Throttler

from rbx import console
from rbx.box import naming
from rbx.box.tooling.boca.debug_utils import pretty_print_request_data
from rbx.grading.steps import Outcome

ALERT_REGEX = re.compile(r'\<script[^\>]*\>\s*alert\(\'([^\']+)\'\);?\s*\<\/script\>')
REDIRECT_REGEX = re.compile(
    r'\<script[^\>]*\>\s*document\.location\s*=\s*\'([^\']+)\'\;\s*\<\/script\>'
)
START_DATE_REGEX = re.compile(r'Start date\s*\(contest\=([^\)]+)\)')
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


def _parse_answer_as_outcome(answer: str) -> Optional[Outcome]:
    answer = answer.lower()
    if 'yes' in answer:
        return Outcome.ACCEPTED
    if 'wrong answer' in answer:
        return Outcome.WRONG_ANSWER
    if 'time limit exceeded' in answer:
        return Outcome.TIME_LIMIT_EXCEEDED
    if 'runtime error' in answer:
        return Outcome.RUNTIME_ERROR
    return None


def _big_hex_sum(hex1: str, hex2: str) -> str:
    return f'{int(hex1, 16) + int(hex2, 16):x}'


class BocaProblem(BaseModel):
    index: int
    shortname: str
    fullname: str
    basename: str
    color: str
    color_name: str
    descfile_url: str
    package_url: str
    package_hash: str


class BocaLanguage(BaseModel):
    index: int
    name: str
    extension: str


class BocaRun(BaseModel):
    run_number: int
    site_number: int
    problem_shortname: str
    outcome: Optional[Outcome]
    time: int
    status: str

    user: Optional[str] = None

    @classmethod
    def from_run_number(cls, run_number: int, site_number: int):
        return cls(
            run_number=run_number,
            site_number=site_number,
            problem_shortname='',
            outcome=None,
            time=0,
            status='',
        )


class BocaDetailedRun(BocaRun):
    language_repr: str
    code: str
    filename: pathlib.Path

    autojudge_answer: str


class BocaScraper:
    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        throttler: Optional[Throttler] = None,
        verbose: bool = False,
        is_judge: bool = False,
    ):
        self.base_url = _parse_env_var('BOCA_BASE_URL', base_url)
        self.username = _parse_env_var('BOCA_USERNAME', username)
        self.password = _parse_env_var('BOCA_PASSWORD', password)
        self.verbose = verbose
        self.loggedIn = False
        self.is_judge = is_judge
        self.throttler = throttler or Throttler(max_req=1, period=1)
        self.br = mechanize.Browser()
        self.br.set_handle_robots(False)
        self.br.addheaders = [  # type: ignore
            (
                'User-agent',
                'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1',
            )
        ]

    def log(self, message: str):
        if self.verbose:
            console.console.print(message)

    def error(self, message: str) -> NoReturn:
        console.console.print(
            f'[error]{message} (at [item]{self.base_url}[/item])[/error]',
        )
        raise typer.Exit(1)

    def raw_error(self, message: str) -> NoReturn:
        console.console.print(f'[error]{message}[/error]')
        raise typer.Exit(1)

    def pretty_print(self, html: str):
        soup = BeautifulSoup(html, 'html.parser')
        console.console.print(soup.prettify())

    def get_redirect(self, html: str) -> Optional[str]:
        redirect = REDIRECT_REGEX.search(html)
        if redirect is None:
            return None
        return redirect.group(1)

    def get_alert(self, html: str) -> Optional[str]:
        alert = ALERT_REGEX.search(html)
        if alert is None:
            return None
        return alert.group(1)

    def log_response_alert(
        self,
        response: Any,
        message: str,
        alert_ok_fn: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[Any, str]:
        if response is None:
            self.raw_error(
                f'{message} ([item]{self.base_url}[/item]):\nNo response received.'
            )
        html = response.read().decode()
        alert = self.get_alert(html)
        if alert:
            if alert_ok_fn is not None and alert_ok_fn(alert):
                return response, html
            self.raw_error(f'{message} ([item]{self.base_url}[/item]):\n{alert}')
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

            parsed_date = dateparser.parse(
                date, settings={'TO_TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}
            )
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
        alert = self.get_alert(html)
        if alert:
            if 'Violation' in alert:
                return False
            self.raw_error(f'Error while submitting problem to BOCA website:\n{alert}')

        redirect = self.get_redirect(html)
        if redirect is None:
            self.raw_error(
                'Error while submitting problem to BOCA website:\nNo redirect found after upload.'
            )
        _, html = self.open(
            redirect, error_msg='Error while freeing BOCA problems after upload'
        )
        return self.check_logs_for_update(problem_id)

    def open(
        self,
        url_or_request: Union[str, mechanize.Request],
        *args,
        error_msg: Optional[str] = None,
        **kwargs,
    ):
        url_or_request = self.throttler.throttle(url_or_request)
        if isinstance(url_or_request, mechanize.Request):
            url = url_or_request.get_full_url()
        else:
            url = url_or_request
        if error_msg is None:
            error_msg = f'Error while opening [item]{url}[/item]'
        response = self.br.open(url_or_request, *args, **kwargs)
        return self.log_response_alert(response, error_msg)

    def hash_single(self, password: str) -> str:
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        return pwd_hash

    def hash(self, password: str, salt: str) -> str:
        pwd_hash = self.hash_single(password)
        pwd_hash = self.hash_single(pwd_hash + salt)
        return pwd_hash

    def hash_two(self, password1: str, password2: str) -> str:
        return _big_hex_sum(self.hash_single(password1), self.hash_single(password2))

    def find_salt(self, html: str, field: str) -> str:
        needle = f"js_myhash(document.{field}.value)+'"
        start = html.index(needle)
        start_salt = start + len(needle)
        end_salt = html.index("'", start_salt)
        salt = html[start_salt:end_salt]
        return salt

    def login(self):
        if self.loggedIn:
            return

        _, html = self.open(
            f'{self.base_url}', error_msg='Error while opening BOCA login page'
        )

        salt = self.find_salt(html, 'form1.password')
        console.console.print(f'Using salt [item]{salt}[/item]')

        pwd_hash = self.hash(self.password, salt)

        login_url = f'{self.base_url}?name={self.username}&password={pwd_hash}'
        self.open(login_url, error_msg='Error while logging in to BOCA')

        self.loggedIn = True

    def upload(
        self,
        file: pathlib.Path,
        testing: bool = False,
    ) -> bool:
        self.open(
            f'{self.base_url}/admin/problem.php',
            error_msg='Error while opening BOCA problem upload page',
        )
        try:
            self.br.select_form(name='form1')
        except mechanize.FormNotFoundError:
            self.error(
                'Problem upload form not found in BOCA website. This might happen when the login failed.'
            )

        form = typing.cast(mechanize.HTMLForm, self.br.form)
        form.set_all_readonly(False)

        if testing:
            problem_index = 0
            problem_shortname = 'A'
            hex_color = None
        else:
            problem_index = naming.get_problem_index()
            if problem_index is None:
                console.console.print(
                    'It seems this problem is not part of a contest. Cannot upload it to BOCA.'
                )
                raise typer.Exit(1)

            problem_shortname = naming.get_problem_shortname()
            assert problem_shortname is not None
            if problem_shortname is None:
                console.console.print(
                    'It seems this problem is not part of a contest. Cannot upload it to BOCA.'
                )
                raise typer.Exit(1)

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
        if form.find_control('autojudge_new_sel'):
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
                self.loggedIn = False
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
                '[warning]This might be caused by PHP max upload size limit (which usually defaults to 2MB).[/warning]'
            )
            console.console.print(
                '[warning]Check [item]https://www.php.net/manual/en/ini.core.php#ini.sect.file-uploads[/item] for more information.[/warning]'
            )
            raise typer.Exit(1)

    def get_link_from_a(self, a: Tag) -> Optional[str]:
        href = a.attrs.get('href')
        if href is None:
            return None
        link = self.br.find_link(url=href)
        if link is None:
            return None
        return link.absolute_url

    def get_first_link(self, tag: Tag) -> Optional[str]:
        a = tag.find('a')
        if a is None:
            return None
        return self.get_link_from_a(typing.cast(Tag, a))

    def list_problems(self) -> List[BocaProblem]:
        _, html = self.open(
            f'{self.base_url}/admin/problem.php',
            error_msg='Error while listing problems in BOCA',
        )

        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('form[name="form0"] > table > tr')
        problems: List[BocaProblem] = []
        for row in rows[2:]:
            cells = row.select('& > td')
            index = int(cells[0].text.strip())
            shortname = cells[1].text.strip()
            fullname = cells[2].text.strip()
            basename = cells[3].text.strip()
            descfile_url = self.get_first_link(cells[4])
            package_url = self.get_first_link(cells[5])

            hash_balloon = cells[5].find('img')
            if descfile_url is None or package_url is None or hash_balloon is None:
                self.log(f'Skipping problem {shortname} because of missing data')
                continue
            hash_balloon = typing.cast(Tag, hash_balloon)
            hash = hash_balloon.attrs.get('alt')
            if hash is None:
                self.log(f'Skipping problem {shortname} because hash is None')
                continue
            hash = str(hash).strip()

            color_balloon = cells[6].find('img')
            if color_balloon is None:
                self.log(f'Skipping problem {shortname} because color balloon is None')
                continue
            color_balloon = typing.cast(Tag, color_balloon)
            color = color_balloon.attrs.get('alt')
            if color is None:
                self.log(f'Skipping problem {shortname} because color is None')
                continue
            color = str(color).strip()

            color_name = color_balloon.attrs.get('title')
            if color_name is None:
                self.log(f'Skipping problem {shortname} because color name is None')
                continue
            color_name = str(color_name).strip()

            problems.append(
                BocaProblem(
                    index=index,
                    shortname=shortname,
                    fullname=fullname,
                    basename=basename,
                    color=color,
                    color_name=color_name,
                    descfile_url=descfile_url,
                    package_url=package_url,
                    package_hash=hash,
                )
            )

        return problems

    def list_languages(self) -> List[BocaLanguage]:
        _, html = self.open(
            f'{self.base_url}/admin/language.php',
            error_msg='Error while listing languages in BOCA',
        )

        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.select('table')
        for table in tables:
            if 'Language #' in table.text:
                break
        else:
            self.raw_error(
                'Error while listing languages in BOCA:\nNo language table found.'
            )
        table = typing.cast(Tag, table)
        rows = table.select('tr')
        languages: List[BocaLanguage] = []
        for row in rows[1:]:
            cells = row.select('td')
            index = int(cells[0].text.strip())
            name = cells[1].text.strip()
            extension = cells[2].text.strip()
            languages.append(BocaLanguage(index=index, name=name, extension=extension))
        return languages

    def list_runs(self, only_judged: bool = True) -> List[BocaRun]:
        _, html = self.open(
            f'{self.base_url}/admin/run.php'
            if not self.is_judge
            else f'{self.base_url}/judge/runchief.php',
            error_msg='Error while listing runs in BOCA',
        )

        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('form[name="form1"] table tr')
        off = 1 if self.is_judge else 0

        runs: List[BocaRun] = []
        for row in rows[1:]:
            cells = row.select('td')

            run_number = cells[0].text.strip()
            site_number = cells[1].text.strip()
            shortname = cells[4 - off].text.strip()
            answer = cells[-1 - off].text.strip()
            time = int(cells[3 - off].text.strip())
            user = (
                cells[2].text.strip() if not self.is_judge else cells[-1].text.strip()
            )
            status = cells[-4 - off].text.strip().lower()

            if only_judged and status != 'judged':
                continue
            outcome = _parse_answer_as_outcome(answer)
            if outcome is None:
                if status == 'judged':
                    continue
            runs.append(
                BocaRun(
                    run_number=run_number,
                    site_number=site_number,
                    problem_shortname=shortname,
                    outcome=outcome,
                    time=time,
                    status=status,
                    user=user,
                )
            )

        return runs

    def wait_for_all_judged(self, step: int = 5):
        while True:
            runs = self.list_runs(only_judged=False)
            if all(run.outcome is not None for run in runs):
                return
            time.sleep(step)

    def retrieve_run(self, run: BocaRun) -> BocaDetailedRun:
        self.log(
            f'Retrieving run [item]{run.run_number}-{run.site_number}[/item] from BOCA...'
        )
        runedit_url = (
            f'{self.base_url}/admin/runedit.php'
            if not self.is_judge
            else f'{self.base_url}/judge/runeditchief.php'
        )
        url = (
            f'{runedit_url}?runnumber={run.run_number}&runsitenumber={run.site_number}'
        )
        _, html = self.open(
            url,
            error_msg=f'Error while downloading BOCA run [item]{run.run_number}-{run.site_number}[/item]',
        )

        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('tr')

        href: Optional[str] = None
        filename: Optional[pathlib.Path] = None

        for row in rows:
            row_text = row.select('td')[0].text.strip().lower()
            if not row_text.endswith('code:'):
                continue
            link_col = row.select_one('td:nth-of-type(2) a:nth-of-type(1)')
            if link_col is None:
                continue
            href = str(link_col.attrs['href'])
            if filename is None:
                filename = pathlib.Path(link_col.text.strip())
            break

        if href is None or filename is None:
            self.raw_error(
                "Error while downloading run:\nNo link to team's code found."
            )

        link = self.br.find_link(url=href)
        tmp_file, _ = self.br.retrieve(link.absolute_url)
        if tmp_file is None:
            self.raw_error('Error while downloading run:\nDownloaded file is None.')

        return BocaDetailedRun(
            **run.model_dump(),
            language_repr='',
            code=pathlib.Path(tmp_file).read_text(),
            filename=filename,
            autojudge_answer='',
        )

    def retrieve_runs(self, only_judged: bool = True) -> List[BocaDetailedRun]:
        runs = self.list_runs(only_judged)
        return [self.retrieve_run(run) for run in runs]

    def download_run(
        self,
        run: BocaRun,
        into_dir: pathlib.Path,
        name: Optional[str] = None,
    ) -> pathlib.Path:
        detailed_run = self.retrieve_run(run)
        filename = detailed_run.filename.with_stem(
            name or f'{run.run_number}-{run.site_number}'
        )
        final_path = into_dir / filename
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(detailed_run.code, final_path)
        return final_path

    def _set_starttime(
        self,
        form: mechanize.HTMLForm,
        start_time: datetime.datetime,
        tzinfo: datetime.tzinfo,
    ):
        start_time = start_time.astimezone(tzinfo)

        form['startdateh'] = f'{start_time.hour:02d}'
        form['startdatemin'] = f'{start_time.minute:02d}'
        form['startdated'] = f'{start_time.day:02d}'
        form['startdatem'] = f'{start_time.month:02d}'
        form['startdatey'] = f'{start_time.year}'

        self.log(
            f'Setting start time to {start_time.hour}:{start_time.minute} {start_time.day}/{start_time.month}/{start_time.year}'
        )

    def create_and_activate_contest(self):
        _, html = self.open(
            f'{self.base_url}/system/contest.php?new=1',
            error_msg='Error while creating contest in BOCA',
        )

        contest_page = self.get_redirect(html)
        self.log(f'Redirected to contest page: {contest_page}')
        if contest_page is None:
            self.pretty_print(html)
            self.raw_error(
                'Error while creating contest:\nNo redirect to contest page found.'
            )

        _, html = self.open(
            contest_page, error_msg='Error while opening the contest page'
        )

        try:
            self.br.select_form(name='form1')
        except mechanize.FormNotFoundError:
            self.error(
                'Contest activation form not found in BOCA website. This might happen when the login failed.'
            )

        form = typing.cast(mechanize.HTMLForm, self.br.form)
        form.set_all_readonly(False)
        form['confirmation'] = 'confirm'

        response = self.br.submit(name='Submit3', type='submit', nr=1)

        def alert_ok_fn(alert: str) -> bool:
            return 'You must log in the new contest' in alert

        self.log_response_alert(
            response,
            'Error while activating contest',
            alert_ok_fn=alert_ok_fn,
        )
        self.log('Contest activated successfully')

    def infer_timezone(self) -> datetime.tzinfo:
        _, html = self.open(
            f'{self.base_url}/admin/site.php',
            error_msg='Error while inferring timezone in BOCA',
        )

        match = START_DATE_REGEX.search(html)
        if match is None:
            self.raw_error(
                'Error while inferring timezone in BOCA:\nNo start date found.'
            )
        start_date = match.group(1)
        parsed_date = dateparser.parse(
            start_date, settings={'RETURN_AS_TIMEZONE_AWARE': True}
        )
        if parsed_date is None:
            self.raw_error(
                'Error while inferring timezone in BOCA:\nCould not parse start date.'
            )
        return parsed_date.tzinfo or datetime.timezone.utc

    def configure_contest(
        self,
        start_time: Optional[datetime.datetime] = None,
    ):
        tzinfo = self.infer_timezone()

        _, html = self.open(
            f'{self.base_url}/admin/contest.php',
            error_msg='Error while configuring contest in BOCA',
        )

        try:
            self.br.select_form(name='form1')
        except mechanize.FormNotFoundError:
            self.error(
                'Contest activation form not found in BOCA website. This might happen when the login failed.'
            )

        form = typing.cast(mechanize.HTMLForm, self.br.form)
        form.set_all_readonly(False)
        form['confirmation'] = 'confirm'

        if start_time is not None:
            self._set_starttime(form, start_time, tzinfo)

        req = self.br.click(name='Submit3', type='submit', nr=1)
        pretty_print_request_data(req)
        self.open(req)
        self.log('Contest configured successfully')

    def configure_main_site(
        self, autojudge: Optional[bool] = None, chief: Optional[str] = None
    ):
        _, html = self.open(
            f'{self.base_url}/admin/site.php',
            error_msg='Error while configuring main site in BOCA',
        )

        try:
            form = self.br.select_form(name='form1')
        except mechanize.FormNotFoundError:
            self.error(
                'Main site configuration form not found in BOCA website. This might happen when the login failed.'
            )

        form = typing.cast(mechanize.HTMLForm, self.br.form)
        form.set_all_readonly(False)
        form['confirmation'] = 'confirm'

        if autojudge is not None:
            self.br.find_control(name='autojudge', type='checkbox').items[
                0
            ].selected = autojudge

        if chief is not None:
            form['chiefname'] = chief

        req = self.br.click(name='Submit1', type='submit', nr=0)
        pretty_print_request_data(req)
        self.open(req)
        self.log('Main site configured successfully')

    def create_judge_account(self, password: str = 'boca'):
        _, html = self.open(
            f'{self.base_url}/admin/user.php',
            error_msg='Error while creating judge account in BOCA',
        )

        try:
            self.br.select_form(name='form3')
        except mechanize.FormNotFoundError:
            self.error(
                'Judge account creation form not found in BOCA website. This might happen when the login failed.'
            )

        salt = self.find_salt(html, 'form3.passwordo')
        console.console.print(f'Using salt [item]{salt}[/item]')
        admin_pwd_hash = self.hash(self.password, salt)

        self.br.form = self.br.global_form()
        form = typing.cast(mechanize.HTMLForm, self.br.form)

        form.method = 'POST'
        form.set_all_readonly(False)
        form['confirmation'] = 'confirm'
        form['usernumber'] = '42565759'
        form['username'] = 'judge'
        form['usertype'] = ['judge']
        form['usermultilogin'] = ['t']
        form['userfullname'] = 'Judge RBX'
        form['passwordn1'] = self.hash_two(password, self.password)
        form['passwordn2'] = self.hash_two(password, self.password)
        form['passwordo'] = admin_pwd_hash

        req = self.br.click(name='Submit', type='submit')
        pretty_print_request_data(req)
        self.open(req)
        self.log('Judge account created successfully')

    def wait_for_problem(self, problem_index_in_contest: int, timeout: int, step: int):
        _, html = self.open(
            f'{self.base_url}/judge/team.php',
            error_msg='Error while waiting for problem in BOCA',
        )

        self.log(
            f'Waiting for problem [item]{problem_index_in_contest}[/item] in BOCA (timeout: {timeout}s, step: {step}s)...'
        )
        soup = BeautifulSoup(html, 'html.parser')
        options = soup.select('select[name="problem"] option')
        available_indices = set(
            int(option.attrs['value'])
            for option in options
            if option.attrs.get('value') is not None
        )
        if problem_index_in_contest not in available_indices:
            if timeout <= 0:
                self.raw_error(
                    f'Problem index [item]{problem_index_in_contest}[/item] not found in BOCA.'
                )
            time.sleep(step)
            return self.wait_for_problem(problem_index_in_contest, timeout - step, step)
        return

    def submit_as_judge(
        self,
        problem_index_in_contest: int,
        language_index_in_contest: int,
        file: pathlib.Path,
        wait: int = 0,
    ):
        if wait > 0:
            self.wait_for_problem(problem_index_in_contest, wait, 5)
        _, html = self.open(
            f'{self.base_url}/judge/team.php',
            error_msg='Error while submitting problem to BOCA',
        )

        try:
            self.br.select_form(name='form1')
        except mechanize.FormNotFoundError:
            self.error(
                'Judge submission form not found in BOCA website. This might happen when the login failed.'
            )

        form = typing.cast(mechanize.HTMLForm, self.br.form)
        form.set_all_readonly(False)
        form['confirmation'] = 'confirm'

        form['problem'] = [str(problem_index_in_contest)]
        form['language'] = [str(language_index_in_contest)]

        with file.open('rb') as f:
            form.add_file(
                f,
                filename=file.name,
                name='sourcefile',
            )

            req = self.br.click(name='Submit', type='submit')
            pretty_print_request_data(req)
            self.open(req)
            self.log('Judge submission sent successfully')


@functools.cache
def get_boca_scraper(
    base_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> BocaScraper:
    return BocaScraper(base_url, username, password)


class ContestSnapshot:
    def __init__(
        self,
        problems: Optional[List[BocaProblem]] = None,
        languages: Optional[List[BocaLanguage]] = None,
        runs: Optional[List[BocaRun]] = None,
        detailed_runs: Optional[List[BocaDetailedRun]] = None,
    ):
        self.problems = problems or []
        self.languages = languages or []
        self.runs = runs or []
        self.detailed_runs = detailed_runs or []

    def __str__(self) -> str:
        return f'ContestSnapshot(problems={self.problems}, languages={self.languages})'

    def __repr__(self) -> str:
        return self.__str__()

    def get_problem_by_shortname(self, shortname: str) -> BocaProblem:
        for problem in self.problems:
            if problem.shortname == shortname:
                return problem
        raise ValueError(f'Problem with shortname {shortname} not found')

    def get_problem_by_basename(self, basename: str) -> BocaProblem:
        for problem in self.problems:
            if problem.basename == basename:
                return problem
        raise ValueError(f'Problem with basename {basename} not found')

    def get_problem_by_index(self, index: int) -> BocaProblem:
        for problem in self.problems:
            if problem.index == index:
                return problem
        raise ValueError(f'Problem with index {index} not found')

    def get_language_by_name(self, name: str) -> BocaLanguage:
        for language in self.languages:
            if language.name == name:
                return language
        raise ValueError(f'Language with name {name} not found')

    def get_language_by_extension(self, extension: str) -> BocaLanguage:
        for language in self.languages:
            if language.extension == extension:
                return language
        raise ValueError(f'Language with extension {extension} not found')

    def get_language_by_index(self, index: int) -> BocaLanguage:
        for language in self.languages:
            if language.index == index:
                return language
        raise ValueError(f'Language with index {index} not found')

    def get_run_by_number(self, number: int) -> BocaRun:
        for run in self.runs:
            if run.run_number == number:
                return run
        raise ValueError(f'Run with number {number} not found')

    def get_detailed_run_by_number(self, number: int) -> BocaDetailedRun:
        for run in self.detailed_runs:
            if run.run_number == number:
                return run
        raise ValueError(f'Run with number {number} not found')

    def get_detailed_run_by_path(self, path: pathlib.Path) -> BocaDetailedRun:
        for run in self.detailed_runs:
            if run.filename.name == path.name:
                return run
        raise ValueError(f'Run with path {path} not found')


def create_snapshot(
    scraper: BocaScraper, detailed_runs: bool = False
) -> ContestSnapshot:
    scraper.login()
    problems = scraper.list_problems()
    languages = scraper.list_languages()
    runs = scraper.list_runs()
    detailed = scraper.retrieve_runs() if detailed_runs else []
    return ContestSnapshot(problems, languages, runs, detailed)
