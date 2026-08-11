"""Add database-backed product release notes.

Revision ID: a0c4e8f2b691
Revises: 9f42c1a7e6bd
Create Date: 2026-08-11 23:30:00.000000
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "a0c4e8f2b691"
down_revision = "9f42c1a7e6bd"
branch_labels = None
depends_on = None


def _at(month: int, day: int, hour: int = 18) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


def upgrade() -> None:
    release_notes_table = op.create_table(
        "product_release_notes",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("title_en", sa.String(length=200), nullable=False),
        sa.Column("title_ru", sa.String(length=200), nullable=False),
        sa.Column("summary_en", sa.Text(), nullable=False),
        sa.Column("summary_ru", sa.Text(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_release_notes_published_at",
        "product_release_notes",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_product_release_notes_is_published",
        "product_release_notes",
        ["is_published"],
        unique=False,
    )

    op.bulk_insert(
        release_notes_table,
        [
            {
                "id": "2026-08-11-personal-name-settings",
                "published_at": _at(8, 11, 20),
                "title_en": "Simpler member-name settings",
                "title_ru": "Проще настроить имена участников",
                "summary_en": "Member names now have a focused personal preference instead of an unclear cycling control.",
                "summary_ru": "Теперь способ отображения имён выбирается в понятном меню личных настроек, а не переключается по кругу.",
                "changes": [
                    {"en": "Choose between each member's server name and Discord @username.", "ru": "Можно выбрать имя участника на сервере или его имя пользователя в Discord с символом @."},
                    {"en": "Each option explains exactly which name will be shown.", "ru": "Под каждым вариантом указано, какое имя будет показано."},
                    {"en": "The compact personal-settings menu keeps the dashboard header quieter.", "ru": "Компактное меню личных настроек не перегружает шапку панели."},
                ],
            },
            {
                "id": "2026-08-11-moderation-clarity",
                "published_at": _at(8, 11, 19),
                "title_en": "Clearer moderation history",
                "title_ru": "Понятнее журнал модерации",
                "summary_en": "Actions and cases now explain what happened without squeezing the important details.",
                "summary_ru": "В действиях и делах теперь проще увидеть, что произошло: важные сведения не теряются в тесных строках.",
                "changes": [
                    {"en": "Timed mutes and bans distinguish scheduled completion from a moderator reversal.", "ru": "У мутов и банов с истёкшим сроком теперь отдельный статус — их больше не путают с отменёнными действиями."},
                    {"en": "Action lists and details show cited rules by name in a dedicated column and section.", "ru": "В списке и карточке действия видны названия связанных правил; в таблице для них появился отдельный столбец."},
                    {"en": "Reasons and moderator commentary remain readable, and optional columns can be hidden.", "ru": "Причины и комментарии модераторов читаются целиком, а ненужные столбцы можно скрыть."},
                    {"en": "Case details and member profiles work better on narrow screens.", "ru": "Карточки дел и профили участников удобнее читать на небольших экранах."},
                ],
            },
            {
                "id": "2026-08-08-flexible-moderation-durations",
                "published_at": _at(8, 8),
                "title_en": "More flexible moderation durations",
                "title_ru": "Гибче сроки наказаний",
                "summary_en": "Moderators can set long temporary actions without the duration controls getting in the way.",
                "summary_ru": "Модераторы могут задавать длительные временные наказания без ограничений со стороны формы.",
                "changes": [
                    {"en": "Temporary bans can last up to one year.", "ru": "Временный бан можно выдать на срок до одного года."},
                    {"en": "Duration fields validate the entered value instead of silently changing it.", "ru": "Поле срока проверяет введённое значение и больше не меняет его незаметно."},
                    {"en": "Preset editing works consistently across moderation settings and action dialogs.", "ru": "Готовые сроки одинаково работают в настройках модерации и в окне действия."},
                ],
            },
            {
                "id": "2026-08-06-profiles-and-bot-surfaces",
                "published_at": _at(8, 6),
                "title_en": "Public profiles and separate bot surfaces",
                "title_ru": "Публичные профили и отдельные панели ботов",
                "summary_en": "Member information is easier to inspect, while Modral and CyberColors now keep their own identities and server routes.",
                "summary_ru": "Информацию об участниках стало проще посмотреть, а Modral и CyberColors теперь сохраняют собственные профили и маршруты серверов.",
                "changes": [
                    {"en": "The public profile command shows server details, presence, and warnings that the member can already see.", "ru": "Публичная команда профиля показывает данные участника на сервере, его статус и доступные ему предупреждения."},
                    {"en": "Profiles include server flair and use cached presence when live presence is unavailable.", "ru": "В профиле появились сведения о сервере; если текущий статус недоступен, используется последнее сохранённое значение."},
                    {"en": "The dashboard routes each server through its primary Discord application during multi-bot migrations.", "ru": "Во время перехода между ботами панель направляет сервер через его основное приложение Discord."},
                ],
            },
            {
                "id": "2026-08-02-scheduled-posts",
                "published_at": _at(8, 2),
                "title_en": "Scheduled posts with Discord-ready previews",
                "title_ru": "Отложенные публикации с предпросмотром Discord",
                "summary_en": "Teams can prepare bot messages in advance and see how formatting and mentions will look before delivery.",
                "summary_ru": "Команда может заранее подготовить сообщение от бота и проверить форматирование и упоминания до отправки.",
                "changes": [
                    {"en": "Create, edit, and manage scheduled bot posts from the dashboard.", "ru": "В панели можно создавать, редактировать и контролировать отложенные публикации."},
                    {"en": "Scheduled posts support file attachments.", "ru": "К отложенной публикации можно прикрепить файлы."},
                    {"en": "Previews render Discord formatting and controlled broadcast mentions.", "ru": "Предпросмотр показывает форматирование Discord и разрешённые массовые упоминания."},
                ],
            },
            {
                "id": "2026-07-31-mention-controls",
                "published_at": _at(7, 31),
                "title_en": "Explicit mention controls",
                "title_ru": "Понятные настройки упоминаний",
                "summary_en": "Message authors can decide exactly which Discord references should notify people.",
                "summary_ru": "Автор сообщения может точно выбрать, какие упоминания в Discord отправят уведомление.",
                "changes": [
                    {"en": "User and role mentions can notify or remain silent independently.", "ru": "Упоминания пользователей и ролей можно отдельно сделать обычными или беззвучными."},
                    {"en": "A clear “Do not ping” control applies the choice to the whole message.", "ru": "Переключатель «Не уведомлять» применяет выбор ко всему сообщению."},
                    {"en": "Controlled @everyone mentions are available where the sender has permission.", "ru": "Упоминание @everyone доступно только там, где у отправителя есть нужное разрешение."},
                ],
            },
            {
                "id": "2026-07-30-reply-editor",
                "published_at": _at(7, 30),
                "title_en": "A clearer automatic-reply editor",
                "title_ru": "Понятнее редактор автоответов",
                "summary_en": "Automatic replies are easier to create, review, and tune without learning the underlying trigger model.",
                "summary_ru": "Автоответы стало проще создавать, проверять и настраивать без знания внутреннего устройства триггеров.",
                "changes": [
                    {"en": "The editor separates handwritten triggers, reusable concepts, and AI-generated variations.", "ru": "В редакторе отдельно показаны ручные триггеры, переиспользуемые понятия и варианты, созданные ИИ."},
                    {"en": "A reply can start with one handwritten trigger.", "ru": "Для создания ответа достаточно одного ручного триггера."},
                    {"en": "Language coverage and generated examples are visible before saving.", "ru": "До сохранения видно, для каких языков и примеров сработает ответ."},
                ],
            },
            {
                "id": "2026-07-29-temp-voice-chat",
                "published_at": _at(7, 29),
                "title_en": "Better temporary voice archives",
                "title_ru": "Удобнее архивы временных каналов",
                "summary_en": "Temporary voice-channel history now reads more like Discord and remains usable with long conversations.",
                "summary_ru": "История временных голосовых каналов стала ближе к Discord и удобнее при длинной переписке.",
                "changes": [
                    {"en": "Archived chat renders Discord references and channel links.", "ru": "В архиве чата правильно отображаются упоминания и ссылки на каналы Discord."},
                    {"en": "Long histories scroll inside the archive instead of expanding the whole page.", "ru": "Длинная история прокручивается внутри архива и не растягивает всю страницу."},
                    {"en": "Participant status is easier to distinguish at a glance.", "ru": "Статус участников проще определить с первого взгляда."},
                ],
            },
            {
                "id": "2026-07-28-ai-destinations-and-history",
                "published_at": _at(7, 28),
                "title_en": "More control over AI, replies, and destinations",
                "title_ru": "Больше контроля над ИИ, ответами и каналами",
                "summary_en": "Server teams gained finer controls for the AI companion and for where bot messages can be sent.",
                "summary_ru": "Команда сервера получила более точные настройки ИИ-помощника и мест, куда бот может отправлять сообщения.",
                "changes": [
                    {"en": "Choose which tools the AI companion may use on each server.", "ru": "Для каждого сервера можно выбрать инструменты, доступные ИИ-помощнику."},
                    {"en": "Bot messages can target threads and forum posts, with channels ordered like Discord.", "ru": "Бот может отправлять сообщения в ветки и публикации форума, а каналы расположены в том же порядке, что и в Discord."},
                    {"en": "Automatic replies support per-reply cooldowns.", "ru": "Для каждого автоответа можно задать собственную задержку между срабатываниями."},
                    {"en": "Member nickname changes are recorded in nickname history.", "ru": "Изменения никнейма участника сохраняются в истории имён."},
                ],
            },
            {
                "id": "2026-07-27-safer-moderation-workflows",
                "published_at": _at(7, 27),
                "title_en": "Safer moderation workflows",
                "title_ru": "Надёжнее рабочие процессы модерации",
                "summary_en": "Linked actions, privacy controls, and update safeguards reduce ambiguity during routine moderation work.",
                "summary_ru": "Связанные действия, настройки хранения данных и защита при обновлении уменьшают риск ошибок в повседневной модерации.",
                "changes": [
                    {"en": "Mutes can link an existing warning, and bans can target users who already left the server.", "ru": "К муту можно привязать существующее предупреждение, а забанить — даже пользователя, который уже покинул сервер."},
                    {"en": "Moderation logs report whether an unban notification reached the user.", "ru": "В журнале видно, получил ли пользователь уведомление о снятии бана."},
                    {"en": "Privacy retention controls remove old dashboard sessions and moderation data on schedule.", "ru": "Настройки хранения данных по расписанию удаляют старые сессии панели и данные модерации."},
                    {"en": "The dashboard warns about unsaved work before loading an update.", "ru": "Перед обновлением панель предупреждает о несохранённых изменениях."},
                ],
            },
            {
                "id": "2026-07-26-commands-replies-and-knowledge",
                "published_at": _at(7, 26),
                "title_en": "Commands, replies, and knowledge in one place",
                "title_ru": "Команды, ответы и база знаний в одном месте",
                "summary_en": "Several configuration areas became searchable, localized, and easier to manage from the dashboard.",
                "summary_ru": "Разделы настроек стали удобнее: появился поиск, перевод интерфейса и более понятное управление из панели.",
                "changes": [
                    {"en": "Manage intent-based automatic replies and their target channels from focused tabs.", "ru": "Автоответы по смыслу и их целевые каналы настраиваются в отдельных вкладках."},
                    {"en": "Search and add YouTube videos and channels to the server knowledge base.", "ru": "Видео и каналы YouTube можно найти и добавить в базу знаний сервера."},
                    {"en": "Discord command visibility is shown in the Access section and supports inherited rules.", "ru": "Доступность команд Discord видна в разделе «Доступ» и учитывает унаследованные правила."},
                    {"en": "The command reference is localized and easier to use on mobile.", "ru": "Справочник команд переведён и стал удобнее на мобильных устройствах."},
                ],
            },
            {
                "id": "2026-07-22-messages-and-knowledge",
                "published_at": _at(7, 22),
                "title_en": "Richer bot messages and clearer knowledge jobs",
                "title_ru": "Больше возможностей у сообщений и базы знаний",
                "summary_en": "Bot announcements support richer content, while knowledge indexing shows what is happening and why.",
                "summary_ru": "Сообщения от бота поддерживают больше форматов, а в индексации базы знаний понятнее видно, что происходит.",
                "changes": [
                    {"en": "Turn bot replies into announcements and attach media.", "ru": "Ответ бота можно отправить как объявление и добавить к нему медиафайл."},
                    {"en": "Use the shared emoji picker in reply and birthday-message editors.", "ru": "В редакторах ответов и поздравлений появился общий выбор эмодзи."},
                    {"en": "Knowledge jobs show their source and indexing status more clearly.", "ru": "В задачах базы знаний понятнее показаны источник и статус индексации."},
                ],
            },
            {
                "id": "2026-07-21-access-and-bot-messaging",
                "published_at": _at(7, 21),
                "title_en": "Human-readable access controls and bot messaging",
                "title_ru": "Понятнее права доступа и сообщения от бота",
                "summary_en": "Server owners can understand permissions more easily and send audited messages as the bot.",
                "summary_ru": "Владельцам сервера проще разобраться в правах и отправлять от имени бота сообщения, которые сохраняются в журнале.",
                "changes": [
                    {"en": "RBAC permissions use readable names and descriptions instead of internal keys.", "ru": "Права доступа показываются понятными названиями и описаниями вместо внутренних ключей."},
                    {"en": "The dashboard includes a send-as-bot composer with an audit trail.", "ru": "В панели появился редактор сообщений от имени бота; отправки сохраняются в журнале."},
                    {"en": "Recent moderation actions can be searched and linked without copying identifiers.", "ru": "Недавнее действие модерации можно найти и привязать без копирования идентификатора."},
                ],
            },
            {
                "id": "2026-07-19-moderation-controls",
                "published_at": _at(7, 19),
                "title_en": "Moderation controls where the work happens",
                "title_ru": "Действия модерации прямо в журнале",
                "summary_en": "Common action controls moved into the moderation log and gained clearer identifiers and notifications.",
                "summary_ru": "Основные действия перенесены в журнал модерации; у записей появились понятные номера и уведомления.",
                "changes": [
                    {"en": "Revert and related controls are available from moderation log entries.", "ru": "Отменить действие и открыть связанные данные можно прямо из записи журнала."},
                    {"en": "Actions have human-readable numbers and searchable autocomplete.", "ru": "У действий появились понятные номера и поиск с автодополнением."},
                    {"en": "Users receive consistent notifications about moderation actions.", "ru": "Пользователи получают единообразные уведомления о действиях модерации."},
                    {"en": "Monitoring alerts support snooze and cooldown settings.", "ru": "Для уведомлений мониторинга можно задать паузу и минимальный интервал."},
                ],
            },
            {
                "id": "2026-07-17-cases-and-ai-review",
                "published_at": _at(7, 17),
                "title_en": "Stronger moderation cases and AI review",
                "title_ru": "Удобнее дела модерации и проверка ИИ",
                "summary_en": "Case evidence, moderation history, and AI suggestions are easier to review without leaving the dashboard.",
                "summary_ru": "Доказательства по делу, история модерации и предложения ИИ теперь удобнее проверять прямо в панели.",
                "changes": [
                    {"en": "Upload private case evidence through time-limited download links.", "ru": "К делу можно добавить закрытые доказательства с временными ссылками на скачивание."},
                    {"en": "Moderation journal entries and action details share consistent visuals.", "ru": "Записи журнала и карточки действий оформлены единообразно."},
                    {"en": "Review or dismiss several AI moderation suggestions at once.", "ru": "Несколько предложений ИИ по модерации можно проверить или отклонить за один раз."},
                    {"en": "Dashboard sign-in uses secured server-side sessions.", "ru": "Вход в панель переведён на защищённые серверные сессии."},
                ],
            },
            {
                "id": "2026-07-14-dashboard-foundations",
                "published_at": _at(7, 14),
                "title_en": "A more adaptable dashboard",
                "title_ru": "Панель лучше подстраивается под сервер",
                "summary_en": "Early dashboard improvements made navigation, localization, and server-specific views more practical.",
                "summary_ru": "Навигация, перевод интерфейса и страницы сервера стали удобнее для повседневной работы.",
                "changes": [
                    {"en": "Choose which roles appear in the server overview.", "ru": "Можно выбрать роли, которые отображаются в обзоре сервера."},
                    {"en": "Manage Discord command visibility from the dashboard.", "ru": "Доступность команд Discord настраивается из панели."},
                    {"en": "Moderation flows and labels are available in English and Russian.", "ru": "Основные разделы модерации и подписи доступны на русском и английском языках."},
                    {"en": "Action layouts remain usable at narrow browser widths.", "ru": "Карточки действий остаются удобными при небольшой ширине окна."},
                ],
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_product_release_notes_is_published", table_name="product_release_notes")
    op.drop_index("ix_product_release_notes_published_at", table_name="product_release_notes")
    op.drop_table("product_release_notes")
