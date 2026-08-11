"""Structure product release notes by feature and surface.

Revision ID: c6d9f2a4b731
Revises: a0c4e8f2b691
Create Date: 2026-08-11 23:55:00.000000
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "c6d9f2a4b731"
down_revision = "a0c4e8f2b691"
branch_labels = None
depends_on = None


LEGACY_NOTE_IDS = (
    "2026-08-11-personal-name-settings",
    "2026-08-11-moderation-clarity",
    "2026-08-08-flexible-moderation-durations",
    "2026-08-06-profiles-and-bot-surfaces",
    "2026-08-02-scheduled-posts",
    "2026-07-31-mention-controls",
    "2026-07-30-reply-editor",
    "2026-07-29-temp-voice-chat",
    "2026-07-28-ai-destinations-and-history",
    "2026-07-27-safer-moderation-workflows",
    "2026-07-26-commands-replies-and-knowledge",
    "2026-07-22-messages-and-knowledge",
    "2026-07-21-access-and-bot-messaging",
    "2026-07-19-moderation-controls",
    "2026-07-17-cases-and-ai-review",
    "2026-07-14-dashboard-foundations",
)


def _at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def _note(
    note_id: str,
    published_at: datetime,
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


NOTES = [
    _note(
        "2026-08-11-member-name-preference-v2", _at(8, 11, 20), "dashboard",
        "Members", "Участники", "Choose which member name the dashboard shows", "Выберите, какое имя участника показывать",
        "The old name switcher has been replaced with one clear personal preference.",
        "Вместо непонятного переключателя теперь есть одна настройка отображения имён.",
        [("Open the person icon in the top-right corner and choose Server name or Discord @username.", "Нажмите на значок человека в правом верхнем углу и выберите имя на сервере или @имя пользователя Discord."),
         ("The choice is stored in this browser and applies throughout the dashboard.", "Выбор сохраняется в этом браузере и действует во всей панели.")],
    ),
    _note(
        "2026-08-11-action-completion-status-v2", _at(8, 11, 19, 50), "dashboard",
        "Moderation", "Модерация", "Expired actions now say “Completed”", "Завершённые наказания больше не называются отменёнными",
        "A timed mute or ban that reaches its end is now distinguished from an action reverted by a moderator.",
        "Мут или бан, срок которого истёк сам, теперь отличается от действия, отменённого модератором.",
        [("Completed means the punishment ran for its full scheduled duration.", "Статус «Завершено» означает, что наказание действовало весь назначенный срок."),
         ("Reverted is reserved for actions that a moderator ended early.", "Статус «Отменено» используется только тогда, когда модератор завершил действие досрочно.")],
        ("Open action history", "Открыть историю действий", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-08-11-rule-citations-v2", _at(8, 11, 19, 40), "dashboard",
        "Moderation", "Модерация", "Rules and reasons are now separate", "Правила и причина теперь показаны отдельно",
        "Moderation actions no longer hide a cited rule inside the reason text.",
        "В действии модерации ссылка на правило больше не прячется внутри текста причины.",
        [("The action list has a dedicated Rules column with rule names.", "В списке действий появился отдельный столбец «Правила» с названиями правил."),
         ("The action card shows the full reason, moderator commentary, and cited rules in separate sections.", "В карточке отдельно показаны полная причина, комментарий модератора и связанные правила.")],
        ("Open action history", "Открыть историю действий", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-08-11-moderation-layout-v2", _at(8, 11, 19, 30), "dashboard",
        "Moderation", "Модерация", "Moderation tables fit the way your team works", "Журнал модерации можно настроить под работу команды",
        "Long content stays readable, and optional columns can be hidden when space is limited.",
        "Длинный текст остаётся читаемым, а ненужные столбцы можно скрыть, если места мало.",
        [("Choose which columns are visible in the action log.", "Выберите, какие столбцы показывать в журнале действий."),
         ("Case details and member profiles no longer spill outside their panels on narrow screens.", "Карточки дел и профили участников больше не выходят за границы панели на узких экранах.")],
        ("Open moderation", "Открыть модерацию", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-08-08-moderation-durations-v2", _at(8, 8, 18), "both",
        "Moderation", "Модерация", "Temporary bans can last up to one year", "Временный бан можно выдать на срок до года",
        "Duration fields now accept long punishments and tell you when a value is invalid instead of changing it silently.",
        "Поля срока принимают длительные наказания и сообщают об ошибке вместо незаметной замены значения.",
        [("The same validation is used in action dialogs and moderation presets.", "Одинаковая проверка действует в окнах действий и в готовых сроках модерации.")],
        ("Open moderation settings", "Открыть настройки модерации", "/dashboard/{server_id}/moderation?tab=settings"),
    ),
    _note(
        "2026-08-06-public-profile-command-v2", _at(8, 6, 18), "bot",
        "Member profiles", "Профили участников", "Members can open their public server profile", "Участник может открыть свой профиль на сервере",
        "The profile command shows information the member is already allowed to see without exposing private moderator notes.",
        "Команда профиля показывает участнику доступные ему сведения и не раскрывает закрытые заметки модераторов.",
        [("The profile includes server details, presence, roles, and active warnings.", "В профиле видны данные сервера, статус, роли и активные предупреждения."),
         ("Cached presence is used when Discord does not provide a live status.", "Если Discord не передал текущий статус, используется последнее сохранённое значение.")],
    ),
    _note(
        "2026-08-06-bot-profiles-v2", _at(8, 6, 17, 50), "both",
        "Server setup", "Настройка сервера", "Modral and CyberColors keep separate identities", "Modral и CyberColors сохраняют разные профили",
        "Each bot now keeps its own profile, server routes, and dashboard identity.",
        "У каждого бота теперь свой профиль, свои серверы и своё оформление панели.",
        [("Opening one bot no longer sends you into the other bot's server context.", "Переход в одного бота больше не открывает серверы и страницы другого.")],
    ),
    _note(
        "2026-08-02-scheduled-posts-v2", _at(8, 2, 18), "both",
        "Scheduled posts", "Отложенные публикации", "Schedule messages and manage their next delivery", "Запланируйте сообщение и управляйте следующей отправкой",
        "Scheduled posts now have a focused workspace for timing, status, and delivery controls.",
        "У отложенных публикаций появился отдельный раздел со временем, статусом и управлением отправкой.",
        [("See when a post will be sent and pause or edit it before delivery.", "Посмотрите время следующей отправки, приостановите публикацию или измените её заранее.")],
        ("Open scheduled posts", "Открыть отложенные публикации", "/dashboard/{server_id}/replies?tab=scheduled"),
    ),
    _note(
        "2026-08-02-discord-preview-v2", _at(8, 2, 17, 50), "dashboard",
        "Bot messages", "Сообщения бота", "Preview bot messages as they will look in Discord", "Посмотрите, как сообщение будет выглядеть в Discord",
        "Message previews now render Discord formatting before you send or schedule a post.",
        "Предпросмотр показывает форматирование Discord до отправки или публикации по расписанию.",
        [("Links, mentions, timestamps, and custom emoji are rendered in the preview.", "В предпросмотре отображаются ссылки, упоминания, время и пользовательские эмодзи."),
         ("Long text is checked against Discord's message limits.", "Длинный текст проверяется с учётом ограничений Discord.")],
        ("Compose a bot message", "Создать сообщение", "/dashboard/{server_id}/replies?tab=talk"),
    ),
    _note(
        "2026-07-31-mention-delivery-v2", _at(7, 31, 18), "both",
        "Bot messages", "Сообщения бота", "Choose whether mentions notify people", "Укажите, должны ли упоминания отправлять уведомления",
        "Mention text and notification delivery can now be controlled separately.",
        "Текст упоминания и само уведомление теперь настраиваются отдельно.",
        [("User and role mentions can notify or remain silent independently.", "Упоминания пользователей и ролей можно независимо сделать обычными или беззвучными."),
         ("@everyone is available only when the sender has permission.", "@everyone доступен только отправителю с нужным разрешением.")],
        ("Compose a bot message", "Создать сообщение", "/dashboard/{server_id}/replies?tab=talk"),
    ),
    _note(
        "2026-07-30-reply-editor-v2", _at(7, 30, 18), "dashboard",
        "Automatic replies", "Автоответы", "The automatic-reply editor explains every trigger", "Редактор автоответов объясняет каждый тип триггера",
        "You can create and review a reply without learning the internal trigger model.",
        "Автоответ можно создать и проверить, не разбираясь во внутреннем устройстве триггеров.",
        [("Handwritten triggers, reusable concepts, and AI-generated variations are shown separately.", "Ручные триггеры, переиспользуемые понятия и варианты от ИИ показаны отдельно."),
         ("Language coverage and generated examples are visible before saving.", "До сохранения видно, какие языки и примеры охватывает ответ.")],
        ("Open automatic replies", "Открыть автоответы", "/dashboard/{server_id}/replies?tab=automatic"),
    ),
    _note(
        "2026-07-29-temp-voice-archives-v2", _at(7, 29, 18), "dashboard",
        "Temporary channels", "Временные каналы", "Temporary-channel archives read like Discord", "Архив временного канала выглядит как переписка в Discord",
        "Long archived conversations are easier to follow without stretching the whole page.",
        "Длинную переписку в архиве проще читать: она больше не растягивает всю страницу.",
        [("Discord references and channel links render correctly, and participant state is clearer.", "Упоминания и ссылки на каналы отображаются правильно, а статус участников легче различить.")],
        ("Open temporary channels", "Открыть временные каналы", "/dashboard/{server_id}/temp-voice"),
    ),
    _note(
        "2026-07-28-ai-tool-access-v2", _at(7, 28, 18), "both",
        "AI companion", "ИИ-помощник", "Choose which tools the AI companion may use", "Выберите инструменты, доступные ИИ-помощнику",
        "Tool access is configured separately for each server.",
        "Доступ к инструментам настраивается отдельно для каждого сервера.",
        [("Disable capabilities the companion should not use in this server.", "Отключите возможности, которые помощник не должен использовать на этом сервере.")],
        ("Open AI companion settings", "Открыть настройки ИИ-помощника", "/dashboard/{server_id}/ai?tab=companion"),
    ),
    _note(
        "2026-07-28-thread-destinations-v2", _at(7, 28, 17, 50), "both",
        "Bot messages", "Сообщения бота", "Send bot messages to threads and forum posts", "Отправляйте сообщения бота в ветки и публикации форума",
        "Message destinations now follow Discord's channel structure and ordering.",
        "Список мест отправки теперь повторяет структуру и порядок каналов в Discord.",
        [("Threads and forum posts appear alongside regular text channels.", "Ветки и публикации форума доступны рядом с обычными текстовыми каналами.")],
        ("Compose a bot message", "Создать сообщение", "/dashboard/{server_id}/replies?tab=talk"),
    ),
    _note(
        "2026-07-28-reply-cooldowns-v2", _at(7, 28, 17, 40), "both",
        "Automatic replies", "Автоответы", "Set a separate cooldown for each automatic reply", "Задайте отдельную паузу для каждого автоответа",
        "Frequently matched replies can be limited without slowing down every other reply.",
        "Частый автоответ можно ограничить, не замедляя остальные ответы.",
        [("The cooldown is edited with the reply and applies only to that reply.", "Пауза задаётся в редакторе ответа и действует только для него.")],
        ("Open automatic replies", "Открыть автоответы", "/dashboard/{server_id}/replies?tab=automatic"),
    ),
    _note(
        "2026-07-28-nickname-history-v2", _at(7, 28, 17, 30), "both",
        "Members", "Участники", "Nickname changes are saved in member history", "Изменения никнейма сохраняются в истории участника",
        "Moderators can distinguish a current server nickname from names used earlier.",
        "Модератор может отличить текущий никнейм на сервере от прежних имён.",
        [("The history records server-specific nickname changes observed by the bot.", "В историю попадают изменения никнейма на сервере, которые увидел бот.")],
        ("Open members", "Открыть участников", "/dashboard/{server_id}/users"),
    ),
    _note(
        "2026-07-27-linked-actions-v2", _at(7, 27, 18), "both",
        "Moderation", "Модерация", "Link related moderation actions", "Связывайте относящиеся друг к другу действия",
        "A mute can reference an existing warning, and moderators can find recent actions without copying identifiers.",
        "Мут можно связать с предупреждением, а недавнее действие — найти без копирования идентификатора.",
        [("Bans can also target users who have already left the server.", "Забанить можно и пользователя, который уже покинул сервер.")],
        ("Open action history", "Открыть историю действий", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-07-27-unban-delivery-v2", _at(7, 27, 17, 50), "bot",
        "Moderation", "Модерация", "The log shows whether an unban notice was delivered", "В журнале видно, доставлено ли уведомление о разбане",
        "Moderators no longer have to guess whether Discord delivered the message to the user.",
        "Модератору больше не нужно гадать, дошло ли сообщение до пользователя.",
        [("Delivery outcome is recorded with the moderation action.", "Результат отправки сохраняется вместе с действием модерации.")],
    ),
    _note(
        "2026-07-27-retention-controls-v2", _at(7, 27, 17, 40), "dashboard",
        "Privacy", "Конфиденциальность", "Set retention periods for dashboard and moderation data", "Настройте сроки хранения данных панели и модерации",
        "Old sessions and moderation records can be removed automatically on the server's schedule.",
        "Старые сессии и записи модерации могут удаляться автоматически по расписанию сервера.",
        [("Retention controls are available with the server security settings.", "Сроки хранения настраиваются в параметрах безопасности сервера.")],
        ("Open security settings", "Открыть настройки безопасности", "/dashboard/{server_id}/settings?tab=security"),
    ),
    _note(
        "2026-07-27-safe-dashboard-update-v2", _at(7, 27, 17, 30), "dashboard",
        "Dashboard updates", "Обновления панели", "Updates wait until you are ready", "Обновление панели подождёт, пока вы не будете готовы",
        "When a new dashboard version is ready, you can finish and save open work before reloading.",
        "Когда готова новая версия панели, можно сначала закончить и сохранить текущую работу.",
        [("The update prompt warns when reloading could discard unsaved form changes.", "Перед перезагрузкой панель предупреждает о возможной потере несохранённых изменений.")],
    ),
    _note(
        "2026-07-26-intent-replies-v2", _at(7, 26, 18), "both",
        "Automatic replies", "Автоответы", "Manage meaning-based replies from focused tabs", "Настраивайте смысловые автоответы в отдельных вкладках",
        "Reply intent and destination settings are easier to find and review.",
        "Настройки смысла ответа и места отправки проще найти и проверить.",
        [("Target channels are managed next to the automatic replies that use them.", "Целевые каналы настраиваются рядом с автоответами, которые их используют.")],
        ("Open automatic replies", "Открыть автоответы", "/dashboard/{server_id}/replies?tab=automatic"),
    ),
    _note(
        "2026-07-26-youtube-knowledge-v2", _at(7, 26, 17, 50), "dashboard",
        "AI knowledge", "База знаний ИИ", "Add YouTube videos and channels to server knowledge", "Добавляйте видео и каналы YouTube в базу знаний",
        "Search YouTube from the dashboard and choose what the server's AI may use.",
        "Найдите YouTube-материалы из панели и выберите, что сможет использовать ИИ сервера.",
        [("Added sources are indexed and tracked with the rest of the knowledge base.", "Добавленные источники индексируются и отображаются вместе с остальной базой знаний.")],
        ("Open AI knowledge", "Открыть базу знаний ИИ", "/dashboard/{server_id}/ai?tab=knowledge"),
    ),
    _note(
        "2026-07-26-command-visibility-v2", _at(7, 26, 17, 40), "both",
        "Access", "Доступ", "See who can use each Discord command", "Посмотрите, кому доступна каждая команда Discord",
        "Command visibility is managed from the dashboard and includes inherited rules.",
        "Доступность команд настраивается из панели с учётом унаследованных правил.",
        [("Review access by command instead of reconstructing it from internal permission keys.", "Проверьте доступ по конкретной команде, не разбирая внутренние ключи прав.")],
        ("Open command access", "Открыть доступ к командам", "/dashboard/{server_id}/rbac?tab=commands"),
    ),
    _note(
        "2026-07-26-command-reference-v2", _at(7, 26, 17, 30), "dashboard",
        "Command reference", "Справочник команд", "The command reference is localized and mobile-friendly", "Справочник команд переведён и удобен на телефоне",
        "Moderators can search the actual commands available to the bot in English or Russian.",
        "Модератор может найти реальные команды бота на русском или английском языке.",
        [("Descriptions and required access stay readable on narrow screens.", "Описания и требуемые права остаются читаемыми на узком экране.")],
        ("Open command reference", "Открыть справочник команд", "/dashboard/{server_id}/commands"),
    ),
    _note(
        "2026-07-22-announcements-and-media-v2", _at(7, 22, 18), "both",
        "Bot messages", "Сообщения бота", "Send announcements and media as the bot", "Отправляйте объявления и медиа от имени бота",
        "Bot messages can be published as Discord announcements with attached media.",
        "Сообщение бота можно опубликовать как объявление Discord и приложить медиафайл.",
        [("Delivery is recorded in the same audited messaging workflow.", "Отправка сохраняется в том же журналируемом процессе сообщений.")],
        ("Compose a bot message", "Создать сообщение", "/dashboard/{server_id}/replies?tab=talk"),
    ),
    _note(
        "2026-07-22-emoji-picker-v2", _at(7, 22, 17, 50), "dashboard",
        "Message editing", "Редактор сообщений", "Use one emoji picker across message editors", "Используйте единый выбор эмодзи в редакторах сообщений",
        "Reply and birthday-message editors now use the same searchable emoji experience.",
        "В редакторах автоответов и поздравлений теперь одинаковый поиск и выбор эмодзи.",
        [("Custom server emoji appear alongside standard emoji where they are available.", "Эмодзи сервера показываются рядом с обычными, если их можно использовать.")],
        ("Open birthday messages", "Открыть поздравления", "/dashboard/{server_id}/birthdays?tab=messages"),
    ),
    _note(
        "2026-07-22-knowledge-job-status-v2", _at(7, 22, 17, 40), "dashboard",
        "AI knowledge", "База знаний ИИ", "Knowledge jobs explain what is being indexed", "Задачи базы знаний показывают, что именно индексируется",
        "Each indexing job now shows its source and current status clearly.",
        "У каждой задачи индексации теперь понятно показаны источник и текущий статус.",
        [("Failures are easier to distinguish from work that is queued or still running.", "Ошибку проще отличить от задачи в очереди или от продолжающейся обработки.")],
        ("Open AI knowledge", "Открыть базу знаний ИИ", "/dashboard/{server_id}/ai?tab=knowledge"),
    ),
    _note(
        "2026-07-21-readable-access-v2", _at(7, 21, 18), "dashboard",
        "Access", "Доступ", "Permissions use readable names and explanations", "У прав доступа появились понятные названия и объяснения",
        "Server owners no longer have to interpret internal RBAC keys to understand access.",
        "Владельцу сервера больше не нужно расшифровывать внутренние ключи прав.",
        [("Permissions are grouped by purpose and explain the actions they allow.", "Права сгруппированы по назначению и объясняют, какие действия разрешают.")],
        ("Open access settings", "Открыть настройки доступа", "/dashboard/{server_id}/rbac?tab=assignments"),
    ),
    _note(
        "2026-07-21-send-as-bot-v2", _at(7, 21, 17, 50), "both",
        "Bot messages", "Сообщения бота", "Compose and audit messages sent as the bot", "Создавайте и проверяйте сообщения от имени бота",
        "The dashboard now has a dedicated composer for bot messages, with every send recorded.",
        "В панели появился отдельный редактор сообщений от имени бота; каждая отправка сохраняется в журнале.",
        [("Choose the destination, formatting, mentions, and attachments before sending.", "До отправки можно выбрать место, форматирование, упоминания и вложения.")],
        ("Compose a bot message", "Создать сообщение", "/dashboard/{server_id}/replies?tab=talk"),
    ),
    _note(
        "2026-07-19-action-controls-v2", _at(7, 19, 18), "dashboard",
        "Moderation", "Модерация", "Act on a moderation record without leaving the log", "Работайте с действием, не уходя из журнала",
        "Revert, linked messages, and related details are available directly from each record.",
        "Отмена, связанные сообщения и подробности доступны прямо из записи журнала.",
        [("Actions also have readable numbers and searchable autocomplete.", "У действий также появились понятные номера и поиск с автодополнением.")],
        ("Open action history", "Открыть историю действий", "/dashboard/{server_id}/moderation?tab=actions"),
    ),
    _note(
        "2026-07-19-moderation-notices-v2", _at(7, 19, 17, 50), "bot",
        "Moderation", "Модерация", "Moderation notices use one consistent format", "Уведомления о модерации оформлены единообразно",
        "Users receive a clearer explanation of the action, reason, duration, and rules they are allowed to see.",
        "Пользователь получает понятное описание действия, причины, срока и доступных ему правил.",
        [("Private moderator commentary remains inside the moderation workspace.", "Закрытый комментарий модератора остаётся только в рабочем разделе модерации.")],
    ),
    _note(
        "2026-07-19-monitoring-alert-controls-v2", _at(7, 19, 17, 40), "both",
        "Monitoring", "Мониторинг", "Pause noisy monitoring alerts", "Приостановите слишком частые уведомления мониторинга",
        "Each monitored member can use snooze and cooldown controls without disabling monitoring completely.",
        "Для участника можно настроить паузу и минимальный интервал, не отключая мониторинг полностью.",
        [("Snooze stops alerts temporarily; cooldown limits how often repeated alerts are sent.", "Пауза временно останавливает уведомления, а интервал ограничивает частоту повторов.")],
        ("Open monitoring", "Открыть мониторинг", "/dashboard/{server_id}/monitoring?tab=settings"),
    ),
    _note(
        "2026-07-17-private-case-evidence-v2", _at(7, 17, 18), "dashboard",
        "Moderation cases", "Дела модерации", "Attach private evidence to a moderation case", "Добавляйте закрытые доказательства к делу",
        "Evidence files stay private and use time-limited download links.",
        "Файлы доказательств остаются закрытыми и скачиваются по временным ссылкам.",
        [("Notes and evidence are reviewed inside the case workspace.", "Заметки и доказательства проверяются в рабочем разделе дела.")],
        ("Open moderation cases", "Открыть дела", "/dashboard/{server_id}/moderation?tab=cases"),
    ),
    _note(
        "2026-07-17-bulk-ai-review-v2", _at(7, 17, 17, 50), "dashboard",
        "AI moderation", "ИИ-модерация", "Review several AI moderation suggestions at once", "Проверяйте несколько предложений ИИ за один раз",
        "The moderation queue supports bulk approval and dismissal without opening every item.",
        "В очереди модерации можно принять или отклонить несколько предложений, не открывая каждое отдельно.",
        [("The final moderation decision still belongs to an authorized moderator.", "Окончательное решение по-прежнему принимает модератор с нужными правами.")],
        ("Open AI review queue", "Открыть очередь ИИ", "/dashboard/{server_id}/ai?tab=queue"),
    ),
    _note(
        "2026-07-17-secure-dashboard-sessions-v2", _at(7, 17, 17, 40), "dashboard",
        "Sign-in", "Вход", "Dashboard sign-in now uses server-side sessions", "Вход в панель переведён на серверные сессии",
        "Authentication state is protected by the backend instead of being trusted solely from browser storage.",
        "Состояние входа проверяется сервером, а не только данными в хранилище браузера.",
        [("Discord authorization still opens the same dashboard after sign-in.", "После авторизации Discord пользователь по-прежнему попадает в ту же панель.")],
    ),
    _note(
        "2026-07-14-overview-roles-v2", _at(7, 14, 18), "dashboard",
        "Server overview", "Обзор сервера", "Choose which roles appear in the server overview", "Выберите роли для обзора сервера",
        "Server owners can keep the overview focused on the roles their team actually uses.",
        "Владелец сервера может оставить в обзоре только те роли, которые действительно нужны команде.",
        [("Role visibility is configured in the Overview section of server settings.", "Отображение ролей настраивается в разделе «Обзор» настроек сервера.")],
        ("Open overview settings", "Открыть настройки обзора", "/dashboard/{server_id}/settings?tab=overview"),
    ),
    _note(
        "2026-07-14-bilingual-moderation-v2", _at(7, 14, 17, 50), "dashboard",
        "Localization", "Локализация", "Moderation workflows are available in English and Russian", "Разделы модерации доступны на русском и английском",
        "Core moderation pages, action labels, and status text now follow the dashboard language.",
        "Основные страницы модерации, названия действий и статусы теперь соответствуют языку панели.",
        [("The layout also remains usable at narrow browser widths.", "Интерфейс остаётся удобным и при небольшой ширине окна.")],
        ("Open language settings", "Открыть настройки языка", "/dashboard/{server_id}/settings?tab=localization"),
    ),
]


def upgrade() -> None:
    op.add_column(
        "product_release_notes",
        sa.Column("surface", sa.String(length=16), server_default="both", nullable=False),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("feature_en", sa.String(length=100), server_default="Product", nullable=False),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("feature_ru", sa.String(length=100), server_default="Продукт", nullable=False),
    )
    op.add_column("product_release_notes", sa.Column("action_label_en", sa.String(length=120), nullable=True))
    op.add_column("product_release_notes", sa.Column("action_label_ru", sa.String(length=120), nullable=True))
    op.add_column("product_release_notes", sa.Column("action_path", sa.String(length=300), nullable=True))
    op.create_check_constraint(
        "ck_product_release_notes_surface",
        "product_release_notes",
        "surface IN ('dashboard', 'bot', 'both')",
    )

    table = sa.table(
        "product_release_notes",
        sa.column("id", sa.String),
        sa.column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.column("title_en", sa.String),
        sa.column("title_ru", sa.String),
        sa.column("summary_en", sa.Text),
        sa.column("summary_ru", sa.Text),
        sa.column("surface", sa.String),
        sa.column("feature_en", sa.String),
        sa.column("feature_ru", sa.String),
        sa.column("action_label_en", sa.String),
        sa.column("action_label_ru", sa.String),
        sa.column("action_path", sa.String),
        sa.column("changes", sa.JSON),
        sa.column("is_published", sa.Boolean),
    )
    bind = op.get_bind()
    bind.execute(
        table.update().where(table.c.id.in_(LEGACY_NOTE_IDS)).values(is_published=False)
    )
    op.bulk_insert(table, NOTES)

    op.alter_column("product_release_notes", "surface", server_default=None)
    op.alter_column("product_release_notes", "feature_en", server_default=None)
    op.alter_column("product_release_notes", "feature_ru", server_default=None)


def downgrade() -> None:
    table = sa.table(
        "product_release_notes",
        sa.column("id", sa.String),
        sa.column("is_published", sa.Boolean),
    )
    bind = op.get_bind()
    bind.execute(table.delete().where(table.c.id.in_([note["id"] for note in NOTES])))
    bind.execute(
        table.update().where(table.c.id.in_(LEGACY_NOTE_IDS)).values(is_published=True)
    )

    op.drop_constraint("ck_product_release_notes_surface", "product_release_notes", type_="check")
    op.drop_column("product_release_notes", "action_path")
    op.drop_column("product_release_notes", "action_label_ru")
    op.drop_column("product_release_notes", "action_label_en")
    op.drop_column("product_release_notes", "feature_ru")
    op.drop_column("product_release_notes", "feature_en")
    op.drop_column("product_release_notes", "surface")
