from asyncio import sleep, run
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from json import load
from logging import INFO, DEBUG, getLogger, StreamHandler, Logger, Formatter
from logging.handlers import TimedRotatingFileHandler
from os import access, R_OK, makedirs
from os.path import isfile, exists
from re import compile, match
from sys import argv
from typing import Optional, Callable, Any

import requests
# noinspection PyPackageRequirements
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from colorlog import ColoredFormatter
from msgraph import GraphServiceClient
from msgraph.generated.communications.get_presences_by_user_id.get_presences_by_user_id_post_request_body import \
    GetPresencesByUserIdPostRequestBody
from msgraph.generated.models.presence import Presence
from msgraph.generated.users.users_request_builder import UsersRequestBuilder
from peewee import Model, CharField, SqliteDatabase, ForeignKeyField, DateTimeField, SQL, fn, DoesNotExist, \
    IntegerField, JOIN, PrimaryKeyField

_APP_NAME = "presence_tracker"


class Params:
    _DEFAULT_PARAMS_FILE = "params.json"

    _DEFAULT_GOTIFY_URL = ""
    _DEFAULT_GOTIFY_APP_TOKENS = []
    _DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
    _DEFAULT_AZURE_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
    _DEFAULT_LOGIN_USERNAME = None
    _DEFAULT_PING_SECONDS = 60
    _DEFAULT_START_HOUR = 9
    _DEFAULT_END_HOUR = 15
    _DEFAULT_TRACKED_USER_EMAILS = []

    def __init__(self, params_file_path: str = _DEFAULT_PARAMS_FILE) -> None:
        self.gotify_url = self._DEFAULT_GOTIFY_URL
        self.gotify_app_tokens = self._DEFAULT_GOTIFY_APP_TOKENS
        self.authority = self._DEFAULT_AUTHORITY
        self.azure_client_id = self._DEFAULT_AZURE_CLIENT_ID
        self.login_username = self._DEFAULT_LOGIN_USERNAME
        self.ping_seconds = self._DEFAULT_PING_SECONDS
        self.start_hour = self._DEFAULT_START_HOUR
        self.end_hour = self._DEFAULT_END_HOUR
        self.tracked_user_emails = self._DEFAULT_TRACKED_USER_EMAILS
        self.tracked_user_email_severity: dict[str, int] = {}
        self._load_params(params_file_path)

    def _load_params(self, params_file_path: str) -> None:
        no_arg = 1
        if len(argv) > no_arg:
            params_file_path = argv[no_arg]

        if not self._is_valid_file(params_file_path):
            exit(1)

        with open(params_file_path) as params_file:
            params_dict = load(params_file)

        self.gotify_url = params_dict.get("gotify_url", self._DEFAULT_GOTIFY_URL)
        self.gotify_app_tokens = params_dict.get("gotify_app_tokens", self._DEFAULT_GOTIFY_APP_TOKENS)
        self.authority = params_dict.get("authority", self._DEFAULT_AUTHORITY)
        self.azure_client_id = params_dict.get("azure_client_id", self._DEFAULT_AZURE_CLIENT_ID)
        self.login_username = params_dict.get("login_username", self._DEFAULT_LOGIN_USERNAME)
        self.ping_seconds = params_dict.get("ping_seconds", self._DEFAULT_PING_SECONDS)
        self.start_hour = params_dict.get("start_hour", self._DEFAULT_START_HOUR)
        self.end_hour = params_dict.get("end_hour", self._DEFAULT_END_HOUR)

        self.tracked_user_emails: list[str] = params_dict.get("tracked_user_emails", self._DEFAULT_TRACKED_USER_EMAILS)
        self.tracked_user_email_severity = {
            email.lstrip("+"): self._count_plus_at_start(email)
            for email in self.tracked_user_emails
        }

        self.tracked_user_emails = [email for email in self.tracked_user_email_severity.keys()]

    def _is_valid_file(self, file_path: str) -> bool:
        if isfile(file_path) and access(file_path, R_OK):
            return True
        else:
            print(
                f"The provided parameters file cannot be accessed. Please make sure the file exists and is readable. "
                f"Default expected: (dir_containing_python_script)/{self._DEFAULT_PARAMS_FILE}"
            )
            return False

    @staticmethod
    def _count_plus_at_start(mail: str) -> int:
        m = match(r"^(\+*)", mail)
        if m:
            return len(m.group())
        else:
            return 0


