import asyncio
import importlib.util
from importlib.metadata import distribution
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import alembic
# The repository's migration directory is also a Python package. Add the
# installed Alembic package location for its migration-testing APIs.
alembic.__path__.append(str(distribution('alembic').locate_file('alembic')))
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.config import get_database_connect_args, get_database_url, require_test_database_schema
from src.db.models import AIKnowledgeChunk, AIKnowledgeSource, GlobalUser, Server, User
from src.modules.ai.knowledge import KNOWLEDGE_EMBEDDING_DIMENSIONS
from src.modules.ai.knowledge_identities import search_identity_aliases
from src.modules.ai.knowledge_retrieval import _database_branch, retrieve_server_knowledge

# Each synchronous test owns an asyncio.run loop. Do not reuse asyncpg
# connections across those loops (or change the application's global pool).
engine = create_async_engine(get_database_url(), connect_args=get_database_connect_args(), poolclass=NullPool)

MIGRATION_PATH = Path(__file__).resolve().parents[1] / 'alembic/versions/e1c7a4b9d620_add_knowledge_identity_index.py'


def _migration():
    spec = importlib.util.spec_from_file_location('identity_migration', MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _prepare_schema(schema):
    await engine.dispose()
    async with engine.begin() as connection:
        exists = (await connection.execute(text('SELECT 1 FROM pg_namespace WHERE nspname = :schema'), {'schema': schema})).first()
        if exists:
            raise RuntimeError('Identity integration tests require a fresh disposable schema')
        await connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    await engine.dispose()
    # Exercise the same migration chain used by deployment, not model DDL.
    try:
        await asyncio.to_thread(
            subprocess.run, [str(Path(sys.executable).with_name('alembic')), 'upgrade', 'head'],
            cwd=MIGRATION_PATH.parents[2], check=True, capture_output=True, text=True,
        )
    except BaseException:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        await engine.dispose()
        raise



@pytest.fixture(scope='module', autouse=True)
def disposable_schema():
    schema = require_test_database_schema(os.environ.get('DB_SCHEMA'))
    if not schema.startswith('cybercolors_test_identity_'):
        pytest.skip('Use a fresh DB_SCHEMA=cybercolors_test_identity_* for identity database integration tests')
    asyncio.run(_prepare_schema(schema))
    yield
    async def cleanup():
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        await engine.dispose()
    asyncio.run(cleanup())


class QueryEmbedder:
    provider_name = 'fake'
    model = 'identity-test'

    def __init__(self, *, fail=False):
        self.calls = 0
        self.fail = fail

    async def embed_texts(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError('embedding service unavailable')
        return [[1.0, *([0.0] * (KNOWLEDGE_EMBEDDING_DIMENSIONS - 1))] for _ in texts]


async def _seed(session):
    session.add(Server(server_id=1001, server_name='Identity test'))
    session.add(GlobalUser(discord_id=2001, username='aronz', global_name='Denis Bailyn'))
    await session.flush()
    session.add(User(server_id=1001, user_id=2001, server_nickname='Денис'))
    source = AIKnowledgeSource(server_id=1001, source_type='text', subject_type='admin', subject_user_id=2001,
                               title='Denis Bailyn', content_text='A community video editor.', status='ready', visibility='public_answer')
    session.add(source)
    await session.flush()
    session.add(AIKnowledgeChunk(server_id=1001, source_id=source.id, chunk_ordinal=0,
        chunk_text='Denis Bailyn is a community video editor.', text_hash=uuid4().hex, token_count=10,
        embedding=[0.0, 1.0, *([0.0] * (KNOWLEDGE_EMBEDDING_DIMENSIONS - 2))]))
    await session.flush()
    return source


def test_indexed_aliases_retrieve_linked_facts_without_reembedding():
    async def scenario():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            source = await _seed(session)
            for query in ['aronz', 'ARONZ', 'Who is aronz?', 'Who is aronz.', 'Что известно про aronz?', 'Denis Bailyn', 'Денис', '<@2001>']:
                embedder = QueryEmbedder()
                result = await retrieve_server_knowledge(session, server_id=1001, query=query, embedder=embedder, identity_enabled=True)
                assert [item['source_id'] for item in result['items']] == [str(source.id)], (query, result)
                assert result['items'][0]['identity']['username'] == 'aronz'
                assert result['items'][0]['score'] == 0.0
                assert result['items'][0]['retrieval_methods'] == ['identity']
                assert not result['degraded_components']
                assert embedder.calls == 1
            assert 'aronz' not in source.content_text
    asyncio.run(scenario())


def test_phrase_candidates_keep_full_handle_spelling():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            await _seed(session)
            await session.exec(text("UPDATE global_users SET username = 'foo_bar' WHERE discord_id = 2001"))
            for query in ['foo bar', 'Who is foo?', 'foo_bar123']:
                assert not (await search_identity_aliases(session, server_id=1001, query=query)).matches
            assert (await search_identity_aliases(session, server_id=1001, query='Who is @foo_bar?')).matches
            await session.exec(text("UPDATE global_users SET username = 'foo.bar' WHERE discord_id = 2001"))
            assert (await search_identity_aliases(session, server_id=1001, query='Who is @foo.bar?')).matches
            assert not (await search_identity_aliases(session, server_id=1001, query='foo bar')).matches
    asyncio.run(scenario())


def test_name_changes_replace_aliases_without_changing_chunks():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            await _seed(session)
            await session.exec(text("UPDATE global_users SET username = 'new_handle' WHERE discord_id = 2001"))
            assert not (await search_identity_aliases(session, server_id=1001, query='aronz')).matches
            assert (await search_identity_aliases(session, server_id=1001, query='new_handle')).matches
            await session.exec(text("UPDATE users SET server_nickname = NULL WHERE server_id = 1001 AND user_id = 2001"))
            assert not (await search_identity_aliases(session, server_id=1001, query='Денис')).matches
            assert (await search_identity_aliases(session, server_id=1001, query='Denis Bailyn')).matches
            assert (await session.exec(text('SELECT count(*) FROM ai_knowledge_chunks'))).scalar_one() == 1
    asyncio.run(scenario())


def test_shared_name_stays_ambiguous_even_if_only_one_person_has_knowledge():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            source = await _seed(session)
            session.add(GlobalUser(discord_id=2002, username='another_account'))
            await session.flush()
            session.add(User(server_id=1001, user_id=2002, server_nickname='Денис'))
            chunk = (await session.exec(select(AIKnowledgeChunk))).one()
            chunk.embedding = (await QueryEmbedder().embed_texts(['query']))[0]
            await session.flush()
            result = await retrieve_server_knowledge(session, server_id=1001, query='Денис', embedder=QueryEmbedder(), identity_enabled=True)
            assert result['items'] == []
            assert {person['user_id'] for person in result['ambiguities'][0]['candidates']} == {'2001', '2002'}
            chosen = await retrieve_server_knowledge(session, server_id=1001, query='Денис', target_user_ids=[2001], embedder=QueryEmbedder(), identity_enabled=True)
            assert not chosen['ambiguities']
            assert chosen['items'][0]['source_id'] == str(source.id)
            empty = await retrieve_server_knowledge(session, server_id=1001, query='Денис', target_user_ids=[2002], embedder=QueryEmbedder(), identity_enabled=True)
            assert not empty['items'] and not empty['ambiguities']
    asyncio.run(scenario())


def test_multiple_targets_keep_distinct_facts_and_report_insufficient_result_budget():
    async def scenario():
        async with AsyncSession(engine) as session:
            first = await _seed(session)
            session.add(GlobalUser(discord_id=2002, username='painter_account'))
            await session.flush()
            session.add(User(server_id=1001, user_id=2002))
            second = AIKnowledgeSource(server_id=1001, source_type='text', subject_type='admin', subject_user_id=2002,
                title='Another member', content_text='A painter.', status='ready', visibility='public_answer')
            session.add(second)
            await session.flush()
            session.add(AIKnowledgeChunk(server_id=1001, source_id=second.id, chunk_ordinal=0,
                chunk_text='This member paints.', text_hash=uuid4().hex, token_count=4,
                embedding=[0.0, 1.0, *([0.0] * (KNOWLEDGE_EMBEDDING_DIMENSIONS - 2))]))
            await session.flush()
            for query in ['Compare aronz and painter_account', 'Compare <@2001> and <@2002>']:
                result = await retrieve_server_knowledge(session, server_id=1001, query=query,
                    embedder=QueryEmbedder(), identity_enabled=True)
                assert {item['source_id'] for item in result['items']} == {str(first.id), str(second.id)}
                assert len(result['items']) == 2 and not result['ambiguities']
            limited = await retrieve_server_knowledge(session, server_id=1001, query='Compare them',
                target_user_ids=[2001, 2001, 2002], limit=1, embedder=QueryEmbedder(), identity_enabled=True)
            assert len(limited['items']) == 1 and len(limited['identity_matches']) == 2 and limited['truncated']
    asyncio.run(scenario())


def test_identity_branch_preserves_visibility_server_status_and_source_scope():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            source = await _seed(session)
            async def search(**kwargs):
                return await retrieve_server_knowledge(session, query='aronz', embedder=QueryEmbedder(), identity_enabled=True, **kwargs)
            assert not (await search(server_id=1002))['items']
            assert not (await search(server_id=1001, source_id=str(uuid4())))['items']
            for status, visibility, deleted in [('disabled', 'public_answer', False), ('ready', 'admin_answer', False), ('ready', 'public_answer', True)]:
                source.status, source.visibility = status, visibility
                from src.db.models import utcnow_utc_tz
                source.deleted_at = utcnow_utc_tz() if deleted else None
                await session.flush()
                assert not (await search(server_id=1001))['items']
            source.deleted_at = None
            source.visibility = 'admin_answer'
            await session.flush()
            assert (await search(server_id=1001, visibility='admin_answer'))['items'][0]['source_id'] == str(source.id)
            source.visibility = 'moderation'
            await session.flush()
            # Moderation still follows its existing semantic-only policy.
            assert not (await search(server_id=1001, visibility='moderation'))['items']
    asyncio.run(scenario())


def test_embedding_failure_still_returns_identity_facts_and_null_scores():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            source = await _seed(session)
            result = await retrieve_server_knowledge(session, server_id=1001, query='aronz', embedder=QueryEmbedder(fail=True), identity_enabled=True)
            assert result['degraded_components'] == ['semantic']
            assert result['items'][0]['source_id'] == str(source.id)
            assert result['items'][0]['score'] is None and result['items'][0]['distance'] is None
            from api.models.ai_knowledge import AIKnowledgeSearchResponseModel
            assert AIKnowledgeSearchResponseModel(**result).items[0].identity.username == 'aronz'
    asyncio.run(scenario())


def test_failed_identity_statement_does_not_abort_semantic_search():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            source = await _seed(session)
            chunk = (await session.exec(select(AIKnowledgeChunk))).one()
            chunk.embedding = (await QueryEmbedder().embed_texts(['query']))[0]
            await session.flush()
            await session.exec(text('ALTER TABLE ai_knowledge_identity_aliases RENAME TO unavailable_aliases'))
            result = await retrieve_server_knowledge(session, server_id=1001, query='aronz', embedder=QueryEmbedder(), identity_enabled=True)
            assert result['degraded_components'] == ['identity']
            assert result['items'][0]['source_id'] == str(source.id)
            assert (await session.exec(text('SELECT 1'))).scalar_one() == 1
    asyncio.run(scenario())


def test_relevant_later_chunk_ranks_first_and_common_word_gets_no_reserved_slot():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            source = await _seed(session)
            aligned = (await QueryEmbedder().embed_texts(['query']))[0]
            session.add(AIKnowledgeChunk(server_id=1001, source_id=source.id, chunk_ordinal=1,
                chunk_text='A relevant later passage.', text_hash=uuid4().hex, token_count=8, embedding=aligned))
            await session.flush()
            result = await retrieve_server_knowledge(session, server_id=1001, query='aronz', embedder=QueryEmbedder(), identity_enabled=True, limit=1)
            assert result['items'][0]['chunk_ordinal'] == 1
            await session.exec(text("UPDATE global_users SET username='may' WHERE discord_id=2001"))
            await session.exec(text('DELETE FROM ai_knowledge_chunks WHERE chunk_ordinal=1'))
            rules = AIKnowledgeSource(server_id=1001, source_type='text', subject_type='server', title='Posting links',
                                      status='ready', visibility='public_answer')
            session.add(rules)
            await session.flush()
            session.add(AIKnowledgeChunk(server_id=1001, source_id=rules.id, chunk_ordinal=0, chunk_text='Post relevant links.',
                text_hash=uuid4().hex, token_count=8, embedding=aligned))
            await session.flush()
            result = await retrieve_server_knowledge(session, server_id=1001, query='May I post links?', embedder=QueryEmbedder(), identity_enabled=True, limit=1)
            assert result['items'][0]['source_id'] == str(rules.id)
            assert result['identity_matches'][0]['evidence'][0]['match_type'] == 'alias_phrase'
    asyncio.run(scenario())


def test_backfill_is_idempotent_and_note_is_a_private_draft():
    async def scenario():
        await engine.dispose()
        from scripts.backfill_knowledge_identities import backfill_batch, identity_audit
        async with AsyncSession(engine) as session:
            await _seed(session)
            await session.exec(text('DELETE FROM ai_knowledge_identity_aliases'))
            assert (await identity_audit(session, server_id=1001))['missing_aliases'] == 1
            cursor, count = await backfill_batch(session, server_id=1001, after_user_id=0, batch_size=10)
            assert (cursor, count) == (2001, 1)
            indexed_at = (await session.exec(text('SELECT alias_kind, indexed_at FROM ai_knowledge_identity_aliases ORDER BY alias_kind'))).all()
            await backfill_batch(session, server_id=1001, after_user_id=0, batch_size=10)
            assert (await session.exec(text('SELECT alias_kind, indexed_at FROM ai_knowledge_identity_aliases ORDER BY alias_kind'))).all() == indexed_at
            assert (await identity_audit(session, server_id=1001))['missing_aliases'] == 0
            note = (await session.exec(text('SELECT is_published, is_public FROM product_release_notes WHERE id=:id'),
                                      params={'id': _migration().NOTE_ID})).one()
            assert note == (False, False)
    asyncio.run(scenario())


def test_database_branch_restores_timeout_and_transaction_after_cancellation():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as session:
            before = (await session.exec(text('SHOW statement_timeout'))).scalar_one()
            with pytest.raises(Exception, match='statement timeout'):
                async with _database_branch(session):
                    await session.exec(text('SELECT pg_sleep(2)'))
            assert (await session.exec(text('SHOW statement_timeout'))).scalar_one() == before
            assert (await session.exec(text('SELECT 1'))).scalar_one() == 1
    asyncio.run(scenario())


def test_concurrent_account_and_server_nickname_updates_do_not_restore_stale_aliases():
    async def scenario():
        await engine.dispose()
        async with AsyncSession(engine) as seed:
            seed.add(Server(server_id=9001, server_name='Concurrent identity test'))
            seed.add(GlobalUser(discord_id=9002, username='old_account', global_name='Visible name'))
            await seed.flush()
            seed.add(User(server_id=9001, user_id=9002, server_nickname='Old nickname'))
            await seed.commit()
        async with AsyncSession(engine) as account, AsyncSession(engine) as membership:
            await account.exec(text("UPDATE global_users SET username='new_account' WHERE discord_id=9002"))
            await membership.exec(text("SET LOCAL statement_timeout='2s'"))
            await membership.exec(text("UPDATE users SET server_nickname='New nickname' WHERE user_id=9002 AND server_id=9001"))
            await membership.commit()
            await account.commit()
        async with AsyncSession(engine) as session:
            names = (await session.exec(text('SELECT alias_text FROM ai_knowledge_identity_aliases WHERE server_id=9001'))).scalars().all()
            assert set(names) == {'new_account', 'Visible name', 'New nickname'}
    asyncio.run(scenario())


def test_backfill_and_rename_serialize_on_canonical_rows():
    async def scenario():
        await engine.dispose()
        from scripts.backfill_knowledge_identities import backfill_batch
        async with AsyncSession(engine) as seed:
            seed.add(Server(server_id=9101, server_name='Backfill concurrency test'))
            seed.add(GlobalUser(discord_id=9102, username='before_backfill'))
            await seed.flush()
            seed.add(User(server_id=9101, user_id=9102))
            await seed.commit()
        async with AsyncSession(engine) as batch:
            await backfill_batch(batch, server_id=9101, after_user_id=0, batch_size=10)
            started = asyncio.Event()
            async def rename():
                async with AsyncSession(engine) as writer:
                    await writer.exec(text("SET LOCAL statement_timeout='3s'"))
                    started.set()
                    await writer.exec(text("UPDATE global_users SET username='after_backfill' WHERE discord_id=9102"))
                    await writer.commit()
            pending = asyncio.create_task(rename())
            await started.wait()
            await batch.commit()
            await pending
        async with AsyncSession(engine) as session:
            names = (await session.exec(text('SELECT alias_text FROM ai_knowledge_identity_aliases WHERE server_id=9101'))).scalars().all()
            assert names == ['after_backfill']
            await session.exec(text('DELETE FROM users WHERE user_id=9102 AND server_id=9101'))
            assert not (await session.exec(text('SELECT 1 FROM ai_knowledge_identity_aliases WHERE server_id=9101'))).first()
    asyncio.run(scenario())


def test_migration_can_be_downgraded_and_upgraded_in_a_transaction():
    async def scenario():
        await engine.dispose()
        async with engine.connect() as conn:
            transaction = await conn.begin()
            def migrate(sync_conn, operation):
                migration = _migration()
                migration.op = Operations(MigrationContext.configure(sync_conn))
                getattr(migration, operation)()
            await conn.run_sync(lambda sync_conn: migrate(sync_conn, 'downgrade'))
            assert (await conn.execute(text("SELECT to_regclass('ai_knowledge_identity_aliases')"))).scalar_one() is None
            await conn.run_sync(lambda sync_conn: migrate(sync_conn, 'upgrade'))
            assert (await conn.execute(text("SELECT to_regclass('ai_knowledge_identity_aliases')"))).scalar_one() is not None
            await transaction.rollback()
    asyncio.run(scenario())


def test_dashboard_tool_and_answer_context_share_identity_results(monkeypatch):
    async def scenario():
        await engine.dispose()
        from api.models.ai_knowledge import AIKnowledgeSearchRequestModel
        from api.services import ai_knowledge as api_service
        from src.modules.ai import ai_main as ai_module
        from src.modules.ai import tools as ai_tools
        monkeypatch.setenv('AI_KNOWLEDGE_IDENTITY_SERVER_IDS', '1001')
        async def retrieve(*args, **kwargs):
            return await retrieve_server_knowledge(*args, **kwargs, embedder=QueryEmbedder())
        monkeypatch.setattr(api_service, 'retrieve_server_knowledge', retrieve)
        monkeypatch.setattr(ai_module, 'retrieve_server_knowledge', retrieve)
        monkeypatch.setattr(ai_tools, 'retrieve_server_knowledge', retrieve)
        async with AsyncSession(engine) as session:
            source = await _seed(session)
            dashboard = await api_service.search_knowledge_sources(session, server_id=1001, body=AIKnowledgeSearchRequestModel(query='Who is aronz?'))
            tool = await ai_tools._server_knowledge_tool(session=session, server_id=1001, query='Who is aronz?')
            assert dashboard.items[0].source_id == tool['items'][0]['source_id'] == str(source.id)
            prompt = await ai_module.AIMain._append_relevant_knowledge('Other context', session=session, server_id=1001,
                author_user_id=None, query='Who is aronz?', enabled=True)
            assert 'aronz' in prompt and 'Denis Bailyn is a community video editor.' in prompt
            assert 'Ignore incidental ordinary words' in prompt
    asyncio.run(scenario())


@pytest.mark.skipif(os.getenv('KNOWLEDGE_IDENTITY_BENCHMARK') != '1', reason='Opt-in 100,000-member query benchmark')
def test_identity_index_at_100000_members():
    async def scenario():
        import json
        import math
        import time
        await engine.dispose()
        async with AsyncSession(engine) as session:
            await _seed(session)
            await session.exec(text("INSERT INTO global_users (discord_id, username) SELECT 3000000+n, 'member' || n FROM generate_series(1,100000) AS n"))
            await session.exec(text("INSERT INTO users (user_id, server_id, is_member) SELECT 3000000+n, 1001, true FROM generate_series(1,100000) AS n"))
            await session.exec(text("UPDATE users SET server_nickname='May' WHERE user_id BETWEEN 3000001 AND 3000050"))
            await session.exec(text('ANALYZE ai_knowledge_identity_aliases'))
            await session.exec(text('ANALYZE users'))
            await session.exec(text('ANALYZE global_users'))
            plans = {}
            for name, predicate, index in [
                ('exact', "normalized_alias = 'aronz'", 'ix_knowledge_identity_exact'),
                ('sentence', "search_vector @@ kb_identity_any_terms('who is aronz') AND to_tsvector('simple', 'who is aronz') @@ alias_phrase", 'ix_knowledge_identity_search'),
                ('common', "search_vector @@ kb_identity_any_terms('What does May do?') AND to_tsvector('simple', 'What does May do?') @@ alias_phrase", 'ix_knowledge_identity_search'),
            ]:
                plan = (await session.exec(text(f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT user_id FROM ai_knowledge_identity_aliases WHERE server_id=1001 AND {predicate}'))).scalar_one()
                assert index in json.dumps(plan)
                plans[name] = plan
            timings = []
            for iteration in range(40):
                started = time.perf_counter()
                result = await search_identity_aliases(session, server_id=1001,
                    query='Who is aronz?' if iteration % 2 == 0 else 'What does May do?')
                timings.append((time.perf_counter() - started) * 1000)
                if iteration % 2 == 0:
                    assert result.matches[0]['identity']['user_id'] == '2001'
                else:
                    assert not result.matches and result.ambiguities[0]['overflow']
            p95 = sorted(timings)[math.ceil(len(timings) * .95) - 1]
            print(json.dumps({'identity_members': 100001, 'samples': len(timings), 'identity_cold_ms': timings[0],
                              'identity_p50_ms': sorted(timings)[19], 'identity_p95_ms': p95,
                              **{f'{name}_execution_ms': plan[0]['Execution Time'] for name, plan in plans.items()}}))
            assert p95 < 100
    asyncio.run(scenario())
