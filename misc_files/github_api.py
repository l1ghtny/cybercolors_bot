import os
import github
from dotenv import load_dotenv
from github import Github
import basevariables

load_dotenv()
# using an access token
access_token = os.getenv('github_token')
g = Github(access_token)

regular_bot = g.get_repo(full_name_or_id='l1ghtny/regular_bot')


async def get_release_notes():
    try:
        print('started analysis of releases')
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
                return release_date, release_title, release_text
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
        print(error)
        return release_date, release_title, release_text
