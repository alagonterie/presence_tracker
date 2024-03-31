from asyncio import sleep, run
from datetime import datetime, date
from json import load
from logging import basicConfig, INFO
from os import access, R_OK
from os.path import isfile
from sys import argv
from typing import Optional

# noinspection PyPackageRequirements
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from msgraph import GraphServiceClient
from msgraph.generated.communications.get_presences_by_user_id.get_presences_by_user_id_post_request_body import \
    GetPresencesByUserIdPostRequestBody
from msgraph.generated.models.presence import Presence
from msgraph.generated.users.users_request_builder import UsersRequestBuilder
from peewee import Model, CharField, SqliteDatabase, ForeignKeyField, DateTimeField, SQL, fn, DoesNotExist, \
    IntegerField, JOIN

basicConfig(level=INFO)


class Params:
    _DEFAULT_PARAMS_FILE = "params.json"

    _DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
    _DEFAULT_AZURE_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
    _DEFAULT_LOGIN_USERNAME = None
    _DEFAULT_PING_SECONDS = 60
    _DEFAULT_START_HOUR = 9
    _DEFAULT_END_HOUR = 15
    _DEFAULT_TRACKED_USER_EMAILS = []

    def __init__(self, params_file_path: str = _DEFAULT_PARAMS_FILE) -> None:
        self.authority = self._DEFAULT_AUTHORITY
        self.azure_client_id = self._DEFAULT_AZURE_CLIENT_ID
        self.login_username = self._DEFAULT_LOGIN_USERNAME
        self.ping_seconds = self._DEFAULT_PING_SECONDS
        self.start_hour = self._DEFAULT_START_HOUR
        self.end_hour = self._DEFAULT_END_HOUR
        self.tracked_user_emails = self._DEFAULT_TRACKED_USER_EMAILS
        self._load_params(params_file_path)

    def _load_params(self, params_file_path: str) -> None:
        no_arg = 1
        if len(argv) > no_arg:
            params_file_path = argv[no_arg]

        if not self._is_valid_file(params_file_path):
            exit(1)

        with open(params_file_path) as params_file:
            params_dict = load(params_file)

        self.authority = params_dict.get("authority", self._DEFAULT_AUTHORITY)
        self.azure_client_id = params_dict.get("azure_client_id", self._DEFAULT_AZURE_CLIENT_ID)
        self.login_username = params_dict.get("login_username", self._DEFAULT_LOGIN_USERNAME)
        self.ping_seconds = params_dict.get("ping_seconds", self._DEFAULT_PING_SECONDS)
        self.start_hour = params_dict.get("start_hour", self._DEFAULT_START_HOUR)
        self.end_hour = params_dict.get("end_hour", self._DEFAULT_END_HOUR)
        self.tracked_user_emails = params_dict.get("tracked_user_emails", self._DEFAULT_TRACKED_USER_EMAILS)

    def _is_valid_file(self, file_path: str) -> bool:
        if isfile(file_path) and access(file_path, R_OK):
            return True
        else:
            print(
                f"The provided parameters file cannot be accessed. Please make sure the file exists and is readable. "
                f"Default expected: (dir_containing_python_script)/{self._DEFAULT_PARAMS_FILE}"
            )
            return False


db = SqliteDatabase('presence_tracker.db')


class DbBase(Model):
    class Meta:
        database = db


class DbUser(DbBase):
    id = CharField(unique=True)
    mail = CharField(unique=True)
    display_name = CharField(max_length=255)
    job_title = CharField(max_length=255, null=True)


class DbPresence(DbBase):
    user = ForeignKeyField(DbUser, backref='presences')
    start_time = DateTimeField(default=datetime.now)
    end_time = DateTimeField(null=True)
    duration_seconds = IntegerField(default=0)


