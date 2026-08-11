"""Complete the release-note inventory and classify changes.

Revision ID: e4a1c7d9b205
Revises: c6d9f2a4b731
Create Date: 2026-08-12 00:30:00.000000
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "e4a1c7d9b205"
down_revision = "c6d9f2a4b731"
branch_labels = None
depends_on = None


def _at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def _note(
    note_id: str,
    published_at: datetime,
    change_type: str,
    surface: str,
    feature_en: str,
    feature_ru: str,
    title_en: str,
    title_ru: str,
    summary_en: str,
    summary_ru: str,
    changes: list[tuple[str, str]],
    action: tuple[str, str, str] | None = None,
) -> dict[str, object]:
    return {
        "id": note_id,
        "published_at": published_at,
        "change_type": change_type,
        "surface": surface,
        "feature_en": feature_en,
        "feature_ru": feature_ru,
        "title_en": title_en,
        "title_ru": title_ru,
        "summary_en": summary_en,
        "summary_ru": summary_ru,
        "changes": [{"en": en, "ru": ru} for en, ru in changes],
        "action_label_en": action[0] if action else None,
        "action_label_ru": action[1] if action else None,
        "action_path": action[2] if action else None,
        "is_published": True,
    }


# Feature names describe the exact place or command affected. The surface field
# remains intentionally broader so changes shared by the bot and dashboard show
# up in both filters.
EXISTING_NOTE_METADATA = {
    "2026-08-11-member-name-preference-v2": ("improved", "Personal settings · Member names", "Личные настройки · Имена участников"),
    "2026-08-11-action-completion-status-v2": ("fixed", "Moderation · Action history", "Модерация · История действий"),
    "2026-08-11-rule-citations-v2": ("improved", "Moderation · Action history", "Модерация · История действий"),
    "2026-08-11-moderation-layout-v2": ("fixed", "Moderation · Actions and cases", "Модерация · Действия и дела"),
    "2026-08-08-moderation-durations-v2": ("fixed", "Moderation · Duration settings", "Модерация · Настройки сроков"),
    "2026-08-06-public-profile-command-v2": ("added", "Discord command · /profile", "Команда Discord · /profile"),
    "2026-08-06-bot-profiles-v2": ("improved", "Server setup · Bot identity", "Настройка сервера · Профиль бота"),
    "2026-08-02-scheduled-posts-v2": ("added", "Replies · Scheduled posts", "Ответы · Отложенные публикации"),
    "2026-08-02-discord-preview-v2": ("improved", "Replies · Bot message composer", "Ответы · Сообщение от бота"),
    "2026-07-31-mention-delivery-v2": ("improved", "Replies · Bot message composer", "Ответы · Сообщение от бота"),
    "2026-07-30-reply-editor-v2": ("improved", "Replies · Automatic replies", "Ответы · Автоответы"),
    "2026-07-29-temp-voice-archives-v2": ("improved", "Temporary channels · Chat archive", "Временные каналы · Архив чата"),
    "2026-07-28-ai-tool-access-v2": ("added", "AI · Companion settings", "ИИ · Настройки помощника"),
    "2026-07-28-thread-destinations-v2": ("added", "Replies · Bot message composer", "Ответы · Сообщение от бота"),
    "2026-07-28-reply-cooldowns-v2": ("added", "Replies · Automatic replies", "Ответы · Автоответы"),
    "2026-07-28-nickname-history-v2": ("added", "Members · Name history", "Участники · История имён"),
    "2026-07-27-linked-actions-v2": ("added", "Discord moderation · Mute, kick, and ban", "Модерация в Discord · Мут, кик и бан"),
    "2026-07-27-unban-delivery-v2": ("improved", "Discord command · /mod unban", "Команда Discord · /mod unban"),
    "2026-07-27-retention-controls-v2": ("added", "Settings · Security and retention", "Настройки · Безопасность и хранение данных"),
    "2026-07-27-safe-dashboard-update-v2": ("improved", "Dashboard updates", "Обновления панели"),
    "2026-07-26-intent-replies-v2": ("added", "Replies · Automatic replies", "Ответы · Автоответы"),
    "2026-07-26-youtube-knowledge-v2": ("added", "AI · Knowledge sources", "ИИ · Источники базы знаний"),
    "2026-07-26-command-visibility-v2": ("added", "Access · Discord commands", "Доступ · Команды Discord"),
    "2026-07-26-command-reference-v2": ("improved", "Documentation · Discord commands", "Документация · Команды Discord"),
    "2026-07-22-announcements-and-media-v2": ("added", "Replies · Bot message composer", "Ответы · Сообщение от бота"),
    "2026-07-22-emoji-picker-v2": ("added", "Replies and birthdays · Message editors", "Ответы и дни рождения · Редакторы сообщений"),
    "2026-07-22-knowledge-job-status-v2": ("improved", "AI · Knowledge jobs", "ИИ · Задачи базы знаний"),
    "2026-07-21-readable-access-v2": ("improved", "Access · Role permissions", "Доступ · Права ролей"),
    "2026-07-21-send-as-bot-v2": ("added", "Replies · Bot message composer", "Ответы · Сообщение от бота"),
    "2026-07-19-action-controls-v2": ("added", "Moderation · Action history", "Модерация · История действий"),
    "2026-07-19-moderation-notices-v2": ("improved", "Discord moderation · User notifications", "Модерация в Discord · Уведомления участников"),
    "2026-07-19-monitoring-alert-controls-v2": ("added", "Monitoring · Alert settings", "Мониторинг · Настройки уведомлений"),
    "2026-07-17-private-case-evidence-v2": ("added", "Moderation · Cases", "Модерация · Дела"),
    "2026-07-17-bulk-ai-review-v2": ("added", "AI · Moderation queue", "ИИ · Очередь модерации"),
    "2026-07-17-secure-dashboard-sessions-v2": ("improved", "Dashboard sign-in", "Вход в панель"),
    "2026-07-14-overview-roles-v2": ("added", "Settings · Server overview", "Настройки · Обзор сервера"),
    "2026-07-14-bilingual-moderation-v2": ("improved", "Dashboard language", "Язык панели"),
}


NEW_NOTES = [
    _note(
        "2026-08-11-warns-legacy-reasons", _at(8, 11, 19, 55), "fixed", "bot",
        "Discord command · /warns", "Команда Discord · /warns",
        "/warns now explains imported warnings", "/warns теперь объясняет старые предупреждения",
        "Warnings imported from the old system no longer show a dead rule reference with no explanation.",
        "Предупреждения из старой системы больше не показывают недоступное правило без объяснения.",
        [("When an imported warning has no link to a current rule, the rule section is hidden.", "Если старое предупреждение не связано с действующим правилом, раздел с правилом не показывается."),
         ("The card shows the member-facing reason that was stored during import.", "В карточке показывается причина, сохранённая при импорте и доступная участнику."),
         ("Private moderator commentary, cases, and moderator identity remain hidden.", "Закрытый комментарий, дело и имя модератора по-прежнему не раскрываются.")],
    ),
    _note(
        "2026-08-11-member-display-name-fix", _at(8, 11, 19, 45), "fixed", "both",
        "Member profiles · Server nickname", "Профили участников · Никнейм на сервере",
        "Server nicknames now appear consistently", "Никнейм на сервере теперь показывается правильно",
        "Member profiles and name history now use the server-specific nickname Discord sends for that membership.",
        "В профиле участника и истории имён теперь используется никнейм именно с этого сервера.",
        [("A missing server nickname falls back to the Discord username instead of leaving an unexplained blank.", "Если никнейм на сервере не задан, показывается имя пользователя Discord, а не пустое место.")],
        ("Open members", "Открыть участников", "/dashboard/{server_id}/users"),
    ),
    _note(
        "2026-08-09-birthday-role-reconciliation", _at(8, 9, 18, 30), "fixed", "bot",
        "Birthdays · Birthday role", "Дни рождения · Роль именинника",
        "Birthday roles are reconciled separately on every server", "Роль именинника проверяется отдельно на каждом сервере",
        "A member who shares several servers with the bot no longer keeps or loses a birthday role because of another server's state.",
        "Если участник состоит на нескольких серверах с ботом, роль именинника больше не зависит от состояния на другом сервере.",
        [("The bot records role state per server and removes stale roles when a birthday ends.", "Бот хранит состояние роли отдельно для каждого сервера и снимает устаревшую роль после дня рождения."),
         ("A reconciliation pass repairs roles missed by an earlier run.", "Повторная проверка исправляет роли, пропущенные во время предыдущего запуска.")],
        ("Open birthday settings", "Открыть настройки дней рождения", "/dashboard/{server_id}/birthdays?tab=settings"),
    ),
    _note(
        "2026-08-06-warns-command", _at(8, 6, 18, 30), "added", "bot",
        "Discord command · /warns", "Команда Discord · /warns",
        "Members can check active warnings with /warns", "Участники могут проверить активные предупреждения через /warns",
        "The public command shows the requester's warnings by default or the warnings of a selected member.",
        "Команда по умолчанию показывает предупреждения автора запроса, но можно выбрать другого участника.",
        [("The localized card shows active warnings, public rule labels or reasons, and issue dates.", "В локализованной карточке видны активные предупреждения, доступные правила или причины и даты выдачи."),
         ("The response does not reveal moderator commentary, moderator identity, cases, or dashboard links.", "Команда не раскрывает комментарии и имя модератора, дела или ссылки на панель."),
         ("Mentions in the card do not notify the selected member.", "Упоминание в карточке не отправляет выбранному участнику уведомление.")],
    ),
    _note(
        "2026-08-06-moderator-profile-command", _at(8, 6, 18, 20), "added", "both",
        "Discord command · /mod profile", "Команда Discord · /mod profile",
        "Moderators can open a private member summary in Discord", "Модератор может открыть закрытую сводку об участнике в Discord",
        "/mod profile combines member details and recent moderation history without requiring a trip to the dashboard.",
        "/mod profile объединяет данные участника и недавнюю историю модерации — открывать панель необязательно.",
        [("The private card includes join dates, action and case totals, commonly cited rules, and recent actions.", "В закрытой карточке видны даты вступления, количество действий и дел, часто упоминаемые правила и недавние действия."),
         ("A button opens the full member profile in the dashboard when more detail is needed.", "Если нужны подробности, кнопка открывает полный профиль участника в панели.")],
        ("Open members", "Открыть участников", "/dashboard/{server_id}/users"),
    ),
    _note(
        "2026-07-30-kick-message-cleanup", _at(7, 30, 18, 30), "added", "bot",
        "Discord command · /mod kick", "Команда Discord · /mod kick",
        "A kick can also remove the member's recent messages", "При кике можно удалить недавние сообщения участника",
        "/mod kick now has the same evidence-aware cleanup controls as other moderation actions.",
        "/mod kick теперь поддерживает ту же очистку сообщений с сохранением доказательств, что и другие действия модерации.",
        [("Choose a recent time window, a maximum number of messages, and an optional channel.", "Можно выбрать период, максимальное количество сообщений и при необходимости конкретный канал."),
         ("Deleted logged messages remain linked to the action as evidence.", "Удалённые сообщения из журнала остаются связанными с действием как доказательства.")],
    ),
    _note(
        "2026-07-29-russian-reply-matching", _at(7, 29, 18, 30), "improved", "bot",
        "Automatic replies · Russian matching", "Автоответы · Распознавание русского языка",
        "Russian automatic replies recognize more word forms", "Автоответы лучше распознают формы русских слов",
        "A configured phrase can now match common Russian inflections instead of requiring the exact stored form.",
        "Фраза может сработать на распространённые формы русских слов, а не только на точное совпадение с сохранённым вариантом.",
        [("The same language-aware matching is used for handwritten triggers and reusable concepts.", "Одинаковая проверка форм слов используется для ручных триггеров и переиспользуемых понятий.")],
        ("Open automatic replies", "Открыть автоответы", "/dashboard/{server_id}/replies?tab=automatic"),
    ),
    _note(
        "2026-07-29-cat-command-media", _at(7, 29, 18, 20), "fixed", "bot",
        "Discord command · /cat", "Команда Discord · /cat",
        "/cat handles generated images and long captions reliably", "/cat надёжнее отправляет изображения и длинные подписи",
        "Generated cat images are uploaded in a Discord-compatible format, and captions no longer fail when they exceed one message.",
        "Изображения котов отправляются в совместимом с Discord формате, а длинная подпись больше не ломает команду.",
        [("Short captions can use more of Discord's message limit.", "Короткая подпись теперь может занимать большую часть лимита сообщения."),
         ("Long captions are split into readable follow-up messages.", "Длинная подпись разбивается на несколько читаемых сообщений.")],
    ),
    _note(
        "2026-07-27-rule-selection-reliability", _at(7, 27, 18, 30), "fixed", "bot",
        "Discord moderation · Rule selection", "Модерация в Discord · Выбор правила",
        "Rule selection stays within Discord's response deadline", "Выбор правила укладывается в срок ответа Discord",
        "Large rule lists no longer make moderation autocomplete time out or repeat the same rule label.",
        "Большой список правил больше не приводит к тайм-ауту автодополнения и не дублирует названия правил.",
        [("Autocomplete returns quickly while continuing to search active server rules.", "Автодополнение отвечает быстро и при этом продолжает искать среди действующих правил сервера."),
         ("Moderation notices avoid duplicate rule numbers and names.", "В уведомлениях модерации больше не повторяются номер и название правила.")],
        ("Open moderation rules", "Открыть правила модерации", "/dashboard/{server_id}/moderation?tab=rules"),
    ),
    _note(
        "2026-07-21-warnings-do-not-expire", _at(7, 21, 18, 30), "fixed", "both",
        "Moderation · Warnings", "Модерация · Предупреждения",
        "Warnings no longer ask for an expiry duration", "Для предупреждения больше не нужно выбирать срок",
        "A warning remains active until a moderator reverts it; duration applies only to mutes and temporary bans.",
        "Предупреждение остаётся активным, пока модератор его не отменит. Срок используется только для мута и временного бана.",
        [("Discord action menus hide the duration field when Warning is selected.", "В меню действий Discord поле срока скрывается после выбора предупреждения."),
         ("The dashboard and bot now follow the same warning lifecycle.", "Панель и бот теперь одинаково обрабатывают срок предупреждения.")],
        ("Open action history", "Открыть историю действий", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-07-20-message-moderation-actions", _at(7, 20, 18, 30), "added", "both",
        "Discord message menu · Moderation actions", "Меню сообщения Discord · Действия модерации",
        "Start or document moderation from the reported message", "Начинайте или оформляйте действие прямо из сообщения",
        "The message context menu can create a moderation action or attach the message to an existing action.",
        "Через контекстное меню сообщение можно превратить в новое действие модерации или связать с уже существующим.",
        [("Starting an action archives the source message, applies the selected rule, and links the message as evidence.", "При создании действия исходное сообщение сохраняется, к действию добавляется выбранное правило, а сообщение связывается как доказательство."),
         ("Link to action accepts a readable action number, so moderators do not need to copy UUIDs.", "Для привязки достаточно понятного номера действия — копировать UUID не нужно.")],
        ("Open action history", "Открыть историю действий", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-07-20-lockdown-controls", _at(7, 20, 18, 20), "improved", "both",
        "Moderation · Lockdown", "Модерация · Блокировка сервера",
        "Lockdown can apply different slowmode settings by channel", "Для блокировки можно задать отдельный slowmode в каждом канале",
        "Incident controls are now explicit instead of hiding several server-wide changes behind one switch.",
        "Настройки для инцидента теперь показывают каждое изменение сервера отдельно, а не прячут их за одним переключателем.",
        [("Set slowmode per channel and temporarily restrict invites or member DMs.", "Можно отдельно настроить slowmode в каналах и временно ограничить приглашения или личные сообщения участников."),
         ("The panel shows the active verification, raid-alert, and membership-screening state.", "В панели видны текущие настройки проверки, защиты от рейдов и проверки новых участников.")],
        ("Open lockdown", "Открыть блокировку сервера", "/dashboard/{server_id}/moderation?tab=lockdown"),
    ),
    _note(
        "2026-07-17-ai-images-and-reply-context", _at(7, 17, 18, 30), "improved", "bot",
        "AI · Images and replied messages", "ИИ · Изображения и ответы на сообщения",
        "AI responses understand more of the Discord message", "ИИ учитывает больше данных из сообщения Discord",
        "The assistant and AI moderation now handle image attachments more reliably and keep replied-to authors separate from the requester.",
        "ИИ-помощник и ИИ-модерация надёжнее обрабатывают изображения и не путают автора исходного сообщения с автором запроса.",
        [("If Discord blocks a direct image URL, the bot downloads the attachment and supplies a compatible copy to the model.", "Если модель не может открыть прямую ссылку Discord, бот скачивает вложение и передаёт совместимую копию."),
         ("Replies include public-safe context about the original message and its author.", "При ответе учитываются исходное сообщение и доступные публичные сведения о его авторе.")],
        ("Open AI settings", "Открыть настройки ИИ", "/dashboard/{server_id}/ai?tab=companion"),
    ),
    _note(
        "2026-07-16-member-join-persistence", _at(7, 16, 18, 30), "fixed", "both",
        "Members · Server membership", "Участники · Членство на сервере",
        "New members are saved with the correct server join time", "Новые участники сохраняются с правильной датой вступления",
        "Member profiles no longer lose server-specific membership data when the bot first sees a new join.",
        "Профиль участника больше не теряет данные о членстве на сервере, когда бот впервые видит нового участника.",
        [("The stored join time and server membership are available to profiles, activity views, and moderation tools.", "Сохранённые дата вступления и членство доступны в профиле, активности и инструментах модерации.")],
        ("Open members", "Открыть участников", "/dashboard/{server_id}/users"),
    ),
]


def _release_notes_table() -> sa.TableClause:
    return sa.table(
        "product_release_notes",
        sa.column("id", sa.String),
        sa.column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.column("title_en", sa.String),
        sa.column("title_ru", sa.String),
        sa.column("summary_en", sa.Text),
        sa.column("summary_ru", sa.Text),
        sa.column("change_type", sa.String),
        sa.column("surface", sa.String),
        sa.column("feature_en", sa.String),
        sa.column("feature_ru", sa.String),
        sa.column("action_label_en", sa.String),
        sa.column("action_label_ru", sa.String),
        sa.column("action_path", sa.String),
        sa.column("changes", sa.JSON),
        sa.column("is_published", sa.Boolean),
    )


def upgrade() -> None:
    op.add_column(
        "product_release_notes",
        sa.Column("change_type", sa.String(length=16), server_default="improved", nullable=False),
    )
    op.create_check_constraint(
        "ck_product_release_notes_change_type",
        "product_release_notes",
        "change_type IN ('added', 'fixed', 'improved')",
    )

    table = _release_notes_table()
    bind = op.get_bind()
    for note_id, (change_type, feature_en, feature_ru) in EXISTING_NOTE_METADATA.items():
        bind.execute(
            table.update()
            .where(table.c.id == note_id)
            .values(
                change_type=change_type,
                feature_en=feature_en,
                feature_ru=feature_ru,
            )
        )

    # This deployment detail does not help moderators understand or use a feature.
    bind.execute(
        table.update()
        .where(table.c.id == "2026-08-06-bot-profiles-v2")
        .values(is_published=False)
    )

    bind.execute(
        table.update()
        .where(table.c.id == "2026-07-31-mention-delivery-v2")
        .values(
            title_en="Choose whether mentions in bot messages notify people",
            title_ru="Выберите, должны ли упоминания в сообщении бота отправлять уведомления",
            summary_en="In Replies → Bot message composer, mention text and notification delivery can now be controlled separately.",
            summary_ru="В разделе «Ответы» → «Сообщение от бота» текст упоминания и само уведомление теперь настраиваются отдельно.",
        )
    )
    bind.execute(
        table.update()
        .where(table.c.id == "2026-08-02-scheduled-posts-v2")
        .values(
            changes=[
                {"en": "See when a post will be sent and pause or edit it before delivery.", "ru": "Посмотрите время следующей отправки, приостановите публикацию или измените её заранее."},
                {"en": "Attach files that will be stored securely and sent with the scheduled message.", "ru": "К публикации можно приложить файлы: они сохранятся и будут отправлены вместе с сообщением."},
                {"en": "Delivery history distinguishes sent, failed, and skipped runs.", "ru": "В истории отправок отдельно показаны успешные, неудачные и пропущенные запуски."},
            ]
        )
    )
    bind.execute(
        table.update()
        .where(table.c.id == "2026-07-27-linked-actions-v2")
        .values(
            title_en="Create a warning together with a mute, kick, or ban",
            title_ru="Создавайте предупреждение вместе с мутом, киком или баном",
            summary_en="Discord moderation commands can create a linked warning in the same case as the main action.",
            summary_ru="Команды модерации в Discord могут создать связанное предупреждение в том же деле, что и основное действие.",
            changes=[
                {"en": "Enable Add warning on a mute, kick, or ban; a new case is created when none is selected.", "ru": "Включите «Добавить предупреждение» при муте, кике или бане. Если дело не выбрано, бот создаст новое."},
                {"en": "The moderator receipt links both action numbers.", "ru": "В закрытой карточке модератора есть ссылки на номера обоих действий."},
                {"en": "A ban can also target a user who has already left the server.", "ru": "Забанить можно и пользователя, который уже покинул сервер."},
            ],
        )
    )

    op.bulk_insert(table, NEW_NOTES)
    op.alter_column("product_release_notes", "change_type", server_default=None)


def downgrade() -> None:
    table = _release_notes_table()
    bind = op.get_bind()
    bind.execute(table.delete().where(table.c.id.in_([note["id"] for note in NEW_NOTES])))
    bind.execute(
        table.update()
        .where(table.c.id == "2026-08-06-bot-profiles-v2")
        .values(is_published=True)
    )
    op.drop_constraint(
        "ck_product_release_notes_change_type",
        "product_release_notes",
        type_="check",
    )
    op.drop_column("product_release_notes", "change_type")
