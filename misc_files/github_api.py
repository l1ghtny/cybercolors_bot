import os
import github
from dotenv import load_dotenv
from github import Github
import misc_files.basevariables as basevariables
import datetime
import pytz
from modules.logs_setup import logger

load_dotenv()
# using an access token
access_token = os.getenv('github_token')
g = Github(access_token)

regular_bot = g.get_repo(full_name_or_id='l1ghtny/regular_bot')
logger = logger.logging.getLogger("bot")


async def get_release_notes():
    try:
        logger.info('started analysis of releases')
        release = regular_bot.get_latest_release()
        release_id = release.id
        release_text = release.body
        release_title = release.title
        release_date = release.created_at
        conn, cursor = await basevariables.access_db_basic()
        first_query = 'SELECT * from "public".githubdata ORDER BY last_release_datetime DESC'
        cursor.execute(first_query)
        last_date_row = cursor.fetchone()
        if last_date_row is None:
            query = 'INSERT INTO "public".githubdata (last_release_id, last_release_datetime) VALUES (%s, %s)'
            values = (release_id, release_date,)
            cursor.execute(query, values)
            conn.commit()
            conn.close()
            return release_date, release_title, release_text
        else:
            last_date = last_date_row['last_release_datetime']
            if last_date != release_date:
                query = 'INSERT INTO "public".githubdata (last_release_id, last_release_datetime) VALUES (%s, %s)'
                values = (release_id, release_date,)
                cursor.execute(query, values)
                conn.commit()
                conn.close()
                tz_info = pytz.timezone('Europe/Moscow')
                release_date_msc = release_date.replace(tzinfo=datetime.timezone.utc).astimezone(tz=tz_info)
                release_date_final = release_date_msc.replace(tzinfo=None)
                return release_date_final, release_title, release_text
            else:
                conn.close()
                release_date = None
                release_title = None
                release_text = None
                return release_date, release_title, release_text

    except github.GithubException as error:
        release_date = None
        release_title = None
        release_text = None
        logger.info(f'{error}')
        return release_date, release_title, release_text