db = SqliteDatabase(f"{_APP_NAME}.db")


class DbBase(Model):
    class Meta:
        database = db


class DbUser(DbBase):
    id = CharField(unique=True)
    mail = CharField(unique=True)
    display_name = CharField(max_length=255)
    job_title = CharField(max_length=255, null=True)

    class Meta:
        db_table = "user"


class DbSession(DbBase):
    id = PrimaryKeyField(null=False)
    start_time = DateTimeField(default=datetime.now)
    end_time = DateTimeField(null=True)

    class Meta:
        db_table = "session"


class DbPresence(DbBase):
    session = ForeignKeyField(DbSession, backref="presences")
    user = ForeignKeyField(DbUser, backref="presences")
    start_time = DateTimeField(default=datetime.now)
    end_time = DateTimeField(null=True)
    duration_seconds = IntegerField(default=0)

    class Meta:
        db_table = "presence"


class Notifier:
    @staticmethod
    def send_lifecycle_notifications(gotify_url: str, gotify_app_tokens: list[str], session_id: PrimaryKeyField, exception: Exception = None) -> None:
        message = f"Session {session_id} {"Started" if not exception else "Ended Unexpectedly"}!"
        if not exception:
            payload = {"message": message}
        else:
            payload = {"title": message, "message": str(exception)}

        Notifier._send_notifications(gotify_url, gotify_app_tokens, payload)

    @staticmethod
    def send_presence_notifications(gotify_url: str, gotify_app_tokens: list[str], display_name: str, unavailable_seconds: int, start_time: str, end_time: str) -> None:
        payload = {
            "title": f"{display_name} was Away!",
            "message": f"{display_name} was unavailable from {start_time} to {end_time} ({unavailable_seconds // 60} minutes)!"
        }

        Notifier._send_notifications(gotify_url, gotify_app_tokens, payload)

    @staticmethod
    def send_stats_notifications(gotify_url: str, gotify_app_tokens: list[str], display_name: str, unavailable_seconds: int) -> None:
        payload = {
            "title": f"{display_name} Session Stats",
            "message": f"{display_name} total unavailability was {unavailable_seconds // 60} minute(s)"
        }

        Notifier._send_notifications(gotify_url, gotify_app_tokens, payload)

    @staticmethod
    def _send_notifications(gotify_url: str, gotify_app_tokens: list[str], payload: dict[str, Any]):
        def send_request(app_token: str) -> None:
            try:
                response = requests.post(f"{gotify_url}/message?token={app_token}", json=payload, timeout=10)
                response.raise_for_status()
            except requests.RequestException as e:
                print(f"Failed to send notification to Gotify: {e}")
            except Exception as e:
                print(f"Unexpected error sending notification: {e}")

        with ThreadPoolExecutor() as executor:
            executor.map(send_request, gotify_app_tokens)


