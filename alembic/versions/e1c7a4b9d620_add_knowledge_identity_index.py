"""Index current Discord names separately from KB content.

Revision ID: e1c7a4b9d620
Revises: 49703b66f5d6
"""

from alembic import op
from datetime import datetime, timezone
import json
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e1c7a4b9d620"
down_revision = "49703b66f5d6"
branch_labels = None
depends_on = None
NOTE_ID = "2026-09-04-knowledge-discord-identities"


def _note_table():
    return sa.table("product_release_notes",
        sa.column("id", sa.String), sa.column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.column("title_en", sa.String), sa.column("title_ru", sa.String),
        sa.column("summary_en", sa.Text), sa.column("summary_ru", sa.Text),
        sa.column("change_type", sa.String), sa.column("surface", sa.String),
        sa.column("feature_en", sa.String), sa.column("feature_ru", sa.String),
        sa.column("changes", sa.JSON), sa.column("is_published", sa.Boolean), sa.column("is_public", sa.Boolean),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)))


def upgrade() -> None:
    op.create_table(
        "ai_knowledge_identity_aliases",
        sa.Column("server_id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("alias_kind", sa.String(30), primary_key=True),
        sa.Column("alias_text", sa.Text, nullable=False),
        sa.Column("normalized_alias", sa.Text, nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR, sa.Computed("to_tsvector('pg_catalog.simple', normalized_alias)", persisted=True), nullable=False),
        sa.Column("alias_phrase", postgresql.TSQUERY, sa.Computed("phraseto_tsquery('pg_catalog.simple', normalized_alias)", persisted=True), nullable=False),
        sa.Column("normalization_version", sa.Integer, server_default="1", nullable=False),
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["server_id", "user_id"], ["users.server_id", "users.user_id"], ondelete="CASCADE"),
        sa.CheckConstraint("alias_kind IN ('username', 'global_name', 'server_nickname')", name="ck_knowledge_identity_alias_kind"),
    )
    op.create_index("ix_knowledge_identity_exact", "ai_knowledge_identity_aliases", ["server_id", "normalized_alias"])
    op.create_index("ix_knowledge_identity_user", "ai_knowledge_identity_aliases", ["user_id"])
    op.create_index("ix_knowledge_identity_search", "ai_knowledge_identity_aliases", ["search_vector"], postgresql_using="gin")
    op.execute(r"""
        CREATE FUNCTION kb_identity_normalize(value text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT lower(normalize(btrim(regexp_replace(coalesce(value, ''), '\s+', ' ', 'g')), NFC))
        $$
    """)
    op.execute("""
        CREATE FUNCTION kb_identity_any_terms(value text) RETURNS tsquery
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT coalesce(string_agg(quote_literal(term), ' | ')::tsquery, ''::tsquery)
            FROM unnest(tsvector_to_array(to_tsvector('pg_catalog.simple', value))) AS terms(term)
        $$
    """)
    # All writers use the same projection, including OAuth and import updates.
    # Capture this migration's search_path rather than the trigger caller's path.
    op.execute("""
        CREATE FUNCTION kb_identity_refresh(member_server_id bigint, member_user_id bigint,
            alias_kinds text[] DEFAULT ARRAY['username', 'global_name', 'server_nickname']) RETURNS void
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
        BEGIN
            DELETE FROM ai_knowledge_identity_aliases AS a
            WHERE a.server_id = member_server_id AND a.user_id = member_user_id
              AND a.alias_kind = ANY(alias_kinds)
              AND NOT EXISTS (
                SELECT 1 FROM users AS m JOIN global_users AS g ON g.discord_id = m.user_id
                CROSS JOIN LATERAL (VALUES ('username', g.username), ('global_name', g.global_name),
                    ('server_nickname', m.server_nickname)) AS v(kind, value)
                WHERE m.server_id = member_server_id AND m.user_id = member_user_id
                  AND v.kind = a.alias_kind AND kb_identity_normalize(v.value) <> ''
              );
            INSERT INTO ai_knowledge_identity_aliases
                (server_id, user_id, alias_kind, alias_text, normalized_alias)
            SELECT m.server_id, m.user_id, v.kind, v.value, kb_identity_normalize(v.value)
            FROM users AS m JOIN global_users AS g ON g.discord_id = m.user_id
            CROSS JOIN LATERAL (VALUES ('username', g.username), ('global_name', g.global_name),
                ('server_nickname', m.server_nickname)) AS v(kind, value)
            WHERE m.server_id = member_server_id AND m.user_id = member_user_id
              AND v.kind = ANY(alias_kinds)
              AND kb_identity_normalize(v.value) <> ''
            ON CONFLICT (server_id, user_id, alias_kind) DO UPDATE
            SET alias_text = EXCLUDED.alias_text, normalized_alias = EXCLUDED.normalized_alias,
                normalization_version = 1, indexed_at = clock_timestamp()
            WHERE ai_knowledge_identity_aliases.alias_text IS DISTINCT FROM EXCLUDED.alias_text
               OR ai_knowledge_identity_aliases.normalized_alias IS DISTINCT FROM EXCLUDED.normalized_alias
               OR ai_knowledge_identity_aliases.normalization_version <> 1;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION kb_identity_membership_changed() RETURNS trigger
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM 1 FROM global_users WHERE discord_id = NEW.user_id FOR SHARE;
                PERFORM kb_identity_refresh(NEW.server_id, NEW.user_id);
            ELSE
                PERFORM kb_identity_refresh(NEW.server_id, NEW.user_id, ARRAY['server_nickname']);
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION kb_identity_account_changed() RETURNS trigger
        LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
        DECLARE membership record;
        BEGIN
            FOR membership IN SELECT server_id FROM users WHERE user_id = NEW.discord_id ORDER BY server_id LOOP
                PERFORM kb_identity_refresh(membership.server_id, NEW.discord_id, ARRAY['username', 'global_name']);
            END LOOP;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER knowledge_identity_membership_insert AFTER INSERT ON users
        FOR EACH ROW EXECUTE FUNCTION kb_identity_membership_changed()""")
    op.execute("""CREATE TRIGGER knowledge_identity_membership_update AFTER UPDATE OF server_nickname ON users
        FOR EACH ROW WHEN (OLD.server_nickname IS DISTINCT FROM NEW.server_nickname)
        EXECUTE FUNCTION kb_identity_membership_changed()""")
    op.execute("""CREATE TRIGGER knowledge_identity_account_update AFTER UPDATE OF username, global_name ON global_users
        FOR EACH ROW WHEN (OLD.username IS DISTINCT FROM NEW.username OR OLD.global_name IS DISTINCT FROM NEW.global_name)
        EXECUTE FUNCTION kb_identity_account_changed()""")
    op.get_bind().execute(_note_table().insert().values(
        id=NOTE_ID, published_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        title_en="Find linked member facts by Discord account name",
        title_ru="Поиск сведений об участнике по имени аккаунта Discord",
        summary_en="Knowledge-base search and AI answers can use the linked account's current names, even when those names are absent from the saved text.",
        summary_ru="Поиск в базе знаний и ответы ИИ учитывают текущие имена привязанного аккаунта, даже если этих имён нет в тексте записи.",
        change_type="fixed", surface="both", feature_en="AI · Knowledge base", feature_ru="ИИ · База знаний",
        changes=sa.cast(op.inline_literal(json.dumps([
            {"en": "Search by Discord username, display name, server nickname, or an actual account mention.",
             "ru": "Участника можно найти по имени пользователя Discord, отображаемому имени, нику на сервере или упоминанию аккаунта."},
            {"en": "Search results explain which name matched and offer account choices when a name is shared.",
             "ru": "В результатах видно, какое имя совпало с запросом. Если оно подходит нескольким аккаунтам, можно выбрать нужный."},
            {"en": "Account name changes update lookup without requiring edits to the saved biography.",
             "ru": "После смены имени аккаунта поиск обновляется без правок биографии в базе знаний."},
        ], ensure_ascii=False), type_=sa.Text()), sa.JSON()),
        # Publish after pilot activation and runtime verification, not while the
        # identity feature flag is still disabled during a rolling deployment.
        is_published=False, is_public=False, created_at=sa.func.now(),
    ))


def downgrade() -> None:
    table = _note_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))
    op.execute("DROP TRIGGER knowledge_identity_account_update ON global_users")
    op.execute("DROP TRIGGER knowledge_identity_membership_update ON users")
    op.execute("DROP TRIGGER knowledge_identity_membership_insert ON users")
    op.execute("DROP FUNCTION kb_identity_account_changed()")
    op.execute("DROP FUNCTION kb_identity_membership_changed()")
    op.execute("DROP FUNCTION kb_identity_refresh(bigint, bigint, text[])")
    op.execute("DROP FUNCTION kb_identity_any_terms(text)")
    op.execute("DROP FUNCTION kb_identity_normalize(text)")
    op.drop_table("ai_knowledge_identity_aliases")