class Repository:
    @staticmethod
    def init_db():
        db.connect()
        db.create_tables([DbUser, DbPresence], safe=True)

    @staticmethod
    def add_user(user_id: str, mail: str, display_name: str, job_title: str) -> None:
        """Adds a new user to the database, avoiding duplicates."""
        user, created = DbUser.get_or_create(
            id=user_id,
            defaults={
                'mail': mail.lower(),
                'display_name': display_name,
                'job_title': job_title
            }
        )
        if not created and (user.display_name != display_name or user.job_title != job_title):
            user.display_name = display_name
            user.job_title = job_title
            user.save()

    @staticmethod
    def get_user(user_id):
        return DbUser.get(DbUser.id == user_id)

    @staticmethod
    def get_last_presence(user_id: str):
        """Fetches the most recent presence record for a specified user. Returns None if no record is found."""
        try:
            return DbPresence.select().where(DbPresence.user == user_id).order_by(DbPresence.start_time.desc()).get()
        except DoesNotExist:
            return None

    @staticmethod
    def update_presence_end_time_and_duration(user_id: str, end_time: datetime, duration_seconds: int):
        """Updates the end time and duration of the last tracked period of unavailability for a specific user."""
        query = DbPresence.update(end_time=end_time, duration_seconds=duration_seconds).where(
            (DbPresence.user == user_id) & (DbPresence.end_time.is_null())
        )
        query.execute()

    @staticmethod
    def add_presence(user_id, start_time, end_time, duration_seconds: int):
        user = Repository.get_user(user_id)
        DbPresence.create(user=user, start_time=start_time, end_time=end_time, duration_seconds=duration_seconds)

    @staticmethod
    def get_users_by_emails(emails):
        return DbUser.select().where(DbUser.mail.in_(emails))

    @staticmethod
    def delete_incomplete_presence_records() -> int:
        return DbPresence.delete().where(DbPresence.start_time.is_null()).execute()

    @staticmethod
    def set_end_time_to_now_for_incomplete_records() -> int:
        now = datetime.now()
        query = DbPresence.update(end_time=now).where(
            (~(DbPresence.start_time.is_null())) & (DbPresence.end_time.is_null())
        )
        return query.execute()

    @staticmethod
    def get_user_availability(user_mails: list[str], start_dt: datetime, end_dt: datetime):
        result = (
            DbUser.select(DbUser, fn.COALESCE(fn.SUM(DbPresence.duration_seconds), 0).alias('total_seconds'))
            .join(DbPresence, JOIN.LEFT_OUTER, on=(DbUser.id == DbPresence.user))
            .where((DbPresence.start_time.between(start_dt, end_dt)) | (DbPresence.start_time.is_null()))
            .where(DbUser.mail.in_(user_mails))
            .group_by(DbUser)
            .having(
                (fn.COALESCE(fn.SUM(DbPresence.duration_seconds), 0) <
                 fn.floor((end_dt - start_dt).total_seconds()) - 5)
            )
            .order_by(SQL('total_seconds').desc())
        )

        return result


class PresenceTracker:
    def __init__(self):
        self.params = Params()
        self.graph_client = self._initialize_graph_client(self.params)
        Repository.init_db()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_async()

    async def track_async(self) -> None:
        await self._populate_tracked_users_async()
        start_dt, end_dt = self._get_start_and_end_time()

        if datetime.now() < start_dt:
            print(f"Waiting until the scheduled start time: {self._format_time(start_dt)}...")

            while datetime.now() < start_dt:
                await sleep(1)

        await self._track_until_scheduled_end_time_async(end_dt)

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
                filter=f"mail in ({', '.join([f'\'{email}\'' for email in remaining_emails])})",
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

        print(f"Presence stats from {self._format_time(start_dt)} to {self._format_time(end_dt)}:")
        if not user_availability:
            print("All users were unavailable for the scheduled tracking time")
        else:
            for user in user_availability:
                print(f"{user.display_name} total unavailability was {round(user.total_seconds / 60, 2)} minute(s)")

    def _track_individual_user(self, presence: Presence, dt_initial: Optional[datetime]) -> None:
        display_name = Repository.get_user(presence.id).display_name
        availability, user_id = presence.availability, presence.id
        dt_now = dt_initial if dt_initial is not None else datetime.now()

        if availability in ['Away', 'Offline']:
            last_presence = Repository.get_last_presence(user_id)
            if last_presence is None or last_presence.end_time is not None:
                Repository.add_presence(user_id, dt_now, None, 0)
                if not dt_initial:
                    print(f"{display_name} went {availability.lower()} at {self._format_time(dt_now)}")
        else:
            self._handle_user_becoming_available(user_id, dt_now)

    def _handle_user_becoming_available(self, user_id: str, dt_available: datetime) -> None:
        last_presence = Repository.get_last_presence(user_id)

        if last_presence is not None and last_presence.start_time is not None and last_presence.end_time is None:
            self._end_unavailability_presence(user_id, last_presence.start_time, dt_available)

    def _end_unavailability_presence(self, user_id: str, dt_start: datetime, dt_end: datetime) -> None:
        str_start, str_end = self._format_time(dt_start), self._format_time(dt_end)

        if str_start != str_end:
            print(f"{Repository.get_user(user_id).display_name} was unavailable from {str_start} to {str_end}")

        duration_seconds = int((dt_end - dt_start).total_seconds())
        Repository.update_presence_end_time_and_duration(user_id, dt_end, duration_seconds)

    @staticmethod
    async def cleanup_async():
        deleted_records = Repository.delete_incomplete_presence_records()
        updated_records = Repository.set_end_time_to_now_for_incomplete_records()

        if deleted_records > 0:
            print(f"Cleanup: deleted {deleted_records} presence record(s) with no start time")

        if updated_records > 0:
            print(f"Cleanup: updated end time to now for {updated_records} presence record(s) with missing end time")

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
        # return dt.strftime('%I:%M:%p').lstrip('0').lower()  # real
        return dt.strftime('%I:%M:%S%p').lstrip('0').lower()  # test


async def main():
    async with PresenceTracker() as tracker:
        try:
            await tracker.track_async()
        except Exception as e:
            print(f"An error occurred: {e}")
        except BaseException:
            print(f"Script cancelled")
        finally:
            await tracker.cleanup_async()


if __name__ == '__main__':
    run(main())