class Repository:
    @staticmethod
    def init_db() -> None:
        db.connect()
        db.create_tables([DbUser, DbPresence, DbSession], safe=True)

    @staticmethod
    def start_session() -> DbSession:
        return DbSession.create()

    @staticmethod
    def add_user(user_id: str, mail: str, display_name: str, job_title: str) -> None:
        user, created = DbUser.get_or_create(
            id=user_id,
            defaults={
                "mail": mail.lower(),
                "display_name": display_name,
                "job_title": job_title
            }
        )
        if not created and (user.display_name != display_name or user.job_title != job_title):
            user.display_name = display_name
            user.job_title = job_title
            user.save()

    @staticmethod
    def get_user(user_id: str):
        return DbUser.get(DbUser.id == user_id)

    @staticmethod
    def get_last_presence(user_id: str):
        try:
            return DbPresence.select().where(DbPresence.user == user_id).order_by(DbPresence.start_time.desc()).get()
        except DoesNotExist:
            return None

    @staticmethod
    def update_presence_end_time_and_duration(user_id: str, end_time: datetime, duration_seconds: int):
        query = DbPresence.update(end_time=end_time, duration_seconds=duration_seconds).where(
            (DbPresence.user == user_id) & (DbPresence.end_time.is_null())
        )
        query.execute()

    @staticmethod
    def add_presence(session: DbSession, user_id, start_time, end_time, duration_seconds: int) -> None:
        user = Repository.get_user(user_id)
        DbPresence.create(
            session=session,
            user=user,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds
        )

    @staticmethod
    def get_users_by_emails(emails: list[str]):
        return DbUser.select().where(DbUser.mail.in_(emails))

    @staticmethod
    def delete_invalid_presence_records() -> int:
        return DbPresence.delete().where(DbPresence.start_time.is_null()).execute()

    @staticmethod
    def close_out_incomplete_presence_records(now: datetime) -> int:
        query = DbPresence.update(
            end_time=now,
            duration_seconds=fn.Round((fn.JulianDay(now) - fn.JulianDay(DbPresence.start_time)) * 86400)
        ).where(
            (~(DbPresence.start_time.is_null())) &
            (DbPresence.end_time.is_null())
        )
        return query.execute()

    @staticmethod
    def get_user_availability(user_mails: list[str], start_dt: datetime, end_dt: datetime):
        result = (
            DbUser.select(DbUser, fn.COALESCE(fn.SUM(DbPresence.duration_seconds), 0).alias("total_seconds"))
            .join(DbPresence, JOIN.LEFT_OUTER, on=(DbUser.id == DbPresence.user))
            .where((DbPresence.start_time.between(start_dt, end_dt)) | (DbPresence.start_time.is_null()))
            .where(DbUser.mail.in_(user_mails))
            .group_by(DbUser)
            .having(
                (fn.COALESCE(fn.SUM(DbPresence.duration_seconds), 0) <
                 fn.floor((end_dt - start_dt).total_seconds()) - 5)
            )
            .order_by(SQL("total_seconds").desc())
        )

        return result


class PresenceTracker:
    def __init__(self):
        self.params = Params()
        self.logger = self.configure_logger()
        self._log_severities = {
            0: self.logger.info,
            1: self.logger.warning,
            2: self.logger.error,
            3: self.logger.critical
        }
        self.graph_client = self._initialize_graph_client(self.params)
        self.session = None
        Repository.init_db()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_async()

    async def track_async(self) -> None:
        await self._populate_tracked_users_async()
        start_dt, end_dt = self._get_start_and_end_time()

        if datetime.now() < start_dt:
            self.logger.info(f"Waiting until the scheduled start time: {self._format_time(start_dt)}...")

            while datetime.now() < start_dt:
                await sleep(1)

        self.session = Repository.start_session()
        self.logger.info(f"Presence tracker started, session id: {self.session.id}")
        Notifier.send_lifecycle_notifications(self.params.gotify_url, self.params.gotify_app_tokens, self.session.id)
        try:
            await self._track_until_scheduled_end_time_async(end_dt)
        except Exception as e:
            Notifier.send_lifecycle_notifications(self.params.gotify_url, self.params.gotify_app_tokens, self.session.id, e)

        self._end_of_scheduled_time_cleanup(end_dt)
        self._print_presence_statistics(start_dt, end_dt)

    async def _populate_tracked_users_async(self) -> None:
        email_chunks = self._chunk_emails(self.params.tracked_user_emails)
        for chunk in email_chunks:
            db_users = {user.mail: user for user in Repository.get_users_by_emails(chunk)}
            remaining_emails = [email for email in chunk if email not in db_users]

            if not remaining_emails:
                continue

            query_params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                select=["id", "mail", "displayName", "jobTitle"],
                filter=f"mail in ({", ".join([f"\"{email}\"" for email in remaining_emails])})",
            )

            request_config = UsersRequestBuilder.UsersRequestBuilderGetRequestConfiguration(
                query_parameters=query_params
            )
            response = await self.graph_client.users.get(request_configuration=request_config)

            for user in response.value:
                if user.mail in db_users:
                    continue

                Repository.add_user(user.id, user.mail, user.display_name, user.job_title)

    async def _track_until_scheduled_end_time_async(self, end_dt: datetime) -> None:
        dt_initial = datetime.now()
        while datetime.now() < end_dt:
            await self._track_user_presence_async(dt_initial)
            dt_initial = None

            await sleep(self.params.ping_seconds)

    async def _track_user_presence_async(self, dt_initial: Optional[datetime]) -> None:
        db_users = Repository.get_users_by_emails(self.params.tracked_user_emails)

        request_body = GetPresencesByUserIdPostRequestBody(ids=[user.id for user in db_users])
        response = await self.graph_client.communications.get_presences_by_user_id.post(request_body)

        for presence in response.value:
            self._track_individual_user(presence, dt_initial)

    # noinspection PyMethodMayBeStatic
    def _get_start_and_end_time(self) -> tuple[datetime, datetime]:
        # from datetime import time  # real
        # start_time = time(self.params.start_hour, 0)  # real time
        # end_time = time(self.params.end_hour, 0)  # real time

        from datetime import timedelta  # test
        start_time = (datetime.now() + timedelta(seconds=10)).time()  # test time
        end_time = (datetime.now() + timedelta(seconds=10, minutes=1)).time()  # test time

        start_dt = datetime.combine(date.today(), start_time)
        end_dt = datetime.combine(date.today(), end_time)
        return start_dt, end_dt

    def _end_of_scheduled_time_cleanup(self, end_dt: datetime) -> None:
        for user in Repository.get_users_by_emails(self.params.tracked_user_emails):
            if user.presences:
                last_presence = Repository.get_last_presence(user.id)

                if not last_presence.end_time:
                    duration_seconds = int((end_dt - last_presence.start_time).total_seconds())
                    Repository.update_presence_end_time_and_duration(user.id, end_dt, duration_seconds)

    def _print_presence_statistics(self, start_dt: datetime, end_dt: datetime) -> None:
        user_availability = Repository.get_user_availability(self.params.tracked_user_emails, start_dt, end_dt)

        self.logger.info(f"Presence stats from {self._format_time(start_dt)} to {self._format_time(end_dt)}:")
        if not user_availability:
            self.logger.info("All users were unavailable for the scheduled tracking time")
        else:
            for user in user_availability:
                severity = self.params.tracked_user_email_severity[user.mail]
                if severity >= 3:
                    Notifier.send_stats_notifications(self.params.gotify_url, self.params.gotify_app_tokens, user.display_name, user.total_seconds)

                self.logger.info(f"{user.display_name} total unavailability was {user.total_seconds // 60} minute(s)")

    def _track_individual_user(self, presence: Presence, dt_initial: Optional[datetime]) -> None:
        db_user = Repository.get_user(presence.id)
        display_name, email = db_user.display_name, db_user.mail
        severity = self.params.tracked_user_email_severity[email]

        log_func = self._log_severities.get(min(severity, max(self._log_severities.keys())))
        availability, user_id = presence.availability, presence.id
        dt_now = dt_initial if dt_initial is not None else datetime.now()

        if availability in ["Away", "Offline"]:
            last_presence = Repository.get_last_presence(user_id)
            if last_presence is None or last_presence.end_time is not None:
                Repository.add_presence(self.session, user_id, dt_now, None, 0)
                if not dt_initial:
                    log_func(f"{display_name} went {availability.lower()} at {self._format_time(dt_now)}")
        else:
            self._handle_user_becoming_available(user_id, dt_now, log_func)

    def _handle_user_becoming_available(self, user_id: str, dt_available: datetime, log: Callable) -> None:
        last_presence = Repository.get_last_presence(user_id)

        if last_presence is not None and last_presence.start_time is not None and last_presence.end_time is None:
            self._end_unavailability_presence(user_id, last_presence.start_time, dt_available, log)

    def _end_unavailability_presence(self, user_id: str, dt_start: datetime, dt_end: datetime, log: Callable) -> None:
        str_start, str_end = self._format_time(dt_start), self._format_time(dt_end)

        user = Repository.get_user(user_id)
        if str_start != str_end:
            log(f"{user.display_name} was unavailable from {str_start} to {str_end}")

        severity = self.params.tracked_user_email_severity[user.mail]
        duration_seconds = int((dt_end - dt_start).total_seconds())
        if severity >= 3 and (duration_seconds / 60) > 60:
            Notifier.send_presence_notifications(self.params.gotify_url, self.params.gotify_app_tokens, user.display_name, duration_seconds, str_start, str_end)

        Repository.update_presence_end_time_and_duration(user_id, dt_end, duration_seconds)

    async def cleanup_async(self):
        now = datetime.now()
        if self.session is not None:
            self.session.end_time = now
            self.session.save()

        deleted_records = Repository.delete_invalid_presence_records()
        updated_records = Repository.close_out_incomplete_presence_records(now)

        if deleted_records > 0:
            self.logger.info(f"Cleanup: deleted {deleted_records} presence record(s) with no start time")

        if updated_records > 0:
            self.logger.info(
                f"Cleanup: updated end time to now for {updated_records} presence record(s) with missing end time"
            )

    @staticmethod
    def configure_logger() -> Logger:
        log_dir = "logs"
        if not exists(log_dir):
            makedirs(log_dir)

        logger = getLogger(__name__)
        logger.setLevel(DEBUG)

        file_handler = TimedRotatingFileHandler(f"{log_dir}/{_APP_NAME}", when="midnight", interval=1)
        file_handler.suffix = "%Y%m%d.log"
        file_handler.extMatch = compile(r"^\d{8}.log$")

        console_handler = StreamHandler()
        console_handler.setLevel(INFO)

        file_formatter = Formatter(
            "%(levelname)-8s[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        console_formatter = ColoredFormatter(
            "[%(asctime)s] %(log_color)s%(message)s",
            datefmt="%H:%M:%S",
            reset=True,
            log_colors={
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            }
        )

        file_handler.setFormatter(file_formatter)
        console_handler.setFormatter(console_formatter)

        httpx_logger = getLogger("httpx")
        httpx_logger.setLevel(INFO)
        httpx_logger.addHandler(file_handler)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    @staticmethod
    def _initialize_graph_client(params: Params) -> GraphServiceClient:
        read_presence_scope = "Presence.Read"
        credentials = InteractiveBrowserCredential(
            client_id=params.azure_client_id,
            authority=params.authority,
            login_hint=params.login_username,
            cache_persistence_options=TokenCachePersistenceOptions()
        )
        credentials.get_token(read_presence_scope)

        # noinspection PyTypeChecker
        return GraphServiceClient(
            credentials=credentials,
            scopes=[read_presence_scope]
        )

    @staticmethod
    def _chunk_emails(emails: list[str]) -> list[list[str]]:
        email_chunk_limit = 15
        chunks = [emails[i:i + email_chunk_limit] for i in range(0, len(emails), email_chunk_limit)]
        return chunks

    @staticmethod
    def _format_time(dt: datetime) -> str:
        # return dt.strftime("%I:%M:%p").lstrip("0").lower()  # real
        return dt.strftime("%I:%M:%S%p").lstrip("0").lower()  # test


async def main():
    async with PresenceTracker() as tracker:
        try:
            await tracker.track_async()
        except Exception as e:
            tracker.logger.error(e)
        except BaseException:
            tracker.logger.warning(f"Script cancelled")
        finally:
            await tracker.cleanup_async()


if __name__ == "__main__":
    run(main())
